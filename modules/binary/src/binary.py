"""Binary module — stub implementation."""
from __future__ import annotations
from core.logger import get_logger

logger = get_logger(__name__)


def _stub(*args, **kwargs):
    return {"status": "not_implemented", "module": "binary"}

def binary_info(**kwargs) -> dict:
    """[Stub] Get binary file info."""
    return {"status": "not_implemented", "tool": "binary_info"}

def binary_disasm(**kwargs) -> dict:
    """[Stub] Disassemble binary code."""
    return {"status": "not_implemented", "tool": "binary_disasm"}

def binary_strings(**kwargs) -> dict:
    """[Stub] Extract strings from binary."""
    return {"status": "not_implemented", "tool": "binary_strings"}

def binary_patch(**kwargs) -> dict:
    """[Stub] Patch bytes in a binary."""
    return {"status": "not_implemented", "tool": "binary_patch"}

def binary_hex(**kwargs) -> dict:
    """[Stub] Hex dump of binary file."""
    return {"status": "not_implemented", "tool": "binary_hex"}
