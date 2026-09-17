"""Meta Muse Image 适配器 + 场景图流水线的本地测试（全部使用 mock HTTP，不调用付费 API）

覆盖：
- provider 配置/能力输出（只暴露缺失的 env 名，绝不泄露 key）
- 请求形状（endpoint/base/bearer/body/size/response_format）与 b64 解析的严格校验
- 异常 base64、错误 magic bytes、超限图片、HTTP 错误/重试、取消、URL fallback（SSRF + 不漏 key）
- service 层参数校验（未配置 → 503，禁止静默换 provider）
- 流水线：Meta 生成 `assets/scene_XXX.webp` → motion provider 收到该文件作为 reference；
  未开启时保持旧行为；retry 不重复生成成功图片；失败/清理路径
- API：capabilities 暴露 image_providers、create job 缺配置 → 503、响应不泄露内部字段

运行：cd backend && python -m pytest tests/test_video_export_image_providers.py -q
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.video_export import VideoExportJob, VideoExportScene
from app.services.video_export import ffmpeg_runner
from app.services.video_export.image_providers import (
    IMAGE_STATUS_FAILED,
    IMAGE_STATUS_PENDING,
    IMAGE_STATUS_READY,
    ImageCancelledError,
    ImageConfigError,
    ImageProviderError,
    ImageRequest,
    ImageRequestError,
    MetaMuseImageProvider,
    build_image_provider,
    detect_image_magic,
    list_image_provider_capabilities,
    output_extension,
    validate_provider_base_url,
)
from app.services.video_export.service import (
    normalize_image_options,
    serialize_job,
    serialize_scene,
    video_export_service,
)

TEST_API_KEY = "meta-test-key-not-real"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + (64).to_bytes(4, "little") + b"WEBP" + b"\x00" * 48
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _b64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def image_settings(monkeypatch):
    """统一配置：清空凭证、缩短重试，避免测试串味"""
    monkeypatch.setattr(settings, "meta_muse_api_key", None)
    monkeypatch.setattr(settings, "model_api_key", None)
    monkeypatch.setattr(settings, "meta_muse_base_url", "https://api.meta.ai/v1")
    monkeypatch.setattr(settings, "meta_muse_model", "muse-image-1.0")
    monkeypatch.setattr(settings, "meta_muse_output_format", "webp")
    monkeypatch.setattr(settings, "meta_muse_reasoning_strengths", "low,high")
    monkeypatch.setattr(settings, "video_image_enabled", True)
    monkeypatch.setattr(settings, "video_image_provider", None)
    monkeypatch.setattr(settings, "video_image_model", None)
    monkeypatch.setattr(settings, "video_image_aspect_ratio", None)
    monkeypatch.setattr(settings, "video_image_reasoning_strength", None)
    monkeypatch.setattr(settings, "video_image_timeout_seconds", 30)
    monkeypatch.setattr(settings, "video_image_max_retries", 0)
    monkeypatch.setattr(settings, "video_image_retry_delay_seconds", 0.01)
    monkeypatch.setattr(settings, "video_image_max_mb", 16)
    monkeypatch.setattr(settings, "image_allow_insecure_localhost", True)
    return settings


def _provider(handler, **kwargs) -> MetaMuseImageProvider:
    return MetaMuseImageProvider(transport=httpx.MockTransport(handler), **kwargs)


def _request(tmp_path: Path, **overrides) -> ImageRequest:
    payload = {
        "prompt": "Một căn nhà gỗ bên hồ, sương sớm",
        "aspect_ratio": "16:9",
        "size": "1792x1024",
        "model": None,
        "reasoning_strength": None,
    }
    payload.update(overrides)
    return ImageRequest(**payload)


# --------------------------------------------------------------------------- 配置 / 能力


def test_unconfigured_provider_reports_only_env_names():
    state = MetaMuseImageProvider(api_key="").configuration()
    assert state.configured is False
    assert state.missing_config == ("META_MUSE_API_KEY",)
    assert "MODEL_API_KEY" in (state.detail or ""), "có thể gợi ý alias nhưng không trả giá trị"

    provider = MetaMuseImageProvider(api_key="")
    capabilities = provider.capabilities()
    assert capabilities["configured"] is False
    assert capabilities["missing_config"] == ["META_MUSE_API_KEY"]
    assert capabilities["models"] == ["muse-image-1.0"]
    assert capabilities["sizes"] == ["1792x1024", "1024x1792", "1024x1024"]
    assert capabilities["cost_note"]


def test_alias_model_api_key_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", TEST_API_KEY)
    provider = MetaMuseImageProvider()
    assert provider.configuration().configured is True


def test_capabilities_never_expose_key(monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    payload = json.dumps(list_image_provider_capabilities(), ensure_ascii=False)
    assert TEST_API_KEY not in payload
    assert "api_key" not in payload


@pytest.mark.parametrize(
    "url",
    [
        "http://api.evil.example.com/v1",
        "https://user:pass@api.meta.ai/v1",
        "ftp://api.meta.ai/v1",
        "",
        "https:///v1",
    ],
)
def test_base_url_validation_rejects_unsafe_values(url):
    with pytest.raises(ImageConfigError):
        validate_provider_base_url(url, allow_insecure_localhost=False)


def test_base_url_allows_localhost_only_in_dev():
    assert validate_provider_base_url("http://127.0.0.1:8080/v1", allow_insecure_localhost=True)
    with pytest.raises(ImageConfigError):
        validate_provider_base_url("http://127.0.0.1:8080/v1", allow_insecure_localhost=False)
    assert validate_provider_base_url("https://api.meta.ai/v1/", allow_insecure_localhost=False) == (
        "https://api.meta.ai/v1"
    )


def test_provider_with_invalid_base_url_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    provider = MetaMuseImageProvider(base_url="http://api.meta.ai/v1")
    state = provider.configuration()
    assert state.configured is False
    assert state.missing_config == ("META_MUSE_BASE_URL",)
    assert TEST_API_KEY not in (state.detail or "")


def test_registry_rejects_unknown_provider():
    with pytest.raises(ImageConfigError):
        build_image_provider("not_a_provider")
    assert output_extension(MetaMuseImageProvider(api_key="k")) == ".webp"


# --------------------------------------------------------------------------- 请求形状


@pytest.mark.asyncio
async def test_submit_request_shape_and_b64_response(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": _b64(WEBP_BYTES)}]})

    provider = _provider(handler)
    out_path = tmp_path / "assets" / "scene_000.webp"
    result = await provider.generate_image(_request(tmp_path), out_path)

    assert captured["url"] == "https://api.meta.ai/v1/images/generations"
    assert captured["auth"] == f"Bearer {TEST_API_KEY}"
    assert captured["content_type"] == "application/json"
    assert captured["body"] == {
        "model": "muse-image-1.0",
        "prompt": "Một căn nhà gỗ bên hồ, sương sớm",
        "n": 1,
        "size": "1792x1024",
        "response_format": "b64_json",
        "output_format": "webp",
    }
    assert out_path.is_file() and out_path.read_bytes() == WEBP_BYTES
    assert not out_path.with_name(out_path.name + ".part").exists()
    assert result.mime_type == "image/webp"
    assert result.size == "1792x1024"
    assert result.bytes_written == len(WEBP_BYTES)
    # không trả về đường dẫn hệ thống hay base64 trong kết quả
    assert not hasattr(result, "b64_json")


@pytest.mark.asyncio
async def test_reasoning_strength_is_optional(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": _b64(PNG_BYTES)}]})

    provider = _provider(handler)
    await provider.generate_image(_request(tmp_path), tmp_path / "a.webp")
    assert "reasoning_strength" not in bodies[0]

    await provider.generate_image(_request(tmp_path, reasoning_strength="HIGH"), tmp_path / "b.webp")
    assert bodies[1]["reasoning_strength"] == "high"


@pytest.mark.asyncio
async def test_invalid_reasoning_strength_is_rejected():
    provider = _provider(lambda _request: httpx.Response(200, json={}))
    with pytest.raises(ImageRequestError):
        provider.normalize_reasoning_strength("turbo")


@pytest.mark.parametrize(
    "aspect, expected_size",
    [("16:9", "1792x1024"), ("9:16", "1024x1792"), ("1:1", "1024x1024")],
)
def test_size_follows_aspect_ratio(aspect, expected_size):
    provider = _provider(lambda _request: httpx.Response(200, json={}))
    assert provider.normalize_size(None, aspect) == expected_size


def test_client_cannot_request_arbitrary_size():
    provider = _provider(lambda _request: httpx.Response(200, json={}))
    with pytest.raises(ImageRequestError):
        provider.normalize_size("9999x9999", "16:9")
    with pytest.raises(ImageRequestError):
        provider.normalize_aspect_ratio("4:3")


@pytest.mark.asyncio
async def test_output_format_png_configures_payload_and_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "meta_muse_output_format", "png")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": _b64(PNG_BYTES)}]})

    provider = _provider(handler)
    assert output_extension(provider) == ".png"
    result = await provider.generate_image(_request(tmp_path), tmp_path / "scene.png")
    assert bodies[0]["output_format"] == "png"
    assert result.mime_type == "image/png"


# --------------------------------------------------------------------------- b64 / magic bytes 校验


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"data": []}, "không trả về ảnh"),
        ({"data": [{}]}, "không trả về b64_json hoặc URL"),
        ({"data": [{"b64_json": ""}]}, "dữ liệu rỗng"),
        ({"data": [{"b64_json": "!!!!not-base64!!!"}]}, "base64 không hợp lệ"),
        ({"data": [{"b64_json": _b64(b"GIF89a-not-supported")}]}, "magic bytes"),
        ({"data": [{"b64_json": _b64(b"<html>gateway</html>")}]}, "magic bytes"),
        ({"error": {"message": "rate limited"}}, "rate limited"),
    ],
)
async def test_malformed_responses_fail_clearly(tmp_path, monkeypatch, payload, expected):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    provider = _provider(lambda _request: httpx.Response(200, json=payload))
    out_path = tmp_path / "scene.webp"
    with pytest.raises(ImageProviderError) as exc:
        await provider.generate_image(_request(tmp_path), out_path)
    assert expected in str(exc.value)
    assert TEST_API_KEY not in str(exc.value)
    assert not out_path.exists(), "không được ghi ảnh lỗi ra đĩa"
    assert not out_path.with_name(out_path.name + ".part").exists()


@pytest.mark.asyncio
async def test_oversized_image_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "video_image_max_mb", 1)
    big = PNG_BYTES + b"\x00" * (2 * 1024 * 1024)
    provider = _provider(lambda _request: httpx.Response(200, json={"data": [{"b64_json": _b64(big)}]}))
    with pytest.raises(ImageProviderError) as exc:
        await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")
    assert "vượt giới hạn dung lượng" in str(exc.value)


def test_detect_image_magic():
    assert detect_image_magic(PNG_BYTES[:16]) == "png"
    assert detect_image_magic(JPEG_BYTES[:16]) == "jpeg"
    assert detect_image_magic(WEBP_BYTES[:16]) == "webp"
    assert detect_image_magic(b"GIF89a") is None
    assert detect_image_magic(b"RIFFxxxxNOPE") is None


# --------------------------------------------------------------------------- sanitize（không lộ key/URL/path）


@pytest.mark.parametrize(
    "raw, leaked",
    [
        (f"invalid api_key={TEST_API_KEY}", TEST_API_KEY),
        (f"Authorization: Bearer {TEST_API_KEY}", TEST_API_KEY),
        ("fetch https://api.meta.ai/v1/images/generations?key=abc failed", "api.meta.ai"),
        ("cannot write /storage/generated_videos/user-1/job-1/assets/scene_000.webp", "/storage/"),
        ("path C:\\Users\\secret\\scene.webp not writable", "C:\\Users"),
        ("data:image/png;base64," + _b64(PNG_BYTES), "iVBOR"),
        ("token " + "A" * 48, "A" * 24),
    ],
)
def test_sanitize_message_masks_secrets_urls_and_paths(raw, leaked):
    from app.services.video_export.providers.errors import sanitize_message

    cleaned = sanitize_message(raw)
    assert leaked not in cleaned
    assert "<" in cleaned, "nội dung nhạy cảm phải được thay bằng placeholder"


def test_sanitize_message_keeps_env_var_names_readable():
    """Tên biến môi trường không phải bí mật: phải giữ nguyên để admin biết cần cấu hình gì"""
    from app.services.video_export.providers.errors import sanitize_message

    message = "Thiếu cấu hình: VIDEO_MOTION_OPENAI_BASE_URL và VIDEO_MOTION_GEMINI_API_KEY"
    cleaned = sanitize_message(message)
    assert "VIDEO_MOTION_OPENAI_BASE_URL" in cleaned
    assert "VIDEO_MOTION_GEMINI_API_KEY" in cleaned


def test_sanitize_message_masks_known_secret_value():
    from app.services.video_export.providers.errors import sanitize_message

    cleaned = sanitize_message(f"upstream said key {TEST_API_KEY} invalid", secrets=(TEST_API_KEY,))
    assert TEST_API_KEY not in cleaned
    assert "<hidden>" in cleaned


@pytest.mark.asyncio
async def test_provider_echoing_key_is_scrubbed(tmp_path, monkeypatch):
    """Provider echo lại key trong error body → message/DB/UI không bao giờ thấy key"""
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": f"bad request, api_key={TEST_API_KEY} at https://api.meta.ai/v1"}},
        )

    provider = _provider(handler)
    with pytest.raises(ImageProviderError) as exc:
        await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")
    message = str(exc.value)
    assert TEST_API_KEY not in message
    assert "api.meta.ai" not in message
    assert TEST_API_KEY not in str(exc.value.args)


def test_image_request_error_does_not_leak_payload():
    with pytest.raises(ImageRequestError) as exc:
        # giá trị client gửi kèm URL/key phải bị che trong thông báo lỗi
        raise ImageRequestError("size không hợp lệ: https://api.meta.ai/v1?key=abc123456789")

    assert "api.meta.ai" not in str(exc.value)


# --------------------------------------------------------------------------- reasoning strength（low/high）


def test_reasoning_strength_whitelist_is_low_high_only():
    provider = _provider(lambda _request: httpx.Response(200, json={}))
    assert provider.reasoning_strengths == ("low", "high")
    assert provider.normalize_reasoning_strength("low") == "low"
    assert provider.normalize_reasoning_strength("HIGH") == "high"
    with pytest.raises(ImageRequestError):
        provider.normalize_reasoning_strength("medium")


def test_capabilities_only_advertise_supported_strengths():
    provider = _provider(lambda _request: httpx.Response(200, json={}))
    capabilities = provider.capabilities()
    assert capabilities["reasoning_strengths"] == ["low", "high"]
    assert "medium" not in capabilities["reasoning_strengths"]


# --------------------------------------------------------------------------- HTTP 错误 / 重试 / 取消


@pytest.mark.asyncio
async def test_http_error_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": f"invalid key {TEST_API_KEY}"}})

    provider = _provider(handler)
    with pytest.raises(ImageProviderError) as exc:
        await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")
    message = str(exc.value)
    assert "403" in message
    assert TEST_API_KEY not in message, "thông báo lỗi không được chứa key"


@pytest.mark.asyncio
async def test_transient_error_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "video_image_max_retries", 2)
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append("call")
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        return httpx.Response(200, json={"data": [{"b64_json": _b64(WEBP_BYTES)}]})

    provider = _provider(handler)
    await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cancel_before_request_makes_no_call(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": [{"b64_json": _b64(PNG_BYTES)}]})

    provider = _provider(handler)

    async def cancel_check() -> bool:
        return True

    with pytest.raises(ImageCancelledError):
        await provider.generate_image(
            _request(tmp_path), tmp_path / "scene.webp", cancel_check=cancel_check
        )
    assert calls == []


@pytest.mark.asyncio
async def test_missing_configuration_fails_before_request(tmp_path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    provider = _provider(handler, api_key="")
    with pytest.raises(ImageConfigError) as exc:
        await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")
    assert "META_MUSE_API_KEY" in exc.value.missing_config
    assert calls == []


@pytest.mark.asyncio
async def test_cancel_during_request_raises_cancelled_not_provider_error(tmp_path, monkeypatch):
    """Cancel trong lúc chờ retry sau request: phải là ImageCancelledError (không phải provider failure)

    Regression: HTTP helper báo cancel bằng MotionCancelledError; nếu adapter bắt nhầm thành
    ImageProviderError thì pipeline sẽ ghi scene failed thay vì kết thúc JobCancelled.
    """
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "video_image_max_retries", 2)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503, json={"error": {"message": "unavailable"}})

    provider = _provider(handler)

    async def cancel_check() -> bool:
        # đã gửi request (và nhận 503) rồi mới cancel → rơi vào nhánh chờ retry
        return bool(calls)

    out_path = tmp_path / "scene.webp"
    with pytest.raises(ImageCancelledError):
        await provider.generate_image(_request(tmp_path), out_path, cancel_check=cancel_check)

    assert calls, "request đã được gửi trước khi cancel"
    assert len(calls) == 1, "cancel phải dừng ngay, không retry tiếp"
    assert not out_path.exists()
    assert not out_path.with_name(out_path.name + ".part").exists(), "phải dọn .part"


@pytest.mark.asyncio
async def test_cancel_during_url_download_raises_cancelled_and_cleans_part(tmp_path, monkeypatch):
    """Cancel ngay trước khi tải ảnh theo URL: phải là ImageCancelledError và dọn `.part`"""
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "image_allow_insecure_localhost", True)
    monkeypatch.setattr(settings, "video_motion_allow_insecure_localhost", True)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "http://127.0.0.1:9/scene.webp"}]})
        requested.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=WEBP_BYTES)

    provider = _provider(handler)
    state = {"checks": 0}

    async def cancel_check() -> bool:
        state["checks"] += 1
        return state["checks"] > 1

    out_path = tmp_path / "scene.webp"
    with pytest.raises(ImageCancelledError):
        await provider.generate_image(_request(tmp_path), out_path, cancel_check=cancel_check)

    assert requested == [], "cancel trước khi bắt đầu tải thì không gọi URL"
    assert not out_path.exists()
    assert not out_path.with_name(out_path.name + ".part").exists()


@pytest.mark.asyncio
async def test_cancel_mid_download_cleans_partial_file(tmp_path, monkeypatch):
    """Cancel trong lúc đang stream ảnh: vẫn phải dọn `.part` và không để lại file dở"""
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "image_allow_insecure_localhost", True)
    monkeypatch.setattr(settings, "video_motion_allow_insecure_localhost", True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "http://127.0.0.1:9/scene.webp"}]})
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=WEBP_BYTES)

    provider = _provider(handler)
    state = {"checks": 0}

    async def cancel_check() -> bool:
        state["checks"] += 1
        # False ở check #1 (trước POST) và #2 (trước download) → cancel ở check #3 (trong lúc tải)
        return state["checks"] > 2

    out_path = tmp_path / "scene.webp"
    with pytest.raises(ImageCancelledError):
        await provider.generate_image(_request(tmp_path), out_path, cancel_check=cancel_check)

    assert not out_path.exists()
    assert not out_path.with_name(out_path.name + ".part").exists()


# --------------------------------------------------------------------------- URL fallback（SSRF）


@pytest.mark.asyncio
async def test_url_fallback_downloads_without_leaking_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "video_motion_allow_insecure_localhost", True)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "http://127.0.0.1:9/scene.webp"}]})
        seen["host"] = request.url.host
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=WEBP_BYTES)

    provider = _provider(handler)
    result = await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")

    assert result.mime_type == "image/webp"
    assert seen["host"] == "127.0.0.1"
    assert seen["auth"] is None, "không gửi API key tới host CDN"


@pytest.mark.asyncio
async def test_url_fallback_never_sends_authorization_even_for_provider_host(tmp_path, monkeypatch):
    """Kể cả khi URL trùng host provider, download tuyệt đối không mang theo Bearer token"""
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "meta_muse_base_url", "https://api.meta.ai/v1")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://api.meta.ai/cdn/scene.webp"}]})
        seen["host"] = request.url.host
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=WEBP_BYTES)

    provider = _provider(handler)
    result = await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")

    assert result.mime_type == "image/webp"
    assert seen["host"] == "api.meta.ai"
    assert "authorization" not in seen["headers"], "URL fallback không bao giờ gửi Authorization"
    assert TEST_API_KEY not in json.dumps(seen["headers"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_url",
    [
        "https://10.0.0.5/scene.webp",
        "https://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
    ],
)
async def test_url_fallback_blocks_ssrf_targets(tmp_path, monkeypatch, remote_url):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": remote_url}]})
        requested.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=WEBP_BYTES)

    provider = _provider(handler)
    with pytest.raises(ImageProviderError):
        await provider.generate_image(_request(tmp_path), tmp_path / "scene.webp")
    assert requested == [], "URL nội bộ/không hợp lệ không được gọi"


# --------------------------------------------------------------------------- service: 参数校验


def test_normalize_image_options_disabled_returns_empty_plan():
    plan = normalize_image_options(None)
    assert plan == {
        "generate_scene_images": False,
        "image_provider": None,
        "image_model": None,
        "image_aspect_ratio": None,
        "image_size": None,
        "image_reasoning_strength": None,
    }


def test_normalize_image_options_requires_credentials():
    with pytest.raises(HTTPException) as exc:
        normalize_image_options({"generate_scene_images": True})
    assert exc.value.status_code == 503
    assert "META_MUSE_API_KEY" in exc.value.detail


def test_normalize_image_options_rejects_unknown_provider():
    with pytest.raises(HTTPException) as exc:
        normalize_image_options(
            {"generate_scene_images": True, "image_provider": "ghost_image"}
        )
    assert exc.value.status_code == 400


def test_normalize_image_options_ok_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    plan = normalize_image_options(
        {
            "generate_scene_images": True,
            "image_aspect_ratio": "9:16",
            "image_reasoning_strength": "high",
        }
    )
    assert plan["image_provider"] == "meta_muse_image"
    assert plan["image_model"] == "muse-image-1.0"
    assert plan["image_aspect_ratio"] == "9:16"
    assert plan["image_size"] == "1024x1792"
    assert plan["image_reasoning_strength"] == "high"


def test_normalize_image_options_rejects_unsupported_reasoning_strength(monkeypatch):
    """`medium` không nằm trong whitelist Meta hiện hành → 400 trước khi gọi API"""
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    with pytest.raises(HTTPException) as exc:
        normalize_image_options(
            {"generate_scene_images": True, "image_reasoning_strength": "medium"}
        )
    assert exc.value.status_code == 400


def test_normalize_image_options_respects_server_switch(monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "video_image_enabled", False)
    with pytest.raises(HTTPException) as exc:
        normalize_image_options({"generate_scene_images": True})
    assert exc.value.status_code == 503
    assert "VIDEO_IMAGE_ENABLED" in exc.value.detail


def test_normalize_image_options_rejects_bad_size(monkeypatch):
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    with pytest.raises(HTTPException) as exc:
        normalize_image_options({"generate_scene_images": True, "image_size": "4096x4096"})
    assert exc.value.status_code == 400


def test_serialize_scene_hides_image_internals():
    scene = VideoExportScene(
        id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        scene_index=0,
        narration="n",
        duration_seconds=6.0,
        status="failed",
        image_provider="meta_muse_image",
        image_model="muse-image-1.0",
        image_status="failed",
        image_error="Meta Model API báo lỗi",
        image_size="1792x1024",
        image_path="assets/scene_000.webp",
    )
    payload = serialize_scene(scene)
    assert payload["image_provider"] == "meta_muse_image"
    assert payload["image_status"] == "failed"
    assert payload["image_size"] == "1792x1024"
    assert "image_path" not in payload
    assert not any("assets/" in str(value) for value in payload.values() if isinstance(value, str))


# --------------------------------------------------------------------------- service: 流水线


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'image.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        yield db


@pytest.fixture(autouse=True)
def isolated_video_storage(tmp_path, monkeypatch):
    from app.services.video_export import paths as video_paths
    from app.services.video_export import service as service_module

    root = tmp_path / "video-storage"
    monkeypatch.setattr(video_paths, "VIDEO_STORAGE_DIR", root)
    monkeypatch.setattr(service_module, "VIDEO_STORAGE_DIR", root)
    return root


@pytest_asyncio.fixture
async def sample_project(session: AsyncSession):
    project = Project(
        id=str(uuid.uuid4()),
        user_id="user-1",
        title="Dự án ảnh phân cảnh",
        cover_image_url=None,
        cover_status="none",
    )
    session.add(project)
    session.add(
        Chapter(
            id=str(uuid.uuid4()),
            project_id=project.id,
            chapter_number=1,
            title="Chương một",
            content="Trời chưa sáng. Đoàn người rời làng. " * 40,
        )
    )
    await session.commit()
    return project


def _stub_spawn(monkeypatch):
    spawned: list[tuple[str, str]] = []

    async def fake_spawn(task_id, user_id, task_func, *args, **kwargs):
        spawned.append((task_id, user_id))

    monkeypatch.setattr(
        "app.services.video_export.service.background_task_service.spawn_background_task", fake_spawn
    )
    monkeypatch.setattr(ffmpeg_runner, "ffmpeg_binary", lambda: "/usr/bin/ffmpeg")
    return spawned


class _FakeImageProvider:
    """假图片 provider：可配置成功/失败，记录每次调用"""

    name = "meta_muse_image"
    label = "Meta Muse Image 1.0"
    kind = "image"
    models = ("muse-image-1.0",)
    default_model = "muse-image-1.0"
    aspect_ratios = ("16:9", "9:16", "1:1")
    size_options = ("1792x1024", "1024x1792", "1024x1024")
    default_size = "1792x1024"
    output_format = "webp"
    supports_reasoning_strength = True
    reasoning_strengths = ("low", "medium", "high")

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[ImageRequest] = []

    def configuration(self):
        from app.services.video_export.image_providers.base import ImageProviderConfigState

        return ImageProviderConfigState(configured=True)

    def size_for_aspect(self, aspect_ratio: str) -> str:
        return {"16:9": "1792x1024", "9:16": "1024x1792", "1:1": "1024x1024"}.get(
            aspect_ratio, self.default_size
        )

    def normalize_model(self, value):
        return value or self.default_model

    def normalize_aspect_ratio(self, value):
        return value or self.aspect_ratios[0]

    def normalize_size(self, value, aspect_ratio):
        return value or self.size_for_aspect(aspect_ratio)

    def normalize_reasoning_strength(self, value):
        return value or None

    async def generate_image(self, request, out_path, *, cancel_check=None, timeout=None):
        from app.services.video_export.image_providers.base import SceneImageResult

        self.calls.append(request)
        if self.fail:
            raise ImageProviderError("fake image provider down")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(WEBP_BYTES)
        return SceneImageResult(
            path=out_path,
            provider=self.name,
            model=self.default_model,
            size=request.size,
            mime_type="image/webp",
            bytes_written=len(WEBP_BYTES),
        )


class _RecordingMotionProvider:
    """假 motion provider：记录收到的 reference"""

    name = "fake_remote"
    kind = "remote"
    models = ("fake-model",)
    default_model = "fake-model"
    supports_cancel = False
    supports_idempotency = True
    aspect_ratios = ("16:9",)
    resolutions = ("720p",)
    default_resolution = "720p"

    def __init__(self) -> None:
        self.references: list = []

    def configuration(self):
        from app.services.video_export.providers.base import ProviderConfigState

        return ProviderConfigState(configured=True)

    async def render_scene(self, *, request, out_path, cancel_check=None, timeout=None, on_operation=None):
        from app.services.video_export.providers.base import MotionOperation, MotionRenderResult

        self.references.append(request.reference)
        if on_operation is not None:
            await on_operation(
                MotionOperation(
                    provider=self.name,
                    model=self.default_model,
                    operation_id="fake-1",
                    status="running",
                )
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"remote-clip")
        return MotionRenderResult(
            clip_path=out_path,
            provider=self.name,
            model=self.default_model,
            duration_seconds=6.0,
            operation_id="fake-1",
        )


async def _awaitable(value):
    return value


async def _run_pipeline(engine, session, job, monkeypatch, *, image=None, motion=None, local=None):
    from app.services.video_export import service as service_module

    monkeypatch.setattr(service_module, "get_engine", lambda user_id: _awaitable(engine))
    monkeypatch.setattr(service_module, "resolve_motion_provider", lambda name: motion)
    monkeypatch.setattr(service_module, "build_provider", lambda name, **kwargs: local)
    if image is not None:
        monkeypatch.setattr(service_module, "resolve_image_provider", lambda name: image)
        monkeypatch.setattr(service_module, "build_image_provider", lambda name, **kwargs: image)

    async def fake_concat(clip_paths, out_path, **kwargs):
        out_path.write_bytes(b"video")

    async def fake_mux(video_path, srt_path, out_path, **kwargs):
        out_path.write_bytes(b"subtitled")
        return True

    async def fake_probe(path):
        return 6.0

    monkeypatch.setattr(ffmpeg_runner, "concat_clips", fake_concat)
    monkeypatch.setattr(ffmpeg_runner, "mux_subtitles", fake_mux)
    monkeypatch.setattr(ffmpeg_runner, "probe_duration", fake_probe)

    await service_module._run_video_export_job(job.id, job.user_id, job.id)
    await session.refresh(job)
    return await video_export_service._get_scenes(db=session, job_id=job.id)


def _job(project: Project, chapter_id: str, *, mode: str = "local", images: bool = False) -> VideoExportJob:
    options: dict = {"resolution": "854x480", "fps": 12, "use_project_cover": False}
    if mode == "hybrid":
        options["hybrid_fallback_on_error"] = True
    if images:
        options.update(
            {
                "generate_scene_images": True,
                "image_provider": "meta_muse_image",
                "image_model": "muse-image-1.0",
                "image_aspect_ratio": "16:9",
                "image_size": "1792x1024",
            }
        )
    return VideoExportJob(
        id=str(uuid.uuid4()),
        user_id=project.user_id,
        project_id=project.id,
        status="pending",
        progress=0,
        chapter_ids=[chapter_id],
        options=options,
        motion_mode=mode,
        motion_provider="fake_remote" if mode != "local" else None,
        motion_model="fake-model" if mode != "local" else None,
        image_provider="meta_muse_image" if images else None,
        image_model="muse-image-1.0" if images else None,
        scene_count=0,
        duration_seconds=0.0,
    )


async def _seed_scenes(*, db: AsyncSession, job: VideoExportJob, chapter_id: str) -> list[VideoExportScene]:
    from app.services.video_export.storyboard import (
        SourceChapter,
        StoryboardOptions,
        build_storyboard,
    )

    chapter = await db.get(Chapter, chapter_id)
    scenes = build_storyboard(
        [
            SourceChapter(
                id=chapter.id,
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                content=chapter.content or "",
            )
        ],
        StoryboardOptions(narration_chars_per_scene=220, chars_per_second=12.5, resolution="854x480", fps=12),
    )
    rows = []
    for scene in scenes:
        row = VideoExportScene(
            job_id=job.id,
            scene_index=scene.scene_index,
            chapter_id=scene.chapter_id,
            chapter_number=scene.chapter_number,
            title=scene.title,
            narration=scene.narration,
            duration_seconds=scene.duration_seconds,
            visual_prompt=scene.visual_prompt,
            asset_kind="placeholder",
            status="pending",
            motion_provider=job.motion_provider,
            motion_model=job.motion_model,
            motion_status="pending" if job.motion_provider else None,
            motion_idempotency_key=f"{job.id}:{scene.scene_index}",
            image_provider=job.image_provider,
            image_model=job.image_model,
            image_status=IMAGE_STATUS_PENDING if job.image_provider else None,
            image_size=job.options.get("image_size"),
        )
        db.add(row)
        rows.append(row)
    job.scene_count = len(scenes)
    from app.models.background_task import BackgroundTask

    db.add(
        BackgroundTask(
            id=job.id,
            user_id=job.user_id,
            project_id=job.project_id,
            task_type="video_export",
            status="pending",
            progress=0,
        )
    )
    await db.commit()
    return rows


@pytest.mark.asyncio
async def test_pipeline_generates_scene_image_and_feeds_motion_reference(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """Meta 生成 ảnh → motion provider 收到该文件作为 reference → 成片完成"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job(sample_project, chapter.id, mode="remote", images=True)
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)

    image = _FakeImageProvider()
    motion = _RecordingMotionProvider()
    local = _FakeImageProvider()  # 不会被用到
    scenes = await _run_pipeline(engine, session, job, monkeypatch, image=image, motion=motion, local=local)

    assert job.status == "completed", job.error_message
    assert len(image.calls) == len(scenes), "mỗi phân cảnh một ảnh"
    assert all(scene.image_status == IMAGE_STATUS_READY for scene in scenes)
    assert all(scene.image_provider == "meta_muse_image" for scene in scenes)
    assert all(scene.image_path and scene.image_path.startswith("assets/") for scene in scenes)
    assert all(scene.image_size == "1792x1024" for scene in scenes)

    # motion provider nhận đúng ảnh do Meta tạo (không phải cover/placeholder)
    assert motion.references and all(ref is not None for ref in motion.references)
    assert all(ref.kind == "image" for ref in motion.references)
    assert all(ref.path.name.startswith("scene_") and ref.path.suffix == ".webp" for ref in motion.references)
    assert all(ref.path.is_file() for ref in motion.references)

    payload = serialize_job(job, scenes)
    assert payload["image_provider"] == "meta_muse_image"
    assert "image_path" not in payload["scenes"][0]


@pytest.mark.asyncio
async def test_pipeline_without_images_keeps_legacy_behavior(
    session, engine, sample_project, monkeypatch
):
    """未开启 Meta：保持 ảnh cảnh thủ công → cover → placeholder 的旧行为"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job(sample_project, chapter.id, mode="local", images=False)
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)

    image = _FakeImageProvider()
    motion = _RecordingMotionProvider()
    local = _RecordingMotionProvider()
    scenes = await _run_pipeline(engine, session, job, monkeypatch, image=image, motion=motion, local=local)

    assert job.status == "completed", job.error_message
    assert image.calls == [], "không bật Meta thì không được gọi provider ảnh"
    assert all(scene.image_status is None for scene in scenes)
    assert all(scene.status == "ready" for scene in scenes)


@pytest.mark.asyncio
async def test_image_failure_fails_scene_without_silent_fallback(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job(sample_project, chapter.id, mode="remote", images=True)
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)

    image = _FakeImageProvider(fail=True)
    motion = _RecordingMotionProvider()
    local = _FakeImageProvider()
    scenes = await _run_pipeline(engine, session, job, monkeypatch, image=image, motion=motion, local=local)

    assert job.status == "failed"
    assert all(scene.status == "failed" for scene in scenes)
    assert all(scene.image_status == IMAGE_STATUS_FAILED for scene in scenes)
    assert all("fake image provider down" in (scene.image_error or "") for scene in scenes)
    assert motion.references == [], "không có ảnh thì không gọi motion provider"


@pytest.mark.asyncio
async def test_retry_does_not_regenerate_ready_image(session, sample_project, monkeypatch):
    """Ảnh đã tạo thành công không được tạo lại (tránh tính phí hai lần)"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    workdir = video_export_service.__class__  # noqa: F841 - 保持可读性
    from app.services.video_export.paths import job_directory

    assets_dir = job_directory("user-1", job.id) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    image_file = assets_dir / f"scene_{scenes[0].scene_index:03d}.webp"
    image_file.write_bytes(WEBP_BYTES)

    ready = scenes[0]
    ready.image_provider = "meta_muse_image"
    ready.image_model = "muse-image-1.0"
    ready.image_status = IMAGE_STATUS_READY
    ready.image_path = f"assets/{image_file.name}"
    ready.status = "failed"
    failed = scenes[1]
    failed.image_provider = "meta_muse_image"
    failed.image_status = IMAGE_STATUS_FAILED
    failed.image_error = "boom"
    failed.status = "failed"
    await session.commit()

    await video_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)

    refreshed = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert refreshed[0].image_status == IMAGE_STATUS_READY, "ảnh thành công phải được giữ nguyên"
    assert refreshed[0].image_path == f"assets/{image_file.name}"
    assert image_file.is_file()
    assert refreshed[1].image_status == IMAGE_STATUS_PENDING, "ảnh lỗi sẽ được tạo lại khi chạy"
    assert refreshed[1].image_error is None


@pytest.mark.asyncio
async def test_delete_project_removes_scene_image_assets(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """Xóa dự án/tác vụ phải dọn cả ảnh cảnh lẫn clip"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    job.status = "completed"
    job.video_path = f"user-1/{job.id}/output.mp4"
    await session.commit()

    from app.services.video_export.paths import job_directory

    job_dir = job_directory("user-1", job.id)
    (job_dir / "assets").mkdir(parents=True, exist_ok=True)
    (job_dir / "assets" / "scene_000.webp").write_bytes(WEBP_BYTES)
    (job_dir / "clips").mkdir(parents=True, exist_ok=True)
    (job_dir / "clips" / "scene_000.mp4").write_bytes(b"clip")
    (job_dir / "output.mp4").write_bytes(b"video")

    result = await video_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=sample_project.id, commit=True
    )
    assert result["jobs"] == 1
    assert not job_dir.exists(), "toàn bộ ảnh/clip phải bị dọn cùng tác vụ"


@pytest.mark.asyncio
async def test_image_files_stay_inside_managed_storage(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """图片只写在任务目录内（项目删除时会随目录一起清理）"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job(sample_project, chapter.id, mode="remote", images=True)
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)

    image = _FakeImageProvider()
    scenes = await _run_pipeline(
        engine,
        session,
        job,
        monkeypatch,
        image=image,
        motion=_RecordingMotionProvider(),
        local=_FakeImageProvider(),
    )

    assert job.status == "completed", job.error_message
    for scene in scenes:
        path = isolated_video_storage / "user-1" / job.id / scene.image_path
        assert path.is_file() and path.parent == isolated_video_storage / "user-1" / job.id / "assets"


class _CancellingImageProvider(_FakeImageProvider):
    """Ảnh bị cancel ngay khi bắt đầu generate (mô phỏng người dùng bấm Hủy)"""

    async def generate_image(self, request, out_path, *, cancel_check=None, timeout=None):
        self.calls.append(request)
        raise ImageCancelledError("Đã hủy theo yêu cầu của người dùng")


@pytest.mark.asyncio
async def test_cancel_during_image_generation_cancels_job_without_failing_scene(
    session, engine, sample_project, monkeypatch
):
    """Cancel khi đang tạo ảnh → job `cancelled`, scene KHÔNG bị đánh dấu failed"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job(sample_project, chapter.id, mode="remote", images=True)
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)

    provider = _CancellingImageProvider()
    motion = _RecordingMotionProvider()
    scenes = await _run_pipeline(
        engine, session, job, monkeypatch, image=provider, motion=motion, local=_FakeImageProvider()
    )

    assert job.status == "cancelled", job.error_message
    assert scenes[0].image_status == "cancelled", "phân cảnh đang chạy được đánh dấu cancelled"
    assert all(scene.status != "failed" for scene in scenes), "cancel không phải lỗi provider"
    assert all(scene.image_status != IMAGE_STATUS_FAILED for scene in scenes)
    assert motion.references == [], "cancel thì không gọi motion provider"
    # các phân cảnh chưa chạy tới vẫn ở trạng thái chờ (sẽ được reset khi retry)
    assert all(scene.image_status in ("cancelled", IMAGE_STATUS_PENDING) for scene in scenes)


@pytest.mark.asyncio
async def test_retry_after_cancel_regenerates_only_unfinished_images(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """Cancel rồi retry: ảnh `ready` được giữ (không tính phí lại), ảnh chưa xong được tạo lại"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job(sample_project, chapter.id, mode="local", images=True)
    session.add(job)
    await session.commit()
    scenes = await _seed_scenes(db=session, job=job, chapter_id=chapter.id)

    from app.services.video_export.paths import job_directory

    assets_dir = job_directory(job.user_id, job.id) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    ready_file = assets_dir / f"scene_{scenes[0].scene_index:03d}.webp"
    ready_file.write_bytes(WEBP_BYTES)

    # scene 0: ảnh đã xong nhưng clip chưa (bị cancel) → giữ ảnh
    scenes[0].image_status = IMAGE_STATUS_READY
    scenes[0].image_path = f"assets/{ready_file.name}"
    scenes[0].status = "rendering"  # dấu vết của lần chạy bị cancel
    # scene 1: ảnh đang generating dở → phải được tạo lại
    scenes[1].image_status = "generating"
    scenes[1].status = "rendering"
    job.status = "cancelled"
    await session.commit()

    await video_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)

    refreshed = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert refreshed[0].image_status == IMAGE_STATUS_READY, "ảnh đã tạo thành công phải giữ nguyên"
    assert refreshed[0].image_path == f"assets/{ready_file.name}"
    assert ready_file.is_file(), "không xoá ảnh đã trả phí"
    assert refreshed[1].image_status == IMAGE_STATUS_PENDING, "ảnh dở phải được tạo lại"
    assert all(scene.status == "pending" for scene in refreshed), "mọi scene dở đều được reset"
    await session.refresh(job)
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_retry_resets_every_unfinished_scene_status(
    session, sample_project, monkeypatch
):
    """retry_job reset cả `pending`/`rendering`/`failed` (không chỉ `failed`)"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert len(scenes) >= 3
    scenes[0].status = "ready"          # giữ nguyên
    scenes[1].status = "rendering"      # dấu vết进程 bị giết
    scenes[2].status = "failed"
    scenes[2].error_message = "boom"
    job.status = "failed"
    await session.commit()

    await video_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)

    refreshed = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert refreshed[0].status == "ready", "scene hoàn tất không bị reset"
    assert refreshed[1].status == "pending"
    assert refreshed[2].status == "pending"
    assert refreshed[2].error_message is None


# --------------------------------------------------------------------------- worker lease takeover


@pytest.mark.asyncio
async def test_stale_running_claim_can_be_taken_over(session, sample_project, monkeypatch):
    """Worker chết khi job đang `running`: lease hết hạn thì worker khác được tiếp quản"""
    _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "video_job_timeout_seconds", 60)
    monkeypatch.setattr(settings, "video_claim_ttl_buffer_seconds", 0)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    job.status = "running"
    job.worker_token = "dead-worker"
    job.claimed_at = datetime.now() - timedelta(seconds=600)
    await session.commit()

    assert await video_export_service._claim_job(db=session, job=job, token="worker-b") is True
    await session.refresh(job)
    assert job.worker_token == "worker-b"
    assert job.status == "running", "takeover không đổi status, pipeline sẽ tiếp tục"
    # operation id của phân cảnh được giữ nguyên để resume (không submit lại)
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert all(scene.motion_operation_id is None or isinstance(scene.motion_operation_id, str) for scene in scenes)


@pytest.mark.asyncio
async def test_fresh_running_claim_is_not_stolen(session, sample_project, monkeypatch):
    """Job `running` với lease còn hiệu lực thì worker khác không được chen vào"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    job.status = "running"
    job.worker_token = "alive-worker"
    job.claimed_at = datetime.now()
    await session.commit()

    assert await video_export_service._claim_job(db=session, job=job, token="worker-b") is False
    await session.refresh(job)
    assert job.worker_token == "alive-worker"


@pytest.mark.asyncio
async def test_taken_over_job_stops_the_previous_worker(session, engine, sample_project, monkeypatch):
    """Lease bị worker khác lấy mất → worker cũ coi như bị huỷ và dừng pipeline (không ghi đè)"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    job.status = "running"
    job.worker_token = "worker-a"
    job.claimed_at = datetime.now()
    await session.commit()
    # worker-a đang chạy (in-memory token khớp DB)
    assert await video_export_service._is_cancelled(session, job) is False

    # worker-b tiếp quản từ **process khác** (session khác) → token trong bộ nhớ của worker-a không đổi
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as other_worker:
        await other_worker.execute(
            update(VideoExportJob)
            .where(VideoExportJob.id == job.id)
            .values(worker_token="worker-b", claimed_at=datetime.now())
        )
        await other_worker.commit()

    assert job.worker_token == "worker-a", "process cũ vẫn giữ token cũ trong bộ nhớ"
    assert await video_export_service._is_cancelled(session, job) is True, (
        "worker cũ phải dừng khi执行权 đã thuộc worker khác"
    )
    # release của worker cũ không được xoá lease của worker-b
    await video_export_service._release_claim(db=session, job=job, token="worker-a")
    await session.refresh(job)
    assert job.worker_token == "worker-b"


# --------------------------------------------------------------------------- API

def _build_api_app(session: AsyncSession):
    from fastapi import FastAPI, Request

    from app.api import video_export as video_export_api
    from app.database import get_db

    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        user_id = request.headers.get("x-test-user")
        if user_id:
            request.state.user_id = user_id
        return await call_next(request)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(video_export_api.router, prefix="/api")
    return app


def test_api_capabilities_exposes_image_providers_without_secrets(session, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)

    with TestClient(_build_api_app(session)) as client:
        response = client.get("/api/video-export/capabilities", headers={"x-test-user": "user-1"})

    assert response.status_code == 200
    assert TEST_API_KEY not in response.text
    payload = response.json()
    providers = {item["id"]: item for item in payload["image_providers"]}
    assert providers["meta_muse_image"]["configured"] is True
    assert providers["meta_muse_image"]["models"] == ["muse-image-1.0"]
    assert providers["meta_muse_image"]["sizes"] == ["1792x1024", "1024x1792", "1024x1024"]
    assert payload["default_image_provider"] == "meta_muse_image"
    assert payload["default_image_size"] == "1792x1024"
    assert payload["image_enabled"] is True


def test_api_capabilities_reports_missing_env_names(session):
    from fastapi.testclient import TestClient

    with TestClient(_build_api_app(session)) as client:
        payload = client.get(
            "/api/video-export/capabilities", headers={"x-test-user": "user-1"}
        ).json()

    provider = payload["image_providers"][0]
    assert provider["configured"] is False
    assert provider["missing_config"] == ["META_MUSE_API_KEY"]
    assert payload["default_image_provider"] is None


@pytest.mark.asyncio
async def test_api_create_job_with_images_requires_configuration(
    session, sample_project, monkeypatch
):
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    project_id, chapter_id = sample_project.id, chapter.id

    with TestClient(_build_api_app(session)) as client:
        response = client.post(
            "/api/video-export/jobs",
            headers={"x-test-user": "user-1"},
            json={
                "project_id": project_id,
                "chapter_ids": [chapter_id],
                "options": {"generate_scene_images": True},
            },
        )

    assert response.status_code == 503
    assert "META_MUSE_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_create_job_persists_image_plan(session, sample_project, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    project_id, chapter_id = sample_project.id, chapter.id

    with TestClient(_build_api_app(session)) as client:
        created = client.post(
            "/api/video-export/jobs",
            headers={"x-test-user": "user-1"},
            json={
                "project_id": project_id,
                "chapter_ids": [chapter_id],
                "options": {
                    "generate_scene_images": True,
                    "image_aspect_ratio": "9:16",
                    "image_reasoning_strength": "high",
                },
            },
        )
        assert created.status_code == 200, created.text
        detail = client.get(
            f"/api/video-export/jobs/{created.json()['id']}", headers={"x-test-user": "user-1"}
        )

    body = detail.json()
    assert body["image_provider"] == "meta_muse_image"
    assert body["image_model"] == "muse-image-1.0"
    scene = body["scenes"][0]
    assert scene["image_status"] == IMAGE_STATUS_PENDING
    assert scene["image_size"] == "1024x1792"
    for leaked in ("image_path", "b64_json", "api_key", "prompt_sensitive"):
        assert leaked not in detail.text


@pytest.mark.asyncio
async def test_remote_mode_accepts_meta_images_as_reference(session, sample_project, monkeypatch):
    """Bật Meta ảnh thì chế độ remote không còn bắt buộc ảnh bìa dự án"""
    monkeypatch.setattr(settings, "meta_muse_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
        options={
            "motion_mode": "remote",
            "motion_provider": "xai_grok_imagine",
            "use_project_cover": False,
            "generate_scene_images": True,
        },
    )

    assert job.motion_mode == "remote"
    assert job.image_provider == "meta_muse_image"
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert all(scene.image_status == IMAGE_STATUS_PENDING for scene in scenes)
