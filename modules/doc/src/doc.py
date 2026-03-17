"""Doc module — stub implementation."""
from __future__ import annotations
from core.logger import get_logger

logger = get_logger(__name__)


def _stub(*args, **kwargs):
    return {"status": "not_implemented", "module": "doc"}

def doc_generate(**kwargs) -> dict:
    """[Stub] Generate documentation."""
    return {"status": "not_implemented", "tool": "doc_generate"}

def doc_serve(**kwargs) -> dict:
    """[Stub] Serve documentation locally."""
    return {"status": "not_implemented", "tool": "doc_serve"}

def doc_lint(**kwargs) -> dict:
    """[Stub] Lint documentation."""
    return {"status": "not_implemented", "tool": "doc_lint"}
