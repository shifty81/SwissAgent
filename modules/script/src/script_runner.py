"""Script runner module implementation."""
from __future__ import annotations
import subprocess
import sys


def _run(cmd: list[str], cwd: str | None = None) -> dict:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def run_python(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    return _run([sys.executable, path] + (args or []), cwd=cwd)


def run_shell(path: str, args: list[str] | None = None, cwd: str | None = None) -> dict:
    return _run(["bash", path] + (args or []), cwd=cwd)


def run_lua(path: str, args: list[str] | None = None) -> dict:
    return _run(["lua", path] + (args or []))


def run_node(path: str, args: list[str] | None = None) -> dict:
    return _run(["node", path] + (args or []))


def eval_python(code: str) -> dict:
    import io
    from contextlib import redirect_stdout, redirect_stderr
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    local_ns: dict = {}
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, local_ns)  # noqa: S102
        return {"stdout": stdout_buf.getvalue(), "stderr": stderr_buf.getvalue(), "returncode": 0}
    except Exception as exc:
        return {"stdout": stdout_buf.getvalue(), "stderr": str(exc), "returncode": 1}
