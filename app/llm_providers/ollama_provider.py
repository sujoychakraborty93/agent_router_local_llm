"""Ollama backend: native /api/chat and /api/tags."""

import requests

from app.config import LOCAL_LLM_CONNECT_TIMEOUT, LOCAL_LLM_READ_TIMEOUT
from app.errors import LocalLLMUnavailableError
from app.llm_providers.base import LocalLLMProvider


class OllamaProvider(LocalLLMProvider):
    def chat(self, *, system, user, json_schema=None, temperature=0, num_predict=512):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": temperature, "num_predict": num_predict},
            # Reasoning models (qwen3.5 and friends) burn num_predict on <thinking>
            # tokens unless this is off, leaving no room for the real answer.
            "think": False,
            "stream": False,
        }
        if json_schema is not None:
            payload["format"] = json_schema

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=(LOCAL_LLM_CONNECT_TIMEOUT, LOCAL_LLM_READ_TIMEOUT),
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise LocalLLMUnavailableError(
                f"Could not reach Ollama at {self.base_url} (is `ollama serve` running?): {exc}"
            ) from exc

        data = response.json()
        return data.get("message", {}).get("content", "")

    def list_models(self) -> list[str]:
        response = requests.get(f"{self.base_url}/api/tags", timeout=LOCAL_LLM_CONNECT_TIMEOUT)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", []) if m.get("name")]

    def is_ready(self) -> tuple[bool, str]:
        try:
            models = self.list_models()
        except requests.exceptions.RequestException:
            return False, f"Ollama isn't reachable at {self.base_url}. Start it with `ollama serve`."

        if not any(m == self.model or m.startswith(self.model.split(":")[0]) for m in models):
            return False, f"Model '{self.model}' isn't pulled. Run `ollama pull {self.model}`."
        return True, "ok"
