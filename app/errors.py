class LocalLLMUnavailableError(Exception):
    """Raised when the configured local LLM runtime (Ollama, LM Studio, ...) can't be
    reached, or the configured model isn't available there."""


class ClassificationError(Exception):
    """Raised when the classifier response can't be parsed at all (rare; classify() normally
    falls back to 'medium' instead of raising)."""


class MissingApiKeyError(Exception):
    """Raised when no Anthropic API key is configured."""
