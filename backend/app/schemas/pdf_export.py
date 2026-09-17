"""PDF 全本导出相关的 Pydantic 数据模型"""
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.video_export import VideoImageProviderInfo  # 复用图片 provider 能力描述


class PdfExportOptions(BaseModel):
    """PDF 导出参数（全部有服务端默认值/白名单）"""

    include_cover: Optional[bool] = Field(default=True, description="Có dùng ảnh bìa dự án làm trang bìa không")
    include_images: Optional[bool] = Field(
        default=False, description="Có tạo ảnh minh họa cho từng chương bằng image provider (tính phí) không"
    )
    include_toc: Optional[bool] = Field(default=True, description="Có sinh mục lục không")
    image_provider: Optional[str] = Field(
        default=None, max_length=50, description="image provider id (hiện có meta_muse_image)"
    )
    image_model: Optional[str] = Field(default=None, max_length=100, description="模型 ảnh")
    image_aspect_ratio: Optional[str] = Field(default=None, max_length=10, description="16:9 / 9:16 / 1:1")
    image_size: Optional[str] = Field(default=None, max_length=20, description="Kích thước ảnh trong whitelist")
    image_reasoning_strength: Optional[str] = Field(default=None, max_length=20, description="low / high")
    image_failure_policy: Optional[str] = Field(
        default=None, description="skip: bỏ qua ảnh lỗi và vẫn xuất PDF | fail: dừng tác vụ"
    )
    page_size: Optional[str] = Field(default=None, max_length=10, description="A4 hoặc LETTER")
    title: Optional[str] = Field(default=None, max_length=200, description="Ghi đè tiêu đề truyện trên bìa")
    author: Optional[str] = Field(default=None, max_length=120, description="Tên tác giả hiển thị trên bìa")


class PdfExportCreateRequest(BaseModel):
    """创建 PDF 导出任务的请求体（可选参数；章节范围始终是“全项目”）"""

    options: Optional[PdfExportOptions] = None


class PdfExportImageResponse(BaseModel):
    """章节插图信息（不含路径/URL/base64/key）"""

    id: str
    chapter_id: Optional[str] = None
    chapter_number: Optional[int] = None
    sub_index: Optional[int] = None
    title: Optional[str] = None
    status: str
    provider: Optional[str] = None
    model: Optional[str] = None
    size: Optional[str] = None
    error: Optional[str] = None


class PdfExportJobResponse(BaseModel):
    """PDF 导出任务详情"""

    id: str
    project_id: str
    status: str
    progress: int = 0
    status_message: Optional[str] = None
    error_message: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    chapter_count: int = 0
    image_count: int = 0
    text_chars: int = 0
    page_count: Optional[int] = None
    file_size_bytes: Optional[int] = None
    has_pdf: bool = False
    artifact_stale: bool = Field(
        default=False, description="本次运行失败/取消，但仍有上一次成功生成的 PDF 可下载"
    )
    artifact_generation: int = 0
    artifact_created_at: Optional[str] = None
    run_attempt: int = 0
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None
    images: list[PdfExportImageResponse] = Field(default_factory=list)


class PdfExportJobSummary(BaseModel):
    """任务列表项（不含插图明细）"""

    id: str
    project_id: str
    status: str
    progress: int = 0
    status_message: Optional[str] = None
    error_message: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    chapter_count: int = 0
    image_count: int = 0
    text_chars: int = 0
    page_count: Optional[int] = None
    file_size_bytes: Optional[int] = None
    has_pdf: bool = False
    artifact_stale: bool = False
    artifact_generation: int = 0
    artifact_created_at: Optional[str] = None
    run_attempt: int = 0
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None


class PdfExportJobListResponse(BaseModel):
    """任务列表响应"""

    items: list[PdfExportJobSummary] = Field(default_factory=list)
    total: int = Field(default=0, description="项目内任务总数（应用 limit 之前）")


class PdfExportCapabilitiesResponse(BaseModel):
    """实例能力与限制（不含字体路径、密钥或本地目录）"""

    enabled: bool
    reportlab_available: bool
    font_available: bool
    allowed_page_sizes: list[str] = Field(default_factory=list)
    default_page_size: str = "A4"
    max_chapters: int
    max_text_chars: int
    max_images: int
    max_output_mb: int
    max_active_jobs: int
    job_timeout_seconds: int
    image_failure_policies: list[str] = Field(default_factory=list)
    default_image_failure_policy: str = "skip"
    image_enabled: bool = True
    default_image_provider: Optional[str] = None
    default_image_model: Optional[str] = None
    image_providers: list[VideoImageProviderInfo] = Field(default_factory=list)
