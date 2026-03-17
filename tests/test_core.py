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


def test_tool_registry_register():
    from core.tool_registry import ToolRegistry
    reg = ToolRegistry()
    reg.register({"name": "test_tool", "description": "A test tool"}, lambda: "ok")
    assert reg.get("test_tool") is not None
    assert reg.get_callable("test_tool")() == "ok"


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
    assert "hello" in result


def test_llm_factory_local():
    from core.config_loader import ConfigLoader
    from llm.factory import create_llm
    from llm.local import LocalLLM
    cfg = ConfigLoader("configs")
    assert isinstance(create_llm("local", cfg), LocalLLM)
