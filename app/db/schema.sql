CREATE TABLE IF NOT EXISTS users (
    email      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chats (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email         TEXT NOT NULL REFERENCES users(email),
    title              TEXT NOT NULL DEFAULT 'Default Chat',
    kind               TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat', 'code', 'database')),
    folder_path        TEXT,       -- kind='code': the sandboxed root folder; kind='database': the .db file path
    title_set_by_user  INTEGER NOT NULL DEFAULT 0,  -- 0 = still auto-titled, 1 = user renamed it
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS queries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id             INTEGER NOT NULL REFERENCES chats(id),
    user_email          TEXT NOT NULL REFERENCES users(email),
    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
    input_prompt        TEXT NOT NULL,
    output_response     TEXT,
    classification      TEXT CHECK (classification IS NULL OR classification IN ('easy','medium','complex')),
    classification_raw  TEXT,
    model_used          TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cost_usd            REAL,
    latency_ms          INTEGER,
    status               TEXT NOT NULL DEFAULT 'ok',
    error_message        TEXT,
    sql_query            TEXT,   -- Database mode: the generated SQL for this turn
    result_json           TEXT   -- Database mode: JSON {"columns": [...], "rows": [...]}
);

CREATE INDEX IF NOT EXISTS idx_queries_chat_id    ON queries(chat_id);
CREATE INDEX IF NOT EXISTS idx_queries_user_email ON queries(user_email);
CREATE INDEX IF NOT EXISTS idx_queries_timestamp  ON queries(timestamp);
