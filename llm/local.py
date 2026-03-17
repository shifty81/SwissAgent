"""Local (stub) LLM backend for offline/testing use."""
from __future__ import annotations
from typing import Any
from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)


class LocalLLM(BaseLLM):
    """Stub local LLM. In production load a GGUF model via llama-cpp-python."""

    def __init__(self, model_path: str = "") -> None:
        self.model_path = model_path
        if model_path:
            logger.info("LocalLLM: would load model from %s", model_path)
        else:
            logger.warning("LocalLLM: no model path configured, using stub responses")

    def chat(self, messages: list[dict[str, str]]) -> str:
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return f"[LocalLLM stub] Received: {last}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.chat(messages)

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []
