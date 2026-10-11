"""Automation meta.ai/create bằng Playwright persistent profile."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

CREATE_URL = "https://www.meta.ai/create"
PROMPT_URL_RE = re.compile(r"https://www\.meta\.ai/prompt/[0-9a-f-]+", re.I)
VIDEO_FILE_RE = re.compile(r"https?://[^\s\"'\\]+\.(?:mp4|webm|m3u8)(?:\?[^\s\"'\\]*)?", re.I)
HTTP_URL_RE = re.compile(r"https?://[^\s\"'\\]+", re.I)
REFUSAL_RE = re.compile(
    r"video animation isn't available|"
    r"isn't available right now|"
    r"can't generate a true|"
    r"i can't generate|"
    r"unable to generate|"
    r"can't create video|"
    r"not able to generate video|"
    r"i can't create a video|"
    r"video (?:generation|creation) (?:isn't|is not|not) available",
    re.I,
)


def default_profile_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "meta_ai_playwright_profile"


def default_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "storage" / "meta_ai_videos"


def _log(msg: str) -> None:
    print(f"[meta-ai] {msg}", file=sys.stderr, flush=True)


def _headed(*, default: bool = True) -> bool:
    import os

    raw = str(os.getenv("META_AI_HEADED", "")).strip().lower()
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    return default


def _use_chrome_channel() -> Optional[str]:
    import os

    raw = str(os.getenv("META_AI_BROWSER_CHANNEL", "chrome")).strip().lower()
    if raw in {"", "none", "chromium"}:
        return None
    return raw


def _launch_kwargs(*, headless: bool) -> dict[str, Any]:
    return {
        "headless": headless,
        "channel": _use_chrome_channel(),
        "accept_downloads": True,
        "viewport": {"width": 1360, "height": 900},
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }


def _is_html_artifact(url: str) -> bool:
    parsed = urlparse(url or "")
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    host = (parsed.hostname or "").lower()
    if "metaaiusercontent.com" in host and ("/html" in path or "artifact_uuid" in query):
        return True
    return "/html" in path and "artifact_uuid" in query


def _is_playable_video_url(url: str) -> bool:
    if not url or url.startswith(("blob:", "data:")):
        return False
    if _is_html_artifact(url):
        return False
    lowered = url.lower()
    if VIDEO_FILE_RE.search(url):
        return True
    if any(token in lowered for token in (".mp4", ".webm", "mime=video", "/video/", "video_redirect")):
        return True
    return False


def _short_exc(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:180]


def _looks_like_video_bytes(body: bytes) -> bool:
    if not body or len(body) < 4096:
        return False
    head = body[:64].lstrip()
    if head.startswith((b"<", b"{", b"[")):
        return False
    if b"ftyp" in body[:32] or body[:4] == b"\x1aE\xdf\xa3":
        return True
    return len(body) >= 20_000


def _add_unique(bucket: list[str], url: str) -> bool:
    if not url or url in bucket:
        return False
    bucket.append(url)
    return True


def _walk_urls(obj: Any) -> list[str]:
    found: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and value.startswith(("http://", "https://", "blob:")):
                    key_l = str(key).lower()
                    if key_l in {
                        "uri",
                        "url",
                        "src",
                        "hd_src",
                        "sd_src",
                        "playback_url",
                        "video_url",
                        "download_url",
                        "playable_url",
                    } or _is_playable_video_url(value):
                        _add_unique(found, value)
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, str):
            for match in VIDEO_FILE_RE.finditer(node):
                _add_unique(found, match.group(0).rstrip("\\\",'"))

    visit(obj)
    return found


async def _wait_for_logged_in(page, *, timeout_ms: int) -> None:
    """Chờ UI composer / create sau khi user login tay."""
    deadline = time.monotonic() + timeout_ms / 1000
    last_url = ""
    while time.monotonic() < deadline:
        url = page.url or ""
        if url != last_url:
            last_url = url
        if "facebook.com" in url or "login" in url.lower():
            await asyncio.sleep(1.5)
            continue
        for sel in (
            'input[type="file"]',
            '[contenteditable="true"]',
            "textarea",
            '[data-testid*="composer"]',
            '[aria-label*="Prompt"]',
            '[aria-label*="prompt"]',
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=500):
                    return
            except Exception:  # noqa: BLE001
                pass
        if "/create" in url or PROMPT_URL_RE.search(url):
            return
        await asyncio.sleep(1.5)
    raise TimeoutError(
        "Hết thời gian chờ đăng nhập. Mở meta.ai/create, đăng nhập Facebook/Meta, rồi thử lại."
    )


async def open_login_browser(
    *,
    profile_dir: Optional[Path] = None,
    wait_minutes: int = 15,
) -> dict[str, Any]:
    """Mở Chromium có profile; user đăng nhập tay trên meta.ai."""
    from playwright.async_api import async_playwright

    profile = Path(profile_dir or default_profile_dir())
    profile.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(profile),
            **_launch_kwargs(headless=False),
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(CREATE_URL, wait_until="domcontentloaded", timeout=120_000)
        try:
            await _wait_for_logged_in(page, timeout_ms=max(60, wait_minutes) * 60_000)
            logged_in = True
            message = "Đã thấy trang Create / composer. Đóng cửa sổ trình duyệt khi xong."
        except TimeoutError as exc:
            logged_in = False
            message = str(exc)
        finally:
            await context.close()
    return {
        "success": logged_in,
        "message": message,
        "profile_dir": str(profile),
    }


async def check_session(*, profile_dir: Optional[Path] = None) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    profile = Path(profile_dir or default_profile_dir())
    if not profile.is_dir():
        return {
            "success": False,
            "logged_in": False,
            "message": f"Chưa có profile. Chạy login trước: {profile}",
            "profile_dir": str(profile),
        }
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(profile),
            **_launch_kwargs(headless=True),
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(CREATE_URL, wait_until="domcontentloaded", timeout=120_000)
            await _wait_for_logged_in(page, timeout_ms=45_000)
            return {
                "success": True,
                "logged_in": True,
                "message": "Session meta.ai còn hiệu lực",
                "profile_dir": str(profile),
                "url": page.url,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "logged_in": False,
                "message": f"Session hết hạn hoặc chưa login: {type(exc).__name__}",
                "profile_dir": str(profile),
                "url": page.url,
            }
        finally:
            await context.close()


async def _select_video_mode(page) -> None:
    for role, name in (
        ("tab", r"Video"),
        ("button", r"Video"),
        ("button", r"Generate video|Image to video|Create video"),
    ):
        loc = page.get_by_role(role, name=re.compile(name, re.I))
        if await loc.count() == 0:
            continue
        try:
            await loc.first.click(timeout=3000)
            _log(f"Đã chọn mode video ({name})")
            await asyncio.sleep(0.8)
            return
        except Exception:  # noqa: BLE001
            continue


async def _click_attach_button(page) -> bool:
    locators = (
        page.get_by_role("button", name=re.compile(r"add|attach|upload|photo|image|plus|file", re.I)),
        page.locator(
            'button[aria-label*="Add" i], button[aria-label*="Attach" i], '
            'button[aria-label*="Upload" i], button[aria-label*="Photo" i], '
            'button[aria-label*="Image" i], button[aria-label*="plus" i]'
        ),
    )
    for loc in locators:
        if await loc.count() == 0:
            continue
        try:
            await loc.last.click(timeout=4000)
            _log("Đã bấm nút đính kèm (+)")
            await asyncio.sleep(0.6)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _composer_has_image(page) -> bool:
    for sel in (
        'form img',
        '[contenteditable="true"] img',
        '[role="textbox"] img',
        'img[alt*="upload" i]',
        'img[alt*="attachment" i]',
        'img[alt*="image" i]',
    ):
        try:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.last.is_visible(timeout=500):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _upload_reference_image(page, image_path: Path) -> None:
    image_path = image_path.resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy ảnh: {image_path}")

    uploads: list[str] = []

    def on_request(request) -> None:
        url = request.url or ""
        if "rupload.meta.ai" in url or "recent-upload-media" in url:
            uploads.append(url)

    page.on("request", on_request)
    try:
        await _click_attach_button(page)
        file_inputs = page.locator('input[type="file"]')
        if await file_inputs.count() == 0:
            raise RuntimeError("Không tìm thấy ô upload ảnh trên meta.ai (bấm + cạnh Ask Meta AI).")

        target = file_inputs.last
        for index in range(await file_inputs.count()):
            accept = (await file_inputs.nth(index).get_attribute("accept") or "").lower()
            if "image" in accept or "video" in accept or not accept:
                target = file_inputs.nth(index)
        await target.set_input_files(str(image_path))
        _log(f"Đã set file {image_path.name}, chờ Meta nhận ảnh…")

        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if uploads or await _composer_has_image(page):
                _log("Ảnh đã đính kèm trên composer / rupload")
                await asyncio.sleep(1.0)
                return
            await asyncio.sleep(0.5)
        raise RuntimeError(
            "Ảnh không được đính kèm vào prompt (composer vẫn chỉ có chữ). "
            "Trên cửa sổ Chrome hãy bấm + rồi chọn ảnh, sau đó chạy lại."
        )
    finally:
            try:
                page.remove_listener("request", on_request)
            except Exception:  # noqa: BLE001
                pass


async def _fill_prompt(page, prompt: str) -> None:
    text = (prompt or "").strip()
    if not text:
        raise ValueError("Prompt trống")
    targets = [
        page.locator('[contenteditable="true"]').last,
        page.locator("textarea").last,
        page.get_by_role("textbox").last,
    ]
    for loc in targets:
        if await loc.count() == 0:
            continue
        try:
            await loc.click(timeout=5000)
            await loc.fill(text)
            return
        except Exception:  # noqa: BLE001
            try:
                await loc.click(timeout=5000)
                await page.keyboard.press("Control+A")
                await page.keyboard.type(text, delay=15)
                return
            except Exception:  # noqa: BLE001
                continue
    raise RuntimeError("Không tìm thấy ô nhập prompt trên meta.ai/create")


async def _submit_prompt(page) -> None:
    for sel in (
        'button[type="submit"]',
        '[aria-label*="Send"]',
        '[aria-label*="Create"]',
        '[aria-label*="Generate"]',
    ):
        btn = page.locator(sel).first
        if await btn.count() > 0:
            try:
                await btn.click(timeout=3000)
                return
            except Exception:  # noqa: BLE001
                pass
    await page.keyboard.press("Enter")


async def _assistant_refusal(page) -> Optional[str]:
    try:
        text = await page.inner_text("body", timeout=2000)
    except Exception:  # noqa: BLE001
        return None
    match = REFUSAL_RE.search(text or "")
    if not match:
        return None
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 120)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _maybe_video_response(response) -> Optional[str]:
    try:
        url = response.url or ""
        if url.startswith(("blob:", "data:")):
            return None
        ctype = (response.headers or {}).get("content-type", "").lower()
        if "video/" in ctype or _is_playable_video_url(url):
            return url
    except Exception:  # noqa: BLE001
        return None
    return None


async def _capture_response_video(response, captured: list[str], bodies: list[tuple[str, bytes]]) -> None:
    url = _maybe_video_response(response)
    if not url:
        return
    try:
        body = await response.body()
    except Exception:  # noqa: BLE001
        if _add_unique(captured, url):
            _log(f"Thấy URL video (chưa lấy được body): {url[:100]}")
        return
    if not _looks_like_video_bytes(body):
        return
    bodies.append((url, body))
    _log(f"Bắt {len(body)} bytes video từ network: {url[:90]}")


async def _graphql_capture(response, captured: list[str], artifacts: list[str]) -> None:
    try:
        if "/api/graphql" not in (response.url or ""):
            return
        raw = await response.text()
    except Exception:  # noqa: BLE001
        return
    urls: list[str] = []
    try:
        urls.extend(_walk_urls(json.loads(raw)))
    except Exception:  # noqa: BLE001
        for match in HTTP_URL_RE.finditer(raw):
            urls.append(match.group(0).rstrip("\\\",'"))
    for url in urls:
        if _is_html_artifact(url):
            if _add_unique(artifacts, url):
                _log(f"Thấy artifact HTML (player, chưa phải MP4): {url[:90]}")
        elif _is_playable_video_url(url):
            if _add_unique(captured, url):
                _log(f"Bắt URL video từ GraphQL: {url[:100]}")


def _b64_to_bytes(b64: str) -> bytes:
    return base64.b64decode(b64)


_FETCH_BYTES_JS = """async (url) => {
    const resp = await fetch(url, { credentials: 'include' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const buf = await resp.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
}"""

_RECORD_VIDEO_JS = """async () => {
    const v = document.querySelector('video');
    if (!v) throw new Error('no-video');
    const src = v.currentSrc || v.src || (v.querySelector('source') && v.querySelector('source').src) || '';
    if (src && !src.startsWith('blob:')) {
        const resp = await fetch(src, { credentials: 'include' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const buf = await resp.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let binary = '';
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        }
        return { kind: 'fetch', src, b64: btoa(binary) };
    }
    if (v.readyState < 2) throw new Error('video-not-ready');
    v.muted = true;
    try { await v.play(); } catch (e) {}
    const duration = (Number.isFinite(v.duration) && v.duration > 0 && v.duration < 120) ? v.duration : 8;
    const stream = v.captureStream();
    const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
        ? 'video/webm;codecs=vp9'
        : 'video/webm';
    const rec = new MediaRecorder(stream, { mimeType: mime });
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.start(200);
    await new Promise((resolve) => {
        const timer = setTimeout(resolve, Math.ceil((duration + 0.8) * 1000));
        v.onended = () => { clearTimeout(timer); resolve(); };
    });
    rec.stop();
    await new Promise((resolve) => { rec.onstop = resolve; });
    const blob = new Blob(chunks, { type: mime });
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return { kind: 'record', src: src || 'captureStream', b64: btoa(binary) };
}"""


async def _fetch_bytes_in_world(target, url: str) -> bytes:
    b64 = await target.evaluate(_FETCH_BYTES_JS, url)
    return _b64_to_bytes(b64)


async def _find_video_in_frames(page) -> tuple[Optional[str], Any]:
    for frame in page.frames:
        try:
            src = await frame.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    if (!v) return null;
                    if (v.readyState < 2 && !(v.currentSrc || v.src)) return null;
                    if (v.currentSrc) return v.currentSrc;
                    if (v.src) return v.src;
                    const s = v.querySelector('source');
                    return s ? (s.src || null) : null;
                }"""
            )
            if src:
                return str(src), frame
        except Exception:  # noqa: BLE001
            continue
    return None, None


async def _save_from_video_element(frame, out: Path) -> Optional[str]:
    try:
        result = await frame.evaluate(_RECORD_VIDEO_JS)
    except Exception as exc:  # noqa: BLE001
        _log(f"Không lấy được bytes từ <video>: {_short_exc(exc)}")
        return None
    if not result or not result.get("b64"):
        return None
    body = _b64_to_bytes(result["b64"])
    if not _looks_like_video_bytes(body):
        _log(f"Bytes từ <video> không giống video ({len(body)} bytes, kind={result.get('kind')})")
        return None
    out.write_bytes(body)
    src = str(result.get("src") or "video-element")
    _log(f"Đã lấy video từ <video> ({result.get('kind')}, {len(body)} bytes)")
    return src


async def _click_download(page, out: Path) -> Optional[str]:
    labels = (
        r"Download",
        r"Tải xuống",
        r"Save video",
        r"Save",
    )
    for label in labels:
        btn = page.get_by_role("button", name=re.compile(label, re.I))
        if await btn.count() == 0:
            btn = page.locator(f'[aria-label*="{label.split()[0]}"]')
        if await btn.count() == 0:
            continue
        try:
            async with page.expect_download(timeout=20_000) as pending:
                await btn.first.click(timeout=5000)
            download = await pending.value
            await download.save_as(str(out))
            if out.is_file() and out.stat().st_size >= 4096:
                _log(f"Đã tải qua nút {label}: {out.name} ({out.stat().st_size} bytes)")
                return download.url or "download"
        except Exception as exc:  # noqa: BLE001
            _log(f"Nút {label} chưa tải được: {type(exc).__name__}")
    return None


async def _try_save_video(
    page,
    captured: list[str],
    artifacts: list[str],
    bodies: list[tuple[str, bytes]],
    failed: set[str],
    out: Path,
    *,
    try_download: bool,
    try_record: bool,
) -> Optional[str]:
    if bodies:
        url, body = bodies[-1]
        out.write_bytes(body)
        _log(f"Lưu video từ network capture: {len(body)} bytes")
        return url

    src, frame = await _find_video_in_frames(page)
    if try_record and src and frame is not None:
        saved = await _save_from_video_element(frame, out)
        if saved:
            return saved

    for url in list(captured):
        if url in failed or not _is_playable_video_url(url):
            continue
        try:
            _log(f"Tải URL video (cookie trình duyệt): {url[:100]}")
            body = await _fetch_bytes_in_world(page, url)
            if _looks_like_video_bytes(body):
                out.write_bytes(body)
                return url
            _log(f"Bỏ URL không phải video ({len(body)} bytes)")
            failed.add(url)
        except Exception as exc:  # noqa: BLE001
            failed.add(url)
            _log(f"Fetch URL thất bại: {_short_exc(exc)}")

    if try_download and (artifacts or src):
        downloaded = await _click_download(page, out)
        if downloaded:
            return downloaded
    return None


async def _wait_and_save_video(
    page,
    captured: list[str],
    artifacts: list[str],
    bodies: list[tuple[str, bytes]],
    out: Path,
    *,
    timeout_sec: int,
) -> str:
    deadline = time.monotonic() + timeout_sec
    last_status = 0.0
    last_download_try = 0.0
    last_record_try = 0.0
    failed: set[str] = set()
    while time.monotonic() < deadline:
        now = time.monotonic()
        try_download = bool(artifacts) and (now - last_download_try >= 30)
        if try_download:
            last_download_try = now
        try_record = now - last_record_try >= 20
        if try_record:
            last_record_try = now
        saved = await _try_save_video(
            page,
            captured,
            artifacts,
            bodies,
            failed,
            out,
            try_download=try_download,
            try_record=try_record,
        )
        if saved:
            return saved
        refusal = await _assistant_refusal(page)
        if refusal:
            raise RuntimeError(
                "Meta AI trả lời chat, không generate video: "
                f"{refusal} — dừng sớm, không chờ hết timeout."
            )
        if now - last_status >= 15:
            last_status = now
            elapsed = int(now - (deadline - timeout_sec))
            if artifacts:
                hint = "artifact HTML đã có"
            elif bodies:
                hint = "đã bắt bytes video"
            elif captured:
                hint = f"{len(captured)} URL video"
            else:
                hint = "chưa thấy player"
            _log(f"Đang chờ video… {elapsed}s / {timeout_sec}s ({hint}; url={page.url})")
        await asyncio.sleep(2.0)
    raise TimeoutError(
        f"Không tải được file video sau {timeout_sec}s. "
        "Nếu cửa sổ Chrome đã có video, bấm Download thủ công rồi copy file vào storage/meta_ai_videos."
    )


async def create_video(
    *,
    prompt: str,
    image_path: str,
    output_path: Optional[str] = None,
    profile_dir: Optional[Path] = None,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    profile = Path(profile_dir or default_profile_dir())
    image = Path(image_path)
    out_dir = default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    if output_path:
        out = Path(output_path)
    else:
        stamp = int(time.time())
        out = out_dir / f"meta_ai_{stamp}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    captured_urls: list[str] = []
    artifact_urls: list[str] = []
    video_bodies: list[tuple[str, bytes]] = []
    headed = _headed(default=True)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(profile),
            **_launch_kwargs(headless=not headed),
        )
        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(response):
            await _capture_response_video(response, captured_urls, video_bodies)
            html_url = response.url or ""
            if _is_html_artifact(html_url) and _add_unique(artifact_urls, html_url):
                _log(f"Player HTML đã load: {html_url[:90]}")
            await _graphql_capture(response, captured_urls, artifact_urls)

        page.on("response", lambda response: asyncio.create_task(on_response(response)))
        started = time.monotonic()
        try:
            _log(f"Mở meta.ai/create (headed={headed})…")
            await page.goto(CREATE_URL, wait_until="domcontentloaded", timeout=120_000)
            _log("Kiểm tra session đăng nhập…")
            await _wait_for_logged_in(page, timeout_ms=60_000)
            await _select_video_mode(page)
            _log(f"Upload ảnh: {image.name}")
            await _upload_reference_image(page, image)
            _log("Nhập prompt…")
            await _fill_prompt(page, prompt)
            _log("Gửi prompt — Meta AI thường mất 2–8 phút render video…")
            await _submit_prompt(page)
            remaining = max(60, timeout_sec - int(time.monotonic() - started))
            _log(f"Chờ video (tối đa {remaining}s)…")
            video_url = await _wait_and_save_video(
                page,
                captured_urls,
                artifact_urls,
                video_bodies,
                out,
                timeout_sec=remaining,
            )
            size = out.stat().st_size if out.is_file() else 0
            if size < 4096:
                raise RuntimeError("File video quá nhỏ — generation có thể chưa xong")
            _log(f"Đã lưu: {out} ({size} bytes)")
            return {
                "success": True,
                "message": "Đã tạo và tải video từ meta.ai",
                "video_path": str(out.resolve()),
                "video_url": video_url,
                "profile_dir": str(profile),
                "prompt": prompt,
                "image_path": str(image.resolve()),
                "elapsed_sec": round(time.monotonic() - started, 1),
            }
        finally:
            await context.close()
