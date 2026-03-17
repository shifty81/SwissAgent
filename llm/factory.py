"""LLM factory — creates the appropriate backend from config."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config_loader import ConfigLoader
    from llm.base import BaseLLM


def create_llm(backend: str, config: "ConfigLoader") -> "BaseLLM":
    backend = backend.lower()
    if backend == "ollama":
        from llm.ollama import OllamaLLM
        return OllamaLLM(
            base_url=config.get("llm.ollama.base_url", "http://localhost:11434"),
            model=config.get("llm.ollama.model", "llama3"),
        )
    if backend == "api":
        from llm.api import APILlm
        return APILlm(
            base_url=config.get("llm.api.base_url", "https://api.openai.com"),
            api_key=config.get("llm.api.key", ""),
            model=config.get("llm.api.model", "gpt-3.5-turbo"),
        )
    from llm.local import LocalLLM
    return LocalLLM(model_path=config.get("llm.local.model_path", ""))
