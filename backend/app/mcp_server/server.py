"""FastMCP server exposing MuMuAINovel story operations.

The database and video-export calls intentionally reuse the app's SQLAlchemy
models/services.  Wizard and chapter-generation calls use the existing HTTP
routes because those routes own the long-running SSE/background-task logic.

Configuration (never hard-code secrets):
* ``MUMU_API_BASE`` - FastAPI base URL, default ``http://127.0.0.1:8000``.
* ``MUMU_MCP_TOKEN`` - shared MCP bearer token or a signed session token.
* ``MUMU_SESSION_TOKEN`` - alias for the signed session token.
* ``MUMU_MCP_USER_ID`` - user id used for direct DB calls.
* ``MUMU_USER_ID`` - backwards-compatible user id alias.
* ``MUMU_MCP_HOST``/``MUMU_MCP_PORT`` - optional HTTP listener settings.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Sequence
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from app.constants.prompt_categories import CATEGORY_LIST
from app.database import check_database_health, get_engine
from app.models.career import Career
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.prompt_template import PromptTemplate
from app.models.writing_style import WritingStyle
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.security import verify_session_token
from app.services.video_export.service import (
    DOWNLOAD_KIND_SUBTITLES,
    DOWNLOAD_KIND_VIDEO,
    serialize_job,
    video_export_service,
)


class MCPConfigurationError(RuntimeError):
    """Cấu hình MCP thiếu user/token bắt buộc."""


@dataclass(frozen=True)
class MCPSettings:
    api_base: str = os.getenv("MUMU_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    token: str = os.getenv("MUMU_MCP_TOKEN") or os.getenv("MUMU_SESSION_TOKEN", "")
    user_id: str = os.getenv("MUMU_MCP_USER_ID") or os.getenv("MUMU_USER_ID", "")
    http_host: str = os.getenv("MUMU_MCP_HOST", "127.0.0.1")
    http_port: int = int(os.getenv("MUMU_MCP_PORT", "8765"))


def _settings() -> MCPSettings:
    """Read env at call time so tests/embedded launchers can set env safely."""
    return MCPSettings(
        api_base=os.getenv("MUMU_API_BASE", "http://127.0.0.1:8000").rstrip("/"),
        token=os.getenv("MUMU_MCP_TOKEN") or os.getenv("MUMU_SESSION_TOKEN", ""),
        user_id=os.getenv("MUMU_MCP_USER_ID") or os.getenv("MUMU_USER_ID", ""),
        http_host=os.getenv("MUMU_MCP_HOST", "127.0.0.1"),
        http_port=int(os.getenv("MUMU_MCP_PORT", "8765")),
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _model_dict(obj: Any, fields: Sequence[str]) -> dict[str, Any]:
    return {field: _jsonable(getattr(obj, field, None)) for field in fields}


PROJECT_FIELDS = (
    "id", "user_id", "title", "description", "theme", "genre", "target_words",
    "current_words", "status", "wizard_status", "wizard_step", "outline_mode",
    "world_time_period", "world_location", "world_atmosphere", "world_rules",
    "chapter_count", "narrative_perspective", "character_count", "cover_image_url",
    "cover_status", "created_at", "updated_at",
)
CHAPTER_FIELDS = (
    "id", "project_id", "title", "chapter_number", "content", "summary",
    "word_count", "status", "outline_id", "sub_index", "expansion_plan",
    "created_at", "updated_at",
)


class _TokenVerifier:
    """Verifier for a shared MCP token or the app's signed session token."""

    def __init__(self, cfg: MCPSettings | None = None):
        self.cfg = cfg

    async def verify_token(self, token: str) -> AccessToken | None:
        cfg = self.cfg or _settings()
        configured = cfg.token
        if not configured or not secrets.compare_digest(token, configured):
            return None
        return AccessToken(token=token, client_id=cfg.user_id or "mumu-agent", scopes=["mumu"])


class _ApiClient:
    def __init__(self, cfg: MCPSettings):
        self.cfg = cfg

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.cfg.token:
            headers["Authorization"] = f"Bearer {self.cfg.token}"
            # Signed session tokens are also accepted by the regular app auth.
            headers["Cookie"] = f"session_token={self.cfg.token}"
        if self.cfg.user_id:
            headers["X-Mumu-User-ID"] = self.cfg.user_id
        return headers

    async def json(self, method: str, path: str, **kwargs: Any) -> Any:
        url = urljoin(self.cfg.api_base + "/", path.lstrip("/"))
        headers = dict(self.headers())
        headers.update(kwargs.pop("headers", {}) or {})
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
        if response.status_code >= 400:
            detail: Any = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(f"MuMu API {response.status_code}: {detail}")
        if not response.content:
            return {}
        return response.json()

    async def sse(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = urljoin(self.cfg.api_base + "/", path.lstrip("/"))
        events: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(url, headers=self.headers(), json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"MuMu API {response.status_code}: {response.text}")
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        result = next((e.get("data") for e in reversed(events) if e.get("type") == "result"), None)
        error = next((e for e in reversed(events) if e.get("type") == "error"), None)
        return {
            "events": events,
            "result": result,
            "error": error,
            "completed": any(e.get("type") == "done" for e in events),
            "progress": next((e.get("progress") for e in reversed(events) if e.get("type") == "progress"), None),
        }


class MCPRuntime:
    def __init__(self, cfg: MCPSettings | None = None):
        raw = cfg or _settings()
        # A signed session token already carries its user id, so a separate
        # MUMU_MCP_USER_ID is optional for that supported authentication mode.
        derived_user = raw.user_id or verify_session_token(raw.token) or ""
        self.cfg = MCPSettings(
            api_base=raw.api_base,
            token=raw.token,
            user_id=derived_user,
            http_host=raw.http_host,
            http_port=raw.http_port,
        )

    def require_user(self) -> str:
        if not self.cfg.token:
            raise MCPConfigurationError(
                "Thiếu MUMU_MCP_TOKEN (hoặc MUMU_SESSION_TOKEN); không chạy MCP mutation khi chưa có secret."
            )
        if self.cfg.user_id:
            return self.cfg.user_id
        raise MCPConfigurationError(
            "Thiếu MUMU_MCP_USER_ID (hoặc MUMU_USER_ID); MCP cần user id để cô lập dữ liệu."
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        engine = await get_engine(self.require_user())
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            yield db

    def api(self) -> _ApiClient:
        return _ApiClient(self.cfg)


def _register_tools(server: FastMCP, runtime: MCPRuntime) -> None:
    @server.tool(name="mumu_auth_status", description="Kiểm tra cấu hình xác thực MCP và user hiện tại.")
    async def mumu_auth_status() -> dict[str, Any]:
        token = runtime.cfg.token
        return {
            "authenticated": bool(token and runtime.cfg.user_id),
            "token_configured": bool(token),
            "user_id": runtime.cfg.user_id or None,
            "api_base": runtime.cfg.api_base,
            "transport_auth": "Bearer MUMU_MCP_TOKEN (hoặc session cookie nội bộ)",
        }

    @server.tool(name="mumu_health", description="Kiểm tra sức khỏe MCP, API và cơ sở dữ liệu.")
    async def mumu_health() -> dict[str, Any]:
        try:
            db = await check_database_health(runtime.cfg.user_id or None)
        except Exception as exc:  # health should report, not crash the agent
            db = {"healthy": False, "error": str(exc)}
        return {"status": "ok" if db.get("healthy", True) else "degraded", "database": db, "api_base": runtime.cfg.api_base}

    @server.tool(name="list_projects", description="Liệt kê các truyện/dự án của user hiện tại.")
    async def list_projects(skip: int = 0, limit: int = 100) -> dict[str, Any]:
        async for db in runtime.session():
            total = (await db.execute(select(func.count(Project.id)).where(Project.user_id == runtime.require_user()))).scalar_one()
            rows = (await db.execute(select(Project).where(Project.user_id == runtime.require_user()).order_by(Project.updated_at.desc()).offset(max(skip, 0)).limit(min(max(limit, 1), 100)))).scalars().all()
            return {"total": total, "items": [_model_dict(row, PROJECT_FIELDS) for row in rows]}

    @server.tool(name="create_project", description="Tạo một truyện/dự án mới không cần mở web UI.")
    async def create_project(title: str, description: str | None = None, theme: str | None = None, genre: str | None = None, target_words: int | None = None, outline_mode: str = "one-to-many") -> dict[str, Any]:
        payload = ProjectCreate(title=title, description=description, theme=theme, genre=genre, target_words=target_words, outline_mode=outline_mode)
        async for db in runtime.session():
            project = Project(**payload.model_dump(), user_id=runtime.require_user())
            db.add(project)
            await db.commit()
            await db.refresh(project)
            return _model_dict(project, PROJECT_FIELDS)

    @server.tool(name="update_project", description="Cập nhật thông tin truyện/dự án (bao gồm thể loại/genre).")
    async def update_project(project_id: str, title: str | None = None, description: str | None = None, theme: str | None = None, genre: str | None = None, target_words: int | None = None, status: str | None = None) -> dict[str, Any]:
        update = ProjectUpdate(**{k: v for k, v in {"title": title, "description": description, "theme": theme, "genre": genre, "target_words": target_words, "status": status}.items() if v is not None})
        async for db in runtime.session():
            row = (await db.execute(select(Project).where(Project.id == project_id, Project.user_id == runtime.require_user()))).scalar_one_or_none()
            if not row:
                raise RuntimeError("Không tìm thấy truyện hoặc không có quyền truy cập")
            for field, value in update.model_dump(exclude_unset=True).items():
                setattr(row, field, value)
            await db.commit()
            await db.refresh(row)
            return _model_dict(row, PROJECT_FIELDS)

    @server.tool(name="list_categories", description="Liệt kê taxonomy truyện: prompt categories, genre đã dùng và nhóm nghề nghiệp.")
    async def list_categories(project_id: str | None = None) -> dict[str, Any]:
        async for db in runtime.session():
            genres = (await db.execute(select(Project.genre).where(Project.user_id == runtime.require_user(), Project.genre.is_not(None)).distinct())).scalars().all()
            careers_query = select(Career.category).join(Project, Project.id == Career.project_id).where(Project.user_id == runtime.require_user(), Career.category.is_not(None))
            if project_id:
                careers_query = careers_query.where(Career.project_id == project_id)
            career_categories = (await db.execute(careers_query.distinct())).scalars().all()
            prompt_categories = (await db.execute(select(PromptTemplate.category).where(PromptTemplate.user_id == runtime.require_user(), PromptTemplate.category.is_not(None), ~PromptTemplate.template_key.like("__mcp_%")).distinct())).scalars().all()
            markers = (await db.execute(select(PromptTemplate.template_key, PromptTemplate.template_name).where(PromptTemplate.user_id == runtime.require_user(), PromptTemplate.template_key.like("__mcp_%")))).all()
            for key, marker_name in markers:
                if key.startswith("__mcp_genre__:"):
                    genres.append(marker_name)
                elif key.startswith("__mcp_career__:"):
                    career_categories.append(marker_name)
            return {"prompt": CATEGORY_LIST + [{"id": str(x), "name": str(x), "custom": True} for x in prompt_categories if str(x) not in {c["id"] for c in CATEGORY_LIST}], "genre": sorted({str(x) for x in genres if x}), "career": sorted({str(x) for x in career_categories if x})}

    @server.tool(name="create_category", description="Tạo taxonomy: genre gắn vào project, career cập nhật nhóm nghề, hoặc prompt category marker.")
    async def create_category(kind: str, name: str, project_id: str | None = None, career_id: str | None = None, template_key: str | None = None, template_content: str = "") -> dict[str, Any]:
        kind = kind.strip().lower()
        if kind not in {"genre", "career", "prompt"}:
            raise ValueError("kind phải là genre, career hoặc prompt")
        async for db in runtime.session():
            user_id = runtime.require_user()
            if kind == "genre":
                if not project_id:
                    key = f"__mcp_genre__:{name.strip().lower().replace(' ', '-') }"
                    marker = (await db.execute(select(PromptTemplate).where(PromptTemplate.user_id == user_id, PromptTemplate.template_key == key))).scalar_one_or_none()
                    if marker is None:
                        db.add(PromptTemplate(user_id=user_id, template_key=key, template_name=name, template_content="", description="MCP genre taxonomy marker", category="__mcp_taxonomy__", is_active=True, is_system_default=False))
                    await db.commit()
                    return {"kind": kind, "name": name, "created": True, "taxonomy_marker": key}
                project = (await db.execute(select(Project).where(Project.id == project_id, Project.user_id == user_id))).scalar_one_or_none()
                if not project:
                    raise RuntimeError("Không tìm thấy project")
                project.genre = name
                await db.commit()
                return {"kind": kind, "name": name, "project_id": project_id, "created": True}
            if kind == "career":
                if not career_id:
                    key = f"__mcp_career__:{name.strip().lower().replace(' ', '-') }"
                    marker = (await db.execute(select(PromptTemplate).where(PromptTemplate.user_id == user_id, PromptTemplate.template_key == key))).scalar_one_or_none()
                    if marker is None:
                        db.add(PromptTemplate(user_id=user_id, template_key=key, template_name=name, template_content="", description="MCP career taxonomy marker", category="__mcp_taxonomy__", is_active=True, is_system_default=False))
                    await db.commit()
                    return {"kind": kind, "name": name, "created": True, "taxonomy_marker": key}
                career = (await db.execute(select(Career).join(Project, Project.id == Career.project_id).where(Career.id == career_id, Project.user_id == user_id))).scalar_one_or_none()
                if not career:
                    raise RuntimeError("Không tìm thấy nghề nghiệp")
                career.category = name
                await db.commit()
                return {"kind": kind, "name": name, "career_id": career_id, "created": True}
            key = template_key or f"__mcp_category__:{name.strip().lower().replace(' ', '-') }"
            existing = (await db.execute(select(PromptTemplate).where(PromptTemplate.user_id == user_id, PromptTemplate.template_key == key))).scalar_one_or_none()
            if existing:
                existing.category = name
                existing.template_name = existing.template_name or name
            else:
                existing = PromptTemplate(user_id=user_id, template_key=key, template_name=name, template_content=template_content, description="MCP taxonomy marker", category=name, is_active=True, is_system_default=False)
                db.add(existing)
            await db.commit()
            return {"kind": kind, "name": name, "template_key": key, "created": True}

    async def wizard_call(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("user_id", runtime.require_user())
        return await runtime.api().sse(path, payload)

    @server.tool(name="wizard_world_building", description="Chạy bước wizard xây dựng bối cảnh thế giới và trả về kết quả SSE đã gom.")
    async def wizard_world_building(title: str, description: str, theme: str, genre: str, chapter_count: int | None = None, narrative_perspective: str | None = None, target_words: int | None = None, project_id: str | None = None, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
        payload = {"title": title, "description": description, "theme": theme, "genre": genre, "chapter_count": chapter_count, "narrative_perspective": narrative_perspective, "target_words": target_words, "project_id": project_id, "provider": provider, "model": model}
        return await wizard_call("/api/wizard-stream/world-building", {k: v for k, v in payload.items() if v is not None})

    @server.tool(name="wizard_world_regenerate", description="Tạo lại bối cảnh thế giới của project qua wizard SSE.")
    async def wizard_world_regenerate(project_id: str, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
        payload = {k: v for k, v in {"project_id": project_id, "provider": provider, "model": model}.items() if v is not None}
        return await wizard_call(f"/api/wizard-stream/world-building/{project_id}/regenerate", payload)

    @server.tool(name="wizard_career_system", description="Chạy bước wizard sinh hệ nghề nghiệp cho project.")
    async def wizard_career_system(project_id: str, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
        return await wizard_call("/api/wizard-stream/career-system", {k: v for k, v in {"project_id": project_id, "provider": provider, "model": model}.items() if v is not None})

    @server.tool(name="wizard_characters", description="Chạy bước wizard sinh nhân vật cho project.")
    async def wizard_characters(project_id: str, count: int = 5, requirements: str = "", provider: str | None = None, model: str | None = None) -> dict[str, Any]:
        return await wizard_call("/api/wizard-stream/characters", {k: v for k, v in {"project_id": project_id, "count": count, "requirements": requirements, "provider": provider, "model": model}.items() if v is not None})

    @server.tool(name="wizard_outline", description="Chạy bước wizard sinh dàn ý cho project.")
    async def wizard_outline(project_id: str, chapter_count: int = 3, narrative_perspective: str | None = None, target_words: int | None = None, requirements: str = "", provider: str | None = None, model: str | None = None) -> dict[str, Any]:
        return await wizard_call("/api/wizard-stream/outline", {k: v for k, v in {"project_id": project_id, "chapter_count": chapter_count, "narrative_perspective": narrative_perspective, "target_words": target_words, "requirements": requirements, "provider": provider, "model": model}.items() if v is not None})

    @server.tool(name="wizard_status", description="Đọc trạng thái wizard hiện tại từ project (wizard_step/wizard_status).")
    async def wizard_status(project_id: str) -> dict[str, Any]:
        async for db in runtime.session():
            row = (await db.execute(select(Project).where(Project.id == project_id, Project.user_id == runtime.require_user()))).scalar_one_or_none()
            if not row:
                raise RuntimeError("Không tìm thấy project")
            return {"project_id": project_id, "wizard_status": row.wizard_status, "wizard_step": row.wizard_step, "world": {"time_period": row.world_time_period, "location": row.world_location, "atmosphere": row.world_atmosphere, "rules": row.world_rules}}

    @server.tool(name="list_chapters", description="Liệt kê các chương của một truyện.")
    async def list_chapters(project_id: str) -> dict[str, Any]:
        async for db in runtime.session():
            owned = (await db.execute(select(Project.id).where(Project.id == project_id, Project.user_id == runtime.require_user()))).scalar_one_or_none()
            if not owned:
                raise RuntimeError("Không tìm thấy project")
            rows = (await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.chapter_number))).scalars().all()
            return {"total": len(rows), "items": [_model_dict(row, CHAPTER_FIELDS) for row in rows]}

    @server.tool(name="create_chapter", description="Tạo thủ công một chương mới trong truyện.")
    async def create_chapter(project_id: str, title: str, chapter_number: int, content: str | None = None, summary: str | None = None, status: str = "draft", outline_id: str | None = None, sub_index: int = 1) -> dict[str, Any]:
        async for db in runtime.session():
            project = (await db.execute(select(Project).where(Project.id == project_id, Project.user_id == runtime.require_user()))).scalar_one_or_none()
            if not project:
                raise RuntimeError("Không tìm thấy project")
            chapter = Chapter(project_id=project_id, title=title, chapter_number=chapter_number, content=content, summary=summary, status=status, outline_id=outline_id, sub_index=sub_index, word_count=len(content or ""))
            db.add(chapter)
            project.current_words = (project.current_words or 0) + chapter.word_count
            await db.commit()
            await db.refresh(chapter)
            return _model_dict(chapter, CHAPTER_FIELDS)

    @server.tool(name="generate_chapter", description="Bắt đầu AI viết một chương qua background task hoặc SSE của app.")
    async def generate_chapter(chapter_id: str, target_word_count: int = 3000, style_id: int | None = None, model: str | None = None, enable_mcp: bool = True, wait_for_stream: bool = False) -> dict[str, Any]:
        payload = {"target_word_count": target_word_count, "style_id": style_id, "model": model, "enable_mcp": enable_mcp}
        path = f"/api/chapters/{chapter_id}/generate-stream" if wait_for_stream else f"/api/chapters/{chapter_id}/generate-background"
        if wait_for_stream:
            return await runtime.api().sse(path, {k: v for k, v in payload.items() if v is not None})
        return await runtime.api().json("POST", path, json={k: v for k, v in payload.items() if v is not None})

    @server.tool(name="continue_chapters", description="Bắt đầu tạo liên tiếp nhiều chương theo thứ tự và trả về batch task.")
    async def continue_chapters(project_id: str, start_chapter_number: int, count: int, target_word_count: int = 3000, style_id: int | None = None, model: str | None = None, enable_mcp: bool = True) -> dict[str, Any]:
        payload = {"start_chapter_number": start_chapter_number, "count": count, "target_word_count": target_word_count, "style_id": style_id, "model": model, "enable_mcp": enable_mcp}
        return await runtime.api().json("POST", f"/api/chapters/project/{project_id}/batch-generate", json={k: v for k, v in payload.items() if v is not None})

    @server.tool(name="task_status", description="Theo dõi trạng thái background task (wizard/chapter/batch).")
    async def task_status(task_id: str) -> dict[str, Any]:
        return await runtime.api().json("GET", f"/api/tasks/{task_id}")

    @server.tool(name="list_prompt_templates", description="Liệt kê prompt template của user, có thể lọc category.")
    async def list_prompt_templates(category: str | None = None, active_only: bool = True) -> dict[str, Any]:
        async for db in runtime.session():
            query = select(PromptTemplate).where(PromptTemplate.user_id == runtime.require_user(), ~PromptTemplate.template_key.like("__mcp_%"))
            if category:
                query = query.where(PromptTemplate.category == category)
            if active_only:
                query = query.where(PromptTemplate.is_active == True)
            rows = (await db.execute(query.order_by(PromptTemplate.category, PromptTemplate.template_key))).scalars().all()
            return {"total": len(rows), "items": [_model_dict(row, ("id", "template_key", "template_name", "description", "category", "parameters", "is_active", "is_system_default")) for row in rows]}

    @server.tool(name="list_writing_styles", description="Liệt kê writing styles preset và style tùy chỉnh của user.")
    async def list_writing_styles() -> dict[str, Any]:
        async for db in runtime.session():
            rows = (await db.execute(select(WritingStyle).where((WritingStyle.user_id.is_(None)) | (WritingStyle.user_id == runtime.require_user())).order_by(WritingStyle.order_index))).scalars().all()
            return {"total": len(rows), "items": [_model_dict(row, ("id", "user_id", "name", "style_type", "preset_id", "description", "prompt_content", "order_index")) for row in rows]}

    @server.tool(name="video_capabilities", description="Xem khả năng xuất video, FFmpeg, TTS và provider hiện có.")
    async def video_capabilities() -> dict[str, Any]:
        return _jsonable(video_export_service.capabilities())

    @server.tool(name="create_video_export", description="Tạo job xuất video từ các chương đã có nội dung.")
    async def create_video_export(project_id: str, chapter_ids: list[str], options: dict[str, Any] | None = None) -> dict[str, Any]:
        async for db in runtime.session():
            job = await video_export_service.create_job(db=db, user_id=runtime.require_user(), project_id=project_id, chapter_ids=chapter_ids, options=options)
            job, scenes = await video_export_service.get_job_detail(db=db, user_id=runtime.require_user(), job_id=job.id)
            return _jsonable(serialize_job(job, scenes))

    @server.tool(name="list_video_exports", description="Liệt kê job xuất video theo project.")
    async def list_video_exports(project_id: str, limit: int = 20) -> dict[str, Any]:
        async for db in runtime.session():
            jobs = await video_export_service.list_jobs(db=db, user_id=runtime.require_user(), project_id=project_id, limit=limit)
            return {"total": len(jobs), "items": [_jsonable(serialize_job(job)) for job in jobs]}

    @server.tool(name="get_video_export", description="Lấy chi tiết và storyboard của job video.")
    async def get_video_export(job_id: str) -> dict[str, Any]:
        async for db in runtime.session():
            job, scenes = await video_export_service.get_job_detail(db=db, user_id=runtime.require_user(), job_id=job_id)
            return _jsonable(serialize_job(job, scenes))

    @server.tool(name="video_export_action", description="Retry hoặc cancel một job xuất video.")
    async def video_export_action(job_id: str, action: str) -> dict[str, Any]:
        async for db in runtime.session():
            if action == "retry":
                job = await video_export_service.retry_job(db=db, user_id=runtime.require_user(), job_id=job_id)
                return {"message": "Đã đưa job vào hàng đợi chạy lại", "job": _jsonable(serialize_job(job))}
            if action == "cancel":
                job = await video_export_service.cancel_job(db=db, user_id=runtime.require_user(), job_id=job_id)
                return {"message": "Đã hủy job", "job": _jsonable(serialize_job(job))}
            raise ValueError("action phải là retry hoặc cancel")

    @server.tool(name="video_download_paths", description="Lấy đường dẫn tải video/phụ đề khi job đã hoàn tất (không trả file nhị phân qua MCP).")
    async def video_download_paths(job_id: str) -> dict[str, Any]:
        async for db in runtime.session():
            result: dict[str, Any] = {
                "job_id": job_id,
                "video_url": urljoin(runtime.cfg.api_base + "/", f"api/video-export/jobs/{job_id}/download/video"),
                "subtitles_url": urljoin(runtime.cfg.api_base + "/", f"api/video-export/jobs/{job_id}/download/subtitles"),
            }
            for key, kind in (("video", DOWNLOAD_KIND_VIDEO), ("subtitles", DOWNLOAD_KIND_SUBTITLES)):
                try:
                    _job, path = await video_export_service.get_output_path(db=db, user_id=runtime.require_user(), job_id=job_id, kind=kind)
                    result[key] = str(Path(path))
                except HTTPException as exc:
                    result[key] = None
                    result[f"{key}_error"] = str(exc.detail)
            return result


def create_server(runtime: MCPRuntime | None = None) -> FastMCP:
    """Create a fresh FastMCP instance (handy for tests and embedding)."""
    runtime = runtime or MCPRuntime()
    server = FastMCP(
        "MuMuAINovel",
        instructions="Công cụ first-party để tạo truyện, chạy wizard và xuất video MuMuAINovel.",
        token_verifier=_TokenVerifier(runtime.cfg),
        auth=AuthSettings(
            issuer_url=f"http://{runtime.cfg.http_host}:{runtime.cfg.http_port}",
            resource_server_url=None,
            required_scopes=["mumu"],
        ),
        stateless_http=True,
        streamable_http_path="/mcp",
        host=runtime.cfg.http_host,
        port=runtime.cfg.http_port,
    )
    _register_tools(server, runtime)
    return server


# Public module-level instance for embedders that prefer ``server.mcp``.
# ``create_server`` remains available for tests and isolated instances.
mcp = create_server()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MuMuAINovel first-party MCP server")
    parser.add_argument("--transport", choices=("stdio", "streamable-http", "sse"), default=os.getenv("MUMU_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=_settings().http_host)
    parser.add_argument("--port", type=int, default=_settings().http_port)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    cfg = _settings()
    if args.host != cfg.http_host or args.port != cfg.http_port:
        cfg = MCPSettings(
            api_base=cfg.api_base,
            token=cfg.token,
            user_id=cfg.user_id,
            http_host=args.host,
            http_port=args.port,
        )
    server = create_server(MCPRuntime(cfg))
    if args.transport == "stdio":
        server.run(transport="stdio")
    elif args.transport == "sse":
        server.run(transport="sse")
    else:
        server.run(transport="streamable-http")


if __name__ == "__main__":  # pragma: no cover
    main()
