"""Constructs the configured LocalLLMProvider. Import this instead of a concrete
provider class so classifier.py and Database mode stay provider-agnostic."""

from app import config
from app.llm_providers.base import LocalLLMProvider
from app.llm_providers.ollama_provider import OllamaProvider
from app.llm_providers.openai_compat_provider import OpenAICompatProvider

_PROVIDER_CLASSES = {
    "ollama": OllamaProvider,
    "openai_compat": OpenAICompatProvider,
}


def get_provider(
    provider_id: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> LocalLLMProvider:
    """Defaults to the saved config; callers pass explicit values to try settings
    the user hasn't saved yet (e.g. the Settings 'refresh models' button)."""
    provider_id = (provider_id or config.LOCAL_LLM_PROVIDER).strip().lower()
    cls = _PROVIDER_CLASSES.get(provider_id, OllamaProvider)
    return cls(
        base_url=base_url or config.LOCAL_LLM_BASE_URL,
        model=model if model is not None else config.LOCAL_LLM_MODEL,
    )


def list_models_for(provider_id: str, base_url: str) -> list[str]:
    """Model discovery for the Settings UI, against a provider/URL that may not be
    saved yet — lets the picker populate before the user commits to a choice."""
    return get_provider(provider_id, base_url, model="").list_models()
