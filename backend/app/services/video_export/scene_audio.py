"""Replace generated speech with a separately controlled narrator or silence."""
from pathlib import Path
import math
from app.services.video_export import ffmpeg_runner
from app.services.video_export.ffmpeg_runner import FFmpegExecutionError


async def replace_scene_audio(clip: Path, *, audio_path=None, cancel_check=None, timeout=None, fps=24):
    video_duration=await ffmpeg_runner.probe_duration(clip)
    if not video_duration or video_duration<=0:raise FFmpegExecutionError('Không đọc được thời lượng clip')
    voice_duration=await ffmpeg_runner.probe_duration(audio_path) if audio_path else 0
    if audio_path and (not voice_duration or voice_duration<=0):
        raise FFmpegExecutionError('Không đọc được audio lời kể; chưa thay track âm thanh')
    fps = max(1, min(int(fps), 60))
    # Fit motion to narration instead of freezing the last frame or keeping silent tails.
    duration = math.ceil((float(voice_duration) + 0.08) * fps) / fps if audio_path else video_duration
    target=clip.with_name(clip.stem+'_audio.mp4')
    args=['-i',str(clip)]
    if audio_path:
        args+=['-i',str(audio_path)]
    else:
        args+=['-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000']
    args+=['-map','0:v:0','-map','1:a:0']
    if audio_path:
        # Slow down only when needed; otherwise cut the moving clip at the narration end.
        factor = max(1.0, duration / video_duration)
        args+=['-vf',f'setpts={factor:.9f}*(PTS-STARTPTS),fps={fps}',
               '-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',
               '-r',str(fps),'-video_track_timescale','24000']
    else:
        args+=['-c:v','copy']
    args+=['-af','apad','-c:a','aac','-ar','48000','-ac','2','-b:a','160k','-t',f'{duration:.3f}',
           '-movflags','+faststart','-y',str(target)]
    try:
        await ffmpeg_runner.run_ffmpeg(args,cancel_check=cancel_check,timeout=timeout)
        target.replace(clip)
    finally:
        target.unlink(missing_ok=True)
