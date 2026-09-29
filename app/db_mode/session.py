"""NL -> SQL -> answer pipeline for Database mode.

Deliberately NOT built as a tool-calling agent loop (unlike Code mode's CodeSession):
tool-calling support is inconsistent across local runtimes (Ollama, LM Studio,
llama.cpp's server, ...) and unreliable on small models. Instead this is a plain
three-step pipeline that only needs structured JSON text output, which every
LocalLLMProvider already supports for classify():

  1. Ask the local model for one SQL SELECT statement, given the DB's schema and the
     user's question (JSON-format output: {"sql": "..."}).
  2. Validate it's read-only and run it against the file (opened via a read-only
     SQLite URI, so even a bug here can't write to the file).
  3. Ask the local model to phrase a short natural-language answer from the rows.

One repair attempt is made if step 2's query fails, feeding the error back to the
model. No MCP server is involved — this process already owns both the LLM call and
the SQLite connection, so there's nothing an external tool protocol would add here.
"""

import json
import re
import sqlite3
from pathlib import Path

from app.llm_providers.factory import get_provider

MAX_ROWS = 200
MAX_PREVIEW_ROWS = 20

SQL_SYSTEM_PROMPT = """You translate a user's natural-language question into exactly one SQLite
SELECT query against the schema given below. Respond ONLY with JSON matching the schema
{"sql": "<the query>"}. Do not include any other text.

Rules:
- Only a single SELECT (or a SELECT built on a WITH clause) statement — never
  INSERT/UPDATE/DELETE/DROP/ALTER/ATTACH/PRAGMA/CREATE/REPLACE.
- No semicolons, no comments, no markdown code fences — just the raw SQL as the "sql" value.
- Use only the tables/columns that appear in the schema below.
- Prefer aggregate functions (SUM, COUNT, AVG, GROUP BY) when the question asks for a total,
  count, average, or breakdown by some column.
- If the question is ambiguous, make the most reasonable interpretation and still return a
  single query — never ask a follow-up question.
"""

SQL_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}

ANSWER_SYSTEM_PROMPT = """You are given a user's question, the SQL query that was run against a
local SQLite database, and the resulting rows. Write a short, direct natural-language answer to
the question using only these results — 1 to 3 sentences, no SQL, no preamble like "Based on the
query". If the results are empty, say so plainly."""

_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|pragma|replace|create|vacuum|reindex)\b",
    re.IGNORECASE,
)


class DBSession:
    def __init__(self, db_path: str):
        path = Path(db_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"'{db_path}' is not a file.")
        self.db_path = path
        self._schema_text = self._load_schema()

    # ---- public API used by app/api.py -------------------------------------

    def ask(self, question: str) -> dict:
        provider = get_provider()

        sql, _ = self._generate_sql(provider, question)
        columns, rows, error = self._try_execute(sql)

        if error is not None:
            sql, _ = self._generate_sql(provider, question, prior_sql=sql, error=error)
            columns, rows, error = self._try_execute(sql)
            if error is not None:
                return {"ok": False, "error": f"Couldn't run a valid query: {error}", "sql": sql}

        answer = self._summarize(provider, question, sql, columns, rows)
        return {"ok": True, "sql": sql, "columns": columns, "rows": rows, "answer": answer}

    # ---- internals ------------------------------------------------------------

    def _ro_uri(self) -> str:
        return f"{self.db_path.as_uri()}?mode=ro"

    def _load_schema(self) -> str:
        conn = sqlite3.connect(self._ro_uri(), uri=True)
        try:
            rows = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        return "\n\n".join(row[0] for row in rows)

    def _generate_sql(self, provider, question: str, prior_sql: str | None = None, error: str | None = None):
        user = f"Schema:\n{self._schema_text}\n\nQuestion: {question}"
        if prior_sql:
            user += (
                f"\n\nYour previous query failed:\n{prior_sql}\nError: {error}\n"
                "Return a corrected query."
            )
        raw = provider.chat(
            system=SQL_SYSTEM_PROMPT,
            user=user,
            json_schema=SQL_RESPONSE_FORMAT,
            temperature=0,
            num_predict=300,
        )
        return self._extract_sql(raw), raw

    @staticmethod
    def _extract_sql(raw: str) -> str:
        try:
            parsed = json.loads(raw)
            sql = str(parsed.get("sql", "")).strip()
            if sql:
                return sql.rstrip(";").strip()
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
        match = re.search(r"((?:select|with)\b.*)", raw or "", re.IGNORECASE | re.DOTALL)
        return match.group(1).strip().rstrip(";").strip() if match else (raw or "").strip()

    @staticmethod
    def _validate(sql: str) -> None:
        if not sql or not sql.strip():
            raise ValueError("The model didn't return a query.")
        if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
            raise ValueError("Only SELECT queries are allowed.")
        if ";" in sql:
            raise ValueError("Only a single statement is allowed.")
        if _FORBIDDEN_RE.search(sql):
            raise ValueError("Query contains a disallowed keyword.")

    def _try_execute(self, sql: str):
        try:
            self._validate(sql)
            columns, rows = self._execute(sql)
            return columns, rows, None
        except (ValueError, sqlite3.Error) as exc:
            return None, None, str(exc)

    def _execute(self, sql: str):
        conn = sqlite3.connect(self._ro_uri(), uri=True)
        try:
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [list(r) for r in cursor.fetchmany(MAX_ROWS)]
            return columns, rows
        finally:
            conn.close()

    def _summarize(self, provider, question, sql, columns, rows) -> str:
        preview = self._rows_to_text(columns, rows)
        try:
            text = provider.chat(
                system=ANSWER_SYSTEM_PROMPT,
                user=f"Question: {question}\n\nSQL used: {sql}\n\nResults:\n{preview}",
                temperature=0.2,
                num_predict=200,
            ).strip()
            return text or "(no answer returned)"
        except Exception:
            return "Query ran successfully — see the table above (the local model couldn't summarize it)."

    @staticmethod
    def _rows_to_text(columns, rows, max_rows: int = MAX_PREVIEW_ROWS) -> str:
        if not rows:
            return "(no rows)"
        lines = [", ".join(columns)]
        for row in rows[:max_rows]:
            lines.append(", ".join("NULL" if v is None else str(v) for v in row))
        if len(rows) > max_rows:
            lines.append(f"... ({len(rows)} rows total)")
        return "\n".join(lines)
