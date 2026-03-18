"""
title: SwissAgent IDE Tools
author: SwissAgent
version: 0.1.0
license: MIT
description: >
  Push AI-generated code directly from Open WebUI into your SwissAgent IDE.
  Requires SwissAgent to be running on the same machine (or reachable network).
requirements: requests
"""
import requests


# ── Configuration ──────────────────────────────────────────────────────────────
# Change this if SwissAgent is running on a different host or port.
SWISSAGENT_URL = "http://localhost:8000"


class Tools:
    """Open WebUI tool functions for SwissAgent IDE integration."""

    def push_file_to_ide(self, path: str, content: str) -> str:
        """Write or update a file in the SwissAgent IDE workspace.

        Use this whenever you generate complete file content that the user wants
        to save. The IDE will open the file automatically after the push.

        :param path: Workspace-relative path, e.g. ``workspace/src/main.py``.
                     Must start with ``workspace/`` or ``projects/``.
        :param content: The full text content to write to the file.
        :return: A confirmation message or an error description.
        """
        try:
            r = requests.post(
                f"{SWISSAGENT_URL}/api/ide/push",
                json={"path": path, "content": content, "open_in_editor": True},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                return f"✓ Written {data.get('bytes', '?')} bytes to `{path}` in SwissAgent IDE."
            return f"⚠ SwissAgent returned {r.status_code}: {r.text[:200]}"
        except requests.exceptions.ConnectionError:
            return (
                "⚠ Could not reach SwissAgent IDE at "
                f"{SWISSAGENT_URL}. Is it running?"
            )
        except Exception as exc:
            return f"⚠ Error: {exc}"

    def read_file_from_ide(self, path: str) -> str:
        """Read a file from the SwissAgent IDE workspace.

        Use this to fetch existing code so you can review or modify it.

        :param path: Workspace-relative path, e.g. ``workspace/src/main.py``.
        :return: The file content, or an error message.
        """
        try:
            r = requests.get(
                f"{SWISSAGENT_URL}/files/read",
                params={"path": path},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("content", "")
            return f"⚠ SwissAgent returned {r.status_code}: {r.text[:200]}"
        except requests.exceptions.ConnectionError:
            return (
                "⚠ Could not reach SwissAgent IDE at "
                f"{SWISSAGENT_URL}. Is it running?"
            )
        except Exception as exc:
            return f"⚠ Error: {exc}"

    def list_workspace_files(self, path: str = "workspace") -> str:
        """List files and directories in the SwissAgent workspace.

        :param path: Directory to list (default: ``workspace``).
        :return: A formatted directory listing.
        """
        try:
            r = requests.get(
                f"{SWISSAGENT_URL}/files",
                params={"path": path},
                timeout=10,
            )
            if r.status_code == 200:
                entries = r.json().get("entries", [])
                lines = []
                for e in entries:
                    icon = "📁" if e["type"] == "dir" else "📄"
                    lines.append(f"{icon} {e['name']}")
                return "\n".join(lines) or "(empty)"
            return f"⚠ SwissAgent returned {r.status_code}: {r.text[:200]}"
        except requests.exceptions.ConnectionError:
            return (
                "⚠ Could not reach SwissAgent IDE at "
                f"{SWISSAGENT_URL}. Is it running?"
            )
        except Exception as exc:
            return f"⚠ Error: {exc}"

    def ide_status(self) -> str:
        """Check whether the SwissAgent IDE is reachable and return its status.

        :return: Status string.
        """
        try:
            r = requests.get(f"{SWISSAGENT_URL}/api/ide/status", timeout=5)
            if r.status_code == 200:
                d = r.json()
                return (
                    f"✓ SwissAgent IDE is running — "
                    f"version {d.get('version', '?')}, "
                    f"{d.get('tools', '?')} tools loaded."
                )
            return f"⚠ SwissAgent returned {r.status_code}"
        except requests.exceptions.ConnectionError:
            return f"⚠ SwissAgent IDE is not reachable at {SWISSAGENT_URL}"
        except Exception as exc:
            return f"⚠ Error: {exc}"
