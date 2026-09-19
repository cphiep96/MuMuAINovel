"""Meta Muse Image 1.0 provider for vertical novel covers.

The scene-image provider already contains the transport, response validation, and
base64/URL safety checks for Meta Muse.  Covers use the same API contract but
request Muse's portrait size (1024x1792), which is the closest supported size to
the cover service's 2:3 canvas.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.cover_providers.base_cover_provider import (
    BaseCoverProvider,
    CoverGenerationResult,
)


class MetaMuseCoverProvider(BaseCoverProvider):
    """Generate a book cover with Meta Model API's Muse Image 1.0 model."""

    name = "meta_muse"
    default_base_url = "https://api.meta.ai/v1"
    default_model = "muse-image-1.0"
    portrait_size = "1024x1792"

    def __init__(self, api_key: str, base_url: str):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or self.default_base_url).rstrip("/")

    async def generate_cover(
        self,
        *,
        prompt: str,
        model: str,
        width: int,
        height: int,
    ) -> CoverGenerationResult:
        # Import lazily: the video-export package imports the cover path helper,
        # so importing it at module load time would create a circular import.
        from app.services.video_export.image_providers.base import ImageRequest
        from app.services.video_export.image_providers.meta_muse_image import MetaMuseImageProvider

        del width, height  # Muse accepts a fixed portrait size for this provider.

        cover_prompt = (
            f"{(prompt or '').strip()}\n\n"
            "Compose this as a polished vertical 9:16 novel cover illustration. "
            "Keep the focal subject and important details in the central safe area. "
            "Do not render a title, author name, logo, watermark, or other text."
        ).strip()
        if not cover_prompt:
            raise ValueError("Thiếu prompt cho ảnh bìa")

        provider = MetaMuseImageProvider(
            api_key=self.api_key,
            base_url=self.base_url,
            model=(model or self.default_model).strip() or self.default_model,
            output_format="webp",
            reasoning_strengths="low,high",
        )

        # Meta Muse returns the image through the scene-provider contract.  A
        # temporary file lets us reuse its strict magic-byte/size validation,
        # while the cover service still receives the bytes it expects.
        with tempfile.TemporaryDirectory(prefix="mumu-cover-") as temp_dir:
            output_path = Path(temp_dir) / "cover.webp"
            result = await provider.generate_image(
                ImageRequest(
                    prompt=cover_prompt,
                    aspect_ratio="9:16",
                    size=self.portrait_size,
                    model=(model or self.default_model).strip() or self.default_model,
                    reasoning_strength="low",
                ),
                output_path,
            )
            content = output_path.read_bytes()
            extension = output_path.suffix.lstrip(".").lower() or "webp"

        return {
            "content": content,
            "mime_type": result.mime_type,
            "file_extension": extension,
            "revised_prompt": None,
            "provider": self.name,
            "model": result.model,
        }
