"""Example plugin main script."""
from __future__ import annotations


def example_hello(name: str) -> dict:
    """Return a greeting message."""
    return {"greeting": f"Hello from SwissAgent example plugin, {name}!"}
