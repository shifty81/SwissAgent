"""SwissAgent Core Agent Loop."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any
from core.config_loader import ConfigLoader
from core.logger import get_logger
from core.permission import PermissionSystem
from core.task_runner import TaskRunner
from core.tool_registry import ToolRegistry
from llm.base import BaseLLM

logger = get_logger(__name__)


@dataclass
class AgentState:
    prompt: str
    plan: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 20
    done: bool = False


class Agent:
    """Core agent that drives the prompt->plan->tool_call->execution->result loop."""

    def __init__(
        self,
        llm: BaseLLM,
        tool_registry: ToolRegistry,
        permission_system: PermissionSystem,
        task_runner: TaskRunner,
        config: ConfigLoader,
    ) -> None:
        self.llm = llm
        self.tools = tool_registry
        self.permissions = permission_system
        self.runner = task_runner
        self.config = config

    def run(self, prompt: str) -> str:
        state = AgentState(prompt=prompt)
        logger.info("Agent started. prompt=%r", prompt)
        while not state.done and state.iteration < state.max_iterations:
            state.iteration += 1
            logger.debug("Iteration %d", state.iteration)
            self._plan(state)
            tool_calls = self._select_tool_calls(state)
            if not tool_calls:
                state.done = True
                break
            for tc in tool_calls:
                result = self._execute_tool(tc, state)
                state.results.append(result)
                state.history.append({"tool": tc.get("name"), "result": result})
        final = self._finalize(state)
        logger.info("Agent finished after %d iterations.", state.iteration)
        return final

    def _plan(self, state: AgentState) -> None:
        messages = self._build_messages(state)
        response = self.llm.chat(messages)
        state.plan = self._parse_plan(response)
        logger.debug("Plan: %s", state.plan)

    def _select_tool_calls(self, state: AgentState) -> list[dict[str, Any]]:
        messages = self._build_messages(state, include_tools=True)
        tool_calls = self.llm.tool_call(messages, self.tools.list_tools())
        return tool_calls or []

    def _execute_tool(self, tool_call: dict[str, Any], state: AgentState) -> Any:
        name = tool_call.get("name", "")
        args = tool_call.get("arguments", {})
        if not self.permissions.is_allowed(name, args):
            logger.warning("Tool %r blocked by permission system.", name)
            return {"error": f"Permission denied for tool '{name}'"}
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'"}
        return self.runner.run(tool, args)

    def _finalize(self, state: AgentState) -> str:
        messages = self._build_messages(state)
        messages.append({"role": "user", "content": "Summarize the final result."})
        return self.llm.generate(messages)

    def _build_messages(self, state: AgentState, include_tools: bool = False) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt(include_tools)},
            {"role": "user", "content": state.prompt},
        ]
        for entry in state.history:
            messages.append(
                {"role": "assistant", "content": f"Tool {entry['tool']} returned: {entry['result']}"}
            )
        return messages

    def _system_prompt(self, include_tools: bool = False) -> str:
        base = (
            "You are SwissAgent, an AI-powered offline development platform assistant. "
            "You help with code generation, build automation, asset pipelines, and development tasks. "
            "Think step-by-step and use available tools to complete tasks."
        )
        if include_tools:
            tool_names = [t["name"] for t in self.tools.list_tools()]
            base += f"\n\nAvailable tools: {', '.join(tool_names)}"
        return base

    @staticmethod
    def _parse_plan(response: str) -> list[str]:
        lines = response.strip().splitlines()
        plan = []
        for line in lines:
            stripped = line.strip().lstrip("0123456789.-) ").strip()
            if stripped:
                plan.append(stripped)
        return plan
