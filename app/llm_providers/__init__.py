"""Local LLM runtime backends. Import app.llm_providers.factory to get one — callers
should never import a concrete provider class directly, so classifier.py and Database
mode stay provider-agnostic."""
