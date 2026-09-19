"""章节 → 分镜（storyboard）启发式转换

MVP 不依赖任何付费 API：按句子长度切分章节正文，估算朗读时长，
并基于正文片段生成画面提示词。后续接入图片/视频生成 provider 时，
可直接消费 `StoryboardScene.visual_prompt` 与 `narration`。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from fastapi import HTTPException

from app.config import settings

# 分镜参数：默认值需与分镜时长上限自洽（150 字 / 12.5 字每秒 ≈ 12 秒）
DEFAULT_NARRATION_CHARS = 150
MIN_NARRATION_CHARS = 80
MAX_NARRATION_CHARS = 600
DEFAULT_CHARS_PER_SECOND = 12.5
MAX_SCENES_PER_CHAPTER = 8

_MARKUP_PATTERN = re.compile(r"[*_`>#\[\]]+")
_SENTENCE_PATTERN = re.compile(r"[^.!?。！？…\n]+[.!?。！？…]*")
_VISUAL_STYLE_SUFFIX = (
    "Phong cách minh họa điện ảnh, ánh sáng mềm, bố cục 16:9, không chữ, không watermark."
)


@dataclass
class SourceChapter:
    """分镜输入所需的章节字段"""

    id: str
    chapter_number: int
    title: str
    content: str


@dataclass
class StoryboardScene:
    """单个分镜"""

    scene_index: int
    chapter_id: str
    chapter_number: int
    title: str
    narration: str
    duration_seconds: float
    visual_prompt: str


@dataclass
class StoryboardOptions:
    """分镜生成参数（已由上层校验）"""

    narration_chars_per_scene: int = DEFAULT_NARRATION_CHARS
    chars_per_second: float = DEFAULT_CHARS_PER_SECOND
    resolution: str = field(default_factory=lambda: settings.video_default_resolution)
    fps: int = field(default_factory=lambda: settings.video_default_fps)


def normalize_text(text: str) -> str:
    """去掉 Markdown 标记并压缩空白"""
    cleaned = _MARKUP_PATTERN.sub(" ", text or "")
    cleaned = re.sub(r"[ \t\u3000]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def split_sentences(text: str) -> list[str]:
    """按中英文句末标点切句"""
    return [part.strip() for part in _SENTENCE_PATTERN.findall(text or "") if part.strip()]


def chunk_sentences(sentences: Sequence[str], max_chars: int, min_chars: int) -> list[str]:
    """把句子合并成尽量接近 max_chars 的旁白片段"""
    chunks: list[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if buffer and len(candidate) > max_chars and len(buffer) >= min_chars:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer = candidate
    if buffer:
        chunks.append(buffer)

    # 合并尾部过短片段，避免出现只有一个词的分镜
    if len(chunks) >= 2 and len(chunks[-1]) < min_chars:
        chunks[-2] = f"{chunks[-2]} {chunks[-1]}".strip()
        chunks.pop()
    return chunks


def estimate_duration(narration: str, chars_per_second: float) -> float:
    """按朗读速度估算分镜时长并夹在配置区间内"""
    rate = chars_per_second if chars_per_second > 0 else DEFAULT_CHARS_PER_SECOND
    raw = len(narration) / rate
    clamped = max(settings.video_scene_min_seconds, min(raw, settings.video_scene_max_seconds))
    return round(clamped, 1)


def build_visual_prompt(chapter_title: str, scene_index: int, narration: str) -> str:
    """基于正文片段生成确定性画面提示词（无需 AI 调用）"""
    excerpt = " ".join(narration.split())[:60]
    return (
        f"Cảnh {scene_index + 1} của chương «{chapter_title}»: {excerpt}. "
        f"{_VISUAL_STYLE_SUFFIX}"
    )


def build_storyboard(
    chapters: Iterable[SourceChapter],
    options: StoryboardOptions,
) -> list[StoryboardScene]:
    """把章节列表转换为分镜列表（每个章节至少一个分镜）"""
    max_chars = options.narration_chars_per_scene
    min_chars = min(MIN_NARRATION_CHARS, max_chars)
    scenes: list[StoryboardScene] = []
    scene_index = 0

    for chapter in chapters:
        text = normalize_text(chapter.content)
        sentences = split_sentences(text)
        chunks = chunk_sentences(sentences, max_chars, min_chars) or [text]
        if len(chunks) > MAX_SCENES_PER_CHAPTER:
            # 超出上限时合并剩余片段，保持旁白完整
            merged = " ".join(chunks[MAX_SCENES_PER_CHAPTER - 1:])
            chunks = chunks[: MAX_SCENES_PER_CHAPTER - 1] + [merged]

        for chunk in chunks:
            narration = chunk.strip()
            if not narration:
                continue
            scenes.append(
                StoryboardScene(
                    scene_index=scene_index,
                    chapter_id=chapter.id,
                    chapter_number=chapter.chapter_number,
                    title=chapter.title,
                    narration=narration,
                    duration_seconds=estimate_duration(narration, options.chars_per_second),
                    visual_prompt=build_visual_prompt(chapter.title, scene_index, narration),
                )
            )
            scene_index += 1

    if not scenes:
        raise HTTPException(
            status_code=400,
            detail="Không tạo được phân cảnh nào, vui lòng kiểm tra nội dung chương đã chọn",
        )
    return scenes


def estimate_scene_count(total_chars: int, options: StoryboardOptions) -> int:
    """预算分镜数量，用于在生成前给出明确提示"""
    per_scene = max(options.narration_chars_per_scene, 1)
    return max(1, math.ceil(total_chars / per_scene))


def validate_storyboard_limits(scenes: Sequence[StoryboardScene]) -> float:
    """校验分镜数量与总时长上限，返回总时长"""
    max_scenes = settings.video_max_scenes
    if len(scenes) > max_scenes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cần {len(scenes)} phân cảnh, vượt giới hạn {max_scenes} phân cảnh mỗi tác vụ. "
                "Hãy chọn ít chương hơn hoặc tăng số ký tự mỗi phân cảnh."
            ),
        )

    total_duration = round(sum(scene.duration_seconds for scene in scenes), 1)
    max_duration = settings.video_max_duration_seconds
    if total_duration > max_duration:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tổng thời lượng dự kiến {total_duration:.0f} giây, vượt giới hạn {max_duration} giây mỗi tác vụ. "
                "Hãy chọn ít chương hơn để tiếp tục."
            ),
        )
    return total_duration
