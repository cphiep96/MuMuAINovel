import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from app.database import Base
from app.config import settings
from app.services.video_export.continuity import story_beats, build_continuity_storyboard
from app.services.video_export.storyboard import SourceChapter, StoryboardOptions
from app.services.video_export.scene_audio import replace_scene_audio
from app.services.video_export import ffmpeg_runner
from app.services.video_export.providers.base import MotionRequest
from app.services.video_export.providers.muse_tool import MuseToolVideoProvider
from app.services.video_export.service import normalize_options, video_export_service

def test_dialogue_is_not_cut_mid_quote_or_merged_across_paragraphs():
    speech='“Bờ bên kia kìa. Người ta sẽ xây trung tâm thương mại. Nhưng mình chẳng vào đó được.”'
    text=f'Lâm nói: {speech}\n\nAn nhìn mặt nước.\n\nLâm vẫn chèo đò.'
    beats=story_beats(text,30)
    assert beats[0]==f'Lâm nói: {speech}'
    assert beats[1]=='An nhìn mặt nước.'
    assert not any(beat.startswith('”') for beat in beats)

def test_time_change_is_separate_from_the_previous_action():
    beats=story_beats('Ông bước khỏi xưởng. Đêm đầu tiên, An lên mái nhà.',600)
    assert beats==['Ông bước khỏi xưởng.','Đêm đầu tiên, An lên mái nhà.']
    scenes,directions,_=build_continuity_storyboard([SourceChapter('c1',1,'Chương 1','\n\n'.join(beats))],StoryboardOptions())
    assert len(scenes)==2
    assert directions[1]['transition']=='Chuyển thời gian rõ ràng'
    assert 'Đêm đầu tiên' in directions[1]['timeOfDay']

def test_reviewed_states_are_kept_and_stale_review_is_rejected():
    chapters=[SourceChapter('c1',1,'Chương 1','Đò đang đi.\n\nĐò tới bến.')]
    options=StoryboardOptions()
    scenes,directions,stamp=build_continuity_storyboard(chapters,options)
    assert 'Đò đang đi.' in scenes[1].visual_prompt
    plan=[{'scene_index':i,'direction':direction} for i,direction in enumerate(directions)]
    plan[0]['direction']['endState']='Đò chưa đến bến'
    plan[1]['direction']['startState']='Đò chưa đến bến'
    _,reviewed,_=build_continuity_storyboard(chapters,options,reviewed_plan=plan,reviewed_fingerprint=stamp)
    assert reviewed[1]['startState']=='Đò chưa đến bến'
    with pytest.raises(HTTPException) as exc:
        build_continuity_storyboard([SourceChapter('c1',1,'Chương 1','Đã lên bờ.')],options,reviewed_plan=plan,reviewed_fingerprint=stamp)
    assert exc.value.status_code==409

@pytest.mark.asyncio
async def test_muse_receives_scene_contract_and_silent_audio():
    seen=[]
    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(202,json={'id':'task-1','status':'waiting'})
    provider=MuseToolVideoProvider(api_key='x'*40,config_file='',transport=httpx.MockTransport(handler))
    await provider._submit(MotionRequest(prompt='Đò đang đi.',duration_seconds=10,aspect_ratio='16:9',resolution='auto',
        reference=None,idempotency_key='scene-1',audio_mode='silent',scene_direction={'startState':'Ngồi trên đò','lighting':'Chiều nhiều mây'}))
    assert seen[0]['audioMode']=='silent'
    assert seen[0]['sceneDirection']['startState']=='Ngồi trên đò'

def test_muse_narration_is_allowed_without_a_cover():
    video_export_service._ensure_remote_reference_available(project=object(),normalized={'tts_enabled':True},motion={'motion_provider':'muse_tool'})
    with pytest.raises(HTTPException):
        video_export_service._ensure_remote_reference_available(project=object(),normalized={'tts_enabled':True},motion={'motion_provider':'google_veo'})

@pytest.mark.asyncio
@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg unavailable')
async def test_narration_replaces_generated_audio_and_is_not_cut(tmp_path):
    clip=tmp_path/'clip.mp4';voice=tmp_path/'voice.wav'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=320x180:r=24:d=1',
        '-f','lavfi','-i','sine=frequency=1000:duration=1','-c:v','libx264','-c:a','aac','-shortest','-y',str(clip)],check=True)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','sine=frequency=200:duration=2','-y',str(voice)],check=True)
    await replace_scene_audio(clip,audio_path=voice,timeout=20)
    assert (await ffmpeg_runner.probe_duration(clip))>=2.2
    assert not clip.with_name('clip_audio.mp4').exists()
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(clip)]))
    assert len([s for s in probe['streams'] if s['codec_type']=='audio'])==1

@pytest.mark.asyncio
async def test_audio_failure_retains_original_and_cleans_temp(tmp_path,monkeypatch):
    clip=tmp_path/'clip.mp4';clip.write_bytes(b'original')
    async def duration(path):return 1.0
    async def fail(args,**kwargs):
        Path(args[-1]).write_bytes(b'partial')
        raise ffmpeg_runner.FFmpegExecutionError('failed')
    monkeypatch.setattr(ffmpeg_runner,'probe_duration',duration)
    monkeypatch.setattr(ffmpeg_runner,'run_ffmpeg',fail)
    with pytest.raises(ffmpeg_runner.FFmpegExecutionError):
        await replace_scene_audio(clip)
    assert clip.read_bytes()==b'original'
    assert not clip.with_name('clip_audio.mp4').exists()
