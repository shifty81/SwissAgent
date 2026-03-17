"""Cache module — disk-based JSON key-value store."""
from __future__ import annotations
import json
import time
from pathlib import Path

_CACHE_DIR = Path("cache")


def _path(key: str) -> Path:
    safe = key.replace("/", "_").replace("\\", "_")
    return _CACHE_DIR / f"{safe}.json"


def cache_get(key: str) -> dict:
    p = _path(key)
    if not p.exists():
        return {"hit": False, "value": None}
    data = json.loads(p.read_text())
    if data.get("ttl") and time.time() > data["ttl"]:
        p.unlink()
        return {"hit": False, "value": None}
    return {"hit": True, "value": data["value"]}


def cache_set(key: str, value: str, ttl: int | None = None) -> dict:
    _CACHE_DIR.mkdir(exist_ok=True)
    data: dict = {"value": value, "created": time.time()}
    if ttl:
        data["ttl"] = time.time() + ttl
    _path(key).write_text(json.dumps(data))
    return {"stored": key}


def cache_delete(key: str) -> dict:
    p = _path(key)
    if p.exists():
        p.unlink()
    return {"deleted": key}


def cache_clear() -> dict:
    count = 0
    for p in _CACHE_DIR.glob("*.json"):
        p.unlink()
        count += 1
    return {"cleared": count}


def cache_stats() -> dict:
    files = list(_CACHE_DIR.glob("*.json"))
    return {"entries": len(files), "total_bytes": sum(f.stat().st_size for f in files)}
