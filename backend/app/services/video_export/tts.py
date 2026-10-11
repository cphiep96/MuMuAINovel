"""TTS cho xuất video: OmniVoice (k2-fsa), Deepgram Speak, OpenAI-compatible.

Mặc định là `NullTTSEngine` (video im lặng). Deepgram Flux/Aura hiện chỉ có
giọng tiếng Anh (`-en`) nên đọc chữ Việt theo ngữ âm English. Truyện tiếng
Việt dùng OmniVoice local (https://github.com/k2-fsa/OmniVoice), 600+ ngôn ngữ.
Key Deepgram/OpenAI không bao giờ ghi log hay trả về API.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import threading
import wave
from pathlib import Path
from typing import Any, Optional, Protocol
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.security import validate_ai_http_url
from app.logger import get_logger

logger = get_logger(__name__)

OMNIVOICE_PROVIDER = "omnivoice"
# Cài đặt cũ từng dùng Microsoft Edge; map sang OmniVoice, không còn gọi Edge.
EDGE_PROVIDER = OMNIVOICE_PROVIDER
DEEPGRAM_PROVIDER = "deepgram"
OPENAI_PROVIDER = "openai_compatible"
TTS_PROVIDERS = (OMNIVOICE_PROVIDER, DEEPGRAM_PROVIDER, OPENAI_PROVIDER)

DEFAULT_DEEPGRAM_BASE_URL = "https://api.deepgram.com"
DEFAULT_DEEPGRAM_MODEL = "flux-hannah-en"
DEFAULT_OMNIVOICE_MODEL = "female"
DEFAULT_EDGE_MODEL = DEFAULT_OMNIVOICE_MODEL
OMNIVOICE_SAMPLE_RATE = 24000
OMNIVOICE_HF_ID = "k2-fsa/OmniVoice"

# Chữ Việt có dấu — đủ để phân biệt với Latin không dấu / English.
_VIETNAMESE_RE = re.compile(
    r"[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
    re.IGNORECASE,
)

# Flux voices dùng cho kể chuyện / narration. Model string = flux-{voice}-en.
DEEPGRAM_FLUX_MODELS: tuple[tuple[str, str], ...] = (
    ("flux-hannah-en", "Hannah · Mỹ · kể chuyện"),
    ("flux-kit-en", "Kit · Anh · kể chuyện"),
    ("flux-alexis-en", "Alexis · Mỹ · chuyên nghiệp"),
    ("flux-cliff-en", "Cliff · Mỹ · trầm, tự tin"),
    ("flux-sienna-en", "Sienna · Mỹ · ấm"),
    ("flux-cole-en", "Cole · Mỹ · năng lượng"),
    ("flux-brooke-en", "Brooke · Mỹ · tự tin"),
    ("flux-colin-en", "Colin · Anh · đáng tin"),
    ("flux-gemma-en", "Gemma · Anh · thân thiện"),
    ("flux-haley-en", "Haley · Mỹ · điềm tĩnh"),
    ("flux-heather-en", "Heather · Mỹ · lôi cuốn"),
    ("flux-miles-en", "Miles · Mỹ · chân thành"),
    ("flux-sean-en", "Sean · Anh · dịu dàng"),
    ("flux-jack-en", "Jack · Anh · kể chuyện"),
    ("flux-rufus-en", "Rufus · Anh · kể chuyện"),
    ("flux-maeve-en", "Maeve · Ireland · kể chuyện"),
)

DEEPGRAM_FLUX_MODEL_IDS = {item[0] for item in DEEPGRAM_FLUX_MODELS}

OMNIVOICE_VOICES: tuple[tuple[str, str], ...] = (
    ("female", "Nữ · kể chuyện"),
    ("male", "Nam · kể chuyện"),
    ("auto", "Tự chọn giọng"),
)
OMNIVOICE_MODEL_IDS = {item[0] for item in OMNIVOICE_VOICES}
OMNIVOICE_INSTRUCT = {
    "female": "female, young adult, moderate pitch",
    "male": "male, young adult, low pitch",
    "auto": None,
}
_LEGACY_VOICE_MAP = {
    "vi-vn-hoaimyneural": "female",
    "vi-vn-namminhneural": "male",
    "hoaimy": "female",
    "namminh": "male",
    "edge": "female",
}
EDGE_MODELS = OMNIVOICE_VOICES
EDGE_MODEL_IDS = OMNIVOICE_MODEL_IDS

_omnivoice_model = None
_omnivoice_lock = threading.Lock()


class TTSEngine(Protocol):
    """TTS engine protocol: lỗi tổng hợp không được làm hỏng toàn bộ xuất video."""

    name: str

    async def synthesize(self, *, text: str, out_path: Path) -> Optional[Path]:
        """Tổng hợp giọng nói và ghi ra out_path; không có audio thì trả None."""
        ...


class NullTTSEngine:
    name = "none"

    async def synthesize(self, *, text: str, out_path: Path) -> Optional[Path]:
        return None


class OmniVoiceTTSEngine:
    """k2-fsa OmniVoice: TTS đa ngôn ngữ local, đọc được tiếng Việt."""

    name = OMNIVOICE_PROVIDER

    def __init__(self, *, model: str, timeout: Optional[int] = None) -> None:
        self.model = normalize_omnivoice_voice(model)
        self.timeout = timeout or max(int(settings.video_tts_timeout_seconds), 600)
        self._narrator_prompt = None
        self._narrator_lock = threading.Lock()

    async def synthesize(self, *, text: str, out_path: Path) -> Optional[Path]:
        clean = (text or "").strip()
        if not clean:
            return None
        if not omnivoice_available():
            raise RuntimeError(
                "Chưa cài OmniVoice. Chạy: pip install torch torchaudio omnivoice"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        samples = await asyncio.wait_for(
            asyncio.to_thread(self._generate_sync, clean),
            timeout=self.timeout,
        )
        if samples is None or len(samples) == 0:
            return None
        return _write_tts_audio(samples, out_path, OMNIVOICE_SAMPLE_RATE)

    def _generate_sync(self, text: str):
        model = _load_omnivoice_model()
        kwargs: dict[str, Any] = {
            "text": text,
            "speed": _clamp_speed(settings.video_tts_speed),
            "num_step": max(8, int(settings.video_tts_omnivoice_num_step or 16)),
        }
        if looks_like_vietnamese(text):
            kwargs["language"] = "vi"
        instruct = OMNIVOICE_INSTRUCT.get(self.model)
        with self._narrator_lock:
            if self._narrator_prompt is not None:
                kwargs["voice_clone_prompt"] = self._narrator_prompt
            elif instruct:
                kwargs["instruct"] = instruct
            audio = model.generate(**kwargs)
            samples = audio[0] if isinstance(audio, list) and audio else audio
            if self._narrator_prompt is None and samples is not None and len(samples):
                # Anchor subsequent scenes to our first synthetic voice, never to a real person.
                self._narrator_prompt = model.create_voice_clone_prompt(
                    ref_audio=(samples, OMNIVOICE_SAMPLE_RATE), ref_text=text, preprocess_prompt=False
                )
            return samples


EdgeTTSEngine = OmniVoiceTTSEngine


class OpenAICompatibleTTSEngine:
    """OpenAI-compatible TTS (POST {base_url}/audio/speech)."""

    name = OPENAI_PROVIDER

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
        clean = (text or "").strip()
        if not clean:
            return None
        payload = {
            "model": self.model,
            "input": clean,
            "voice": self.voice,
            "response_format": "mp3",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{validate_ai_http_url(self.base_url)}/audio/speech",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            content = response.content
        return _write_audio(out_path, content)


class DeepgramTTSEngine:
    """Deepgram Speak: Flux trên /v2/speak, Aura trên /v1/speak."""

    name = DEEPGRAM_PROVIDER

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        speed: Optional[float] = None,
        expressivity: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_DEEPGRAM_MODEL
        self.base_url = (base_url or DEFAULT_DEEPGRAM_BASE_URL).rstrip("/")
        self.speed = _clamp_speed(speed)
        self.expressivity = _clamp_expressivity(expressivity)
        self.timeout = timeout or settings.video_tts_timeout_seconds

    def speak_url(self) -> str:
        return build_deepgram_speak_url(
            self.base_url,
            model=self.model,
            speed=self.speed,
            expressivity=self.expressivity,
        )

    async def synthesize(self, *, text: str, out_path: Path) -> Optional[Path]:
        clean = (text or "").strip()
        if not clean:
            return None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                build_deepgram_speak_url(
                    validate_ai_http_url(self.base_url),
                    model=self.model,
                    speed=self.speed,
                    expressivity=self.expressivity,
                ),
                json={"text": clean},
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            content = response.content
        return _write_audio(out_path, content)


def build_deepgram_speak_url(
    base_url: str,
    *,
    model: str,
    speed: float = 1.0,
    expressivity: int = 0,
) -> str:
    """Flux phải đi /v2/speak; Aura giữ /v1/speak."""
    root = (base_url or DEFAULT_DEEPGRAM_BASE_URL).rstrip("/")
    query: dict[str, Any] = {"model": model or DEFAULT_DEEPGRAM_MODEL, "encoding": "mp3"}
    if str(model or "").startswith("flux-"):
        query["speed"] = _clamp_speed(speed)
        query["expressivity"] = _clamp_expressivity(expressivity)
        return f"{root}/v2/speak?{urlencode(query)}"
    return f"{root}/v1/speak?{urlencode(query)}"


def _write_audio(out_path: Path, content: bytes) -> Optional[Path]:
    if not content:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    return out_path


def _clamp_speed(value: Optional[float]) -> float:
    try:
        speed = float(value if value is not None else settings.video_tts_speed)
    except (TypeError, ValueError):
        speed = 1.0
    return max(0.5, min(speed, 1.5))


def _clamp_expressivity(value: Optional[int]) -> int:
    try:
        expressivity = int(value if value is not None else settings.video_tts_expressivity)
    except (TypeError, ValueError):
        expressivity = 0
    return max(-2, min(expressivity, 2))


def _clean(value: Any) -> str:
    return str(value or "").strip()


def looks_like_vietnamese(text: str) -> bool:
    return bool(_VIETNAMESE_RE.search(text or ""))


def is_english_only_tts_model(model: Optional[str]) -> bool:
    name = _clean(model).lower()
    if not name:
        return False
    return name.startswith("flux-") or name.endswith("-en") or name in DEEPGRAM_FLUX_MODEL_IDS


def _normalize_provider(name: Optional[str]) -> str:
    raw = _clean(name).lower()
    if raw in {"edge", "microsoft", "edge_tts"}:
        return OMNIVOICE_PROVIDER
    return raw


def normalize_omnivoice_voice(model: Optional[str]) -> str:
    raw = _clean(model).lower()
    mapped = _LEGACY_VOICE_MAP.get(raw, raw)
    if mapped in OMNIVOICE_MODEL_IDS:
        return mapped
    return DEFAULT_OMNIVOICE_MODEL


def omnivoice_available() -> bool:
    try:
        import omnivoice  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


edge_tts_available = omnivoice_available


def _omnivoice_device() -> str:
    configured = _clean(getattr(settings, "video_tts_omnivoice_device", None))
    if configured:
        return configured
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda:0"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def _load_omnivoice_model():
    global _omnivoice_model
    if _omnivoice_model is not None:
        return _omnivoice_model
    with _omnivoice_lock:
        if _omnivoice_model is not None:
            return _omnivoice_model
        import torch
        from omnivoice import OmniVoice

        device = _omnivoice_device()
        dtype = torch.float32 if device == "cpu" else torch.float16
        model_id = _clean(settings.video_tts_omnivoice_model_id) or OMNIVOICE_HF_ID
        logger.info("Đang tải OmniVoice model=%s device=%s dtype=%s", model_id, device, dtype)
        _omnivoice_model = OmniVoice.from_pretrained(
            model_id,
            device_map=device,
            dtype=dtype,
            load_asr=False,
        )
        logger.info("Đã tải OmniVoice")
        return _omnivoice_model


def _write_wav(path: Path, samples: Any, sample_rate: int) -> None:
    import numpy as np

    if hasattr(samples, "detach"):
        samples = samples.detach().cpu().numpy()
    pcm = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = np.clip(pcm, -1.0, 1.0)
    int16 = (pcm * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(int16.tobytes())


def _write_tts_audio(samples: Any, out_path: Path, sample_rate: int) -> Optional[Path]:
    wav_path = out_path if out_path.suffix.lower() == ".wav" else out_path.with_suffix(".wav")
    _write_wav(wav_path, samples, sample_rate)
    if out_path.suffix.lower() in {"", ".wav"}:
        return wav_path if wav_path.is_file() and wav_path.stat().st_size > 32 else None
    from app.services.video_export.ffmpeg_runner import ffmpeg_binary

    binary = ffmpeg_binary()
    if not binary:
        return wav_path
    try:
        subprocess.run(
            [binary, "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "4", str(out_path)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("Không chuyển được WAV sang MP3, dùng WAV: %s", exc)
        return wav_path
    return out_path if out_path.is_file() and out_path.stat().st_size > 32 else wav_path


def _omnivoice_config() -> Optional[dict[str, Any]]:
    if not omnivoice_available():
        return None
    return {
        "provider": OMNIVOICE_PROVIDER,
        "api_key": "",
        "base_url": "",
        "model": DEFAULT_OMNIVOICE_MODEL,
        "voice": DEFAULT_OMNIVOICE_MODEL,
        "source": "omnivoice",
    }


_edge_config = _omnivoice_config


def prefer_native_language_engine(
    engine: TTSEngine, sample_text: str
) -> tuple[TTSEngine, bool]:
    """Deepgram Flux/Aura -en đọc chữ Việt theo âm English. Đổi sang OmniVoice."""
    if engine.name == OMNIVOICE_PROVIDER or not looks_like_vietnamese(sample_text):
        return engine, False
    model = _clean(getattr(engine, "model", ""))
    english_only = engine.name == DEEPGRAM_PROVIDER or is_english_only_tts_model(model)
    if not english_only:
        return engine, False
    if not omnivoice_available():
        logger.warning(
            "Lời thoại tiếng Việt nhưng OmniVoice chưa được cài; Deepgram vẫn đọc theo tiếng Anh"
        )
        return engine, False
    logger.warning(
        "Model TTS %s chỉ tiếng Anh; chuyển sang OmniVoice %s",
        model or engine.name,
        DEFAULT_OMNIVOICE_MODEL,
    )
    return OmniVoiceTTSEngine(model=DEFAULT_OMNIVOICE_MODEL), True


def resolve_tts_config(
    user_settings: Any = None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Ưu tiên Cài đặt của user, sau đó mới tới biến môi trường máy chủ."""
    user_cfg = _config_from_user_settings(user_settings)
    env_cfg = _config_from_env()
    chosen = user_cfg or env_cfg or _omnivoice_config()
    if chosen is None:
        return None
    override_provider = _normalize_provider(provider)
    if override_provider:
        if override_provider not in TTS_PROVIDERS:
            return None
        chosen = dict(chosen)
        chosen["provider"] = override_provider
        if override_provider == DEEPGRAM_PROVIDER:
            chosen.setdefault("base_url", DEFAULT_DEEPGRAM_BASE_URL)
            chosen.setdefault("model", DEFAULT_DEEPGRAM_MODEL)
        elif override_provider == OMNIVOICE_PROVIDER:
            chosen["api_key"] = chosen.get("api_key") or ""
            chosen.setdefault("model", DEFAULT_OMNIVOICE_MODEL)
    override_model = _clean(model)
    if override_model:
        chosen = dict(chosen)
        chosen["model"] = override_model
    if chosen["provider"] == OMNIVOICE_PROVIDER:
        if not omnivoice_available():
            return None
        chosen["model"] = normalize_omnivoice_voice(chosen.get("model"))
        return chosen
    if chosen["provider"] == DEEPGRAM_PROVIDER:
        if not chosen.get("api_key"):
            return None
        chosen.setdefault("base_url", DEFAULT_DEEPGRAM_BASE_URL)
        chosen.setdefault("model", DEFAULT_DEEPGRAM_MODEL)
        return chosen
    if chosen["provider"] == OPENAI_PROVIDER:
        if not (chosen.get("api_key") and chosen.get("base_url") and chosen.get("model")):
            return None
        return chosen
    return None


def _config_from_user_settings(user_settings: Any) -> Optional[dict[str, Any]]:
    if user_settings is None:
        return None
    enabled = getattr(user_settings, "tts_enabled", None)
    if enabled is None or enabled in (False, 0, "0"):
        return None
    provider = _normalize_provider(getattr(user_settings, "tts_api_provider", "")) or OMNIVOICE_PROVIDER
    if provider not in TTS_PROVIDERS:
        return None
    if provider == OMNIVOICE_PROVIDER:
        voice = normalize_omnivoice_voice(getattr(user_settings, "tts_model", ""))
        return {
            "provider": OMNIVOICE_PROVIDER,
            "api_key": "",
            "base_url": "",
            "model": voice,
            "voice": voice,
            "source": "user",
        }
    api_key = _clean(getattr(user_settings, "tts_api_key", ""))
    if not api_key:
        return None
    cfg: dict[str, Any] = {
        "provider": provider,
        "api_key": api_key,
        "base_url": _clean(getattr(user_settings, "tts_api_base_url", ""))
        or (DEFAULT_DEEPGRAM_BASE_URL if provider == DEEPGRAM_PROVIDER else ""),
        "model": _clean(getattr(user_settings, "tts_model", ""))
        or (DEFAULT_DEEPGRAM_MODEL if provider == DEEPGRAM_PROVIDER else ""),
        "voice": _clean(getattr(user_settings, "tts_voice", "")) or settings.video_tts_voice,
        "source": "user",
    }
    return cfg


def _config_from_env() -> Optional[dict[str, Any]]:
    provider = _normalize_provider(settings.video_tts_provider)
    if provider == OMNIVOICE_PROVIDER or (not settings.video_tts_enabled and not _clean(settings.video_tts_api_key)):
        return _omnivoice_config()
    if not settings.video_tts_enabled:
        return None
    api_key = _clean(settings.video_tts_api_key)
    if not api_key:
        return _omnivoice_config()
    if provider not in TTS_PROVIDERS:
        provider = DEEPGRAM_PROVIDER
    if provider == OMNIVOICE_PROVIDER:
        return _omnivoice_config()
    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": _clean(settings.video_tts_base_url)
        or (DEFAULT_DEEPGRAM_BASE_URL if provider == DEEPGRAM_PROVIDER else ""),
        "model": _clean(settings.video_tts_model)
        or (DEFAULT_DEEPGRAM_MODEL if provider == DEEPGRAM_PROVIDER else ""),
        "voice": _clean(settings.video_tts_voice) or "alloy",
        "source": "env",
    }


def tts_configured(user_settings: Any = None) -> bool:
    return resolve_tts_config(user_settings) is not None


def missing_tts_config_hint() -> str:
    if omnivoice_available():
        return (
            "Chọn OmniVoice (Nữ / Nam) khi xuất phim tiếng Việt. "
            "Deepgram Flux chỉ đọc tiếng Anh."
        )
    return (
        "Cài OmniVoice để đọc tiếng Việt: pip install torch torchaudio omnivoice. "
        "Xem https://github.com/k2-fsa/OmniVoice"
    )


def build_tts_engine(
    user_settings: Any = None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> TTSEngine:
    cfg = resolve_tts_config(user_settings, provider=provider, model=model)
    if cfg is None:
        return NullTTSEngine()
    if cfg["provider"] == OMNIVOICE_PROVIDER:
        return OmniVoiceTTSEngine(model=cfg.get("model") or DEFAULT_OMNIVOICE_MODEL)
    if cfg["provider"] == DEEPGRAM_PROVIDER:
        return DeepgramTTSEngine(
            api_key=cfg["api_key"],
            model=cfg.get("model") or DEFAULT_DEEPGRAM_MODEL,
            base_url=cfg.get("base_url") or DEFAULT_DEEPGRAM_BASE_URL,
        )
    if cfg["provider"] == OPENAI_PROVIDER:
        return OpenAICompatibleTTSEngine(
            base_url=cfg.get("base_url") or "",
            api_key=cfg["api_key"],
            model=cfg.get("model") or "",
            voice=cfg.get("voice") or settings.video_tts_voice,
        )
    logger.warning("TTS provider không hỗ trợ=%s, video sẽ im lặng", cfg.get("provider"))
    return NullTTSEngine()


def list_tts_provider_capabilities(user_settings: Any = None) -> list[dict[str, Any]]:
    omnivoice_ready = omnivoice_available()
    deepgram_ready = resolve_tts_config(user_settings, provider=DEEPGRAM_PROVIDER) is not None
    openai_ready = resolve_tts_config(user_settings, provider=OPENAI_PROVIDER) is not None
    openai_cfg = resolve_tts_config(user_settings, provider=OPENAI_PROVIDER) if openai_ready else None
    return [
        {
            "id": OMNIVOICE_PROVIDER,
            "label": "OmniVoice (k2-fsa)",
            "kind": "tts",
            "description": "TTS local 600+ ngôn ngữ, đọc tiếng Việt. Không dùng Microsoft Edge.",
            "configured": omnivoice_ready,
            "missing_config": [] if omnivoice_ready else ["pip install torch torchaudio omnivoice"],
            "models": [item[0] for item in OMNIVOICE_VOICES],
            "model_labels": {item[0]: item[1] for item in OMNIVOICE_VOICES},
            "default_model": DEFAULT_OMNIVOICE_MODEL,
            "languages": ["vi", "en"],
        },
        {
            "id": DEEPGRAM_PROVIDER,
            "label": "Deepgram Flux (chỉ tiếng Anh)",
            "kind": "tts",
            "description": "Giọng Flux tiếng Anh. Đọc chữ Việt theo ngữ âm English, không dùng cho truyện Việt.",
            "configured": deepgram_ready,
            "missing_config": [] if deepgram_ready else ["TTS API Key (Cài đặt hoặc VIDEO_TTS_API_KEY)"],
            "models": [item[0] for item in DEEPGRAM_FLUX_MODELS],
            "model_labels": {item[0]: item[1] for item in DEEPGRAM_FLUX_MODELS},
            "default_model": DEFAULT_DEEPGRAM_MODEL,
            "languages": ["en"],
        },
        {
            "id": OPENAI_PROVIDER,
            "label": "OpenAI Compatible",
            "kind": "tts",
            "description": "Cổng /audio/speech tương thích OpenAI. Một số model đọc được tiếng Việt.",
            "configured": openai_ready,
            "missing_config": [] if openai_ready else ["VIDEO_TTS_BASE_URL", "VIDEO_TTS_API_KEY", "VIDEO_TTS_MODEL"],
            "models": [openai_cfg["model"]] if openai_cfg and openai_cfg.get("model") else [],
            "default_model": (openai_cfg or {}).get("model") or "",
            "languages": ["en", "vi"],
        },
    ]


def default_tts_provider_name(user_settings: Any = None) -> str:
    if omnivoice_available():
        return OMNIVOICE_PROVIDER
    cfg = resolve_tts_config(user_settings)
    if cfg:
        return str(cfg["provider"])
    return DEEPGRAM_PROVIDER


def default_tts_model(user_settings: Any = None) -> str:
    if omnivoice_available():
        cfg = resolve_tts_config(user_settings, provider=OMNIVOICE_PROVIDER)
        if cfg and cfg.get("model") in OMNIVOICE_MODEL_IDS:
            return str(cfg["model"])
        return DEFAULT_OMNIVOICE_MODEL
    cfg = resolve_tts_config(user_settings)
    if cfg and cfg.get("model"):
        return str(cfg["model"])
    return DEFAULT_DEEPGRAM_MODEL


async def test_tts_settings(
    *,
    provider: str,
    api_key: str,
    api_base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Gọi TTS với câu ngắn để xác nhận key; không lưu file."""
    name = _normalize_provider(provider) or OMNIVOICE_PROVIDER
    key = _clean(api_key)
    chosen_model = _clean(model) or (
        DEFAULT_OMNIVOICE_MODEL
        if name == OMNIVOICE_PROVIDER
        else DEFAULT_DEEPGRAM_MODEL
        if name == DEEPGRAM_PROVIDER
        else ""
    )
    sample = "This is a short narration test for video export."
    if name == OMNIVOICE_PROVIDER:
        if not omnivoice_available():
            return {
                "success": False,
                "message": "Chưa cài OmniVoice. Chạy: pip install torch torchaudio omnivoice",
                "provider": name,
            }
        engine: TTSEngine = OmniVoiceTTSEngine(model=chosen_model, timeout=600)
        sample = "Xin chào, đây là bài kiểm tra giọng đọc tiếng Việt."
    elif name == DEEPGRAM_PROVIDER:
        if not key:
            return {"success": False, "message": "Vui lòng nhập API Key giọng đọc", "provider": name}
        engine = DeepgramTTSEngine(
            api_key=key,
            model=chosen_model,
            base_url=_clean(api_base_url) or DEFAULT_DEEPGRAM_BASE_URL,
            timeout=30,
        )
    elif name == OPENAI_PROVIDER:
        if not key:
            return {"success": False, "message": "Vui lòng nhập API Key giọng đọc", "provider": name}
        base_url = _clean(api_base_url)
        if not base_url or not chosen_model:
            return {
                "success": False,
                "message": "OpenAI-compatible cần địa chỉ API và tên mô hình",
                "provider": name,
            }
        engine = OpenAICompatibleTTSEngine(
            base_url=base_url,
            api_key=key,
            model=chosen_model,
            voice=settings.video_tts_voice,
            timeout=30,
        )
    else:
        return {"success": False, "message": f"Provider TTS không hỗ trợ: {name}", "provider": name}

    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            audio = await engine.synthesize(
                text=sample,
                out_path=Path(tmp) / "tts-test.mp3",
            )
            if audio is None or not audio.is_file() or audio.stat().st_size < 32:
                return {
                    "success": False,
                    "message": "API không trả về file âm thanh",
                    "provider": name,
                    "model": chosen_model,
                }
    except httpx.HTTPStatusError as exc:
        detail = _safe_http_error(exc)
        return {
            "success": False,
            "message": f"Deepgram từ chối yêu cầu: {detail}" if name == DEEPGRAM_PROVIDER else f"TTS từ chối yêu cầu: {detail}",
            "provider": name,
            "model": chosen_model,
        }
    except Exception as exc:  # noqa: BLE001 - test endpoint phải trả lời được
        detail = str(exc).replace("\n", " ").strip()[:240]
        return {
            "success": False,
            "message": (
                f"OmniVoice lỗi: {detail or type(exc).__name__}"
                if name == OMNIVOICE_PROVIDER
                else "Không kết nối được dịch vụ TTS. Kiểm tra API Key và mạng."
            ),
            "provider": name,
            "model": chosen_model,
            "error": type(exc).__name__,
        }
    return {
        "success": True,
        "message": "Kiểm tra giọng đọc thành công",
        "provider": name,
        "model": chosen_model,
    }


def _safe_http_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code if exc.response is not None else 0
    text = ""
    try:
        payload = exc.response.json() if exc.response is not None else {}
        text = str(
            payload.get("err_msg")
            or payload.get("error")
            or payload.get("message")
            or ""
        )
    except Exception:  # noqa: BLE001
        text = ""
    text = text.replace("\n", " ").strip()[:160]
    if text:
        return f"HTTP {status} · {text}"
    return f"HTTP {status}"


__all__ = [
    "DEEPGRAM_FLUX_MODELS",
    "DEEPGRAM_PROVIDER",
    "DEFAULT_DEEPGRAM_BASE_URL",
    "DEFAULT_DEEPGRAM_MODEL",
    "DEFAULT_OMNIVOICE_MODEL",
    "DeepgramTTSEngine",
    "EDGE_PROVIDER",
    "OMNIVOICE_PROVIDER",
    "OmniVoiceTTSEngine",
    "NullTTSEngine",
    "OPENAI_PROVIDER",
    "OpenAICompatibleTTSEngine",
    "TTSEngine",
    "TTS_PROVIDERS",
    "build_deepgram_speak_url",
    "build_tts_engine",
    "default_tts_model",
    "default_tts_provider_name",
    "is_english_only_tts_model",
    "list_tts_provider_capabilities",
    "looks_like_vietnamese",
    "missing_tts_config_hint",
    "normalize_omnivoice_voice",
    "omnivoice_available",
    "prefer_native_language_engine",
    "resolve_tts_config",
    "test_tts_settings",
    "tts_configured",
]
