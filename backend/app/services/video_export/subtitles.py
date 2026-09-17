"""SRT 字幕生成

按分镜时长顺序累加时间轴，输出标准 SubRip 文本。
时间轴保证严格递增且每段时长不小于 `MIN_CUE_SECONDS`，避免播放器解析异常。
"""
from __future__ import annotations

from typing import Sequence

MIN_CUE_SECONDS = 0.5

__all__ = ["format_timestamp", "build_srt", "build_srt_from_scenes", "MIN_CUE_SECONDS"]


def format_timestamp(seconds: float) -> str:
    """秒 → SRT 时间戳 `HH:MM:SS,mmm`"""
    total_ms = int(round(max(seconds, 0.0) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _sanitize_text(text: str) -> str:
    """字幕正文清理：去掉控制符与首尾空白，保留换行外的空格"""
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(ch for ch in cleaned if ch == "\n" or ch >= " ")
    return cleaned.strip()


def build_srt(cues: Sequence[tuple[str, float]]) -> str:
    """由 (文本, 时长秒) 序列生成 SRT 内容"""
    blocks: list[str] = []
    cursor = 0.0
    index = 1

    for text, duration in cues:
        body = _sanitize_text(text)
        if not body:
            continue
        length = max(float(duration or 0.0), MIN_CUE_SECONDS)
        start = cursor
        end = start + length
        blocks.append(
            f"{index}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{body}\n"
        )
        cursor = end
        index += 1

    return "\n".join(blocks)


def build_srt_from_scenes(scenes: Sequence[object]) -> str:
    """由分镜对象（含 narration/duration_seconds）生成 SRT 内容

    远端 provider 返回的片段时长通常与旁白估算时长不同，
    因此优先使用实际片段时长 `clip_duration_seconds`，保证字幕与画面同步。
    """
    cues: list[tuple[str, float]] = []
    for scene in scenes:
        duration = getattr(scene, "clip_duration_seconds", None) or getattr(
            scene, "duration_seconds", 0.0
        )
        cues.append((getattr(scene, "narration", "") or "", float(duration or 0.0)))
    return build_srt(cues)
