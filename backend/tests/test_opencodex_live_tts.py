import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from app.database import Base
from app.config import settings
from app.services.video_export import tts,opencodex_live
from app.services.video_export.service import normalize_options

def test_live_provider_does_not_require_api_key(monkeypatch):
    monkeypatch.setattr(tts,'live_configured',lambda:True)
    cfg=tts.resolve_tts_config(provider='opencodex_live',model='maple')
    assert cfg['provider']=='opencodex_live' and cfg['api_key']=='' and cfg['model']=='maple'
    assert tts.build_tts_engine(provider='opencodex_live',model='cove').name=='opencodex_live'
    assert normalize_options({'tts_enabled':True,'tts_provider':'opencodex_live','tts_model':'cove'})['tts_enabled']
    assert tts.resolve_tts_config(provider='opencodex_live',model='alloy') is None

def test_selected_live_user_setting_does_not_fall_back_to_omnivoice(monkeypatch):
    monkeypatch.setattr(tts,'live_configured',lambda:False)
    user=SimpleNamespace(tts_enabled=True,tts_api_provider='opencodex_live',tts_model='cove')
    assert tts.resolve_tts_config(user) is None
    assert isinstance(tts.build_tts_engine(user),tts.NullTTSEngine)

def test_runtime_rejects_non_loopback_proxy(monkeypatch):
    monkeypatch.setattr(settings,'video_tts_live_base_url','https://untrusted.example')
    with pytest.raises(RuntimeError,match='loopback'):
        opencodex_live.runtime_config()

@pytest.mark.asyncio
async def test_helper_failure_does_not_silently_use_another_voice(tmp_path,monkeypatch):
    async def create(*args,**kwargs):
        class Process:
            returncode=1
            async def communicate(self,data):return b'',b'gpt-live did not read the requested text verbatim'
        return Process()
    monkeypatch.setattr(opencodex_live,'runtime_config',lambda:dict(node='node',bridgePath='bridge',playwrightPath='playwright',browserPath='browser',baseUrl='http://localhost:10100'))
    monkeypatch.setattr(opencodex_live.asyncio,'create_subprocess_exec',create)
    with pytest.raises(RuntimeError,match='verbatim'):
        await opencodex_live.OpenCodexLiveTTSEngine().synthesize(text='An về bến.',out_path=tmp_path/'voice.wav')
    assert not (tmp_path/'voice.wav').exists()
