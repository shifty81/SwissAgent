"""Stable Diffusion interface — offline 2D image generation stub.

Replace the body of ``generate`` with a real diffusers pipeline when an
offline model is available.  The stub writes a Pillow-generated placeholder
so the rest of the pipeline continues to work without a GPU.
"""
from __future__ import annotations
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


class StableDiffusionInterface:
    """Offline Stable Diffusion image generator.

    Parameters
    ----------
    model_path : str | None
        Path to the local diffusers checkpoint directory.
        If None, the stub mode is used.
    device : str
        Torch device string (``"cuda"``, ``"cpu"``, etc.).
    """

    def __init__(self, model_path: str | None = None, device: str = "cpu") -> None:
        self.model_path = model_path
        self.device = device
        self._pipe = None
        if model_path:
            self._load_pipeline(model_path, device)

    def _load_pipeline(self, model_path: str, device: str) -> None:
        try:
            from diffusers import StableDiffusionPipeline
            import torch
            self._pipe = StableDiffusionPipeline.from_pretrained(
                model_path,
                torch_dtype=torch.float16 if "cuda" in device else torch.float32,
            ).to(device)
            logger.info("Stable Diffusion pipeline loaded from %s on %s", model_path, device)
        except ImportError:
            logger.warning("diffusers / torch not installed — running in stub mode.")
        except Exception as exc:
            logger.error("Failed to load Stable Diffusion pipeline: %s", exc)

    def generate(
        self,
        prompt: str,
        output_path: str,
        width: int = 512,
        height: int = 512,
        steps: int = 20,
        guidance: float = 7.5,
    ) -> dict:
        """Generate an image from a text prompt.

        Returns
        -------
        dict with keys ``generated`` (output path) and ``engine`` (used backend).
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if self._pipe is not None:
            try:
                image = self._pipe(
                    prompt,
                    width=width,
                    height=height,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                ).images[0]
                image.save(str(out))
                return {"generated": str(out), "engine": "stable_diffusion", "prompt": prompt}
            except Exception as exc:
                logger.error("Generation failed: %s", exc)

        # Stub fallback — generate a labelled placeholder with Pillow
        return self._stub_generate(prompt, out, width, height)

    @staticmethod
    def _stub_generate(prompt: str, out: Path, width: int, height: int) -> dict:
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (width, height), color=(45, 60, 80))
            draw = ImageDraw.Draw(img)
            draw.rectangle([10, 10, width - 10, height - 10], outline=(100, 140, 180), width=2)
            draw.text((20, 20), "[SD Stub]", fill=(200, 200, 200))
            draw.text((20, 45), prompt[:60], fill=(180, 220, 255))
            img.save(str(out))
            return {"generated": str(out), "engine": "pillow_stub", "prompt": prompt}
        except ImportError:
            out.write_bytes(b"SD_PLACEHOLDER")
            return {"generated": str(out), "engine": "placeholder", "prompt": prompt}
