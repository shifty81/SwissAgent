"""Ui module — stub implementation."""
from __future__ import annotations
from core.logger import get_logger

logger = get_logger(__name__)


def _stub(*args, **kwargs):
    return {"status": "not_implemented", "module": "ui"}

def ui_generate_component(**kwargs) -> dict:
    """[Stub] Generate a UI component."""
    return {"status": "not_implemented", "tool": "ui_generate_component"}

def ui_screenshot(**kwargs) -> dict:
    """[Stub] Screenshot a UI element."""
    return {"status": "not_implemented", "tool": "ui_screenshot"}

def ui_list_components(**kwargs) -> dict:
    """[Stub] List available UI components."""
    return {"status": "not_implemented", "tool": "ui_list_components"}
