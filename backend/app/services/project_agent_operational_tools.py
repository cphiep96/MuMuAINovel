"""项目智能体的运维、分析、导入导出和长任务工具。"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from types import SimpleNamespace
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask
from app.models.background_task import BackgroundTask
from app.models.batch_generation_task import BatchGenerationTask
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.project import Project
from app.models.project_default_style import ProjectDefaultStyle
from app.models.regeneration_task import RegenerationTask
from app.models.writing_style import WritingStyle
from app.services.outline_transfer_service import OutlineTransferService
from app.services.task_resources import affected_resources_for_agent_action
from app.services.project_agent_selectors import find_chapter


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def _chapter_schema(properties: dict[str, Any]) -> dict[str, Any]:
    """Schema for tools that address one specific chapter."""
    result = _schema(properties)
    result["anyOf"] = [{"required": ["chapter_id"]}, {"required": ["chapter_number"]}]
    return result


ID = {"type": "string", "minLength": 1, "pattern": r".*\S.*"}
DATA = {"type": "object", "additionalProperties": True}


OPERATIONAL_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_writing_styles",
        "description": "Truy vấn phong cách viết preset/tùy chỉnh khả dụng của người dùng hiện tại và phong cách mặc định của dự án.",
        "parameters": _schema({}),
    },
    {
        "name": "get_writing_style_detail",
        "description": "Lấy chi tiết phong cách viết khả dụng cho dự án hiện tại theo ID phong cách.",
        "parameters": _schema({"style_id": {"type": "integer", "minimum": 1}}, ["style_id"]),
    },
    {
        "name": "list_background_tasks",
        "description": "Truy vấn các tác vụ tạo, phân tích, tạo hàng loạt và tạo lại của dự án hiện tại.",
        "parameters": _schema({
            "status": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        }),
    },
    {
        "name": "get_background_task_detail",
        "description": "Truy vấn trạng thái đầy đủ và kết quả của một tác vụ nền trong dự án hiện tại.",
        "parameters": _schema({"task_id": ID}, ["task_id"]),
    },
    {
        "name": "get_chapter_analysis_status",
        "description": "Truy vấn trạng thái tác vụ phân tích mới nhất của chương chỉ định. Cần cung cấp ít nhất một trong chapter_id hoặc chapter_number; khi dùng số chương thì đừng truyền chapter_id rỗng.",
        "parameters": _chapter_schema({"chapter_id": ID, "chapter_number": {"type": "integer", "minimum": 1}}),
    },
    {
        "name": "get_chapter_analysis",
        "description": "Lấy phân tích cốt truyện và ký ức câu chuyện đã trích xuất của chương chỉ định. Cần cung cấp ít nhất một trong chapter_id hoặc chapter_number; khi dùng số chương thì đừng truyền chapter_id rỗng.",
        "parameters": _chapter_schema({"chapter_id": ID, "chapter_number": {"type": "integer", "minimum": 1}}),
    },
    {
        "name": "get_chapter_annotations",
        "description": "Lấy vị trí, loại và mức quan trọng của ký ức dùng để chú thích nội dung chính văn của chương chỉ định. Cần cung cấp ít nhất một trong chapter_id hoặc chapter_number; khi dùng số chương thì đừng truyền chapter_id rỗng.",
        "parameters": _chapter_schema({"chapter_id": ID, "chapter_number": {"type": "integer", "minimum": 1}}),
    },
    {
        "name": "get_chapter_navigation",
        "description": "Lấy chương trước, chương sau và vị trí chương trong dự án của chương chỉ định. Cần cung cấp ít nhất một trong chapter_id hoặc chapter_number; khi dùng số chương thì đừng truyền chapter_id rỗng.",
        "parameters": _chapter_schema({"chapter_id": ID, "chapter_number": {"type": "integer", "minimum": 1}}),
    },
    {
        "name": "check_chapter_generation_readiness",
        "description": "Kiểm tra chương chỉ định có đủ điều kiện tạo trước hay không và phân tích chương trước đã sẵn sàng chưa. Cần cung cấp ít nhất một trong chapter_id hoặc chapter_number; khi dùng số chương thì đừng truyền chapter_id rỗng.",
        "parameters": _chapter_schema({"chapter_id": ID, "chapter_number": {"type": "integer", "minimum": 1}}),
    },
    {
        "name": "list_story_memories",
        "description": "Truy vấn ký ức câu chuyện của dự án hiện tại; có thể lọc theo chương, loại và từ khóa.",
        "parameters": _schema({
            "chapter_id": ID,
            "chapter_number": {"type": "integer", "minimum": 1},
            "memory_type": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        }),
    },
    {
        "name": "get_project_export_links",
        "description": "Lấy địa chỉ tải an toàn cho JSON đầy đủ, JSON dàn ý và TXT chương của dự án hiện tại.",
        "parameters": _schema({}),
    },
    {
        "name": "get_story_memory_stats",
        "description": "Thống kê loại, phạm vi chương và mức quan trọng của ký ức câu chuyện trong dự án hiện tại.",
        "parameters": _schema({}),
    },
    {
        "name": "get_project_cover_status",
        "description": "Lấy trạng thái ảnh bìa, địa chỉ ảnh và lỗi gần nhất của dự án hiện tại.",
        "parameters": _schema({}),
    },
    {
        "name": "manage_writing_style",
        "description": "Tạo, cập nhật, xóa phong cách viết của người dùng, hoặc đặt/xóa phong cách mặc định của dự án hiện tại; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({
            "action": {"type": "string", "enum": ["create", "update", "delete", "set_default", "clear_default"]},
            "style_id": {"type": "integer", "minimum": 1},
            "data": DATA,
        }, ["action"]),
        "risk_level": 2,
        "resources": ("writing_styles", "projects"),
    },
    {
        "name": "manage_background_task",
        "description": "Hủy tác vụ nền chưa kết thúc của dự án hiện tại; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({
            "action": {"type": "string", "enum": ["cancel"]},
            "task_id": ID,
        }, ["action", "task_id"]),
        "risk_level": 2,
        "resources": ("tasks",),
    },
    {
        "name": "repair_project_consistency",
        "description": "Sửa bản ghi tổ chức, số thành viên, đồng bộ dàn ý-chương và số chữ dự án của dự án hiện tại; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({
            "action": {"type": "string", "enum": ["all", "organizations", "member_counts", "outline_chapters", "word_counts"]},
        }, ["action"]),
        "risk_level": 2,
        "resources": ("projects", "organizations", "outlines", "chapters"),
    },
    {
        "name": "import_outlines_json",
        "description": "Gộp hoặc thêm JSON xuất dàn ý đã dán vào dự án hiện tại; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({
            "json_content": {"type": "string", "minLength": 2},
            "mode": {"type": "string", "enum": ["append", "merge"]},
        }, ["json_content", "mode"]),
        "risk_level": 2,
        "resources": ("outlines", "chapters", "projects"),
    },
    {
        "name": "import_characters_json",
        "description": "Nhập JSON xuất nhân vật/tổ chức đã dán vào dự án hiện tại; tên trùng sẽ bị bỏ qua; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({"json_content": {"type": "string", "minLength": 2}}, ["json_content"]),
        "risk_level": 2,
        "resources": ("characters", "organizations", "careers"),
    },
    {
        "name": "manage_story_memories",
        "description": "Xóa kết quả phân tích và ký ức câu chuyện của chương chỉ định; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({
            "action": {"type": "string", "enum": ["delete_chapter_analysis"]},
            "chapter_id": ID,
            "chapter_number": {"type": "integer", "minimum": 1},
        }, ["action"]),
        "risk_level": 2,
        "resources": ("chapters", "foreshadows"),
    },
    {
        "name": "replace_chapter_text",
        "description": "Thay đoạn chính xác trong nội dung chính văn chương bằng văn bản mới; phải xác nhận trước và kiểm tra nguyên văn chưa đổi.",
        "parameters": _schema({
            "chapter_id": ID,
            "chapter_number": {"type": "integer", "minimum": 1},
            "start_position": {"type": "integer", "minimum": 0},
            "end_position": {"type": "integer", "minimum": 1},
            "expected_text": {"type": "string", "minLength": 1},
            "new_text": {"type": "string", "minLength": 1},
        }, ["start_position", "end_position", "expected_text", "new_text"]),
        "risk_level": 2,
        "resources": ("chapters", "projects"),
    },
    {
        "name": "manage_project_cover",
        "description": "Tạo hoặc xóa ảnh bìa dự án hiện tại; khi tạo sẽ dùng cấu hình ảnh bìa sẵn có của người dùng; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({
            "action": {"type": "string", "enum": ["generate", "clear"]},
            "overwrite": {"type": "boolean"},
        }, ["action"]),
        "risk_level": 2,
        "resources": ("projects",),
    },
    {
        "name": "start_project_task",
        "description": "Khởi động tác vụ nền tạo/mở rộng dàn ý, tạo/tạo hàng loạt chương hoặc phân tích chương; phải xác nhận trước khi thực hiện.",
        "parameters": _schema({
            "action": {"type": "string", "enum": [
                "generate_outlines", "expand_outline", "batch_expand_outlines",
                "generate_chapter", "batch_generate_chapters", "analyze_chapter",
                "regenerate_chapter", "partial_regenerate_chapter",
                "generate_character", "generate_organization", "generate_careers",
            ]},
            "outline_id": ID,
            "chapter_id": ID,
            "chapter_number": {"type": "integer", "minimum": 1},
            "data": DATA,
        }, ["action"]),
        "risk_level": 2,
        "resources": ("tasks", "outlines", "chapters", "projects"),
    },
]


OPERATIONAL_READ_TOOL_NAMES = {
    spec["name"] for spec in OPERATIONAL_TOOL_SPECS if not spec.get("risk_level")
}
OPERATIONAL_WRITE_TOOL_NAMES = {
    spec["name"] for spec in OPERATIONAL_TOOL_SPECS if spec.get("risk_level")
}


def _value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _preview_value(value: Any, limit: int = 800) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}… (tổng {len(value)} ký tự)"
    if isinstance(value, dict):
        return {key: _preview_value(item, limit) for key, item in list(value.items())[:50]}
    if isinstance(value, list):
        return [_preview_value(item, limit) for item in value[:50]]
    return value


class ProjectAgentOperationalTools:
    """执行非基础 CRUD 工具，并始终限制在当前用户和当前项目。"""

    STYLE_FIELDS = {"name", "description", "prompt_content"}

    def __init__(self, project: Project, db: AsyncSession):
        self.project = project
        self.db = db

    async def read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in OPERATIONAL_READ_TOOL_NAMES:
            raise ValueError(f"Công cụ đọc vận hành chưa đăng ký: {name}")
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            raise ValueError(f"Công cụ chưa được triển khai: {name}")
        return await handler(arguments)

    async def preview(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in OPERATIONAL_WRITE_TOOL_NAMES:
            raise ValueError(f"Công cụ ghi vận hành chưa đăng ký: {name}")
        action = str(arguments.get("action") or "")
        if name in {"import_outlines_json", "import_characters_json", "replace_chapter_text"}:
            action = "execute"
        if not action:
            raise ValueError("Thiếu action")
        handler = getattr(self, f"_{name}_preview_{action}", None)
        if handler is None:
            raise ValueError(f"Công cụ {name} không hỗ trợ hành động {action}")
        before, after, label, entity_id = await handler(arguments)
        if before == after:
            raise ValueError("Không phát hiện nội dung cần sửa")
        spec = next(item for item in OPERATIONAL_TOOL_SPECS if item["name"] == name)
        resources = (
            affected_resources_for_agent_action(action)
            if name == "start_project_task"
            else list(spec["resources"])
        )
        keys = list(dict.fromkeys([*before.keys(), *after.keys()]))
        return {
            "entity_type": name.removeprefix("manage_").removeprefix("start_"),
            "entity_id": entity_id,
            "label": label,
            "changes": {
                key: {
                    "before": _preview_value(before.get(key)),
                    "after": _preview_value(after.get(key)),
                }
                for key in keys
                if before.get(key) != after.get(key)
            },
            "resources": resources,
        }

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in OPERATIONAL_WRITE_TOOL_NAMES:
            raise ValueError(f"Công cụ ghi vận hành chưa đăng ký: {name}")
        action = str(arguments.get("action") or "")
        if name in {"import_outlines_json", "import_characters_json", "replace_chapter_text"}:
            action = "execute"
        preview_handler = getattr(self, f"_{name}_preview_{action}", None)
        handler = getattr(self, f"_{name}_{action}", None)
        if preview_handler is None or handler is None:
            raise ValueError(f"Công cụ {name} không hỗ trợ hành động {action}")
        before, _, _, _ = await preview_handler(arguments)
        entity_id, after, message = await handler(arguments)
        spec = next(item for item in OPERATIONAL_TOOL_SPECS if item["name"] == name)
        resources = (
            affected_resources_for_agent_action(action)
            if name == "start_project_task"
            else list(spec["resources"])
        )
        await self.db.flush()
        return {
            "message": message,
            "entity_id": entity_id,
            "before": before,
            "after": after,
            "resources": resources,
        }

    async def _find_chapter(self, arguments: dict[str, Any]) -> Chapter:
        return await find_chapter(self.db, self.project.id, arguments)

    async def _find_style(self, style_id: Any, *, writable: bool = False) -> WritingStyle:
        if isinstance(style_id, bool) or not isinstance(style_id, int):
            raise ValueError("Phải cung cấp style_id hợp lệ")
        query = select(WritingStyle).where(
            WritingStyle.id == style_id,
            or_(WritingStyle.user_id == self.project.user_id, WritingStyle.user_id.is_(None)),
        )
        style = (await self.db.execute(query)).scalar_one_or_none()
        if not style:
            raise ValueError("Người dùng hiện tại không có phong cách viết chỉ định khả dụng")
        if writable and style.user_id != self.project.user_id:
            raise ValueError("Không thể sửa hoặc xóa phong cách cấu hình sẵn của hệ thống")
        return style

    @staticmethod
    def _style_data(style: WritingStyle, default_style_id: int | None = None) -> dict[str, Any]:
        return {
            "id": style.id,
            "name": style.name,
            "style_type": style.style_type,
            "preset_id": style.preset_id,
            "description": style.description,
            "prompt_content": style.prompt_content,
            "order_index": style.order_index,
            "is_default": style.id == default_style_id,
        }

    async def _default_style_id(self) -> int | None:
        return (await self.db.execute(
            select(ProjectDefaultStyle.style_id).where(ProjectDefaultStyle.project_id == self.project.id)
        )).scalar_one_or_none()

    async def _list_writing_styles(self, _: dict[str, Any]) -> dict[str, Any]:
        rows = (await self.db.execute(
            select(WritingStyle)
            .where(or_(WritingStyle.user_id == self.project.user_id, WritingStyle.user_id.is_(None)))
            .order_by(WritingStyle.user_id.is_not(None), WritingStyle.order_index, WritingStyle.id)
        )).scalars().all()
        default_id = await self._default_style_id()
        return {"total": len(rows), "default_style_id": default_id,
                "items": [self._style_data(row, default_id) for row in rows]}

    async def _get_writing_style_detail(self, arguments: dict[str, Any]) -> dict[str, Any]:
        style = await self._find_style(arguments.get("style_id"))
        return self._style_data(style, await self._default_style_id())

    @staticmethod
    def _task_data(task: Any, task_kind: str, include_result: bool = False) -> dict[str, Any]:
        fields = {
            "id", "project_id", "task_type", "status", "progress", "status_message",
            "task_input", "progress_details", "error_message",
            "cancel_requested", "created_at", "started_at", "completed_at",
            "total_chapters", "completed_chapters", "current_chapter_id",
            "current_chapter_number", "failed_chapters", "chapter_id",
            "regenerated_word_count", "original_word_count", "version_number",
            "modification_instructions", "custom_instructions", "regenerated_content",
        }
        data = {
            field: _preview_value(_value(getattr(task, field)))
            for field in fields if hasattr(task, field)
        }
        if include_result and hasattr(task, "task_result"):
            data["task_result"] = _preview_value(_value(task.task_result))
        data["task_kind"] = task_kind
        return data

    async def _all_tasks(self) -> list[tuple[Any, str]]:
        filters = ("project_id", self.project.id)
        groups: list[tuple[list[Any], str]] = []
        for model, kind in (
            (BackgroundTask, "background"),
            (BatchGenerationTask, "batch_generation"),
            (AnalysisTask, "analysis"),
            (RegenerationTask, "regeneration"),
        ):
            query = select(model).where(getattr(model, filters[0]) == filters[1])
            if hasattr(model, "user_id"):
                query = query.where(model.user_id == self.project.user_id)
            rows = (await self.db.execute(query)).scalars().all()
            groups.append((rows, kind))
        return [(row, kind) for rows, kind in groups for row in rows]

    async def _list_background_tasks(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(arguments.get("limit", 20)), 1), 100)
        status = str(arguments.get("status") or "").strip()
        rows = await self._all_tasks()
        if status:
            rows = [(row, kind) for row, kind in rows if row.status == status]
        rows.sort(key=lambda item: item[0].created_at or datetime.min, reverse=True)
        return {"total": len(rows), "items": [self._task_data(row, kind) for row, kind in rows[:limit]]}

    async def _find_task(self, task_id: str) -> tuple[Any, str]:
        if not task_id:
            raise ValueError("Phải cung cấp task_id")
        for task, kind in await self._all_tasks():
            if task.id == task_id:
                return task, kind
        raise ValueError("Không tìm thấy tác vụ nền trong dự án hiện tại")

    async def _get_background_task_detail(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task, kind = await self._find_task(str(arguments.get("task_id") or ""))
        return self._task_data(task, kind, include_result=True)

    async def _get_chapter_analysis_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        chapter = await self._find_chapter(arguments)
        task = (await self.db.execute(
            select(AnalysisTask).where(
                AnalysisTask.chapter_id == chapter.id,
                AnalysisTask.project_id == self.project.id,
                AnalysisTask.user_id == self.project.user_id,
            ).order_by(AnalysisTask.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        return {
            "chapter_id": chapter.id,
            "chapter_number": chapter.chapter_number,
            "has_task": task is not None,
            "task": self._task_data(task, "analysis") if task else None,
        }

    async def _get_chapter_analysis(self, arguments: dict[str, Any]) -> dict[str, Any]:
        chapter = await self._find_chapter(arguments)
        analysis = (await self.db.execute(
            select(PlotAnalysis).where(
                PlotAnalysis.project_id == self.project.id,
                PlotAnalysis.chapter_id == chapter.id,
            ).order_by(PlotAnalysis.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if not analysis:
            raise ValueError("Chương này tạm chưa có kết quả phân tích")
        memories = (await self.db.execute(
            select(StoryMemory).where(
                StoryMemory.project_id == self.project.id,
                StoryMemory.chapter_id == chapter.id,
            ).order_by(StoryMemory.importance_score.desc())
        )).scalars().all()
        return {
            "chapter_id": chapter.id,
            "chapter_number": chapter.chapter_number,
            "analysis": analysis.to_dict(),
            "memories": [memory.to_dict() for memory in memories],
        }

    async def _get_chapter_annotations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        chapter = await self._find_chapter(arguments)
        memories = (await self.db.execute(
            select(StoryMemory).where(
                StoryMemory.project_id == self.project.id,
                StoryMemory.chapter_id == chapter.id,
            ).order_by(StoryMemory.importance_score.desc())
        )).scalars().all()
        items = [{
            "id": row.id,
            "type": row.memory_type,
            "title": row.title,
            "content": row.content,
            "importance": row.importance_score,
            "position": row.chapter_position,
            "length": row.text_length,
            "tags": row.tags or [],
            "related_characters": row.related_characters or [],
            "related_locations": row.related_locations or [],
        } for row in memories]
        return {"chapter_id": chapter.id, "chapter_number": chapter.chapter_number,
                "title": chapter.title, "total": len(items), "items": items}

    async def _get_chapter_navigation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        chapter = await self._find_chapter(arguments)
        previous = (await self.db.execute(select(Chapter).where(
            Chapter.project_id == self.project.id,
            Chapter.chapter_number < chapter.chapter_number,
        ).order_by(Chapter.chapter_number.desc()).limit(1))).scalar_one_or_none()
        following = (await self.db.execute(select(Chapter).where(
            Chapter.project_id == self.project.id,
            Chapter.chapter_number > chapter.chapter_number,
        ).order_by(Chapter.chapter_number).limit(1))).scalar_one_or_none()
        total = (await self.db.execute(select(func.count(Chapter.id)).where(
            Chapter.project_id == self.project.id
        ))).scalar_one()

        def brief(row: Chapter | None) -> dict[str, Any] | None:
            return None if row is None else {
                "id": row.id, "chapter_number": row.chapter_number, "title": row.title,
                "status": row.status, "word_count": row.word_count or 0,
            }

        return {"current": brief(chapter), "previous": brief(previous), "next": brief(following), "total": total}

    async def _check_chapter_generation_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from app.api.chapters import check_prerequisites, check_previous_analysis_ready

        chapter = await self._find_chapter(arguments)
        can_generate, reason, previous = await check_prerequisites(self.db, chapter)
        analysis_ready, analysis_reason = await check_previous_analysis_ready(self.db, chapter)
        return {
            "chapter_id": chapter.id,
            "chapter_number": chapter.chapter_number,
            "can_generate": bool(can_generate and analysis_ready),
            "content_prerequisites_ready": can_generate,
            "content_prerequisites_message": reason or None,
            "previous_analysis_ready": analysis_ready,
            "previous_analysis_message": analysis_reason or None,
            "previous_chapters": [row.chapter_number for row in previous],
        }

    async def _list_story_memories(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(arguments.get("limit", 30)), 1), 100)
        query = select(StoryMemory).where(StoryMemory.project_id == self.project.id)
        if arguments.get("chapter_id") or arguments.get("chapter_number") is not None:
            chapter = await self._find_chapter(arguments)
            query = query.where(StoryMemory.chapter_id == chapter.id)
        if arguments.get("memory_type"):
            query = query.where(StoryMemory.memory_type == arguments["memory_type"])
        keyword = str(arguments.get("query") or "").strip()
        if keyword:
            pattern = f"%{keyword}%"
            query = query.where(or_(StoryMemory.title.ilike(pattern), StoryMemory.content.ilike(pattern)))
        rows = (await self.db.execute(
            query.order_by(StoryMemory.story_timeline.desc(), StoryMemory.importance_score.desc()).limit(limit)
        )).scalars().all()
        return {"total": len(rows), "items": [row.to_dict() for row in rows]}

    async def _get_story_memory_stats(self, _: dict[str, Any]) -> dict[str, Any]:
        rows = (await self.db.execute(select(StoryMemory).where(
            StoryMemory.project_id == self.project.id
        ))).scalars().all()
        type_counts: dict[str, int] = {}
        for row in rows:
            type_counts[row.memory_type] = type_counts.get(row.memory_type, 0) + 1
        analysis_count = (await self.db.execute(select(func.count(PlotAnalysis.id)).where(
            PlotAnalysis.project_id == self.project.id
        ))).scalar_one()
        return {
            "total_memories": len(rows),
            "memory_types": type_counts,
            "analyzed_chapters": analysis_count,
            "chapter_coverage": len({row.chapter_id for row in rows if row.chapter_id}),
            "average_importance": (
                sum(row.importance_score or 0 for row in rows) / len(rows) if rows else 0
            ),
            "foreshadow_memories": sum(bool(row.is_foreshadow) for row in rows),
        }

    async def _get_project_export_links(self, _: dict[str, Any]) -> dict[str, Any]:
        base = f"/api/projects/{self.project.id}/agent/exports"
        return {
            "project_json": f"{base}/project",
            "outlines_json": f"{base}/outlines",
            "chapters_txt": f"{base}/chapters",
            "characters_json": f"{base}/characters",
        }

    async def _get_project_cover_status(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "project_id": self.project.id,
            "cover_status": self.project.cover_status,
            "cover_image_url": self.project.cover_image_url,
            "cover_prompt": self.project.cover_prompt,
            "cover_error": self.project.cover_error,
            "cover_updated_at": _value(self.project.cover_updated_at),
        }

    @staticmethod
    def _data(arguments: dict[str, Any]) -> dict[str, Any]:
        data = arguments.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("data phải là object")
        return data

    async def _manage_writing_style_preview_create(self, arguments: dict[str, Any]):
        data = self._data(arguments)
        unknown = set(data) - (self.STYLE_FIELDS | {"preset_id"})
        if unknown:
            raise ValueError(f"Chứa trường không hỗ trợ: {', '.join(sorted(unknown))}")
        preset = None
        if data.get("preset_id"):
            preset = (await self.db.execute(select(WritingStyle).where(
                WritingStyle.user_id.is_(None), WritingStyle.preset_id == data["preset_id"]
            ))).scalar_one_or_none()
            if not preset:
                raise ValueError("Phong cách cấu hình sẵn chỉ định không tồn tại")
        name = str(data.get("name") or (preset.name if preset else "")).strip()
        prompt = str(data.get("prompt_content") or (preset.prompt_content if preset else "")).strip()
        if not name or not prompt:
            raise ValueError("Tạo phong cách viết cần name và prompt_content")
        after = {"name": name, "description": data.get("description", preset.description if preset else None),
                 "prompt_content": prompt, "preset_id": data.get("preset_id")}
        return {}, after, f"Tạo phong cách viết«{name}»", None

    async def _manage_writing_style_create(self, arguments: dict[str, Any]):
        _, after, _, _ = await self._manage_writing_style_preview_create(arguments)
        order = (await self.db.execute(select(func.max(WritingStyle.order_index)).where(
            WritingStyle.user_id == self.project.user_id
        ))).scalar_one_or_none() or 0
        row = WritingStyle(user_id=self.project.user_id, name=after["name"],
                           style_type="preset" if after["preset_id"] else "custom",
                           preset_id=after["preset_id"], description=after["description"],
                           prompt_content=after["prompt_content"], order_index=order + 1)
        self.db.add(row)
        await self.db.flush()
        return str(row.id), self._style_data(row), f"Đã tạo phong cách viết«{row.name}»"

    async def _manage_writing_style_preview_update(self, arguments: dict[str, Any]):
        row = await self._find_style(arguments.get("style_id"), writable=True)
        data = self._data(arguments)
        unknown = set(data) - self.STYLE_FIELDS
        if unknown:
            raise ValueError(f"Chứa trường không hỗ trợ: {', '.join(sorted(unknown))}")
        if not data:
            raise ValueError("Chưa cung cấp trường cần cập nhật")
        if "name" in data and not str(data["name"]).strip():
            raise ValueError("name không được để trống")
        if "prompt_content" in data and not str(data["prompt_content"]).strip():
            raise ValueError("prompt_content không được để trống")
        before = {key: getattr(row, key) for key in data}
        return before, data, f"Cập nhật phong cách viết«{row.name}»", str(row.id)

    async def _manage_writing_style_update(self, arguments: dict[str, Any]):
        row = await self._find_style(arguments.get("style_id"), writable=True)
        data = self._data(arguments)
        for key, value in data.items():
            setattr(row, key, value.strip() if key in {"name", "prompt_content"} else value)
        return str(row.id), self._style_data(row), f"Đã cập nhật phong cách viết«{row.name}»"

    async def _manage_writing_style_preview_delete(self, arguments: dict[str, Any]):
        row = await self._find_style(arguments.get("style_id"), writable=True)
        return self._style_data(row), {}, f"Xóa phong cách viết«{row.name}»", str(row.id)

    async def _manage_writing_style_delete(self, arguments: dict[str, Any]):
        row = await self._find_style(arguments.get("style_id"), writable=True)
        row_id, name = row.id, row.name
        default = (await self.db.execute(select(ProjectDefaultStyle).where(
            ProjectDefaultStyle.project_id == self.project.id,
            ProjectDefaultStyle.style_id == row.id,
        ))).scalar_one_or_none()
        if default:
            await self.db.delete(default)
        await self.db.delete(row)
        return str(row_id), {}, f"Đã xóa phong cách viết«{name}»"

    async def _manage_writing_style_preview_set_default(self, arguments: dict[str, Any]):
        row = await self._find_style(arguments.get("style_id"))
        before_id = await self._default_style_id()
        return {"default_style_id": before_id}, {"default_style_id": row.id, "name": row.name}, \
            f"Đặt phong cách viết mặc định của dự án thành«{row.name}»", str(row.id)

    async def _manage_writing_style_set_default(self, arguments: dict[str, Any]):
        row = await self._find_style(arguments.get("style_id"))
        default = (await self.db.execute(select(ProjectDefaultStyle).where(
            ProjectDefaultStyle.project_id == self.project.id
        ))).scalar_one_or_none()
        if default:
            default.style_id = row.id
        else:
            self.db.add(ProjectDefaultStyle(project_id=self.project.id, style_id=row.id))
        return str(row.id), {"default_style_id": row.id, "name": row.name}, f"Đã đặt«{row.name}» làm phong cách viết mặc định của dự án"

    async def _manage_writing_style_preview_clear_default(self, _: dict[str, Any]):
        default_id = await self._default_style_id()
        if default_id is None:
            raise ValueError("Dự án hiện tại chưa có phong cách viết mặc định")
        return {"default_style_id": default_id}, {"default_style_id": None}, "Xóa phong cách viết mặc định của dự án", str(default_id)

    async def _manage_writing_style_clear_default(self, _: dict[str, Any]):
        default = (await self.db.execute(select(ProjectDefaultStyle).where(
            ProjectDefaultStyle.project_id == self.project.id
        ))).scalar_one()
        old_id = default.style_id
        await self.db.delete(default)
        return str(old_id), {"default_style_id": None}, "Đã xóa phong cách viết mặc định của dự án"

    async def _manage_background_task_preview_cancel(self, arguments: dict[str, Any]):
        task, kind = await self._find_task(str(arguments.get("task_id") or ""))
        if task.status not in {"pending", "running"}:
            raise ValueError("Chỉ tác vụ đang chờ hoặc đang chạy mới có thể hủy")
        return {"status": task.status}, {"status": "cancelled", "task_kind": kind}, \
            f"Hủy tác vụ nền {task.id[:8]}", task.id

    async def _manage_background_task_cancel(self, arguments: dict[str, Any]):
        task, _ = await self._find_task(str(arguments.get("task_id") or ""))
        task.status = "cancelled"
        if hasattr(task, "cancel_requested"):
            task.cancel_requested = True
        if hasattr(task, "status_message"):
            task.status_message = "Tác vụ đã bị hủy"
        if hasattr(task, "completed_at"):
            task.completed_at = datetime.now()
        return task.id, {"status": "cancelled"}, f"Đã hủy tác vụ nền {task.id[:8]}"

    async def _consistency_plan(self, action: str) -> dict[str, Any]:
        from app.models.outline import Outline
        from app.models.relationship import Organization, OrganizationMember

        plan: dict[str, Any] = {}
        if action in {"all", "organizations"}:
            org_chars = (await self.db.execute(select(func.count(Character.id)).where(
                Character.project_id == self.project.id,
                Character.is_organization.is_(True),
            ))).scalar_one()
            org_rows = (await self.db.execute(select(func.count(Organization.id)).where(
                Organization.project_id == self.project.id
            ))).scalar_one()
            plan["missing_organization_records"] = max(0, org_chars - org_rows)
        if action in {"all", "member_counts"}:
            organizations = (await self.db.execute(select(Organization).where(
                Organization.project_id == self.project.id
            ))).scalars().all()
            mismatches = 0
            for org in organizations:
                actual = (await self.db.execute(select(func.count(OrganizationMember.id)).where(
                    OrganizationMember.organization_id == org.id
                ))).scalar_one()
                mismatches += int(actual != (org.member_count or 0))
            plan["member_count_mismatches"] = mismatches
        if action in {"all", "outline_chapters"} and self.project.outline_mode == "one-to-one":
            chapters = (await self.db.execute(select(Chapter).where(Chapter.project_id == self.project.id))).scalars().all()
            outlines = (await self.db.execute(select(Outline).where(Outline.project_id == self.project.id))).scalars().all()
            by_order = {row.order_index: row for row in outlines}
            plan["outline_chapter_mismatches"] = sum(
                1 for chapter in chapters
                if chapter.chapter_number not in by_order
                or by_order[chapter.chapter_number].title != chapter.title
                or (by_order[chapter.chapter_number].content or "") != (chapter.summary or "")
            )
        if action in {"all", "word_counts"}:
            chapters = (await self.db.execute(select(Chapter).where(Chapter.project_id == self.project.id))).scalars().all()
            plan["chapter_word_count_mismatches"] = sum(
                1 for row in chapters if (row.word_count or 0) != len(row.content or "")
            )
            plan["project_current_words_before"] = self.project.current_words or 0
            plan["project_current_words_after"] = sum(len(row.content or "") for row in chapters)
        return plan

    async def _repair_project_consistency_preview_all(self, arguments):
        return await self._repair_preview(arguments)
    async def _repair_project_consistency_preview_organizations(self, arguments):
        return await self._repair_preview(arguments)
    async def _repair_project_consistency_preview_member_counts(self, arguments):
        return await self._repair_preview(arguments)
    async def _repair_project_consistency_preview_outline_chapters(self, arguments):
        return await self._repair_preview(arguments)
    async def _repair_project_consistency_preview_word_counts(self, arguments):
        return await self._repair_preview(arguments)

    async def _repair_preview(self, arguments: dict[str, Any]):
        action = str(arguments["action"])
        plan = await self._consistency_plan(action)
        count_keys = {
            "missing_organization_records", "member_count_mismatches",
            "outline_chapter_mismatches", "chapter_word_count_mismatches",
        }
        has_count_issue = any((plan.get(key) or 0) > 0 for key in count_keys)
        has_total_issue = (
            "project_current_words_before" in plan
            and plan["project_current_words_before"] != plan["project_current_words_after"]
        )
        if not has_count_issue and not has_total_issue:
            raise ValueError("Không phát hiện vấn đề nhất quán cần sửa")
        return {}, plan, f"Sửa tính nhất quán dự án ({action})", self.project.id

    async def _repair(self, action: str) -> dict[str, Any]:
        from app.models.outline import Outline
        from app.models.relationship import Organization, OrganizationMember

        result: dict[str, Any] = {}
        if action in {"all", "organizations"}:
            organization_characters = (await self.db.execute(select(Character).where(
                Character.project_id == self.project.id,
                Character.is_organization.is_(True),
            ))).scalars().all()
            existing_character_ids = set((await self.db.execute(select(Organization.character_id).where(
                Organization.project_id == self.project.id
            ))).scalars().all())
            missing = [row for row in organization_characters if row.id not in existing_character_ids]
            for character in missing:
                self.db.add(Organization(
                    project_id=self.project.id,
                    character_id=character.id,
                    member_count=0,
                    power_level=50,
                ))
            result["organizations"] = {"fixed": len(missing), "total": len(organization_characters)}
        if action in {"all", "member_counts"}:
            organizations = (await self.db.execute(select(Organization).where(
                Organization.project_id == self.project.id
            ))).scalars().all()
            fixed = 0
            for organization in organizations:
                actual = (await self.db.execute(select(func.count(OrganizationMember.id)).where(
                    OrganizationMember.organization_id == organization.id
                ))).scalar_one()
                if (organization.member_count or 0) != actual:
                    organization.member_count = actual
                    fixed += 1
            result["member_counts"] = {"fixed": fixed, "total": len(organizations)}
        if action in {"all", "outline_chapters"} and self.project.outline_mode == "one-to-one":
            chapters = (await self.db.execute(select(Chapter).where(Chapter.project_id == self.project.id))).scalars().all()
            outlines = (await self.db.execute(select(Outline).where(Outline.project_id == self.project.id))).scalars().all()
            by_order = {row.order_index: row for row in outlines}
            fixed = 0
            for chapter in chapters:
                outline = by_order.get(chapter.chapter_number)
                if not outline:
                    outline = Outline(project_id=self.project.id, order_index=chapter.chapter_number,
                                      title=chapter.title, content=chapter.summary or "")
                    self.db.add(outline)
                    by_order[chapter.chapter_number] = outline
                    fixed += 1
                elif outline.title != chapter.title or (outline.content or "") != (chapter.summary or ""):
                    outline.title, outline.content = chapter.title, chapter.summary or ""
                    fixed += 1
                structure = {}
                try:
                    structure = json.loads(outline.structure) if outline.structure else {}
                except (json.JSONDecodeError, TypeError):
                    structure = {}
                if isinstance(structure, dict):
                    structure.update({"title": outline.title, "summary": outline.content, "content": outline.content})
                    outline.structure = json.dumps(structure, ensure_ascii=False)
            result["outline_chapters"] = {"fixed": fixed}
        if action in {"all", "word_counts"}:
            chapters = (await self.db.execute(select(Chapter).where(Chapter.project_id == self.project.id))).scalars().all()
            fixed = 0
            total = 0
            for row in chapters:
                actual = len(row.content or "")
                fixed += int((row.word_count or 0) != actual)
                row.word_count = actual
                total += actual
            self.project.current_words = total
            result["word_counts"] = {"fixed_chapters": fixed, "current_words": total}
        return result

    async def _repair_project_consistency_all(self, _): return await self._repair_result("all")
    async def _repair_project_consistency_organizations(self, _): return await self._repair_result("organizations")
    async def _repair_project_consistency_member_counts(self, _): return await self._repair_result("member_counts")
    async def _repair_project_consistency_outline_chapters(self, _): return await self._repair_result("outline_chapters")
    async def _repair_project_consistency_word_counts(self, _): return await self._repair_result("word_counts")

    async def _repair_result(self, action: str):
        result = await self._repair(action)
        return self.project.id, result, f"Đã hoàn tất sửa tính nhất quán dự án ({action})"

    def _parse_outline_import(self, arguments: dict[str, Any]):
        content = str(arguments.get("json_content") or "")
        if len(content.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("Nội dung nhập vượt giới hạn 10MB")
        return OutlineTransferService.parse_file(content.encode("utf-8"))

    async def _import_outlines_json_preview_execute(self, arguments: dict[str, Any]):
        parsed = self._parse_outline_import(arguments)
        mode = arguments.get("mode")
        preview = await OutlineTransferService.preview_import(parsed, self.project, mode, self.db)
        data = preview.model_dump(mode="json")
        if not preview.valid:
            raise ValueError("; ".join(preview.errors))
        after = {key: data[key] for key in (
            "mode", "statistics", "warnings", "target_outline_mode"
        ) if key in data}
        return {}, after, f"{mode} nhập {len(parsed.items)} mục dàn ý", self.project.id

    async def _import_outlines_json_execute(self, arguments: dict[str, Any]):
        parsed = self._parse_outline_import(arguments)
        result = await OutlineTransferService.import_outlines(
            parsed=parsed, project=self.project, mode=arguments["mode"], db=self.db
        )
        data = result.model_dump(mode="json")
        return self.project.id, data, f"Nhập dàn ý xong: thêm {result.imported} mục, cập nhật {result.updated} mục"

    def _parse_character_import(self, arguments: dict[str, Any]) -> dict[str, Any]:
        content = str(arguments.get("json_content") or "")
        if len(content.encode("utf-8")) > 10 * 1024 * 1024:
            raise ValueError("Nội dung nhập vượt giới hạn 10MB")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Lỗi định dạng JSON: dòng {exc.lineno} cột {exc.colno}") from exc
        if not isinstance(data, dict):
            raise ValueError("Nút gốc JSON nhập phải là object")
        return data

    async def _import_characters_json_preview_execute(self, arguments: dict[str, Any]):
        from app.services.import_export_service import ImportExportService

        data = self._parse_character_import(arguments)
        validation = ImportExportService.validate_characters_import(data)
        if not validation.get("valid"):
            raise ValueError("; ".join(validation.get("errors") or ["Dữ liệu nhập nhân vật không hợp lệ"]))
        names = [str(item.get("name") or "") for item in data.get("data", []) if isinstance(item, dict)]
        existing = set((await self.db.execute(select(Character.name).where(
            Character.project_id == self.project.id,
            Character.name.in_(names),
        ))).scalars().all()) if names else set()
        statistics = dict(validation.get("statistics") or {})
        statistics.update({"will_skip_duplicates": len(existing), "will_import": len(names) - len(existing)})
        return {}, {"statistics": statistics, "warnings": validation.get("warnings") or []}, \
            f"Nhập {len(names) - len(existing)} nhân vật/tổ chức", self.project.id

    async def _import_characters_json_execute(self, arguments: dict[str, Any]):
        from app.services.import_export_service import ImportExportService

        result = await ImportExportService.import_characters(
            data=self._parse_character_import(arguments),
            project_id=self.project.id,
            user_id=self.project.user_id,
            db=self.db,
        )
        if not result.get("success"):
            raise ValueError(result.get("message") or "Nhập nhân vật thất bại")
        return self.project.id, result, result.get("message") or "Nhập nhân vật/tổ chức hoàn tất"

    async def _manage_story_memories_preview_delete_chapter_analysis(self, arguments: dict[str, Any]):
        chapter = await self._find_chapter(arguments)
        memory_count = (await self.db.execute(select(func.count(StoryMemory.id)).where(
            StoryMemory.project_id == self.project.id,
            StoryMemory.chapter_id == chapter.id,
        ))).scalar_one()
        analysis_count = (await self.db.execute(select(func.count(PlotAnalysis.id)).where(
            PlotAnalysis.project_id == self.project.id,
            PlotAnalysis.chapter_id == chapter.id,
        ))).scalar_one()
        task_count = (await self.db.execute(select(func.count(AnalysisTask.id)).where(
            AnalysisTask.project_id == self.project.id,
            AnalysisTask.chapter_id == chapter.id,
        ))).scalar_one()
        running_task = (await self.db.execute(select(AnalysisTask.id).where(
            AnalysisTask.project_id == self.project.id,
            AnalysisTask.chapter_id == chapter.id,
            AnalysisTask.status.in_(["pending", "running"]),
        ).limit(1))).scalar_one_or_none()
        if running_task:
            raise ValueError("Chương này vẫn còn tác vụ phân tích đang chạy, vui lòng hủy tác vụ trước")
        if not memory_count and not analysis_count and not task_count:
            raise ValueError("Chương này không có dữ liệu phân tích để xóa")
        before = {"memories": memory_count, "analyses": analysis_count, "analysis_tasks": task_count}
        return before, {"memories": 0, "analyses": 0, "analysis_tasks": 0}, \
            f"Xóa dữ liệu phân tích chương {chapter.chapter_number}«{chapter.title}»", chapter.id

    async def _manage_story_memories_delete_chapter_analysis(self, arguments: dict[str, Any]):
        chapter = await self._find_chapter(arguments)
        memories = (await self.db.execute(select(StoryMemory).where(
            StoryMemory.project_id == self.project.id,
            StoryMemory.chapter_id == chapter.id,
        ))).scalars().all()
        analyses = (await self.db.execute(select(PlotAnalysis).where(
            PlotAnalysis.project_id == self.project.id,
            PlotAnalysis.chapter_id == chapter.id,
        ))).scalars().all()
        tasks = (await self.db.execute(select(AnalysisTask).where(
            AnalysisTask.project_id == self.project.id,
            AnalysisTask.chapter_id == chapter.id,
        ))).scalars().all()
        for row in [*memories, *analyses, *tasks]:
            await self.db.delete(row)
        try:
            from app.services.memory_service import memory_service
            await memory_service.delete_chapter_memories(
                user_id=self.project.user_id,
                project_id=self.project.id,
                chapter_id=chapter.id,
            )
        except Exception:
            pass
        after = {"memories": 0, "analyses": 0, "analysis_tasks": 0}
        return chapter.id, after, f"Đã xóa dữ liệu phân tích chương {chapter.chapter_number}«{chapter.title}»"

    async def _replace_chapter_text_preview_execute(self, arguments: dict[str, Any]):
        chapter = await self._find_chapter(arguments)
        content = chapter.content or ""
        start, end = arguments["start_position"], arguments["end_position"]
        if start < 0 or end > len(content) or start >= end:
            raise ValueError("Vị trí thay thế vượt phạm vi nội dung chương")
        expected = arguments["expected_text"]
        if content[start:end] != expected:
            raise ValueError("Nguyên văn tại vị trí chỉ định không khớp expected_text, vui lòng đọc lại chương")
        new_text = arguments["new_text"]
        after_content = content[:start] + new_text + content[end:]
        before = {"selected_text": expected, "word_count": chapter.word_count or 0}
        after = {"selected_text": new_text, "word_count": len(after_content)}
        return before, after, f"Thay đoạn nội dung chính văn chương {chapter.chapter_number}«{chapter.title}»", chapter.id

    async def _replace_chapter_text_execute(self, arguments: dict[str, Any]):
        chapter = await self._find_chapter(arguments)
        content = chapter.content or ""
        start, end = arguments["start_position"], arguments["end_position"]
        old_count = chapter.word_count or 0
        chapter.content = content[:start] + arguments["new_text"] + content[end:]
        chapter.word_count = len(chapter.content)
        self.project.current_words = max(0, (self.project.current_words or 0) - old_count + chapter.word_count)
        return chapter.id, {"word_count": chapter.word_count}, f"Đã thay đoạn nội dung chính văn chương {chapter.chapter_number}«{chapter.title}»"

    async def _manage_project_cover_preview_generate(self, arguments: dict[str, Any]):
        if self.project.cover_status == "generating":
            raise ValueError("Bìa đang được tạo")
        return {"cover_status": self.project.cover_status, "cover_image_url": self.project.cover_image_url}, \
            {"action": "generate", "overwrite": arguments.get("overwrite", True)}, "Tạo ảnh bìa dự án", self.project.id

    async def _manage_project_cover_generate(self, arguments: dict[str, Any]):
        from app.services.cover_generation_service import cover_generation_service
        try:
            result = await cover_generation_service.generate_cover(
                db=self.db, user_id=self.project.user_id, project_id=self.project.id,
                overwrite=arguments.get("overwrite", True),
            )
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc
        return self.project.id, result, result.get("message", "Tạo bìa thành công")

    async def _manage_project_cover_preview_clear(self, _: dict[str, Any]):
        if not self.project.cover_image_url and self.project.cover_status == "none":
            raise ValueError("Dự án hiện tại không có bìa để xóa")
        return {"cover_status": self.project.cover_status, "cover_image_url": self.project.cover_image_url}, \
            {"cover_status": "none", "cover_image_url": None}, "Xóa ảnh bìa dự án", self.project.id

    async def _manage_project_cover_clear(self, _: dict[str, Any]):
        self.project.cover_image_url = None
        self.project.cover_prompt = None
        self.project.cover_status = "none"
        self.project.cover_error = None
        self.project.cover_updated_at = None
        return self.project.id, {"cover_status": "none", "cover_image_url": None}, "Đã xóa ảnh bìa dự án"

    async def _task_preview(self, arguments: dict[str, Any], action: str):
        data = self._data(arguments)
        if set(data) & {"project_id", "user_id", "chapter_id", "outline_id"}:
            raise ValueError("data không được chứa định danh dự án hoặc tài nguyên, hãy dùng tham số cấp cao của công cụ")
        try:
            if action == "generate_chapter":
                from app.schemas.chapter import ChapterGenerateRequest
                ChapterGenerateRequest(**data)
            elif action == "batch_generate_chapters":
                from app.schemas.chapter import BatchGenerateRequest
                BatchGenerateRequest(**data)
            elif action == "regenerate_chapter":
                from app.schemas.regeneration import ChapterRegenerateRequest
                ChapterRegenerateRequest(**data)
            elif action == "partial_regenerate_chapter":
                from app.schemas.chapter import PartialRegenerateRequest
                PartialRegenerateRequest(**data)
            elif action == "generate_character":
                from app.schemas.character import CharacterGenerateRequest
                CharacterGenerateRequest(project_id=self.project.id, **data)
            elif action == "generate_organization":
                from app.api.organizations import OrganizationGenerateRequest
                OrganizationGenerateRequest(project_id=self.project.id, **data)
            elif action == "generate_careers":
                from app.schemas.career import CareerGenerateRequest
                CareerGenerateRequest(project_id=self.project.id, **data)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Tham số tác vụ không hợp lệ: {exc}") from exc
        target: dict[str, Any] = {"action": action, "parameters": data}
        entity_id: str | None = self.project.id
        if action in {"expand_outline"}:
            from app.models.outline import Outline
            outline_id = arguments.get("outline_id")
            outline = (await self.db.execute(select(Outline).where(
                Outline.id == outline_id, Outline.project_id == self.project.id
            ))).scalar_one_or_none()
            if not outline:
                raise ValueError("Không tìm thấy dàn ý trong dự án hiện tại")
            target["outline"] = {"id": outline.id, "title": outline.title}
            entity_id = outline.id
        if action in {
            "generate_chapter", "analyze_chapter", "regenerate_chapter",
            "partial_regenerate_chapter",
        }:
            chapter = await self._find_chapter(arguments)
            target["chapter"] = {"id": chapter.id, "chapter_number": chapter.chapter_number, "title": chapter.title}
            entity_id = chapter.id
            if action == "analyze_chapter" and not (chapter.content or "").strip():
                raise ValueError("Nội dung chương trống, không thể phân tích")
            if action in {"regenerate_chapter", "partial_regenerate_chapter"} and not (chapter.content or "").strip():
                raise ValueError("Nội dung chương trống, không thể viết lại")
        if action in {"generate_character", "generate_organization", "generate_careers"}:
            target["project"] = {"id": self.project.id, "title": self.project.title}
        return {}, target, f"Khởi động tác vụ nền: {action}", entity_id

    async def _start_project_task_preview_generate_outlines(self, a): return await self._task_preview(a, "generate_outlines")
    async def _start_project_task_preview_expand_outline(self, a): return await self._task_preview(a, "expand_outline")
    async def _start_project_task_preview_batch_expand_outlines(self, a): return await self._task_preview(a, "batch_expand_outlines")
    async def _start_project_task_preview_generate_chapter(self, a): return await self._task_preview(a, "generate_chapter")
    async def _start_project_task_preview_batch_generate_chapters(self, a): return await self._task_preview(a, "batch_generate_chapters")
    async def _start_project_task_preview_analyze_chapter(self, a): return await self._task_preview(a, "analyze_chapter")
    async def _start_project_task_preview_regenerate_chapter(self, a): return await self._task_preview(a, "regenerate_chapter")
    async def _start_project_task_preview_partial_regenerate_chapter(self, a): return await self._task_preview(a, "partial_regenerate_chapter")
    async def _start_project_task_preview_generate_character(self, a): return await self._task_preview(a, "generate_character")
    async def _start_project_task_preview_generate_organization(self, a): return await self._task_preview(a, "generate_organization")
    async def _start_project_task_preview_generate_careers(self, a): return await self._task_preview(a, "generate_careers")

    def _request(self):
        return SimpleNamespace(state=SimpleNamespace(user_id=self.project.user_id))

    @staticmethod
    def _detach(background_tasks: BackgroundTasks) -> None:
        task = asyncio.create_task(background_tasks())
        task.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)

    async def _start_project_task_generate_outlines(self, arguments: dict[str, Any]):
        from app.api.outlines import generate_outline_task
        data = dict(self._data(arguments))
        data["project_id"] = self.project.id
        result = await generate_outline_task(data, self._request(), self.db, None)
        return result["task_id"], result, result["message"]

    async def _start_project_task_expand_outline(self, arguments: dict[str, Any]):
        from app.api.outlines import expand_outline_to_chapters_background
        result = await expand_outline_to_chapters_background(
            arguments["outline_id"], dict(self._data(arguments)), self._request(), self.db
        )
        return result["task_id"], result, result["message"]

    async def _start_project_task_batch_expand_outlines(self, arguments: dict[str, Any]):
        from app.api.outlines import batch_expand_outlines_background
        data = dict(self._data(arguments))
        data["project_id"] = self.project.id
        result = await batch_expand_outlines_background(data, self._request(), self.db)
        return result["task_id"], result, result["message"]

    async def _start_project_task_generate_chapter(self, arguments: dict[str, Any]):
        from app.api.chapters import generate_chapter_content_background
        from app.schemas.chapter import ChapterGenerateRequest
        chapter = await self._find_chapter(arguments)
        request_data = ChapterGenerateRequest(**self._data(arguments))
        result = await generate_chapter_content_background(chapter.id, self._request(), request_data, self.db)
        return result["task_id"], result, result["message"]

    async def _start_project_task_batch_generate_chapters(self, arguments: dict[str, Any]):
        from app.api.chapters import batch_generate_chapters_in_order
        from app.api.settings import get_user_ai_service_from_db
        from app.schemas.chapter import BatchGenerateRequest
        request_data = BatchGenerateRequest(**self._data(arguments))
        tasks = BackgroundTasks()
        ai_service = await get_user_ai_service_from_db(self.project.user_id, self.db)
        result = await batch_generate_chapters_in_order(
            self.project.id, request_data, self._request(), tasks, self.db, ai_service
        )
        self._detach(tasks)
        data = result.model_dump(mode="json")
        return result.batch_id, data, result.message

    async def _start_project_task_analyze_chapter(self, arguments: dict[str, Any]):
        from app.api.chapters import analyze_chapter_background, _schedule_analysis_background
        chapter = await self._find_chapter(arguments)
        existing = (await self.db.execute(select(AnalysisTask).where(
            AnalysisTask.project_id == self.project.id,
            AnalysisTask.chapter_id == chapter.id,
            AnalysisTask.user_id == self.project.user_id,
        ).order_by(AnalysisTask.created_at.desc()).limit(1))).scalar_one_or_none()
        if existing and existing.status in {"pending", "running"}:
            return existing.id, {"task_id": existing.id, "status": existing.status}, "Đã có tác vụ phân tích đang chạy"
        task = AnalysisTask(
            chapter_id=chapter.id,
            project_id=self.project.id,
            user_id=self.project.user_id,
            status="pending",
            progress=0,
        )
        self.db.add(task)
        await self.db.flush()
        task_id = task.id
        await self.db.commit()
        _schedule_analysis_background(analyze_chapter_background(
            chapter_id=chapter.id,
            user_id=self.project.user_id,
            project_id=self.project.id,
            task_id=task_id,
        ))
        result = {"task_id": task_id, "chapter_id": chapter.id, "status": "pending"}
        return task_id, result, "Tác vụ phân tích chương đã vào hàng đợi nền"

    @staticmethod
    async def _consume_sse_response(
        response: Any,
        cancellation_check: Any = None,
    ) -> dict[str, Any]:
        """完整消费内部 SSE，提取 result，并把流内 error 转成后台任务失败。"""
        final_result: dict[str, Any] = {}
        last_cancel_check = 0.0
        async for raw_chunk in response.body_iterator:
            if cancellation_check:
                now = asyncio.get_running_loop().time()
                if now - last_cancel_check >= 2:
                    last_cancel_check = now
                    if await cancellation_check():
                        raise RuntimeError("Tác vụ đã bị hủy")
            chunk = raw_chunk.decode("utf-8") if isinstance(raw_chunk, bytes) else str(raw_chunk)
            for line in chunk.splitlines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "error":
                    raise RuntimeError(str(event.get("error") or "Tác vụ tạo thất bại"))
                if event.get("type") == "result" and isinstance(event.get("data"), dict):
                    final_result = event["data"]
        return final_result

    async def _enqueue_stream_task(
        self,
        *,
        action: str,
        task_input: dict[str, Any],
        chapter_id: str | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        """将原有流式生成 API 包装为可查询、可取消的持久后台任务。"""
        from app.services.background_task_service import (
            TaskProgressTracker,
            background_task_service,
        )

        task = await background_task_service.create_task(
            user_id=self.project.user_id,
            project_id=self.project.id,
            task_type=action,
            task_input={**task_input, "chapter_id": chapter_id} if chapter_id else task_input,
            db=self.db,
        )

        async def run_stream(task_id: str, user_id: str):
            from sqlalchemy.ext.asyncio import AsyncSession as BackgroundSession, async_sessionmaker
            from app.database import get_engine
            from app.api.settings import get_user_ai_service_from_db

            engine = await get_engine(user_id)
            session_factory = async_sessionmaker(
                engine, class_=BackgroundSession, expire_on_commit=False
            )
            tracker = TaskProgressTracker(task_id, user_id, "Trợ lý dự án")
            await tracker.start()
            try:
                async with session_factory() as background_db:
                    ai_service = await get_user_ai_service_from_db(user_id, background_db)
                    http_request = SimpleNamespace(state=SimpleNamespace(user_id=user_id))
                    extra_tasks = BackgroundTasks()

                    if action == "character_generate":
                        from app.api.characters import generate_character_stream
                        from app.schemas.character import CharacterGenerateRequest
                        payload = CharacterGenerateRequest(project_id=self.project.id, **task_input)
                        response = await generate_character_stream(payload, http_request, background_db, ai_service)
                    elif action == "organization_generate":
                        from app.api.organizations import OrganizationGenerateRequest, generate_organization_stream
                        payload = OrganizationGenerateRequest(project_id=self.project.id, **task_input)
                        response = await generate_organization_stream(payload, http_request, background_db, ai_service)
                    elif action == "career_generate":
                        from app.api.careers import generate_career_system
                        from app.schemas.career import CareerGenerateRequest
                        payload = CareerGenerateRequest(project_id=self.project.id, **task_input)
                        response = await generate_career_system(payload, http_request, background_db, ai_service)
                    elif action == "chapter_regenerate":
                        from app.api.chapters import regenerate_chapter_stream
                        from app.schemas.regeneration import ChapterRegenerateRequest
                        payload = ChapterRegenerateRequest(**task_input)
                        response = await regenerate_chapter_stream(
                            chapter_id, http_request, payload, extra_tasks, background_db, ai_service
                        )
                    elif action == "chapter_partial_regenerate":
                        from app.api.chapters import partial_regenerate_stream
                        from app.schemas.chapter import PartialRegenerateRequest
                        payload = PartialRegenerateRequest(**task_input)
                        response = await partial_regenerate_stream(
                            chapter_id, http_request, payload, background_db, ai_service
                        )
                    else:
                        raise RuntimeError(f"Tác vụ nền dạng stream không được hỗ trợ: {action}")

                    await tracker.generating(1, 2, "AI đang tạo và lưu kết quả...")
                    result = await self._consume_sse_response(response, tracker.check_cancelled)
                    if extra_tasks.tasks:
                        self._detach(extra_tasks)
                    await tracker.set_result(result)
                    await tracker.complete("Tác vụ tạo đã hoàn thành")
            except Exception as exc:
                # 取消接口已将任务置为 cancelled；不要再用 failed 覆盖终态。
                if await tracker.check_cancelled():
                    return
                await tracker.error(str(exc))
                raise

        await background_task_service.spawn_background_task(
            task.id, self.project.user_id, run_stream
        )
        data = {
            "task_id": task.id,
            "task_type": action,
            "status": "pending",
            "message": "Tác vụ tạo đã được thêm vào hàng đợi nền",
        }
        return task.id, data, data["message"]

    async def _start_project_task_regenerate_chapter(self, arguments: dict[str, Any]):
        chapter = await self._find_chapter(arguments)
        return await self._enqueue_stream_task(
            action="chapter_regenerate", task_input=dict(self._data(arguments)), chapter_id=chapter.id
        )

    async def _start_project_task_partial_regenerate_chapter(self, arguments: dict[str, Any]):
        chapter = await self._find_chapter(arguments)
        return await self._enqueue_stream_task(
            action="chapter_partial_regenerate", task_input=dict(self._data(arguments)), chapter_id=chapter.id
        )

    async def _start_project_task_generate_character(self, arguments: dict[str, Any]):
        return await self._enqueue_stream_task(
            action="character_generate", task_input=dict(self._data(arguments))
        )

    async def _start_project_task_generate_organization(self, arguments: dict[str, Any]):
        return await self._enqueue_stream_task(
            action="organization_generate", task_input=dict(self._data(arguments))
        )

    async def _start_project_task_generate_careers(self, arguments: dict[str, Any]):
        return await self._enqueue_stream_task(
            action="career_generate", task_input=dict(self._data(arguments))
        )
