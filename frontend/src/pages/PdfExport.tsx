import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Input,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  DeleteOutlined,
  DownloadOutlined,
  FilePdfOutlined,
  PictureOutlined,
  RedoOutlined,
  ReloadOutlined,
  StopOutlined,
} from '@ant-design/icons';
import api, { pdfExportApi } from '../services/api';
import { eventBus, EventNames } from '../store/eventBus';
import type {
  PdfExportCapabilities,
  PdfExportImage,
  PdfExportJob,
  PdfImageFailurePolicy,
  VideoImageProviderInfo,
} from '../types';

const { Text } = Typography;

interface ChapterItem {
  id: string;
  chapter_number: number;
  sub_index?: number;
  title: string;
  word_count?: number;
  content?: string;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: 'Đang chờ', color: 'default' },
  running: { text: 'Đang xuất', color: 'processing' },
  completed: { text: 'Hoàn thành', color: 'success' },
  failed: { text: 'Thất bại', color: 'error' },
  cancelled: { text: 'Đã hủy', color: 'default' },
};

const IMAGE_STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: 'Chờ tạo ảnh', color: 'default' },
  generating: { text: 'Đang tạo ảnh', color: 'processing' },
  ready: { text: 'Ảnh sẵn sàng', color: 'success' },
  failed: { text: 'Ảnh lỗi', color: 'error' },
  cancelled: { text: 'Đã hủy ảnh', color: 'default' },
  skipped: { text: 'Không dùng ảnh', color: 'default' },
};

const formatSize = (bytes?: number | null): string => {
  if (!bytes) return '—';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/** 读取响应头（兼容 axios AxiosHeaders 与普通对象，键名大小写不敏感） */
const headerValue = (headers: unknown, name: string): string | null => {
  if (!headers || typeof headers !== 'object') return null;
  const bag = headers as { get?: (key: string) => unknown };
  const raw =
    typeof bag.get === 'function'
      ? bag.get(name)
      : (headers as Record<string, unknown>)[name] ??
        (headers as Record<string, unknown>)[name.toLowerCase()];
  return typeof raw === 'string' ? raw : null;
};

/** 从 Content-Disposition 解析文件名（支持 filename* 的 UTF-8 形式） */
const extractFilename = (headers?: unknown): string | null => {
  const raw = headerValue(headers, 'content-disposition');
  if (!raw) return null;
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(raw);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      /* ignore malformed */
    }
  }
  const plainMatch = /filename="?([^";]+)"?/i.exec(raw);
  return plainMatch ? plainMatch[1].trim() : null;
};

const PdfExport: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();

  const [capabilities, setCapabilities] = useState<PdfExportCapabilities | null>(null);
  const [chapters, setChapters] = useState<ChapterItem[]>([]);
  const [jobs, setJobs] = useState<PdfExportJob[]>([]);
  const [activeJob, setActiveJob] = useState<PdfExportJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  // 导出参数
  const [includeCover, setIncludeCover] = useState(true);
  const [includeToc, setIncludeToc] = useState(true);
  const [includeImages, setIncludeImages] = useState(false);
  const [pageSize, setPageSize] = useState('A4');
  const [author, setAuthor] = useState('');
  const [imageProviderId, setImageProviderId] = useState<string | null>(null);
  const [imageModel, setImageModel] = useState<string | null>(null);
  const [imageAspectRatio, setImageAspectRatio] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState<string | null>(null);
  const [imageReasoningStrength, setImageReasoningStrength] = useState<string | null>(null);
  const [imageFailurePolicy, setImageFailurePolicy] = useState<PdfImageFailurePolicy>('skip');

  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const isActive = (job: PdfExportJob | null): boolean =>
    !!job && (job.status === 'pending' || job.status === 'running');

  const imageProviders: VideoImageProviderInfo[] = useMemo(
    () => capabilities?.image_providers || [],
    [capabilities]
  );
  const configuredImageProviders = useMemo(
    () => imageProviders.filter((item) => item.configured),
    [imageProviders]
  );
  const selectedImageProvider = useMemo(
    () => imageProviders.find((item) => item.id === imageProviderId) || null,
    [imageProviders, imageProviderId]
  );
  const imageFeatureEnabled = (capabilities?.image_enabled ?? true) && (capabilities?.enabled ?? true);
  // 未配置 provider 时不允许开启插图（服务端也会拒绝）
  const imageInvalid =
    includeImages && (!imageFeatureEnabled || !selectedImageProvider || !selectedImageProvider.configured);
  // capabilities 加载失败（null）或依赖缺失时不允许创建：不能再默认“可用”
  const capabilitiesReady = capabilities !== null;
  const pdfReady =
    capabilitiesReady &&
    (capabilities?.reportlab_available ?? false) &&
    (capabilities?.font_available ?? false);
  const canCreate =
    capabilitiesReady &&
    pdfReady &&
    chapters.length > 0 &&
    !imageInvalid &&
    (capabilities?.enabled ?? false);

  const loadJobs = useCallback(
    async (selectFirst = false) => {
      if (!projectId) return;
      try {
        const response = await pdfExportApi.listJobs(projectId);
        const items = response?.items || [];
        setJobs(items);
        if (selectFirst && items.length > 0) {
          await loadJobDetail(items[0].id);
        }
      } catch (error) {
        console.error('Tải danh sách tác vụ xuất PDF thất bại:', error);
      }
    },
    [projectId] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const loadJobDetail = useCallback(async (jobId: string): Promise<PdfExportJob | null> => {
    try {
      const detail = await pdfExportApi.getJob(jobId);
      setActiveJob(detail);
      return detail;
    } catch (error) {
      console.error('Tải chi tiết tác vụ xuất PDF thất bại:', error);
      return null;
    }
  }, []);

  useEffect(() => {
    const bootstrap = async () => {
      if (!projectId) return;
      try {
        setLoading(true);
        const [capabilityResponse, chapterResponse] = await Promise.all([
          pdfExportApi.getCapabilities(projectId).catch(() => null),
          api.get(`/chapters/project/${projectId}`).catch(() => null),
        ]);
        if (capabilityResponse) {
          setCapabilities(capabilityResponse);
          setPageSize(capabilityResponse.default_page_size);
          setImageFailurePolicy(capabilityResponse.default_image_failure_policy || 'skip');
          const providers = capabilityResponse.image_providers || [];
          const ready = providers.filter((item) => item.configured);
          const preferred =
            providers.find(
              (item) => item.id === capabilityResponse.default_image_provider && item.configured
            ) ||
            ready[0] ||
            null;
          setImageProviderId(preferred?.id ?? null);
          setImageModel(preferred ? capabilityResponse.default_image_model || preferred.default_model : null);
          setImageAspectRatio(preferred?.aspect_ratios?.[0] ?? null);
          setIncludeImages(false);
        }
        const chapterData = chapterResponse?.data || chapterResponse;
        setChapters(chapterData?.items || []);
        await loadJobs(true);
      } catch (error) {
        console.error('Khởi tạo trang xuất PDF thất bại:', error);
        message.error('Không tải được dữ liệu xuất PDF');
      } finally {
        setLoading(false);
      }
    };
    bootstrap();
  }, [projectId, loadJobs]);

  // 只要有任务在 pending/running 就轮询（不只当前选中的任务），列表状态同步更新
  useEffect(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    const activeIds = jobs.filter((job) => isActive(job)).map((job) => job.id);
    if (activeIds.length === 0) return;

    pollTimer.current = setInterval(async () => {
      const response = await pdfExportApi.listJobs(projectId!).catch(() => null);
      const items = response?.items || [];
      if (items.length > 0) setJobs(items);
      const freshActiveIds = items.filter((job) => isActive(job)).map((job) => job.id);
      // 用户选中的任务始终是跟踪目标（即使它刚刚结束，也要拉一次终态）；
      // 仅在未选中任何任务时才自动跟随正在运行的任务，避免面板被切到别的任务
      const selected = activeJob;
      const tracked =
        selected && (isActive(selected) || freshActiveIds.includes(selected.id))
          ? selected.id
          : selected
            ? null
            : freshActiveIds[0] ?? null;
      if (!tracked) return;
      await loadJobDetail(tracked);
    }, 2000);
    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [jobs, activeJob, projectId, loadJobDetail]);

  const applyImageProviderDefaults = (provider: VideoImageProviderInfo) => {
    setImageModel(provider.default_model);
    setImageAspectRatio(provider.aspect_ratios?.[0] ?? null);
    setImageSize(provider.default_size || null);
    setImageReasoningStrength(
      provider.supports_reasoning_strength ? imageReasoningStrength : null
    );
  };

  const handleIncludeImagesChange = (checked: boolean) => {
    if (checked) {
      if (!imageFeatureEnabled) {
        message.warning('Máy chủ đã tắt chức năng tạo ảnh');
        return;
      }
      if (configuredImageProviders.length === 0) {
        message.warning('Provider tạo ảnh chưa được cấu hình (cần META_MUSE_API_KEY)');
        return;
      }
      const provider =
        (selectedImageProvider && selectedImageProvider.configured ? selectedImageProvider : null) ||
        configuredImageProviders[0];
      setImageProviderId(provider.id);
      applyImageProviderDefaults(provider);
    }
    setIncludeImages(checked);
  };

  const handleImageProviderChange = (value: string) => {
    const provider = imageProviders.find((item) => item.id === value) || null;
    setImageProviderId(value);
    if (provider) applyImageProviderDefaults(provider);
  };

  const handleCreate = async () => {
    if (!projectId) return;
    if (chapters.length === 0) {
      message.warning('Dự án chưa có chương nào để xuất PDF');
      return;
    }
    if (imageInvalid) {
      message.warning('Provider tạo ảnh chưa được cấu hình, hãy tắt ảnh minh họa');
      return;
    }
    try {
      setCreating(true);
      const job = await pdfExportApi.createJob(projectId, {
        options: {
          include_cover: includeCover,
          include_images: includeImages,
          include_toc: includeToc,
          page_size: pageSize,
          author: author || null,
          image_provider: includeImages ? imageProviderId : null,
          image_model: includeImages ? imageModel : null,
          image_aspect_ratio: includeImages ? imageAspectRatio : null,
          image_size: includeImages ? imageSize : null,
          image_reasoning_strength: includeImages ? imageReasoningStrength : null,
          image_failure_policy: imageFailurePolicy,
        },
      });
      setActiveJob(job);
      await loadJobs();
      eventBus.emit(EventNames.BACKGROUND_TASK_CREATED, { projectId, taskId: job.id });
      message.success(`Đã tạo tác vụ xuất PDF cho ${job.chapter_count} chương, đang xử lý...`);
      if (includeImages) {
        message.info(
          `Tạo ảnh minh họa bằng ${selectedImageProvider?.label || 'provider ảnh'}: tối đa ${job.chapter_count} ảnh = ${job.chapter_count} lần gọi API có tính phí`,
        );
      }
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Tạo tác vụ xuất PDF thất bại');
    } finally {
      setCreating(false);
    }
  };

  const handleRetry = async (jobId: string) => {
    try {
      await pdfExportApi.retryJob(jobId);
      await loadJobDetail(jobId);
      await loadJobs();
      message.success('Đã xếp lại tác vụ (giữ ảnh đã tạo thành công)');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Không thử lại được tác vụ');
    }
  };

  const handleCancel = async (jobId: string) => {
    try {
      await pdfExportApi.cancelJob(jobId);
      await loadJobDetail(jobId);
      await loadJobs();
      message.success('Đã hủy tác vụ');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Không hủy được tác vụ');
    }
  };

  const handleDelete = async (jobId: string) => {
    try {
      await pdfExportApi.deleteJob(jobId);
      if (activeJob?.id === jobId) setActiveJob(null);
      await loadJobs();
      message.success('Đã xóa tác vụ và tệp PDF kèm ảnh minh họa');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Không xóa được tác vụ');
    }
  };

  const handleDownload = async (job: PdfExportJob) => {
    try {
      const response = await pdfExportApi.downloadPdf(job.id);
      const blob = response.data;
      const filename = extractFilename(response.headers) || `truyen-${job.id.slice(0, 8)}.pdf`;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      message.error('Không tải được PDF, vui lòng thử lại');
    }
  };

  const imageColumns = [
    {
      title: 'Chương',
      key: 'chapter',
      render: (_: unknown, row: PdfExportImage) => (
        <Text>
          Chương {row.chapter_number}
          {row.sub_index && row.sub_index > 1 ? `.${row.sub_index}` : ''}
          {row.title ? ` — ${row.title}` : ''}
        </Text>
      ),
    },
    {
      title: 'Trạng thái ảnh',
      key: 'image_status',
      width: 170,
      render: (_: unknown, row: PdfExportImage) => {
        const label = IMAGE_STATUS_LABELS[row.status] || { text: row.status, color: 'default' };
        const detail = [
          row.provider,
          row.model ? `Model: ${row.model}` : '',
          row.size ? `Kích thước: ${row.size}` : '',
          row.error ? `Lỗi: ${row.error}` : '',
        ]
          .filter(Boolean)
          .join(' · ');
        const tag = <Tag color={label.color}>{label.text}</Tag>;
        return detail ? <Tooltip title={detail}>{tag}</Tooltip> : tag;
      },
    },
  ];

  const jobColumns = [
    {
      title: 'Tác vụ',
      key: 'id',
      render: (_: unknown, job: PdfExportJob) => <Text code>{job.id.slice(0, 8)}</Text>,
    },
    {
      title: 'Trạng thái',
      key: 'status',
      render: (_: unknown, job: PdfExportJob) => (
        <Tag color={STATUS_LABELS[job.status]?.color || 'default'}>
          {STATUS_LABELS[job.status]?.text || job.status}
        </Tag>
      ),
    },
    {
      title: 'Tiến độ',
      key: 'progress',
      width: 160,
      render: (_: unknown, job: PdfExportJob) => (
        <Progress percent={job.progress} size="small" status={job.status === 'failed' ? 'exception' : undefined} />
      ),
    },
    {
      title: 'Kết quả',
      key: 'result',
      render: (_: unknown, job: PdfExportJob) => (
        <Space direction="vertical" size={2}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {job.chapter_count} chương · {job.page_count ? `${job.page_count} trang · ` : ''}
            {job.image_count} ảnh · {formatSize(job.file_size_bytes)}
          </Text>
          {job.has_pdf && job.artifact_stale && (
            <Tooltip title="Lần chạy gần nhất không hoàn tất; tệp bên dưới là PDF của lần chạy thành công trước đó">
              <Tag color="orange">PDF cũ (lần trước)</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: 'Thao tác',
      key: 'action',
      width: 230,
      render: (_: unknown, job: PdfExportJob) => (
        <Space size={4} wrap>
          <Button size="small" onClick={() => loadJobDetail(job.id)}>
            Chi tiết
          </Button>
          {job.has_pdf && (
            <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(job)}>
              PDF
            </Button>
          )}
          {isActive(job) ? (
            <Button size="small" danger icon={<StopOutlined />} onClick={() => handleCancel(job.id)}>
              Hủy
            </Button>
          ) : (
            <>
              <Button size="small" icon={<RedoOutlined />} onClick={() => handleRetry(job.id)}>
                Thử lại
              </Button>
              <Popconfirm
                title="Xóa tác vụ và toàn bộ tệp PDF/ảnh?"
                onConfirm={() => handleDelete(job.id)}
                okText="Xóa"
                cancelText="Đóng"
              >
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  const totalChars = chapters.reduce((sum, chapter) => sum + (chapter.content?.length || 0), 0);

  return (
    <div style={{ padding: 16 }}>
      <Card
        title={
          <Space>
            <FilePdfOutlined />
            <span>Xuất PDF full truyện</span>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => loadJobs()} loading={loading}>
            Làm mới
          </Button>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {!capabilitiesReady && (
            <Alert
              type="error"
              showIcon
              message="Không tải được cấu hình xuất PDF"
              description={
                <span style={{ fontSize: 12 }}>
                  Không xác minh được ReportLab/font và giới hạn của máy chủ nên nút xuất đang bị khóa. Hãy thử tải lại trang.
                </span>
              }
            />
          )}
          {capabilitiesReady && !pdfReady && (
            <Alert
              type="error"
              showIcon
              message="Máy chủ chưa sẵn sàng để tạo PDF"
              description={
                <span style={{ fontSize: 12 }}>
                  {capabilities?.reportlab_available === false
                    ? 'Thiếu ReportLab: hãy cài `pip install reportlab`.'
                    : 'Thiếu font Unicode: cài fonts-dejavu-core/fonts-noto-core hoặc đặt PDF_FONT_PATH.'}
                </span>
              }
            />
          )}
          <Alert
            type="info"
            showIcon
            message="Xuất toàn bộ chương của dự án thành một PDF"
            description={
              <span style={{ fontSize: 12 }}>
                Hệ thống lấy tất cả chương theo thứ tự chương/phần, dựng bìa, mục lục, nội dung và (tuỳ chọn) ảnh minh họa
                cho từng chương. PDF chạy nền nên có thể theo dõi tiến độ, hủy, thử lại và tải về sau.
              </span>
            }
          />

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="Số chương sẽ xuất">{chapters.length}</Descriptions.Item>
                <Descriptions.Item label="Tổng ký tự">{totalChars.toLocaleString('vi-VN')}</Descriptions.Item>
                <Descriptions.Item label="Giới hạn">
                  tối đa {capabilities?.max_chapters ?? '—'} chương · {capabilities?.max_images ?? '—'} ảnh ·{' '}
                  {capabilities?.max_output_mb ?? '—'} MB
                </Descriptions.Item>
                <Descriptions.Item label="Tác vụ song song">
                  {capabilities?.max_active_jobs ?? '—'} tác vụ chưa hoàn tất
                </Descriptions.Item>
              </Descriptions>
            </Col>

            <Col xs={24} lg={12}>
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Text strong>Tuỳ chọn PDF</Text>
                <Space size={20} wrap>
                  <Space size={8}>
                    <Switch checked={includeCover} onChange={setIncludeCover} />
                    <Text style={{ fontSize: 12 }}>Dùng ảnh bìa dự án</Text>
                  </Space>
                  <Space size={8}>
                    <Switch checked={includeToc} onChange={setIncludeToc} />
                    <Text style={{ fontSize: 12 }}>Tạo mục lục</Text>
                  </Space>
                </Space>

                <div>
                  <Text style={{ fontSize: 12 }}>Khổ giấy</Text>
                  <Select
                    style={{ width: 160 }}
                    value={pageSize}
                    onChange={setPageSize}
                    options={(capabilities?.allowed_page_sizes || ['A4']).map((item) => ({
                      label: item,
                      value: item,
                    }))}
                  />
                </div>

                <div>
                  <Text style={{ fontSize: 12 }}>Tên tác giả trên bìa (tuỳ chọn)</Text>
                  <Input
                    placeholder="Ví dụ: Nguyễn Văn A"
                    value={author}
                    maxLength={120}
                    onChange={(event) => setAuthor(event.target.value)}
                  />
                </div>

                <Space size={8}>
                  <Switch
                    checked={includeImages}
                    onChange={handleIncludeImagesChange}
                    disabled={!imageFeatureEnabled || configuredImageProviders.length === 0}
                  />
                  <Tooltip
                    title={
                      !imageFeatureEnabled
                        ? 'Quản trị viên đã tắt chức năng tạo ảnh'
                        : configuredImageProviders.length === 0
                          ? 'Provider tạo ảnh chưa được cấu hình (cần META_MUSE_API_KEY)'
                          : 'Mỗi chương sẽ được tạo một ảnh AI minh họa'
                    }
                  >
                    <Text style={{ fontSize: 12 }}>Tạo ảnh minh họa bằng Meta Muse (tính phí)</Text>
                  </Tooltip>
                </Space>

                {includeImages && selectedImageProvider && (
                  <>
                    <Row gutter={8}>
                      <Col span={12}>
                        <Text style={{ fontSize: 12 }}>Provider ảnh</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={imageProviderId ?? undefined}
                          onChange={handleImageProviderChange}
                          options={imageProviders.map((provider) => ({
                            label: provider.configured
                              ? provider.label
                              : `${provider.label} (chưa cấu hình)`,
                            value: provider.id,
                            disabled: !provider.configured,
                          }))}
                        />
                      </Col>
                      <Col span={12}>
                        <Text style={{ fontSize: 12 }}>Model ảnh</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={imageModel ?? selectedImageProvider.default_model}
                          onChange={setImageModel}
                          options={selectedImageProvider.models.map((model) => ({
                            label: model,
                            value: model,
                          }))}
                        />
                      </Col>
                    </Row>
                    <Row gutter={8}>
                      <Col span={8}>
                        <Text style={{ fontSize: 12 }}>Kích thước</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={imageSize || undefined}
                          placeholder={selectedImageProvider.default_size}
                          onChange={setImageSize}
                          allowClear
                          options={(selectedImageProvider.sizes || []).map((size) => ({
                            label: size,
                            value: size,
                          }))}
                        />
                      </Col>
                      <Col span={8}>
                        <Text style={{ fontSize: 12 }}>Tỉ lệ</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={imageAspectRatio ?? selectedImageProvider.aspect_ratios?.[0]}
                          onChange={setImageAspectRatio}
                          options={(selectedImageProvider.aspect_ratios || []).map((item) => ({
                            label: item,
                            value: item,
                          }))}
                        />
                      </Col>
                      <Col span={8}>
                        <Text style={{ fontSize: 12 }}>Khi ảnh lỗi</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={imageFailurePolicy}
                          onChange={(value) => setImageFailurePolicy(value as PdfImageFailurePolicy)}
                          options={(capabilities?.image_failure_policies || ['skip', 'fail']).map((policy) => ({
                            label:
                              policy === 'skip'
                                ? 'Bỏ qua ảnh, vẫn xuất PDF'
                                : 'Dừng tác vụ (báo lỗi)',
                            value: policy,
                          }))}
                        />
                      </Col>
                    </Row>
                    {selectedImageProvider.supports_reasoning_strength && (
                      <div>
                        <Text style={{ fontSize: 12 }}>Mức suy luận</Text>
                        <Select
                          style={{ width: 200 }}
                          value={imageReasoningStrength ?? undefined}
                          placeholder="Mặc định"
                          allowClear
                          onChange={setImageReasoningStrength}
                          options={(selectedImageProvider.reasoning_strengths || []).map((item) => ({
                            label: item,
                            value: item,
                          }))}
                        />
                      </div>
                    )}
                    <Alert
                      type="warning"
                      showIcon
                      icon={<PictureOutlined />}
                      message="Tạo ảnh minh họa có tính phí theo từng ảnh"
                      description={
                        <span style={{ fontSize: 12 }}>
                          {selectedImageProvider.cost_note} Mỗi chương có thể gọi Meta Muse một lần; ảnh tạo thành công được
                          lưu lại và tái sử dụng khi thử lại (không tạo lại để tránh tính phí hai lần). Nếu ảnh lỗi, chọn
                          "Bỏ qua ảnh, vẫn xuất PDF" để vẫn có bản full truyện chỉ có chữ.
                        </span>
                      }
                    />
                  </>
                )}

                {imageInvalid && (
                  <Alert
                    type="error"
                    showIcon
                    message="Provider tạo ảnh chưa được cấu hình"
                    description={
                      <span style={{ fontSize: 12 }}>
                        Máy chủ còn thiếu biến môi trường:{' '}
                        {selectedImageProvider?.missing_config?.length
                          ? selectedImageProvider.missing_config.join(', ')
                          : 'META_MUSE_API_KEY'}
                        . Hãy tắt ảnh minh họa để xuất PDF chỉ có chữ.
                      </span>
                    }
                  />
                )}

                <Button
                  type="primary"
                  icon={<FilePdfOutlined />}
                  loading={creating}
                  disabled={!canCreate}
                  onClick={handleCreate}
                >
                  Xuất PDF full truyện
                </Button>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Tác vụ chạy nền, bạn có thể rời trang. PDF chỉ có chữ thì không phát sinh chi phí; bật ảnh minh họa mới gọi
                  Meta Model API (cần API key đã cấu hình trên máy chủ).
                </Text>
              </Space>
            </Col>
          </Row>
        </Space>
      </Card>

      <Card title="Tác vụ xuất PDF" size="small" style={{ marginTop: 16 }}>
        {jobs.length === 0 ? (
          <Empty description="Chưa có tác vụ xuất PDF nào" />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={loading}
            dataSource={jobs}
            columns={jobColumns}
            pagination={{ pageSize: 6, size: 'small' }}
          />
        )}
      </Card>

      {activeJob && (
        <Card title="Chi tiết tác vụ" size="small" style={{ marginTop: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space wrap>
              <Tag color={STATUS_LABELS[activeJob.status]?.color || 'default'}>
                {STATUS_LABELS[activeJob.status]?.text || activeJob.status}
              </Tag>
              {activeJob.has_pdf && activeJob.artifact_stale && (
                <Tag color="orange">Đang giữ PDF của lần chạy trước</Tag>
              )}
              <Text type="secondary">
                {activeJob.chapter_count} chương · {activeJob.page_count ? `${activeJob.page_count} trang · ` : ''}
                {activeJob.image_count} ảnh · {formatSize(activeJob.file_size_bytes)}
              </Text>
            </Space>
            <Progress percent={activeJob.progress} status={activeJob.status === 'failed' ? 'exception' : undefined} />
            {activeJob.status_message && <Text type="secondary">{activeJob.status_message}</Text>}
            {activeJob.error_message && <Alert type="error" showIcon message={activeJob.error_message} />}
            {activeJob.warnings && activeJob.warnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message={`${activeJob.warnings.length} cảnh báo (một phần nội dung đã được bỏ qua)`}
                description={
                  <ul style={{ marginBottom: 0, paddingLeft: 18, fontSize: 12 }}>
                    {activeJob.warnings.slice(0, 10).map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                }
              />
            )}
            {activeJob.has_pdf && (
              <Button type="primary" icon={<DownloadOutlined />} onClick={() => handleDownload(activeJob)}>
                Tải PDF
              </Button>
            )}
            {activeJob.images && activeJob.images.length > 0 && (
              <Table
                size="small"
                rowKey="id"
                dataSource={activeJob.images}
                columns={imageColumns}
                pagination={{ pageSize: 8, size: 'small' }}
              />
            )}
          </Space>
        </Card>
      )}
    </div>
  );
};

export default PdfExport;
