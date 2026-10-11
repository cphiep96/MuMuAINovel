import json
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.database import Base  # Initialize ORM before the provider registry.
from app.services.video_export.providers import build_provider, list_provider_capabilities
from app.services.video_export.providers.base import MotionRequest, MotionOperation
from app.services.video_export.providers.errors import (
    MotionCancelledError, MotionProviderError, MotionRequestError, MotionTimeoutError,
)
from app.services.video_export.providers.muse_tool import MuseToolVideoProvider
from app.services.video_export.service import normalize_motion_options, video_export_service

KEY = 'muse-test-key-012345678901234567890123456789'
MP4 = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 256


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(settings, 'video_motion_muse_api_key', None)
    monkeypatch.setattr(settings, 'video_motion_muse_config_file', None)
    monkeypatch.setattr(settings, 'video_motion_muse_base_url', None)
    monkeypatch.setattr(settings, 'video_motion_poll_interval_seconds', 0.01)
    monkeypatch.setattr(settings, 'video_motion_poll_max_interval_seconds', 0.02)
    monkeypatch.setattr(settings, 'video_motion_max_retries', 0)
    monkeypatch.setattr(settings, 'video_motion_allow_insecure_localhost', False)


def request(**extra):
    values = dict(prompt='A paper boat on a quiet lake', duration_seconds=8,
                  aspect_ratio='16:9', resolution='auto', reference=None,
                  idempotency_key='story:scene:1')
    values.update(extra)
    return MotionRequest(**values)


def provider(handler):
    return MuseToolVideoProvider(api_key=KEY, transport=httpx.MockTransport(handler))


def test_registry_and_config_do_not_leak_credentials(tmp_path, monkeypatch):
    config_file = tmp_path / 'video-api.json'
    config_file.write_text(json.dumps({'apiKey': KEY, 'port': 9123}), encoding='utf-8')
    monkeypatch.setattr(settings, 'video_motion_muse_config_file', str(config_file))
    muse = build_provider('muse_tool')
    assert muse.configuration().configured
    assert muse.base_url == 'http://127.0.0.1:9123'
    caps = muse.capabilities()
    assert not caps['features']['image_to_video']
    assert caps['features']['placeholder']
    assert caps['limits']['duration_options'] == [5, 10, 15]
    all_caps = json.dumps(list_provider_capabilities())
    assert KEY not in all_caps and str(config_file) not in all_caps


@pytest.mark.parametrize('url', [
    'https://example.com', 'http://10.0.0.1:8910', 'http://user:pass@localhost:8910',
    'http://localhost:8910/v1', 'http://localhost:8910?secret=1',
    'http://localhost:8910#fragment', 'http://localhost:bad',
])
def test_rejects_invalid_or_nonlocal_base_urls(url):
    assert not MuseToolVideoProvider(api_key=KEY, base_url=url).configuration().configured


def test_missing_and_invalid_config_are_actionable(tmp_path):
    assert not MuseToolVideoProvider().configuration().configured
    state = MuseToolVideoProvider(config_file=str(tmp_path / 'missing.json')).configuration()
    assert not state.configured
    assert 'VIDEO_MOTION_MUSE_CONFIG_FILE' in state.missing_config


@pytest.mark.asyncio
async def test_submit_poll_download_real_contract(tmp_path):
    calls = []
    polls = 0
    def handler(req):
        nonlocal polls
        calls.append(req)
        assert req.headers['authorization'] == f'Bearer {KEY}'
        assert req.headers.get('origin') is None
        if req.method == 'POST':
            assert req.url.path == '/v1/videos'
            assert req.headers['idempotency-key'] == 'story:scene:1'
            assert json.loads(req.content) == {'prompt': request().prompt, 'duration': '10s', 'ratio': '16:9'}
            return httpx.Response(202, json={'id': 'task-1', 'status': 'waiting'})
        if req.url.path.endswith('/content'):
            return httpx.Response(200, content=MP4, headers={'content-type': 'video/mp4'})
        polls += 1
        assert req.url.path == '/v1/videos/task-1'
        return httpx.Response(200, json={'id': 'task-1', 'kind': 'video',
                                        'status': 'connecting' if polls == 1 else 'done',
                                        'downloadUrl': 'http://evil.example/secret'})
    observed = []
    async def save(op):
        observed.append((op.operation_id, op.status))
    out = tmp_path / 'clip.mp4'
    result = await provider(handler).render_scene(request=request(), out_path=out, on_operation=save)
    assert result.operation_id == 'task-1'
    assert out.read_bytes() == MP4
    assert ('task-1', 'completed') in observed
    assert all(req.url.host == '127.0.0.1' for req in calls)


@pytest.mark.asyncio
async def test_resume_does_not_submit_a_second_video(tmp_path):
    def handler(req):
        assert req.method == 'GET'
        if req.url.path.endswith('/content'):
            return httpx.Response(200, content=MP4)
        return httpx.Response(200, json={'id': 'existing-1', 'status': 'done'})
    result = await provider(handler).render_scene(
        request=request(resume_operation_id='existing-1'), out_path=tmp_path / 'clip.mp4')
    assert result.operation_id == 'existing-1'


@pytest.mark.asyncio
async def test_transport_retry_uses_same_idempotency_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'video_motion_max_retries', 1)
    submissions = []
    def handler(req):
        if req.method == 'POST':
            submissions.append(req.headers['idempotency-key'])
            if len(submissions) == 1:
                raise httpx.ReadTimeout('lost response', request=req)
            return httpx.Response(200, json={'id': 'same-job', 'status': 'done'})
        if req.url.path.endswith('/content'):
            return httpx.Response(200, content=MP4)
        return httpx.Response(200, json={'id': 'same-job', 'status': 'done'})
    await provider(handler).render_scene(request=request(), out_path=tmp_path / 'clip.mp4')
    assert submissions == ['story:scene:1', 'story:scene:1']


@pytest.mark.asyncio
async def test_failures_and_wrong_task_are_rejected():
    failed = provider(lambda req: httpx.Response(200, json={
        'id': 'task-1', 'status': 'error', 'message': f'Failure {KEY}'}))
    op = await failed._poll(MotionOperation('muse_tool', 'muse-video', 'task-1'))
    assert op.status == 'failed' and KEY not in op.failure_reason
    bad = provider(lambda req: httpx.Response(200, json={'id': 'other-task', 'status': 'done'}))
    with pytest.raises(MotionProviderError):
        await bad._poll(MotionOperation('muse_tool', 'muse-video', 'task-1'))
    with pytest.raises(MotionProviderError):
        await bad._poll(MotionOperation('muse_tool', 'muse-video', '../escape'))


@pytest.mark.asyncio
async def test_disconnect_keeps_operation_resumable():
    def handler(req):
        raise httpx.ConnectError('closed', request=req)
    with pytest.raises(MotionTimeoutError):
        await provider(handler)._poll(MotionOperation('muse_tool', 'muse-video', 'task-1'))


@pytest.mark.asyncio
async def test_cancel_stops_tracking_without_remote_cancel(tmp_path):
    async def cancelled():
        return True
    def never_called(req):
        pytest.fail('Cancelled tracking must not call Muse')
    with pytest.raises(MotionCancelledError):
        await provider(never_called).render_scene(
            request=request(resume_operation_id='task-1'), out_path=tmp_path / 'clip.mp4',
            cancel_check=cancelled)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['garbage', 'oversized', 'redirect'])
async def test_invalid_download_leaves_no_partial_file(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(settings, 'video_motion_max_clip_mb', 1)
    def handler(req):
        if kind == 'redirect':
            return httpx.Response(302, headers={'location': 'http://127.0.0.1:9999/private'})
        if kind == 'oversized':
            return httpx.Response(200, content=MP4, headers={'content-length': str(2 * 1024 * 1024)})
        return httpx.Response(200, content=b'bad file', headers={'content-type': 'video/mp4'})
    out = tmp_path / 'clip.mp4'
    with pytest.raises(MotionProviderError):
        await provider(handler)._download(MotionOperation('muse_tool', 'muse-video', 'task-1'), out)
    assert not out.exists() and not out.with_name('clip.mp4.part').exists()


@pytest.mark.asyncio
async def test_prompt_and_key_validation_happen_before_submission():
    for invalid in (request(prompt=''), request(idempotency_key=''), request(resolution='720p')):
        with pytest.raises(MotionRequestError):
            await provider(lambda req: pytest.fail('Must not submit'))._submit(invalid)


def test_remote_muse_does_not_require_cover(monkeypatch):
    monkeypatch.setattr(settings, 'video_motion_muse_api_key', KEY)
    monkeypatch.setattr(settings, 'video_motion_model', None)
    monkeypatch.setattr(settings, 'video_motion_resolution', None)
    motion = normalize_motion_options({'motion_mode': 'remote', 'motion_provider': 'muse_tool'})
    assert motion['motion_model'] == 'muse-video' and motion['motion_resolution'] == 'auto'
    video_export_service._ensure_remote_reference_available(
        project=object(), normalized={'use_project_cover': False, 'tts_enabled': False}, motion=motion)
