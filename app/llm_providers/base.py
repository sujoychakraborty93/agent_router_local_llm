"""Common interface every local LLM runtime backend implements, so the classifier and
Database mode can talk to Ollama, LM Studio, llama.cpp's `server`, vLLM, etc.
interchangeably."""

from abc import ABC, abstractmethod


class LocalLLMProvider(ABC):
    def __init__(self, base_url: str, model: str):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model

    @abstractmethod
    def chat(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict | None = None,
        temperature: float = 0,
        num_predict: int = 512,
    ) -> str:
        """Single-turn system+user completion. Returns the raw text content.

        json_schema, when given, asks the runtime to constrain output to that JSON
        shape. Ollama enforces it natively via its `format` field; other runtimes
        only get a looser 'respond with a JSON object' hint, so callers must still
        tolerate malformed JSON coming back (see classifier.py's fallback parsing).
        """

    @abstractmethod
    def list_models(self) -> list[str]:
        """Models the runtime currently has installed/loaded."""

    @abstractmethod
    def is_ready(self) -> tuple[bool, str]:
        """Health check: (ok, human-readable message)."""
