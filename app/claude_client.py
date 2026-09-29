"""Thin wrapper around the Anthropic SDK: one call in, (text, usage) out."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import ANTHROPIC_API_KEY
from app.errors import MissingApiKeyError

if TYPE_CHECKING:
    import anthropic

MAX_TOKENS = 4096

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    # Imported lazily: `import anthropic` alone takes ~2.5s, and doing it at module
    # load time was blocking the webview window from appearing on startup.
    import anthropic

    global _client
    if not ANTHROPIC_API_KEY:
        raise MissingApiKeyError("No Anthropic API key configured.")
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def reset_client() -> None:
    """Call after config.save_api_key() so a freshly-entered key takes effect immediately."""
    global _client
    _client = None


def get_client() -> "anthropic.Anthropic":
    """Public accessor for callers that need the raw SDK client (e.g. the code-mode
    tool-use loop, which makes several calls per turn and needs more than send())."""
    return _get_client()


def send(model_id: str, messages: list[dict]) -> tuple[str, "anthropic.types.Usage"]:
    """Send a (possibly multi-turn) message list to Claude. Returns (response_text, usage).

    `messages` is the full Anthropic-format history including the newest user turn —
    callers (Api) are responsible for reconstructing it from prior queries rows.

    Lets anthropic's typed exceptions (AuthenticationError, RateLimitError,
    APIConnectionError, APIStatusError, ...) propagate — callers catch them individually.
    """
    client = _get_client()
    response = client.messages.create(
        model=model_id,
        max_tokens=MAX_TOKENS,
        messages=messages,
    )

    text_parts = [block.text for block in response.content if block.type == "text"]
    return "".join(text_parts), response.usage
