import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  InputNumber,
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
  theme,
} from 'antd';
import {
  DeleteOutlined,
  DownloadOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  RedoOutlined,
  ReloadOutlined,
  StopOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import { chapterApi, videoExportApi } from '../services/api';
import { eventBus, EventNames } from '../store/eventBus';
import type {
  VideoExportCapabilities,
  VideoExportJob,
  VideoExportScene,
  VideoImageProviderInfo,
  VideoMotionMode,
  VideoMotionProviderInfo,
  VideoTTSProviderInfo,
} from '../types';
import './VideoExport.css';

const { Text } = Typography;

interface ChapterItem {
  id: string;
  chapter_number: number;
  title: string;
  word_count?: number;
  content?: string;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: 'Đang chờ', color: 'default' },
  running: { text: 'Đang dựng', color: 'processing' },
  completed: { text: 'Hoàn thành', color: 'success' },
  failed: { text: 'Thất bại', color: 'error' },
  cancelled: { text: 'Đã hủy', color: 'default' },
};

const SCENE_STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: 'Chờ dựng', color: 'default' },
  rendering: { text: 'Đang dựng', color: 'processing' },
  ready: { text: 'Sẵn sàng', color: 'success' },
  failed: { text: 'Lỗi', color: 'error' },
};

// 远端 provider 的操作状态（与场景渲染状态分开显示）
const MOTION_STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: 'Đang chờ provider', color: 'default' },
  running: { text: 'Provider đang tạo', color: 'processing' },
  completed: { text: 'Provider xong', color: 'success' },
  failed: { text: 'Provider lỗi', color: 'error' },
  expired: { text: 'Hết hạn', color: 'warning' },
  cancelled: { text: 'Đã hủy', color: 'default' },
  skipped: { text: 'Không dùng AI', color: 'default' },
};

// 场景图（image provider）状态
const IMAGE_STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: 'Chờ tạo ảnh', color: 'default' },
  generating: { text: 'Đang tạo ảnh', color: 'processing' },
  ready: { text: 'Ảnh sẵn sàng', color: 'success' },
  failed: { text: 'Ảnh lỗi', color: 'error' },
  cancelled: { text: 'Đã hủy ảnh', color: 'default' },
};

const MOTION_MODE_LABELS: Record<string, { text: string; hint: string }> = {
  local: {
    text: 'Cục bộ (FFmpeg)',
    hint: 'Không gọi API trả phí: ảnh bìa/ảnh phân cảnh được làm hiệu ứng pan/zoom; không tạo cảnh AI mới.',
  },
  remote: {
    text: 'Provider AI (tính phí)',
    hint: 'Mỗi phân cảnh là một lần gọi API image-to-video có tính phí; cần API key và ảnh tham chiếu.',
  },
  hybrid: {
    text: 'Kết hợp (AI ưu tiên)',
    hint: 'Ưu tiên provider AI; nếu provider lỗi và chính sách cho phép thì dựng lại bằng FFmpeg cục bộ.',
  },
};

const formatDuration = (seconds: number): string => {
  const total = Math.max(0, Math.round(seconds || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes} phút ${rest} giây` : `${rest} giây`;
};

const formatSize = (bytes?: number | null): string => {
  if (!bytes) return '—';
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
};

const saveBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};

/**
 * 项目内的Xuất phim trang：chọn chương → tạo tác vụ → xem phân cảnh → tải MP4/SRT
 */
const VideoExport: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams] = useSearchParams();
  const requestedJobId = searchParams.get('job');
  const { token } = theme.useToken();

  const [capabilities, setCapabilities] = useState<VideoExportCapabilities | null>(null);
  const [chapters, setChapters] = useState<ChapterItem[]>([]);
  const [selectedChapterIds, setSelectedChapterIds] = useState<string[]>([]);
  const [jobs, setJobs] = useState<VideoExportJob[]>([]);
  const [activeJob, setActiveJob] = useState<VideoExportJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [sceneActionId, setSceneActionId] = useState<string | null>(null);
  const [playerUrl, setPlayerUrl] = useState<string | null>(null);
  const playerUrlRef = useRef<string | null>(null);
  const playerJobIdRef = useRef<string | null>(null);
  const playerSectionRef = useRef<HTMLElement | null>(null);

  // 导出参数
  const [resolution, setResolution] = useState<string>('1280x720');
  const [fps, setFps] = useState<number>(24);
  const [useCover, setUseCover] = useState(true);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [ttsProviderId, setTtsProviderId] = useState<string | null>(null);
  const [ttsModel, setTtsModel] = useState<string | null>(null);
  const [charsPerScene, setCharsPerScene] = useState<number>(220);

  // 视频转场（motion video）参数
  const [motionMode, setMotionMode] = useState<VideoMotionMode>('local');
  const [motionProviderId, setMotionProviderId] = useState<string | null>(null);
  const [motionModel, setMotionModel] = useState<string | null>(null);
  const [motionResolution, setMotionResolution] = useState<string | null>(null);
  const [motionAspectRatio, setMotionAspectRatio] = useState<string | null>(null);
  const [hybridFallback, setHybridFallback] = useState(true);

  // 场景图生成（image provider，tính phí theo từng ảnh）
  const [generateSceneImages, setGenerateSceneImages] = useState(false);
  const [imageProviderId, setImageProviderId] = useState<string | null>(null);
  const [imageModel, setImageModel] = useState<string | null>(null);
  const [imageAspectRatio, setImageAspectRatio] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState<string | null>(null);
  const [imageReasoningStrength, setImageReasoningStrength] = useState<string | null>(null);

  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const revokePlayerUrl = useCallback(() => {
    if (playerUrlRef.current) {
      URL.revokeObjectURL(playerUrlRef.current);
      playerUrlRef.current = null;
    }
    playerJobIdRef.current = null;
    setPlayerUrl(null);
  }, []);

  const isActive = (job: VideoExportJob | null): boolean =>
    !!job && (job.status === 'pending' || job.status === 'running');

  const loadPlayerBlob = useCallback(
    async (job: VideoExportJob) => {
      if (!job.has_video) {
        revokePlayerUrl();
        return;
      }
      if (playerJobIdRef.current === job.id && playerUrlRef.current) {
        return;
      }
      const requestedId = job.id;
      playerJobIdRef.current = requestedId;
      try {
        const blob = await videoExportApi.downloadVideo(requestedId);
        if (playerJobIdRef.current !== requestedId) {
          return;
        }
        if (!(blob instanceof Blob) || blob.size === 0 || blob.type.includes('json')) {
          throw new Error('Tệp video không hợp lệ');
        }
        if (playerUrlRef.current) {
          URL.revokeObjectURL(playerUrlRef.current);
        }
        const nextUrl = URL.createObjectURL(blob);
        playerUrlRef.current = nextUrl;
        setPlayerUrl(nextUrl);
      } catch (error) {
        if (playerJobIdRef.current === requestedId) {
          console.error('Không tải được video để xem trong trang:', error);
          revokePlayerUrl();
        }
      }
    },
    [revokePlayerUrl]
  );

  const motionProviders: VideoMotionProviderInfo[] = useMemo(
    () => capabilities?.motion_providers || [],
    [capabilities]
  );
  const remoteProviders = useMemo(
    () => motionProviders.filter((item) => item.kind === 'remote'),
    [motionProviders]
  );
  const configuredRemoteProviders = useMemo(
    () => remoteProviders.filter((item) => item.configured),
    [remoteProviders]
  );
  const selectedProvider = useMemo(
    () => motionProviders.find((item) => item.id === motionProviderId) || null,
    [motionProviders, motionProviderId]
  );
  // 当前模型对应的限制（Veo 3.1 只有 8 秒、Lite 不支持 4k…），UI 只能给出必然被接受的组合
  const selectedModelLimits = useMemo(() => {
    if (!selectedProvider) return null;
    const model = motionModel || selectedProvider.default_model;
    return selectedProvider.model_limits?.[model] || selectedProvider.limits;
  }, [selectedProvider, motionModel]);
  const durationHint = useMemo(() => {
    if (!selectedModelLimits) return '';
    const options = selectedModelLimits.duration_options || [];
    if (options.length === 1) return `${options[0]} giây`;
    if (options.length > 1) return `${options.join('/')} giây`;
    return `${selectedModelLimits.min_duration_seconds}–${selectedModelLimits.max_duration_seconds} giây`;
  }, [selectedModelLimits]);
  const remoteModeSelected = motionMode === 'remote' || motionMode === 'hybrid';
  // 选择远端但没有可用 provider（未选/未配置）时不得提交请求
  const motionInvalid = remoteModeSelected && (!selectedProvider || !selectedProvider.configured);
  const remoteModeActive = (activeJob?.motion_mode || 'local') !== 'local';

  // 场景图 provider（image generation）
  const imageProviders: VideoImageProviderInfo[] = useMemo(
    () => capabilities?.image_providers || [],
    [capabilities]
  );
  const configuredImageProviders = useMemo(
    () => imageProviders.filter((item) => item.configured),
    [imageProviders]
  );
  const imageFeatureEnabled = capabilities?.image_enabled ?? true;
  const selectedImageProvider = useMemo(
    () => imageProviders.find((item) => item.id === imageProviderId) || null,
    [imageProviders, imageProviderId]
  );
  // 未配置 provider 时不允许开启（服务端也会拒绝），并且不得发送无效请求
  const imageInvalid =
    generateSceneImages &&
    (!imageFeatureEnabled || !selectedImageProvider || !selectedImageProvider.configured);

  const ttsProviders: VideoTTSProviderInfo[] = useMemo(
    () => capabilities?.tts_providers || [],
    [capabilities]
  );
  const selectedTtsProvider = useMemo(
    () =>
      ttsProviders.find((item) => item.id === ttsProviderId) ||
      ttsProviders.find((item) => item.id === (capabilities?.default_tts_provider || 'omnivoice')) ||
      ttsProviders.find((item) => item.configured) ||
      ttsProviders[0] ||
      null,
    [ttsProviders, ttsProviderId, capabilities?.default_tts_provider]
  );
  const ttsEnglishOnly = (selectedTtsProvider?.languages || []).length === 1 && selectedTtsProvider?.languages?.[0] === 'en';
  const selectedChapters = useMemo(
    () => chapters.filter((chapter) => selectedChapterIds.includes(chapter.id)),
    [chapters, selectedChapterIds]
  );
  const sceneImageUrl = (jobId: string, sceneId: string) =>
    `/api/video-export/jobs/${jobId}/scenes/${sceneId}/image`;
  const storyboardScenes = activeJob?.scenes || [];

  const applyImageProviderDefaults = (provider: VideoImageProviderInfo) => {
    const aspect = imageAspectRatio || capabilities?.default_image_aspect_ratio || provider.aspect_ratios[0];
    setImageModel(provider.default_model);
    setImageAspectRatio(aspect);
    setImageSize(provider.sizes.includes(imageSize || '') ? imageSize : null);
    setImageReasoningStrength(
      provider.supports_reasoning_strength ? imageReasoningStrength : null
    );
  };

  const loadJobs = useCallback(
    async (selectFirst = false, preferredJobId?: string | null) => {
      if (!projectId) return;
      try {
        const response = await videoExportApi.listJobs(projectId);
        const items = (response?.items || []) as VideoExportJob[];
        setJobs(items);
        if (selectFirst && items.length > 0) {
          const preferred =
            items.find((job) => preferredJobId && job.id === preferredJobId) ||
            items.find((job) => job.has_video && job.status === 'completed') ||
            items.find((job) => job.has_video) ||
            items[0];
          const detail = await videoExportApi.getJob(preferred.id);
          setActiveJob(detail);
          void loadPlayerBlob(detail);
        }
      } catch (error) {
        console.error('Tải danh sách tác vụ xuất phim thất bại:', error);
      }
    },
    [projectId, loadPlayerBlob]
  );

  const loadJobDetail = useCallback(
    async (jobId: string) => {
      try {
        const detail = await videoExportApi.getJob(jobId);
        setActiveJob(detail);
        void loadPlayerBlob(detail);
        return detail;
      } catch (error) {
        console.error('Tải chi tiết tác vụ xuất phim thất bại:', error);
        return null;
      }
    },
    [loadPlayerBlob]
  );

  // 初始化：能力 + 章节 + 任务列表
  useEffect(() => {
    const bootstrap = async () => {
      if (!projectId) return;
      try {
        setLoading(true);
        const [capabilityResponse, chapterItems] = await Promise.all([
          videoExportApi.getCapabilities().catch(() => null),
          chapterApi.getChapters(projectId).catch(() => [] as ChapterItem[]),
        ]);

        if (capabilityResponse) {
          setCapabilities(capabilityResponse);
          setResolution(capabilityResponse.default_resolution);
          setFps(capabilityResponse.default_fps);
          setCharsPerScene(capabilityResponse.default_narration_chars_per_scene);

          // 转场默认值：服务端若已配置远端 provider 才允许默认走 remote/hybrid
          const providers = capabilityResponse.motion_providers || [];
          const remotes = providers.filter((item) => item.kind === 'remote' && item.configured);
          const preferred =
            providers.find((item) => item.id === capabilityResponse.default_motion_provider && item.configured) ||
            remotes[0] ||
            null;
          const defaultMode = (capabilityResponse.default_motion_mode || 'local') as VideoMotionMode;
          const usableMode: VideoMotionMode =
            defaultMode !== 'local' && preferred ? defaultMode : 'local';
          const preferredModel = preferred
            ? capabilityResponse.default_motion_model || preferred.default_model
            : null;
          // 限制按模型区分（Veo 3.1 只接受 8 秒，Lite 不支持 4k…）
          const preferredLimits = preferred
            ? preferred.model_limits?.[preferredModel || ''] || preferred.limits
            : null;
          setMotionMode(usableMode);
          setMotionProviderId(preferred?.id ?? null);
          setMotionModel(preferredModel);
          setMotionResolution(
            capabilityResponse.default_motion_resolution || preferredLimits?.default_resolution || null
          );
          setMotionAspectRatio(preferredLimits?.aspect_ratios?.[0] ?? null);
          setHybridFallback(capabilityResponse.hybrid_fallback_on_error ?? true);

          // 场景图默认值：只在 provider 已配置时才允许默认开启
          const imageProviderList = capabilityResponse.image_providers || [];
          const readyImageProviders = imageProviderList.filter((item) => item.configured);
          const preferredImage =
            imageProviderList.find(
              (item) => item.id === capabilityResponse.default_image_provider && item.configured
            ) ||
            readyImageProviders[0] ||
            null;
          setImageProviderId(preferredImage?.id ?? null);
          setImageModel(preferredImage ? capabilityResponse.default_image_model || preferredImage.default_model : null);
          setImageAspectRatio(
            capabilityResponse.default_image_aspect_ratio || preferredImage?.aspect_ratios?.[0] || null
          );
          setImageSize(capabilityResponse.default_image_size || null);
          setGenerateSceneImages(Boolean(preferredImage));
          setTtsProviderId(capabilityResponse.default_tts_provider || 'omnivoice');
          setTtsModel(capabilityResponse.default_tts_model || 'female');
          setTtsEnabled(Boolean(capabilityResponse.tts_available));
        }

        setChapters(chapterItems);
        setSelectedChapterIds(
          chapterItems.filter((chapter) => chapter.content && chapter.content.trim()).map((chapter) => chapter.id)
        );
        await loadJobs(true, requestedJobId);
      } catch (error) {
        console.error('Khởi tạo trang xuất phim thất bại:', error);
        message.error('Không tải được dữ liệu xuất phim');
      } finally {
        setLoading(false);
      }
    };
    bootstrap();
  }, [projectId, loadJobs]);

  useEffect(() => {
    const handleOpenJob = (payload?: unknown) => {
      let jobId = '';
      if (payload && typeof payload === 'object' && 'jobId' in payload) {
        const rawId = payload.jobId;
        if (typeof rawId === 'string') jobId = rawId;
      }
      if (!jobId) return;
      void loadJobDetail(jobId).then((detail) => {
        if (detail?.has_video) {
          playerSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    };
    eventBus.on(EventNames.OPEN_VIDEO_EXPORT_JOB, handleOpenJob);
    return () => {
      eventBus.off(EventNames.OPEN_VIDEO_EXPORT_JOB, handleOpenJob);
    };
  }, [loadJobDetail]);

  useEffect(() => {
    if (!requestedJobId) return;
    void loadJobDetail(requestedJobId).then((detail) => {
      if (detail?.has_video) {
        playerSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }, [requestedJobId, loadJobDetail]);

  // 轮询运行中的任务
  useEffect(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    if (!activeJob || !isActive(activeJob)) return;

    pollTimer.current = setInterval(async () => {
      const detail = await loadJobDetail(activeJob.id);
      if (detail && !isActive(detail)) {
        await loadJobs();
        if (detail.status === 'completed') {
          message.success('Xuất phim hoàn tất. Video nằm ngay dưới nút dựng phim.');
          playerSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } else if (detail.status === 'failed') {
          message.error(detail.error_message || 'Dựng phim thất bại');
        }
      }
    }, 2000);

    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [activeJob, loadJobDetail, loadJobs]);

  useEffect(() => {
    return () => {
      revokePlayerUrl();
    };
  }, [revokePlayerUrl]);

  /** 选择 provider/模型后，把分辨率与比例收敛到该模型必然支持的取值 */
  const applyProviderDefaults = (provider: VideoMotionProviderInfo, model?: string | null) => {
    const limits = provider.model_limits?.[model || provider.default_model] || provider.limits;
    setMotionModel(model ?? provider.default_model);
    setMotionResolution(limits.default_resolution);
    setMotionAspectRatio(limits.aspect_ratios?.[0] ?? null);
  };

  const handleMotionModeChange = (mode: VideoMotionMode) => {
    setMotionMode(mode);
    if (mode === 'local') return;
    const provider =
      (selectedProvider && selectedProvider.kind === 'remote' && selectedProvider.configured
        ? selectedProvider
        : null) || configuredRemoteProviders[0];
    if (provider) {
      setMotionProviderId(provider.id);
      applyProviderDefaults(provider, provider.default_model);
    }
    // 远端 provider 不会把 TTS 音轨合进返回的片段
    setTtsEnabled(false);
  };

  const handleMotionProviderChange = (providerId: string) => {
    const provider = motionProviders.find((item) => item.id === providerId) || null;
    setMotionProviderId(providerId);
    if (provider) {
      applyProviderDefaults(provider, provider.default_model);
      return;
    }
    setMotionModel(null);
    setMotionResolution(null);
    setMotionAspectRatio(null);
  };

  const handleMotionModelChange = (model: string) => {
    if (!selectedProvider) {
      setMotionModel(model);
      return;
    }
    applyProviderDefaults(selectedProvider, model);
  };

  const handleGenerateSceneImagesChange = (checked: boolean) => {
    if (checked) {
      if (!imageFeatureEnabled) {
        message.warning('Máy chủ đã tắt chức năng tạo ảnh phân cảnh');
        return;
      }
      if (configuredImageProviders.length === 0) {
        message.warning('Provider tạo ảnh chưa được cấu hình trên máy chủ (cần META_MUSE_API_KEY)');
        return;
      }
      const provider =
        (selectedImageProvider && selectedImageProvider.configured ? selectedImageProvider : null) ||
        configuredImageProviders[0];
      setImageProviderId(provider.id);
      applyImageProviderDefaults(provider);
    }
    setGenerateSceneImages(checked);
  };

  const handleImageProviderChange = (providerId: string) => {
    const provider = imageProviders.find((item) => item.id === providerId) || null;
    setImageProviderId(providerId);
    if (provider) {
      applyImageProviderDefaults(provider);
    }
  };

  const handleImageSizeChange = (size: string) => {
    setImageSize(size);
    // 尺寸与比例必须自洽：按尺寸反推受支持的比例，避免提交必然 400 的组合
    const inferred = size.includes('x')
      ? (() => {
          const [w, h] = size.split('x').map((part) => Number(part));
          if (!w || !h) return null;
          if (w === h) return '1:1';
          return w > h ? '16:9' : '9:16';
        })()
      : null;
    if (inferred) setImageAspectRatio(inferred);
  };

  const handleCreate = async () => {
    if (!projectId) return;
    if (selectedChapterIds.length === 0) {
      message.warning('Vui lòng chọn ít nhất một chương');
      return;
    }
    if (motionInvalid) {
      message.warning('Provider AI chưa được cấu hình, hãy chọn provider khác hoặc dùng chế độ cục bộ');
      return;
    }
    if (imageInvalid) {
      message.warning('Provider tạo ảnh chưa được cấu hình, hãy tắt tùy chọn tạo ảnh phân cảnh');
      return;
    }
    try {
      setCreating(true);
      const job = await videoExportApi.createJob({
        project_id: projectId,
        chapter_ids: selectedChapterIds,
        options: {
          resolution,
          fps,
          use_project_cover: useCover,
          tts_enabled: remoteModeSelected ? false : ttsEnabled && !!capabilities?.tts_available,
          tts_provider: remoteModeSelected ? null : ttsProviderId || capabilities?.default_tts_provider || 'omnivoice',
          tts_model: remoteModeSelected ? null : ttsModel,
          narration_chars_per_scene: charsPerScene,
          motion_mode: motionMode,
          motion_provider: remoteModeSelected ? motionProviderId : null,
          motion_model: remoteModeSelected ? motionModel : null,
          motion_resolution: remoteModeSelected ? motionResolution : null,
          motion_aspect_ratio: remoteModeSelected ? motionAspectRatio : null,
          hybrid_fallback_on_error: motionMode === 'hybrid' ? hybridFallback : false,
          generate_scene_images: generateSceneImages,
          image_provider: generateSceneImages ? imageProviderId : null,
          image_model: generateSceneImages ? imageModel : null,
          image_aspect_ratio: generateSceneImages ? imageAspectRatio : null,
          image_size: generateSceneImages ? imageSize : null,
          image_reasoning_strength: generateSceneImages ? imageReasoningStrength : null,
        },
      });
      revokePlayerUrl();
      setActiveJob(job);
      await loadJobs();
      // 通知悬浮任务框立即刷新并展开，和新任务行为保持一致
      eventBus.emit(EventNames.BACKGROUND_TASK_CREATED, { projectId, taskId: job.id });
      message.success(`Đã tạo tác vụ với ${job.scene_count} phân cảnh, đang dựng phim...`);
      if (remoteModeSelected) {
        message.info(
          `Chế độ AI: mỗi phân cảnh là một lần gọi API có tính phí (clip ${durationHint || 'theo model'})`,
        );
      }
      if (generateSceneImages) {
        message.info(
          `Tạo ảnh phân cảnh bằng ${selectedImageProvider?.label || 'provider ảnh'}: ${job.scene_count} ảnh = ${job.scene_count} lần gọi API có tính phí`,
        );
      }
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Tạo tác vụ xuất phim thất bại');
    } finally {
      setCreating(false);
    }
  };

  const handleRetryJob = async (jobId: string) => {
    try {
      await videoExportApi.retryJob(jobId);
      await loadJobDetail(jobId);
      await loadJobs();
      if (projectId) {
        eventBus.emit(EventNames.BACKGROUND_TASK_CREATED, { projectId, taskId: jobId });
      }
      message.success('Đã đưa tác vụ vào hàng đợi dựng lại');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Thử lại thất bại');
    }
  };

  const handleRetryScene = async (jobId: string, sceneId: string) => {
    try {
      setSceneActionId(sceneId);
      await videoExportApi.retryScene(jobId, sceneId);
      await loadJobDetail(jobId);
      message.success('Đã đưa phân cảnh vào hàng đợi dựng lại');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Thử lại phân cảnh thất bại');
    } finally {
      setSceneActionId(null);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    try {
      await videoExportApi.cancelJob(jobId);
      await loadJobDetail(jobId);
      await loadJobs();
      message.success('Đã hủy tác vụ');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Hủy tác vụ thất bại');
    }
  };

  const handleDeleteJob = async (jobId: string) => {
    try {
      await videoExportApi.deleteJob(jobId);
      if (activeJob?.id === jobId) {
        revokePlayerUrl();
        setActiveJob(null);
      }
      await loadJobs();
      message.success('Đã xóa tác vụ và tệp đính kèm');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Xóa tác vụ thất bại');
    }
  };

  const handleDownload = async (jobId: string, kind: 'video' | 'subtitles') => {
    try {
      const blob =
        kind === 'video'
          ? await videoExportApi.downloadVideo(jobId)
          : await videoExportApi.downloadSubtitles(jobId);
      saveBlob(blob, `${jobId.slice(0, 8)}.${kind === 'video' ? 'mp4' : 'srt'}`);
    } catch (error) {
      // 错误提示统一由 api 拦截器处理（会解析 blob 内的 detail），这里只记录日志
      console.error('Tải tệp thất bại:', error);
    }
  };

  const ffmpegReady = capabilities?.ffmpeg_available ?? true;
  const featureEnabled = capabilities?.enabled ?? true;
  const canCreate = featureEnabled && ffmpegReady && !motionInvalid && !imageInvalid;

  const jobOptions = useMemo(
    () =>
      (jobs || []).map((job) => ({
        label: `${(job.created_at || '').replace('T', ' ').slice(0, 19)} · ${job.scene_count} cảnh · ${
          STATUS_LABELS[job.status]?.text || job.status
        }`,
        value: job.id,
      })),
    [jobs]
  );

  const sceneColumns = [
    {
      title: 'Khung',
      key: 'frame',
      width: 92,
      render: (_: unknown, scene: VideoExportScene) =>
        scene.has_image && activeJob ? (
          <img
            className="scene-thumb"
            src={sceneImageUrl(activeJob.id, scene.id)}
            alt={scene.title || `Cảnh ${scene.scene_index + 1}`}
          />
        ) : (
          <div className="scene-thumb scene-thumb-empty" />
        ),
    },
    {
      title: '#',
      dataIndex: 'scene_index',
      width: 56,
      render: (value: number) => <Text strong>{value + 1}</Text>,
    },
    {
      title: 'Chương',
      dataIndex: 'chapter_number',
      width: 180,
      render: (value: number, scene: VideoExportScene) => (
        <Tooltip title={scene.title || ''}>
          <Text ellipsis style={{ maxWidth: 160 }}>
            {value ? `Chương ${value}` : '—'}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: 'Lời kể',
      dataIndex: 'narration',
      render: (value: string) => (
        <Tooltip title={value}>
          <Text ellipsis style={{ maxWidth: 320 }}>
            {value}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: 'Thời lượng',
      dataIndex: 'duration_seconds',
      width: 110,
      render: (value: number) => `${Number(value || 0).toFixed(1)}s`,
    },
    {
      title: 'Gợi ý hình ảnh',
      dataIndex: 'visual_prompt',
      render: (value: string) => (
        <Tooltip title={value}>
          <Text type="secondary" ellipsis style={{ maxWidth: 280 }}>
            {value}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      width: 120,
      render: (value: string, scene: VideoExportScene) => {
        const label = SCENE_STATUS_LABELS[value] || { text: value, color: 'default' };
        const tag = <Tag color={label.color}>{label.text}</Tag>;
        return scene.error_message ? <Tooltip title={scene.error_message}>{tag}</Tooltip> : tag;
      },
    },
    {
      title: 'Ảnh cảnh',
      key: 'image',
      width: 170,
      render: (_: unknown, scene: VideoExportScene) => {
        if (!scene.image_provider && !scene.image_status) return <Text type="secondary">—</Text>;
        const label = IMAGE_STATUS_LABELS[scene.image_status || ''] || {
          text: scene.image_status || '',
          color: 'default',
        };
        const detail = [
          imageProviders.find((item) => item.id === scene.image_provider)?.label || scene.image_provider,
          scene.image_model ? `Model: ${scene.image_model}` : '',
          scene.image_size ? `Kích thước: ${scene.image_size}` : '',
          scene.image_error ? `Lỗi: ${scene.image_error}` : '',
        ]
          .filter(Boolean)
          .join(' · ');
        const tag = <Tag color={label.color}>{label.text}</Tag>;
        return detail ? <Tooltip title={detail}>{tag}</Tooltip> : tag;
      },
    },
    {
      title: 'Chuyển động',
      key: 'motion',
      width: 190,
      render: (_: unknown, scene: VideoExportScene) => {
        const providerLabel = motionProviders.find((item) => item.id === scene.motion_provider)?.label;
        const detail = [
          scene.motion_model ? `Model: ${scene.motion_model}` : '',
          scene.clip_duration_seconds ? `Độ dài clip: ${scene.clip_duration_seconds}s` : '',
          scene.provider_error ? `Lỗi provider: ${scene.provider_error}` : '',
        ]
          .filter(Boolean)
          .join(' · ');
        const tag = (
          <Tag color={scene.motion_fallback_used ? 'orange' : 'blue'}>
            {scene.motion_fallback_used
              ? 'FFmpeg (dự phòng)'
              : providerLabel || scene.motion_provider || 'FFmpeg'}
          </Tag>
        );
        return (
          <Space direction="vertical" size={2}>
            {detail ? <Tooltip title={detail}>{tag}</Tooltip> : tag}
            {scene.motion_status && (
              <Tag color={MOTION_STATUS_LABELS[scene.motion_status]?.color || 'default'}>
                {MOTION_STATUS_LABELS[scene.motion_status]?.text || scene.motion_status}
              </Tag>
            )}
          </Space>
        );
      },
    },
    {
      title: 'Thao tác',
      key: 'action',
      width: 120,
      render: (_: unknown, scene: VideoExportScene) => (
        <Button
          size="small"
          type="link"
          icon={<RedoOutlined />}
          loading={sceneActionId === scene.id}
          disabled={!activeJob || isActive(activeJob)}
          onClick={() => activeJob && handleRetryScene(activeJob.id, scene.id)}
        >
          Dựng lại
        </Button>
      ),
    },
  ];

  const chapterColumns = [
    {
      title: 'Chương',
      dataIndex: 'chapter_number',
      width: 100,
      render: (value: number) => `Chương ${value}`,
    },
    { title: 'Tiêu đề', dataIndex: 'title' },
    {
      title: 'Số chữ',
      dataIndex: 'word_count',
      width: 110,
      render: (value: number) => (value ? `${value} chữ` : '—'),
    },
    {
      title: 'Trạng thái',
      key: 'has_content',
      width: 130,
      render: (_: unknown, chapter: ChapterItem) =>
        chapter.content && chapter.content.trim() ? (
          <Tag color="success">Có nội dung</Tag>
        ) : (
          <Tag>Chưa có nội dung</Tag>
        ),
    },
  ];

  return (
    <main className="cinematic-studio" aria-label="Xưởng dựng phim">
      <header className="cinematic-header">
        <div>
          <p className="cinematic-kicker">Story to screen</p>
          <h1 className="cinematic-title">Xưởng hình ảnh điện ảnh</h1>
          <p className="cinematic-description">
            Chọn chương, tạo khung hình AI nhất quán và dựng storyboard thành một bản phim có phụ đề.
          </p>
        </div>
        <div className="cinematic-header-meta" aria-label="Tổng quan dự án phim">
          <div className="cinematic-meta"><strong>{selectedChapterIds.length}</strong><span>chương đã chọn</span></div>
          <div className="cinematic-meta"><strong>{activeJob?.scene_count ?? 0}</strong><span>phân cảnh hiện tại</span></div>
          <div className="cinematic-meta"><strong>{fps}</strong><span>khung hình / giây</span></div>
        </div>
      </header>

      <section className="shot-rail" aria-label="Dải phân cảnh dự kiến">
        <div className="shot-rail-head">
          <span className="shot-rail-title">Dải phân cảnh</span>
          <span className="shot-rail-status">
            {storyboardScenes.length
              ? `${storyboardScenes.filter((scene) => scene.has_image).length}/${storyboardScenes.length} khung đã có ảnh`
              : selectedChapters.length
                ? `${selectedChapters.length} chương sẵn sàng cho storyboard`
                : 'Chọn chương để bắt đầu dàn cảnh'}
          </span>
        </div>
        <div className="shot-strip">
          {storyboardScenes.length ? storyboardScenes.map((scene) => (
            <article className={`shot${scene.has_image ? ' shot-has-media' : ''}`} key={scene.id}>
              {scene.has_image && activeJob ? (
                <img
                  className="shot-frame"
                  src={sceneImageUrl(activeJob.id, scene.id)}
                  alt={scene.title || `Cảnh ${scene.scene_index + 1}`}
                />
              ) : null}
              <span className="shot-number">CẢNH {String(scene.scene_index + 1).padStart(2, '0')}</span>
              <div className="shot-title">{scene.title || scene.narration || `Phân cảnh ${scene.scene_index + 1}`}</div>
            </article>
          )) : selectedChapters.length ? selectedChapters.map((chapter, index) => (
            <article className="shot" key={chapter.id}>
              <span className="shot-number">CẢNH {String(index + 1).padStart(2, '0')}</span>
              <div className="shot-title">{chapter.title || `Chương ${chapter.chapter_number}`}</div>
            </article>
          )) : <div className="shot-empty">Các khung hình sẽ xuất hiện tại đây.</div>}
        </div>
      </section>

      <section ref={playerSectionRef} className="cinematic-player-stage" aria-label="Xem phim đã dựng">
        <div className="cinematic-player-head">
          <span className="cinematic-player-title">Xem phim</span>
          <span className="cinematic-player-status">
            {activeJob?.has_video
              ? `${formatDuration(activeJob.duration_seconds)} · ${formatSize(activeJob.video_size_bytes)}`
              : isActive(activeJob)
                ? activeJob?.status_message || 'Đang dựng phim...'
                : 'Phim sẽ xuất hiện tại đây sau khi dựng xong'}
          </span>
        </div>
        {playerUrl ? (
          <video
            className="cinematic-player"
            controls
            playsInline
            preload="metadata"
            src={playerUrl}
          />
        ) : (
          <div className="cinematic-player-empty">
            {isActive(activeJob)
              ? 'Đang ghép các phân cảnh thành video. Khi xong, phim sẽ tự hiện ở đây.'
              : jobs.some((job) => job.has_video)
                ? 'Đã có phim. Đang tải để phát…'
                : 'Chưa có video. Bấm “Tạo storyboard và dựng phim”, phim sẽ hiện ngay tại đây.'}
          </div>
        )}
        {activeJob?.has_video && (
          <Space wrap className="cinematic-player-actions">
            <Button
              icon={<DownloadOutlined />}
              disabled={activeJob.status !== 'completed'}
              onClick={() => handleDownload(activeJob.id, 'video')}
            >
              Tải MP4
            </Button>
            <Button
              icon={<FileTextOutlined />}
              disabled={!activeJob.has_subtitles || activeJob.status !== 'completed'}
              onClick={() => handleDownload(activeJob.id, 'subtitles')}
            >
              Tải SRT
            </Button>
          </Space>
        )}
      </section>

      <section className="cinematic-workbench">
      <Card className="cinematic-settings"
        title={
          <Space>
            <VideoCameraOutlined />
            <span>Thiết lập sản xuất</span>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => loadJobs()} size="small">
            Đồng bộ tác vụ
          </Button>
        }
      >
        {!featureEnabled && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Chức năng xuất phim đang tắt"
            description="Quản trị viên đã tắt chức năng này trên máy chủ (VIDEO_EXPORT_ENABLED=false)."
          />
        )}

        {featureEnabled && !ffmpegReady && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="Máy chủ chưa có FFmpeg"
            description="Không thể dựng MP4. Hãy cài FFmpeg rồi khởi động lại dịch vụ (hoặc đặt biến môi trường VIDEO_FFMPEG_BINARY trỏ tới ffmpeg)."
          />
        )}

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Text strong>Chọn chương để dựng phim</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Tối đa {capabilities?.max_chapters ?? 10} chương, {capabilities?.max_scenes ?? 40} phân cảnh, tổng
                thời lượng {formatDuration(capabilities?.max_duration_seconds ?? 900)}. Mỗi người dùng có tối đa{' '}
                {capabilities?.max_active_jobs ?? 2} tác vụ chưa hoàn tất. Phân cảnh được dựng theo số thứ tự chương.
              </Text>
              <Table
                size="small"
                rowKey="id"
                loading={loading}
                dataSource={chapters}
                columns={chapterColumns}
                pagination={{ pageSize: 6, size: 'small' }}
                rowSelection={{
                  selectedRowKeys: selectedChapterIds,
                  onChange: (keys) => setSelectedChapterIds(keys as string[]),
                  getCheckboxProps: (chapter: ChapterItem) => ({
                    disabled: !(chapter.content && chapter.content.trim()),
                  }),
                }}
                scroll={{ y: 240 }}
              />
            </Space>
          </Col>

          <Col xs={24} lg={12}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Text strong>Tham số dựng</Text>
              <div>
                <Text style={{ fontSize: 12 }}>Độ phân giải</Text>
                <Select
                  style={{ width: '100%' }}
                  value={resolution}
                  onChange={setResolution}
                  options={(capabilities?.allowed_resolutions || ['1280x720']).map((item) => ({
                    label: item,
                    value: item,
                  }))}
                />
              </div>
              <div>
                <Text style={{ fontSize: 12 }}>FPS</Text>
                <Select
                  style={{ width: '100%' }}
                  value={fps}
                  onChange={setFps}
                  options={(capabilities?.allowed_fps || [24]).map((item) => ({
                    label: `${item} fps`,
                    value: item,
                  }))}
                />
              </div>
              <div>
                <Text style={{ fontSize: 12 }}>Số ký tự mỗi phân cảnh</Text>
                <InputNumber
                  style={{ width: '100%' }}
                  min={capabilities?.narration_chars_range?.[0] ?? 80}
                  max={capabilities?.narration_chars_range?.[1] ?? 600}
                  step={20}
                  value={charsPerScene}
                  onChange={(value) => setCharsPerScene(Number(value || 220))}
                />
              </div>
              <Space size={24} wrap>
                <Space size={8}>
                  <Switch checked={useCover} onChange={setUseCover} />
                  <Text style={{ fontSize: 12 }}>Dùng ảnh bìa làm hình nền</Text>
                </Space>
                <Space size={8}>
                  <Switch
                    checked={ttsEnabled}
                    onChange={setTtsEnabled}
                    disabled={!capabilities?.tts_available || remoteModeSelected}
                  />
                  <Tooltip
                    title={
                      remoteModeSelected
                        ? 'Chế độ provider AI không ghép giọng đọc vào clip do provider trả về'
                        : capabilities?.tts_available
                          ? 'Bật để đọc lời thoại từng phân cảnh. Truyện tiếng Việt hãy chọn OmniVoice (Nữ / Nam).'
                          : capabilities?.tts_hint || 'TTS chưa sẵn sàng. Cài OmniVoice (pip install torch torchaudio omnivoice) hoặc vào Cài đặt → Giọng đọc video.'
                    }
                  >
                    <Text style={{ fontSize: 12 }}>Giọng đọc (TTS)</Text>
                  </Tooltip>
                </Space>
              </Space>
              {!capabilities?.tts_available && (
                <Alert
                  type="warning"
                  showIcon
                  message="Chưa cấu hình giọng đọc"
                  description={
                    <span>
                      Cài OmniVoice trên máy chủ (<Text code>pip install torch torchaudio omnivoice</Text>), hoặc vào{' '}
                      <Link to="/settings">Cài đặt → Giọng đọc video</Link>.
                    </span>
                  }
                />
              )}
              {capabilities?.tts_available && !remoteModeSelected && (
                <>
                  <div>
                    <Text style={{ fontSize: 12 }}>Nhà cung cấp giọng</Text>
                    <Select
                      style={{ width: '100%' }}
                      value={selectedTtsProvider?.id || ttsProviderId || 'omnivoice'}
                      onChange={(value) => {
                        const next = ttsProviders.find((item) => item.id === value);
                        setTtsProviderId(value);
                        setTtsModel(next?.default_model || null);
                      }}
                      disabled={!ttsEnabled}
                      options={ttsProviders.map((item) => ({
                        label: item.label,
                        value: item.id,
                        disabled: !item.configured,
                      }))}
                    />
                  </div>
                  <div>
                    <Text style={{ fontSize: 12 }}>Giọng đọc</Text>
                    <Select
                      style={{ width: '100%' }}
                      value={ttsModel || selectedTtsProvider?.default_model || 'female'}
                      onChange={setTtsModel}
                      disabled={!ttsEnabled}
                      options={(selectedTtsProvider?.models || ['female']).map((item) => ({
                        label: selectedTtsProvider?.model_labels?.[item] || item,
                        value: item,
                      }))}
                    />
                  </div>
                  {ttsEnglishOnly && ttsEnabled && (
                    <Alert
                      type="warning"
                      showIcon
                      message="Giọng này chỉ nói tiếng Anh"
                      description="Deepgram Flux sẽ đọc chữ Việt theo âm English. Hãy chọn OmniVoice — Nữ hoặc Nam."
                    />
                  )}
                </>
              )}

              <Text strong>Chuyển động video</Text>
              <div>
                <Text style={{ fontSize: 12 }}>Chế độ</Text>
                <Select
                  style={{ width: '100%' }}
                  value={motionMode}
                  onChange={handleMotionModeChange}
                  options={(capabilities?.motion_modes || ['local', 'remote', 'hybrid']).map((mode) => ({
                    label: MOTION_MODE_LABELS[mode]?.text || mode,
                    value: mode,
                    disabled: mode !== 'local' && configuredRemoteProviders.length === 0,
                  }))}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {MOTION_MODE_LABELS[motionMode]?.hint}
                </Text>
              </div>

              {remoteModeSelected && (
                <>
                  <div>
                    <Text style={{ fontSize: 12 }}>Provider</Text>
                    <Select
                      style={{ width: '100%' }}
                      value={motionProviderId ?? undefined}
                      placeholder="Chọn provider AI"
                      onChange={handleMotionProviderChange}
                      options={remoteProviders.map((provider) => ({
                        label: provider.configured
                          ? provider.label
                          : `${provider.label} (chưa cấu hình)`,
                        value: provider.id,
                        disabled: !provider.configured,
                      }))}
                    />
                  </div>
                  {selectedProvider && selectedModelLimits && (
                    <Space size={8} wrap>
                      <div style={{ minWidth: 180, flex: 1 }}>
                        <Text style={{ fontSize: 12 }}>Model</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={motionModel ?? selectedProvider.default_model}
                          onChange={handleMotionModelChange}
                          options={selectedProvider.models.map((model) => ({
                            label: model,
                            value: model,
                          }))}
                        />
                      </div>
                      <div style={{ minWidth: 120, flex: 1 }}>
                        <Text style={{ fontSize: 12 }}>Độ phân giải AI</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={motionResolution ?? selectedModelLimits.default_resolution}
                          onChange={setMotionResolution}
                          options={(selectedModelLimits.resolutions || []).map((item) => ({
                            label: item,
                            value: item,
                          }))}
                        />
                      </div>
                      <div style={{ minWidth: 100, flex: 1 }}>
                        <Text style={{ fontSize: 12 }}>Tỉ lệ</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={motionAspectRatio ?? selectedModelLimits.aspect_ratios?.[0]}
                          onChange={setMotionAspectRatio}
                          options={(selectedModelLimits.aspect_ratios || []).map((item) => ({
                            label: item,
                            value: item,
                          }))}
                        />
                      </div>
                    </Space>
                  )}
                  {motionMode === 'hybrid' && (
                    <Space size={8}>
                      <Switch checked={hybridFallback} onChange={setHybridFallback} />
                      <Tooltip title="Khi provider lỗi hoặc hết thời gian chờ, phân cảnh được dựng lại bằng FFmpeg cục bộ (không gọi lại API, không phát sinh thêm chi phí)">
                        <Text style={{ fontSize: 12 }}>Cho phép dựng dự phòng bằng FFmpeg cục bộ</Text>
                      </Tooltip>
                    </Space>
                  )}
                  {selectedProvider && (
                    <Alert
                      type="warning"
                      showIcon
                      message="Video AI có tính phí theo từng phân cảnh"
                      description={
                        <span style={{ fontSize: 12 }}>
                          {selectedProvider.cost_note} Provider cần ảnh tham chiếu (ảnh bìa dự án hoặc ảnh phân cảnh);
                          phân cảnh không có ảnh sẽ báo lỗi rõ chứ không tự tạo ảnh AI. Model đang chọn tạo clip{' '}
                          {durationHint} cho mỗi phân cảnh (dài/ngắn hơn lời kể sẽ được ghép theo clip thực tế),
                          phụ đề bám theo độ dài clip thực tế.
                        </span>
                      }
                    />
                  )}
                </>
              )}

              {motionInvalid && (
                <Alert
                  type="error"
                  showIcon
                  message="Provider AI chưa được cấu hình"
                  description={
                    <span style={{ fontSize: 12 }}>
                      Máy chủ còn thiếu biến môi trường:{' '}
                      {selectedProvider?.missing_config?.length
                        ? selectedProvider.missing_config.join(', ')
                        : 'chưa có provider AI nào được cấu hình'}
                      . Hãy chọn chế độ cục bộ hoặc nhờ quản trị viên cấu hình API key.
                    </span>
                  }
                />
              )}

              <Text strong>Ảnh phân cảnh (AI image)</Text>
              <Space size={8}>
                <Switch
                  checked={generateSceneImages}
                  onChange={handleGenerateSceneImagesChange}
                  disabled={!imageFeatureEnabled || configuredImageProviders.length === 0}
                />
                <Tooltip
                  title={
                    !imageFeatureEnabled
                      ? 'Quản trị viên đã tắt chức năng tạo ảnh phân cảnh trên máy chủ'
                      : configuredImageProviders.length === 0
                        ? 'Provider tạo ảnh chưa được cấu hình'
                        : 'Mỗi phân cảnh sẽ được tạo một ảnh AI làm ảnh tham chiếu cho video'
                  }
                >
                  <Text style={{ fontSize: 12 }}>
                    Tạo ảnh cảnh bằng {selectedImageProvider?.label || 'AI image'}
                  </Text>
                </Tooltip>
              </Space>

              {generateSceneImages && selectedImageProvider && (
                <>
                  <div>
                    <Text style={{ fontSize: 12 }}>Provider ảnh</Text>
                    <Select
                      style={{ width: '100%' }}
                      value={imageProviderId ?? undefined}
                      placeholder="Chọn provider tạo ảnh"
                      onChange={handleImageProviderChange}
                      options={imageProviders.map((provider) => ({
                        label: provider.configured
                          ? provider.label
                          : `${provider.label} (chưa cấu hình)`,
                        value: provider.id,
                        disabled: !provider.configured,
                      }))}
                    />
                  </div>
                  <Space size={8} wrap>
                    <div style={{ minWidth: 180, flex: 1 }}>
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
                    </div>
                    <div style={{ minWidth: 130, flex: 1 }}>
                      <Text style={{ fontSize: 12 }}>Kích thước ảnh</Text>
                      <Select
                        style={{ width: '100%' }}
                        value={imageSize ?? undefined}
                        placeholder={selectedImageProvider.default_size}
                        onChange={handleImageSizeChange}
                        allowClear
                        options={selectedImageProvider.sizes.map((size) => ({
                          label: size,
                          value: size,
                        }))}
                      />
                    </div>
                    <div style={{ minWidth: 100, flex: 1 }}>
                      <Text style={{ fontSize: 12 }}>Tỉ lệ ảnh</Text>
                      <Select
                        style={{ width: '100%' }}
                        value={imageAspectRatio ?? selectedImageProvider.aspect_ratios[0]}
                        onChange={setImageAspectRatio}
                        options={selectedImageProvider.aspect_ratios.map((item) => ({
                          label: item,
                          value: item,
                        }))}
                      />
                    </div>
                    {selectedImageProvider.supports_reasoning_strength && (
                      <div style={{ minWidth: 140, flex: 1 }}>
                        <Text style={{ fontSize: 12 }}>Mức suy luận</Text>
                        <Select
                          style={{ width: '100%' }}
                          value={imageReasoningStrength ?? undefined}
                          placeholder="Mặc định"
                          onChange={setImageReasoningStrength}
                          allowClear
                          options={selectedImageProvider.reasoning_strengths.map((item) => ({
                            label: item,
                            value: item,
                          }))}
                        />
                      </div>
                    )}
                  </Space>
                  <Alert
                    type="warning"
                    showIcon
                    message="Tạo ảnh cảnh có tính phí theo từng ảnh"
                    description={
                      <span style={{ fontSize: 12 }}>
                        {selectedImageProvider.cost_note} Mỗi phân cảnh được bật là một lần gọi API; ảnh tạo thành công
                        được lưu trong thư mục tác vụ và tái sử dụng khi dựng lại (không tạo lại để tránh tính phí hai lần).
                        Ảnh này được dùng làm ảnh tham chiếu cho provider video; không có ảnh thì phân cảnh báo lỗi rõ
                        chứ không tự chuyển sang provider khác.
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
                      . Hãy tắt tùy chọn tạo ảnh phân cảnh hoặc nhờ quản trị viên cấu hình.
                    </span>
                  }
                />
              )}

              {(playerUrl || jobs.some((job) => job.has_video)) && (
                <Alert
                  type="success"
                  showIcon
                  message={playerUrl ? 'Phim đã dựng xong — xem ngay dưới dải phân cảnh' : 'Đã có phim xuất'}
                  description={
                    <span style={{ fontSize: 12 }}>
                      {playerUrl
                        ? 'Không cần tạo lại. Phim đang hiện ngay dưới dải phân cảnh, phía trên form này.'
                        : 'Chọn tác vụ hoàn tất trong Tác vụ xuất phim, hoặc bấm Xem phim trên Tác vụ nền.'}
                    </span>
                  }
                  action={
                    <Button
                      type="primary"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      onClick={() => {
                        const ready =
                          jobs.find((job) => job.has_video && job.status === 'completed') ||
                          jobs.find((job) => job.has_video);
                        if (ready && activeJob?.id !== ready.id) {
                          void loadJobDetail(ready.id);
                        }
                        playerSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                      }}
                    >
                      Xem phim
                    </Button>
                  }
                />
              )}

              <Button
                className="cinematic-create"
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={creating}
                disabled={!canCreate || selectedChapterIds.length === 0}
                onClick={handleCreate}
              >
                Tạo storyboard và dựng phim
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Hệ thống tách chương thành phân cảnh, tạo ảnh tham chiếu khi bật AI image, rồi ghép phim và phụ đề SRT.
              </Text>
            </Space>
          </Col>
        </Row>
      </Card>
      </section>

      <Card className="cinematic-jobs" title="Tác vụ xuất phim" size="small">
        {jobs.length === 0 ? (
          <Empty description="Chưa có tác vụ xuất phim nào" />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Select
              style={{ width: '100%' }}
              value={activeJob?.id}
              placeholder="Chọn tác vụ để xem phân cảnh"
              options={jobOptions}
              onChange={(value) => loadJobDetail(value)}
            />

            {activeJob && (
              <div
                style={{
                  border: `1px solid ${token.colorBorderSecondary}`,
                  borderRadius: token.borderRadiusLG,
                  padding: 12,
                }}
              >
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Space wrap>
                    <Tag color={STATUS_LABELS[activeJob.status]?.color || 'default'}>
                      {STATUS_LABELS[activeJob.status]?.text || activeJob.status}
                    </Tag>
                    <Tag color={remoteModeActive ? 'purple' : 'default'}>
                      {MOTION_MODE_LABELS[activeJob.motion_mode || 'local']?.text || activeJob.motion_mode}
                    </Tag>
                    {activeJob.motion_provider && (
                      <Tag>
                        {motionProviders.find((item) => item.id === activeJob.motion_provider)?.label ||
                          activeJob.motion_provider}
                        {activeJob.motion_model ? ` · ${activeJob.motion_model}` : ''}
                      </Tag>
                    )}
                    {activeJob.image_provider && (
                      <Tag color="gold">
                        Ảnh: {imageProviders.find((item) => item.id === activeJob.image_provider)?.label ||
                          activeJob.image_provider}
                        {activeJob.image_model ? ` · ${activeJob.image_model}` : ''}
                      </Tag>
                    )}
                    <Text type="secondary">
                      {activeJob.scene_count} phân cảnh · {formatDuration(activeJob.duration_seconds)} ·{' '}
                      {formatSize(activeJob.video_size_bytes)}
                    </Text>
                  </Space>

                  <Progress
                    percent={activeJob.progress}
                    status={activeJob.status === 'failed' ? 'exception' : undefined}
                  />
                  {activeJob.status_message && <Text type="secondary">{activeJob.status_message}</Text>}
                  {activeJob.error_message && (
                    <Alert type="error" showIcon message={activeJob.error_message} />
                  )}

                  <Space wrap>
                    <Button
                      type="primary"
                      icon={<PlayCircleOutlined />}
                      disabled={!activeJob.has_video}
                      onClick={() => playerSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                    >
                      Xem phim
                    </Button>
                    <Button
                      icon={<DownloadOutlined />}
                      disabled={!activeJob.has_video || activeJob.status !== 'completed'}
                      onClick={() => handleDownload(activeJob.id, 'video')}
                    >
                      Tải MP4
                    </Button>
                    <Button
                      icon={<FileTextOutlined />}
                      disabled={!activeJob.has_subtitles || activeJob.status !== 'completed'}
                      onClick={() => handleDownload(activeJob.id, 'subtitles')}
                    >
                      Tải SRT
                    </Button>
                    <Button
                      icon={<RedoOutlined />}
                      disabled={isActive(activeJob) || !canCreate}
                      onClick={() => handleRetryJob(activeJob.id)}
                    >
                      Dựng lại
                    </Button>
                    {isActive(activeJob) ? (
                      <Popconfirm
                        title="Hủy tác vụ đang chạy?"
                        onConfirm={() => handleCancelJob(activeJob.id)}
                        okText="Hủy tác vụ"
                        cancelText="Đóng"
                      >
                        <Button danger icon={<StopOutlined />}>
                          Hủy
                        </Button>
                      </Popconfirm>
                    ) : (
                      <Popconfirm
                        title="Xóa tác vụ và toàn bộ tệp đã dựng?"
                        onConfirm={() => handleDeleteJob(activeJob.id)}
                        okText="Xóa"
                        cancelText="Đóng"
                      >
                        <Button danger icon={<DeleteOutlined />}>
                          Xóa
                        </Button>
                      </Popconfirm>
                    )}
                  </Space>
                </Space>
              </div>
            )}
          </Space>
        )}
      </Card>

      {activeJob && (
        <Card className="cinematic-storyboard"
          title={
            <Space>
              <VideoCameraOutlined />
              <span>Storyboard ({activeJob.scenes?.length || 0} phân cảnh)</span>
            </Space>
          }
          size="small"
        >
          <Table
            size="small"
            rowKey="id"
            dataSource={activeJob.scenes || []}
            columns={sceneColumns}
            pagination={{ pageSize: 10, size: 'small' }}
            scroll={{ x: 900 }}
          />
        </Card>
      )}
    </main>
  );
};

export default VideoExport;
