"""Core module tests."""
from __future__ import annotations
import pytest


def test_config_loader_get_default():
    from core.config_loader import ConfigLoader
    cfg = ConfigLoader("configs")
    assert cfg.get("missing.key", "fallback") == "fallback"


def test_config_loader_set_get():
    from core.config_loader import ConfigLoader
    cfg = ConfigLoader("configs")
    cfg.set("test.key", "value")
    assert cfg.get("test.key") == "value"


def test_permission_system_allow():
    from core.permission import PermissionSystem
    ps = PermissionSystem()
    assert ps.is_allowed("read_file", {"path": "workspace/test.txt"})


def test_permission_system_block_tool():
    from core.permission import PermissionSystem
    ps = PermissionSystem()
    ps.block_tool("delete_file")
    assert not ps.is_allowed("delete_file", {})


def test_permission_system_args_list_does_not_crash():
    """is_allowed must not raise when args is a list (LLM mis-format)."""
    from core.permission import PermissionSystem
    ps = PermissionSystem()
    # Should not raise 'list' object has no attribute 'values'
    assert ps.is_allowed("read_file", ["workspace/file.txt"])  # type: ignore[arg-type]


def test_permission_system_args_string_does_not_crash():
    """is_allowed must not raise when args is a plain string."""
    from core.permission import PermissionSystem
    ps = PermissionSystem()
    assert ps.is_allowed("read_file", "workspace/file.txt")  # type: ignore[arg-type]


def test_tool_registry_register():
    from core.tool_registry import ToolRegistry
    reg = ToolRegistry()
    reg.register({"name": "test_tool", "description": "A test tool"}, lambda: "ok")
    assert reg.get("test_tool") is not None
    assert reg.get_callable("test_tool")() == "ok"
    # get() should embed the callable under _callable for TaskRunner
    tool = reg.get("test_tool")
    assert tool is not None and tool.get("_callable") is not None
    assert tool["_callable"]() == "ok"


def test_tool_registry_get_callable_missing():
    from core.tool_registry import ToolRegistry
    reg = ToolRegistry()
    reg.register({"name": "no_func_tool"})
    assert reg.get_callable("no_func_tool") is None
    assert reg.get_callable("nonexistent") is None


def test_tool_registry_list():
    from core.tool_registry import ToolRegistry
    reg = ToolRegistry()
    reg.register({"name": "tool_a"})
    reg.register({"name": "tool_b"})
    names = [t["name"] for t in reg.list_tools()]
    assert "tool_a" in names and "tool_b" in names


def test_llm_local_stub():
    from llm.local import LocalLLM
    llm = LocalLLM()
    result = llm.chat([{"role": "user", "content": "hello"}])
    # Stub now returns a helpful setup message instead of echoing the input
    assert "[LocalLLM stub] Received:" not in result
    assert "LLM" in result or "backend" in result or "Ollama" in result


def test_llm_factory_local():
    from core.config_loader import ConfigLoader
    from llm.factory import create_llm
    from llm.local import LocalLLM
    cfg = ConfigLoader("configs")
    assert isinstance(create_llm("local", cfg), LocalLLM)


def test_agent_execute_tool_list_args():
    """_execute_tool must not crash when LLM returns arguments as a list."""
    from unittest.mock import MagicMock
    from core.agent import Agent
    from core.tool_registry import ToolRegistry
    from core.permission import PermissionSystem
    from core.task_runner import TaskRunner
    from core.config_loader import ConfigLoader

    registry = ToolRegistry()
    captured = {}

    def my_tool(**kwargs):
        captured.update(kwargs)
        return "ok"

    registry.register(
        {"name": "my_tool", "description": "test", "arguments": {"type": "object", "properties": {}}},
        my_tool,
    )

    llm = MagicMock()
    llm.chat.return_value = ""
    llm.generate.return_value = "done"
    llm.tool_call.return_value = []

    agent = Agent(llm, registry, PermissionSystem(), TaskRunner(), ConfigLoader("configs"))

    # Simulate a tool call where 'arguments' came back as a list (LLM mis-format)
    state = MagicMock()
    result = agent._execute_tool({"name": "my_tool", "arguments": ["bad", "list"]}, state)
    # Should not raise; tool is called with no kwargs (args coerced to {})
    assert result == "ok"


def test_agent_system_prompt_includes_schemas():
    """_system_prompt(include_tools=True) must include argument names and descriptions."""
    from unittest.mock import MagicMock
    from core.agent import Agent
    from core.tool_registry import ToolRegistry
    from core.permission import PermissionSystem
    from core.task_runner import TaskRunner
    from core.config_loader import ConfigLoader

    registry = ToolRegistry()
    registry.register({
        "name": "greet",
        "description": "Say hello to someone",
        "arguments": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    })

    llm = MagicMock()
    agent = Agent(llm, registry, PermissionSystem(), TaskRunner(), ConfigLoader("configs"))
    prompt = agent._system_prompt(include_tools=True)

    assert "greet" in prompt
    assert "Say hello to someone" in prompt
    assert "name" in prompt


def test_ollama_tool_call_prompt_includes_schemas():
    """OllamaLLM.tool_call must build a prompt that includes argument schemas."""
    from unittest.mock import MagicMock, patch
    from llm.ollama import OllamaLLM

    llm = OllamaLLM()
    tools = [
        {
            "name": "write_file",
            "description": "Write content to a file",
            "arguments": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        }
    ]

    captured_messages = []

    def fake_chat(messages):
        captured_messages.extend(messages)
        return "[]"

    llm.chat = fake_chat
    llm.tool_call([{"role": "user", "content": "hi"}], tools)

    system_msg = next(m for m in captured_messages if m["role"] == "system")
    assert "write_file" in system_msg["content"]
    assert "path" in system_msg["content"]
    assert "content" in system_msg["content"]
    assert "Write content to a file" in system_msg["content"]
