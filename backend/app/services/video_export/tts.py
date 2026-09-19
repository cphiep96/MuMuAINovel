"""TTS 抽象与可选实现

MVP 默认使用 `NullTTSEngine`：不合成音频，成片为合法的静音视频。
如需旁白，可配置 OpenAI 兼容的 `/audio/speech` 接口（例如本地 GPT-SoVITS 网关、
LocalAI、OpenAI 等），密钥只从环境变量读取，任何情况下都不写入代码或日志。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

import httpx

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


class TTSEngine(Protocol):
    """TTS 引擎协议：合成失败不得中断整体导出流程"""

    name: str

    async def synthesize(self, *, text: str, out_path: Path) -> Optional[Path]:
        """合成语音并写入 out_path；返回音频路径，未产生音频时返回 None"""
        ...


class NullTTSEngine:
    """默认引擎：始终返回 None（静音成片）"""

    name = "none"

    async def synthesize(self, *, text: str, out_path: Path) -> Optional[Path]:
        return None


class OpenAICompatibleTTSEngine:
    """OpenAI 兼容 TTS 引擎（POST {base_url}/audio/speech）"""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        voice: str,
        timeout: Optional[int] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.timeout = timeout or settings.video_tts_timeout_seconds

    async def synthesize(self, *, text: str, out_path: Path) -> Optional[Path]:
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "mp3",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/audio/speech",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            content = response.content
        if not content:
            return None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content)
        return out_path


def tts_configured() -> bool:
    """TTS 是否已完整配置（开关 + 地址 + 密钥 + 模型）"""
    return bool(
        settings.video_tts_enabled
        and settings.video_tts_base_url
        and settings.video_tts_api_key
        and settings.video_tts_model
    )


def build_tts_engine() -> TTSEngine:
    """按配置构建 TTS 引擎；未配置时回落到静音引擎"""
    if not tts_configured():
        return NullTTSEngine()
    if settings.video_tts_provider != "openai_compatible":
        logger.warning("未支持的 TTS provider=%s，回落为静音成片", settings.video_tts_provider)
        return NullTTSEngine()
    return OpenAICompatibleTTSEngine(
        base_url=settings.video_tts_base_url or "",
        api_key=settings.video_tts_api_key or "",
        model=settings.video_tts_model or "",
        voice=settings.video_tts_voice,
    )
