"""Central configuration: env vars, model routing constants, local-LLM settings, paths."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

DB_PATH = BASE_DIR / "data" / "router_agent.db"
SCHEMA_PATH = BASE_DIR / "app" / "db" / "schema.sql"

CLASSIFICATION_TO_MODEL = {
    "easy": "claude-haiku-4-5",
    "medium": "claude-sonnet-5",
    "complex": "claude-opus-5",
}

MODEL_PRICING = {
    # USD per 1M tokens (input, output)
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
}

# ---- local LLM provider (classification, chat titles, Database mode) --------
#
# "ollama" talks to Ollama's native API. "openai_compat" talks to any local server
# that speaks the OpenAI chat-completions API instead — LM Studio, llama.cpp's
# `server`, vLLM, text-generation-webui, etc. — so any model you can load into one
# of those runtimes works here, not just Ollama/Qwen. See app/llm_providers/.

LOCAL_LLM_PROVIDERS = ("ollama", "openai_compat")
LOCAL_LLM_PROVIDER_LABELS = {
    "ollama": "Ollama",
    "openai_compat": "OpenAI-compatible (LM Studio, llama.cpp, vLLM, …)",
}
_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai_compat": "http://localhost:1234/v1",
}

LOCAL_LLM_CONNECT_TIMEOUT = 5
LOCAL_LLM_READ_TIMEOUT = 60


def _initial_provider() -> str:
    value = os.environ.get("LOCAL_LLM_PROVIDER", "ollama").strip().lower()
    return value if value in LOCAL_LLM_PROVIDERS else "ollama"


LOCAL_LLM_PROVIDER = _initial_provider()

# OLLAMA_HOST / OLLAMA_MODEL are read as a fallback so a .env from before this
# multi-provider change keeps working without any edits.
LOCAL_LLM_BASE_URL = (
    os.environ.get("LOCAL_LLM_BASE_URL", "").strip()
    or os.environ.get("OLLAMA_HOST", "").strip()
    or _DEFAULT_BASE_URLS[LOCAL_LLM_PROVIDER]
)
LOCAL_LLM_MODEL = (
    os.environ.get("LOCAL_LLM_MODEL", "").strip()
    or os.environ.get("OLLAMA_MODEL", "").strip()
    or "qwen3.5:4b"
)


def has_api_key() -> bool:
    return bool(ANTHROPIC_API_KEY)


def default_base_url_for(provider: str) -> str:
    return _DEFAULT_BASE_URLS.get(provider, _DEFAULT_BASE_URLS["ollama"])


def _write_env_updates(updates: dict) -> None:
    """Merges {KEY: value} into .env, updating existing lines in place or appending
    new ones. Used so a multi-field save (provider + base URL + model) touches the
    file once instead of three times."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    remaining = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0]
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"
    for key, value in remaining.items():
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


def save_api_key(new_key: str) -> None:
    """Persist a freshly-entered API key to .env and update the running process."""
    global ANTHROPIC_API_KEY
    new_key = new_key.strip()
    _write_env_updates({"ANTHROPIC_API_KEY": new_key})
    ANTHROPIC_API_KEY = new_key
    os.environ["ANTHROPIC_API_KEY"] = new_key


def save_local_llm_settings(provider: str, base_url: str, model: str) -> None:
    """Persist the local LLM provider/base URL/model to .env and update the running
    process so the next classify()/Database-mode call picks it up immediately."""
    global LOCAL_LLM_PROVIDER, LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL

    provider = (provider or "ollama").strip().lower()
    if provider not in LOCAL_LLM_PROVIDERS:
        provider = "ollama"
    base_url = (base_url or "").strip() or _DEFAULT_BASE_URLS[provider]
    model = (model or "").strip() or LOCAL_LLM_MODEL

    _write_env_updates({
        "LOCAL_LLM_PROVIDER": provider,
        "LOCAL_LLM_BASE_URL": base_url,
        "LOCAL_LLM_MODEL": model,
    })

    LOCAL_LLM_PROVIDER = provider
    LOCAL_LLM_BASE_URL = base_url
    LOCAL_LLM_MODEL = model
    os.environ["LOCAL_LLM_PROVIDER"] = provider
    os.environ["LOCAL_LLM_BASE_URL"] = base_url
    os.environ["LOCAL_LLM_MODEL"] = model
