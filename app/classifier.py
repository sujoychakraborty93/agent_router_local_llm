"""Local difficulty classifier — talks to whichever local LLM provider is configured
(see app/llm_providers/), so this works the same whether that's Ollama, LM Studio,
llama.cpp's server, or anything else that implements LocalLLMProvider.

Three layers of defense against an unreliable small local model:
  1. Structured JSON output (`json_schema`) constrains sampling to the enum, where
     the provider supports it.
  2. A regex/keyword scan over the raw text if JSON parsing fails.
  3. A hard default to "medium" if nothing else matches a valid label.
The raw model output is always returned alongside the parsed label so callers can log it.
"""

import json
import re

from app.llm_providers.factory import get_provider

VALID_LABELS = ("easy", "medium", "complex")

SYSTEM_PROMPT = """You are a request-difficulty classifier. Read the user's message and classify it into exactly
one of three difficulty levels: "easy", "medium", or "complex". Respond ONLY with JSON matching
the schema: {"classification": "easy" | "medium" | "complex"}. Do not include any other text.

Guidelines:
- easy: greetings, small talk, simple factual lookups, one-line explanations, trivial formatting
  or short code snippets (a few lines), simple rephrasing/translation of short text.
- medium: multi-step explanations, moderate reasoning, standard code (a function, a small script,
  debugging a specific error), summarizing a medium document, comparisons with 2-4 factors.
- complex: multi-step reasoning chains, system/architecture design, large or multi-file code
  generation/refactors, nuanced tradeoff analysis, math proofs/derivations, long-form writing
  requiring structure and depth, ambiguous or open-ended requests.

Examples:
User: "Hi, how are you?"
Assistant: {"classification": "easy"}

User: "What's the capital of France?"
Assistant: {"classification": "easy"}

User: "Write a Python function to check if a string is a palindrome."
Assistant: {"classification": "medium"}

User: "Explain the difference between TCP and UDP with a couple of use cases."
Assistant: {"classification": "medium"}

User: "Design a scalable microservices architecture for an e-commerce checkout system,
including failure handling and data consistency tradeoffs."
Assistant: {"classification": "complex"}

User: "Refactor this 500-line module to use dependency injection and explain the tradeoffs
of each approach you considered."
Assistant: {"classification": "complex"}
"""

RESPONSE_FORMAT = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": list(VALID_LABELS)},
    },
    "required": ["classification"],
}

_LABEL_RE = re.compile(r"\b(easy|medium|complex)\b", re.IGNORECASE)

TITLE_SYSTEM_PROMPT = """Generate a short, descriptive chat title (3-6 words) summarizing what the
user's message is about. Respond with ONLY the title text — no quotes, no trailing punctuation,
no preamble.

Examples:
User: "Can you help me debug this Python function that's throwing a KeyError?"
Assistant: Debugging a Python KeyError

User: "What's the capital of France?"
Assistant: Capital of France

User: "Refactor this 500-line module to use dependency injection."
Assistant: Refactor module for dependency injection
"""


def is_local_llm_ready() -> tuple[bool, str]:
    """Health-check the configured local LLM provider is reachable and its model available."""
    return get_provider().is_ready()


def classify(prompt: str) -> tuple[str, str]:
    """Returns (classification, raw_model_output). Never raises except LocalLLMUnavailableError."""
    raw = get_provider().chat(
        system=SYSTEM_PROMPT,
        user=prompt,
        json_schema=RESPONSE_FORMAT,
        temperature=0,
        num_predict=20,
    )

    label = None
    try:
        parsed = json.loads(raw)
        candidate = str(parsed.get("classification", "")).strip().lower()
        if candidate in VALID_LABELS:
            label = candidate
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    if label is None:
        match = _LABEL_RE.search(raw or "")
        if match:
            label = match.group(1).lower()

    if label not in VALID_LABELS:
        label = "medium"

    return label, raw


def generate_chat_title(prompt: str) -> str | None:
    """Best-effort short chat title generated locally, for auto-naming a new
    chat/code/database session from its first message. Returns None on any
    failure — title generation must never block sending a message."""
    try:
        raw = get_provider().chat(
            system=TITLE_SYSTEM_PROMPT,
            user=prompt[:2000],
            temperature=0.3,
            num_predict=20,
        )
    except Exception:
        return None

    text = raw.strip().strip("\"'“”.\n ")
    return text[:60] if text else None
