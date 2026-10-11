"""GPT Image Studio local proxy adapter."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.services.video_export.image_providers.gptimage_proxy import GptImageProxyProvider
from app.services.video_export.image_providers.base import ImageRequest

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_unconfigured_without_base_url():
    provider = GptImageProxyProvider(base_url="")
    state = provider.configuration()
    assert state.configured is False
    assert state.missing_config == ("GPTIMAGE_BASE_URL",)


def test_rejects_non_localhost_base_url():
    provider = GptImageProxyProvider(base_url="https://example.com")
    state = provider.configuration()
    assert state.configured is False
    assert "localhost" in (state.detail or "")


def test_localhost_http_is_configured():
    provider = GptImageProxyProvider(base_url="http://127.0.0.1:3000")
    assert provider.configuration().configured is True


@pytest.mark.asyncio
async def test_generate_posts_prompt_and_writes_png(tmp_path: Path):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)
    provider = GptImageProxyProvider(base_url="http://127.0.0.1:3000", transport=transport)
    out = tmp_path / "scene.png"
    result = await provider.generate_image(
        ImageRequest(prompt="Một căn nhà gỗ bên hồ", aspect_ratio="16:9", size="1792x1024"),
        out,
    )
    assert "/api/generate" in captured["url"]
    assert "Một căn nhà gỗ bên hồ" in captured["body"]
    assert "16:9" in captured["body"]
    assert out.is_file()
    assert result.provider == "gptimage"
    assert result.mime_type == "image/png"
    assert result.bytes_written == len(PNG_BYTES)
