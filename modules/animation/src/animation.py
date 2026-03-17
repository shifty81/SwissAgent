"""Animation module — stub implementation."""
from __future__ import annotations
from core.logger import get_logger

logger = get_logger(__name__)


def _stub(*args, **kwargs):
    return {"status": "not_implemented", "module": "animation"}

def anim_import(**kwargs) -> dict:
    """[Stub] Import animation data."""
    return {"status": "not_implemented", "tool": "anim_import"}

def anim_export(**kwargs) -> dict:
    """[Stub] Export animation data."""
    return {"status": "not_implemented", "tool": "anim_export"}

def anim_bake(**kwargs) -> dict:
    """[Stub] Bake animation curves."""
    return {"status": "not_implemented", "tool": "anim_bake"}

def anim_retarget(**kwargs) -> dict:
    """[Stub] Retarget animation to skeleton."""
    return {"status": "not_implemented", "tool": "anim_retarget"}
