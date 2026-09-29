"""The bridge object exposed to the frontend as window.pywebview.api.*"""

import json
import re
import sqlite3
import time
from pathlib import Path

from app import claude_client, config
from app.classifier import classify, generate_chat_title, is_local_llm_ready
from app.code_mode.session import CodeSession
from app.db import database
from app.db_mode.session import DBSession
from app.errors import MissingApiKeyError, LocalLLMUnavailableError
from app.llm_providers import factory as llm_factory
from app.pricing import compute_cost
from app.router import model_for_classification

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Api:
    def __init__(self):
        # Set by main.py right after webview.create_window() — needed for the native
        # folder-picker dialog in Code mode. None until then (and in tests).
        self.window = None

        self.current_user_email: str | None = database.get_first_user_email()
        self.current_chat_id: int | None = (
            database.get_default_chat_id(self.current_user_email)
            if self.current_user_email
            else None
        )

        # Code mode: at most one active folder session at a time, matching the
        # single-window, single-focus shape of the rest of this app.
        self.code_session: CodeSession | None = None
        self.code_chat_id: int | None = None

        # Database mode: same one-active-session shape as Code mode.
        self.db_session: DBSession | None = None
        self.db_chat_id: int | None = None

        # None = "Auto" (the local classifier picks the model, per turn). Set to a
        # model id to bypass the classifier entirely and always use that model.
        self.selected_model: str | None = None

    # ---- bootstrap / setup -------------------------------------------------

    def get_bootstrap_state(self):
        local_llm_ready, local_llm_message = is_local_llm_ready()
        chats = []
        history = []
        if self.current_user_email:
            chats = database.list_chats(self.current_user_email, kind="chat")
            if self.current_chat_id:
                history = database.get_chat_history(self.current_chat_id)
        return {
            "first_run": self.current_user_email is None,
            "email": self.current_user_email,
            "has_api_key": config.has_api_key(),
            "local_llm_ready": local_llm_ready,
            "local_llm_message": local_llm_message,
            "chats": chats,
            "current_chat_id": self.current_chat_id,
            "history": history,
            "available_models": list(config.MODEL_PRICING.keys()),
            "selected_model": self.selected_model,
        }

    def set_model_override(self, model_id: str | None):
        """None (or '') means Auto: the local classifier picks a model per turn. Any
        other value pins every subsequent send to that model and skips classification."""
        model_id = (model_id or "").strip() or None
        if model_id and model_id not in config.MODEL_PRICING:
            return {"ok": False, "error": f"Unknown model '{model_id}'."}
        self.selected_model = model_id
        return {"ok": True, "selected_model": self.selected_model}

    def _set_active_user(self, email: str) -> None:
        """Switches the active account: creates the user (idempotent) plus their default
        chat if new, then resets all in-memory session state so nothing from the
        previously active account (or no account, right after logout) leaks into the
        new one. Every chat/query row is already scoped by user_email in the database,
        so this never touches another account's rows — logging back in as a user just
        re-points these ids at the rows that were already there."""
        chat_id = database.create_user_with_default_chat(email)
        self.current_user_email = email
        self.current_chat_id = chat_id
        self.code_session = None
        self.code_chat_id = None
        self.db_session = None
        self.db_chat_id = None

    def save_email(self, email: str):
        email = (email or "").strip()
        if not _EMAIL_RE.match(email):
            return {"ok": False, "error": "That doesn't look like a valid email address."}
        self._set_active_user(email)
        return {"ok": True}

    def list_users(self):
        """Known accounts on this machine, for the account-switch picker."""
        return database.list_users()

    def login(self, email: str):
        """Logs in as `email` — an existing account (its chats/history are untouched
        and reappear as-is) or a brand new one. Used for both the initial sign-in and
        switching accounts."""
        email = (email or "").strip()
        if not _EMAIL_RE.match(email):
            return {"ok": False, "error": "That doesn't look like a valid email address."}
        self._set_active_user(email)
        return {"ok": True}

    def logout(self):
        """Clears the active account from memory only. Its data stays in the database
        untouched, so logging back in (here or as a different user in between) shows
        it exactly as it was left."""
        self.current_user_email = None
        self.current_chat_id = None
        self.code_session = None
        self.code_chat_id = None
        self.db_session = None
        self.db_chat_id = None
        return {"ok": True}

    def save_api_key(self, api_key: str):
        api_key = (api_key or "").strip()
        if not api_key:
            return {"ok": False, "error": "API key can't be empty."}
        config.save_api_key(api_key)
        claude_client.reset_client()
        return {"ok": True}

    # ---- local LLM settings (classification, titles, Database mode) ---------

    def get_local_llm_settings(self):
        return {
            "provider": config.LOCAL_LLM_PROVIDER,
            "base_url": config.LOCAL_LLM_BASE_URL,
            "model": config.LOCAL_LLM_MODEL,
            "providers": [
                {"id": p, "label": config.LOCAL_LLM_PROVIDER_LABELS[p]}
                for p in config.LOCAL_LLM_PROVIDERS
            ],
        }

    def default_local_llm_base_url(self, provider: str):
        return config.default_base_url_for(provider)

    def list_local_llm_models(self, provider: str | None = None, base_url: str | None = None):
        """Best-effort model discovery for the Settings picker — works against an
        unsaved provider/base_url too, so the user can check before committing."""
        try:
            models = llm_factory.list_models_for(
                provider or config.LOCAL_LLM_PROVIDER,
                base_url or config.LOCAL_LLM_BASE_URL,
            )
            return {"ok": True, "models": models}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "models": []}

    def save_local_llm_settings(self, provider: str, base_url: str, model: str):
        provider = (provider or "ollama").strip().lower()
        if provider not in config.LOCAL_LLM_PROVIDERS:
            return {"ok": False, "error": f"Unknown provider '{provider}'."}
        model = (model or "").strip()
        if not model:
            return {"ok": False, "error": "Model can't be empty."}
        config.save_local_llm_settings(provider, base_url, model)
        return {"ok": True, **self.get_local_llm_settings()}

    # ---- chats (Phase 2: multiple chats + history) ---------------------------

    def list_chats(self):
        if not self.current_user_email:
            return []
        return database.list_chats(self.current_user_email, kind="chat")

    def create_chat(self, title: str | None = None):
        if not self.current_user_email:
            return {"ok": False, "error": "No user set up yet."}
        final_title = (title or "").strip() or "New Chat"
        chat_id = database.create_chat(self.current_user_email, title=final_title)
        self.current_chat_id = chat_id
        return {"ok": True, "chat_id": chat_id, "title": final_title}

    def switch_chat(self, chat_id: int):
        if not self.current_user_email:
            return {"ok": False, "error": "No user set up yet."}
        if not database.chat_belongs_to_user(chat_id, self.current_user_email):
            return {"ok": False, "error": "That chat doesn't exist."}
        self.current_chat_id = chat_id
        return {"ok": True, "chat_id": chat_id, "history": database.get_chat_history(chat_id)}

    def rename_chat(self, chat_id: int, title: str):
        """Manual rename (the sidebar's ⋮ menu) — works for both chat and code-mode
        entries. Marks the chat as user-titled so auto-naming never overwrites it again."""
        if not self.current_user_email:
            return {"ok": False, "error": "No user set up yet."}
        if not database.chat_belongs_to_user(chat_id, self.current_user_email):
            return {"ok": False, "error": "That chat doesn't exist."}
        title = (title or "").strip()[:80]
        if not title:
            return {"ok": False, "error": "Title can't be empty."}
        database.rename_chat(chat_id, title, by_user=True)
        return {"ok": True, "title": title}

    def _maybe_autoname_chat(self, chat_id: int, prompt: str) -> str | None:
        """Best-effort: if this chat hasn't been manually renamed, ask the local model for
        a short title from its first message and persist it. Failures are swallowed —
        title generation must never block sending a message."""
        chat = database.get_chat(chat_id)
        if not chat or chat["title_set_by_user"]:
            return None
        title = generate_chat_title(prompt)
        if not title:
            return None
        database.rename_chat(chat_id, title, by_user=False)
        return title

    # ---- chat ---------------------------------------------------------------

    def send_message(self, prompt: str):
        try:
            return self._send_message(prompt)
        except Exception as exc:  # last-resort net so the JS bridge never gets an unserializable crash
            return {"ok": False, "error": f"Unexpected error: {exc}", "error_type": "unexpected"}

    def _send_message(self, prompt: str):
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "Empty message."}
        if not self.current_user_email or not self.current_chat_id:
            return {"ok": False, "error": "No user set up yet."}

        import anthropic  # deferred: only needed once we're about to call Claude

        started = time.monotonic()

        history = database.get_chat_history(self.current_chat_id)
        if not history:
            self._maybe_autoname_chat(self.current_chat_id, prompt)

        # --- pick a model: the user's explicit override, or the local classifier ---
        if self.selected_model:
            model_id = self.selected_model
            classification, raw_classification = None, None
        else:
            try:
                classification, raw_classification = classify(prompt)
            except LocalLLMUnavailableError as exc:
                database.log_query(
                    chat_id=self.current_chat_id,
                    user_email=self.current_user_email,
                    input_prompt=prompt,
                    status="error",
                    error_message=str(exc),
                )
                return {"ok": False, "error": str(exc), "error_type": "ollama_unavailable"}
            model_id = model_for_classification(classification)

        # --- call Claude, with prior turns from this chat as context ---
        messages = []
        for turn in history:
            messages.append({"role": "user", "content": turn["input_prompt"]})
            messages.append({"role": "assistant", "content": turn["output_response"]})
        messages.append({"role": "user", "content": prompt})

        try:
            output_text, usage = claude_client.send(model_id, messages)
        except MissingApiKeyError:
            message = "No Anthropic API key configured. Add one in Settings."
            database.log_query(
                chat_id=self.current_chat_id,
                user_email=self.current_user_email,
                input_prompt=prompt,
                classification=classification,
                classification_raw=raw_classification,
                model_used=model_id,
                status="error",
                error_message=message,
            )
            return {"ok": False, "error": message, "error_type": "missing_api_key"}
        except anthropic.AuthenticationError:
            message = "Anthropic API key was rejected. Check it in Settings."
            error_type = "auth_error"
        except anthropic.RateLimitError:
            message = "Rate limited by the Anthropic API. Try again shortly."
            error_type = "rate_limit"
        except anthropic.APIConnectionError:
            message = "Couldn't reach the Anthropic API. Check your network connection."
            error_type = "connection_error"
        except anthropic.APIStatusError as exc:
            message = f"Anthropic API error ({exc.status_code}): {exc.message}"
            error_type = "api_status_error"
        else:
            latency_ms = int((time.monotonic() - started) * 1000)
            cost_usd = compute_cost(model_id, usage.input_tokens, usage.output_tokens)
            database.log_query(
                chat_id=self.current_chat_id,
                user_email=self.current_user_email,
                input_prompt=prompt,
                output_response=output_text,
                classification=classification,
                classification_raw=raw_classification,
                model_used=model_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                status="ok",
            )
            return {
                "ok": True,
                "input": prompt,
                "output": output_text,
                "classification": classification,
                "model_used": model_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
            }

        # any of the except-branches above that didn't `return` land here
        database.log_query(
            chat_id=self.current_chat_id,
            user_email=self.current_user_email,
            input_prompt=prompt,
            classification=classification,
            classification_raw=raw_classification,
            model_used=model_id,
            status="error",
            error_message=message,
        )
        return {"ok": False, "error": message, "error_type": error_type}

    # ---- code mode (Phase 3: folder access + tool-use loop) ------------------

    def list_code_chats(self):
        if not self.current_user_email:
            return []
        return database.list_chats(self.current_user_email, kind="code")

    def switch_code_chat(self, chat_id: int):
        """Reopens a past code session's folder. Note: this starts a FRESH CodeSession —
        the prior tool-use conversation isn't persisted/restored, only the folder is
        (see CodeSession's docstring on why conversation state is in-memory only)."""
        if not self.current_user_email:
            return {"ok": False, "error": "No user set up yet."}
        chat = database.get_chat(chat_id)
        if not chat or chat["user_email"] != self.current_user_email or chat["kind"] != "code":
            return {"ok": False, "error": "That code session doesn't exist."}
        if not chat["folder_path"]:
            return {"ok": False, "error": "This code session has no folder recorded."}

        try:
            self.code_session = CodeSession(chat["folder_path"])
        except NotADirectoryError as exc:
            return {"ok": False, "error": str(exc)}

        self.code_chat_id = chat_id
        return {"ok": True, "folder": self.code_session.folder, "title": chat["title"]}

    def choose_code_folder(self):
        """Opens a native folder picker and starts a fresh CodeSession scoped to it."""
        import webview

        if self.window is None:
            return {"ok": False, "error": "Window not ready yet."}

        selection = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if not selection:
            return {"ok": False, "error": None}  # user cancelled the picker

        folder = selection[0] if isinstance(selection, (list, tuple)) else selection
        try:
            self.code_session = CodeSession(folder)
        except NotADirectoryError as exc:
            return {"ok": False, "error": str(exc)}

        if self.current_user_email:
            self.code_chat_id = database.create_chat(
                self.current_user_email,
                title=f"Code: {Path(self.code_session.folder).name}",
                kind="code",
                folder_path=self.code_session.folder,
            )

        return {"ok": True, "folder": self.code_session.folder, "chat_id": self.code_chat_id}

    def send_code_message(self, prompt: str):
        try:
            return self._send_code_message(prompt)
        except Exception as exc:  # last-resort net, same as send_message
            return {"ok": False, "error": f"Unexpected error: {exc}", "error_type": "unexpected"}

    def _send_code_message(self, prompt: str):
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "Empty message."}
        if self.code_session is None:
            return {"ok": False, "error": "Choose a folder first."}
        if self.code_session.pending_writes or self.code_session.pending_questions:
            return {
                "ok": False,
                "error": "Resolve the pending item(s) above before sending a new message.",
                "error_type": "pending_input",
            }

        # Use the DB's logged history (not CodeSession.messages) to detect "first message":
        # reopening a past session via switch_code_chat() creates a fresh, empty CodeSession
        # even though the chat already has a title, so it must not be renamed again.
        if self.code_chat_id and not database.get_chat_history(self.code_chat_id):
            self._maybe_autoname_chat(self.code_chat_id, prompt)

        if self.selected_model:
            model_id = self.selected_model
            classification, raw_classification = None, None
        else:
            try:
                classification, raw_classification = classify(prompt)
            except LocalLLMUnavailableError as exc:
                return {"ok": False, "error": str(exc), "error_type": "ollama_unavailable"}
            model_id = model_for_classification(classification)

        return self._run_code_session(
            lambda: self.code_session.start_task(prompt, model_id),
            prompt=prompt,
            classification=classification,
            classification_raw=raw_classification,
        )

    def resolve_code_write(self, write_id, approve: bool):
        try:
            return self._resolve_code_write(write_id, approve)
        except Exception as exc:
            return {"ok": False, "error": f"Unexpected error: {exc}", "error_type": "unexpected"}

    def _resolve_code_write(self, write_id, approve: bool):
        if self.code_session is None:
            return {"ok": False, "error": "No active code session."}
        try:
            write_id = int(write_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid write id."}

        return self._run_code_session(
            lambda: self.code_session.resolve_write(write_id, bool(approve)),
            prompt=self.code_session.initial_prompt,
            classification=None,
            classification_raw=None,
        )

    def resolve_code_questions(self, question_set_id, answers):
        try:
            return self._resolve_code_questions(question_set_id, answers)
        except Exception as exc:
            return {"ok": False, "error": f"Unexpected error: {exc}", "error_type": "unexpected"}

    def _resolve_code_questions(self, question_set_id, answers):
        if self.code_session is None:
            return {"ok": False, "error": "No active code session."}
        try:
            question_set_id = int(question_set_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid question set id."}
        if not isinstance(answers, list):
            return {"ok": False, "error": "Answers must be a list."}

        return self._run_code_session(
            lambda: self.code_session.resolve_questions(question_set_id, answers),
            prompt=self.code_session.initial_prompt,
            classification=None,
            classification_raw=None,
        )

    def _run_code_session(self, fn, *, prompt, classification, classification_raw):
        """Runs a CodeSession step (start_task or resolve_write), mapping the same
        Anthropic exception types send_message() handles into the same response shape,
        and logging a queries row once a task reaches 'final' (not on each intermediate
        pending_input round-trip — see CodeSession's docstring)."""
        import anthropic

        try:
            result = fn()
        except MissingApiKeyError:
            message, error_type = "No Anthropic API key configured. Add one in Settings.", "missing_api_key"
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}
        except anthropic.AuthenticationError:
            message, error_type = "Anthropic API key was rejected. Check it in Settings.", "auth_error"
        except anthropic.RateLimitError:
            message, error_type = "Rate limited by the Anthropic API. Try again shortly.", "rate_limit"
        except anthropic.APIConnectionError:
            message, error_type = "Couldn't reach the Anthropic API. Check your network connection.", "connection_error"
        except anthropic.APIStatusError as exc:
            message, error_type = f"Anthropic API error ({exc.status_code}): {exc.message}", "api_status_error"
        else:
            result["ok"] = True
            if classification:
                result["classification"] = classification
            if result["status"] == "final":
                self._log_code_turn(prompt, classification, classification_raw, result)
            return result

        self._log_code_turn_error(prompt, classification, classification_raw, message)
        return {"ok": False, "error": message, "error_type": error_type}

    def _log_code_turn(self, prompt, classification, classification_raw, result):
        if not self.code_chat_id or not self.current_user_email:
            return
        database.log_query(
            chat_id=self.code_chat_id,
            user_email=self.current_user_email,
            input_prompt=prompt,
            output_response=result.get("text"),
            classification=classification,
            classification_raw=classification_raw,
            model_used=result.get("model_used"),
            input_tokens=result.get("input_tokens"),
            output_tokens=result.get("output_tokens"),
            cost_usd=result.get("cost_usd"),
            status="ok",
        )

    def _log_code_turn_error(self, prompt, classification, classification_raw, message):
        if not self.code_chat_id or not self.current_user_email:
            return
        database.log_query(
            chat_id=self.code_chat_id,
            user_email=self.current_user_email,
            input_prompt=prompt or "",
            classification=classification,
            classification_raw=classification_raw,
            status="error",
            error_message=message,
        )

    # ---- database mode (Phase 4: NL -> SQL over a local SQLite file) ---------
    #
    # Unlike Code mode, this never touches the Anthropic API — the local LLM
    # provider generates the SQL and the answer, so every turn here is free and
    # fully local. See app/db_mode/session.py for why this isn't a tool-calling
    # loop (and why no MCP server is needed).

    def list_db_chats(self):
        if not self.current_user_email:
            return []
        return database.list_chats(self.current_user_email, kind="database")

    def create_db_chat(self, db_path: str | None = None):
        """With no db_path, targets this app's own query-log database — the common
        case ('how much did each model cost'). Pass a path to point at a different
        SQLite file instead (see choose_db_file for the native file-picker version)."""
        if not self.current_user_email:
            return {"ok": False, "error": "No user set up yet."}
        target = (db_path or "").strip() or str(config.DB_PATH)
        try:
            self.db_session = DBSession(target)
        except (FileNotFoundError, sqlite3.Error) as exc:
            return {"ok": False, "error": str(exc)}

        title = "Database" if target == str(config.DB_PATH) else f"Database: {Path(target).name}"
        self.db_chat_id = database.create_chat(
            self.current_user_email, title=title, kind="database", folder_path=target,
        )
        return {"ok": True, "chat_id": self.db_chat_id, "db_path": target, "title": title}

    def choose_db_file(self):
        """Opens a native file picker and starts a fresh DBSession against whichever
        .db/.sqlite file the user picks."""
        import webview

        if self.window is None:
            return {"ok": False, "error": "Window not ready yet."}

        selection = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("SQLite files (*.db;*.sqlite;*.sqlite3)", "All files (*.*)"),
        )
        if not selection:
            return {"ok": False, "error": None}  # user cancelled the picker

        path = selection[0] if isinstance(selection, (list, tuple)) else selection
        return self.create_db_chat(path)

    def switch_db_chat(self, chat_id: int):
        """Reopens a past database chat's target file — a fresh DBSession, matching
        Code mode's switch_code_chat (only the target is restored, not conversation
        state, since each turn here is already a self-contained NL->SQL round trip)."""
        if not self.current_user_email:
            return {"ok": False, "error": "No user set up yet."}
        chat = database.get_chat(chat_id)
        if not chat or chat["user_email"] != self.current_user_email or chat["kind"] != "database":
            return {"ok": False, "error": "That database chat doesn't exist."}
        target = chat["folder_path"] or str(config.DB_PATH)

        try:
            self.db_session = DBSession(target)
        except (FileNotFoundError, sqlite3.Error) as exc:
            return {"ok": False, "error": str(exc)}

        self.db_chat_id = chat_id
        history = database.get_chat_history(chat_id)
        return {"ok": True, "db_path": target, "title": chat["title"], "history": history}

    def send_db_message(self, prompt: str):
        try:
            return self._send_db_message(prompt)
        except Exception as exc:  # last-resort net, same as send_message
            return {"ok": False, "error": f"Unexpected error: {exc}", "error_type": "unexpected"}

    def _send_db_message(self, prompt: str):
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "Empty message."}
        if self.db_session is None:
            return {"ok": False, "error": "Choose a database first."}

        if self.db_chat_id and not database.get_chat_history(self.db_chat_id):
            self._maybe_autoname_chat(self.db_chat_id, prompt)

        started = time.monotonic()
        try:
            result = self.db_session.ask(prompt)
        except LocalLLMUnavailableError as exc:
            self._log_db_turn_error(prompt, str(exc), None)
            return {"ok": False, "error": str(exc), "error_type": "local_llm_unavailable"}
        latency_ms = int((time.monotonic() - started) * 1000)

        if not result["ok"]:
            self._log_db_turn_error(prompt, result["error"], result.get("sql"), latency_ms)
            return {"ok": False, "error": result["error"], "sql": result.get("sql")}

        result_json = json.dumps({"columns": result["columns"], "rows": result["rows"]})
        if self.db_chat_id and self.current_user_email:
            database.log_query(
                chat_id=self.db_chat_id,
                user_email=self.current_user_email,
                input_prompt=prompt,
                output_response=result["answer"],
                model_used=f"local:{config.LOCAL_LLM_MODEL}",
                sql_query=result["sql"],
                result_json=result_json,
                cost_usd=0.0,
                latency_ms=latency_ms,
                status="ok",
            )
        return {
            "ok": True,
            "input": prompt,
            "answer": result["answer"],
            "sql": result["sql"],
            "columns": result["columns"],
            "rows": result["rows"],
            "latency_ms": latency_ms,
        }

    def _log_db_turn_error(self, prompt, error_message, sql, latency_ms=None):
        if not self.db_chat_id or not self.current_user_email:
            return
        database.log_query(
            chat_id=self.db_chat_id,
            user_email=self.current_user_email,
            input_prompt=prompt,
            sql_query=sql,
            latency_ms=latency_ms,
            status="error",
            error_message=error_message,
        )
