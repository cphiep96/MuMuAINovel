"""PDF 全本导出数据模型 - 记录一次"整个项目章节 → 单个 PDF"的导出过程"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, JSON, ForeignKey
from sqlalchemy.sql import func
from app.database import Base
import uuid


class PdfExportJob(Base):
    """PDF 导出任务表"""

    __tablename__ = "pdf_export_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True, comment="用户ID")
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目ID",
    )

    status = Column(
        String(20),
        default="pending",
        nullable=False,
        comment="任务状态: pending/running/completed/failed/cancelled",
    )
    progress = Column(Integer, default=0, comment="进度百分比(0-100)")
    status_message = Column(String(500), comment="当前状态消息")
    error_message = Column(Text, comment="失败原因")
    warnings = Column(JSON, comment="非致命警告列表(如部分插图被跳过)")

    # 输入与参数
    options = Column(JSON, comment="导出参数: include_cover/include_images/image_provider/image_failure_policy 等")

    # 结果概览（这些字段始终描述**当前可下载的产物**，重试失败时不会被覆盖）
    chapter_count = Column(Integer, default=0, comment="章节数量")
    image_count = Column(Integer, default=0, comment="已嵌入的插图数量")
    text_chars = Column(Integer, default=0, comment="正文总字符数")
    page_count = Column(Integer, comment="PDF 页数")
    output_path = Column(String(500), comment="PDF 相对路径(相对 PDF 存储根目录)")
    file_size_bytes = Column(Integer, comment="PDF 大小(字节)")

    # 产物与运行代次（用于区分“上一次成功的 PDF”与“本次运行”）
    output_generation = Column(Integer, default=0, comment="成功产物的代次，每次构建成功 +1")
    output_created_at = Column(DateTime, comment="当前产物生成时间")
    run_attempt = Column(Integer, default=0, comment="运行代次，每次开始执行 +1")

    # 跨进程执行权（多 worker 部署时用条件 UPDATE 抢占）
    worker_token = Column(String(64), comment="当前执行该任务的 worker 令牌")
    claimed_at = Column(DateTime, comment="执行权领取时间")

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    started_at = Column(DateTime, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<PdfExportJob(id={self.id[:8]}, status={self.status}, progress={self.progress}%)>"


class PdfExportImage(Base):
    """章节插图记录 - 每个章节一行，用于缓存与「只重做失败图片」策略

    只保存服务端受管目录内的相对路径；不保存远端 URL、base64 或任何密钥。
    """

    __tablename__ = "pdf_export_images"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("pdf_export_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属 PDF 任务ID",
    )
    chapter_id = Column(String(36), comment="来源章节ID")
    chapter_number = Column(Integer, comment="章节序号")
    sub_index = Column(Integer, default=1, comment="大纲下的子章节序号")
    title = Column(String(200), comment="章节标题")

    status = Column(
        String(20),
        default="pending",
        nullable=False,
        comment="图片状态: pending/generating/ready/failed/cancelled/skipped",
    )
    provider = Column(String(50), comment="图片 provider 名称")
    model = Column(String(100), comment="图片模型名")
    size = Column(String(20), comment="请求的图片尺寸")
    path = Column(String(500), comment="图片相对路径(相对任务目录)，仅服务端使用")
    error = Column(Text, comment="失败原因摘要(已 sanitize)")

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<PdfExportImage(job={self.job_id[:8]}, chapter={self.chapter_number}, status={self.status})>"
