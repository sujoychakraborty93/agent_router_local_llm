# Router Agent

A local desktop chat app that classifies each prompt's difficulty with a **local** LLM, then
routes it to the cheapest Claude model that can handle it:

| Classification | Model | Price (in/out per MTok) |
|---|---|---|
| easy | `claude-haiku-4-5` | $1 / $5 |
| medium | `claude-sonnet-5` | $2 / $10 |
| complex | `claude-opus-5` | $5 / $25 |

Every query is logged to a local SQLite database (`data/router_agent.db`) with the prompt,
response, classification, model used, token counts, and computed cost.

## Prerequisites

- Python 3.10+.
- A GUI toolkit for [pywebview](https://pywebview.flowrl.com/) to render its window:
  - **macOS**: nothing extra — uses the built-in Cocoa/WebKit.
  - **Windows**: nothing extra on Windows 10/11 — uses the pre-installed WebView2 runtime.
  - **Linux**: install GTK's WebKit bindings first, e.g. on Debian/Ubuntu:
    `sudo apt install python3-gi gir1.2-webkit2-4.1`.
- A local LLM runtime — any ONE of:
  - [Ollama](https://ollama.com) (the default), or
  - [LM Studio](https://lmstudio.ai), llama.cpp's `server`, vLLM, text-generation-webui, or
    anything else exposing an OpenAI-compatible chat API.

  See **Using a different local model** below to point the app at whichever you pick.

## Setup

1. Start your local LLM runtime. With the default (Ollama):
   ```
   ollama serve
   ollama pull qwen3.5:4b
   ```
2. Create a virtualenv and install dependencies:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and put in your real Anthropic API key (you can also paste it
   into the app's Settings (gear icon) instead, which writes to the same file):
   ```
   cp .env.example .env
   ```
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
4. Run it:
   ```
   python main.py
   ```

On first launch you'll be asked for your email (no password — just a local label). After that,
type a prompt and send it; the response bubble is tagged with the classification, model used,
cost, and latency for that call.

## Using a different local model

The local model is used for three things: classifying prompt difficulty, generating chat
titles, and Database mode (below). It isn't tied to Qwen or Ollama — any model you've loaded
into a supported runtime works.

- **Any Ollama model**: set `LOCAL_LLM_MODEL` in `.env` (or in Settings → Local model) to
  whatever you've pulled, e.g. `llama3.1:8b`, `mistral:7b`, `gemma2:9b`.
- **A non-Ollama runtime** (LM Studio, llama.cpp's `server`, vLLM, text-generation-webui, ...):
  set `LOCAL_LLM_PROVIDER=openai_compat` and `LOCAL_LLM_BASE_URL` to that server's API base
  (e.g. `http://localhost:1234/v1` for LM Studio's default), and `LOCAL_LLM_MODEL` to the model
  name it reports.

All of this is also editable from the app itself: click the gear icon → **Local model** →
pick a runtime, base URL, and model (the ⟳ button discovers what's currently available there),
then Save. No restart needed.

## Multiple chats (Phase 2)

The sidebar lists your chats. Click **+** to start a new one, or click any chat to switch to it —
switching reloads that chat's full history and re-renders it. Each new message you send is sent
to Claude along with that chat's prior turns (reconstructed from the `queries` table), so Claude
has real conversation context, not just the latest message. Classification still runs per-message
against just the new text.

## Code mode (Phase 3)

Click **Code** in the header to switch modes, then **Choose Folder…** to pick a local project
folder via the native file dialog. Claude gets four tools scoped to that folder:

- `list_files` / `read_file` — run immediately, no approval needed (read-only).
- `write_file` — never runs immediately. It shows you a unified diff and pauses; nothing
  touches disk until you click **Approve & Write** or **Reject** on that specific change.
- `ask_questions` — lets Claude pause and ask you one or more multiple-choice questions when
  it needs a decision only you can make (which approach, which file, a naming/scope choice),
  as opposed to permission to write a file. Each question renders as radio buttons (or
  checkboxes if it allows multiple answers), plus a free-form "Other" option; a batch of
  questions all show at once with one **Submit Answers** button, enabled once every question
  has an answer.

Either kind of pause disables the input box (placeholder changes to say so) and posts a
"⏳ Waiting for your input…" notice in the conversation, so it's clear the task is blocked on
you — a new message is rejected (by the backend, not just the UI) until every pending write and
question from that turn is resolved.

All file access is sandboxed to the chosen folder — a path that would resolve outside it (via
`..` or an absolute path) is rejected before touching the filesystem. The task's initial prompt
is classified the same way as normal chat, so the model (and its cost) still scales with how
hard the task looks; the same model then services the whole tool-use loop for that task,
including any turns after you resolve a pending write or question. Each *completed* task (not
every intermediate pending round-trip) is logged to `queries` under a `Code: <folder>` chat, so
cost tracking covers Code mode too.

## Database mode (Phase 4)

Click **Database** in the header. **Use App Data** opens a chat against this app's own
`data/router_agent.db` — the common case, since that's where every prompt/response/cost/model
is already logged (e.g. ask *"how much was the cost per model"* or *"what's my most expensive
chat"*). **Choose .db File…** points a new chat at any other SQLite file instead, via the native
file dialog.

Each question runs a three-step pipeline, entirely on your local model (no Anthropic call, no
cost):

1. The model is given the file's schema (from `sqlite_master`) and your question, and asked to
   return one SQL `SELECT` as JSON.
2. That query runs against the file opened **read-only** — nothing it does can write to the
   file. A second check also rejects anything that isn't a single `SELECT`/`WITH` statement
   before it's even run (belt-and-suspenders: the read-only connection would refuse a write
   either way). One repair attempt is made if the query fails, feeding the error back to the
   model.
3. The model phrases a short natural-language answer from the returned rows.

The generated SQL and the result table are both shown alongside the answer (SQL is collapsed
under "SQL used"). This is a plain request/response pipeline, not a tool-calling agent loop —
it only needs the model to return structured text, so it works the same regardless of whether
your chosen runtime supports tool calling. No MCP server is involved: this process already owns
both the LLM call and the SQLite connection directly.

## Notes

- The first call to your local LLM after starting the app is slow (the model has to load into
  memory — tens of seconds is normal on this machine); subsequent calls are much faster once
  it's warm.
- If your local LLM runtime isn't running or the configured model isn't available, a banner at
  the top explains the fix.
- Inspect logged usage/cost directly:
  ```
  sqlite3 data/router_agent.db "SELECT timestamp, classification, model_used, cost_usd FROM queries ORDER BY timestamp DESC LIMIT 20;"
  sqlite3 data/router_agent.db "SELECT SUM(cost_usd) FROM queries;"
  ```
  (Or just ask the app itself, in Database mode.)
