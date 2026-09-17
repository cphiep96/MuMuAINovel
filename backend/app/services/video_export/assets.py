"""分镜画面来源解析

安全策略：只允许使用服务端已受管的素材
1. 任务目录内的分镜图片（`<job_dir>/assets/scene_000.png` 等），便于后续接入图片生成流程
2. 项目封面（已完成生成且文件存在）
3. 都没有时返回 None，由 FFmpeg 生成占位背景，保证成片仍然有效

客户端永远不会传来文件路径，因此不存在任意路径读取。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.logger import get_logger
from app.services.cover_generation_service import resolve_cover_file_path

logger = get_logger(__name__)

ALLOWED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

# 远端 provider 需要 MIME 类型（不依赖客户端的文件名/声明）
MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

ASSET_KIND_SCENE_IMAGE = "image"
ASSET_KIND_COVER = "cover"
ASSET_KIND_PLACEHOLDER = "placeholder"


@dataclass
class SceneAsset:
    """单个分镜的画面来源"""

    path: Optional[Path]
    kind: str

    @property
    def is_placeholder(self) -> bool:
        return self.path is None

    @property
    def mime_type(self) -> str:
        return guess_image_mime(self.path) if self.path is not None else ""


def guess_image_mime(path: Path) -> str:
    """按扩展名推断图片 MIME（后缀来自服务端受管目录，不接受客户端输入）"""
    return MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")


def find_scene_image(assets_dir: Path, scene_index: int) -> Optional[Path]:
    """查找外部放入任务目录的分镜图片（扩展点：可对接任意图片 provider）"""
    for suffix in ALLOWED_IMAGE_SUFFIXES:
        candidate = assets_dir / f"scene_{scene_index:03d}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def resolve_cover_image(cover_image_url: Optional[str], cover_status: Optional[str]) -> Optional[Path]:
    """解析项目封面路径，不可用时返回 None（不抛错，交由占位背景兜底）"""
    if cover_status != "ready" or not cover_image_url:
        return None
    try:
        path = resolve_cover_file_path(cover_image_url)
    except Exception as exc:  # noqa: BLE001 - 封面不可用不应阻断导出
        logger.warning("封面素材不可用，改用占位背景: %s", exc)
        return None
    return path if path.is_file() else None


def resolve_scene_asset(
    *,
    assets_dir: Path,
    scene_index: int,
    cover_path: Optional[Path],
    use_project_cover: bool,
) -> SceneAsset:
    """按优先级解析分镜画面来源"""
    scene_image = find_scene_image(assets_dir, scene_index)
    if scene_image is not None:
        return SceneAsset(path=scene_image, kind=ASSET_KIND_SCENE_IMAGE)
    if use_project_cover and cover_path is not None:
        return SceneAsset(path=cover_path, kind=ASSET_KIND_COVER)
    return SceneAsset(path=None, kind=ASSET_KIND_PLACEHOLDER)
