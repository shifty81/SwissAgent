"""Build tools — CMake/Make/Ninja and custom build system integration."""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> dict:
    """Run a subprocess command and return a result dict."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": " ".join(cmd),
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Executable not found: {cmd[0]}",
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Build timed out after {timeout}s",
            "command": " ".join(cmd),
        }


def build_cmake(
    source_dir: str,
    build_dir: str,
    generator: str | None = None,
    extra_args: list[str] | None = None,
) -> dict:
    """Configure and build a CMake project.

    Parameters
    ----------
    source_dir : str
        Path to the directory containing CMakeLists.txt.
    build_dir : str
        Path to the directory where CMake will write build files.
    generator : str | None
        Optional CMake generator (e.g. ``"Ninja"``, ``"Unix Makefiles"``).
        If None, CMake picks the platform default.
    extra_args : list[str] | None
        Additional arguments forwarded to the ``cmake`` configure step.

    Returns
    -------
    dict
        ``{"returncode": int, "stdout": str, "stderr": str, "command": str}``
    """
    if not shutil.which("cmake"):
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "cmake not found in PATH",
            "command": "cmake",
        }

    src = Path(source_dir)
    bld = Path(build_dir)

    if not src.exists():
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": f"Source directory does not exist: {source_dir}",
            "command": "cmake",
        }

    bld.mkdir(parents=True, exist_ok=True)

    configure_cmd = ["cmake", str(src), "-B", str(bld)]
    if generator:
        configure_cmd += ["-G", generator]
    if extra_args:
        configure_cmd += extra_args

    configure_result = _run(configure_cmd)
    if configure_result["returncode"] != 0:
        return configure_result

    build_result = _run(["cmake", "--build", str(bld)])
    return build_result


def build_make(
    build_dir: str,
    target: str | None = None,
    jobs: int | None = None,
) -> dict:
    """Run ``make`` in *build_dir*.

    Parameters
    ----------
    build_dir : str
        Directory containing a Makefile.
    target : str | None
        Optional make target (e.g. ``"install"``).  Defaults to the default
        target.
    jobs : int | None
        Number of parallel jobs (``-j`` flag).  If None, uses ``-j4``.

    Returns
    -------
    dict
        ``{"returncode": int, "stdout": str, "stderr": str, "command": str}``
    """
    if not shutil.which("make"):
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "make not found in PATH",
            "command": "make",
        }

    cmd = ["make", f"-j{jobs if jobs else 4}"]
    if target:
        cmd.append(target)

    return _run(cmd, cwd=build_dir)


def build_ninja(build_dir: str, target: str | None = None) -> dict:
    """Run ``ninja`` in *build_dir*.

    Parameters
    ----------
    build_dir : str
        Directory containing a ``build.ninja`` file.
    target : str | None
        Optional ninja target.

    Returns
    -------
    dict
        ``{"returncode": int, "stdout": str, "stderr": str, "command": str}``
    """
    if not shutil.which("ninja"):
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "ninja not found in PATH",
            "command": "ninja",
        }

    cmd = ["ninja"]
    if target:
        cmd.append(target)

    return _run(cmd, cwd=build_dir)


def build_custom(workspace: str, command: str) -> dict:
    """Run an arbitrary build command inside *workspace*.

    Parameters
    ----------
    workspace : str
        Working directory for the command.
    command : str
        Shell command string to execute (split on whitespace).

    Returns
    -------
    dict
        ``{"returncode": int, "stdout": str, "stderr": str, "command": str}``
    """
    parts = command.split()
    if not parts:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "Empty command",
            "command": "",
        }
    return _run(parts, cwd=workspace)
