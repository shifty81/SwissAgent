"""DEV mode — self-upgrade hook for SwissAgent pipelines.

In DEV mode the agent can inspect and regenerate its own tool implementations,
pipelines, and build runners.  This is intentionally conservative:
  - It creates backups before overwriting.
  - It runs a dry-run by default.
  - Changes are written to a staging area for human review.
"""
from __future__ import annotations
import shutil
from datetime import datetime
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)

_BACKUP_DIR = Path("logs") / "dev_mode_backups"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = _BACKUP_DIR / ts / path.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    return backup


class DevMode:
    """Manages self-upgrade operations for SwissAgent internals."""

    def __init__(self, staging_dir: str | Path = "logs/dev_mode_staging") -> None:
        self.staging_dir = Path(staging_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def upgrade_file(self, target_path: str, new_content: str, dry_run: bool = True) -> dict:
        """Apply an upgrade to a single file.

        Parameters
        ----------
        target_path : str
            Path of the file to upgrade (relative to project root).
        new_content : str
            Replacement content.
        dry_run : bool
            If True (default), write to staging/ only and do NOT overwrite the
            original.  Set to False to apply the change in-place.
        """
        target = Path(target_path)
        staged = self.staging_dir / target.name
        staged.write_text(new_content, encoding="utf-8")
        logger.info("DEV mode: staged upgrade → %s", staged)

        if dry_run:
            return {
                "staged": str(staged),
                "target": str(target),
                "dry_run": True,
                "message": "Dry run — review staging file before applying.",
            }

        backup = _backup(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, target)
        return {
            "applied": str(target),
            "backup": str(backup) if backup else None,
            "dry_run": False,
        }

    def upgrade_build_runner(self, new_content: str, dry_run: bool = True) -> dict:
        """Upgrade tools/build_runner.py."""
        return self.upgrade_file("tools/build_runner.py", new_content, dry_run=dry_run)

    def upgrade_media_pipeline(self, new_content: str, dry_run: bool = True) -> dict:
        """Upgrade tools/media_pipeline.py."""
        return self.upgrade_file("tools/media_pipeline.py", new_content, dry_run=dry_run)

    def upgrade_feedback_parser(self, new_content: str, dry_run: bool = True) -> dict:
        """Upgrade tools/feedback_parser.py."""
        return self.upgrade_file("tools/feedback_parser.py", new_content, dry_run=dry_run)

    def list_staged(self) -> list[str]:
        """Return list of files currently in the staging area."""
        return [str(p) for p in self.staging_dir.iterdir() if p.is_file()]

    def apply_all_staged(self) -> list[dict]:
        """Apply all staged upgrades in-place (use with caution)."""
        results = []
        for staged_file in self.staging_dir.iterdir():
            if not staged_file.is_file():
                continue
            content = staged_file.read_text(encoding="utf-8")
            result = self.upgrade_file(staged_file.name, content, dry_run=False)
            staged_file.unlink()
            results.append(result)
        return results

    def status(self) -> dict:
        staged = self.list_staged()
        return {
            "staging_dir": str(self.staging_dir),
            "staged_files": staged,
            "staged_count": len(staged),
        }
