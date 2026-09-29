# Local "Router" Agent — Implementation Plan

## Context

The goal is a local desktop chat app that routes each user prompt to a cost-appropriate Claude model, using a **local LLM as a difficulty classifier** so cheap Haiku calls handle easy questions and expensive Opus calls are reserved for genuinely hard ones. This is a cost-optimization + UX experiment: measuring per-query token cost is central to proving the router is actually saving money over "always call Opus." Phase 1 builds the smallest end-to-end version of this (single chat, single-turn, full cost logging); later phases (multi-chat history, a Claude-Code-style file-editing mode, response caching, and eventually fine-tuning a local model on the accumulated query log) build on top of it without requiring a rewrite.

The project directory (`/Users/sujoychakraborty/projects-2/AI_Agent/5_Router_agent`) is currently empty — this is a from-scratch build, not a refactor.

**Confirmed decisions:**

- Stack: **Python** backend, **pywebview** for the native desktop window, plain HTML/JS frontend (no heavy framework needed for a chat UI).
- Local classifier: **Ollama** (already installed, v0.34.0) running **`qwen3.5:4b`** (already pulled) via its local HTTP API — classification never leaves the machine.
- Database: **SQLite** (single local file) — this is a single-user local app, no need for a server-based DB.
- Anthropic API key: stored in a local `.env` file (gitignored); user pastes it in once.
- Claude models and pricing (verified current): `claude-haiku-4-5` ($1/$5 per MTok in/out) for **easy**, `claude-sonnet-5` ($2/$10 per MTok) for **medium**, `claude-opus-5` ($5/$25 per MTok) for **complex**.

---

## How token usage / cost will be measured

Every Anthropic Messages API response includes a `usage` object with `input_tokens` and `output_tokens` (and cache-related fields, unused in Phase 1). Cost per call is computed directly from that object against a static per-model price table:

```python
MODEL_PRICING = {
    "claude-haiku-4-5": {"input": 1.0,  "output": 5.0},   # $ per 1M tokens
    "claude-sonnet-5":  {"input": 2.0,  "output": 10.0},
    "claude-opus-5":    {"input": 5.0,  "output": 25.0},
}

def compute_cost(model_id, input_tokens, output_tokens):
    p = MODEL_PRICING[model_id]
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]
```

This cost, plus the raw token counts, classification, and model used, is written to the `queries` table on every call (see schema below) — so total spend, spend-by-classification, and spend-by-user are all just SQL aggregates over that table once data accumulates. No external billing API is needed for Phase 1.

---

## Phase 1 — Implementation Plan

### Project structure

```
5_Router_agent/
├── .env                    # ANTHROPIC_API_KEY=... (gitignored)
├── .env.example
├── .gitignore              # .env, data/*.db, __pycache__/
├── requirements.txt        # pywebview, anthropic, requests, python-dotenv
├── main.py                 # entry point: init DB, build Api, launch pywebview window
├── app/
│   ├── config.py           # loads .env; model map; ollama host/model constants; db path
│   ├── api.py               # Api class exposed to the frontend via pywebview's js_api bridge
│   ├── classifier.py         # Ollama call + prompt template + JSON parsing + fallback
│   ├── router.py               # classification -> Claude model id mapping
│   ├── claude_client.py          # wraps the anthropic SDK call, extracts usage
│   ├── pricing.py                 # MODEL_PRICING table + compute_cost()
│   ├── errors.py                    # OllamaUnavailableError, etc.
│   └── db/
│       ├── schema.sql                # DDL (CREATE TABLE IF NOT EXISTS)
│       └── database.py                # sqlite3 connection + init_db() + CRUD helpers
├── frontend/
│   ├── index.html           # chat shell + first-run email modal
│   ├── styles.css
│   └── app.js                # renders chat, calls window.pywebview.api.*, first-run modal logic
└── data/
    └── router_agent.db      # created at runtime; gitignored
```

No FastAPI/web-server layer in Phase 1 — pywebview's built-in JS-API bridge (`window.pywebview.api.*`) is simpler for a single-window local app (no port management, no CORS, and pywebview already runs each API call off the main thread so long Claude calls don't freeze the UI). This can be added later without touching `app/`'s business logic if Phase 2+ needs streaming.

### Database schema (SQLite)

Two things worth deciding now to avoid rework in Phase 2: add a `chats` table even though multi-chat UI doesn't exist yet (Phase 1 just auto-creates one "Default Chat" per user), and make `queries` an append-only wide log (one row per turn) rather than splitting user/assistant into separate message rows — simpler, and sufficient until Phase 2 needs to reconstruct multi-turn history.

```sql
CREATE TABLE IF NOT EXISTS users (
    email      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL REFERENCES users(email),
    title      TEXT NOT NULL DEFAULT 'Default Chat',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS queries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id             INTEGER NOT NULL REFERENCES chats(id),
    user_email          TEXT NOT NULL REFERENCES users(email),
    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
    input_prompt        TEXT NOT NULL,
    output_response     TEXT,
    classification      TEXT CHECK (classification IS NULL OR classification IN ('easy','medium','complex')),
    classification_raw  TEXT,       -- raw Ollama output, kept for future prompt tuning
    model_used           TEXT,
    input_tokens          INTEGER,
    output_tokens          INTEGER,
    cost_usd                REAL,
    latency_ms                INTEGER,
    status                     TEXT NOT NULL DEFAULT 'ok',  -- 'ok' | 'error'
    error_message               TEXT
);

CREATE INDEX IF NOT EXISTS idx_queries_chat_id    ON queries(chat_id);
CREATE INDEX IF NOT EXISTS idx_queries_user_email ON queries(user_email);
CREATE INDEX IF NOT EXISTS idx_queries_timestamp  ON queries(timestamp);
```

`database.py` runs this DDL on every launch (idempotent) — no migration framework needed at this scale.

### Classifier design (Ollama / qwen3.5:4b)

Use Ollama's structured-output support (`format` as a JSON schema on `/api/chat`) so the model's sampling is constrained to the three-label enum, rather than hoping a 4B model free-texts exactly one word. Call with `temperature: 0`, a short `num_predict`, and explicit connect/read timeouts (never an unbounded call).

System prompt (with few-shot examples) instructs the model to classify into `easy` / `medium` / `complex` — easy: greetings, simple lookups, trivial snippets; medium: standard code/debugging, multi-step explanations, moderate summaries; complex: architecture/design questions, large multi-file code changes, deep tradeoff analysis, long-form structured writing.

Parsing has three layers of defense: (1) the JSON-schema-constrained response, (2) a regex/keyword fallback if JSON parsing fails, (3) default to `"medium"` if nothing matches a valid label — the safe middle ground on both cost and quality. The raw Ollama output is always stored in `classification_raw` for later prompt iteration. Realistic expectation: a 4B local model doing subjective 3-way classification will be noisy (roughly 65–80% agreement with human judgment), with easy-vs-not-easy being the more reliable split than medium-vs-complex — acceptable for Phase 1, and something to revisit once real usage data exists.

### Backend request flow

1. Frontend: user submits prompt → input disabled → `window.pywebview.api.send_message(prompt)`.
2. `Api.send_message`, wrapped in one top-level try/except:
   - Classify via `classifier.classify(prompt)`. If Ollama is unreachable, return a distinct error immediately and log a `status='error'` row (no silent hang — health-check `/api/tags` on startup and surface a clear "start Ollama" banner if it's down).
   - Map classification → model via `router.CLASSIFICATION_TO_MODEL`.
   - Call Claude via `claude_client.send(model_id, prompt)`, catching `AuthenticationError`, `RateLimitError`, `APIConnectionError`, `APIStatusError` individually so each surfaces a specific, human-readable message rather than a generic failure.
   - On success: compute `cost_usd` from `response.usage`, measure latency, log the full row to `queries`, and return `{input, output, classification, model_used, cost_usd, input_tokens, output_tokens}` to the frontend.
3. Frontend renders the user bubble and an assistant bubble tagged with the model name and cost, or a distinct error bubble on failure; re-enables input in a `finally`.

Phase 1 sends a **single-turn** message to Claude (no prior conversation history) — deliberate scope-limiting; Phase 2 adds history without a schema change (see roadmap below).

### Frontend & first-run email capture

Plain HTML/CSS/JS: a scrollable message list, an input row, and a first-run modal. On `pywebviewready`, the frontend calls `get_bootstrap_state()`; if no row exists in `users`, it shows the email modal (client-side regex check) before enabling chat. Submitting the email calls `Api.save_email(email)`, which inserts into `users`, creates the one default row in `chats`, caches `current_user_email`/`current_chat_id` on the `Api` instance for the session, and unblocks the chat UI. On subsequent launches the modal is skipped entirely.

### Key risks to handle explicitly

- Ollama not running or model not pulled → clear banner with the exact fix (`ollama serve` / `ollama pull qwen3.5:4b`), never a silent hang.
- Missing `ANTHROPIC_API_KEY` → don't crash; show an inline prompt/settings panel to paste it, writing to `.env`.
- Malformed classifier output → three-layer fallback described above, always logged.
- Anthropic API errors → caught per-exception-type with specific messaging, full error text kept in `error_message`.

### Verification (end-to-end)

1. `ollama serve` running, `qwen3.5:4b` present (`ollama list`); `.env` populated with a real `ANTHROPIC_API_KEY`.
2. `pip install -r requirements.txt && python main.py` — window opens, first-run email modal appears, submitting an email persists a `users` + `chats` row (spot-check via `sqlite3 data/router_agent.db "select * from users; select * from chats;"`).
3. Send an obviously easy prompt ("hi") → confirm it classifies `easy` and the response is tagged `claude-haiku-4-5`; send a clearly complex prompt (e.g. "design a distributed rate limiter with failure-mode tradeoffs") → confirm `complex`/`claude-opus-5`. Check `classification_raw` in the DB to see what Ollama actually returned.
4. Confirm `queries` rows have non-null `input_tokens`, `output_tokens`, `cost_usd` matching the pricing formula, and that `SELECT SUM(cost_usd) FROM queries` gives a sane running total.
5. Stop Ollama (`kill` the process or stop the app) and send a prompt → confirm a clear error banner appears instead of a hang, and an error row is logged.
6. Remove/blank the API key and send a prompt → confirm a clear "missing/invalid API key" message rather than a crash.

---

## Roadmap for Phases 2–5 (high-level; to be planned in detail after Phase 1 is built and used)

\*\*Phase 1.5 — if claude asks for permission or has quesrions, those will be reflcted on the webviewer window so that the user can answer to those questions and the webviewer can undewrstand the responses and pass the reponsse to claude accordingly. Similartly for multiple questions (from claude)

**Phase 2 — Multiple chats + conversation history.** The `chats` table already exists, so this is additive: a "New Chat" UI action inserts a new `chats` row; a chat-switcher lists chats by `user_email`; sending a message reconstructs prior turns from `queries WHERE chat_id = ? ORDER BY timestamp` into a multi-turn `messages=[...]` array passed to `client.messages.create()`. Per-turn classification stays unchanged (classify each new message independently, still against just that message — decide later whether classification should also consider prior context). Worth watching: growing context cost as history lengthens — may want prompt caching (`cache_control`) once conversations get long. use local LLM to rename every new chat - local agent should be able to understand the prompt (which it already does during classification) and then rename the chat on left hand bar - for both 'chat' section and 'code' section. also allow a 'three' dots for each chat for the user to be able to rename it.when select a area to be copied and then right click - i dont see copy option (image). fix that. i should be able to copy a selected part. also add a 'full text' copy option.

**Phase 3 — "Code" mode (folder access, like Claude Code).** A second UI section where the user picks a local folder (native folder-picker via pywebview); the backend gets read/write access scoped to that folder and the LLM is given file tools (read/write/list, likely via the Anthropic tool-use loop rather than free-text) to act on it. This is a much bigger scope increase (sandboxing which paths are writable, diff/approval UX before writes, tool-use loop instead of a single `messages.create()` call) and deserves its own detailed plan once Phase 1/2 are stable — flagging now only that the DB schema and `Api` class should stay agent-agnostic enough that a second "mode" can plug in without a rewrite.add a 'model selection' dropdown on the webviewer and list the three models Haiku, Sonnet, Claude, and Auto - so that the user can select which model it wants to use specifically. Default should be 'auto' - where the local classifier determines which model should be selected. But if user selectes a specific model, then classifier should be skipped and webviewer should directly call claude with the selected model.
i want this tool to be - 1. uploadable to git in a public repo so that anyone can download, install and run it lcoally. 2. there should be flexibility of the user to connect it not only to QWEN, but any other local model downloaded on their local machine/server 3. so tell me what changes do you need to make in the current architecture? give me the high level steps. 4. Alomng side chat and code, create anew sction for 'database'. This section will allow chats with teh local SQLite database. I will need the local LLM to be able to connect to the sqlite databse and pull data from sqlite in natural language. For eg in that 'database' section, in a new chat, if i ask - how much was the cost per model - the lcoal LLM should be able to understand that, create a query into the SQLITE database and pul the fdata acordinly. Tell me if i need to build a MCP or anythinh else for the local LLM tro be able to connect to the local sqlite inside ythe project fodler

**Phase 4 — Response caching from logged history.** A separate program reads `queries`, builds a similarity index (likely embeddings) over `input_prompt` → `output_response` pairs, and on a new query checks for a close match before hitting the classifier/Claude at all. The tricky part flagged in the request — detecting when a "similar" query is actually a _repeat_ signaling the cached answer was wrong, versus a genuinely fine cache hit — needs a concrete decision rule (e.g. a similarity threshold plus an explicit "wasn't helpful"/re-ask signal from the user) before implementation; that's a design question for when this phase is actually scoped.

**Phase 5 — Fine-tuning a local model on accumulated query/response history.** A separate offline training script (Python, likely LoRA/PEFT fine-tuning) that exports `queries` (prompt + accepted response, probably filtered to "ok" status and maybe weighted by which classification tier) into a training set and fine-tunes a local model — most plausibly used to _improve the local classifier itself_ (a router purpose-tuned on this user's actual prompt distribution) rather than to replace Claude outright. Needs enough accumulated data from Phases 1–4 before it's worth scoping in detail.

Phases 2–5 are intentionally not spec'd file-by-file here — each is a large enough scope change that it should get its own focused plan once Phase 1 is running and real usage/cost data exists to inform the decisions above (e.g. whether qwen3.5:4b's classifier accuracy is good enough as-is, or needs prompt iteration before Phase 5's fine-tuning is even useful).
