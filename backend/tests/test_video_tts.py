"""Unit tests for Deepgram / video TTS wiring (no live API calls)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.video_export.service import normalize_options
from app.services.video_export.tts import (
    DEEPGRAM_PROVIDER,
    DEFAULT_DEEPGRAM_MODEL,
    DeepgramTTSEngine,
    NullTTSEngine,
    OpenAICompatibleTTSEngine,
    build_deepgram_speak_url,
    build_tts_engine,
    resolve_tts_config,
    tts_configured,
)


def test_deepgram_flux_uses_v2_speak():
    url = build_deepgram_speak_url(
        "https://api.deepgram.com",
        model="flux-hannah-en",
        speed=1,
        expressivity=0,
    )
    assert url.startswith("https://api.deepgram.com/v2/speak?")
    assert "model=flux-hannah-en" in url
    assert "encoding=mp3" in url
    assert "speed=1" in url
    assert "expressivity=0" in url


def test_deepgram_aura_uses_v1_speak():
    url = build_deepgram_speak_url("https://api.deepgram.com", model="aura-2-thalia-en")
    assert url.startswith("https://api.deepgram.com/v1/speak?")
    assert "model=aura-2-thalia-en" in url
    assert "expressivity" not in url


def test_user_settings_enable_deepgram():
    user = SimpleNamespace(
        tts_enabled=True,
        tts_api_provider="deepgram",
        tts_api_key="dg-test-key",
        tts_api_base_url="",
        tts_model="flux-kit-en",
        tts_voice="",
    )
    assert tts_configured(user) is True
    cfg = resolve_tts_config(user)
    assert cfg is not None
    assert cfg["provider"] == DEEPGRAM_PROVIDER
    assert cfg["model"] == "flux-kit-en"
    engine = build_tts_engine(user)
    assert isinstance(engine, DeepgramTTSEngine)
    assert engine.model == "flux-kit-en"


def test_user_can_disable_deepgram_without_blocking_vietnamese_tts():
    from app.services.video_export.tts import OMNIVOICE_PROVIDER, omnivoice_available

    user = SimpleNamespace(
        tts_enabled=False,
        tts_api_provider="deepgram",
        tts_api_key="dg-test-key",
        tts_api_base_url="",
        tts_model=DEFAULT_DEEPGRAM_MODEL,
        tts_voice="",
    )
    cfg = resolve_tts_config(user)
    if omnivoice_available():
        assert cfg is not None
        assert cfg["provider"] == OMNIVOICE_PROVIDER
        engine = build_tts_engine(user)
        assert engine.name == OMNIVOICE_PROVIDER
    else:
        assert cfg is None or cfg["provider"] != DEEPGRAM_PROVIDER
        if cfg is None:
            assert isinstance(build_tts_engine(user), NullTTSEngine)


def test_normalize_options_accepts_tts_when_user_configured():
    user = SimpleNamespace(
        tts_enabled=True,
        tts_api_provider="deepgram",
        tts_api_key="dg-test-key",
        tts_api_base_url="",
        tts_model="flux-hannah-en",
        tts_voice="",
    )
    options = normalize_options(
        {"tts_enabled": True, "tts_provider": "deepgram", "tts_model": "flux-hannah-en"},
        user_settings=user,
    )
    assert options["tts_enabled"] is True
    assert options["tts_provider"] == "deepgram"
    assert options["tts_model"] == "flux-hannah-en"


def test_vietnamese_text_detected():
    from app.services.video_export.tts import looks_like_vietnamese

    assert looks_like_vietnamese("Nguyễn Minh Khang bước xuống ga Thượng Đình") is True
    assert looks_like_vietnamese("Hello station") is False


def test_flux_models_are_english_only():
    from app.services.video_export.tts import is_english_only_tts_model

    assert is_english_only_tts_model("flux-hannah-en") is True
    assert is_english_only_tts_model("female") is False


def test_prefer_vietnamese_engine_switches_deepgram():
    from app.services.video_export.tts import (
        DEFAULT_OMNIVOICE_MODEL,
        DeepgramTTSEngine,
        OmniVoiceTTSEngine,
        omnivoice_available,
        prefer_native_language_engine,
    )

    engine = DeepgramTTSEngine(api_key="dg-test-key", model="flux-hannah-en")
    switched_engine, switched = prefer_native_language_engine(
        engine, "Khang nghe tiếng bíp lệch ở ga Thượng Đình"
    )
    if omnivoice_available():
        assert switched is True
        assert isinstance(switched_engine, OmniVoiceTTSEngine)
        assert switched_engine.model == DEFAULT_OMNIVOICE_MODEL
    else:
        assert switched is False
        assert switched_engine is engine


def test_legacy_edge_maps_to_omnivoice():
    from app.services.video_export.tts import (
        OMNIVOICE_PROVIDER,
        normalize_omnivoice_voice,
        omnivoice_available,
        resolve_tts_config,
    )

    assert normalize_omnivoice_voice("vi-VN-HoaiMyNeural") == "female"
    assert normalize_omnivoice_voice("vi-VN-NamMinhNeural") == "male"
    if not omnivoice_available():
        pytest.skip("omnivoice chưa cài")
    cfg = resolve_tts_config(provider="edge", model="vi-VN-HoaiMyNeural")
    assert cfg is not None
    assert cfg["provider"] == OMNIVOICE_PROVIDER
    assert cfg["model"] == "female"


def test_omnivoice_is_configured_without_api_key():
    from app.services.video_export.tts import OMNIVOICE_PROVIDER, omnivoice_available, resolve_tts_config

    if not omnivoice_available():
        pytest.skip("omnivoice chưa cài")
    cfg = resolve_tts_config(provider=OMNIVOICE_PROVIDER)
    assert cfg is not None
    assert cfg["provider"] == OMNIVOICE_PROVIDER


def test_normalize_options_still_rejects_tts_without_config():
    from app.services.video_export.tts import omnivoice_available

    if omnivoice_available():
        options = normalize_options({"tts_enabled": True})
        assert options["tts_enabled"] is True
        return
    with pytest.raises(HTTPException) as exc:
        normalize_options({"tts_enabled": True})
    assert exc.value.status_code == 400


def test_null_user_tts_setting_is_disabled():
    user = SimpleNamespace(
        tts_enabled=None,
        tts_api_provider="deepgram",
        tts_api_key="dg-test-key",
        tts_api_base_url="https://api.deepgram.com",
        tts_model=DEFAULT_DEEPGRAM_MODEL,
        tts_voice="",
    )
    cfg = resolve_tts_config(user_settings=user)
    assert cfg is None or cfg["provider"] != DEEPGRAM_PROVIDER


@pytest.mark.asyncio
async def test_openai_tts_rejects_private_base_url_before_request(tmp_path):
    engine = OpenAICompatibleTTSEngine(
        base_url="http://127.0.0.1:9",
        api_key="test-key",
        model="test-model",
        voice="alloy",
    )
    with pytest.raises(HTTPException):
        await engine.synthesize(text="probe", out_path=tmp_path / "probe.mp3")
