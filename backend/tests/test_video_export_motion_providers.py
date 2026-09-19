"""视频转场 provider 的本地测试（全部使用 mock HTTP，不调用任何付费 API）

覆盖：provider 注册表/能力输出、SSRF 与下载校验、xAI/Veo/OpenAI 兼容适配器的请求形状与轮询、
取消/超时/失败处理、以及服务层 remote/hybrid 策略与旧任务兼容性。

运行：cd backend && python -m pytest tests/test_video_export_motion_providers.py -q
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.background_task import BackgroundTask
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.video_export import VideoExportJob, VideoExportScene
from app.services.video_export.providers import (
    LocalRenderOptions,
    MotionCancelledError,
    MotionConfigError,
    MotionProviderError,
    MotionRequest,
    MotionRequestError,
    MotionReference,
    MotionTimeoutError,
    build_provider,
    is_known_provider,
    list_provider_capabilities,
)
from app.services.video_export.providers.google_veo import GoogleVeoProvider, validate_operation_name
from app.services.video_export.providers.http_utils import (
    download_to_path,
    looks_like_video,
    validate_download_url,
)
from app.services.video_export.providers.openai_compatible import OpenAICompatibleVideoProvider
from app.services.video_export.providers.base import next_backoff
from app.services.video_export.providers.xai_grok_imagine import XaiGrokImagineProvider
from app.services.video_export import ffmpeg_runner
from app.services.video_export.service import (
    normalize_motion_options,
    serialize_job,
    serialize_scene,
    video_export_service,
)
from app.services.video_export.storyboard import build_storyboard, SourceChapter, StoryboardOptions
from app.services.video_export.subtitles import build_srt_from_scenes

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 256


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def motion_settings(monkeypatch):
    """所有用例统一的转场配置：清空凭证、加快轮询、仅本用例内放开 localhost 下载"""
    for name in (
        "video_motion_xai_api_key",
        "video_motion_gemini_api_key",
        "video_motion_openai_api_key",
        "video_motion_openai_base_url",
        "video_motion_provider",
        "video_motion_model",
        "video_motion_resolution",
        "video_motion_download_allowed_hosts",
    ):
        monkeypatch.setattr(settings, name, None)
    monkeypatch.setattr(settings, "video_motion_mode", "local")
    monkeypatch.setattr(settings, "video_motion_hybrid_fallback_on_error", True)
    monkeypatch.setattr(settings, "video_motion_poll_interval_seconds", 0.01)
    monkeypatch.setattr(settings, "video_motion_poll_max_interval_seconds", 0.02)
    monkeypatch.setattr(settings, "video_motion_max_retries", 0)
    monkeypatch.setattr(settings, "video_motion_allow_insecure_localhost", True)
    return settings


def _reference(tmp_path: Path) -> MotionReference:
    image = tmp_path / "scene.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return MotionReference(path=image, mime_type="image/png", kind="image")


@pytest.fixture(autouse=True)
def stub_image_probe(monkeypatch):
    """适配器单测聚焦请求形状：默认认为参考图尺寸已匹配，避免真的调用 FFmpeg

    需要覆盖 resize 分支的用例会再次 monkeypatch `ffmpeg_runner.probe_image_size`。
    """
    from app.services.video_export import ffmpeg_runner

    monkeypatch.setattr(ffmpeg_runner, "probe_image_size", lambda _path, **_: (1280, 720))
    return ffmpeg_runner


def _request(tmp_path: Path, **overrides) -> MotionRequest:
    payload = {
        "prompt": "Một cơn mưa nhẹ trên mái ngói",
        "duration_seconds": 6.0,
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "reference": _reference(tmp_path),
        "idempotency_key": "job:0",
        "model": None,
        "local": LocalRenderOptions(width=854, height=480, fps=12),
    }
    payload.update(overrides)
    return MotionRequest(**payload)


# --------------------------------------------------------------------------- registry / capabilities


def test_registry_lists_local_and_remote_providers():
    capabilities = list_provider_capabilities()
    ids = [item["id"] for item in capabilities]
    assert ids[0] == "local_ffmpeg"
    for expected in ("xai_grok_imagine", "google_veo", "openai_compatible"):
        assert expected in ids
    assert is_known_provider("google_veo")
    assert not is_known_provider("not-a-provider")


def test_capabilities_never_expose_secrets_or_paths(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "sk-super-secret-value")
    payload = json.dumps(list_provider_capabilities(), ensure_ascii=False)
    assert "sk-super-secret-value" not in payload
    xai = next(item for item in list_provider_capabilities() if item["id"] == "xai_grok_imagine")
    assert xai["configured"] is True
    assert "VIDEO_MOTION_XAI_API_KEY" not in json.dumps(xai)


def test_unconfigured_provider_reports_missing_env_names():
    state = build_provider("xai_grok_imagine").configuration()
    assert state.configured is False
    assert "VIDEO_MOTION_XAI_API_KEY" in state.missing_config
    with pytest.raises(MotionConfigError):
        build_provider("xai_grok_imagine").require_configured()
    with pytest.raises(MotionConfigError):
        build_provider("khong_ton_tai")


# --------------------------------------------------------------------------- SSRF / download 校验


@pytest.mark.asyncio
async def test_validate_download_url_rejects_non_https_and_credentials():
    with pytest.raises(MotionProviderError):
        await validate_download_url("ftp://cdn.example.com/video.mp4")
    with pytest.raises(MotionProviderError):
        await validate_download_url("http://cdn.example.com/video.mp4", allow_insecure_localhost=False)
    with pytest.raises(MotionProviderError):
        await validate_download_url("https://user:pass@cdn.example.com/video.mp4")
    with pytest.raises(MotionProviderError):
        await validate_download_url("")


@pytest.mark.asyncio
async def test_validate_download_url_blocks_private_networks_without_dns():
    for url in ("https://10.0.0.5/video.mp4", "https://127.0.0.1/video.mp4", "https://169.254.169.254/latest/meta-data"):
        with pytest.raises(MotionProviderError):
            await validate_download_url(url, allow_insecure_localhost=False)


@pytest.mark.asyncio
async def test_validate_download_url_enforces_host_whitelist():
    with pytest.raises(MotionProviderError):
        await validate_download_url(
            "https://evil.example.com/video.mp4", allowed_hosts=("cdn.example.com",)
        )


@pytest.mark.asyncio
async def test_validate_download_url_allows_localhost_http_when_enabled():
    url = await validate_download_url("http://127.0.0.1:8080/video.mp4", allow_insecure_localhost=True)
    assert url.endswith("/video.mp4")


def test_looks_like_video_requires_container_magic():
    assert looks_like_video("video/mp4", FAKE_MP4) is True
    assert looks_like_video("application/octet-stream", FAKE_MP4) is True
    assert looks_like_video("text/html", b"<html>error</html>") is False
    assert looks_like_video("application/json", b'{"error": "nope"}') is False


def test_looks_like_video_never_trusts_content_type_alone():
    """Content-Type 不能替代 magic bytes：声明是视频但内容不是视频必须被拒绝"""
    garbage = b"this is definitely not a video file" * 4
    for content_type in ("video/mp4", "video/webm", "application/octet-stream", "application/mp4", "binary/octet-stream"):
        assert looks_like_video(content_type, garbage) is False
    # 声明为图片/JSON 但内容是合法 mp4：以 magic bytes 为准
    assert looks_like_video("image/png", FAKE_MP4) is True
    # 太短的前缀不足以判断
    assert looks_like_video("video/mp4", b"\x00\x00\x00\x18ft") is False


@pytest.mark.asyncio
async def test_download_rejects_garbage_bytes_even_with_video_content_type(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "video/mp4"}, content=b"<html>gateway error</html>"
        )

    out = tmp_path / "clip.mp4"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MotionProviderError) as exc:
            await download_to_path(client, "http://127.0.0.1/video.mp4", out, max_bytes=4096)
    assert "magic bytes" in str(exc.value)
    assert not out.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(ffmpeg_runner.ffmpeg_binary() is None, reason="FFmpeg chưa được cài đặt")
async def test_real_ffmpeg_mp4_passes_magic_check(tmp_path):
    """真实 FFmpeg 产出的 MP4 必须通过严格的文件头校验（避免校验过严）"""
    clip = tmp_path / "probe.mp4"
    await ffmpeg_runner.run_ffmpeg(
        ["-f", "lavfi", "-i", "color=c=black:s=320x240", "-t", "1", "-y", clip.as_posix()]
    )
    head = clip.read_bytes()[:12]
    assert looks_like_video("video/mp4", head) is True


@pytest.mark.asyncio
async def test_download_rejects_html_and_cleans_temp_file(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>nope</html>")

    out = tmp_path / "clip.mp4"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MotionProviderError):
            await download_to_path(client, "http://127.0.0.1/video.mp4", out, max_bytes=1024)
    assert not out.exists()
    assert not out.with_name(out.name + ".part").exists()


@pytest.mark.asyncio
async def test_download_enforces_size_limit(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "video/mp4"}, content=FAKE_MP4 * 10
        )

    out = tmp_path / "clip.mp4"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MotionProviderError) as exc:
            await download_to_path(client, "http://127.0.0.1/video.mp4", out, max_bytes=64)
    assert "dung lượng" in str(exc.value)
    assert not out.exists()


@pytest.mark.asyncio
async def test_download_follows_redirect_only_to_allowed_hosts(tmp_path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/start.mp4":
            return httpx.Response(302, headers={"location": "http://10.0.0.9/latest/meta-data"})
        return httpx.Response(200, headers={"content-type": "video/mp4"}, content=FAKE_MP4)

    out = tmp_path / "clip.mp4"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MotionProviderError):
            await download_to_path(client, "http://127.0.0.1/start.mp4", out, max_bytes=4096)
    assert calls == ["http://127.0.0.1/start.mp4"], "重定向目标必须在发起前被拒绝"
    assert not out.exists()


# --------------------------------------------------------------------------- xAI Grok Imagine


@pytest.mark.asyncio
async def test_xai_submit_builds_image_to_video_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-test-key")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"request_id": "req-123"})

    provider = XaiGrokImagineProvider(transport=httpx.MockTransport(handler))
    operation = await provider._submit(_request(tmp_path, duration_seconds=9.4))

    assert captured["url"] == "https://api.x.ai/v1/videos/generations"
    assert captured["auth"] == "Bearer xai-test-key"
    body = captured["body"]
    assert body["model"] == "grok-imagine-video-1.5"
    assert body["duration"] == 9  # 1–15s 整数：四舍五入并夹在区间内
    assert body["aspect_ratio"] == "16:9"
    assert body["resolution"] == "720p"
    assert body["image"]["url"].startswith("data:image/png;base64,")
    assert operation.operation_id == "req-123"
    assert operation.status == "pending"


@pytest.mark.asyncio
async def test_xai_duration_is_clamped_to_api_range(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-test-key")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"request_id": "req-1"})

    provider = XaiGrokImagineProvider(transport=httpx.MockTransport(handler))
    await provider._submit(_request(tmp_path, duration_seconds=99.0))
    assert captured["body"]["duration"] == 15, "超出 API 上限时必须夹到 15 秒"


@pytest.mark.asyncio
async def test_xai_submit_rejects_placeholder_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-test-key")
    provider = XaiGrokImagineProvider(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={})))
    with pytest.raises(MotionRequestError):
        await provider._submit(_request(tmp_path, reference=None))


@pytest.mark.asyncio
async def test_xai_poll_maps_status_and_download_url(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-test-key")
    responses = [
        {"status": "pending", "progress": 30},
        {"status": "done", "progress": 100, "video": {"url": "http://127.0.0.1/clip.mp4", "duration": 8}},
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    provider = XaiGrokImagineProvider(transport=httpx.MockTransport(handler))
    operation = provider_operation(provider.name, "req-1")
    pending = await provider._poll(operation)
    assert pending.status == "pending" and pending.progress == 30
    done = await provider._poll(operation)
    assert done.status == "completed" and done.download_url == "http://127.0.0.1/clip.mp4"


@pytest.mark.asyncio
async def test_xai_poll_surfaces_failure_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "failed", "error": {"message": "moderation blocked"}})

    provider = XaiGrokImagineProvider(transport=httpx.MockTransport(handler))
    operation = await provider._poll(
        provider_operation(provider.name, "req-1")
    )
    assert operation.status == "failed"
    assert "moderation" in (operation.failure_reason or "")


@pytest.mark.asyncio
async def test_xai_download_does_not_leak_api_key_to_cdn(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-test-key")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, headers={"content-type": "video/mp4"}, content=FAKE_MP4)

    provider = XaiGrokImagineProvider(transport=httpx.MockTransport(handler))
    operation = provider_operation(provider.name, "req-1", download_url="http://127.0.0.1:9/clip.mp4")
    written = await provider._download(operation, tmp_path / "clip.mp4")

    assert written == len(FAKE_MP4)
    assert seen["host"] == "127.0.0.1"
    assert seen["auth"] is None, "下载走 CDN 时不得携带 provider 凭证"


# --------------------------------------------------------------------------- Google Veo


@pytest.mark.asyncio
async def test_veo_submit_builds_predict_long_running_body(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("x-goog-api-key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "models/veo-3.1-generate-preview/operations/abc"})

    provider = GoogleVeoProvider(transport=httpx.MockTransport(handler))
    operation = await provider._submit(_request(tmp_path, duration_seconds=6.0, resolution="720p"))

    assert captured["url"].endswith("/models/veo-3.1-generate-preview:predictLongRunning")
    assert captured["key"] == "gemini-test-key"
    body = captured["body"]
    # Veo 3.1 chỉ tạo video 8 giây: 6 秒的旁白会被夹到 8 秒（不是 400）
    assert body["parameters"]["durationSeconds"] == 8
    assert body["parameters"]["aspectRatio"] == "16:9"
    assert body["parameters"]["resolution"] == "720p"
    assert body["parameters"]["sampleCount"] == 1
    assert body["instances"][0]["image"]["bytesBase64Encoded"]
    assert body["instances"][0]["image"]["mimeType"] == "image/png"
    assert operation.operation_id == "models/veo-3.1-generate-preview/operations/abc"


def test_veo_model_limits_match_documented_api():
    provider = GoogleVeoProvider(api_key="k")
    for model in ("veo-3.1-generate-preview", "veo-3.1-fast-generate-preview", "veo-3.1-lite-generate-preview"):
        limits = provider.model_limits(model)
        assert limits["duration_options"] == [8.0], f"{model} 只产生 8 秒视频"
        assert limits["min_duration_seconds"] == limits["max_duration_seconds"] == 8.0
    lite = provider.model_limits("veo-3.1-lite-generate-preview")
    assert "4k" not in lite["resolutions"], "Veo 3.1 Lite 不支持 4k"
    assert provider.model_limits("veo-3.1-generate-preview")["resolutions"] == ["720p", "1080p", "4k"]
    veo2 = provider.model_limits("veo-2.0-generate-001")
    assert veo2["duration_options"] == [5.0, 6.0, 7.0, 8.0]
    assert veo2["resolutions"] == ["720p"], "Veo 2.0 只支持 720p"

    # 4/6 秒不得出现在 Veo 3.1 的能力输出里
    capabilities = {item["id"]: item for item in list_provider_capabilities()}["google_veo"]
    for model in ("veo-3.1-generate-preview", "veo-3.1-lite-generate-preview"):
        assert 4.0 not in capabilities["model_limits"][model]["duration_options"]
        assert 6.0 not in capabilities["model_limits"][model]["duration_options"]


@pytest.mark.asyncio
async def test_veo_submits_4k_only_for_models_supporting_it(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"name": "models/veo-3.1-fast-generate-preview/operations/op-1"}
        )

    provider = GoogleVeoProvider(transport=httpx.MockTransport(handler))
    await provider._submit(
        _request(tmp_path, model="veo-3.1-fast-generate-preview", resolution="4k", duration_seconds=8.0)
    )
    assert captured["body"]["parameters"]["resolution"] == "4k"
    assert captured["body"]["parameters"]["durationSeconds"] == 8
    assert "veo-3.1-fast-generate-preview" in captured["url"]


@pytest.mark.asyncio
async def test_veo_rejects_4k_for_lite_model(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")
    provider = GoogleVeoProvider(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={})))
    with pytest.raises(MotionRequestError) as exc:
        await provider._submit(
            _request(tmp_path, model="veo-3.1-lite-generate-preview", resolution="4k", duration_seconds=8.0)
        )
    assert "4k" in str(exc.value)


@pytest.mark.asyncio
async def test_veo_rejects_1080p_for_veo2_model(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")
    provider = GoogleVeoProvider(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={})))
    with pytest.raises(MotionRequestError) as exc:
        await provider._submit(
            _request(tmp_path, model="veo-2.0-generate-001", resolution="1080p", duration_seconds=8.0)
        )
    assert "1080p" in str(exc.value)


@pytest.mark.asyncio
async def test_veo_poll_reads_operation_and_video_uri(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")
    payloads = [
        {"done": False, "metadata": {"progressPercent": 42}},
        {
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [{"video": {"uri": "http://127.0.0.1/clip.mp4"}}]
                }
            },
        },
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads.pop(0))

    provider = GoogleVeoProvider(transport=httpx.MockTransport(handler))
    operation = provider_operation(
        provider.name, f"models/{provider.default_model}/operations/abc", model=provider.default_model
    )
    running = await provider._poll(operation)
    assert running.status == "running" and running.progress == 42
    done = await provider._poll(operation)
    assert done.status == "completed" and done.download_url == "http://127.0.0.1/clip.mp4"


@pytest.mark.asyncio
async def test_veo_poll_reports_error_object(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 400, "message": "invalid image"}})

    provider = GoogleVeoProvider(transport=httpx.MockTransport(handler))
    operation = provider_operation(
        provider.name, f"models/{provider.default_model}/operations/x", model=provider.default_model
    )
    result = await provider._poll(operation)
    assert result.status == "failed"
    assert "invalid image" in (result.failure_reason or "")


# --------------------------------------------------------------------------- 轮询退避


def test_next_backoff_grows_exponentially_and_caps():
    interval, cap = 5.0, 20.0
    wait = interval
    schedule = []
    for _ in range(4):
        wait = next_backoff(wait, progressed=False, interval=interval, max_interval=cap)
        schedule.append(wait)
    assert schedule == [10.0, 20.0, 20.0, 20.0], f"退避应为 5→10→20 并封顶，实际 {schedule}"
    # provider 有进展时回到初始间隔
    assert next_backoff(20.0, progressed=True, interval=interval, max_interval=cap) == interval


@pytest.mark.asyncio
async def test_poll_interval_actually_grows_between_polls(monkeypatch, tmp_path):
    """轮询间隔必须真的递增（回归：曾固定为 min(interval, max_interval)）"""
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings, "video_motion_poll_interval_seconds", 0.05)
    monkeypatch.setattr(settings, "video_motion_poll_max_interval_seconds", 0.2)
    stamps: list[float] = []

    class _Provider(OpenAICompatibleVideoProvider):
        async def _poll(self, operation, cancel_check=None):
            stamps.append(time.monotonic())
            operation.status = "running"
            operation.progress = None
            return operation

    provider = _Provider(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"id": "v"})))
    provider.require_configured = lambda: None  # 跳过真实配置校验

    with pytest.raises(MotionTimeoutError):
        await provider.render_scene(
            request=_request(tmp_path, resume_operation_id="video_x"),
            out_path=tmp_path / "clip.mp4",
            timeout=0.5,
        )

    gaps = [round(b - a, 3) for a, b in zip(stamps, stamps[1:])]
    assert len(gaps) >= 3, f"需要至少 3 次轮询才能观察退避，实际 {gaps}"
    assert gaps[1] > gaps[0], f"第二次间隔应大于第一次: {gaps}"
    assert gaps[2] >= gaps[1], f"间隔不应变小: {gaps}"
    assert max(gaps) <= 0.35, f"间隔不得超过上限（含调度误差）: {gaps}"


# --------------------------------------------------------------------------- operation name 校验（SSRF）

MODEL = "veo-3.1-generate-preview"


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example.com/steal",
        "http://evil.example.com/steal",
        "//evil.example.com/steal",
        "/models/veo-3.1-generate-preview/operations/abc",
        "models/veo-3.1-generate-preview/operations/../../../secrets",
        "models/veo-3.1-generate-preview/operations/..",
        "models/veo-3.1-generate-preview/operations/abc?key=leak",
        "models/veo-3.1-generate-preview/operations/abc#frag",
        "models/veo-3.1-generate-preview/operations/abc%2F..%2Fevil",
        "models/veo-3.1-generate-preview/operations/abc/extra",
        "models/veo-3.1-generate-preview/operations",
        "models/veo-3.1-generate-preview",
        "projects/p/locations/l/models/veo-3.1-generate-preview/operations/abc",
        "models/veo-3.1-generate-preview\\operations\\abc",
        "models/veo-3.1-generate-preview/operations/abc def",
        "models/other-model/operations/abc",
        "models/veo-2.0-generate-001/operations/abc",
        "",
        "   ",
        "models//operations/abc",
        "models/veo-3.1-generate-preview//operations/abc",
    ],
)
def test_veo_rejects_hostile_operation_names(hostile):
    with pytest.raises(MotionProviderError) as exc:
        validate_operation_name(hostile, expected_model=MODEL)
    message = str(exc.value)
    assert "evil.example.com" not in message, "错误消息不得回显可疑内容"
    assert "operations/abc" not in message


@pytest.mark.parametrize(
    "name",
    [
        f"models/{MODEL}/operations/abc",
        f"models/{MODEL}/operations/abc-123_DEF.4",
        f"models/{MODEL}/operations/op-00000000-0000-0000-0000-000000000000",
        f"models/{MODEL}-001/operations/abc",  # 允许模型版本后缀
    ],
)
def test_veo_accepts_documented_operation_names(name):
    assert validate_operation_name(name, expected_model=MODEL) == name


@pytest.mark.asyncio
async def test_veo_submit_rejects_operation_name_from_hostile_response(monkeypatch, tmp_path):
    """provider 返回绝对 URL 时不得存库、更不得在轮询时带着 API key 去请求"""
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "https://evil.example.com/steal"})

    provider = GoogleVeoProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(MotionProviderError) as exc:
        await provider._submit(_request(tmp_path))
    assert "gemini-test-key" not in str(exc.value)


@pytest.mark.asyncio
async def test_veo_poll_rejects_tampered_operation_id_before_requesting(monkeypatch):
    """数据库中/被篡改的 operation id 不得改变请求目标（resume 也必须校验）"""
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json={"done": False})

    provider = GoogleVeoProvider(transport=httpx.MockTransport(handler))
    for hostile in ("https://evil.example.com/steal", "../../etc/passwd", f"models/{MODEL}/operations/../x"):
        operation = provider_operation(provider.name, hostile)
        operation.model = MODEL
        with pytest.raises(MotionProviderError):
            await provider._poll(operation)
    assert requested == [], "非法 operation id 不得触发任何请求"


@pytest.mark.asyncio
async def test_veo_poll_happy_path_requests_relative_path(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_gemini_api_key", "gemini-test-key")
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        assert request.headers.get("x-goog-api-key") == "gemini-test-key"
        return httpx.Response(200, json={"done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "http://127.0.0.1/clip.mp4"}}]}}})

    provider = GoogleVeoProvider(transport=httpx.MockTransport(handler))
    operation = provider_operation(provider.name, f"models/{MODEL}/operations/abc")
    operation.model = MODEL
    result = await provider._poll(operation)

    assert requested == [f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}/operations/abc"]
    assert result.status == "completed"
    assert result.download_url == "http://127.0.0.1/clip.mp4"


@pytest.mark.asyncio
async def test_xai_and_openai_reject_tampered_operation_ids(monkeypatch):
    """同一类注入风险在其它 provider 上同样被拦截（不发出任何请求）"""
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    xai = XaiGrokImagineProvider(transport=httpx.MockTransport(handler))
    openai_provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))

    for hostile in ("https://evil.example.com/steal", "../../x", "abc/def"):
        with pytest.raises(MotionProviderError):
            await xai._poll(provider_operation(xai.name, hostile))
        with pytest.raises(MotionProviderError):
            await openai_provider._poll(provider_operation(openai_provider.name, hostile))
    assert calls == []


# --------------------------------------------------------------------------- OpenAI compatible

@pytest.mark.asyncio
async def test_openai_compatible_uses_documented_pixel_sizes(monkeypatch, tmp_path):
    """size 必须来自 Videos API 白名单，不能用算术推导出非法尺寸"""
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(json.dumps({"raw": request.content.decode("latin-1")})))
        return httpx.Response(200, json={"id": "video_1", "status": "queued"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    cases = [
        ("720p", "16:9", "1280x720"),
        ("720p", "9:16", "720x1280"),
        ("1024p", "16:9", "1792x1024"),
        ("1024p", "9:16", "1024x1792"),
    ]
    for resolution, aspect, expected in cases:
        # 让参考图“恰好等于”目标尺寸，聚焦 size 映射本身
        target_w, target_h = (int(part) for part in expected.split("x"))
        monkeypatch.setattr(
            ffmpeg_runner,
            "probe_image_size",
            lambda _path, _w=target_w, _h=target_h, **_: (_w, _h),
        )
        await provider._submit(
            _request(tmp_path, resolution=resolution, aspect_ratio=aspect, model="sora-2-pro")
        )
        raw = captured[-1]["raw"]
        assert f'name="size"' in raw and expected in raw, f"{resolution}/{aspect} phải map thành {expected}"
        # 不得出现按像素比例算出的非法尺寸
        for invalid in ("1820x1024", "1024x1820", "1280x1024", "1024x1280"):
            assert invalid not in raw


def test_openai_model_limits_distinguish_sora_2_and_pro():
    provider = OpenAICompatibleVideoProvider(api_key="k", base_url="https://video.example.com/v1")
    assert provider.model_limits("sora-2")["resolutions"] == ["720p"]
    assert provider.model_limits("sora-2-pro")["resolutions"] == ["720p", "1024p"]
    assert provider.model_limits("sora-2")["duration_options"] == [4.0, 8.0, 12.0]

    capabilities = {item["id"]: item for item in list_provider_capabilities()}["openai_compatible"]
    assert capabilities["model_limits"]["sora-2"]["resolutions"] == ["720p"]
    assert capabilities["model_limits"]["sora-2-pro"]["resolutions"] == ["720p", "1024p"]
    assert capabilities["limits"]["resolutions"] == ["720p"], "限制默认值（sora-2）不得包含 1024p"


@pytest.mark.asyncio
async def test_openai_rejects_1024p_for_sora_2_before_calling_api(monkeypatch, tmp_path):
    """Sora 2 官方只支持 720p：1024p 必须提前失败，不得调用 API"""
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"id": "video_1", "status": "queued"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(MotionRequestError) as exc:
        await provider._submit(_request(tmp_path, resolution="1024p", model="sora-2"))
    assert "1024p" in str(exc.value) and "sora-2" in str(exc.value)
    assert calls == [], "不得为非法分辨率调用 API"

    # 同一个分辨率在 sora-2-pro 上是合法的（参考图对齐 1792x1024 以免触发真实 resize）
    monkeypatch.setattr(ffmpeg_runner, "probe_image_size", lambda _path, **_: (1792, 1024))
    await provider._submit(_request(tmp_path, resolution="1024p", model="sora-2-pro"))
    assert calls == ["/v1/videos"], "Pro 模型应放行 1024p"


@pytest.mark.asyncio
async def test_openai_compatible_rejects_unsupported_size_combination(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")
    provider = OpenAICompatibleVideoProvider(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    )
    with pytest.raises(MotionRequestError) as resolution_exc:
        await provider._submit(_request(tmp_path, resolution="1080p"))
    assert "1080p" in str(resolution_exc.value)

    with pytest.raises(MotionRequestError) as aspect_exc:
        await provider._submit(_request(tmp_path, aspect_ratio="1:1"))
    assert "kích thước hợp lệ" in str(aspect_exc.value)


@pytest.mark.asyncio
async def test_openai_compatible_resizes_reference_when_size_differs(monkeypatch, tmp_path):
    """参考图尺寸与 size 不一致时必须生成缩放副本，而不是原样上传"""
    from app.services.video_export import ffmpeg_runner

    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")
    monkeypatch.setattr(ffmpeg_runner, "probe_image_size", lambda _path, **_: (640, 360))
    resized: dict = {}

    def fake_resize(source, target, *, width, height):
        resized.update({"source": source.name, "target": target.name, "width": width, "height": height})
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        monkeypatch.setattr(
            ffmpeg_runner, "probe_image_size", lambda path, **_: (width, height) if path == target else (640, 360)
        )

    monkeypatch.setattr(ffmpeg_runner, "resize_image_cover", fake_resize)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["raw"] = request.content
        return httpx.Response(200, json={"id": "video_1", "status": "queued"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    await provider._submit(_request(tmp_path, resolution="720p", aspect_ratio="16:9"))

    assert resized == {"source": "scene.png", "target": "scene_ai_1280x720.png", "width": 1280, "height": 720}
    assert b"scene_ai_1280x720.png" in captured["raw"]


@pytest.mark.asyncio
async def test_openai_compatible_fails_clearly_when_resize_unavailable(monkeypatch, tmp_path):
    from app.services.video_export import ffmpeg_runner

    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")
    monkeypatch.setattr(ffmpeg_runner, "probe_image_size", lambda _path, **_: (640, 360))

    def boom(*_args, **_kwargs):
        raise ffmpeg_runner.FFmpegUnavailableError("no ffmpeg")

    monkeypatch.setattr(ffmpeg_runner, "resize_image_cover", boom)
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        return httpx.Response(200, json={"id": "video_1", "status": "queued"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(MotionRequestError) as exc:
        await provider._submit(_request(tmp_path))
    assert "không có FFmpeg" in str(exc.value)
    assert called == [], "不得提交尺寸不符的请求"


@pytest.mark.asyncio
async def test_openai_compatible_submit_uses_multipart_and_idempotency(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["idempotency"] = request.headers.get("idempotency-key")
        captured["content_type"] = request.headers.get("content-type")
        captured["raw"] = request.content
        return httpx.Response(200, json={"id": "video_1", "status": "queued"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    operation = await provider._submit(_request(tmp_path, duration_seconds=8.0))

    assert captured["url"] == "https://video.example.com/v1/videos"
    assert captured["auth"] == "Bearer openai-test-key"
    assert captured["idempotency"] == "job:0"
    assert "multipart/form-data" in (captured["content_type"] or "")
    raw = captured["raw"]
    assert b'name="model"' in raw and b'sora-2' in raw
    assert b'name="size"' in raw and b"1280x720" in raw
    assert b'name="seconds"' in raw and b"8" in raw
    assert b'name="input_reference"' in raw
    assert operation.operation_id == "video_1"


@pytest.mark.asyncio
async def test_openai_compatible_poll_and_download_content(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "http://127.0.0.1:9/v1")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(200, json={"id": "video_9", "status": "queued"})
        if request.url.path.endswith("/content"):
            return httpx.Response(200, headers={"content-type": "video/mp4"}, content=FAKE_MP4)
        return httpx.Response(200, json={"id": "video_9", "status": "completed", "progress": 100})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    result = await provider.render_scene(request=_request(tmp_path), out_path=tmp_path / "clip.mp4")

    assert requests == [
        "POST /v1/videos",
        "GET /v1/videos/video_9",
        "GET /v1/videos/video_9/content",
    ]
    assert result.clip_path.read_bytes() == FAKE_MP4
    assert result.operation_id == "video_9"
    assert result.provider == "openai_compatible"


@pytest.mark.asyncio
async def test_openai_compatible_failed_operation_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "http://127.0.0.1:9/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "video_2", "status": "in_progress"})
        return httpx.Response(200, json={"id": "video_2", "status": "failed", "error": {"message": "policy"}})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(MotionProviderError) as exc:
        await provider.render_scene(request=_request(tmp_path), out_path=tmp_path / "clip.mp4")
    assert "policy" in str(exc.value)
    assert not (tmp_path / "clip.mp4").exists()


@pytest.mark.asyncio
async def test_remote_render_cancel_stops_polling_without_download(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "http://127.0.0.1:9/v1")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "video_3", "status": "in_progress"})
        return httpx.Response(200, json={"id": "video_3", "status": "in_progress"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))

    async def cancel_check() -> bool:
        return len(calls) >= 2

    with pytest.raises(MotionCancelledError):
        await provider.render_scene(
            request=_request(tmp_path),
            out_path=tmp_path / "clip.mp4",
            cancel_check=cancel_check,
        )
    assert not any(path.endswith("/content") for path in calls), "取消后不得继续下载"


@pytest.mark.asyncio
async def test_remote_render_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "http://127.0.0.1:9/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "video_4", "status": "queued"})
        return httpx.Response(200, json={"id": "video_4", "status": "in_progress"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(MotionTimeoutError):
        await provider.render_scene(
            request=_request(tmp_path), out_path=tmp_path / "clip.mp4", timeout=0.05
        )


@pytest.mark.asyncio
async def test_remote_render_resumes_existing_operation_without_resubmitting(monkeypatch, tmp_path):
    """任务重启后只续跑轮询，不重复提交（避免重复计费）"""
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "http://127.0.0.1:9/v1")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/content"):
            return httpx.Response(200, headers={"content-type": "video/mp4"}, content=FAKE_MP4)
        return httpx.Response(200, json={"id": "video_7", "status": "completed", "progress": 100})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))
    result = await provider.render_scene(
        request=_request(tmp_path, resume_operation_id="video_7"),
        out_path=tmp_path / "clip.mp4",
    )

    assert requests == ["GET /v1/videos/video_7", "GET /v1/videos/video_7/content"]
    assert result.operation_id == "video_7"


@pytest.mark.asyncio
async def test_run_job_skips_duplicate_execution(session, sample_project, monkeypatch):
    """同一任务已在本进程执行时，重复入队不得再次执行（否则会产生重复 API 请求）"""
    from app.services.video_export.service import RUNNING_JOB_IDS

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    job_id = job.id
    RUNNING_JOB_IDS.add(job_id)
    try:
        await video_export_service.run_job(job_id=job_id, user_id="user-1")
    finally:
        RUNNING_JOB_IDS.discard(job_id)

    await session.refresh(job)
    assert job.status == "pending", "重复执行不应改动任务状态"


@pytest.mark.asyncio
async def test_remote_render_cancel_before_submit_makes_no_request(monkeypatch, tmp_path):
    """提交前已取消：不得发出任何 HTTP 请求（避免产生付费任务）"""
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "http://127.0.0.1:9/v1")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"id": "video_5", "status": "queued"})

    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(handler))

    async def cancel_check() -> bool:
        return True

    with pytest.raises(MotionCancelledError):
        await provider.render_scene(
            request=_request(tmp_path),
            out_path=tmp_path / "clip.mp4",
            cancel_check=cancel_check,
        )
    assert calls == []


@pytest.mark.asyncio
async def test_remote_render_requires_configuration(monkeypatch, tmp_path):
    provider = OpenAICompatibleVideoProvider(transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
    with pytest.raises(MotionConfigError) as exc:
        await provider.render_scene(request=_request(tmp_path), out_path=tmp_path / "clip.mp4")
    assert "VIDEO_MOTION_OPENAI_API_KEY" in exc.value.missing_config


def provider_operation(
    name: str, operation_id: str, *, download_url: str | None = None, model: str = "m"
):
    from app.services.video_export.providers.base import MotionOperation

    return MotionOperation(
        provider=name,
        model=model,
        operation_id=operation_id,
        status="pending",
        download_url=download_url,
    )


# --------------------------------------------------------------------------- 参数校验（service 层）


def test_normalize_motion_options_local_ignores_remote_fields(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    options = normalize_motion_options(
        {"motion_mode": "local", "motion_provider": "xai_grok_imagine", "motion_model": "x"}
    )
    assert options["motion_mode"] == "local"
    assert options["motion_provider"] is None
    assert options["hybrid_fallback_on_error"] is False


def test_normalize_motion_options_rejects_unknown_mode_and_provider():
    with pytest.raises(HTTPException) as mode_exc:
        normalize_motion_options({"motion_mode": "turbo"})
    assert mode_exc.value.status_code == 400

    with pytest.raises(HTTPException) as provider_exc:
        normalize_motion_options({"motion_mode": "remote", "motion_provider": "ghost"})
    assert provider_exc.value.status_code == 400


def test_normalize_motion_options_remote_requires_credentials():
    with pytest.raises(HTTPException) as exc:
        normalize_motion_options({"motion_mode": "remote", "motion_provider": "xai_grok_imagine"})
    assert exc.value.status_code == 503
    assert "VIDEO_MOTION_XAI_API_KEY" in exc.value.detail


def test_normalize_motion_options_remote_ok_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    options = normalize_motion_options(
        {
            "motion_mode": "remote",
            "motion_provider": "xai_grok_imagine",
            "motion_model": "grok-imagine-video",
            "motion_resolution": "1080p",
            "motion_aspect_ratio": "9:16",
        }
    )
    assert options["motion_provider"] == "xai_grok_imagine"
    assert options["motion_model"] == "grok-imagine-video"
    assert options["motion_resolution"] == "1080p"
    assert options["motion_aspect_ratio"] == "9:16"
    assert options["hybrid_fallback_on_error"] is False


def test_normalize_motion_options_rejects_local_provider_in_remote_mode(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    with pytest.raises(HTTPException) as exc:
        normalize_motion_options({"motion_mode": "remote", "motion_provider": "local_ffmpeg"})
    assert exc.value.status_code == 400


def test_normalize_motion_options_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    with pytest.raises(HTTPException) as exc:
        normalize_motion_options(
            {"motion_mode": "remote", "motion_provider": "xai_grok_imagine", "motion_model": "sora-2"}
        )
    assert exc.value.status_code == 400


def test_normalize_motion_options_enforces_model_specific_resolution(monkeypatch):
    """Sora 2 只有 720p：1024p 在创建任务阶段即 400；Sora 2 Pro 放行"""
    monkeypatch.setattr(settings, "video_motion_openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "video_motion_openai_base_url", "https://video.example.com/v1")

    with pytest.raises(HTTPException) as exc:
        normalize_motion_options(
            {
                "motion_mode": "remote",
                "motion_provider": "openai_compatible",
                "motion_model": "sora-2",
                "motion_resolution": "1024p",
            }
        )
    assert exc.value.status_code == 400
    assert "1024p" in exc.value.detail

    pro = normalize_motion_options(
        {
            "motion_mode": "remote",
            "motion_provider": "openai_compatible",
            "motion_model": "sora-2-pro",
            "motion_resolution": "1024p",
        }
    )
    assert pro["motion_resolution"] == "1024p"


def test_normalize_motion_options_hybrid_reads_fallback_policy(monkeypatch):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    default = normalize_motion_options({"motion_mode": "hybrid", "motion_provider": "xai_grok_imagine"})
    assert default["hybrid_fallback_on_error"] is True
    explicit = normalize_motion_options(
        {"motion_mode": "hybrid", "motion_provider": "xai_grok_imagine", "hybrid_fallback_on_error": False}
    )
    assert explicit["hybrid_fallback_on_error"] is False


def test_normalize_motion_options_remote_without_any_provider():
    with pytest.raises(HTTPException) as exc:
        normalize_motion_options({"motion_mode": "remote"})
    assert exc.value.status_code == 503
    assert "cấu hình" in exc.value.detail


# --------------------------------------------------------------------------- 序列化与旧任务兼容


def _job(**kwargs) -> VideoExportJob:
    payload = {
        "id": str(uuid.uuid4()),
        "user_id": "user-1",
        "project_id": str(uuid.uuid4()),
        "status": "completed",
    }
    payload.update(kwargs)
    return VideoExportJob(**payload)


def test_legacy_job_without_motion_columns_serializes_as_local():
    job = _job(options={"resolution": "1280x720"})
    payload = serialize_job(job)
    assert payload["motion_mode"] == "local"
    assert payload["motion_provider"] is None
    assert payload["motion_model"] is None


def test_legacy_job_options_motion_mode_is_used_as_fallback():
    job = _job(options={"motion_mode": "hybrid", "motion_provider": "google_veo"})
    assert serialize_job(job)["motion_mode"] == "hybrid"


def test_scene_serialization_exposes_motion_metadata_without_remote_url():
    scene = VideoExportScene(
        id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        scene_index=2,
        narration="n",
        duration_seconds=6.0,
        status="failed",
        motion_provider="xai_grok_imagine",
        motion_model="grok-imagine-video-1.5",
        motion_operation_id="req-9",
        motion_status="failed",
        motion_fallback_used=True,
        provider_error="moderation blocked",
        clip_duration_seconds=6.0,
    )
    payload = serialize_scene(scene)
    assert payload["motion_provider"] == "xai_grok_imagine"
    assert payload["motion_status"] == "failed"
    assert payload["motion_fallback_used"] is True
    assert payload["clip_duration_seconds"] == 6.0
    assert "motion_operation_id" not in payload, "operation id 只保存在数据库用于续跑，不对外暴露"
    assert not any("http" in str(value) for value in payload.values() if isinstance(value, str))


def test_srt_uses_actual_clip_duration_for_remote_clips():
    class _Scene:
        def __init__(self, narration: str, duration: float, clip: float | None) -> None:
            self.narration = narration
            self.duration_seconds = duration
            self.clip_duration_seconds = clip

    srt = build_srt_from_scenes([_Scene("Cảnh một.", 12.0, 8.0), _Scene("Cảnh hai.", 12.0, None)])
    assert "00:00:00,000 --> 00:00:08,000" in srt
    assert "00:00:08,000 --> 00:00:20,000" in srt, "没有实际时长的分镜仍使用旁白估算时长"


# --------------------------------------------------------------------------- 服务层：任务创建与流水线


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'motion.db').as_posix()}")
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
        title="Dự án chuyển động",
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
    from app.services.video_export import ffmpeg_runner

    monkeypatch.setattr(ffmpeg_runner, "ffmpeg_binary", lambda: "/usr/bin/ffmpeg")
    return spawned


@pytest.mark.asyncio
async def test_create_job_remote_without_credentials_fails_before_creating_job(
    session, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.create_job(
            db=session,
            user_id="user-1",
            project_id=sample_project.id,
            chapter_ids=[chapter.id],
            options={"motion_mode": "remote", "motion_provider": "xai_grok_imagine"},
        )
    assert exc.value.status_code == 503
    assert "VIDEO_MOTION_XAI_API_KEY" in exc.value.detail

    count = (await session.execute(VideoExportJob.__table__.select())).all()
    assert count == [], "缺少凭证时不得创建任务"


@pytest.mark.asyncio
async def test_create_job_remote_requires_reference_image(session, sample_project, monkeypatch):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.create_job(
            db=session,
            user_id="user-1",
            project_id=sample_project.id,
            chapter_ids=[chapter.id],
            options={
                "motion_mode": "remote",
                "motion_provider": "xai_grok_imagine",
                "use_project_cover": False,
            },
        )
    assert exc.value.status_code == 400
    assert "ảnh tham chiếu" in exc.value.detail


@pytest.mark.asyncio
async def test_create_job_local_default_is_backward_compatible(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    assert job.motion_mode == "local"
    assert job.motion_provider is None

    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert scenes and all(scene.motion_provider is None for scene in scenes)
    assert all(scene.motion_idempotency_key for scene in scenes)

    payload = serialize_job(job, scenes)
    assert payload["motion_mode"] == "local"
    assert payload["scenes"][0]["motion_status"] is None
    assert payload["scenes"][0]["motion_fallback_used"] is False


@pytest.mark.asyncio
async def test_create_job_remote_persists_plan(session, sample_project, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "video_motion_xai_api_key", "xai-key")
    sample_project.cover_image_url = "user-1/cover.png"
    sample_project.cover_status = "ready"
    _stub_spawn(monkeypatch)

    from app.services.video_export import service as service_module

    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(service_module, "resolve_cover_image", lambda *_args, **_kwargs: cover)

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
        options={"motion_mode": "remote", "motion_provider": "xai_grok_imagine"},
    )
    assert job.motion_mode == "remote"
    assert job.motion_provider == "xai_grok_imagine"
    assert job.motion_model == "grok-imagine-video-1.5"

    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert all(scene.motion_provider == "xai_grok_imagine" for scene in scenes)
    assert all(scene.motion_status == "pending" for scene in scenes)


# --------------------------------------------------------------------------- hybrid 回落策略


class _FakeRemoteProvider:
    """记录调用并按需失败的假远端 provider"""

    name = "fake_remote"
    kind = "remote"
    models = ("fake-model",)
    default_model = "fake-model"
    supports_cancel = False
    supports_idempotency = True
    aspect_ratios = ("16:9",)
    resolutions = ("720p",)
    default_resolution = "720p"

    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.calls: list[MotionRequest] = []

    def configuration(self):  # pragma: no cover - 仅满足协议
        from app.services.video_export.providers.base import ProviderConfigState

        return ProviderConfigState(configured=True)

    async def render_scene(self, *, request, out_path, cancel_check=None, timeout=None, on_operation=None):
        from app.services.video_export.providers.base import MotionOperation, MotionRenderResult

        self.calls.append(request)
        if on_operation is not None:
            await on_operation(
                MotionOperation(
                    provider=self.name,
                    model=self.default_model,
                    operation_id=f"fake-{len(self.calls)}",
                    status="running",
                )
            )
        if self.fail:
            raise MotionProviderError("fake provider unavailable")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"remote-clip")
        return MotionRenderResult(
            clip_path=out_path,
            provider=self.name,
            model=self.default_model,
            duration_seconds=6.0,
            operation_id=f"fake-{len(self.calls)}",
        )


class _FakeLocalProvider:
    name = "local_ffmpeg"
    kind = "local"
    models = ("ken_burns",)
    default_model = "ken_burns"

    def __init__(self) -> None:
        self.calls: list[MotionRequest] = []

    def configuration(self):  # pragma: no cover
        from app.services.video_export.providers.base import ProviderConfigState

        return ProviderConfigState(configured=True)

    async def render_scene(self, *, request, out_path, cancel_check=None, timeout=None, on_operation=None):
        from app.services.video_export.providers.base import MotionRenderResult

        self.calls.append(request)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"local-clip")
        return MotionRenderResult(
            clip_path=out_path,
            provider=self.name,
            model=self.default_model,
            duration_seconds=request.duration_seconds,
        )


async def _run_pipeline(engine, session, job, monkeypatch, remote, local):
    from app.services.video_export import ffmpeg_runner
    from app.services.video_export import service as service_module

    monkeypatch.setattr(service_module, "get_engine", lambda user_id: _awaitable(engine))
    monkeypatch.setattr(service_module, "build_provider", lambda name, **kwargs: local)
    monkeypatch.setattr(service_module, "resolve_motion_provider", lambda name: remote)

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


async def _awaitable(value):
    return value


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_local_when_remote_fails(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    remote = _FakeRemoteProvider(fail=True)
    local = _FakeLocalProvider()

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job_for_pipeline(sample_project, chapter.id, mode="hybrid")
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)
    job.status = "pending"
    await session.commit()

    scenes = await _run_pipeline(engine, session, job, monkeypatch, remote, local)

    assert job.status == "completed", job.error_message
    assert remote.calls, "hybrid 应先调用远端 provider"
    assert local.calls, "远端失败后必须回落到本地 FFmpeg"
    assert all(scene.status == "ready" for scene in scenes)
    assert all(scene.motion_fallback_used for scene in scenes)
    assert all("fake provider unavailable" in (scene.provider_error or "") for scene in scenes)
    assert all(scene.motion_provider == "local_ffmpeg" for scene in scenes)
    assert all(scene.motion_status == "failed" for scene in scenes), "giữ lại lỗi provider để truy vết"


@pytest.mark.asyncio
async def test_remote_failure_does_not_fall_back_and_reports_provider_error(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    remote = _FakeRemoteProvider(fail=True)
    local = _FakeLocalProvider()

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job_for_pipeline(sample_project, chapter.id, mode="remote")
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)
    job.status = "pending"
    await session.commit()

    scenes = await _run_pipeline(engine, session, job, monkeypatch, remote, local)

    assert job.status == "failed"
    assert not local.calls, "remote 模式不得静默回落到本地"
    assert all(scene.status == "failed" for scene in scenes)
    assert all(scene.motion_fallback_used is False for scene in scenes)
    assert all("fake provider unavailable" in (scene.provider_error or "") for scene in scenes)
    assert all(scene.motion_operation_id for scene in scenes)


@pytest.mark.asyncio
async def test_remote_success_records_operation_and_clip_duration(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    remote = _FakeRemoteProvider(fail=False)
    local = _FakeLocalProvider()

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job_for_pipeline(sample_project, chapter.id, mode="remote")
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)
    job.status = "pending"
    await session.commit()

    scenes = await _run_pipeline(engine, session, job, monkeypatch, remote, local)

    assert job.status == "completed", job.error_message
    assert not local.calls
    assert all(scene.status == "ready" for scene in scenes)
    assert all(scene.motion_status == "completed" for scene in scenes)
    assert all(scene.motion_operation_id for scene in scenes)
    assert all(scene.clip_duration_seconds == 6.0 for scene in scenes)


def _job_for_pipeline(project: Project, chapter_id: str, *, mode: str) -> VideoExportJob:
    """构造一个已落库的待执行任务（跳过 create_job 的凭证校验，聚焦流水线行为）"""
    options: dict = {"resolution": "854x480", "fps": 12, "use_project_cover": False}
    if mode == "hybrid":
        options["hybrid_fallback_on_error"] = True
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
        scene_count=0,
        duration_seconds=0.0,
    )


async def _seed_scenes(*, db: AsyncSession, job: VideoExportJob, chapter_id: str) -> list[VideoExportScene]:
    """测试辅助：为手工构造的任务补分镜记录与后台任务映射"""
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
        )
        db.add(row)
        rows.append(row)
    job.scene_count = len(scenes)
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


def test_provider_capabilities_include_cost_and_limits():
    capabilities = {item["id"]: item for item in list_provider_capabilities()}
    xai = capabilities["xai_grok_imagine"]
    assert xai["kind"] == "remote"
    assert xai["features"]["placeholder"] is False
    assert xai["limits"]["max_duration_seconds"] >= 8
    assert xai["cost_note"]

    local = capabilities["local_ffmpeg"]
    assert local["kind"] == "local"
    assert local["features"]["placeholder"] is True
    assert local["configured"] is True


# --------------------------------------------------------------------------- API 层


def _build_api_app(session: AsyncSession):
    """只挂载视频导出路由，用请求头模拟登录态（与其他视频导出用例一致）"""
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


def test_api_capabilities_exposes_motion_providers_without_secrets(session, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "video_motion_xai_api_key", "sk-should-never-appear")

    with TestClient(_build_api_app(session)) as client:
        response = client.get("/api/video-export/capabilities", headers={"x-test-user": "user-1"})

    assert response.status_code == 200
    payload = response.json()
    assert "sk-should-never-appear" not in response.text
    assert payload["motion_modes"] == ["local", "remote", "hybrid"]
    providers = {item["id"]: item for item in payload["motion_providers"]}
    assert providers["xai_grok_imagine"]["configured"] is True
    assert providers["google_veo"]["configured"] is False
    assert "VIDEO_MOTION_GEMINI_API_KEY" in providers["google_veo"]["missing_config"]
    assert providers["local_ffmpeg"]["kind"] == "local"
    # 每个模型各自的限制必须可见，UI 才能避免提交必然 400 的组合
    veo_limits = providers["google_veo"]["model_limits"]
    assert veo_limits["veo-3.1-generate-preview"]["duration_options"] == [8.0]
    assert "4k" not in veo_limits["veo-3.1-lite-generate-preview"]["resolutions"]
    assert providers["openai_compatible"]["model_limits"]["sora-2"]["resolutions"] == ["720p"]
    assert providers["openai_compatible"]["model_limits"]["sora-2-pro"]["resolutions"] == ["720p", "1024p"]


@pytest.mark.asyncio
async def test_api_create_job_remote_without_credentials_returns_503(session, sample_project, monkeypatch):
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
                "options": {"motion_mode": "remote", "motion_provider": "google_veo"},
            },
        )

    assert response.status_code == 503
    assert "VIDEO_MOTION_GEMINI_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_create_job_invalid_motion_mode_returns_400(session, sample_project, monkeypatch):
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
                "options": {"motion_mode": "turbo"},
            },
        )

    assert response.status_code == 400
    assert "Chế độ chuyển động" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_job_response_hides_internal_identifiers(session, sample_project, monkeypatch):
    """公开响应不得暴露 operation id / 幂等键 / 执行权等内部字段"""
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    project_id, chapter_id = sample_project.id, chapter.id

    with TestClient(_build_api_app(session)) as client:
        created = client.post(
            "/api/video-export/jobs",
            headers={"x-test-user": "user-1"},
            json={"project_id": project_id, "chapter_ids": [chapter_id]},
        )
        assert created.status_code == 200, created.text
        detail = client.get(
            f"/api/video-export/jobs/{created.json()['id']}", headers={"x-test-user": "user-1"}
        )

    body = detail.text
    assert detail.status_code == 200
    for leaked in ("motion_operation_id", "motion_idempotency_key", "worker_token", "claimed_at"):
        assert leaked not in body, f"响应不得包含内部字段 {leaked}"
    scene_payload = detail.json()["scenes"][0]
    assert scene_payload["motion_status"] is None  # local 模式尚未渲染
    assert scene_payload["motion_provider"] is None


# --------------------------------------------------------------------------- 多 worker 执行权（lease）

@pytest.mark.asyncio
async def test_claim_job_is_atomic_and_blocks_second_worker(session, sample_project, monkeypatch):
    """两个 worker 同时领取：只有一个成功，避免重复提交远端任务"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )

    first = await video_export_service._claim_job(db=session, job=job, token="worker-a")
    second = await video_export_service._claim_job(db=session, job=job, token="worker-b")

    assert first is True
    assert second is False, "已被领取的任务不得被第二个 worker 再次领取"
    await session.refresh(job)
    assert job.worker_token == "worker-a" and job.claimed_at is not None


@pytest.mark.asyncio
async def test_run_job_skips_when_claim_held_by_other_worker(session, engine, sample_project, monkeypatch):
    """执行权被其它 worker 持有时，本进程直接跳过（不进入流水线）"""
    from app.services.video_export import service as service_module

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    job.worker_token = "other-worker"
    job.claimed_at = datetime.now()
    await session.commit()
    job_id = job.id

    monkeypatch.setattr(service_module, "get_engine", lambda user_id: _awaitable(engine))
    pipeline_calls: list[str] = []

    async def fake_pipeline(**kwargs):
        pipeline_calls.append("called")

    monkeypatch.setattr(service_module.video_export_service, "_render_pipeline", fake_pipeline)

    await video_export_service.run_job(job_id=job_id, user_id="user-1")

    assert pipeline_calls == []
    await session.refresh(job)
    assert job.worker_token == "other-worker", "跳过时不得抢占他人的执行权"
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_stale_claim_can_be_taken_over(session, sample_project, monkeypatch):
    """worker 崩溃后（lease 过期）其它 worker 可以接管"""
    from app.services.video_export import service as service_module

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    monkeypatch.setattr(settings, "video_job_timeout_seconds", 60)
    monkeypatch.setattr(settings, "video_claim_ttl_buffer_seconds", 0)
    job.worker_token = "dead-worker"
    job.claimed_at = datetime.now() - timedelta(seconds=300)
    await session.commit()

    assert await video_export_service._claim_job(db=session, job=job, token="worker-b") is True
    await session.refresh(job)
    assert job.worker_token == "worker-b"


@pytest.mark.asyncio
async def test_release_claim_after_terminal_state(session, engine, sample_project, monkeypatch):
    """任务收敛后必须释放执行权，其它 worker 才能重试"""
    _stub_spawn(monkeypatch)
    remote = _FakeRemoteProvider(fail=False)
    local = _FakeLocalProvider()

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job_for_pipeline(sample_project, chapter.id, mode="remote")
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)
    job.status = "pending"
    await session.commit()

    await _run_pipeline(engine, session, job, monkeypatch, remote, local)

    await session.refresh(job)
    assert job.status == "completed"
    assert job.worker_token is None and job.claimed_at is None


@pytest.mark.asyncio
async def test_retry_releases_lease_for_requeue(session, sample_project, monkeypatch):
    """重试时清空执行权，任务能被任意 worker 重新领取"""
    spawned = _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    job.status = "failed"
    job.worker_token = "stale-worker"
    job.claimed_at = datetime.now()
    await session.commit()

    await video_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)

    await session.refresh(job)
    assert job.status == "pending"
    assert job.worker_token is None and job.claimed_at is None
    assert spawned[-1] == (job.id, "user-1")


# --------------------------------------------------------------------------- 重试与计费安全


@pytest.mark.asyncio
async def test_retry_after_cancel_resumes_remote_operation_without_new_request(
    session, sample_project, monkeypatch
):
    """取消后远端操作可能仍在执行：重试必须续跑同一个 operation，不得重新下单"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
        options={"motion_mode": "local"},
    )
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    target = scenes[0]
    target.status = "failed"
    target.motion_provider = "xai_grok_imagine"
    target.motion_operation_id = "req-keep-me"
    target.motion_status = "cancelled"
    original_key = target.motion_idempotency_key
    await session.commit()

    await video_export_service.retry_scene(
        db=session, user_id="user-1", job_id=job.id, scene_id=target.id
    )

    await session.refresh(target)
    assert target.motion_operation_id == "req-keep-me", "operation id 必须保留以便续跑"
    assert target.motion_idempotency_key == original_key
    assert target.motion_status == "running"
    assert target.status == "pending"
    await session.refresh(job)
    assert "không tạo yêu cầu mới" in (job.status_message or "")


@pytest.mark.asyncio
async def test_retry_of_terminal_failure_starts_fresh_request(session, sample_project, monkeypatch):
    """远端已明确失败时，重试才生成新的幂等键（这是用户明确的意图）"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    target = scenes[0]
    target.status = "failed"
    target.motion_provider = "xai_grok_imagine"
    target.motion_operation_id = "req-dead"
    target.motion_status = "failed"
    original_key = target.motion_idempotency_key
    await session.commit()

    await video_export_service.retry_scene(
        db=session, user_id="user-1", job_id=job.id, scene_id=target.id
    )

    await session.refresh(target)
    assert target.motion_operation_id is None
    assert target.motion_idempotency_key != original_key
    assert target.motion_status == "pending"
    await session.refresh(job)
    assert "không tạo yêu cầu mới" not in (job.status_message or "")


@pytest.mark.asyncio
async def test_remote_timeout_keeps_operation_resumable(session, engine, sample_project, monkeypatch):
    """超时不是终态：远端操作可能仍在跑，状态保持 running 以便续跑"""
    from app.services.video_export.providers import MotionOperation
    from app.services.video_export.providers.base import MotionRenderResult

    class _TimeoutProvider(_FakeRemoteProvider):
        async def render_scene(self, *, request, out_path, cancel_check=None, timeout=None, on_operation=None):
            self.calls.append(request)
            if on_operation is not None:
                await on_operation(
                    MotionOperation(
                        provider=self.name,
                        model=self.default_model,
                        operation_id="fake-timeout",
                        status="running",
                    )
                )
            raise MotionTimeoutError("Provider chưa hoàn tất sau X giây")

    _stub_spawn(monkeypatch)
    remote = _TimeoutProvider(fail=True)
    local = _FakeLocalProvider()

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = _job_for_pipeline(sample_project, chapter.id, mode="remote")
    session.add(job)
    await session.commit()
    await _seed_scenes(db=session, job=job, chapter_id=chapter.id)
    job.status = "pending"
    await session.commit()

    scenes = await _run_pipeline(engine, session, job, monkeypatch, remote, local)

    assert job.status == "failed"
    assert all(scene.motion_status == "running" for scene in scenes)
    assert all(scene.motion_operation_id == "fake-timeout" for scene in scenes)
    assert not local.calls
    _ = MotionRenderResult  # 保持导入与类型一致


# --------------------------------------------------------------------------- 启动期安全检查


def _missing_lifespan_names(source: str) -> set[str]:
    """返回 lifespan 里“被使用但未定义”的 ORM 模型名（用于检测启动期 NameError 回归）"""
    import ast

    tree = ast.parse(source)
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            module_names.add(node.target.id)

    lifespan = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
    )
    local_names: set[str] = {arg.arg for arg in lifespan.args.args}
    for node in ast.walk(lifespan):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            local_names.add(node.id)
        elif isinstance(node, ast.Import):
            local_names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            local_names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local_names.add(node.name)

    used = {
        node.id
        for node in ast.walk(lifespan)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    known_models = {
        "VideoExportJob",
        "VideoExportScene",
        "BackgroundTask",
        "BatchGenerationTask",
        "AnalysisTask",
    }
    return (used & known_models) - (module_names | local_names)


def test_lifespan_import_guard_detects_missing_model_import():
    """自查：该守卫必须能发现“用了 VideoExportJob 但没 import”这种回归"""
    buggy = (
        "from app.models.background_task import BackgroundTask\n"
        "from sqlalchemy import update as sql_update\n"
        "async def lifespan(app):\n"
        "    await conn.execute(sql_update(VideoExportJob).values(status='failed'))\n"
    )
    assert _missing_lifespan_names(buggy) == {"VideoExportJob"}

    fixed = buggy.replace(
        "from app.models.background_task import BackgroundTask",
        "from app.models.background_task import BackgroundTask\n"
        "from app.models.video_export import VideoExportJob",
    )
    assert _missing_lifespan_names(fixed) == set()


def test_main_lifespan_has_no_missing_model_names():
    """回归：main.py 的启动块使用了未导入的 ORM 模型（VideoExportJob）会 NameError"""
    source_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    missing = _missing_lifespan_names(source_path.read_text(encoding="utf-8"))
    assert not missing, (
        f"startup 块使用了未导入的模型: {sorted(missing)} —— 会在应用启动时抛 NameError"
    )


def test_main_lifespan_uses_startup_helper_for_video_jobs():
    """回归：启动块不得直接引用未导入的模型，必须调用可测试的 startup helper"""
    main_source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "fail_interrupted_jobs" in main_source
    assert "sql_update(VideoExportJob)" not in main_source, "启动块不应直接拼 VideoExportJob 的 UPDATE"


@pytest.mark.asyncio
async def test_startup_fails_interrupted_jobs_but_keeps_remote_operation(session, sample_project, monkeypatch):
    """重启收敛：pending/running → failed、释放执行权，但保留分镜的远端操作以便续跑"""
    from app.services.video_export.startup import fail_interrupted_jobs

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    interrupted = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    interrupted.status = "running"
    interrupted.worker_token = "dead-worker"
    interrupted.claimed_at = datetime.now()
    done = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    done.status = "completed"
    await session.commit()

    scenes = await video_export_service._get_scenes(db=session, job_id=interrupted.id)
    scene = scenes[0]
    scene.motion_provider = "xai_grok_imagine"
    scene.motion_operation_id = "req-survives-restart"
    scene.motion_status = "running"
    await session.commit()

    affected = await fail_interrupted_jobs(session)

    assert affected == 1
    await session.refresh(interrupted)
    assert interrupted.status == "failed"
    assert "khởi động lại" in (interrupted.error_message or "")
    assert interrupted.worker_token is None and interrupted.claimed_at is None
    await session.refresh(done)
    assert done.status == "completed", "已结束的任务不应被改动"

    await session.refresh(scene)
    assert scene.motion_operation_id == "req-survives-restart", "operation id 必须保留以便续跑"
    assert scene.motion_status == "running"
