"""SQLite access layer. One connection per call (fine at this scale/concurrency)."""

import sqlite3
from contextlib import contextmanager

from app.config import DB_PATH, SCHEMA_PATH


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Small additive migrations for columns added after a DB file already existed.
    CREATE TABLE IF NOT EXISTS in schema.sql only helps brand-new databases."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(chats)")}
    if "kind" not in columns:
        conn.execute(
            "ALTER TABLE chats ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'"
        )
    if "folder_path" not in columns:
        conn.execute("ALTER TABLE chats ADD COLUMN folder_path TEXT")
    if "title_set_by_user" not in columns:
        conn.execute(
            "ALTER TABLE chats ADD COLUMN title_set_by_user INTEGER NOT NULL DEFAULT 0"
        )

    query_columns = {row["name"] for row in conn.execute("PRAGMA table_info(queries)")}
    if "sql_query" not in query_columns:
        conn.execute("ALTER TABLE queries ADD COLUMN sql_query TEXT")
    if "result_json" not in query_columns:
        conn.execute("ALTER TABLE queries ADD COLUMN result_json TEXT")

    _migrate_chats_kind_check(conn)


def _migrate_chats_kind_check(conn: sqlite3.Connection) -> None:
    """SQLite bakes CHECK constraints into a table's definition and won't let ALTER
    TABLE touch them, so a chats table created before 'database' was a valid kind
    (Database mode) needs to be rebuilt — new table, copy rows, swap — rather than
    altered in place.

    Builds the replacement under a temporary name and renames it into 'chats' only
    at the very end (rather than renaming the original table out of the way first)
    so queries.chat_id's `REFERENCES chats(id)` is never left dangling: SQLite
    rewrites *other* tables' foreign-key text when the table they reference gets
    renamed, which would otherwise repoint 'queries' at a table this function is
    about to drop."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chats'"
    ).fetchone()
    if row is None or row["sql"] is None or "'database'" in row["sql"]:
        return  # brand-new table (already has it) or nothing to migrate

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """
        CREATE TABLE chats_new (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email         TEXT NOT NULL REFERENCES users(email),
            title              TEXT NOT NULL DEFAULT 'Default Chat',
            kind               TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat', 'code', 'database')),
            folder_path        TEXT,
            title_set_by_user  INTEGER NOT NULL DEFAULT 0,
            created_at         TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        INSERT INTO chats_new (id, user_email, title, kind, folder_path, title_set_by_user, created_at)
        SELECT id, user_email, title, kind, folder_path, title_set_by_user, created_at FROM chats
        """
    )
    conn.execute("DROP TABLE chats")
    conn.execute("ALTER TABLE chats_new RENAME TO chats")
    conn.execute("PRAGMA foreign_keys = ON")


def get_first_user_email() -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT email FROM users ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return row["email"] if row else None


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT email, created_at FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_default_chat_id(user_email: str) -> int | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM chats WHERE user_email = ? AND kind = 'chat' ORDER BY created_at ASC LIMIT 1",
            (user_email,),
        ).fetchone()
        return row["id"] if row else None


def create_user_with_default_chat(email: str) -> int:
    """Inserts the user (idempotent) and their one Phase-1 default chat. Returns chat_id."""
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (email) VALUES (?)",
            (email,),
        )
        existing = conn.execute(
            "SELECT id FROM chats WHERE user_email = ? AND kind = 'chat' ORDER BY created_at ASC LIMIT 1",
            (email,),
        ).fetchone()
        if existing:
            return existing["id"]

        cursor = conn.execute(
            "INSERT INTO chats (user_email, title, kind) VALUES (?, 'Default Chat', 'chat')",
            (email,),
        )
        return cursor.lastrowid


def create_chat(
    user_email: str, title: str = "New Chat", kind: str = "chat", folder_path: str | None = None
) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO chats (user_email, title, kind, folder_path) VALUES (?, ?, ?, ?)",
            (user_email, title, kind, folder_path),
        )
        return cursor.lastrowid


def list_chats(user_email: str, kind: str = "chat") -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.folder_path, c.created_at,
                   (SELECT MAX(timestamp) FROM queries q WHERE q.chat_id = c.id) AS last_activity
            FROM chats c
            WHERE c.user_email = ? AND c.kind = ?
            ORDER BY COALESCE(last_activity, c.created_at) DESC
            """,
            (user_email, kind),
        ).fetchall()
        return [dict(row) for row in rows]


def get_chat(chat_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None


def chat_belongs_to_user(chat_id: int, user_email: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM chats WHERE id = ? AND user_email = ?",
            (chat_id, user_email),
        ).fetchone()
        return row is not None


def rename_chat(chat_id: int, title: str, by_user: bool = True) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE chats SET title = ?, title_set_by_user = ? WHERE id = ?",
            (title, 1 if by_user else 0, chat_id),
        )


def get_chat_history(chat_id: int) -> list[dict]:
    """Ordered, successful turns for a chat — used both to reconstruct multi-turn Claude
    history and to re-render a chat's messages when the frontend switches to it."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT input_prompt, output_response, classification, model_used,
                   input_tokens, output_tokens, cost_usd, latency_ms, timestamp,
                   sql_query, result_json
            FROM queries
            WHERE chat_id = ? AND status = 'ok'
            ORDER BY timestamp ASC, id ASC
            """,
            (chat_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def log_query(
    *,
    chat_id: int,
    user_email: str,
    input_prompt: str,
    output_response: str | None = None,
    classification: str | None = None,
    classification_raw: str | None = None,
    model_used: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
    status: str = "ok",
    error_message: str | None = None,
    sql_query: str | None = None,
    result_json: str | None = None,
) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO queries (
                chat_id, user_email, input_prompt, output_response,
                classification, classification_raw, model_used,
                input_tokens, output_tokens, cost_usd, latency_ms,
                status, error_message, sql_query, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                user_email,
                input_prompt,
                output_response,
                classification,
                classification_raw,
                model_used,
                input_tokens,
                output_tokens,
                cost_usd,
                latency_ms,
                status,
                error_message,
                sql_query,
                result_json,
            ),
        )
        return cursor.lastrowid


def total_cost_for_user(user_email: str) -> float:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM queries WHERE user_email = ?",
            (user_email,),
        ).fetchone()
        return row["total"]
