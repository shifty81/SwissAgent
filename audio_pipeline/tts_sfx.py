"""Audio pipeline — offline TTS, SFX, and music generation.

Backends (in order of preference):
  1. pyttsx3 (TTS, system voice, fully offline)
  2. pydub + synthesised tone (SFX stub)
  3. SoX command-line tool (SFX / conversion)
  4. Raw WAV placeholder (always works)
"""
from __future__ import annotations
import struct
import subprocess
import shutil
import math
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_placeholder_wav(path: Path) -> None:
    """Write a minimal valid 1-second silent WAV file."""
    sample_rate = 44100
    num_samples = sample_rate
    data_size = num_samples * 2  # 16-bit mono
    with path.open("wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)


def _write_tone_wav(path: Path, frequency: float = 440.0, duration: float = 1.0) -> None:
    """Write a simple sine-wave tone WAV file (no external deps)."""
    sample_rate = 44100
    num_samples = int(sample_rate * duration)
    data_size = num_samples * 2
    with path.open("wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        for i in range(num_samples):
            sample = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
            f.write(struct.pack("<h", sample))


class AudioPipeline:
    """Offline audio generation: TTS, SFX, and music stubs."""

    # ------------------------------------------------------------------
    # Text-to-speech
    # ------------------------------------------------------------------

    def generate_tts(
        self,
        text: str,
        output_path: str,
        rate: int = 150,
        volume: float = 1.0,
    ) -> dict:
        """Convert text to speech using pyttsx3 (offline) or a placeholder."""
        out = Path(output_path)
        _ensure_dir(out)
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", rate)
            engine.setProperty("volume", volume)
            engine.save_to_file(text, str(out))
            engine.runAndWait()
            return {"generated": str(out), "engine": "pyttsx3", "text": text}
        except Exception as exc:
            logger.warning("pyttsx3 unavailable: %s — using placeholder.", exc)
        _write_placeholder_wav(out)
        return {"generated": str(out), "engine": "placeholder", "text": text}

    # ------------------------------------------------------------------
    # Sound effects
    # ------------------------------------------------------------------

    def generate_sfx(
        self,
        name: str,
        output_path: str,
        frequency: float = 440.0,
        duration: float = 0.5,
        sox_command: str | None = None,
    ) -> dict:
        """Generate a sound effect.

        Uses SoX if available, otherwise synthesises a tone directly.
        """
        out = Path(output_path)
        _ensure_dir(out)

        if sox_command:
            sox = shutil.which("sox")
            if sox:
                result = subprocess.run(
                    sox_command.split(), capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    return {"generated": str(out), "engine": "sox", "name": name}
                logger.warning("sox command failed: %s", result.stderr)

        _write_tone_wav(out, frequency=frequency, duration=duration)
        return {"generated": str(out), "engine": "tone_stub", "name": name,
                "frequency": frequency, "duration": duration}

    # ------------------------------------------------------------------
    # Audio conversion
    # ------------------------------------------------------------------

    def convert(self, src: str, dst: str, fmt: str = "wav") -> dict:
        """Convert audio format using FFmpeg or pydub."""
        out = Path(dst)
        _ensure_dir(out)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            result = subprocess.run(
                [ffmpeg, "-y", "-i", src, str(out)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return {"converted": str(out), "engine": "ffmpeg"}
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(src)
            audio.export(str(out), format=fmt)
            return {"converted": str(out), "engine": "pydub"}
        except Exception as exc:
            logger.warning("pydub unavailable: %s", exc)
        return {"error": "No audio conversion backend available", "src": src}

    # ------------------------------------------------------------------
    # Music / ambient placeholder
    # ------------------------------------------------------------------

    def generate_music_placeholder(self, output_path: str, duration: float = 5.0) -> dict:
        """Write a multi-tone ambient music placeholder."""
        out = Path(output_path)
        _ensure_dir(out)
        _write_tone_wav(out, frequency=220.0, duration=duration)
        return {"generated": str(out), "engine": "tone_stub", "duration": duration}
