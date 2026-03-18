"""Base LLM interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Iterator


class BaseLLM(ABC):
    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat conversation and return the assistant response."""

    @abstractmethod
    def generate(self, messages: list[dict[str, str]]) -> str:
        """Generate a completion from messages."""

    @abstractmethod
    def tool_call(
        self, messages: list[dict[str, str]], tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Perform a tool-call interaction and return list of tool calls."""

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        """Stream chat response token by token.

        Default implementation yields the full response in one chunk.
        Override in subclasses that support native streaming (e.g. Ollama).
        """
        yield self.chat(messages)
