"""Tile module — stub implementation."""
from __future__ import annotations
from core.logger import get_logger

logger = get_logger(__name__)


def _stub(*args, **kwargs):
    return {"status": "not_implemented", "module": "tile"}

def tile_slice(**kwargs) -> dict:
    """[Stub] Slice a tileset image."""
    return {"status": "not_implemented", "tool": "tile_slice"}

def tile_pack(**kwargs) -> dict:
    """[Stub] Pack tiles into a tileset."""
    return {"status": "not_implemented", "tool": "tile_pack"}

def tile_export(**kwargs) -> dict:
    """[Stub] Export tilemap to JSON."""
    return {"status": "not_implemented", "tool": "tile_export"}
