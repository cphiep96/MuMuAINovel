"""Shared argument normalization and entity selectors for project-agent tools.

Tool calls can come from different model providers (or be invoked directly by
tests/code), so selectors must not rely solely on the JSON schema being
enforced upstream.  In particular, a whitespace-only ID must not take
precedence over a valid alternate selector such as ``chapter_number``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import Career
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.foreshadow import Foreshadow
from app.models.outline import Outline
from app.models.relationship import Organization


def clean_identifier(value: Any) -> Any:
    """Trim string identifiers and turn empty/whitespace values into ``None``."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def normalize_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a defensive copy with whitespace-only ID fields removed.

    Only top-level fields are normalized: nested ``data`` payloads may contain
    free-form text where trimming would change user intent.
    """
    normalized = dict(arguments)
    for key, value in tuple(normalized.items()):
        if key.endswith("_id") and isinstance(value, str):
            normalized[key] = clean_identifier(value)
    return normalized


def _chapter_number(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("chapter_number phải là số nguyên dương")
    return value


async def find_chapter(
    db: AsyncSession,
    project_id: str,
    arguments: dict[str, Any],
) -> Chapter:
    """Resolve a chapter by ID and/or number within one project.

    An explicitly supplied ID is authoritative.  If both selectors are
    supplied they must identify the same row; silently falling back from a
    missing ID to a number could modify the wrong chapter.
    """
    normalized = normalize_tool_arguments(arguments)
    chapter_id = clean_identifier(normalized.get("chapter_id"))
    chapter_number = _chapter_number(normalized.get("chapter_number"))
    if chapter_id is None and chapter_number is None:
        raise ValueError("Phải cung cấp chapter_id hoặc chapter_number")

    if chapter_id is not None:
        result = await db.execute(
            select(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.id == chapter_id,
            )
        )
        chapter = result.scalar_one_or_none()
        if chapter is None:
            raise ValueError("Không tìm thấy ID chương chỉ định trong dự án hiện tại")
        if chapter_number is not None and chapter.chapter_number != chapter_number:
            raise ValueError("chapter_id và chapter_number trỏ tới chương khác nhau")
        return chapter

    result = await db.execute(
        select(Chapter).where(
            Chapter.project_id == project_id,
            Chapter.chapter_number == chapter_number,
        )
    )
    chapter = result.scalar_one_or_none()
    if chapter is None:
        raise ValueError("Không tìm thấy chương trong dự án hiện tại")
    return chapter


def _positive_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} phải là số nguyên dương")
    return value


async def find_outline(db: AsyncSession, project_id: str, arguments: dict[str, Any]) -> Outline:
    outline_id = clean_identifier(arguments.get("outline_id"))
    order_index = _positive_integer(arguments.get("order_index"), "order_index")
    if outline_id is None and order_index is None:
        raise ValueError("Phải cung cấp outline_id hoặc order_index")
    if outline_id is not None:
        row = (await db.execute(select(Outline).where(
            Outline.project_id == project_id, Outline.id == outline_id
        ))).scalar_one_or_none()
        if row is None:
            raise ValueError("Không tìm thấy ID dàn ý chỉ định trong dự án hiện tại")
        if order_index is not None and row.order_index != order_index:
            raise ValueError("outline_id và order_index trỏ tới dàn ý khác nhau")
        return row
    row = (await db.execute(select(Outline).where(
        Outline.project_id == project_id, Outline.order_index == order_index
    ))).scalar_one_or_none()
    if row is None:
        raise ValueError("Không tìm thấy dàn ý chỉ định trong dự án hiện tại")
    return row


async def find_character(db: AsyncSession, project_id: str, arguments: dict[str, Any]) -> Character:
    character_id = clean_identifier(arguments.get("character_id"))
    character_name = clean_identifier(arguments.get("character_name") or arguments.get("name"))
    if character_id is None and character_name is None:
        raise ValueError("Phải cung cấp character_id hoặc character_name")
    if character_id is not None:
        row = (await db.execute(select(Character).where(
            Character.project_id == project_id, Character.id == character_id
        ))).scalar_one_or_none()
        if row is None:
            raise ValueError("Không tìm thấy ID nhân vật chỉ định trong dự án hiện tại")
        if character_name is not None and row.name != character_name:
            raise ValueError("character_id và character_name trỏ tới nhân vật khác nhau")
        return row
    row = (await db.execute(select(Character).where(
        Character.project_id == project_id, Character.name == character_name
    ))).scalar_one_or_none()
    if row is None:
        raise ValueError("Không tìm thấy nhân vật chỉ định trong dự án hiện tại")
    return row


async def find_organization(db: AsyncSession, project_id: str, arguments: dict[str, Any]) -> tuple[Organization, Character]:
    organization_id = clean_identifier(arguments.get("organization_id"))
    name = clean_identifier(arguments.get("name"))
    if organization_id is None and name is None:
        raise ValueError("Phải cung cấp organization_id hoặc name")
    query = select(Organization, Character).join(
        Character, Organization.character_id == Character.id
    ).where(Organization.project_id == project_id)
    if organization_id is not None:
        row = (await db.execute(query.where(Organization.id == organization_id))).one_or_none()
        if row is None:
            raise ValueError("Không tìm thấy ID tổ chức chỉ định trong dự án hiện tại")
        if name is not None and row[1].name != name:
            raise ValueError("organization_id và name trỏ tới tổ chức khác nhau")
        return row
    row = (await db.execute(query.where(Character.name == name))).one_or_none()
    if row is None:
        raise ValueError("Không tìm thấy tổ chức trong dự án hiện tại")
    return row


async def find_career(db: AsyncSession, project_id: str, arguments: dict[str, Any]) -> Career:
    career_id = clean_identifier(arguments.get("career_id"))
    name = clean_identifier(arguments.get("name"))
    if career_id is None and name is None:
        raise ValueError("Phải cung cấp career_id hoặc name")
    if career_id is not None:
        row = (await db.execute(select(Career).where(
            Career.project_id == project_id, Career.id == career_id
        ))).scalar_one_or_none()
        if row is None:
            raise ValueError("Không tìm thấy ID nghề chỉ định trong dự án hiện tại")
        if name is not None and row.name != name:
            raise ValueError("career_id và name trỏ tới nghề khác nhau")
        return row
    row = (await db.execute(select(Career).where(
        Career.project_id == project_id, Career.name == name
    ))).scalar_one_or_none()
    if row is None:
        raise ValueError("Không tìm thấy nghề nghiệp trong dự án hiện tại")
    return row


async def find_foreshadow(db: AsyncSession, project_id: str, arguments: dict[str, Any]) -> Foreshadow:
    foreshadow_id = clean_identifier(arguments.get("foreshadow_id"))
    title = clean_identifier(arguments.get("title"))
    if foreshadow_id is None and title is None:
        raise ValueError("Phải cung cấp foreshadow_id hoặc title")
    if foreshadow_id is not None:
        row = (await db.execute(select(Foreshadow).where(
            Foreshadow.project_id == project_id, Foreshadow.id == foreshadow_id
        ))).scalar_one_or_none()
        if row is None:
            raise ValueError("Không tìm thấy ID phục bút chỉ định trong dự án hiện tại")
        if title is not None and row.title != title:
            raise ValueError("foreshadow_id và title trỏ tới phục bút khác nhau")
        return row
    row = (await db.execute(select(Foreshadow).where(
        Foreshadow.project_id == project_id, Foreshadow.title == title
    ))).scalar_one_or_none()
    if row is None:
        raise ValueError("Không tìm thấy phục bút trong dự án hiện tại")
    return row
