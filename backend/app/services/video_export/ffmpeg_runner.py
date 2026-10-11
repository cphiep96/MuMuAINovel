"""FFmpeg 渲染封装

职责：
- 探测 FFmpeg 是否可用（缺失时给出明确错误，而不是静默失败）
- 把单个分镜渲染为片段（有图片时用 zoompan 做 pan/zoom，无图片时生成安全的占位背景）
- 合并片段、写入 SRT 字幕轨、探测成片时长
- 运行期间周期性检查取消信号与总超时，任何异常都会先终止子进程，避免孤儿进程

所有外部进程都通过参数列表调用（不使用 shell），避免命令注入。
"""
from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

_UNRESOLVED = object()
_ffmpeg_cache: object | str | None = _UNRESOLVED
_ffprobe_cache: object | str | None = _UNRESOLVED

# 取消回调：返回 True 表示应尽快终止当前 FFmpeg 进程
CancelCheck = Callable[[], Awaitable[bool]]


class FFmpegUnavailableError(RuntimeError):
    """未找到 FFmpeg 可执行文件"""


class FFmpegExecutionError(RuntimeError):
    """FFmpeg 执行失败"""


class FFmpegCancelledError(RuntimeError):
    """FFmpeg 进程因任务取消/超时被主动终止"""


def _resolve_binary(configured: Optional[str], fallback: str) -> Optional[str]:
    candidate = (configured or "").strip() or fallback
    found = shutil.which(candidate)
    if found:
        return found
    # 配置了具体路径但不在 PATH 中时，直接校验文件是否存在
    path = Path(candidate)
    if path.is_file():
        return str(path)
    return None


def ffmpeg_binary() -> Optional[str]:
    """返回 FFmpeg 可执行文件路径（进程内缓存），未安装时返回 None"""
    global _ffmpeg_cache
    if _ffmpeg_cache is _UNRESOLVED:
        _ffmpeg_cache = _resolve_binary(settings.video_ffmpeg_binary, "ffmpeg")
    return _ffmpeg_cache  # type: ignore[return-value]


def ffprobe_binary() -> Optional[str]:
    """返回 ffprobe 路径（用于探测时长），未安装时返回 None"""
    global _ffprobe_cache
    if _ffprobe_cache is _UNRESOLVED:
        found = shutil.which("ffprobe")
        if not found and ffmpeg_binary():
            sibling = Path(str(ffmpeg_binary())).parent / (
                "ffprobe.exe" if Path(str(ffmpeg_binary())).suffix.lower() == ".exe" else "ffprobe"
            )
            found = str(sibling) if sibling.is_file() else None
        _ffprobe_cache = found
    return _ffprobe_cache  # type: ignore[return-value]


def reset_binary_cache() -> None:
    """清空可执行文件缓存（配置变更或测试时使用）"""
    global _ffmpeg_cache, _ffprobe_cache
    _ffmpeg_cache = _UNRESOLVED
    _ffprobe_cache = _UNRESOLVED


def require_ffmpeg() -> str:
    binary = ffmpeg_binary()
    if not binary:
        raise FFmpegUnavailableError(
            "FFmpeg chưa được cài đặt hoặc không nằm trong PATH. "
            "Hãy cài FFmpeg rồi đặt biến môi trường VIDEO_FFMPEG_BINARY nếu cần chỉ định đường dẫn."
        )
    return binary


def _as_ff_path(path: Path) -> str:
    """FFmpeg 参数中的路径统一使用 POSIX 形式，避免 Windows 反斜杠被当作转义符"""
    return path.resolve().as_posix()


async def _terminate_process(process: "asyncio.subprocess.Process", *, grace_seconds: float = 5.0) -> None:
    """终止子进程并回收，确保不留下孤儿进程"""
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        return
    except asyncio.TimeoutError:
        pass
    with contextlib.suppress(ProcessLookupError, PermissionError):
        process.kill()
    with contextlib.suppress(Exception):
        await process.wait()


async def _wait_with_guards(
    process: "asyncio.subprocess.Process",
    *,
    deadline: float,
    poll_seconds: float,
    cancel_check: Optional[CancelCheck],
    limit: float,
) -> None:
    """等待进程结束，期间周期性检查取消信号与总超时"""
    wait_task = asyncio.ensure_future(process.wait())
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FFmpegExecutionError(f"FFmpeg vượt quá thời gian chờ {limit:g} giây")
            done, _ = await asyncio.wait(
                {wait_task}, timeout=max(0.05, min(poll_seconds, remaining))
            )
            if done:
                return
            if cancel_check is not None and await cancel_check():
                raise FFmpegCancelledError("Đã dừng FFmpeg do tác vụ bị hủy")
    finally:
        if not wait_task.done():
            wait_task.cancel()
            with contextlib.suppress(BaseException):
                await wait_task


async def run_ffmpeg(
    args: Sequence[str],
    *,
    timeout: Optional[float] = None,
    cancel_check: Optional[CancelCheck] = None,
    poll_seconds: Optional[float] = None,
) -> str:
    """执行 FFmpeg 命令，失败时抛出带 stderr 摘要的异常

    - `cancel_check`：运行期间周期性调用，返回 True 时立即终止进程并抛出 FFmpegCancelledError
    - `timeout`：本次调用的墙钟上限，超时同样终止进程
    - stderr 写入临时文件（而不是管道），避免输出过多时子进程被阻塞
    """
    binary = require_ffmpeg()
    command = [binary, "-hide_banner", "-nostdin", *args]
    limit = float(timeout or settings.video_render_timeout_seconds)
    poll = float(poll_seconds or settings.video_cancel_poll_seconds)
    deadline = time.monotonic() + limit
    logger.debug("执行 FFmpeg: %s", " ".join(command[-8:]))

    with tempfile.TemporaryFile() as stderr_file:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=stderr_file,
        )
        try:
            await _wait_with_guards(
                process,
                deadline=deadline,
                poll_seconds=poll,
                cancel_check=cancel_check,
                limit=limit,
            )
        except BaseException:
            # 取消、超时或连接中断都必须先回收子进程
            await _terminate_process(process)
            raise
        stderr_file.seek(0)
        stderr_text = stderr_file.read().decode("utf-8", errors="replace").strip()

    if process.returncode != 0:
        tail = stderr_text[-600:] if stderr_text else "không có thông tin lỗi"
        raise FFmpegExecutionError(f"FFmpeg lỗi (mã {process.returncode}): {tail}")
    return stderr_text


async def probe_duration(path: Path) -> Optional[float]:
    """用 ffprobe 读取媒体时长（秒），失败时返回 None"""
    probe = ffprobe_binary()
    if not probe or not path.is_file():
        return None
    process = await asyncio.create_subprocess_exec(
        probe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        _as_ff_path(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return None
    if process.returncode != 0:
        return None
    try:
        return float((stdout or b"").decode().strip())
    except ValueError:
        return None


def probe_image_size(path: Path) -> Optional[tuple[int, int]]:
    """同步读取图片像素尺寸（供 provider 校验/缩放参考图），失败返回 None"""
    probe = ffprobe_binary()
    if not probe or not path.is_file():
        return None
    try:
        completed = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                _as_ff_path(path),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    text = (completed.stdout or b"").decode("utf-8", errors="replace").strip().splitlines()
    if not text:
        return None
    try:
        width_text, height_text = text[0].split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError:
        return None
    return (width, height) if width > 0 and height > 0 else None


def resize_image_cover(source: Path, target: Path, *, width: int, height: int) -> None:
    """把图片缩放并居中裁剪到精确像素尺寸（用于 provider 要求参考图与视频尺寸一致）"""
    binary = require_ffmpeg()
    if not source.is_file():
        raise FFmpegExecutionError("Ảnh tham chiếu không tồn tại để resize")
    target.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-i",
        _as_ff_path(source),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},format=yuvj420p",
        "-frames:v",
        "1",
        "-y",
        _as_ff_path(target),
    ]
    completed = subprocess.run(
        [binary, "-hide_banner", "-nostdin", *args],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()[-300:]
        raise FFmpegExecutionError(f"Không thể resize ảnh tham chiếu: {detail or 'FFmpeg lỗi'}")


async def probe_stream_types(path: Path) -> list[str]:
    probe = ffprobe_binary()
    if not probe or not path.is_file():
        return []
    process = await asyncio.create_subprocess_exec(
        probe,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        _as_ff_path(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return []
    if process.returncode != 0:
        return []
    return [line.strip() for line in (stdout or b"").decode().splitlines() if line.strip()]


def _motion_filter(width: int, height: int, fps: int, duration: float) -> str:
    """图片分镜的 Ken Burns 效果：放大到 2 倍画布后缓慢推近"""
    frames = max(int(round(duration * fps)), 1)
    scaled_w, scaled_h = width * 2, height * 2
    return (
        f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
        f"crop={scaled_w}:{scaled_h},"
        f"zoompan=z='min(zoom+0.0012,1.12)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )


def _still_filter(width: int, height: int) -> str:
    """静态铺满画面（等比缩放 + 居中留边）"""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"format=yuv420p"
    )


def _output_args(
    *,
    out_path: Path,
    duration: float,
    audio_path: Optional[Path],
) -> list[str]:
    args = [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if audio_path is not None:
        args += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        args += ["-an"]
    args += ["-t", f"{duration:.2f}", "-y", _as_ff_path(out_path)]
    return args


def _build_scene_attempts(
    *,
    image_path: Optional[Path],
    out_path: Path,
    width: int,
    height: int,
    fps: int,
    duration: float,
    audio_path: Optional[Path],
    enable_motion: bool,
) -> list[tuple[str, list[str]]]:
    """返回候选命令列表，按优先级从"效果最好"到"最保守" """
    attempts: list[tuple[str, list[str]]] = []
    audio_input = ["-i", _as_ff_path(audio_path)] if audio_path is not None else []

    if image_path is not None:
        if enable_motion:
            attempts.append(
                (
                    "pan-zoom",
                    [
                        "-loop",
                        "1",
                        "-framerate",
                        str(fps),
                        "-i",
                        _as_ff_path(image_path),
                        *audio_input,
                        "-vf",
                        _motion_filter(width, height, fps, duration),
                        *_output_args(out_path=out_path, duration=duration, audio_path=audio_path),
                    ],
                )
            )
        attempts.append(
            (
                "still",
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(fps),
                    "-i",
                    _as_ff_path(image_path),
                    *audio_input,
                    "-vf",
                    _still_filter(width, height),
                    *_output_args(out_path=out_path, duration=duration, audio_path=audio_path),
                ],
            )
        )
        return attempts

    # 无可用图片：生成安全的渐变/纯色占位背景，保证输出依然是合法视频
    if enable_motion:
        attempts.append(
            (
                "gradient",
                [
                    "-f",
                    "lavfi",
                    "-r",
                    str(fps),
                    "-i",
                    f"gradients=s={width}x{height}:c0=0x1b2333:c1=0x3a2d5c:x0=0:y0=0:"
                    f"x1={width}:y1={height}:d={duration:.2f}:speed=0.02:r={fps}",
                    *audio_input,
                    "-vf",
                    "format=yuv420p",
                    *_output_args(out_path=out_path, duration=duration, audio_path=audio_path),
                ],
            )
        )
    attempts.append(
        (
            "solid",
            [
                "-f",
                "lavfi",
                "-r",
                str(fps),
                "-i",
                f"color=c=0x141a2b:s={width}x{height}",
                *audio_input,
                "-vf",
                "format=yuv420p",
                *_output_args(out_path=out_path, duration=duration, audio_path=audio_path),
            ],
        )
    )
    return attempts


async def render_scene_clip(
    *,
    out_path: Path,
    duration: float,
    width: int,
    height: int,
    fps: int,
    image_path: Optional[Path] = None,
    audio_path: Optional[Path] = None,
    enable_motion: bool = True,
    cancel_check: Optional[CancelCheck] = None,
    timeout: Optional[float] = None,
) -> None:
    """渲染单个分镜片段，候选命令依次降级，全部失败才报错"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    errors: list[str] = []
    for label, args in _build_scene_attempts(
        image_path=image_path,
        out_path=out_path,
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        audio_path=audio_path,
        enable_motion=enable_motion,
    ):
        try:
            await run_ffmpeg(args, timeout=timeout, cancel_check=cancel_check)
        except FFmpegCancelledError:
            # 任务已取消：不再尝试降级命令，避免拖慢停止流程
            out_path.unlink(missing_ok=True)
            raise
        except FFmpegExecutionError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if out_path.is_file() and out_path.stat().st_size > 0:
            return
        errors.append(f"{label}: tệp đầu ra rỗng")

    raise FFmpegExecutionError(
        "Không thể dựng phân cảnh bằng FFmpeg: " + (" | ".join(errors) if errors else "không rõ nguyên nhân")
    )


async def concat_clips(
    clip_paths: Sequence[Path],
    out_path: Path,
    *,
    workdir: Path,
    fps: int,
    normalize_timestamps: bool = False,
    cancel_check: Optional[CancelCheck] = None,
    timeout: Optional[float] = None,
) -> None:
    """按顺序合并片段，优先流拷贝，失败时重新编码"""
    if not clip_paths:
        raise FFmpegExecutionError("Không có phân cảnh nào để ghép thành phim")

    if normalize_timestamps:
        # A concat filter aligns decoded streams; avoid MP4/AAC per-file start offsets
        # producing a hold or quiet gap at every splice.
        inputs=[]
        filters=[]
        for index,path in enumerate(clip_paths):
            inputs += ["-i", _as_ff_path(path)]
            filters += [f"[{index}:v:0]setpts=PTS-STARTPTS,fps={fps},setsar=1[v{index}]",
                        f"[{index}:a:0]asetpts=PTS-STARTPTS,aresample=48000[a{index}]"]
        pairs="".join(f"[v{i}][a{i}]" for i in range(len(clip_paths)))
        filters.append(f"{pairs}concat=n={len(clip_paths)}:v=1:a=1[v][a]")
        try:
            await run_ffmpeg([*inputs,"-filter_complex",";".join(filters),"-map","[v]","-map","[a]",
                "-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",
                "-r",str(fps),"-c:a","aac","-b:a","160k","-ar","48000","-ac","2",
                "-movflags","+faststart","-y",_as_ff_path(out_path)],
                timeout=timeout,cancel_check=cancel_check)
        except BaseException:
            out_path.unlink(missing_ok=True)
            raise
        if not out_path.is_file() or out_path.stat().st_size==0:
            raise FFmpegExecutionError("Ghép phim không tạo được tệp")
        return

    list_file = workdir / "clips.txt"
    lines = [f"file '{_as_ff_path(path)}'" for path in clip_paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if out_path.exists():
        out_path.unlink()

    concat_input = ["-f", "concat", "-safe", "0", "-i", _as_ff_path(list_file)]
    attempts: list[tuple[str, list[str]]] = [
        ("copy", [*concat_input, "-c", "copy", "-movflags", "+faststart", "-y", _as_ff_path(out_path)]),
        (
            "reencode",
            [
                *concat_input,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "24",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-y",
                _as_ff_path(out_path),
            ],
        ),
    ]

    errors: list[str] = []
    for label, args in attempts:
        try:
            await run_ffmpeg(args, timeout=timeout, cancel_check=cancel_check)
        except FFmpegCancelledError:
            out_path.unlink(missing_ok=True)
            raise
        except FFmpegExecutionError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if out_path.is_file() and out_path.stat().st_size > 0:
            return
        errors.append(f"{label}: tệp đầu ra rỗng")

    raise FFmpegExecutionError("Không thể ghép các phân cảnh: " + " | ".join(errors))


async def mux_subtitles(
    video_path: Path,
    srt_path: Path,
    out_path: Path,
    *,
    cancel_check: Optional[CancelCheck] = None,
    timeout: Optional[float] = None,
) -> bool:
    """把 SRT 作为字幕轨写入 MP4（尽力而为，失败时保留无字幕成片）"""
    if not (video_path.is_file() and srt_path.is_file()):
        return False
    if out_path.exists():
        out_path.unlink()
    args = [
        "-i",
        _as_ff_path(video_path),
        "-i",
        _as_ff_path(srt_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=vie",
        "-movflags",
        "+faststart",
        "-y",
        _as_ff_path(out_path),
    ]
    try:
        await run_ffmpeg(args, timeout=timeout, cancel_check=cancel_check)
    except FFmpegCancelledError:
        out_path.unlink(missing_ok=True)
        raise
    except FFmpegExecutionError as exc:
        logger.warning("写入字幕轨失败，保留无内嵌字幕的成片: %s", exc)
        return False
    return out_path.is_file() and out_path.stat().st_size > 0
