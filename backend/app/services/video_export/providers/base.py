"""视频转场 Provider 契约

设计目标：新增 provider 只需实现 4 个方法（`_submit` / `_poll` / `_download` / `_cancel`），
轮询退避、墙钟上限、取消检查、下载校验统一由 `RemoteMotionProvider` 负责。

- `LocalFFmpegProvider`：本地 Ken Burns/占位背景，作为兜底
- `RemoteMotionProvider`：提交异步任务 → 轮询到终态 → 下载 MP4
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.logger import get_logger
from app.services.video_export.providers.errors import (
    MotionCancelledError,
    MotionConfigError,
    MotionProviderError,
    MotionRequestError,
    MotionTimeoutError,
    sanitize_message,
)

logger = get_logger(__name__)

CancelCheck = Callable[[], Awaitable[bool]]
OperationHook = Callable[["MotionOperation"], Awaitable[None]]

KIND_LOCAL = "local"
KIND_REMOTE = "remote"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_EXPIRED, STATUS_CANCELLED})


@dataclass(frozen=True)
class MotionReference:
    """参考图/首帧（只来自服务端受管素材）"""

    path: Path
    mime_type: str
    kind: str

    @property
    def is_placeholder(self) -> bool:
        return self.kind == "placeholder"


@dataclass(frozen=True)
class LocalRenderOptions:
    """仅本地 FFmpeg provider 使用的渲染参数"""

    width: int
    height: int
    fps: int
    audio_path: Optional[Path] = None
    enable_motion: bool = True


@dataclass(frozen=True)
class MotionRequest:
    """单个分镜的视频生成请求"""

    prompt: str
    duration_seconds: float
    aspect_ratio: str
    resolution: str
    reference: Optional[MotionReference]
    idempotency_key: str
    model: Optional[str] = None
    negative_prompt: Optional[str] = None
    local: Optional[LocalRenderOptions] = None
    resume_operation_id: Optional[str] = None
    audio_mode: Optional[str] = None
    scene_direction: Optional[dict[str, Any]] = None


@dataclass
class MotionOperation:
    """远端异步操作（只把 operation_id/status 落库，绝不保存远端 URL）"""

    provider: str
    model: str
    operation_id: str
    status: str = STATUS_PENDING
    progress: Optional[int] = None
    download_url: Optional[str] = field(default=None, repr=False)
    failure_reason: Optional[str] = None


@dataclass
class MotionRenderResult:
    """单个分镜的最终片段"""

    clip_path: Path
    provider: str
    model: str
    duration_seconds: Optional[float] = None
    operation_id: Optional[str] = None
    fallback_used: bool = False


@dataclass(frozen=True)
class ProviderConfigState:
    """provider 配置状态（只暴露环境变量名，不暴露值）"""

    configured: bool
    missing_config: tuple[str, ...] = ()
    detail: Optional[str] = None


class MotionProvider(ABC):
    """视频转场 provider 基类"""

    name: str = ""
    label: str = ""
    kind: str = KIND_REMOTE
    description: str = ""
    models: tuple[str, ...] = ()
    default_model: str = ""
    supports_placeholder: bool = False
    supports_cancel: bool = False
    supports_idempotency: bool = False
    min_duration_seconds: float = 1.0
    max_duration_seconds: float = 8.0
    duration_options: tuple[float, ...] = ()
    aspect_ratios: tuple[str, ...] = ("16:9",)
    resolutions: tuple[str, ...] = ()
    default_resolution: str = ""
    cost_note: str = ""

    def configuration(self) -> ProviderConfigState:  # pragma: no cover - 由子类实现
        return ProviderConfigState(configured=True)

    def require_configured(self) -> None:
        state = self.configuration()
        if not state.configured:
            raise MotionConfigError(
                state.detail or f"Provider {self.name} chưa được cấu hình trên máy chủ",
                missing_config=state.missing_config,
            )

    # ---------------------------------------------------------------- 限制（可按模型不同）

    def model_limits(self, model: Optional[str] = None) -> dict[str, Any]:
        """某个模型允许的时长/比例/分辨率（默认对所有模型一致，子类可覆盖）"""
        return {
            "min_duration_seconds": self.min_duration_seconds,
            "max_duration_seconds": self.max_duration_seconds,
            "duration_options": list(self.duration_options),
            "aspect_ratios": list(self.aspect_ratios),
            "resolutions": list(self.resolutions),
            "default_resolution": self.default_resolution,
        }

    def clamp_duration(self, seconds: float, model: Optional[str] = None) -> float:
        """把分镜时长夹到 provider（该模型）允许的区间"""
        limits = self.model_limits(model)
        value = float(seconds or 0.0)
        options: list[float] = limits.get("duration_options") or []
        if options:
            return float(min(options, key=lambda option: abs(option - value)))
        low = float(limits.get("min_duration_seconds") or self.min_duration_seconds)
        high = float(limits.get("max_duration_seconds") or self.max_duration_seconds)
        return float(min(max(value, low), high))

    def normalize_aspect_ratio(self, value: Optional[str], model: Optional[str] = None) -> str:
        ratios = tuple(self.model_limits(model).get("aspect_ratios") or self.aspect_ratios)
        candidate = str(value or "").strip()
        if candidate and candidate in ratios:
            return candidate
        if candidate:
            raise MotionRequestError(
                f"Tỉ lệ khung hình {candidate} không được provider {self.name} hỗ trợ"
            )
        return ratios[0]

    def normalize_resolution(self, value: Optional[str], model: Optional[str] = None) -> str:
        limits = self.model_limits(model)
        resolutions = tuple(limits.get("resolutions") or self.resolutions)
        candidate = str(value or "").strip()
        if candidate and candidate in resolutions:
            return candidate
        if candidate:
            raise MotionRequestError(
                f"Độ phân giải {candidate} không được model {self.normalize_model(model)} hỗ trợ"
            )
        default = str(limits.get("default_resolution") or self.default_resolution or "")
        return default or (resolutions[0] if resolutions else "")

    def normalize_model(self, value: Optional[str]) -> str:
        candidate = str(value or "").strip()
        if candidate and candidate in self.models:
            return candidate
        if candidate:
            raise MotionRequestError(f"Model {candidate} không thuộc provider {self.name}")
        return self.default_model or (self.models[0] if self.models else "")

    def capabilities(self) -> dict[str, Any]:
        """对外能力描述：不包含密钥、绝对路径或服务端目录

        `limits` 为默认模型的限制（兼容旧客户端），`model_limits` 给出每个模型的限制，
        避免客户端提交必然被 provider 拒绝的组合（例如 Veo 3.1 只接受 8 秒）。
        """
        state = self.configuration()
        default_limits = self.model_limits(self.default_model or None)
        return {
            "id": self.name,
            "label": self.label or self.name,
            "kind": self.kind,
            "description": self.description,
            "configured": state.configured,
            "missing_config": list(state.missing_config),
            "config_error": state.detail,
            "models": list(self.models),
            "default_model": self.default_model,
            "features": {
                "image_to_video": True,
                "placeholder": self.supports_placeholder,
                "cancel": self.supports_cancel,
                "idempotency": self.supports_idempotency,
            },
            "limits": default_limits,
            "model_limits": {model: self.model_limits(model) for model in self.models},
            "cost_note": self.cost_note,
        }

    @abstractmethod
    async def render_scene(
        self,
        *,
        request: MotionRequest,
        out_path: Path,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
        on_operation: Optional[OperationHook] = None,
    ) -> MotionRenderResult:
        """生成单个分镜片段并写入 `out_path`"""
        raise NotImplementedError


class RemoteMotionProvider(MotionProvider):
    """远端 provider 通用流程：提交 → 轮询（退避 + 墙钟上限 + 取消）→ 下载校验"""

    kind = KIND_REMOTE

    # 子类可覆盖：请求级别的 HTTP 超时
    request_timeout_seconds: Optional[float] = None

    def __init__(self, *, transport=None) -> None:
        # `transport` 仅用于测试注入 httpx.MockTransport
        self._transport = transport

    # ---------------------------------------------------------------- 子类实现

    @abstractmethod
    async def _submit(
        self, request: MotionRequest, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        """创建远端操作，返回含 operation_id 的 MotionOperation"""
        raise NotImplementedError

    @abstractmethod
    async def _poll(
        self, operation: MotionOperation, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        """查询操作状态，更新 status/progress/download_url/failure_reason"""
        raise NotImplementedError

    @abstractmethod
    async def _download(
        self,
        operation: MotionOperation,
        out_path: Path,
        *,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
    ) -> int:
        """把远端成片下载到 out_path，返回字节数（必须做 SSRF/体积/MIME 校验）"""
        raise NotImplementedError

    async def _cancel(self, operation: MotionOperation) -> None:
        """尽力取消远端操作；provider 不支持时静默跳过并按本地取消处理"""
        return None

    def _http_timeout(self) -> float:
        return float(self.request_timeout_seconds or settings.video_motion_request_timeout_seconds)

    def _client(self) -> Any:
        return None

    # ---------------------------------------------------------------- 流程

    async def render_scene(
        self,
        *,
        request: MotionRequest,
        out_path: Path,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
        on_operation: Optional[OperationHook] = None,
    ) -> MotionRenderResult:
        self.require_configured()
        limit = float(timeout or settings.video_motion_operation_timeout_seconds)
        deadline = time.monotonic() + limit

        if request.resume_operation_id:
            # 断点续跑：任务重启前已提交的远端操作直接继续轮询，不重复下单（避免重复计费）
            logger.info(
                "Tiếp tục theo dõi thao tác từ xa đã gửi trước đó: provider=%s operation=%s",
                self.name,
                request.resume_operation_id[:12],
            )
            operation = MotionOperation(
                provider=self.name,
                model=self.normalize_model(request.model),
                operation_id=request.resume_operation_id,
                status=STATUS_RUNNING,
            )
        else:
            operation = await self._submit(request, cancel_check)
        await self._notify(on_operation, operation)
        operation = await self._poll_until_terminal(
            operation, deadline=deadline, cancel_check=cancel_check, on_operation=on_operation
        )
        if operation.status != STATUS_COMPLETED:
            reason = operation.failure_reason or f"Provider kết thúc với trạng thái {operation.status}"
            raise MotionProviderError(reason)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MotionTimeoutError("Hết thời gian chờ provider hoàn tất video")
        await self._download(
            operation,
            out_path,
            cancel_check=cancel_check,
            timeout=min(remaining, float(settings.video_motion_download_timeout_seconds)),
        )
        if not out_path.is_file() or out_path.stat().st_size <= 0:
            raise MotionProviderError("Tệp video tải về rỗng")
        return MotionRenderResult(
            clip_path=out_path,
            provider=self.name,
            model=operation.model or self.default_model,
            operation_id=operation.operation_id,
        )

    async def _notify(self, hook: Optional[OperationHook], operation: MotionOperation) -> None:
        if hook is None:
            return
        try:
            await hook(operation)
        except MotionCancelledError:
            # 取消必须冒泡：轮询循环会立即停止并跳过下载
            raise
        except Exception as exc:  # noqa: BLE001 - 持久化失败不应中断生成流程
            logger.warning("无法持久化远端操作状态: %s", type(exc).__name__)

    async def _poll_until_terminal(
        self,
        operation: MotionOperation,
        *,
        deadline: float,
        cancel_check: Optional[CancelCheck],
        on_operation: Optional[OperationHook],
    ) -> MotionOperation:
        interval = max(float(settings.video_motion_poll_interval_seconds), 0.05)
        max_interval = max(float(settings.video_motion_poll_max_interval_seconds), interval)
        current = operation
        first = True
        wait = interval
        snapshot: Optional[tuple[str, Optional[int]]] = None

        while True:
            if cancel_check is not None and await cancel_check():
                await self._cancel_best_effort(current)
                raise MotionCancelledError("Đã hủy theo yêu cầu của người dùng")
            if not first and time.monotonic() >= deadline:
                raise MotionTimeoutError(
                    f"Provider chưa hoàn tất sau {settings.video_motion_operation_timeout_seconds} giây"
                )
            first = False

            previous = snapshot
            current = await self._poll(current, cancel_check)
            if current.status in TERMINAL_STATUSES:
                await self._notify(on_operation, current)
                if current.status == STATUS_CANCELLED:
                    await self._cancel_best_effort(current)
                    raise MotionCancelledError("Provider đã hủy tác vụ")
                return current
            await self._notify(on_operation, current)

            # 指数退避（5s → 10s → 20s，到顶后保持）：provider 有进展时回到初始间隔
            snapshot = (current.status, current.progress)
            wait = next_backoff(
                wait,
                progressed=snapshot != previous,
                interval=interval,
                max_interval=max_interval,
            )
            await self._sleep_until(wait, deadline, cancel_check)

    async def _sleep_until(
        self, wait: float, deadline: float, cancel_check: Optional[CancelCheck]
    ) -> bool:
        """等待一小段时间；被取消时抛错，超时返回 False 由上层收敛为 TimeoutError"""
        end = min(time.monotonic() + wait, deadline + 0.05)
        while True:
            if cancel_check is not None and await cancel_check():
                raise MotionCancelledError("Đã hủy theo yêu cầu của người dùng")
            remaining = end - time.monotonic()
            if remaining <= 0:
                return True
            await asyncio.sleep(min(0.5, remaining))

    async def _cancel_best_effort(self, operation: MotionOperation) -> None:
        if not self.supports_cancel:
            logger.info(
                "Provider %s không hỗ trợ hủy từ xa; đánh dấu hủy cục bộ và không tải tiếp",
                self.name,
            )
            return
        try:
            await self._cancel(operation)
        except Exception as exc:  # noqa: BLE001 - 取消失败不应阻断任务收敛
            logger.warning("Gọi API hủy của provider %s thất bại: %s", self.name, type(exc).__name__)


def next_backoff(
    current: float,
    *,
    progressed: bool,
    interval: float,
    max_interval: float,
) -> float:
    """计算下一次轮询间隔：provider 有进展时回到初始值，否则指数增长并封顶"""
    if progressed:
        return interval
    return min(max(current, interval) * 2, max_interval)


def provider_error_detail(exc: Exception) -> str:
    """把异常转换为可直接展示的错误文本（无密钥/无绝对路径）"""
    if isinstance(exc, (MotionConfigError, MotionProviderError, MotionRequestError, MotionTimeoutError, MotionCancelledError)):
        return sanitize_message(str(exc)) or type(exc).__name__
    return f"{type(exc).__name__}: {sanitize_message(exc)}"
