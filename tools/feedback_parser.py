"""Feedback parser — parse build/runtime output and extract actionable errors.

Produces structured suggestions the agent can act on (fix imports, fix
syntax errors, missing dependencies, etc.) without network access.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from core.logger import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------
# Error patterns (language-agnostic first, then language-specific)
# -----------------------------------------------------------------------
_PATTERNS: list[tuple[str, str, str]] = [
    # Python
    (r"ModuleNotFoundError: No module named '([^']+)'", "missing_import", "python"),
    (r"ImportError: (.+)", "import_error", "python"),
    (r"SyntaxError: (.+)", "syntax_error", "python"),
    (r"NameError: name '([^']+)' is not defined", "undefined_name", "python"),
    (r"AttributeError: (.+)", "attribute_error", "python"),
    (r"TypeError: (.+)", "type_error", "python"),
    # C / C++
    (r"error: (.+): No such file or directory", "missing_file", "cpp"),
    (r"undefined reference to `([^']+)'", "undefined_ref", "cpp"),
    (r"error: (.+)", "compile_error", "cpp"),
    # C#
    (r"error CS\d+: (.+)", "cs_compile_error", "csharp"),
    (r"The type or namespace name '([^']+)' could not be found", "cs_missing_type", "csharp"),
    # Java
    (r"error: cannot find symbol\s+symbol:\s+(.+)", "java_missing_symbol", "java"),
    (r"error: (.+)", "java_compile_error", "java"),
    # Rust
    (r"error\[E\d+\]: (.+)", "rust_error", "rust"),
    (r"cannot find value `([^`]+)` in this scope", "rust_undefined", "rust"),
    # Go
    (r"undefined: (.+)", "go_undefined", "go"),
    (r"imported and not used: \"([^\"]+)\"", "go_unused_import", "go"),
    # Generic
    (r"(FAILED|FAILURE|BUILD FAILED)", "build_failed", "generic"),
    (r"warning: (.+)", "warning", "generic"),
]


@dataclass
class ParsedError:
    kind: str
    message: str
    language: str
    suggestion: str = ""
    line: int | None = None


@dataclass
class ParseResult:
    errors: list[ParsedError] = field(default_factory=list)
    warnings: list[ParsedError] = field(default_factory=list)
    has_failures: bool = False

    def summary(self) -> str:
        if not self.errors and not self.warnings:
            return "No errors or warnings detected."
        lines = []
        if self.errors:
            lines.append(f"{len(self.errors)} error(s):")
            for e in self.errors:
                lines.append(f"  [{e.kind}] {e.message}")
                if e.suggestion:
                    lines.append(f"    → {e.suggestion}")
        if self.warnings:
            lines.append(f"{len(self.warnings)} warning(s):")
            for w in self.warnings:
                lines.append(f"  [{w.kind}] {w.message}")
        return "\n".join(lines)


class FeedbackParser:
    """Parse build/runtime output into structured errors with suggestions."""

    def parse(self, log: str) -> ParseResult:
        result = ParseResult()
        for line in log.splitlines():
            self._process_line(line.strip(), result)
        result.has_failures = any(
            e.kind in {"build_failed", "compile_error", "syntax_error",
                       "undefined_ref", "cs_compile_error", "rust_error",
                       "java_compile_error"}
            for e in result.errors
        )
        return result

    def _process_line(self, line: str, result: ParseResult) -> None:
        for pattern, kind, lang in _PATTERNS:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                msg = m.group(1) if m.lastindex else line
                suggestion = self._suggest(kind, msg)
                entry = ParsedError(kind=kind, message=msg, language=lang, suggestion=suggestion)
                if kind == "warning":
                    result.warnings.append(entry)
                else:
                    result.errors.append(entry)
                break

    @staticmethod
    def _suggest(kind: str, message: str) -> str:
        suggestions: dict[str, str] = {
            "missing_import": f"Run: pip install {message.split('.')[-1]}",
            "import_error": "Check that the package is installed and the import path is correct.",
            "syntax_error": "Review the syntax near the indicated line.",
            "undefined_name": f"Define or import '{message}' before use.",
            "missing_file": "Ensure the file/header exists and paths are correct in CMakeLists.",
            "undefined_ref": f"Link the library that provides '{message}'.",
            "cs_missing_type": f"Add a using directive or NuGet reference for '{message}'.",
            "rust_undefined": f"Declare or import '{message}' in scope.",
            "go_unused_import": f"Remove unused import '{message}' or use it.",
            "build_failed": "Review the full build log for earlier error messages.",
        }
        return suggestions.get(kind, "")
