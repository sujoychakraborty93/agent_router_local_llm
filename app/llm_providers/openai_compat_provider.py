"""Backend for any local runtime that speaks the OpenAI chat-completions API — LM
Studio, llama.cpp's `server`, vLLM, text-generation-webui, etc. Whatever model you've
loaded into one of those is usable here without any code change."""

import requests

from app.config import LOCAL_LLM_CONNECT_TIMEOUT, LOCAL_LLM_READ_TIMEOUT
from app.errors import LocalLLMUnavailableError
from app.llm_providers.base import LocalLLMProvider


class OpenAICompatProvider(LocalLLMProvider):
    def chat(self, *, system, user, json_schema=None, temperature=0, num_predict=512):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": num_predict,
        }
        # Most OpenAI-compatible servers only support the loose 'json_object' mode
        # (not an enforced schema) — callers still need their own fallback parsing.
        if json_schema is not None:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=(LOCAL_LLM_CONNECT_TIMEOUT, LOCAL_LLM_READ_TIMEOUT),
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise LocalLLMUnavailableError(
                f"Could not reach the local model server at {self.base_url}: {exc}"
            ) from exc

        choices = response.json().get("choices") or []
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    def list_models(self) -> list[str]:
        response = requests.get(f"{self.base_url}/models", timeout=LOCAL_LLM_CONNECT_TIMEOUT)
        response.raise_for_status()
        return [m["id"] for m in response.json().get("data", []) if m.get("id")]

    def is_ready(self) -> tuple[bool, str]:
        try:
            self.list_models()
        except requests.exceptions.RequestException:
            return False, f"No local model server reachable at {self.base_url}."
        return True, "ok"
