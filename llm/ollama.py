"""Ollama LLM backend."""
from __future__ import annotations
import json
from typing import Any
import requests
from core.logger import get_logger
from llm.base import BaseLLM

logger = get_logger(__name__)


class OllamaLLM(BaseLLM):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False}
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except Exception as exc:
            logger.error("Ollama chat error: %s", exc)
            return f"[ERROR] {exc}"

    def generate(self, messages: list[dict[str, str]]) -> str:
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        try:
            resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as exc:
            logger.error("Ollama generate error: %s", exc)
            return f"[ERROR] {exc}"

    def tool_call(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        system_tool_prompt = (
            "You must respond with a JSON array of tool calls. "
            "Each item must have 'name' and 'arguments' keys. "
            "If no tool is needed, return an empty array [].\n"
            f"Available tools: {json.dumps([t['name'] for t in tools])}"
        )
        augmented = [{"role": "system", "content": system_tool_prompt}] + messages
        response = self.chat(augmented)
        try:
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except Exception:
            pass
        return []
