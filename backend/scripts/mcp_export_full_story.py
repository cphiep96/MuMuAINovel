"""Tao chuong + viet bang MCP (Exa) + xuat phim full truyen.

Khong in secret. Chi in tien do ASCII-safe cho Windows console.
"""
from __future__ import annotations

import json
import os
import sys
import time
import http.cookiejar
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "51429db0-c71e-4217-8c52-9a5ae10015c7"
BASE = os.environ.get("MUMU_API_BASE", "http://127.0.0.1:8137").rstrip("/")
CHAPTER_TIMEOUT = 90 * 60
VIDEO_TIMEOUT = 90 * 60


def _load_env() -> None:
    for env_path in (ROOT / ".env", ROOT / "backend" / ".env"):
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def log(msg: str) -> None:
    print(msg, flush=True)


class Api:
    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, payload=None, timeout: int = 120):
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body[:800]}
            return exc.code, parsed


def wait_until(predicate, timeout: int, interval: int, label: str):
    start = time.time()
    last = None
    while True:
        status, payload = predicate()
        snapshot = json.dumps(payload, ensure_ascii=False)[:400]
        if snapshot != last:
            log(f"{label} http={status} {snapshot}")
            last = snapshot
        if status >= 200 and status < 300 and payload.get("_done"):
            return payload
        if time.time() - start > timeout:
            raise SystemExit(f"{label} timeout after {timeout}s last={snapshot}")
        time.sleep(interval)


def main() -> int:
    _utf8()
    _load_env()
    api = Api(BASE)
    user = os.environ.get("LOCAL_AUTH_USERNAME") or "admin"
    password = os.environ.get("LOCAL_AUTH_PASSWORD") or "admin123"

    log(f"PHASE login base={BASE}")
    st, login = api.call("POST", "/api/auth/local/login", {"username": user, "password": password})
    if st != 200:
        raise SystemExit(f"login failed {st} {login}")
    log("PHASE login ok")

    st, plugins = api.call("GET", "/api/mcp/plugins")
    enabled = []
    if isinstance(plugins, list):
        enabled = [p.get("name") for p in plugins if p.get("enabled")]
    log(f"PHASE mcp_plugins enabled={enabled}")

    st, outlines = api.call("GET", f"/api/outlines/project/{PROJECT_ID}")
    items = (outlines.get("items") or []) if isinstance(outlines, dict) else []
    items = sorted(items, key=lambda x: x.get("order_index") or 0)
    if not items:
        raise SystemExit("no outlines")
    log(f"PHASE outlines count={len(items)}")

    st, chapters = api.call("GET", f"/api/chapters/project/{PROJECT_ID}")
    existing = (chapters.get("items") or []) if isinstance(chapters, dict) else []
    by_number = {int(ch["chapter_number"]): ch for ch in existing}

    created_ids = []
    for outline in items:
        number = int(outline.get("order_index") or (len(created_ids) + 1))
        if number in by_number:
            ch = by_number[number]
            created_ids.append(ch["id"])
            log(f"PHASE chapter exists n={number} id={ch['id']} words={ch.get('word_count')}")
            continue
        payload = {
            "project_id": PROJECT_ID,
            "title": outline.get("title") or f"Chuong {number}",
            "chapter_number": number,
            "summary": outline.get("content") or "",
            "status": "pending",
            "outline_id": outline.get("id"),
            "sub_index": 1,
        }
        st, created = api.call("POST", "/api/chapters", payload)
        if st >= 400:
            raise SystemExit(f"create chapter failed {st} {created}")
        created_ids.append(created["id"])
        by_number[number] = created
        log(f"PHASE chapter created n={number} id={created['id']}")

    st, chapters = api.call("GET", f"/api/chapters/project/{PROJECT_ID}")
    existing = sorted(
        (chapters.get("items") or []) if isinstance(chapters, dict) else [],
        key=lambda x: x.get("chapter_number") or 0,
    )
    empty = [ch for ch in existing if not (ch.get("content") or "").strip()]
    log(f"PHASE chapters total={len(existing)} empty={len(empty)}")

    if empty:
        st, batch = api.call(
            "POST",
            f"/api/chapters/project/{PROJECT_ID}/batch-generate",
            {
                "start_chapter_number": empty[0]["chapter_number"],
                "count": len(empty),
                "target_word_count": 1500,
                "enable_mcp": True,
                "enable_analysis": True,
                "max_retries": 3,
            },
        )
        if st >= 400:
            raise SystemExit(f"batch generate failed {st} {batch}")
        batch_id = batch.get("batch_id")
        log(f"PHASE generate_start batch_id={batch_id} count={len(empty)} mcp=1")

        def poll_batch():
            code, data = api.call("GET", f"/api/chapters/batch-generate/{batch_id}/status")
            status = (data.get("status") or "").lower() if isinstance(data, dict) else ""
            if isinstance(data, dict):
                data = dict(data)
                data["_done"] = status in ("completed", "failed", "cancelled")
            else:
                data = {"_done": False, "raw": data}
            return code, data

        result = wait_until(poll_batch, CHAPTER_TIMEOUT, 12, "PHASE generate")
        if (result.get("status") or "").lower() != "completed":
            raise SystemExit(f"generate failed {result}")
        log("PHASE generate done")
    else:
        log("PHASE generate skip already written")

    st, chapters = api.call("GET", f"/api/chapters/project/{PROJECT_ID}")
    ready = [
        ch
        for ch in sorted((chapters.get("items") or []), key=lambda x: x.get("chapter_number") or 0)
        if (ch.get("content") or "").strip()
    ]
    if not ready:
        raise SystemExit("no chapter content after generate")
    chapter_ids = [ch["id"] for ch in ready]
    log(
        "PHASE ready "
        + ", ".join(f"n={ch.get('chapter_number')} words={ch.get('word_count')}" for ch in ready)
    )

    st, job = api.call(
        "POST",
        "/api/video-export/jobs",
        {
            "project_id": PROJECT_ID,
            "chapter_ids": chapter_ids,
            "options": {
                "resolution": "1280x720",
                "fps": 24,
                "use_project_cover": True,
                "tts_enabled": True,
                "tts_provider": "deepgram",
                "tts_model": "flux-hannah-en",
                "narration_chars_per_scene": 150,
                "motion_mode": "local",
                "generate_scene_images": True,
                "image_provider": "meta_muse_image",
                "image_model": "muse-image-1.0",
                "image_aspect_ratio": "16:9",
                "image_size": "1792x1024",
            },
        },
        timeout=180,
    )
    if st >= 400:
        raise SystemExit(f"video create failed {st} {job}")
    job_id = job.get("id")
    log(
        f"PHASE video_start job_id={job_id} scenes={job.get('scene_count')} "
        f"duration={job.get('duration_seconds')} status={job.get('status')}"
    )

    def poll_video():
        code, data = api.call("GET", f"/api/video-export/jobs/{job_id}")
        status = (data.get("status") or "").lower() if isinstance(data, dict) else ""
        slim = {}
        if isinstance(data, dict):
            slim = {
                "status": data.get("status"),
                "progress": data.get("progress"),
                "status_message": data.get("status_message"),
                "error_message": data.get("error_message"),
                "scene_count": data.get("scene_count"),
                "has_video": data.get("has_video"),
                "_done": status in ("completed", "failed", "cancelled"),
            }
        return code, slim

    video = wait_until(poll_video, VIDEO_TIMEOUT, 10, "PHASE video")
    if (video.get("status") or "").lower() != "completed":
        raise SystemExit(f"video failed {video}")
    log(
        f"PHASE video done job_id={job_id} "
        f"url={BASE}/api/video-export/jobs/{job_id}/download/video "
        f"ui=http://localhost:5173/project/{PROJECT_ID}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
