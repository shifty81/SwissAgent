"""Media pipeline — offline asset generation stubs for 2D/3D/audio/video.

Each generator is a stub that can be replaced with a real offline engine:
  - 2D images  → Stable Diffusion / Pillow procedural generation
  - 3D models  → Blender CLI / procedural mesh generation
  - Audio      → pydub / pyttsx3 / SoX
  - Video      → Blender CLI animation render / FFmpeg assembly

All functions write placeholder assets so downstream pipeline stages
continue to work even before real generators are wired up.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_WORKSPACE = Path("workspace") / "sample_project" / "assets"


def _asset_path(category: str, name: str, workspace: str | None = None) -> Path:
    base = Path(workspace) if workspace else _DEFAULT_WORKSPACE
    p = base / category / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# 2D image generation
# ---------------------------------------------------------------------------

def generate_2d_image(
    prompt: str = "placeholder",
    name: str = "placeholder.png",
    workspace: str | None = None,
) -> dict:
    """Generate a 2D image asset (stub — replace with Stable Diffusion)."""
    path = _asset_path("2D", name, workspace)
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (512, 512), color=(60, 90, 120))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), prompt[:60], fill=(255, 255, 255))
        img.save(str(path))
        logger.info("Generated 2D image: %s", path)
        return {"generated": str(path), "engine": "pillow_stub"}
    except ImportError:
        path.write_bytes(b"PNG_PLACEHOLDER")
        return {"generated": str(path), "engine": "placeholder"}


def generate_texture(
    name: str = "texture.png",
    width: int = 512,
    height: int = 512,
    color: tuple = (128, 128, 128),
    workspace: str | None = None,
) -> dict:
    """Generate a solid-colour texture (stub)."""
    path = _asset_path("2D/textures", name, workspace)
    try:
        from PIL import Image
        Image.new("RGB", (width, height), color=color).save(str(path))
        return {"generated": str(path), "size": [width, height]}
    except ImportError:
        path.write_bytes(b"TEXTURE_PLACEHOLDER")
        return {"generated": str(path), "engine": "placeholder"}


def generate_icon(
    name: str = "icon.png",
    size: int = 64,
    workspace: str | None = None,
) -> dict:
    """Generate a placeholder application icon."""
    return generate_texture(name, size, size, workspace=workspace)


# ---------------------------------------------------------------------------
# 3D model generation
# ---------------------------------------------------------------------------

def generate_3d_model(
    name: str = "model.fbx",
    script: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Generate a 3D model via Blender CLI (stub)."""
    path = _asset_path("3D", name, workspace)
    if script:
        import shutil
        import subprocess
        blender = shutil.which("blender")
        if blender:
            script_path = path.parent / "_gen_script.py"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [blender, "--background", "--python", str(script_path)],
                capture_output=True, text=True, timeout=120,
            )
            script_path.unlink(missing_ok=True)
            return {
                "generated": str(path),
                "engine": "blender",
                "returncode": result.returncode,
                "stderr": result.stderr[:500],
            }
    path.write_bytes(b"3D_MODEL_PLACEHOLDER")
    return {"generated": str(path), "engine": "placeholder"}


# ---------------------------------------------------------------------------
# Audio generation
# ---------------------------------------------------------------------------

def generate_audio(
    name: str = "sound.wav",
    text: str = "",
    workspace: str | None = None,
) -> dict:
    """Generate audio (voiceover via pyttsx3 or placeholder WAV)."""
    path = _asset_path("audio", name, workspace)
    if text:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(text, str(path))
            engine.runAndWait()
            return {"generated": str(path), "engine": "pyttsx3", "text": text}
        except Exception as exc:
            logger.warning("pyttsx3 not available: %s", exc)
    path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")  # minimal WAV header stub
    return {"generated": str(path), "engine": "placeholder"}


def generate_sfx(
    name: str = "sfx.wav",
    command: str = "",
    workspace: str | None = None,
) -> dict:
    """Generate a sound effect via SoX command (stub)."""
    path = _asset_path("audio/sfx", name, workspace)
    if command:
        import shutil
        import subprocess
        sox = shutil.which("sox")
        if sox:
            result = subprocess.run(
                command.split(), capture_output=True, text=True, timeout=30
            )
            return {"generated": str(path), "engine": "sox", "returncode": result.returncode}
    path.write_bytes(b"SFX_PLACEHOLDER")
    return {"generated": str(path), "engine": "placeholder"}


# ---------------------------------------------------------------------------
# Video generation
# ---------------------------------------------------------------------------

def generate_video(
    name: str = "video.mp4",
    blend_file: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Render a video via Blender CLI animation render (stub)."""
    path = _asset_path("video", name, workspace)
    if blend_file:
        import shutil
        import subprocess
        blender = shutil.which("blender")
        if blender:
            result = subprocess.run(
                [blender, "--background", blend_file, "--render-anim"],
                capture_output=True, text=True, timeout=300,
            )
            return {
                "generated": str(path),
                "engine": "blender",
                "returncode": result.returncode,
            }
    path.write_bytes(b"VIDEO_PLACEHOLDER")
    return {"generated": str(path), "engine": "placeholder"}


# ---------------------------------------------------------------------------
# Asset index
# ---------------------------------------------------------------------------

def generate_asset_manifest(workspace: str | None = None) -> dict:
    """Walk assets/ and produce a JSON manifest of all generated files."""
    base = Path(workspace) if workspace else _DEFAULT_WORKSPACE
    manifest: dict = {"assets": []}
    if base.exists():
        for p in sorted(base.rglob("*")):
            if p.is_file():
                manifest["assets"].append({
                    "path": str(p.relative_to(base)),
                    "size": p.stat().st_size,
                })
    manifest_path = base / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest": str(manifest_path), "count": len(manifest["assets"])}
