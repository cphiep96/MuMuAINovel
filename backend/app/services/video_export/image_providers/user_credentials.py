"""Lấy cấu hình Muse từ trang Cài đặt (không lộ key ra response).

Ảnh phân cảnh / PDF dùng chung key với Provider ảnh bìa khi người dùng
chọn Meta Muse Image 1.0. Env META_MUSE_API_KEY vẫn là fallback máy chủ.
"""
from __future__ import annotations

from typing import Any

MUSE_COVER_PROVIDERS = {"meta_muse", "meta_muse_image"}


def image_provider_kwargs_from_settings(user_settings: Any) -> dict[str, str]:
    """Trả kwargs cho MetaMuseImageProvider từ Settings của user.

    Không trả gì nếu chưa chọn Muse hoặc chưa có API key — caller sẽ
    fallback sang biến môi trường.
    """
    if user_settings is None:
        return {}
    provider = str(getattr(user_settings, "cover_api_provider", "") or "").strip().lower()
    if provider not in MUSE_COVER_PROVIDERS:
        return {}
    api_key = str(getattr(user_settings, "cover_api_key", "") or "").strip()
    if not api_key:
        return {}
    kwargs: dict[str, str] = {"api_key": api_key}
    base_url = str(getattr(user_settings, "cover_api_base_url", "") or "").strip()
    if base_url:
        kwargs["base_url"] = base_url
    model = str(getattr(user_settings, "cover_image_model", "") or "").strip()
    if model:
        kwargs["model"] = model
    return kwargs


def missing_muse_config_hint() -> str:
    return (
        "Cấu hình Meta Muse ở trang Cài đặt → Cấu hình mô hình ảnh "
        "(Provider ảnh bìa = Meta Muse Image 1.0, nhập API Key rồi Lưu), "
        "hoặc đặt biến môi trường META_MUSE_API_KEY trên máy chủ."
    )


__all__ = [
    "MUSE_COVER_PROVIDERS",
    "image_provider_kwargs_from_settings",
    "missing_muse_config_hint",
]
