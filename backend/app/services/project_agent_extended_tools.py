"""项目智能体的扩展项目域工具。"""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import Career, CharacterCareer
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.foreshadow import Foreshadow
from app.models.outline import Outline
from app.models.project import Project
from app.models.relationship import (
    CharacterRelationship,
    Organization,
    OrganizationMember,
    RelationshipType,
)
from app.services.project_agent_selectors import (
    clean_identifier,
    find_career,
    find_chapter,
    find_character,
    find_foreshadow,
    find_organization,
)


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


ID = {"type": "string", "minLength": 1, "pattern": r".*\S.*"}
DATA = {"type": "object", "additionalProperties": True}


EXTENDED_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_organizations",
        "description": "Tra cứu tổ chức có cấu trúc và thuộc tính thế lực của dự án hiện tại.",
        "parameters": _schema({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
    },
    {
        "name": "get_organization_detail",
        "description": "Lấy chi tiết tổ chức và danh sách thành viên.",
        "parameters": _schema({"organization_id": ID, "name": {"type": "string"}}),
    },
    {
        "name": "list_careers",
        "description": "Tra cứu hệ thống nghề nghiệp chính và nghề nghiệp phụ của dự án hiện tại.",
        "parameters": _schema({"career_type": {"type": "string", "enum": ["all", "main", "sub"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
    },
    {
        "name": "get_career_detail",
        "description": "Lấy chi tiết giai đoạn và năng lực của nghề nghiệp theo ID hoặc tên nghề nghiệp.",
        "parameters": _schema({"career_id": ID, "name": {"type": "string"}}),
    },
    {
        "name": "get_character_careers",
        "description": "Tra cứu nghề nghiệp chính, nghề nghiệp phụ và tiến độ giai đoạn của nhân vật.",
        "parameters": _schema({"character_id": ID, "character_name": {"type": "string"}}),
    },
    {
        "name": "get_relationship_types",
        "description": "Lấy các loại quan hệ nhân vật khả dụng.",
        "parameters": _schema({}),
    },
    {
        "name": "get_relationship_graph",
        "description": "Lấy đồ thị quan hệ nhân vật/tổ chức của dự án hiện tại.",
        "parameters": _schema({}),
    },
    {
        "name": "get_foreshadow_detail",
        "description": "Lấy chi tiết đầy đủ của phục bút theo ID hoặc tiêu đề.",
        "parameters": _schema({"foreshadow_id": ID, "title": {"type": "string"}}),
    },
    {
        "name": "get_foreshadow_stats",
        "description": "Thống kê phục bút theo từng trạng thái và tình trạng quá hạn của dự án hiện tại.",
        "parameters": _schema({}),
    },
    {
        "name": "get_foreshadow_context",
        "description": "Lấy ngữ cảnh phục bút cần gài cắm, thu hồi hoặc lưu ý cho chương được chỉ định.",
        "parameters": _schema({"chapter_number": {"type": "integer", "minimum": 1}}, ["chapter_number"]),
    },
    {
        "name": "manage_outline",
        "description": "Tạo, xóa hoặc sắp xếp lại dàn ý; phải xác nhận trước khi thực thi. Muốn cập nhật nội dung hãy dùng update_outline.",
        "parameters": _schema({"action": {"type": "string", "enum": ["create", "delete", "reorder"]}, "outline_id": ID, "title": {"type": "string"}, "content": {"type": "string"}, "order_index": {"type": "integer", "minimum": 1}, "ordered_ids": {"type": "array", "items": ID}}, ["action"]),
        "risk_level": 2,
        "resources": ("outlines", "chapters"),
    },
    {
        "name": "manage_character",
        "description": "Tạo hoặc xóa bản ghi nhân vật/tổ chức phiên bản cũ; phải xác nhận trước khi thực thi. Muốn cập nhật hãy dùng update_character.",
        "parameters": _schema({"action": {"type": "string", "enum": ["create", "delete"]}, "character_id": ID, "data": DATA}, ["action"]),
        "risk_level": 2,
        "resources": ("characters", "organizations", "relationships", "careers"),
    },
    {
        "name": "manage_chapter",
        "description": "Tạo, xóa chương hoặc cập nhật nội dung chính văn/kế hoạch mở rộng của chương; phải xác nhận trước khi thực thi. Muốn cập nhật siêu dữ liệu hãy dùng update_chapter.",
        "parameters": _schema({"action": {"type": "string", "enum": ["create", "delete", "update_content", "update_plan"]}, "chapter_id": ID, "chapter_number": {"type": "integer", "minimum": 1}, "data": DATA}, ["action"]),
        "risk_level": 2,
        "resources": ("chapters", "projects"),
    },
    {
        "name": "manage_relationship",
        "description": "Tạo, cập nhật hoặc xóa quan hệ nhân vật của dự án hiện tại; phải xác nhận trước khi thực thi.",
        "parameters": _schema({"action": {"type": "string", "enum": ["create", "update", "delete"]}, "relationship_id": ID, "data": DATA}, ["action"]),
        "risk_level": 2,
        "resources": ("relationships",),
    },
    {
        "name": "manage_organization",
        "description": "Tạo, cập nhật, xóa tổ chức có cấu trúc hoặc quản lý thành viên tổ chức; phải xác nhận trước khi thực thi.",
        "parameters": _schema({"action": {"type": "string", "enum": ["create", "update", "delete", "add_member", "update_member", "remove_member"]}, "organization_id": ID, "member_id": ID, "data": DATA}, ["action"]),
        "risk_level": 2,
        "resources": ("organizations", "characters"),
    },
    {
        "name": "manage_foreshadow",
        "description": "Tạo, cập nhật, xóa, gài cắm, thu hồi hoặc bỏ phục bút; phải xác nhận trước khi thực thi.",
        "parameters": _schema({"action": {"type": "string", "enum": ["create", "update", "delete", "plant", "resolve", "abandon"]}, "foreshadow_id": ID, "data": DATA}, ["action"]),
        "risk_level": 2,
        "resources": ("foreshadows",),
    },
    {
        "name": "manage_career",
        "description": "Tạo, cập nhật, xóa nghề nghiệp hoặc thiết lập nghề nghiệp và giai đoạn cho nhân vật; phải xác nhận trước khi thực thi.",
        "parameters": _schema({"action": {"type": "string", "enum": ["create", "update", "delete", "set_main", "add_sub", "update_stage", "remove_sub"]}, "career_id": ID, "character_id": ID, "data": DATA}, ["action"]),
        "risk_level": 2,
        "resources": ("careers", "characters"),
    },
    {
        "name": "check_project_consistency",
        "description": "Kiểm tra tính nhất quán của tiêu đề dàn ý/chương theo chế độ một-một, các liên kết mồ côi và trường đếm trong dự án, không sửa dữ liệu.",
        "parameters": _schema({}),
    },
]


READ_TOOL_NAMES = {
    spec["name"] for spec in EXTENDED_TOOL_SPECS if not spec.get("risk_level")
}
WRITE_TOOL_NAMES = {
    spec["name"] for spec in EXTENDED_TOOL_SPECS if spec.get("risk_level")
}


def _value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _snapshot(entity: Any, fields: set[str] | list[str]) -> dict[str, Any]:
    return {field: _value(getattr(entity, field, None)) for field in fields}


def _preview_value(value: Any, limit: int = 800) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}… (tổng {len(value)} ký tự)"
    return value


class ProjectAgentExtendedTools:
    """扩展工具执行器，所有查询都强制带当前项目条件。"""

    CHARACTER_FIELDS = {
        "name", "age", "gender", "is_organization", "role_type", "personality",
        "background", "appearance", "organization_type", "organization_purpose",
        "traits", "avatar_url", "status", "status_changed_chapter",
        "current_state", "state_updated_chapter",
    }
    RELATIONSHIP_FIELDS = {
        "relationship_type_id", "relationship_name", "intimacy_level", "status",
        "description", "started_at", "ended_at",
    }
    ORGANIZATION_FIELDS = {"parent_org_id", "level", "power_level", "location", "motto", "color"}
    MEMBER_FIELDS = {"position", "rank", "status", "joined_at", "left_at", "loyalty", "contribution", "notes"}
    FORESHADOW_FIELDS = {
        "title", "content", "hint_text", "resolution_text", "plant_chapter_number",
        "target_resolve_chapter_number", "status", "is_long_term", "importance",
        "strength", "subtlety", "urgency", "related_characters",
        "related_foreshadow_ids", "tags", "category", "notes", "resolution_notes",
        "auto_remind", "remind_before_chapters", "include_in_context",
    }
    CAREER_FIELDS = {
        "name", "type", "description", "category", "stages", "max_stage",
        "requirements", "special_abilities", "worldview_rules", "attribute_bonuses",
    }

    def __init__(self, project: Project, db: AsyncSession):
        self.project = project
        self.db = db

    async def read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_{name}", None)
        if handler is None or name not in READ_TOOL_NAMES:
            raise ValueError(f"Công cụ đọc mở rộng chưa đăng ký: {name}")
        return await handler(arguments)

    async def preview(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in WRITE_TOOL_NAMES:
            raise ValueError(f"Công cụ ghi mở rộng chưa đăng ký: {name}")
        action = str(arguments.get("action") or "")
        if not action:
            raise ValueError("Thiếu action")
        before, after, label = await self._prepare(name, action, arguments)
        if before == after:
            raise ValueError("Không phát hiện trường nào cần sửa")
        resources = next(spec["resources"] for spec in EXTENDED_TOOL_SPECS if spec["name"] == name)
        keys = list(dict.fromkeys([*before.keys(), *after.keys()]))
        return {
            "entity_type": name.removeprefix("manage_"),
            "entity_id": arguments.get("relationship_id") or arguments.get("organization_id")
            or arguments.get("foreshadow_id") or arguments.get("career_id")
            or arguments.get("character_id") or arguments.get("chapter_id")
            or arguments.get("outline_id"),
            "label": label,
            "changes": {
                key: {
                    "before": _preview_value(before.get(key)),
                    "after": _preview_value(after.get(key)),
                }
                for key in keys if before.get(key) != after.get(key)
            },
            "resources": list(resources),
        }

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in WRITE_TOOL_NAMES:
            raise ValueError(f"Công cụ ghi mở rộng chưa đăng ký: {name}")
        action = str(arguments.get("action") or "")
        before, _, label = await self._prepare(name, action, arguments)
        handler = getattr(self, f"_{name}_{action}", None)
        if handler is None:
            raise ValueError(f"Công cụ {name} không hỗ trợ hành động {action}")
        entity_id, after, message = await handler(arguments)
        resources = next(spec["resources"] for spec in EXTENDED_TOOL_SPECS if spec["name"] == name)
        await self.db.flush()
        return {
            "message": message or f"Đã thực thi {label}",
            "entity_id": entity_id,
            "before": before,
            "after": after,
            "resources": list(resources),
        }

    async def _prepare(
        self,
        name: str,
        action: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        handler = getattr(self, f"_{name}_preview_{action}", None)
        if handler is None:
            raise ValueError(f"Công cụ {name} không hỗ trợ hành động {action}")
        return await handler(arguments)

    async def _list_organizations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(arguments.get("limit", 50)), 1), 100)
        query = (
            select(Organization, Character)
            .join(Character, Organization.character_id == Character.id)
            .where(Organization.project_id == self.project.id)
        )
        keyword = str(arguments.get("query") or "").strip()
        if keyword:
            query = query.where(Character.name.ilike(f"%{keyword}%"))
        rows = (await self.db.execute(query.order_by(Character.name).limit(limit))).all()
        return {"total": len(rows), "items": [self._organization_data(org, char) for org, char in rows]}

    async def _get_organization_detail(self, arguments: dict[str, Any]) -> dict[str, Any]:
        org, char = await self._find_organization(arguments)
        members = (await self.db.execute(
            select(OrganizationMember, Character)
            .join(Character, OrganizationMember.character_id == Character.id)
            .where(OrganizationMember.organization_id == org.id)
            .order_by(OrganizationMember.rank.desc(), Character.name)
        )).all()
        data = self._organization_data(org, char)
        data["members"] = [
            {**_snapshot(member, self.MEMBER_FIELDS | {"id", "character_id"}), "character_name": member_char.name}
            for member, member_char in members
        ]
        return data

    @staticmethod
    def _organization_data(org: Organization, char: Character) -> dict[str, Any]:
        return {
            "id": org.id, "character_id": char.id, "name": char.name,
            "type": char.organization_type, "purpose": char.organization_purpose,
            "parent_org_id": org.parent_org_id, "level": org.level,
            "power_level": org.power_level, "member_count": org.member_count,
            "location": org.location, "motto": org.motto, "color": org.color,
        }

    async def _list_careers(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(arguments.get("limit", 50)), 1), 100)
        query = select(Career).where(Career.project_id == self.project.id)
        career_type = arguments.get("career_type", "all")
        if career_type in {"main", "sub"}:
            query = query.where(Career.type == career_type)
        rows = (await self.db.execute(query.order_by(Career.type, Career.name).limit(limit))).scalars().all()
        return {"total": len(rows), "items": [self._career_data(row) for row in rows]}

    async def _get_career_detail(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._career_data(await self._find_career(arguments))

    async def _get_character_careers(self, arguments: dict[str, Any]) -> dict[str, Any]:
        character = await self._find_character(arguments)
        rows = (await self.db.execute(
            select(CharacterCareer, Career)
            .join(Career, CharacterCareer.career_id == Career.id)
            .where(CharacterCareer.character_id == character.id)
            .order_by(CharacterCareer.career_type)
        )).all()
        return {
            "character_id": character.id,
            "character_name": character.name,
            "items": [
                {**_snapshot(link, {"id", "career_id", "career_type", "current_stage", "stage_progress", "started_at", "reached_current_stage_at", "notes"}), "career": self._career_data(career)}
                for link, career in rows
            ],
        }

    @staticmethod
    def _career_data(career: Career) -> dict[str, Any]:
        def parse(value: str | None, fallback: Any) -> Any:
            try:
                return json.loads(value) if value else fallback
            except json.JSONDecodeError:
                return fallback
        return {
            **_snapshot(career, {"id", "name", "type", "description", "category", "max_stage", "requirements", "special_abilities", "worldview_rules", "source"}),
            "stages": parse(career.stages, []),
            "attribute_bonuses": parse(career.attribute_bonuses, None),
        }

    async def _get_relationship_types(self, _: dict[str, Any]) -> dict[str, Any]:
        rows = (await self.db.execute(select(RelationshipType).order_by(RelationshipType.id))).scalars().all()
        return {"items": [_snapshot(row, {"id", "name", "category", "reverse_name", "intimacy_range", "description"}) for row in rows]}

    async def _get_relationship_graph(self, _: dict[str, Any]) -> dict[str, Any]:
        chars = (await self.db.execute(select(Character).where(Character.project_id == self.project.id))).scalars().all()
        relationships = (await self.db.execute(select(CharacterRelationship).where(CharacterRelationship.project_id == self.project.id))).scalars().all()
        return {
            "nodes": [{"id": row.id, "name": row.name, "type": "organization" if row.is_organization else "character", "role_type": row.role_type} for row in chars],
            "links": [{"id": row.id, "source": row.character_from_id, "target": row.character_to_id, "relationship": row.relationship_name, "intimacy": row.intimacy_level, "status": row.status} for row in relationships],
        }

    async def _get_foreshadow_detail(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return (await self._find_foreshadow(arguments)).to_dict()

    async def _get_foreshadow_stats(self, _: dict[str, Any]) -> dict[str, Any]:
        rows = (await self.db.execute(select(Foreshadow).where(Foreshadow.project_id == self.project.id))).scalars().all()
        status_counts = {status: 0 for status in ("pending", "planted", "resolved", "partially_resolved", "abandoned")}
        for row in rows:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1
        current_chapter = max((row.chapter_number for row in (await self.db.execute(select(Chapter).where(Chapter.project_id == self.project.id))).scalars()), default=0)
        return {"total": len(rows), **status_counts, "long_term_count": sum(bool(row.is_long_term) for row in rows), "overdue_count": sum(row.get_urgency_level(current_chapter) == 3 for row in rows)}

    async def _get_foreshadow_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(arguments["chapter_number"])
        rows = (await self.db.execute(select(Foreshadow).where(Foreshadow.project_id == self.project.id, Foreshadow.include_in_context.is_(True)))).scalars().all()
        items = []
        for row in rows:
            urgency = row.get_urgency_level(chapter_number)
            if row.plant_chapter_number == chapter_number or urgency > 0 or (row.target_resolve_chapter_number and row.target_resolve_chapter_number == chapter_number):
                items.append({**row.to_dict(), "calculated_urgency": urgency})
        return {"chapter_number": chapter_number, "items": items, "context_text": "\n".join(row["title"] + ": " + row["content"] for row in items)}

    async def _check_project_consistency(self, _: dict[str, Any]) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        chapters = (await self.db.execute(select(Chapter).where(Chapter.project_id == self.project.id))).scalars().all()
        outlines = (await self.db.execute(select(Outline).where(Outline.project_id == self.project.id))).scalars().all()
        if self.project.outline_mode == "one-to-one":
            outline_by_order = {row.order_index: row for row in outlines}
            for chapter in chapters:
                outline = outline_by_order.get(chapter.chapter_number)
                if not outline:
                    issues.append({"type": "missing_outline", "chapter_id": chapter.id, "chapter_number": chapter.chapter_number})
                elif outline.title != chapter.title or outline.content != chapter.summary:
                    issues.append({"type": "outline_chapter_mismatch", "chapter_id": chapter.id, "outline_id": outline.id, "chapter_number": chapter.chapter_number, "chapter_title": chapter.title, "outline_title": outline.title})
        calculated_words = sum(row.word_count or 0 for row in chapters)
        if calculated_words != (self.project.current_words or 0):
            issues.append({"type": "project_word_count_mismatch", "stored": self.project.current_words or 0, "calculated": calculated_words})
        return {"consistent": not issues, "issue_count": len(issues), "issues": issues}

    async def _find_character(self, arguments: dict[str, Any]) -> Character:
        return await find_character(self.db, self.project.id, arguments)

    async def _find_organization(self, arguments: dict[str, Any]) -> tuple[Organization, Character]:
        return await find_organization(self.db, self.project.id, arguments)

    async def _find_career(self, arguments: dict[str, Any]) -> Career:
        return await find_career(self.db, self.project.id, arguments)

    async def _find_foreshadow(self, arguments: dict[str, Any]) -> Foreshadow:
        return await find_foreshadow(self.db, self.project.id, arguments)

    async def _find_outline(self, outline_id: str | None) -> Outline:
        outline_id = clean_identifier(outline_id)
        if not outline_id:
            raise ValueError("Phải cung cấp outline_id")
        row = (await self.db.execute(select(Outline).where(
            Outline.id == outline_id,
            Outline.project_id == self.project.id,
        ))).scalar_one_or_none()
        if not row:
            raise ValueError("Không tìm thấy dàn ý trong dự án hiện tại")
        return row

    async def _find_chapter(self, arguments: dict[str, Any]) -> Chapter:
        return await find_chapter(self.db, self.project.id, arguments)

    async def _find_relationship(self, relationship_id: str | None) -> CharacterRelationship:
        relationship_id = clean_identifier(relationship_id)
        if not relationship_id:
            raise ValueError("Phải cung cấp relationship_id")
        row = (await self.db.execute(select(CharacterRelationship).where(
            CharacterRelationship.id == relationship_id,
            CharacterRelationship.project_id == self.project.id,
        ))).scalar_one_or_none()
        if not row:
            raise ValueError("Không tìm thấy quan hệ nhân vật trong dự án hiện tại")
        return row

    async def _find_member(self, member_id: str | None) -> OrganizationMember:
        member_id = clean_identifier(member_id)
        if not member_id:
            raise ValueError("Phải cung cấp member_id")
        row = (await self.db.execute(
            select(OrganizationMember)
            .join(Organization, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.id == member_id, Organization.project_id == self.project.id)
        )).scalar_one_or_none()
        if not row:
            raise ValueError("Không tìm thấy thành viên tổ chức trong dự án hiện tại")
        return row

    @staticmethod
    def _data(arguments: dict[str, Any]) -> dict[str, Any]:
        data = arguments.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("data phải là object")
        return data

    @staticmethod
    def _fields(data: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        fields = {key: value for key, value in data.items() if key in allowed}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Chứa trường không hỗ trợ: {', '.join(sorted(unknown))}")
        return fields

    # --- 大纲管理 ---

    async def _manage_outline_preview_create(self, arguments: dict[str, Any]):
        title = str(arguments.get("title") or "").strip()
        content = str(arguments.get("content") or "").strip()
        order_index = arguments.get("order_index")
        if not title or not content or not isinstance(order_index, int) or order_index < 1:
            raise ValueError("Tạo dàn ý cần title, content và order_index là số nguyên dương")
        exists = (await self.db.execute(select(Outline.id).where(
            Outline.project_id == self.project.id,
            Outline.order_index == order_index,
        ))).scalar_one_or_none()
        if exists:
            raise ValueError(f"Dàn ý thứ {order_index} đã tồn tại")
        after = {"title": title, "content": content, "order_index": order_index}
        return {}, after, f"Tạo dàn ý thứ {order_index} «{title}»"

    async def _manage_outline_create(self, arguments: dict[str, Any]):
        title = str(arguments["title"]).strip()
        content = str(arguments["content"]).strip()
        order_index = int(arguments["order_index"])
        structure = json.dumps({"title": title, "summary": content, "content": content}, ensure_ascii=False)
        row = Outline(project_id=self.project.id, title=title, content=content, order_index=order_index, structure=structure)
        self.db.add(row)
        await self.db.flush()
        if self.project.outline_mode == "one-to-one":
            self.db.add(Chapter(
                project_id=self.project.id,
                outline_id=row.id,
                chapter_number=order_index,
                title=title,
                summary=content,
                content="",
                word_count=0,
                status="pending",
                sub_index=1,
            ))
        return row.id, _snapshot(row, {"id", "title", "content", "order_index"}), f"Đã tạo dàn ý thứ {order_index} «{title}»"

    async def _manage_outline_preview_delete(self, arguments: dict[str, Any]):
        row = await self._find_outline(arguments.get("outline_id"))
        before = _snapshot(row, {"id", "title", "content", "order_index"})
        chapter_query = select(Chapter).where(Chapter.project_id == self.project.id)
        if self.project.outline_mode == "one-to-one":
            chapter_query = chapter_query.where(Chapter.chapter_number == row.order_index)
        else:
            chapter_query = chapter_query.where(Chapter.outline_id == row.id)
        chapters = (await self.db.execute(chapter_query)).scalars().all()
        before["affected_chapters"] = len(chapters)
        before["affected_words"] = sum(chapter.word_count or 0 for chapter in chapters)
        return before, {}, f"Xóa dàn ý thứ {row.order_index} «{row.title}»"

    async def _manage_outline_delete(self, arguments: dict[str, Any]):
        row = await self._find_outline(arguments.get("outline_id"))
        entity_id, deleted_order = row.id, row.order_index
        label = f"Dàn ý thứ {deleted_order} «{row.title}»"
        chapter_query = select(Chapter).where(Chapter.project_id == self.project.id)
        if self.project.outline_mode == "one-to-one":
            chapter_query = chapter_query.where(Chapter.chapter_number == deleted_order)
        else:
            chapter_query = chapter_query.where(Chapter.outline_id == row.id)
        chapters = (await self.db.execute(chapter_query)).scalars().all()
        deleted_words = sum(chapter.word_count or 0 for chapter in chapters)
        for chapter in chapters:
            try:
                from app.services.memory_service import memory_service
                await memory_service.delete_chapter_memories(
                    user_id=self.project.user_id,
                    project_id=self.project.id,
                    chapter_id=chapter.id,
                )
            except Exception:
                pass
            await self.db.delete(chapter)
        self.project.current_words = max(0, (self.project.current_words or 0) - deleted_words)
        await self.db.delete(row)
        subsequent_outlines = (await self.db.execute(select(Outline).where(
            Outline.project_id == self.project.id,
            Outline.order_index > deleted_order,
        ))).scalars().all()
        for outline in subsequent_outlines:
            outline.order_index -= 1
        if self.project.outline_mode == "one-to-one":
            subsequent_chapters = (await self.db.execute(select(Chapter).where(
                Chapter.project_id == self.project.id,
                Chapter.chapter_number > deleted_order,
            ))).scalars().all()
            for chapter in subsequent_chapters:
                chapter.chapter_number -= 1
        return entity_id, {}, f"Đã xóa {label}"

    async def _manage_outline_preview_reorder(self, arguments: dict[str, Any]):
        ordered_ids = arguments.get("ordered_ids") or []
        if not isinstance(ordered_ids, list) or not ordered_ids or len(set(ordered_ids)) != len(ordered_ids):
            raise ValueError("ordered_ids phải là danh sách ID dàn ý không trùng")
        rows = (await self.db.execute(select(Outline).where(Outline.project_id == self.project.id))).scalars().all()
        by_id = {row.id: row for row in rows}
        if set(ordered_ids) != set(by_id):
            raise ValueError("ordered_ids phải bao gồm đầy đủ mọi ID dàn ý của dự án hiện tại")
        before = {row.id: row.order_index for row in rows}
        after = {outline_id: index for index, outline_id in enumerate(ordered_ids, 1)}
        return before, after, "Sắp xếp lại toàn bộ dàn ý"

    async def _manage_outline_reorder(self, arguments: dict[str, Any]):
        ordered_ids = list(arguments["ordered_ids"])
        rows = (await self.db.execute(select(Outline).where(Outline.project_id == self.project.id))).scalars().all()
        by_id = {row.id: row for row in rows}
        chapters_by_outline: dict[str, Chapter] = {}
        if self.project.outline_mode == "one-to-one":
            chapters = (await self.db.execute(select(Chapter).where(
                Chapter.project_id == self.project.id
            ))).scalars().all()
            old_order_to_id = {row.order_index: row.id for row in rows}
            chapters_by_outline = {
                chapter.outline_id or old_order_to_id.get(chapter.chapter_number): chapter
                for chapter in chapters
                if chapter.outline_id or old_order_to_id.get(chapter.chapter_number)
            }
        for index, outline_id in enumerate(ordered_ids, 1):
            by_id[outline_id].order_index = index
            chapter = chapters_by_outline.get(outline_id)
            if chapter:
                chapter.chapter_number = index
        return None, {outline_id: index for index, outline_id in enumerate(ordered_ids, 1)}, "Đã sắp xếp lại dàn ý"

    # --- 角色管理 ---

    async def _manage_character_preview_create(self, arguments: dict[str, Any]):
        data = self._fields(self._data(arguments), self.CHARACTER_FIELDS | self.ORGANIZATION_FIELDS)
        self._validate_character_fields(data)
        organization_fields = {key: data[key] for key in data if key in self.ORGANIZATION_FIELDS}
        if organization_fields and not data.get("is_organization"):
            raise ValueError("Nhân vật thường không thể đặt trường riêng của tổ chức")
        await self._validate_organization_fields(organization_fields)
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Tạo nhân vật cần name")
        return {}, data, f"Tạo {'tổ chức' if data.get('is_organization') else 'nhân vật'}«{name}»"

    async def _manage_character_create(self, arguments: dict[str, Any]):
        data = self._fields(self._data(arguments), self.CHARACTER_FIELDS | self.ORGANIZATION_FIELDS)
        self._validate_character_fields(data)
        org_data = {key: data.pop(key) for key in list(data) if key in self.ORGANIZATION_FIELDS}
        await self._validate_organization_fields(org_data)
        data["name"] = str(data.get("name") or "").strip()
        row = Character(project_id=self.project.id, **data)
        self.db.add(row)
        await self.db.flush()
        if row.is_organization:
            self.db.add(Organization(project_id=self.project.id, character_id=row.id, **org_data))
        return row.id, _snapshot(row, self.CHARACTER_FIELDS | {"id"}), f"Đã tạo {'tổ chức' if row.is_organization else 'nhân vật'}«{row.name}»"

    @staticmethod
    def _validate_character_fields(fields: dict[str, Any]) -> None:
        if "status" in fields and fields["status"] not in {
            "active", "deceased", "missing", "retired", "destroyed"
        }:
            raise ValueError("status không phải trạng thái nhân vật được hỗ trợ")
        for key in ("status_changed_chapter", "state_updated_chapter"):
            value = fields.get(key)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{key} phải là số nguyên dương hoặc null")

    async def _manage_character_preview_delete(self, arguments: dict[str, Any]):
        row = await self._find_character(arguments)
        before = _snapshot(row, self.CHARACTER_FIELDS | {"id"})
        return before, {}, f"Xóa {'tổ chức' if row.is_organization else 'nhân vật'}«{row.name}»"

    async def _manage_character_delete(self, arguments: dict[str, Any]):
        row = await self._find_character(arguments)
        entity_id, label = row.id, f"{'tổ chức' if row.is_organization else 'nhân vật'}«{row.name}»"
        await self.db.delete(row)
        return entity_id, {}, f"Đã xóa {label}"

    # --- 章节管理 ---

    async def _manage_chapter_preview_create(self, arguments: dict[str, Any]):
        data = self._data(arguments)
        chapter_number = data.get("chapter_number", arguments.get("chapter_number"))
        title = str(data.get("title") or "").strip()
        if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
            raise ValueError("Tạo chương cần chapter_number và title")
        exists = (await self.db.execute(select(Chapter.id).where(Chapter.project_id == self.project.id, Chapter.chapter_number == chapter_number))).scalar_one_or_none()
        if exists:
            raise ValueError(f"Chương {chapter_number} đã tồn tại")
        allowed = {"chapter_number", "title", "content", "summary", "status", "outline_id", "sub_index", "expansion_plan"}
        after = self._fields({**data, "chapter_number": chapter_number, "title": title}, allowed)
        if after.get("outline_id"):
            await self._find_outline(after["outline_id"])
        return {}, after, f"Tạo chương {chapter_number}«{title}»"

    async def _manage_chapter_create(self, arguments: dict[str, Any]):
        data = self._data(arguments)
        data["chapter_number"] = data.get("chapter_number", arguments.get("chapter_number"))
        allowed = {"chapter_number", "title", "content", "summary", "status", "outline_id", "sub_index", "expansion_plan"}
        fields = self._fields(data, allowed)
        if fields.get("outline_id"):
            await self._find_outline(fields["outline_id"])
        if isinstance(fields.get("expansion_plan"), (dict, list)):
            fields["expansion_plan"] = json.dumps(fields["expansion_plan"], ensure_ascii=False)
        fields["word_count"] = len(fields.get("content") or "")
        row = Chapter(project_id=self.project.id, **fields)
        self.db.add(row)
        self.project.current_words = (self.project.current_words or 0) + fields["word_count"]
        await self.db.flush()
        return row.id, _snapshot(row, {"id", "chapter_number", "title", "summary", "status", "word_count"}), f"Đã tạo chương {row.chapter_number}«{row.title}»"

    async def _manage_chapter_preview_delete(self, arguments: dict[str, Any]):
        row = await self._find_chapter(arguments)
        before = _snapshot(row, {"id", "chapter_number", "title", "summary", "status", "word_count"})
        return before, {}, f"Xóa chương {row.chapter_number}«{row.title}»"

    async def _manage_chapter_delete(self, arguments: dict[str, Any]):
        row = await self._find_chapter(arguments)
        entity_id, label = row.id, f"chương {row.chapter_number}«{row.title}»"
        self.project.current_words = max(0, (self.project.current_words or 0) - (row.word_count or 0))
        try:
            from app.services.memory_service import memory_service
            await memory_service.delete_chapter_memories(
                user_id=self.project.user_id,
                project_id=self.project.id,
                chapter_id=row.id,
            )
        except Exception:
            pass
        await self.db.delete(row)
        return entity_id, {}, f"Đã xóa {label}"

    async def _manage_chapter_preview_update_content(self, arguments: dict[str, Any]):
        row = await self._find_chapter(arguments)
        data = self._data(arguments)
        unknown = set(data) - {"content", "status"}
        if unknown:
            raise ValueError(f"Chứa trường không hỗ trợ: {', '.join(sorted(unknown))}")
        if "content" not in data or not isinstance(data["content"], str):
            raise ValueError("update_content cần data.content")
        if data.get("status", row.status) not in {"draft", "pending", "writing", "completed"}:
            raise ValueError("status không phải trạng thái chương được hỗ trợ")
        before = {"content": row.content or "", "word_count": row.word_count or 0, "status": row.status}
        after = {"content": data["content"], "word_count": len(data["content"]), "status": data.get("status", row.status)}
        return before, after, f"Cập nhật nội dung chính văn chương {row.chapter_number}«{row.title}»"

    async def _manage_chapter_update_content(self, arguments: dict[str, Any]):
        row = await self._find_chapter(arguments)
        data = self._data(arguments)
        old_count = row.word_count or 0
        row.content = data["content"]
        row.word_count = len(row.content or "")
        if "status" in data:
            row.status = data["status"]
        self.project.current_words = max(0, (self.project.current_words or 0) - old_count + row.word_count)
        return row.id, {"word_count": row.word_count, "status": row.status}, f"Đã cập nhật nội dung chính văn chương {row.chapter_number}«{row.title}»"

    async def _manage_chapter_preview_update_plan(self, arguments: dict[str, Any]):
        row = await self._find_chapter(arguments)
        data = self._data(arguments)
        plan = data.get("expansion_plan", data)
        before = {"expansion_plan": self._parse_json(row.expansion_plan, {})}
        after = {"expansion_plan": plan}
        return before, after, f"Cập nhật kế hoạch chương {row.chapter_number}«{row.title}»"

    async def _manage_chapter_update_plan(self, arguments: dict[str, Any]):
        row = await self._find_chapter(arguments)
        data = self._data(arguments)
        plan = data.get("expansion_plan", data)
        row.expansion_plan = json.dumps(plan, ensure_ascii=False)
        return row.id, {"expansion_plan": plan}, f"Đã cập nhật kế hoạch chương {row.chapter_number}«{row.title}»"

    # --- 关系管理 ---

    async def _manage_relationship_preview_create(self, arguments: dict[str, Any]):
        data = self._fields(self._data(arguments), self.RELATIONSHIP_FIELDS | {"character_from_id", "character_to_id"})
        await self._validate_relationship_characters(data)
        self._validate_relationship_fields(data)
        return {}, data, "Tạo quan hệ nhân vật"

    async def _manage_relationship_create(self, arguments: dict[str, Any]):
        data = self._fields(self._data(arguments), self.RELATIONSHIP_FIELDS | {"character_from_id", "character_to_id"})
        await self._validate_relationship_characters(data)
        self._validate_relationship_fields(data)
        row = CharacterRelationship(project_id=self.project.id, source="manual", **data)
        self.db.add(row)
        await self.db.flush()
        return row.id, _snapshot(row, self.RELATIONSHIP_FIELDS | {"id", "character_from_id", "character_to_id"}), "Đã tạo quan hệ nhân vật"

    async def _manage_relationship_preview_update(self, arguments: dict[str, Any]):
        row = await self._find_relationship(arguments.get("relationship_id"))
        fields = self._fields(self._data(arguments), self.RELATIONSHIP_FIELDS)
        self._validate_relationship_fields(fields)
        return _snapshot(row, set(fields)), fields, f"Cập nhật quan hệ {row.id[:8]}"

    async def _manage_relationship_update(self, arguments: dict[str, Any]):
        row = await self._find_relationship(arguments.get("relationship_id"))
        fields = self._fields(self._data(arguments), self.RELATIONSHIP_FIELDS)
        self._validate_relationship_fields(fields)
        for key, value in fields.items(): setattr(row, key, value)
        return row.id, _snapshot(row, set(fields)), "Đã cập nhật quan hệ nhân vật"

    async def _manage_relationship_preview_delete(self, arguments: dict[str, Any]):
        row = await self._find_relationship(arguments.get("relationship_id"))
        before = _snapshot(row, self.RELATIONSHIP_FIELDS | {"id", "character_from_id", "character_to_id"})
        return before, {}, f"Xóa quan hệ {row.id[:8]}"

    async def _manage_relationship_delete(self, arguments: dict[str, Any]):
        row = await self._find_relationship(arguments.get("relationship_id"))
        entity_id = row.id
        await self.db.delete(row)
        return entity_id, {}, "Đã xóa quan hệ nhân vật"

    async def _validate_relationship_characters(self, data: dict[str, Any]) -> None:
        from_id, to_id = data.get("character_from_id"), data.get("character_to_id")
        if not from_id or not to_id or from_id == to_id:
            raise ValueError("Hai bên quan hệ phải là hai ID nhân vật khác nhau")
        count = (await self.db.execute(select(func.count(Character.id)).where(Character.project_id == self.project.id, Character.id.in_([from_id, to_id])))).scalar_one()
        if count != 2:
            raise ValueError("Hai bên quan hệ phải thuộc dự án hiện tại")

    @staticmethod
    def _validate_relationship_fields(data: dict[str, Any]) -> None:
        intimacy = data.get("intimacy_level")
        if intimacy is not None and (
            isinstance(intimacy, bool)
            or not isinstance(intimacy, int)
            or not -100 <= intimacy <= 100
        ):
            raise ValueError("intimacy_level phải là số nguyên từ -100 đến 100")
        if "status" in data and data["status"] not in {"active", "broken", "past", "complicated"}:
            raise ValueError("status không phải trạng thái quan hệ được hỗ trợ")

    # --- 组织管理 ---

    async def _manage_organization_preview_create(self, arguments: dict[str, Any]):
        data = self._data(arguments)
        character = await self._find_character({"character_id": data.get("character_id")})
        if not character.is_organization:
            raise ValueError("Nhân vật liên kết không phải bản ghi tổ chức")
        exists = (await self.db.execute(select(Organization.id).where(Organization.character_id == character.id))).scalar_one_or_none()
        if exists:
            raise ValueError("Tổ chức này đã có chi tiết có cấu trúc")
        fields = self._fields({key: value for key, value in data.items() if key != "character_id"}, self.ORGANIZATION_FIELDS)
        await self._validate_organization_fields(fields)
        return {}, {"character_id": character.id, **fields}, f"Tạo chi tiết tổ chức«{character.name}»"

    async def _manage_organization_create(self, arguments: dict[str, Any]):
        data = self._data(arguments)
        character = await self._find_character({"character_id": data.get("character_id")})
        fields = self._fields({key: value for key, value in data.items() if key != "character_id"}, self.ORGANIZATION_FIELDS)
        await self._validate_organization_fields(fields)
        row = Organization(project_id=self.project.id, character_id=character.id, **fields)
        self.db.add(row)
        await self.db.flush()
        return row.id, _snapshot(row, self.ORGANIZATION_FIELDS | {"id", "character_id"}), f"Đã tạo chi tiết tổ chức«{character.name}»"

    async def _manage_organization_preview_update(self, arguments: dict[str, Any]):
        row, char = await self._find_organization(arguments)
        fields = self._fields(self._data(arguments), self.ORGANIZATION_FIELDS)
        await self._validate_organization_fields(fields, current_id=row.id)
        return _snapshot(row, set(fields)), fields, f"Cập nhật tổ chức«{char.name}»"

    async def _manage_organization_update(self, arguments: dict[str, Any]):
        row, char = await self._find_organization(arguments)
        fields = self._fields(self._data(arguments), self.ORGANIZATION_FIELDS)
        await self._validate_organization_fields(fields, current_id=row.id)
        for key, value in fields.items(): setattr(row, key, value)
        return row.id, _snapshot(row, set(fields)), f"Đã cập nhật tổ chức«{char.name}»"

    async def _validate_organization_fields(
        self,
        fields: dict[str, Any],
        current_id: str | None = None,
    ) -> None:
        parent_id = fields.get("parent_org_id")
        if parent_id:
            if parent_id == current_id:
                raise ValueError("Tổ chức không thể đặt chính mình làm tổ chức cha")
            parent = (await self.db.execute(select(Organization.id).where(
                Organization.id == parent_id,
                Organization.project_id == self.project.id,
            ))).scalar_one_or_none()
            if not parent:
                raise ValueError("Tổ chức cha phải thuộc dự án hiện tại")
        power = fields.get("power_level")
        if power is not None and (
            isinstance(power, bool)
            or not isinstance(power, int)
            or not 0 <= power <= 100
        ):
            raise ValueError("power_level phải là số nguyên từ 0 đến 100")

    async def _manage_organization_preview_delete(self, arguments: dict[str, Any]):
        row, char = await self._find_organization(arguments)
        before = self._organization_data(row, char)
        return before, {}, f"Xóa chi tiết tổ chức«{char.name}»"

    async def _manage_organization_delete(self, arguments: dict[str, Any]):
        row, char = await self._find_organization(arguments)
        entity_id, name = row.id, char.name
        await self.db.delete(row)
        return entity_id, {}, f"Đã xóa chi tiết tổ chức«{name}»"

    async def _manage_organization_preview_add_member(self, arguments: dict[str, Any]):
        org, org_char = await self._find_organization(arguments)
        data = self._data(arguments)
        character = await self._find_character({"character_id": data.get("character_id")})
        exists = (await self.db.execute(select(OrganizationMember.id).where(OrganizationMember.organization_id == org.id, OrganizationMember.character_id == character.id))).scalar_one_or_none()
        if exists:
            raise ValueError("Nhân vật này đã là thành viên tổ chức")
        fields = self._fields({key: value for key, value in data.items() if key != "character_id"}, self.MEMBER_FIELDS)
        if not str(fields.get("position") or "").strip():
            raise ValueError("Thêm thành viên cần position")
        self._validate_member_fields(fields)
        return {}, {"character_id": character.id, "character_name": character.name, **fields}, f"Thêm thành viên«{character.name}» vào tổ chức«{org_char.name}»"

    async def _manage_organization_add_member(self, arguments: dict[str, Any]):
        org, org_char = await self._find_organization(arguments)
        data = self._data(arguments)
        character = await self._find_character({"character_id": data.get("character_id")})
        fields = self._fields({key: value for key, value in data.items() if key != "character_id"}, self.MEMBER_FIELDS)
        self._validate_member_fields(fields)
        row = OrganizationMember(organization_id=org.id, character_id=character.id, source="manual", **fields)
        self.db.add(row)
        org.member_count = (org.member_count or 0) + 1
        await self.db.flush()
        return row.id, _snapshot(row, self.MEMBER_FIELDS | {"id", "character_id"}), f"Đã thêm thành viên«{character.name}» vào tổ chức«{org_char.name}»"

    async def _manage_organization_preview_update_member(self, arguments: dict[str, Any]):
        row = await self._find_member(arguments.get("member_id"))
        fields = self._fields(self._data(arguments), self.MEMBER_FIELDS)
        self._validate_member_fields(fields)
        return _snapshot(row, set(fields)), fields, f"Cập nhật thành viên tổ chức {row.id[:8]}"

    async def _manage_organization_update_member(self, arguments: dict[str, Any]):
        row = await self._find_member(arguments.get("member_id"))
        fields = self._fields(self._data(arguments), self.MEMBER_FIELDS)
        self._validate_member_fields(fields)
        for key, value in fields.items(): setattr(row, key, value)
        return row.id, _snapshot(row, set(fields)), "Đã cập nhật thành viên tổ chức"

    @staticmethod
    def _validate_member_fields(fields: dict[str, Any]) -> None:
        for key in ("loyalty", "contribution"):
            value = fields.get(key)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 100
            ):
                raise ValueError(f"{key} phải là số nguyên từ 0 đến 100")
        if "status" in fields and fields["status"] not in {"active", "retired", "expelled", "deceased"}:
            raise ValueError("status không phải trạng thái thành viên được hỗ trợ")

    async def _manage_organization_preview_remove_member(self, arguments: dict[str, Any]):
        row = await self._find_member(arguments.get("member_id"))
        before = _snapshot(row, self.MEMBER_FIELDS | {"id", "organization_id", "character_id"})
        return before, {}, f"Gỡ thành viên tổ chức {row.id[:8]}"

    async def _manage_organization_remove_member(self, arguments: dict[str, Any]):
        row = await self._find_member(arguments.get("member_id"))
        org = (await self.db.execute(select(Organization).where(Organization.id == row.organization_id))).scalar_one()
        entity_id = row.id
        org.member_count = max(0, (org.member_count or 0) - 1)
        await self.db.delete(row)
        return entity_id, {}, "Đã gỡ thành viên tổ chức"

    # --- 伏笔管理 ---

    async def _manage_foreshadow_preview_create(self, arguments: dict[str, Any]):
        fields = self._fields(self._data(arguments), self.FORESHADOW_FIELDS)
        self._validate_foreshadow_fields(fields)
        if not str(fields.get("title") or "").strip() or not str(fields.get("content") or "").strip():
            raise ValueError("Tạo phục bút cần title và content")
        return {}, fields, f"Tạo phục bút«{fields['title']}»"

    async def _manage_foreshadow_create(self, arguments: dict[str, Any]):
        fields = self._fields(self._data(arguments), self.FORESHADOW_FIELDS)
        self._validate_foreshadow_fields(fields)
        row = Foreshadow(project_id=self.project.id, source_type="manual", **fields)
        self.db.add(row)
        await self.db.flush()
        return row.id, row.to_dict(), f"Đã tạo phục bút«{row.title}»"

    async def _manage_foreshadow_preview_update(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        fields = self._fields(self._data(arguments), self.FORESHADOW_FIELDS)
        self._validate_foreshadow_fields(fields)
        return _snapshot(row, set(fields)), fields, f"Cập nhật phục bút«{row.title}»"

    async def _manage_foreshadow_update(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        fields = self._fields(self._data(arguments), self.FORESHADOW_FIELDS)
        self._validate_foreshadow_fields(fields)
        for key, value in fields.items(): setattr(row, key, value)
        return row.id, _snapshot(row, set(fields)), f"Đã cập nhật phục bút«{row.title}»"

    @staticmethod
    def _validate_foreshadow_fields(fields: dict[str, Any]) -> None:
        if "status" in fields and fields["status"] not in {
            "pending", "planted", "resolved", "partially_resolved", "abandoned"
        }:
            raise ValueError("status không phải trạng thái phục bút được hỗ trợ")
        importance = fields.get("importance")
        if importance is not None and (
            isinstance(importance, bool)
            or not isinstance(importance, (int, float))
            or not 0 <= importance <= 1
        ):
            raise ValueError("importance phải nằm trong khoảng 0 đến 1")
        for key in ("strength", "subtlety"):
            value = fields.get(key)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= 10
            ):
                raise ValueError(f"{key} phải là số nguyên từ 1 đến 10")

    async def _manage_foreshadow_preview_delete(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        return row.to_dict(), {}, f"Xóa phục bút«{row.title}»"

    async def _manage_foreshadow_delete(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        entity_id, title = row.id, row.title
        await self.db.delete(row)
        return entity_id, {}, f"Đã xóa phục bút«{title}»"

    async def _manage_foreshadow_preview_plant(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        data = self._data(arguments)
        chapter = await self._find_chapter({"chapter_id": data.get("chapter_id"), "chapter_number": data.get("chapter_number")})
        before = _snapshot(row, {"status", "plant_chapter_id", "plant_chapter_number", "hint_text"})
        after = {"status": "planted", "plant_chapter_id": chapter.id, "plant_chapter_number": chapter.chapter_number, "hint_text": data.get("hint_text", row.hint_text)}
        return before, after, f"Gài cắm phục bút«{row.title}» ở chương {chapter.chapter_number}"

    async def _manage_foreshadow_plant(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        data = self._data(arguments)
        chapter = await self._find_chapter({"chapter_id": data.get("chapter_id"), "chapter_number": data.get("chapter_number")})
        row.status, row.plant_chapter_id, row.plant_chapter_number = "planted", chapter.id, chapter.chapter_number
        row.hint_text, row.planted_at = data.get("hint_text", row.hint_text), datetime.now()
        return row.id, _snapshot(row, {"status", "plant_chapter_id", "plant_chapter_number", "hint_text"}), f"Đã gài cắm phục bút«{row.title}» ở chương {chapter.chapter_number}"

    async def _manage_foreshadow_preview_resolve(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        data = self._data(arguments)
        chapter = await self._find_chapter({"chapter_id": data.get("chapter_id"), "chapter_number": data.get("chapter_number")})
        status = "partially_resolved" if data.get("is_partial") else "resolved"
        before = _snapshot(row, {"status", "actual_resolve_chapter_id", "actual_resolve_chapter_number", "resolution_text"})
        after = {"status": status, "actual_resolve_chapter_id": chapter.id, "actual_resolve_chapter_number": chapter.chapter_number, "resolution_text": data.get("resolution_text", row.resolution_text)}
        return before, after, f"Thu hồi phục bút«{row.title}» ở chương {chapter.chapter_number}"

    async def _manage_foreshadow_resolve(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        data = self._data(arguments)
        chapter = await self._find_chapter({"chapter_id": data.get("chapter_id"), "chapter_number": data.get("chapter_number")})
        row.status = "partially_resolved" if data.get("is_partial") else "resolved"
        row.actual_resolve_chapter_id, row.actual_resolve_chapter_number = chapter.id, chapter.chapter_number
        row.resolution_text, row.resolved_at = data.get("resolution_text", row.resolution_text), datetime.now()
        return row.id, _snapshot(row, {"status", "actual_resolve_chapter_id", "actual_resolve_chapter_number", "resolution_text"}), f"Đã thu hồi phục bút«{row.title}» ở chương {chapter.chapter_number}"

    async def _manage_foreshadow_preview_abandon(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        before = _snapshot(row, {"status", "resolution_notes"})
        after = {"status": "abandoned", "resolution_notes": self._data(arguments).get("reason", row.resolution_notes)}
        return before, after, f"Hủy phục bút«{row.title}»"

    async def _manage_foreshadow_abandon(self, arguments: dict[str, Any]):
        row = await self._find_foreshadow(arguments)
        row.status = "abandoned"
        row.resolution_notes = self._data(arguments).get("reason", row.resolution_notes)
        return row.id, _snapshot(row, {"status", "resolution_notes"}), f"Đã hủy phục bút«{row.title}»"

    # --- 职业管理 ---

    def _career_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        fields = self._fields(data, self.CAREER_FIELDS)
        if "type" in fields and fields["type"] not in {"main", "sub"}:
            raise ValueError("type nghề nghiệp phải là main hoặc sub")
        if "stages" in fields:
            if not isinstance(fields["stages"], list) or not fields["stages"]:
                raise ValueError("stages phải là danh sách không rỗng")
            fields["stages"] = json.dumps(fields["stages"], ensure_ascii=False)
        if "attribute_bonuses" in fields:
            fields["attribute_bonuses"] = json.dumps(fields["attribute_bonuses"], ensure_ascii=False) if fields["attribute_bonuses"] is not None else None
        return fields

    async def _manage_career_preview_create(self, arguments: dict[str, Any]):
        raw = self._data(arguments)
        fields = self._career_fields(raw)
        if not str(fields.get("name") or "").strip() or fields.get("type") not in {"main", "sub"} or "stages" not in fields:
            raise ValueError("Tạo nghề nghiệp cần name, type và stages")
        display = dict(raw)
        return {}, display, f"Tạo nghề nghiệp«{fields['name']}»"

    async def _manage_career_create(self, arguments: dict[str, Any]):
        fields = self._career_fields(self._data(arguments))
        row = Career(project_id=self.project.id, source="manual", **fields)
        self.db.add(row)
        await self.db.flush()
        return row.id, self._career_data(row), f"Đã tạo nghề nghiệp«{row.name}»"

    async def _manage_career_preview_update(self, arguments: dict[str, Any]):
        row = await self._find_career(arguments)
        raw = self._data(arguments)
        fields = self._career_fields(raw)
        before = {key: self._parse_json(getattr(row, key), None) if key in {"stages", "attribute_bonuses"} else _value(getattr(row, key)) for key in fields}
        return before, raw, f"Cập nhật nghề nghiệp«{row.name}»"

    async def _manage_career_update(self, arguments: dict[str, Any]):
        row = await self._find_career(arguments)
        fields = self._career_fields(self._data(arguments))
        for key, value in fields.items(): setattr(row, key, value)
        return row.id, self._career_data(row), f"Đã cập nhật nghề nghiệp«{row.name}»"

    async def _manage_career_preview_delete(self, arguments: dict[str, Any]):
        row = await self._find_career(arguments)
        usage_count = (await self.db.execute(select(func.count(CharacterCareer.id)).where(CharacterCareer.career_id == row.id))).scalar_one()
        if usage_count:
            raise ValueError(f"Nghề này vẫn đang được {usage_count} nhân vật sử dụng, vui lòng gỡ liên kết nghề trước")
        return self._career_data(row), {}, f"Xóa nghề nghiệp«{row.name}»"

    async def _manage_career_delete(self, arguments: dict[str, Any]):
        row = await self._find_career(arguments)
        entity_id, name = row.id, row.name
        await self.db.delete(row)
        return entity_id, {}, f"Đã xóa nghề nghiệp«{name}»"

    async def _prepare_character_career(self, arguments: dict[str, Any], expected_type: str | None = None) -> tuple[Character, Career, dict[str, Any]]:
        character = await self._find_character(arguments)
        career = await self._find_career(arguments)
        data = self._data(arguments)
        if expected_type and career.type != expected_type:
            raise ValueError(f"Nghề này không thuộc loại {expected_type}")
        stage = int(data.get("current_stage", 1))
        if stage < 1 or stage > career.max_stage:
            raise ValueError(f"Giai đoạn nghề phải nằm trong khoảng 1 đến {career.max_stage}")
        progress = data.get("stage_progress", 0)
        if isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100:
            raise ValueError("stage_progress phải là số nguyên từ 0 đến 100")
        return character, career, data

    async def _manage_career_preview_set_main(self, arguments: dict[str, Any]):
        character, career, data = await self._prepare_character_career(arguments, "main")
        current = (await self.db.execute(select(CharacterCareer, Career).join(Career, CharacterCareer.career_id == Career.id).where(CharacterCareer.character_id == character.id, CharacterCareer.career_type == "main"))).one_or_none()
        before = {"career_id": current[0].career_id, "career_name": current[1].name, "current_stage": current[0].current_stage} if current else {}
        after = {"career_id": career.id, "career_name": career.name, "current_stage": int(data.get("current_stage", 1)), "started_at": data.get("started_at")}
        return before, after, f"Đặt nghề chính của nhân vật«{character.name}» thành«{career.name}»"

    async def _manage_career_set_main(self, arguments: dict[str, Any]):
        character, career, data = await self._prepare_character_career(arguments, "main")
        current = (await self.db.execute(select(CharacterCareer).where(CharacterCareer.character_id == character.id, CharacterCareer.career_type == "main"))).scalar_one_or_none()
        if current:
            await self.db.delete(current)
            await self.db.flush()
        row = CharacterCareer(character_id=character.id, career_id=career.id, career_type="main", current_stage=int(data.get("current_stage", 1)), stage_progress=int(data.get("stage_progress", 0)), started_at=data.get("started_at"), reached_current_stage_at=data.get("started_at"), notes=data.get("notes"))
        self.db.add(row)
        character.main_career_id, character.main_career_stage = career.id, row.current_stage
        await self.db.flush()
        return row.id, {"character_id": character.id, "career_id": career.id, "current_stage": row.current_stage}, f"Đã đặt nghề chính của nhân vật«{character.name}» thành«{career.name}»"

    async def _manage_career_preview_add_sub(self, arguments: dict[str, Any]):
        character, career, data = await self._prepare_character_career(arguments, "sub")
        exists = (await self.db.execute(select(CharacterCareer.id).where(CharacterCareer.character_id == character.id, CharacterCareer.career_id == career.id))).scalar_one_or_none()
        if exists:
            raise ValueError("Nhân vật đã sở hữu nghề phụ này")
        after = {"career_id": career.id, "career_name": career.name, "current_stage": int(data.get("current_stage", 1))}
        return {}, after, f"Thêm nghề phụ«{career.name}» cho nhân vật«{character.name}»"

    async def _manage_career_add_sub(self, arguments: dict[str, Any]):
        character, career, data = await self._prepare_character_career(arguments, "sub")
        row = CharacterCareer(character_id=character.id, career_id=career.id, career_type="sub", current_stage=int(data.get("current_stage", 1)), stage_progress=int(data.get("stage_progress", 0)), started_at=data.get("started_at"), reached_current_stage_at=data.get("started_at"), notes=data.get("notes"))
        self.db.add(row)
        await self.db.flush()
        await self._sync_character_sub_careers(character)
        return row.id, {"character_id": character.id, "career_id": career.id, "current_stage": row.current_stage}, f"Đã thêm nghề phụ«{career.name}» cho nhân vật«{character.name}»"

    async def _find_character_career(self, arguments: dict[str, Any]) -> tuple[CharacterCareer, Character, Career]:
        character, career, _ = await self._prepare_character_career(arguments)
        row = (await self.db.execute(select(CharacterCareer).where(CharacterCareer.character_id == character.id, CharacterCareer.career_id == career.id))).scalar_one_or_none()
        if not row:
            raise ValueError("Liên kết nghề nghiệp của nhân vật không tồn tại")
        return row, character, career

    async def _manage_career_preview_update_stage(self, arguments: dict[str, Any]):
        row, character, career = await self._find_character_career(arguments)
        data = self._data(arguments)
        stage = int(data.get("current_stage", row.current_stage))
        if stage < 1 or stage > career.max_stage:
            raise ValueError(f"Giai đoạn nghề phải nằm trong khoảng 1 đến {career.max_stage}")
        before = _snapshot(row, {"current_stage", "stage_progress", "reached_current_stage_at", "notes"})
        after = {"current_stage": stage, "stage_progress": int(data.get("stage_progress", row.stage_progress or 0)), "reached_current_stage_at": data.get("reached_current_stage_at", row.reached_current_stage_at), "notes": data.get("notes", row.notes)}
        return before, after, f"Cập nhật giai đoạn nghề«{career.name}» của nhân vật«{character.name}»"

    async def _manage_career_update_stage(self, arguments: dict[str, Any]):
        row, character, career = await self._find_character_career(arguments)
        data = self._data(arguments)
        row.current_stage = int(data.get("current_stage", row.current_stage))
        row.stage_progress = int(data.get("stage_progress", row.stage_progress or 0))
        row.reached_current_stage_at = data.get("reached_current_stage_at", row.reached_current_stage_at)
        row.notes = data.get("notes", row.notes)
        if row.career_type == "main":
            character.main_career_stage = row.current_stage
        else:
            await self._sync_character_sub_careers(character)
        return row.id, _snapshot(row, {"current_stage", "stage_progress", "reached_current_stage_at", "notes"}), f"Đã cập nhật giai đoạn nghề«{career.name}» của nhân vật«{character.name}»"

    async def _manage_career_preview_remove_sub(self, arguments: dict[str, Any]):
        row, character, career = await self._find_character_career(arguments)
        if row.career_type != "sub":
            raise ValueError("Không thể gỡ nghề chính, chỉ có thể thay đổi")
        return _snapshot(row, {"career_id", "current_stage", "stage_progress"}), {}, f"Gỡ nghề phụ«{career.name}» của nhân vật«{character.name}»"

    async def _manage_career_remove_sub(self, arguments: dict[str, Any]):
        row, character, career = await self._find_character_career(arguments)
        entity_id = row.id
        await self.db.delete(row)
        await self.db.flush()
        await self._sync_character_sub_careers(character)
        return entity_id, {}, f"Đã gỡ nghề phụ«{career.name}» của nhân vật«{character.name}»"

    async def _sync_character_sub_careers(self, character: Character) -> None:
        rows = (await self.db.execute(select(CharacterCareer).where(CharacterCareer.character_id == character.id, CharacterCareer.career_type == "sub"))).scalars().all()
        character.sub_careers = json.dumps([{"career_id": row.career_id, "stage": row.current_stage} for row in rows], ensure_ascii=False)

    @staticmethod
    def _parse_json(value: str | None, fallback: Any) -> Any:
        try:
            return json.loads(value) if value else fallback
        except (json.JSONDecodeError, TypeError):
            return fallback
