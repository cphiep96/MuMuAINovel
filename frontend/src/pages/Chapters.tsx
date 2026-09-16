import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { List, Button, Modal, Form, Input, Select, message, Empty, Space, Badge, Tag, Card, InputNumber, Alert, Radio, Descriptions, Collapse, Popconfirm, Pagination, theme } from 'antd';
import { EditOutlined, FileTextOutlined, ThunderboltOutlined, LockOutlined, DownloadOutlined, SettingOutlined, FundOutlined, SyncOutlined, CheckCircleOutlined, CloseCircleOutlined, RocketOutlined, StopOutlined, InfoCircleOutlined, CaretRightOutlined, DeleteOutlined, BookOutlined, FormOutlined, PlusOutlined, ReadOutlined } from '@ant-design/icons';
import { useStore } from '../store';
import { eventBus, EventNames } from '../store/eventBus';
import { useChapterSync } from '../store/hooks';
import { generateChapterBackground } from '../services/backgroundTaskService';
import { projectApi, writingStyleApi, chapterApi } from '../services/api';
import type { Chapter, ChapterUpdate, ApiError, WritingStyle, AnalysisTask, ExpansionPlanData } from '../types';
import type { TextAreaRef } from 'antd/es/input/TextArea';
import ChapterAnalysis from '../components/ChapterAnalysis';
import ExpansionPlanEditor from '../components/ExpansionPlanEditor';
import { SSELoadingOverlay } from '../components/SSELoadingOverlay';
import ChapterReader from '../components/ChapterReader';
import PartialRegenerateToolbar from '../components/PartialRegenerateToolbar';
import PartialRegenerateModal from '../components/PartialRegenerateModal';

const { TextArea } = Input;

// localStorage 缓存键名
const WORD_COUNT_CACHE_KEY = 'chapter_default_word_count';
const DEFAULT_WORD_COUNT = 3000;

// 从 localStorage 读取缓存的字数
const getCachedWordCount = (): number => {
  try {
    const cached = localStorage.getItem(WORD_COUNT_CACHE_KEY);
    if (cached) {
      const value = parseInt(cached, 10);
      if (!isNaN(value) && value >= 500 && value <= 10000) {
        return value;
      }
    }
  } catch (error) {
    console.warn('Đọc cache số chữ thất bại:', error);
  }
  return DEFAULT_WORD_COUNT;
};

// 保存字数到 localStorage
const setCachedWordCount = (value: number): void => {
  try {
    localStorage.setItem(WORD_COUNT_CACHE_KEY, String(value));
  } catch (error) {
    console.warn('Lưu cache số chữ thất bại:', error);
  }
};

export default function Chapters() {
  const { currentProject, chapters, outlines, setCurrentChapter, setCurrentProject } = useStore();
  const [modal, contextHolder] = Modal.useModal();
  const { token } = theme.useToken();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [isContinuing, setIsContinuing] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [editorForm] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const contentTextAreaRef = useRef<TextAreaRef>(null);
  const [writingStyles, setWritingStyles] = useState<WritingStyle[]>([]);
  const [selectedStyleId, setSelectedStyleId] = useState<number | undefined>();
  const [targetWordCount, setTargetWordCount] = useState<number>(getCachedWordCount);
  const [availableModels, setAvailableModels] = useState<Array<{ value: string, label: string }>>([]);
  const [selectedModel, setSelectedModel] = useState<string | undefined>();
  const [batchSelectedModel, setBatchSelectedModel] = useState<string | undefined>(); // 批量生成的模型选择
  const [batchSelectedSkillKey, setBatchSelectedSkillKey] = useState<string | undefined>(); // 批量生成的Skill选择
  const [temporaryNarrativePerspective, setTemporaryNarrativePerspective] = useState<string | undefined>(); // 临时人称选择
  const [availableSkills, setAvailableSkills] = useState<Array<{ template_key: string; template_name: string; description: string; category: string }>>([]);
  const [selectedSkillKey, setSelectedSkillKey] = useState<string | undefined>();
  const [analysisVisible, setAnalysisVisible] = useState(false);
  const [analysisChapterId, setAnalysisChapterId] = useState<string | null>(null);
  // 分析任务状态管理
  const [analysisTasksMap, setAnalysisTasksMap] = useState<Record<string, AnalysisTask>>({});
  const analysisPollingIntervalRef = useRef<number | null>(null);
  const activeAnalysisPollingIdsRef = useRef<Set<string>>(new Set());
  const analysisPollingInFlightRef = useRef(false);
  const analysisPollingRequestIdRef = useRef(0);
  const currentProjectIdRef = useRef<string | undefined>(currentProject?.id);
  currentProjectIdRef.current = currentProject?.id;
  const editingIdRef = useRef<string | null>(editingId);
  editingIdRef.current = editingId;

  // 列表查询与分页状态
  const [chapterSearchKeyword, setChapterSearchKeyword] = useState('');
  const [chapterPage, setChapterPage] = useState(1);
  const [chapterPageSize, setChapterPageSize] = useState(20);

  // Đọc器状态
  const [readerVisible, setReaderVisible] = useState(false);
  const [readingChapter, setReadingChapter] = useState<Chapter | null>(null);

  // 规划Chỉnh sửa状态
  const [planEditorVisible, setPlanEditorVisible] = useState(false);
  const [editingPlanChapter, setEditingPlanChapter] = useState<Chapter | null>(null);

  // 局部重写状态
  const [partialRegenerateToolbarVisible, setPartialRegenerateToolbarVisible] = useState(false);
  const [partialRegenerateToolbarPosition, setPartialRegenerateToolbarPosition] = useState({ top: 0, left: 0 });
  const [selectedTextForRegenerate, setSelectedTextForRegenerate] = useState('');
  const [selectionStartPosition, setSelectionStartPosition] = useState(0);
  const [selectionEndPosition, setSelectionEndPosition] = useState(0);
  const [partialRegenerateModalVisible, setPartialRegenerateModalVisible] = useState(false);

  // 单章节生成进度状态
  const [singleChapterProgress, setSingleChapterProgress] = useState(0);
  const [singleChapterProgressMessage, setSingleChapterProgressMessage] = useState('');


  // 批量生成相关状态
  const [batchGenerateVisible, setBatchGenerateVisible] = useState(false);
  const [batchGenerating, setBatchGenerating] = useState(false);
  const [batchAnalyzingUnanalyzed, setBatchAnalyzingUnanalyzed] = useState(false);
  const [batchTaskId, setBatchTaskId] = useState<string | null>(null);
  const [batchForm] = Form.useForm();
  const [manualCreateForm] = Form.useForm();
  const [batchProgress, setBatchProgress] = useState<{
    status: string;
    total: number;
    completed: number;
    current_chapter_number: number | null;
    estimated_time_minutes?: number;
  } | null>(null);
  const batchPollingIntervalRef = useRef<number | null>(null);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 读取 textarea 原生选区。textarea 的选区不会出现在 window.getSelection() 中，
  // 且失焦后 selectionStart/selectionEnd 仍然保留，因此可以稳定支持拖拽出Chỉnh sửa框和点击外部。
  const getTextAreaSelection = useCallback(() => {
    if (!isEditorOpen || isGenerating) return null;

    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) return null;

    const start = textArea.selectionStart;
    const end = textArea.selectionEnd;
    if (end <= start) return null;

    const selectedText = textArea.value.substring(start, end);
    if (selectedText.trim().length < 10) return null;

    return { textArea, start, end, selectedText };
  }, [isEditorOpen, isGenerating]);

  // 处理文本选中 - 检测选中文本并显示浮动工具栏
  const handleTextSelection = useCallback(() => {
    const currentSelection = getTextAreaSelection();
    if (!currentSelection) {
      setPartialRegenerateToolbarVisible(false);
      return;
    }

    const { textArea, start, end, selectedText: selectedInTextArea } = currentSelection;
    const textContent = textArea.value;

    // 计算浮动工具栏位置
    const rect = textArea.getBoundingClientRect();
    const computedStyle = window.getComputedStyle(textArea);
    const lineHeight = parseFloat(computedStyle.lineHeight) || 24;
    const paddingTop = parseFloat(computedStyle.paddingTop) || 0;

    // 计算选中文本起始位置所在的行号
    const textBeforeSelection = textContent.substring(0, start);
    const startLine = textBeforeSelection.split('\n').length - 1;

    // 计算选中文本在 textarea 中的视觉位置，并考虑内部滚动偏移
    const scrollTop = textArea.scrollTop;
    const visualTop = (startLine * lineHeight) + paddingTop - scrollTop;
    const toolbarTop = rect.top + visualTop - 45;
    const toolbarLeft = rect.right - 180;

    setSelectedTextForRegenerate(selectedInTextArea);
    setSelectionStartPosition(start);
    setSelectionEndPosition(end);

    // 如果选中位置不在可视区域内，固定在 textarea 边缘
    let finalTop = toolbarTop;
    if (visualTop < 0) {
      finalTop = rect.top + 10;
    } else if (visualTop > textArea.clientHeight) {
      finalTop = rect.bottom - 50;
    }

    setPartialRegenerateToolbarPosition({
      top: Math.max(rect.top + 10, Math.min(finalTop, rect.bottom - 50)),
      left: Math.min(Math.max(rect.left + 20, toolbarLeft), window.innerWidth - 200),
    });
    setPartialRegenerateToolbarVisible(true);
  }, [getTextAreaSelection]);
  // Cập nhật工具栏位置的函数（不检测选中，只Cập nhật位置）
  const updateToolbarPosition = useCallback(() => {
    if (!partialRegenerateToolbarVisible || !selectedTextForRegenerate) return;
    
    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) return;
    
    const rect = textArea.getBoundingClientRect();
    const computedStyle = window.getComputedStyle(textArea);
    const lineHeight = parseFloat(computedStyle.lineHeight) || 24;
    const paddingTop = parseFloat(computedStyle.paddingTop) || 0;
    
    const textContent = textArea.value;
    const textBeforeSelection = textContent.substring(0, selectionStartPosition);
    const startLine = textBeforeSelection.split('\n').length - 1;
    
    const scrollTop = textArea.scrollTop;
    const visualTop = (startLine * lineHeight) + paddingTop - scrollTop;
    
    const toolbarTop = rect.top + visualTop - 45;
    // 固定在 textarea 右上角，不随选中位置变化
    const toolbarLeft = rect.right - 180;
    
    // 工具栏固定在 textarea 可视区域内，即使选中文本滚出视野也保持显示
    // 如果选中位置在可视区域内，跟随选中位置
    // 如果滚出视野，固定在顶部或底部边缘
    let finalTop = toolbarTop;
    if (visualTop < 0) {
      // 选中位置在上方视野外，工具栏固定在顶部
      finalTop = rect.top + 10;
    } else if (visualTop > textArea.clientHeight) {
      // 选中位置在下方视野外，工具栏固定在底部
      finalTop = rect.bottom - 50;
    }
    
    setPartialRegenerateToolbarPosition({
      top: Math.max(rect.top + 10, Math.min(finalTop, rect.bottom - 50)),
      left: Math.min(Math.max(rect.left + 20, toolbarLeft), window.innerWidth - 200),
    });
  }, [partialRegenerateToolbarVisible, selectedTextForRegenerate, selectionStartPosition]);

  // 监听选中事件
  useEffect(() => {
    if (!isEditorOpen) return;

    const textArea = contentTextAreaRef.current?.resizableTextArea?.textArea;
    if (!textArea) return;

    const handleMouseUp = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest('[data-partial-regenerate-toolbar]')) return;

      // 在 document 级别监听，拖拽出 textarea 后松开鼠标也能捕获选区。
      window.setTimeout(handleTextSelection, 0);
    };

    const handleKeyUp = () => {
      // 键盘扩选、收缩选区以及清除选区都通过统一逻辑处理。
      window.setTimeout(handleTextSelection, 0);
    };

    const handleSelect = () => {
      // 原生 textarea 的 select 事件比 window.selection 更可靠。
      handleTextSelection();
    };
    const handleScroll = () => {
      // 滚动时Cập nhật位置（使用 requestAnimationFrame 优化性能）
      requestAnimationFrame(updateToolbarPosition);
    };

    // 监听 textarea 滚动
    document.addEventListener('mouseup', handleMouseUp, true);
    textArea.addEventListener('keyup', handleKeyUp);
    textArea.addEventListener('select', handleSelect);
    textArea.addEventListener('scroll', handleScroll);

    // 同时监听 Modal body 滚动（Modal 内容可能在外层容器滚动）
    const modalBody = textArea.closest('.ant-modal-body');
    if (modalBody) {
      modalBody.addEventListener('scroll', handleScroll);
    }

    // 监听窗口大小变化
    window.addEventListener('resize', handleScroll);

    return () => {
      document.removeEventListener('mouseup', handleMouseUp, true);
      textArea.removeEventListener('keyup', handleKeyUp);
      textArea.removeEventListener('select', handleSelect);
      textArea.removeEventListener('scroll', handleScroll);
      if (modalBody) {
        modalBody.removeEventListener('scroll', handleScroll);
      }
      window.removeEventListener('resize', handleScroll);
    };
  }, [isEditorOpen, handleTextSelection, updateToolbarPosition]);



  const {
    refreshChapters,
    updateChapter,
    deleteChapter,
    generateChapterContentStream
  } = useChapterSync();

  useEffect(() => {
    if (currentProject?.id) {
      const projectId = currentProject.id;
      if (analysisPollingIntervalRef.current !== null) {
        clearInterval(analysisPollingIntervalRef.current);
        analysisPollingIntervalRef.current = null;
      }
      analysisPollingRequestIdRef.current += 1;
      analysisPollingInFlightRef.current = false;
      activeAnalysisPollingIdsRef.current.clear();
      setAnalysisTasksMap({});

      void refreshChapters(projectId).then((latestChapters) => {
        if (currentProjectIdRef.current === projectId) {
          void loadAnalysisTasks(latestChapters, projectId);
        }
      });
      loadWritingStyles();
      checkAndRestoreBatchTask();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject?.id]);

  // 清理轮询定时器
  useEffect(() => {
    return () => {
      if (analysisPollingIntervalRef.current !== null) {
        clearInterval(analysisPollingIntervalRef.current);
        analysisPollingIntervalRef.current = null;
      }
      if (batchPollingIntervalRef.current !== null) {
        clearInterval(batchPollingIntervalRef.current);
        batchPollingIntervalRef.current = null;
      }
    };
  }, []);

  const clearAnalysisPollingIfIdle = useCallback(() => {
    if (activeAnalysisPollingIdsRef.current.size === 0 && analysisPollingIntervalRef.current) {
      clearInterval(analysisPollingIntervalRef.current);
      analysisPollingIntervalRef.current = null;
    }
  }, []);

  const pollActiveAnalysisTasks = useCallback(async () => {
    const projectId = currentProjectIdRef.current;
    if (!projectId || analysisPollingInFlightRef.current) return;

    const activeIds = Array.from(activeAnalysisPollingIdsRef.current);
    if (activeIds.length === 0) {
      clearAnalysisPollingIfIdle();
      return;
    }

    analysisPollingInFlightRef.current = true;
    const requestId = analysisPollingRequestIdRef.current + 1;
    analysisPollingRequestIdRef.current = requestId;

    try {
      const response = await chapterApi.getBatchAnalysisStatuses(projectId, activeIds);
      if (currentProjectIdRef.current !== projectId) return;

      const tasksMap = response.items || {};

      setAnalysisTasksMap(prev => ({
        ...prev,
        ...tasksMap,
      }));

      activeIds.forEach((chapterId) => {
        const task = tasksMap[chapterId];
        if (!task || task.status === 'completed' || task.status === 'failed' || task.status === 'none') {
          activeAnalysisPollingIdsRef.current.delete(chapterId);

          if (task?.status === 'completed') {
            message.success('Phân tích chương hoàn tất');
          } else if (task?.status === 'failed') {
            message.error(`Phân tích chương thất bại: ${task.error_message || 'Lỗi không xác định'}`);
          }
        }
      });

      clearAnalysisPollingIfIdle();
    } catch (error) {
      console.error('Thăm dò hàng loạt tác vụ phân tích thất bại:', error);
    } finally {
      if (analysisPollingRequestIdRef.current === requestId) {
        analysisPollingInFlightRef.current = false;
      }
    }
  }, [clearAnalysisPollingIfIdle]);

  const ensureAnalysisPolling = useCallback(() => {
    if (analysisPollingIntervalRef.current) return;

    analysisPollingIntervalRef.current = window.setInterval(() => {
      void pollActiveAnalysisTasks();
    }, 2000);

    // 立即执行一次
    void pollActiveAnalysisTasks();
  }, [pollActiveAnalysisTasks]);

  // 加载所有章节的分析任务状态（批量接口，避免逐章请求风暴）
  // 接受可选的 chaptersToLoad 参数，解决 React 状态Cập nhật延迟导致的问题
  const loadAnalysisTasks = useCallback(async (
    chaptersToLoad?: typeof chapters,
    projectId?: string,
  ) => {
    const targetChapters = chaptersToLoad || chapters;
    const targetProjectId = projectId || currentProjectIdRef.current;
    if (!targetChapters || targetChapters.length === 0 || !targetProjectId) return;

    const chapterIds = targetChapters
      .filter(chapter => chapter.content && chapter.content.trim() !== '')
      .map(chapter => chapter.id);

    if (chapterIds.length === 0) {
      setAnalysisTasksMap({});
      activeAnalysisPollingIdsRef.current.clear();
      clearAnalysisPollingIfIdle();
      return;
    }

    try {
      const response = await chapterApi.getBatchAnalysisStatuses(targetProjectId, chapterIds);
      if (currentProjectIdRef.current !== targetProjectId) return;

      const tasksMap = response.items || {};
      setAnalysisTasksMap(tasksMap);

      activeAnalysisPollingIdsRef.current.clear();
      Object.entries(tasksMap).forEach(([chapterId, task]) => {
        if (task?.status === 'pending' || task?.status === 'running') {
          activeAnalysisPollingIdsRef.current.add(chapterId);
        }
      });

      if (activeAnalysisPollingIdsRef.current.size > 0) {
        ensureAnalysisPolling();
      } else {
        clearAnalysisPollingIfIdle();
      }
    } catch (error) {
      console.error('Tải hàng loạt trạng thái tác vụ phân tích thất bại:', error);
    }
  }, [chapters, clearAnalysisPollingIfIdle, ensureAnalysisPolling]);

  useEffect(() => {
    const handleTaskSettled = (payload?: unknown) => {
      if (!payload || typeof payload !== 'object') return;
      const data = payload as { projectId?: string; resources?: string[] };
      if (data.projectId && data.projectId !== currentProjectIdRef.current) return;
      if (!data.resources?.includes('analysis')) return;
      void refreshChapters().then(latestChapters => loadAnalysisTasks(latestChapters));
    };
    eventBus.on(EventNames.BACKGROUND_TASK_SETTLED, handleTaskSettled);
    return () => eventBus.off(EventNames.BACKGROUND_TASK_SETTLED, handleTaskSettled);
  }, [loadAnalysisTasks, refreshChapters]);

  // 启动单个章节的任务轮询（内部合并到批量轮询）
  const startPollingTask = (chapterId: string) => {
    activeAnalysisPollingIdsRef.current.add(chapterId);
    ensureAnalysisPolling();
  };

  const loadWritingStyles = async () => {
    if (!currentProject?.id) return;

    try {
      const response = await writingStyleApi.getProjectStyles(currentProject.id);
      setWritingStyles(response.styles);

      // 设置默认风格为初始选中
      const defaultStyle = response.styles.find(s => s.is_default);
      if (defaultStyle) {
        setSelectedStyleId(defaultStyle.id);
      }
    } catch (error) {
      console.error('Tải phong cách viết thất bại:', error);
      message.error('Không tải được phong cách viết');
    }
  };

  // 加载可用的 Skill 列表
  const loadAvailableSkills = async () => {
    try {
      const response = await fetch('/api/skills/list');
      if (response.ok) {
        const data = await response.json();
        if (Array.isArray(data)) {
          setAvailableSkills(data);
        }
      }
    } catch (error) {
      console.error('Tải danh sách Skill thất bại:', error);
    }
  };

  const loadAvailableModels = async () => {
    try {
      // 从设置API获取用户配置的模型列表
      const settingsResponse = await fetch('/api/settings');
      if (settingsResponse.ok) {
        const settings = await settingsResponse.json();
        const { api_key, api_base_url, api_provider } = settings;

        if (api_base_url) {
          try {
            const modelsResponse = await fetch(
              `/api/settings/models?api_key=${encodeURIComponent(api_key || '')}&api_base_url=${encodeURIComponent(api_base_url)}&provider=${api_provider}`
            );
            if (modelsResponse.ok) {
              const data = await modelsResponse.json();
              if (data.models && data.models.length > 0) {
                setAvailableModels(data.models);
                // 设置默认模型为当前配置的模型
                setSelectedModel(settings.llm_model);
                return settings.llm_model; // 返回模型名称
              }
            }
          } catch {
            console.log('Lấy danh sách model thất bại, sẽ dùng model mặc định');
          }
        }
      }
    } catch (error) {
      console.error('Lấy danh sách model khả dụng thất bại:', error);
    }
    return null;
  };

  // 检查并恢复批量生成任务
  const checkAndRestoreBatchTask = async () => {
    if (!currentProject?.id) return;

    try {
      const response = await fetch(`/api/chapters/project/${currentProject.id}/batch-generate/active`);
      if (!response.ok) return;

      const data = await response.json();

      if (data.has_active_task && data.task) {
        const task = data.task;

        // 恢复任务状态（只在顶部进度条显示，不弹出Modal）
        setBatchTaskId(task.batch_id);
        setBatchProgress({
          status: task.status,
          total: task.total,
          completed: task.completed,
          current_chapter_number: task.current_chapter_number,
        });
        setBatchGenerating(true);
        // 不设置 setBatchGenerateVisible(true)，避免弹出Modal遮挡页面

        // 启动轮询
        startBatchPolling(task.batch_id);

        message.info('Phát hiện tác vụ tạo hàng loạt chưa hoàn tất, vui lòng xem danh sách tác vụ');
      }
    } catch (error) {
      console.error('Kiểm tra tác vụ tạo hàng loạt thất bại:', error);
    }
  };

  // 🔔 显示浏览器通知
  const showBrowserNotification = (title: string, body: string, type: 'success' | 'error' | 'info' = 'info') => {
    // 检查浏览器是否支持通知
    if (!('Notification' in window)) {
      console.log('Trình duyệt không hỗ trợ thông báo');
      return;
    }

    // 检查通知权限
    if (Notification.permission === 'granted') {
      // 选择图标
      const icon = type === 'success' ? '/logo.svg' : type === 'error' ? '/favicon.ico' : '/logo.svg';
      
      const notification = new Notification(title, {
        body,
        icon,
        badge: '/favicon.ico',
        tag: 'batch-generation', // 相同tag会替换旧通知
        requireInteraction: false, // 自动关闭
        silent: false, // 播放提示音
      });

      // 点击通知时聚焦到窗口
      notification.onclick = () => {
        window.focus();
        notification.close();
      };

      // 5秒后自动关闭
      setTimeout(() => {
        notification.close();
      }, 5000);
    } else if (Notification.permission !== 'denied') {
      // 如果权限未被明确拒绝，尝试请求权限
      Notification.requestPermission().then(permission => {
        if (permission === 'granted') {
          showBrowserNotification(title, body, type);
        }
      });
    }
  };

  // 按章节号排序并按大纲分组章节 (必须在早返回之前调用，避免违反 Hooks 规则)
  const { sortedChapters } = useMemo(() => {
    const sorted = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number);

    const groups: Record<string, {
      outlineId: string | null;
      outlineTitle: string;
      outlineOrder: number;
      chapters: Chapter[];
    }> = {};

    sorted.forEach(chapter => {
      const key = chapter.outline_id || 'uncategorized';

      if (!groups[key]) {
        groups[key] = {
          outlineId: chapter.outline_id || null,
          outlineTitle: chapter.outline_title || 'Chương chưa phân loại',
          outlineOrder: chapter.outline_order ?? 999,
          chapters: []
        };
      }

      groups[key].chapters.push(chapter);
    });

    return { sortedChapters: sorted };
  }, [chapters]);

  // 章节查询过滤（前端过滤，减少渲染压力）
  const filteredSortedChapters = useMemo(() => {
    const keyword = chapterSearchKeyword.trim().toLowerCase();
    if (!keyword) return sortedChapters;

    return sortedChapters.filter((chapter) => {
      return (
        String(chapter.chapter_number).includes(keyword) ||
        chapter.title.toLowerCase().includes(keyword) ||
        (chapter.outline_title || '').toLowerCase().includes(keyword)
      );
    });
  }, [sortedChapters, chapterSearchKeyword]);

  // 分页后的扁平章节
  const pagedSortedChapters = useMemo(() => {
    const start = (chapterPage - 1) * chapterPageSize;
    return filteredSortedChapters.slice(start, start + chapterPageSize);
  }, [filteredSortedChapters, chapterPage, chapterPageSize]);

  // one-to-many 模式分页后再按大纲分组
  const pagedGroupedChapters = useMemo(() => {
    const groups: Record<string, {
      outlineId: string | null;
      outlineTitle: string;
      outlineOrder: number;
      chapters: Chapter[];
    }> = {};

    pagedSortedChapters.forEach(chapter => {
      const key = chapter.outline_id || 'uncategorized';
      if (!groups[key]) {
        groups[key] = {
          outlineId: chapter.outline_id || null,
          outlineTitle: chapter.outline_title || 'Chương chưa phân loại',
          outlineOrder: chapter.outline_order ?? 999,
          chapters: []
        };
      }
      groups[key].chapters.push(chapter);
    });

    return Object.values(groups).sort((a, b) => a.outlineOrder - b.outlineOrder);
  }, [pagedSortedChapters]);

  // 搜索词或分页大小变化时重置到第一页
  useEffect(() => {
    setChapterPage(1);
  }, [chapterSearchKeyword, chapterPageSize, currentProject?.outline_mode]);

  // 数据变化导致页码越界时自动纠正
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredSortedChapters.length / chapterPageSize));
    if (chapterPage > maxPage) {
      setChapterPage(maxPage);
    }
  }, [filteredSortedChapters.length, chapterPage, chapterPageSize]);

  // 预计算每章可生成状态，避免在渲染阶段重复 O(n²) 扫描
  const chapterGenerateGateMap = useMemo(() => {
    const gateMap: Record<string, { canGenerate: boolean; reason: string }> = {};
    const incompleteChapterNumbers: number[] = [];
    const unanalyzedChapters: Array<{ chapterNumber: number; reason: string }> = [];

    sortedChapters.forEach((chapter) => {
      if (incompleteChapterNumbers.length > 0) {
        gateMap[chapter.id] = {
          canGenerate: false,
          reason: `Cần hoàn thành các chương trước: chương ${incompleteChapterNumbers.join(', ')}`
        };
      } else if (unanalyzedChapters.length > 0) {
        gateMap[chapter.id] = {
          canGenerate: false,
          reason: `Cần phân tích các chương trước: chương ${unanalyzedChapters.map(c => c.chapterNumber).join(', ')} (${unanalyzedChapters.map(c => c.reason).join(', ')})`
        };
      } else {
        gateMap[chapter.id] = { canGenerate: true, reason: '' };
      }

      // 将当前章纳入“后续章节”的前置条件
      if (!chapter.content || chapter.content.trim() === '') {
        incompleteChapterNumbers.push(chapter.chapter_number);
      }

      const task = analysisTasksMap[chapter.id];
      if (!task || !task.has_task) {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: 'Chưa phân tích' });
      } else if (task.status === 'pending') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: 'Chờ phân tích' });
      } else if (task.status === 'running') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: 'Đang phân tích' });
      } else if (task.status === 'failed') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: 'Phân tích thất bại' });
      } else if (task.status !== 'completed') {
        unanalyzedChapters.push({ chapterNumber: chapter.chapter_number, reason: 'Trạng thái không xác định' });
      }
    });

    return gateMap;
  }, [sortedChapters, analysisTasksMap]);

  // 当前可被“一键分析”的章节（有内容且未处于完成/进行中）
  const batchAnalyzableChapterCount = useMemo(() => {
    return sortedChapters.filter((chapter) => {
      if (!chapter.content || chapter.content.trim() === '') return false;
      const task = analysisTasksMap[chapter.id];
      if (!task || !task.has_task) return true;
      return task.status !== 'completed' && task.status !== 'pending' && task.status !== 'running';
    }).length;
  }, [sortedChapters, analysisTasksMap]);

  if (!currentProject) return null;

  // 获取人称的中文显示文本（同时支持中英文值）
  const getNarrativePerspectiveText = (perspective?: string): string => {
    const texts: Record<string, string> = {
      // 英文值映射（向后兼容）
      'first_person': 'Ngôi thứ nhất (tôi)',
      'third_person': 'Ngôi thứ ba (anh/cô ấy)',
      'omniscient': 'Góc nhìn toàn tri',
      // 中文值映射（项目设置使用）
      '第一人称': 'Ngôi thứ nhất (tôi)',
      '第三人称': 'Ngôi thứ ba (anh/cô ấy)',
      '全知视角': 'Góc nhìn toàn tri',
    };
    return texts[perspective || ''] || 'Ngôi thứ ba (mặc định)';
  };

  const canGenerateChapter = (chapter: Chapter): boolean => {
    return chapterGenerateGateMap[chapter.id]?.canGenerate ?? true;
  };

  const getGenerateDisabledReason = (chapter: Chapter): string => {
    return chapterGenerateGateMap[chapter.id]?.reason || '';
  };

  const handleOpenModal = (id: string) => {
    const chapter = chapters.find(c => c.id === id);
    if (chapter) {
      form.setFieldsValue(chapter);
      setEditingId(id);
      setIsModalOpen(true);
    }
  };

  const handleSubmit = async (values: ChapterUpdate) => {
    if (!editingId) return;

    try {
      await updateChapter(editingId, values);

      // 刷新章节列表以获取完整的章节数据（包括outline_title等联查字段）
      await refreshChapters();

      message.success('Cập nhật chương thành công');
      setIsModalOpen(false);
      form.resetFields();
    } catch {
      message.error('Thao tác thất bại');
    }
  };

  const handleOpenEditor = (id: string) => {
    const chapter = chapters.find(c => c.id === id);
    if (chapter) {
      setCurrentChapter(chapter);
      editorForm.setFieldsValue({
        title: chapter.title,
        content: chapter.content,
      });
      setEditingId(id);
      setTemporaryNarrativePerspective(undefined); // 重置人称选择
      setSelectedSkillKey(undefined); // 重置Skill选择
      setIsEditorOpen(true);
      // 打开Chỉnh sửa窗口时加载模型列表和Skill列表
      loadAvailableModels();
      loadAvailableSkills();
    }
  };

  const handleEditorSubmit = async (values: ChapterUpdate) => {
    if (!editingId || !currentProject) return;

    try {
      await updateChapter(editingId, values);

      // 刷新项目信息以Cập nhật总字数统计
      const updatedProject = await projectApi.getProject(currentProject.id);
      setCurrentProject(updatedProject);

      message.success('Lưu chương thành công');
      setIsEditorOpen(false);
    } catch {
      message.error('Lưu thất bại');
    }
  };

  const handleGenerate = async () => {
    if (!editingId) return;

    try {
      setIsContinuing(true);
      setIsGenerating(true);
      setSingleChapterProgress(0);
      setSingleChapterProgressMessage('Đang chuẩn bị tạo...');

      const result = await generateChapterContentStream(
        editingId,
        (content) => {
          editorForm.setFieldsValue({ content });

          if (contentTextAreaRef.current) {
            const textArea = contentTextAreaRef.current.resizableTextArea?.textArea;
            if (textArea) {
              textArea.scrollTop = textArea.scrollHeight;
            }
          }
        },
        selectedStyleId,
        targetWordCount,
        (progressMsg, progressValue) => {
          // 进度回调
          setSingleChapterProgress(progressValue);
          setSingleChapterProgressMessage(progressMsg);
        },
        selectedModel,  // 传递选中的模型
        temporaryNarrativePerspective,  // 传递临时人称参数
        selectedSkillKey  // 传递选中的Skill
      );

      message.success('AI sáng tác thành công, đang phân tích nội dung chương...');

      // 如果返回了分析任务ID，启动轮询
      if (result?.analysis_task_id) {
        const taskId = result.analysis_task_id;
        setAnalysisTasksMap(prev => ({
          ...prev,
          [editingId]: {
            has_task: true,
            task_id: taskId,
            chapter_id: editingId,
            status: 'pending',
            progress: 0
          }
        }));

        // 启动轮询
        startPollingTask(editingId);
      }
    } catch (error) {
      const apiError = error as ApiError;
      message.error('AI sáng tác thất bại: ' + (apiError.response?.data?.detail || apiError.message || 'Lỗi không xác định'));
    } finally {
      setIsContinuing(false);
      setIsGenerating(false);
      setSingleChapterProgress(0);
      setSingleChapterProgressMessage('');
    }
  };

  const showGenerateModal = (chapter: Chapter) => {
    const previousChapters = chapters.filter(
      c => c.chapter_number < chapter.chapter_number
    ).sort((a, b) => a.chapter_number - b.chapter_number);

    const selectedStyle = writingStyles.find(s => s.id === selectedStyleId);

    const instance = modal.confirm({
      title: 'AI sáng tác nội dung chương',
      width: 700,
      centered: true,
      content: (
        <div style={{ marginTop: 16 }}>
          <p>AI sẽ dựa trên các thông tin sau để sáng tác chương này:</p>
          <ul>
            <li>Dàn ý và yêu cầu của chương</li>
            <li>Thiết lập bối cảnh thế giới của dự án</li>
            <li>Thông tin nhân vật liên quan</li>
            <li><strong>Nội dung các chương trước đã hoàn thành (đảm bảo cốt truyện liền mạch)</strong></li>
            {selectedStyle && (
              <li><strong>Phong cách viết: {selectedStyle.name}</strong></li>
            )}
            <li><strong>Số chữ mục tiêu: {targetWordCount} chữ</strong></li>
          </ul>

          {previousChapters.length > 0 && (
            <div style={{
              marginTop: 16,
              padding: 12,
              background: token.colorInfoBg,
              borderRadius: token.borderRadius,
              border: `1px solid ${token.colorInfoBorder}`
            }}>
              <div style={{ marginBottom: 8, fontWeight: 500, color: token.colorPrimary }}>
                📚 Các chương trước sẽ được tham chiếu (tổng {previousChapters.length} chương):
              </div>
              <div style={{ maxHeight: 150, overflowY: 'auto' }}>
                {previousChapters.map(ch => (
                  <div key={ch.id} style={{ padding: '4px 0', fontSize: 13 }}>
                    ✓ Chương {ch.chapter_number}: {ch.title} ({ch.word_count || 0} chữ)
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: token.colorTextSecondary }}>
                💡 AI sẽ tham khảo nội dung các chương này để đảm bảo tình tiết liền mạch, trạng thái nhân vật nhất quán
              </div>
            </div>
          )}

          <p style={{ color: token.colorError, marginTop: 16, marginBottom: 0 }}>
            ⚠️ Lưu ý: thao tác này sẽ ghi đè nội dung chương hiện tại
          </p>
        </div>
      ),
      okText: 'Bắt đầu sáng tác',
      okButtonProps: { danger: true },
      cancelText: 'Hủy',
      onOk: async () => {
        instance.update({
          okButtonProps: { danger: true, loading: true },
          cancelButtonProps: { disabled: true },
          closable: false,
          maskClosable: false,
          keyboard: false,
        });

        try {
          if (!selectedStyleId) {
            message.error('Vui lòng chọn phong cách viết trước');
            instance.update({
              okButtonProps: { danger: true, loading: false },
              cancelButtonProps: { disabled: false },
              closable: true,
              maskClosable: true,
              keyboard: true,
            });
            return;
          }
          await handleGenerate();
          instance.destroy();
        } catch {
          instance.update({
            okButtonProps: { danger: true, loading: false },
            cancelButtonProps: { disabled: false },
            closable: true,
            maskClosable: true,
            keyboard: true,
          });
        }
      },
      onCancel: () => {
        if (isGenerating) {
          message.warning('AI đang sáng tác, vui lòng đợi hoàn tất');
          return false;
        }
      },
    });
  };


  // 后台生成章节（关闭浏览器也不影响）
  // 不再强制显示进度弹窗，任务进度在右下角悬浮任务框中显示
  const handleBackgroundGenerate = async () => {
    if (!editingId) return;
    if (!selectedStyleId) {
      message.error("Vui lòng chọn phong cách viết trước");
      return;
    }

    try {
      const generatedChapterId = editingId;
      const generatedProjectId = currentProject?.id;
      let analysisTrackingStarted = false;

      const refreshGeneratedChapter = async () => {
        if (!generatedProjectId || currentProjectIdRef.current !== generatedProjectId) return [];

        const latestChapters = await refreshChapters(generatedProjectId);
        const latestChapter = latestChapters.find(chapter => chapter.id === generatedChapterId);
        if (latestChapter && editingIdRef.current === generatedChapterId) {
          setCurrentChapter(latestChapter);
          editorForm.setFieldsValue({
            title: latestChapter.title,
            content: latestChapter.content,
          });
        }

        projectApi.getProject(generatedProjectId).then(setCurrentProject).catch(console.error);
        return latestChapters;
      };

      await generateChapterBackground(
        generatedChapterId,
        {
          style_id: selectedStyleId,
          target_word_count: targetWordCount,
          model: selectedModel,
          narrative_perspective: temporaryNarrativePerspective,
        },
        async (status) => {
          if (status.progress_details?.stage !== 'analyzing' || analysisTrackingStarted) return;

          analysisTrackingStarted = true;
          const latestChapters = await refreshGeneratedChapter();
          await loadAnalysisTasks(latestChapters);
        },
        async () => {
          message.success("Tạo và phân tích chương chạy nền đã hoàn tất!");
          const latestChapters = await refreshGeneratedChapter();
          await loadAnalysisTasks(latestChapters);
        },
        async (error) => {
          message.error("Tác vụ chương chạy nền thất bại: " + error);
          const latestChapters = await refreshGeneratedChapter();
          await loadAnalysisTasks(latestChapters);
        }
      );

      message.info("Đã gửi tác vụ tạo chương, xem tiến độ ở bảng tác vụ góc dưới bên phải");
      // 通知悬浮任务框刷新
      eventBus.emit('background-task-created');
    } catch {
      message.error("Tạo tác vụ chạy nền thất bại");
    }
  };
  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      'draft': 'default',
      'pending': 'warning',
      'writing': 'processing',
      'completed': 'success',
    };
    return colors[status] || 'default';
  };

  const getStatusText = (status: string) => {
    const texts: Record<string, string> = {
      'draft': 'Bản nháp',
      'pending': 'Chờ xử lý',
      'writing': 'Đang sáng tác',
      'completed': 'Đã hoàn thành',
    };
    return texts[status] || status;
  };

  const handleExport = () => {
    if (chapters.length === 0) {
      message.warning('Dự án hiện tại chưa có chương nào, không thể xuất');
      return;
    }

    modal.confirm({
      title: 'Xuất chương của dự án',
      content: `Bạn có chắc muốn xuất toàn bộ chương của «${currentProject.title}» ra tệp TXT không?`,
      centered: true,
      okText: 'Xác nhận xuất',
      cancelText: 'Hủy',
      onOk: () => {
        try {
          projectApi.exportProject(currentProject.id);
          message.success('Bắt đầu tải tệp xuất');
        } catch {
          message.error('Xuất thất bại, vui lòng thử lại');
        }
      },
    });
  };

  const handleShowAnalysis = (chapterId: string) => {
    setAnalysisChapterId(chapterId);
    setAnalysisVisible(true);
  };

  // 一键按章节顺序分析未分析章节
  const handleBatchAnalyzeUnanalyzed = async () => {
    if (!currentProject?.id) return;

    try {
      setBatchAnalyzingUnanalyzed(true);
      const result = await chapterApi.batchAnalyzeUnanalyzed(currentProject.id);

      if (result.total_started > 0) {
        setAnalysisTasksMap((prev) => ({
          ...prev,
          ...result.started_tasks,
        }));

        Object.keys(result.started_tasks).forEach((chapterId) => {
          startPollingTask(chapterId);
        });

        message.success(
          `Đã thêm ${result.total_started} chương vào hàng đợi phân tích theo thứ tự (bỏ qua ${result.total_already_completed} chương đã phân tích, ${result.total_skipped_running} chương đang phân tích/chờ)`
        );
      } else {
        message.info('Không có chương nào có thể bắt đầu phân tích: chương hiện tại không có nội dung, đã phân tích xong hoặc đang được phân tích');
      }

      // 刷新一次状态，确保前端与后端一致
      await loadAnalysisTasks();
    } catch (error: unknown) {
      const err = error as Error;
      message.error(`Phân tích hàng loạt thất bại: ${err.message || 'Lỗi không xác định'}`);
    } finally {
      setBatchAnalyzingUnanalyzed(false);
    }
  };

  // 批量生成函数
  const handleBatchGenerate = async (values: {
    startChapterNumber: number;
    count: number;
    enableAnalysis: boolean;
    styleId?: number;
    targetWordCount?: number;
    model?: string;
  }) => {
    if (!currentProject?.id) return;

    // 调试日志
    console.log('[Tạo hàng loạt] giá trị form:', values);
    console.log('[Tạo hàng loạt] trạng thái batchSelectedModel:', batchSelectedModel);

    // 使用批量生成对话框中选择的风格和字数，如果没有选择则使用默认值
    const styleId = values.styleId || selectedStyleId;
    const wordCount = values.targetWordCount || targetWordCount;

    // 使用批量生成专用的模型状态
    const model = batchSelectedModel;

    console.log('[Tạo hàng loạt] model dùng cuối cùng:', model);

    if (!styleId) {
      message.error('Vui lòng chọn phong cách viết');
      return;
    }

    try {
      setBatchGenerating(true);
      setBatchGenerateVisible(false); // 关闭配置对话框，任务进度在悬浮任务框中显示

      const requestBody: {
        start_chapter_number: number;
        count: number;
        enable_analysis: boolean;
        style_id: number;
        target_word_count: number;
        model?: string;
        skill_key?: string;
      } = {
        start_chapter_number: values.startChapterNumber,
        count: values.count,
        enable_analysis: values.enableAnalysis,
        style_id: styleId,
        target_word_count: wordCount,
      };

      // 如果有模型参数，添加到请求体中
      if (model) {
        requestBody.model = model;
        console.log('[Tạo hàng loạt] body request có model:', model);
      } else {
        console.log('[Tạo hàng loạt] body request không có model, dùng model mặc định của backend');
      }

      // 如果有 Skill 参数，添加到请求体中
      if (batchSelectedSkillKey) {
        requestBody.skill_key = batchSelectedSkillKey;
        console.log('[Tạo hàng loạt] body request có skill_key:', batchSelectedSkillKey);
      }

      console.log('[Tạo hàng loạt] body request đầy đủ:', JSON.stringify(requestBody, null, 2));

      const response = await fetch(`/api/chapters/project/${currentProject.id}/batch-generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Tạo tác vụ tạo hàng loạt thất bại');
      }

      const result = await response.json();
      setBatchTaskId(result.batch_id);
      setBatchProgress({
        status: 'running',
        total: result.chapters_to_generate.length,
        completed: 0,
        current_chapter_number: values.startChapterNumber,
        estimated_time_minutes: result.estimated_time_minutes,
      });

      message.success(`Đã tạo tác vụ tạo hàng loạt, dự kiến cần ${result.estimated_time_minutes} phút, xem tiến độ ở bảng tác vụ góc dưới bên phải`);
      // 通知悬浮任务框刷新
      eventBus.emit('background-task-created');

      // 🔔 触发浏览器通知（任务开始）
      showBrowserNotification(
        'Tạo hàng loạt đã bắt đầu',
        `Bắt đầu tạo ${result.chapters_to_generate.length} chương, dự kiến cần ${result.estimated_time_minutes} phút`,
        'info'
      );

      // 开始轮询任务状态
      startBatchPolling(result.batch_id);

    } catch (error: unknown) {
      const err = error as Error;
      message.error('Tạo tác vụ tạo hàng loạt thất bại: ' + (err.message || 'Lỗi không xác định'));
      setBatchGenerating(false);
      setBatchGenerateVisible(false);
    }
  };

  // 轮询批量生成任务状态
  const startBatchPolling = (taskId: string) => {
    if (batchPollingIntervalRef.current) {
      clearInterval(batchPollingIntervalRef.current);
    }

    const poll = async () => {
      try {
        const response = await fetch(`/api/chapters/batch-generate/${taskId}/status`);
        if (!response.ok) return;

        const status = await response.json();
        setBatchProgress({
          status: status.status,
          total: status.total,
          completed: status.completed,
          current_chapter_number: status.current_chapter_number,
        });

        // 每次轮询时刷新章节列表和分析状态，实时显示新生成的章节和分析进度
        // 使用 await 确保获取最新章节列表后再加载分析任务状态
        if (status.completed > 0) {
          const latestChapters = await refreshChapters();
          await loadAnalysisTasks(latestChapters);

          // 刷新项目信息以实时Cập nhật总字数统计
          if (currentProject?.id) {
            const updatedProject = await projectApi.getProject(currentProject.id);
            setCurrentProject(updatedProject);
          }
        }

        // 任务完成或失败，停止轮询
        if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
          if (batchPollingIntervalRef.current) {
            clearInterval(batchPollingIntervalRef.current);
            batchPollingIntervalRef.current = null;
          }

          setBatchGenerating(false);

          // 立即刷新章节列表和分析任务状态（在显示消息前）
          // 使用 refreshChapters 返回的最新章节列表传递给 loadAnalysisTasks
          const finalChapters = await refreshChapters();
          await loadAnalysisTasks(finalChapters);

          // 刷新项目信息以Cập nhật总字数统计
          if (currentProject?.id) {
            const updatedProject = await projectApi.getProject(currentProject.id);
            setCurrentProject(updatedProject);
          }

          if (status.status === 'completed') {
            message.success(`Tạo hàng loạt hoàn tất! Đã tạo thành công ${status.completed} chương`);
            // 🔔 触发浏览器通知
            showBrowserNotification(
              'Tạo hàng loạt hoàn tất',
              `«${currentProject?.title || 'Dự án'}» đã tạo thành công ${status.completed} chương`,
              'success'
            );
          } else if (status.status === 'failed') {
            message.error(`Tạo hàng loạt thất bại: ${status.error_message || 'Lỗi không xác định'}`);
            // 🔔 触发浏览器通知
            showBrowserNotification(
              'Tạo hàng loạt thất bại',
              status.error_message || 'Lỗi không xác định',
              'error'
            );
          } else if (status.status === 'cancelled') {
            message.warning('Đã hủy tạo hàng loạt');
          }

          // 延迟关闭对话框，让用户看到最终状态
          setTimeout(() => {
            setBatchGenerateVisible(false);
            setBatchTaskId(null);
            setBatchProgress(null);
          }, 2000);
        }
      } catch (error) {
        console.error('Thăm dò trạng thái tạo hàng loạt thất bại:', error);
      }
    };

    // 立即执行一次
    poll();

    // 每2秒轮询一次
    batchPollingIntervalRef.current = window.setInterval(poll, 2000);
  };

  // Hủy批量生成
  const handleCancelBatchGenerate = async () => {
    if (!batchTaskId) return;

    try {
      const response = await fetch(`/api/chapters/batch-generate/${batchTaskId}/cancel`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Hủy thất bại');
      }

      message.success('Đã hủy tạo hàng loạt');

      // Hủy后立即刷新章节列表和分析任务，显示已生成的章节
      await refreshChapters();
      await loadAnalysisTasks();

      // 刷新项目信息以Cập nhật总字数统计
      if (currentProject?.id) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }
    } catch (error: unknown) {
      const err = error as Error;
      message.error('Hủy thất bại: ' + (err.message || 'Lỗi không xác định'));
    }
  };

  // 打开批量生成对话框
  const handleOpenBatchGenerate = async () => {
    // 找到第一个未生成的章节
    const firstIncompleteChapter = sortedChapters.find(
      ch => !ch.content || ch.content.trim() === ''
    );

    if (!firstIncompleteChapter) {
      message.info('Tất cả chương đều đã có nội dung');
      return;
    }

    // 检查该章节是否可以生成
    if (!canGenerateChapter(firstIncompleteChapter)) {
      const reason = getGenerateDisabledReason(firstIncompleteChapter);
      message.warning(reason);
      return;
    }

    // 打开对话框时加载模型列表和Skill列表，等待完成
    const defaultModel = await loadAvailableModels();
    loadAvailableSkills();

    console.log('[Mở tạo hàng loạt] defaultModel:', defaultModel);
    console.log('[Mở tạo hàng loạt] selectedStyleId:', selectedStyleId);

    // 设置批量生成的模型选择状态
    setBatchSelectedModel(defaultModel || undefined);

    // 重置表单并设置初始值（使用缓存的字数）
    batchForm.setFieldsValue({
      startChapterNumber: firstIncompleteChapter.chapter_number,
      count: 5,
      enableAnalysis: true,
      styleId: selectedStyleId,
      targetWordCount: getCachedWordCount(),
    });

    setBatchGenerateVisible(true);
  };

  // 手动创建章节(仅one-to-many模式)
  const showManualCreateChapterModal = () => {
    // 计算下一个章节号
    const nextChapterNumber = chapters.length > 0
      ? Math.max(...chapters.map(c => c.chapter_number)) + 1
      : 1;

    modal.confirm({
      title: 'Tạo chương thủ công',
      width: 600,
      centered: true,
      content: (
        <Form
          form={manualCreateForm}
          layout="vertical"
          initialValues={{
            chapter_number: nextChapterNumber,
            status: 'draft'
          }}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="Số thứ tự chương"
            name="chapter_number"
            rules={[{ required: true, message: 'Vui lòng nhập số thứ tự chương' }]}
            tooltip="Nên tạo chương theo thứ tự để đảm bảo nội dung liền mạch"
          >
            <InputNumber min={1} style={{ width: '100%' }} placeholder="Số thứ tự kế tiếp được tính tự động" />
          </Form.Item>

          <Form.Item
            label="Tiêu đề chương"
            name="title"
            rules={[{ required: true, message: 'Vui lòng nhập tiêu đề' }]}
          >
            <Input placeholder="Ví dụ: Chương 1 Lần đầu gặp gỡ" />
          </Form.Item>

          <Form.Item
            label="Dàn ý liên kết"
            name="outline_id"
            rules={[{ required: true, message: 'Vui lòng chọn dàn ý liên kết' }]}
            tooltip="Ở chế độ one-to-many, chương phải được liên kết với dàn ý"
          >
            <Select placeholder="Vui lòng chọn dàn ý">
              {/* 直接使用 store 中的 outlines 数据，而不是从现有章节中提取 */}
              {[...outlines]
                .sort((a, b) => a.order_index - b.order_index)
                .map(outline => (
                  <Select.Option key={outline.id} value={outline.id}>
                    Tập {outline.order_index}: {outline.title}
                  </Select.Option>
                ))}
            </Select>
          </Form.Item>

          <Form.Item
            label="Tóm tắt chương (tùy chọn)"
            name="summary"
            tooltip="Mô tả ngắn gọn nội dung chính và diễn biến tình tiết của chương này"
          >
            <TextArea
              rows={4}
              placeholder="Mô tả ngắn gọn nội dung chương..."
            />
          </Form.Item>

          <Form.Item
            label="Trạng thái"
            name="status"
          >
            <Select>
              <Select.Option value="draft">Bản nháp</Select.Option>
              <Select.Option value="pending">Chờ xử lý</Select.Option>
              <Select.Option value="writing">Đang sáng tác</Select.Option>
              <Select.Option value="completed">Đã hoàn thành</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      ),
      okText: 'Tạo',
      cancelText: 'Hủy',
      onOk: async () => {
        const values = await manualCreateForm.validateFields();

        // 检查章节序号是否已存在
        const conflictChapter = chapters.find(
          ch => ch.chapter_number === values.chapter_number
        );

        if (conflictChapter) {
          // 显示冲突提示Modal
          modal.confirm({
            title: 'Trùng số thứ tự chương',
            icon: <InfoCircleOutlined style={{ color: token.colorError }} />,
            width: 500,
            centered: true,
            content: (
              <div>
                <p style={{ marginBottom: 12 }}>
                  Chương <strong>{values.chapter_number}</strong> đã tồn tại:
                </p>
                <div style={{
                  padding: 12,
                  background: token.colorWarningBg,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorWarningBorder}`,
                  marginBottom: 12
                }}>
                  <div><strong>Tiêu đề:</strong>{conflictChapter.title}</div>
                  <div><strong>Trạng thái:</strong>{getStatusText(conflictChapter.status)}</div>
                  <div><strong>Số chữ:</strong>{conflictChapter.word_count || 0} chữ</div>
                  {conflictChapter.outline_title && (
                    <div><strong>Thuộc dàn ý:</strong>{conflictChapter.outline_title}</div>
                  )}
                </div>
                <p style={{ color: token.colorError, marginBottom: 8 }}>
                  ⚠️ Xóa chương cũ và tạo chương mới?
                </p>
                <p style={{ fontSize: 12, color: token.colorTextSecondary, marginBottom: 0 }}>
                  Sau khi xóa sẽ không thể khôi phục, nội dung chương và kết quả phân tích đều sẽ bị xóa.
                </p>
              </div>
            ),
            okText: 'Xóa và tạo mới',
            okButtonProps: { danger: true },
            cancelText: 'Hủy',
            onOk: async () => {
              try {
                // 先Xóa旧章节
                await handleDeleteChapter(conflictChapter.id);

                // 等待一小段时间确保Xóa完成
                await new Promise(resolve => setTimeout(resolve, 300));

                // 创建新章节
                await chapterApi.createChapter({
                  project_id: currentProject.id,
                  ...values
                });

                message.success('Đã xóa chương cũ và tạo chương mới');
                await refreshChapters();

                // 刷新项目信息以Cập nhật字数统计
                const updatedProject = await projectApi.getProject(currentProject.id);
                setCurrentProject(updatedProject);

                manualCreateForm.resetFields();
              } catch (error: unknown) {
                const err = error as Error;
                message.error('Thao tác thất bại: ' + (err.message || 'Lỗi không xác định'));
                throw error;
              }
            }
          });

          // 阻止外层Modal关闭
          return Promise.reject();
        }

        // 没有冲突，直接创建
        try {
          await chapterApi.createChapter({
            project_id: currentProject.id,
            ...values
          });
          message.success('Tạo chương thành công');
          await refreshChapters();

          // 刷新项目信息以Cập nhật字数统计
          const updatedProject = await projectApi.getProject(currentProject.id);
          setCurrentProject(updatedProject);

          manualCreateForm.resetFields();
        } catch (error: unknown) {
          const err = error as Error;
          message.error('Tạo thất bại: ' + (err.message || 'Lỗi không xác định'));
          throw error;
        }
      }
    });
  };

  // 渲染分析状态标签
  const renderAnalysisStatus = (chapterId: string) => {
    const task = analysisTasksMap[chapterId];

    if (!task) {
      return null;
    }

    switch (task.status) {
      case 'pending':
        return (
          <Tag icon={<SyncOutlined spin />} color="processing">
            Chờ phân tích
          </Tag>
        );
      case 'running': {
        // 检查是否正在重试（后端会在error_message中包含"thử lại"信息）
        const isRetrying = task.error_message && (task.error_message.includes('thử lại') || task.error_message.includes('重试'));
        return (
          <Tag
            icon={<SyncOutlined spin />}
            color={isRetrying ? "warning" : "processing"}
            title={task.error_message || undefined}
          >
            {isRetrying ? `Đang thử lại ${task.progress}%` : `Đang phân tích ${task.progress}%`}
          </Tag>
        );
      }
      case 'completed':
        return (
          <Tag icon={<CheckCircleOutlined />} color="success">
            Đã phân tích
          </Tag>
        );
      case 'failed':
        return (
          <Tag icon={<CloseCircleOutlined />} color="error" title={task.error_message || undefined}>
            Phân tích thất bại
          </Tag>
        );
      default:
        return null;
    }
  };

  // 显示展开规划详情
  const showExpansionPlanModal = (chapter: Chapter) => {
    if (!chapter.expansion_plan) return;

    try {
      const planData: ExpansionPlanData = JSON.parse(chapter.expansion_plan);

      modal.info({
        title: (
          <Space style={{ flexWrap: 'wrap' }}>
            <InfoCircleOutlined style={{ color: token.colorPrimary }} />
            <span style={{ wordBreak: 'break-word' }}>Kế hoạch mở rộng chương {chapter.chapter_number}</span>
          </Space>
        ),
        width: isMobile ? 'calc(100vw - 32px)' : 800,
        centered: true,
        style: isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined,
        styles: {
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(80vh - 110px)',
            overflowY: 'auto'
          }
        },
        content: (
          <div style={{ marginTop: 16 }}>
            <Descriptions
              column={1}
              size="small"
              bordered
              labelStyle={{
                whiteSpace: 'normal',
                wordBreak: 'break-word',
                width: isMobile ? '80px' : '100px'
              }}
              contentStyle={{
                whiteSpace: 'normal',
                wordBreak: 'break-word',
                overflowWrap: 'break-word'
              }}
            >
              <Descriptions.Item label="Tiêu đề chương">
                <strong style={{
                  wordBreak: 'break-word',
                  whiteSpace: 'normal',
                  overflowWrap: 'break-word'
                }}>
                  {chapter.title}
                </strong>
              </Descriptions.Item>
              <Descriptions.Item label="Sắc thái cảm xúc">
                <Tag
                  color="blue"
                  style={{
                    whiteSpace: 'normal',
                    wordBreak: 'break-word',
                    height: 'auto',
                    lineHeight: '1.5',
                    padding: '4px 8px'
                  }}
                >
                  {planData.emotional_tone}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Loại xung đột">
                <Tag
                  color="orange"
                  style={{
                    whiteSpace: 'normal',
                    wordBreak: 'break-word',
                    height: 'auto',
                    lineHeight: '1.5',
                    padding: '4px 8px'
                  }}
                >
                  {planData.conflict_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Số chữ ước tính">
                <Tag color="green">{planData.estimated_words} chữ</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Mục tiêu tự sự">
                <span style={{
                  wordBreak: 'break-word',
                  whiteSpace: 'normal',
                  overflowWrap: 'break-word'
                }}>
                  {planData.narrative_goal}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Sự kiện then chốt">
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  {planData.key_events.map((event, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '4px 0',
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}
                    >
                      <Tag color="purple" style={{ flexShrink: 0 }}>{idx + 1}</Tag>{' '}
                      <span style={{
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}>
                        {event}
                      </span>
                    </div>
                  ))}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Nhân vật liên quan">
                <Space wrap style={{ maxWidth: '100%' }}>
                  {planData.character_focus.map((char, idx) => (
                    <Tag
                      key={idx}
                      color="cyan"
                      style={{
                        whiteSpace: 'normal',
                        wordBreak: 'break-word',
                        height: 'auto',
                        lineHeight: '1.5'
                      }}
                    >
                      {char}
                    </Tag>
                  ))}
                </Space>
              </Descriptions.Item>
              {planData.scenes && planData.scenes.length > 0 && (
                <Descriptions.Item label="Kế hoạch cảnh">
                  <Space direction="vertical" size="small" style={{ width: '100%' }}>
                    {planData.scenes.map((scene, idx) => (
                      <Card
                        key={idx}
                        size="small"
                        style={{
                          backgroundColor: token.colorFillQuaternary,
                          maxWidth: '100%',
                          overflow: 'hidden'
                        }}
                      >
                        <div style={{
                          marginBottom: 4,
                          wordBreak: 'break-word',
                          whiteSpace: 'normal',
                          overflowWrap: 'break-word'
                        }}>
                          <strong>📍 Địa điểm:</strong>
                          <span style={{
                            wordBreak: 'break-word',
                            whiteSpace: 'normal',
                            overflowWrap: 'break-word'
                          }}>
                            {scene.location}
                          </span>
                        </div>
                        <div style={{ marginBottom: 4 }}>
                          <strong>👥 Nhân vật:</strong>
                          <Space
                            size="small"
                            wrap
                            style={{
                              marginLeft: isMobile ? 0 : 8,
                              marginTop: isMobile ? 4 : 0,
                              display: isMobile ? 'flex' : 'inline-flex'
                            }}
                          >
                            {scene.characters.map((char, charIdx) => (
                              <Tag
                                key={charIdx}
                                style={{
                                  whiteSpace: 'normal',
                                  wordBreak: 'break-word',
                                  height: 'auto'
                                }}
                              >
                                {char}
                              </Tag>
                            ))}
                          </Space>
                        </div>
                        <div style={{
                          wordBreak: 'break-word',
                          whiteSpace: 'normal',
                          overflowWrap: 'break-word'
                        }}>
                          <strong>🎯 Mục đích:</strong>
                          <span style={{
                            wordBreak: 'break-word',
                            whiteSpace: 'normal',
                            overflowWrap: 'break-word'
                          }}>
                            {scene.purpose}
                          </span>
                        </div>
                      </Card>
                    ))}
                  </Space>
                </Descriptions.Item>
              )}
            </Descriptions>
            <Alert
              message="Gợi ý"
              description="Đây là thông tin kế hoạch do AI tạo khi mở rộng dàn ý, có thể dùng làm tham khảo khi sáng tác nội dung chương."
              type="info"
              showIcon
              style={{ marginTop: 16 }}
            />
          </div>
        ),
        okText: 'Đóng',
      });
    } catch (error) {
      console.error('Phân tích kế hoạch mở rộng thất bại:', error);
      message.error('Dữ liệu kế hoạch mở rộng sai định dạng');
    }
  };

  // Xóa章节处理函数
  const handleDeleteChapter = async (chapterId: string) => {
    try {
      await deleteChapter(chapterId);

      // 刷新章节列表
      await refreshChapters();

      // 刷新项目信息以Cập nhật总字数统计
      if (currentProject) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }

      message.success('Xóa chương thành công');
    } catch (error: unknown) {
      const err = error as Error;
      message.error('Xóa chương thất bại: ' + (err.message || 'Lỗi không xác định'));
    }
  };

  // 打开规划Chỉnh sửa器
  const handleOpenPlanEditor = (chapter: Chapter) => {
    // 直接打开Chỉnh sửa器,如果没有规划数据则创建新的
    setEditingPlanChapter(chapter);
    setPlanEditorVisible(true);
  };

  // 保存规划信息
  const handleSavePlan = async (planData: ExpansionPlanData) => {
    if (!editingPlanChapter) return;

    try {
      const response = await fetch(`/api/chapters/${editingPlanChapter.id}/expansion-plan`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(planData),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Cập nhật thất bại');
      }

      // 刷新章节列表
      await refreshChapters();

      message.success('Cập nhật thông tin kế hoạch thành công');

      // 关闭Chỉnh sửa器
      setPlanEditorVisible(false);
      setEditingPlanChapter(null);
    } catch (error: unknown) {
      const err = error as Error;
      message.error('Lưu kế hoạch thất bại: ' + (err.message || 'Lỗi không xác định'));
      throw error;
    }
  };

  // 打开Đọc器
  const handleOpenReader = (chapter: Chapter) => {
    setReadingChapter(chapter);
    setReaderVisible(true);
  };

  // Đọc器切换章节
  const handleReaderChapterChange = async (chapterId: string) => {
    try {
      const response = await fetch(`/api/chapters/${chapterId}`);
      if (!response.ok) throw new Error('Không lấy được chương');
      const newChapter = await response.json();
      setReadingChapter(newChapter);
    } catch {
      message.error('Tải chương thất bại');
    }
  };

  // 打开局部重写弹窗
  const handleOpenPartialRegenerate = () => {
    setPartialRegenerateToolbarVisible(false);
    setPartialRegenerateModalVisible(true);
  };

  // 应用局部重写结果
  const handleApplyPartialRegenerate = (newText: string, startPos: number, endPos: number) => {
    // 获取当前内容
    const currentContent = editorForm.getFieldValue('content') || '';
    
    // 替换选中部分
    const newContent = currentContent.substring(0, startPos) + newText + currentContent.substring(endPos);
    
    // Cập nhật表单
    editorForm.setFieldsValue({ content: newContent });
    
    // 关闭弹窗
    setPartialRegenerateModalVisible(false);
    
    message.success('Đã áp dụng viết lại cục bộ');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {contextHolder}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: token.colorBgContainer,
        padding: isMobile ? '12px 0' : '16px 0',
        marginBottom: isMobile ? 12 : 16,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        flexDirection: isMobile ? 'column' : 'row',
        gap: isMobile ? 12 : 0,
        justifyContent: 'space-between',
        alignItems: isMobile ? 'stretch' : 'center'
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: isMobile ? 18 : 24 }}>
            <BookOutlined style={{ marginRight: 8 }} />
            Quản lý chương
          </h2>
          <Tag
            color={currentProject.outline_mode === 'one-to-one' ? 'blue' : 'green'}
            style={{ width: 'fit-content' }}
          >
            {currentProject.outline_mode === 'one-to-one'
              ? 'Chế độ truyền thống: chương do dàn ý quản lý, vui lòng thao tác ở trang dàn ý'
              : 'Chế độ chi tiết: chương có thể mở rộng ở trang dàn ý'}
          </Tag>
        </div>
        <Space direction={isMobile ? 'vertical' : 'horizontal'} style={{ width: isMobile ? '100%' : 'auto' }}>
          <Input.Search
            allowClear
            placeholder="Tìm chương (số thứ tự/tiêu đề/dàn ý)"
            value={chapterSearchKeyword}
            onChange={(e) => setChapterSearchKeyword(e.target.value)}
            style={{ width: isMobile ? '100%' : 280 }}
          />
          {currentProject.outline_mode === 'one-to-many' && (
            <Button
              icon={<PlusOutlined />}
              onClick={showManualCreateChapterModal}
              block={isMobile}
              size={isMobile ? 'middle' : 'middle'}
            >
              Tạo thủ công
            </Button>
          )}
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleBatchAnalyzeUnanalyzed}
            loading={batchAnalyzingUnanalyzed}
            disabled={chapters.length === 0 || batchAnalyzableChapterCount === 0}
            block={isMobile}
            size={isMobile ? 'middle' : 'middle'}
            style={{ background: token.colorWarning, borderColor: token.colorWarning }}
            title={batchAnalyzableChapterCount === 0 ? 'Chưa có chương nào có thể phân tích hàng loạt' : `Có thể phân tích hàng loạt ${batchAnalyzableChapterCount} chương`}
          >
            Phân tích hàng loạt{batchAnalyzableChapterCount > 0 ? ` (${batchAnalyzableChapterCount})` : ''}
          </Button>
          <Button
            type="primary"
            icon={<RocketOutlined />}
            onClick={handleOpenBatchGenerate}
            disabled={chapters.length === 0 || batchGenerating}
            loading={batchGenerating}
            block={isMobile}
            size={isMobile ? 'middle' : 'middle'}
            style={batchGenerating ? {} : { background: token.colorInfo, borderColor: token.colorInfo }}
          >
            {batchGenerating ? 'Đang tạo...' : 'Tạo hàng loạt'}
          </Button>
          <Button
            type="default"
            icon={<DownloadOutlined />}
            onClick={handleExport}
            disabled={chapters.length === 0}
            block={isMobile}
            size={isMobile ? 'middle' : 'middle'}
          >
            Xuất ra TXT
          </Button>
        </Space>
      </div>


      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {chapters.length === 0 ? (
          <Empty description="Chưa có chương nào, hãy bắt đầu sáng tác!" />
        ) : filteredSortedChapters.length === 0 ? (
          <Empty description="Không tìm thấy chương phù hợp" />
        ) : currentProject.outline_mode === 'one-to-one' ? (
          // one-to-one 模式：直接显示扁平列表
          <List
            dataSource={pagedSortedChapters}
            renderItem={(item) => (
              <List.Item
                id={`chapter-item-${item.id}`}
                style={{
                  padding: '16px',
                  marginBottom: 16,
                  background: token.colorBgContainer,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorBorderSecondary}`,
                  flexDirection: isMobile ? 'column' : 'row',
                  alignItems: isMobile ? 'flex-start' : 'center',
                }}
                actions={isMobile ? undefined : [
                  <Button
                    type="text"
                    icon={<ReadOutlined />}
                    onClick={() => handleOpenReader(item)}
                    disabled={!item.content || item.content.trim() === ''}
                    title={!item.content || item.content.trim() === '' ? 'Chưa có nội dung' : 'Đọc đắm chìm'}
                  >
                    Đọc
                  </Button>,
                  <Button
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => handleOpenEditor(item.id)}
                  >
                    Chỉnh sửa
                  </Button>,
                  (() => {
                    const task = analysisTasksMap[item.id];
                    const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                    const hasContent = item.content && item.content.trim() !== '';

                    return (
                      <Button
                        type="text"
                        icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                        onClick={() => handleShowAnalysis(item.id)}
                        disabled={!hasContent || isAnalyzing}
                        loading={isAnalyzing}
                        title={
                          !hasContent ? 'Hãy tạo nội dung chương trước' :
                            isAnalyzing ? 'Đang phân tích, vui lòng chờ...' :
                              ''
                        }
                      >
                        {isAnalyzing ? 'Đang phân tích' : 'Phân tích'}
                      </Button>
                    );
                  })(),
                  <Button
                    type="text"
                    icon={<SettingOutlined />}
                    onClick={() => handleOpenModal(item.id)}
                  >
                    Sửa
                  </Button>,
                ]}
              >
                <div style={{ width: '100%' }}>
                  <List.Item.Meta
                    avatar={!isMobile && <FileTextOutlined style={{ fontSize: 32, color: token.colorPrimary }} />}
                    title={
                      <div style={{
                        display: 'flex',
                        flexDirection: isMobile ? 'column' : 'row',
                        alignItems: isMobile ? 'flex-start' : 'center',
                        gap: isMobile ? 6 : 12,
                        width: '100%'
                      }}>
                        <span style={{ fontSize: isMobile ? 14 : 16, fontWeight: 500, flexShrink: 0 }}>
                          Chương {item.chapter_number}: {item.title}
                        </span>
                        <Space wrap size={isMobile ? 4 : 8}>
                          <Tag color={getStatusColor(item.status)}>{getStatusText(item.status)}</Tag>
                          <Badge count={`${item.word_count || 0} chữ`} style={{ backgroundColor: token.colorSuccess }} />
                          {renderAnalysisStatus(item.id)}
                          {!canGenerateChapter(item) && (
                            <Tag icon={<LockOutlined />} color="warning" title={getGenerateDisabledReason(item)}>
                              Cần chương trước
                            </Tag>
                          )}
                        </Space>
                      </div>
                    }
                    description={
                      item.content ? (
                        <div style={{ marginTop: 8, color: token.colorTextSecondary, lineHeight: 1.6, fontSize: isMobile ? 12 : 14 }}>
                          {item.content.substring(0, isMobile ? 80 : 150)}
                          {item.content.length > (isMobile ? 80 : 150) && '...'}
                        </div>
                      ) : (
                        <span style={{ color: token.colorTextTertiary, fontSize: isMobile ? 12 : 14 }}>Chưa có nội dung</span>
                      )
                    }
                  />

                  {isMobile && (
                    <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }} wrap>
                      <Button
                        type="text"
                        icon={<ReadOutlined />}
                        onClick={() => handleOpenReader(item)}
                        size="small"
                        disabled={!item.content || item.content.trim() === ''}
                        title={!item.content || item.content.trim() === '' ? 'Chưa có nội dung' : 'Đọc'}
                      />
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => handleOpenEditor(item.id)}
                        size="small"
                        title="Chỉnh sửa"
                      />
                      {(() => {
                        const task = analysisTasksMap[item.id];
                        const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                        const hasContent = item.content && item.content.trim() !== '';

                        return (
                          <Button
                            type="text"
                            icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                            onClick={() => handleShowAnalysis(item.id)}
                            size="small"
                            disabled={!hasContent || isAnalyzing}
                            loading={isAnalyzing}
                            title={
                              !hasContent ? 'Hãy tạo nội dung chương trước' :
                                isAnalyzing ? 'Đang phân tích' :
                                  'Phân tích'
                            }
                          />
                        );
                      })()}
                      <Button
                        type="text"
                        icon={<SettingOutlined />}
                        onClick={() => handleOpenModal(item.id)}
                        size="small"
                        title="Sửa"
                      />
                    </Space>
                  )}
                </div>
              </List.Item>
            )}
          />
        ) : (
          // one-to-many 模式：按大纲分组显示
          <Collapse
            bordered={false}
            defaultActiveKey={pagedGroupedChapters.length > 0 ? ['0'] : []}
            destroyInactivePanel
            expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
            style={{ background: 'transparent' }}
          >
            {pagedGroupedChapters.map((group, groupIndex) => (
              <Collapse.Panel
                key={groupIndex.toString()}
                header={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <Tag color={group.outlineId ? 'blue' : 'default'} style={{ margin: 0 }}>
                      {group.outlineId ? `📖 Dàn ý ${group.outlineOrder}` : '📝 Chưa phân loại'}
                    </Tag>
                    <span style={{ fontWeight: 600, fontSize: 16 }}>
                      {group.outlineTitle}
                    </span>
                    <Badge
                      count={`${group.chapters.length} chương`}
                      style={{ backgroundColor: token.colorSuccess }}
                    />
                    <Badge
                      count={`${group.chapters.reduce((sum, ch) => sum + (ch.word_count || 0), 0)} chữ`}
                      style={{ backgroundColor: token.colorPrimary }}
                    />
                  </div>
                }
                style={{
                  marginBottom: 16,
                  background: token.colorBgContainer,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorBorderSecondary}`,
                }}
              >
                <List
                  dataSource={group.chapters}
                  renderItem={(item) => (
                    <List.Item
                      id={`chapter-item-${item.id}`}
                      style={{
                        padding: '16px 0',
                        borderRadius: 8,
                        transition: 'background 0.3s ease',
                        flexDirection: isMobile ? 'column' : 'row',
                        alignItems: isMobile ? 'flex-start' : 'center',
                      }}
                      actions={isMobile ? undefined : [
                        <Button
                          type="text"
                          icon={<ReadOutlined />}
                          onClick={() => handleOpenReader(item)}
                          disabled={!item.content || item.content.trim() === ''}
                          title={!item.content || item.content.trim() === '' ? 'Chưa có nội dung' : 'Đọc đắm chìm'}
                        >
                          Đọc
                        </Button>,
                        <Button
                          type="text"
                          icon={<EditOutlined />}
                          onClick={() => handleOpenEditor(item.id)}
                        >
                          Chỉnh sửa
                        </Button>,
                        (() => {
                          const task = analysisTasksMap[item.id];
                          const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                          const hasContent = item.content && item.content.trim() !== '';

                          return (
                            <Button
                              type="text"
                              icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                              onClick={() => handleShowAnalysis(item.id)}
                              disabled={!hasContent || isAnalyzing}
                              loading={isAnalyzing}
                              title={
                                !hasContent ? 'Hãy tạo nội dung chương trước' :
                                  isAnalyzing ? 'Đang phân tích, vui lòng chờ...' :
                                    ''
                              }
                            >
                              {isAnalyzing ? 'Đang phân tích' : 'Phân tích'}
                            </Button>
                          );
                        })(),
                        <Button
                          type="text"
                          icon={<SettingOutlined />}
                          onClick={() => handleOpenModal(item.id)}
                        >
                          Sửa
                        </Button>,
                        // 只在 one-to-many 模式下显示Xóa按钮
                        ...(currentProject.outline_mode === 'one-to-many' ? [
                          <Popconfirm
                            title="Xác nhận xóa chương này?"
                            description="Không thể khôi phục sau khi xóa; nội dung chương và kết quả phân tích sẽ bị xóa."
                            onConfirm={() => handleDeleteChapter(item.id)}
                            okText="Xác nhận xóa"
                            cancelText="Hủy"
                            okButtonProps={{ danger: true }}
                          >
                            <Button
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                            >
                              Xóa
                            </Button>
                          </Popconfirm>
                        ] : []),
                      ]}
                    >
                      <div style={{ width: '100%' }}>
                        <List.Item.Meta
                          avatar={!isMobile && <FileTextOutlined style={{ fontSize: 32, color: token.colorPrimary }} />}
                          title={
                            <div style={{
                              display: 'flex',
                              flexDirection: isMobile ? 'column' : 'row',
                              alignItems: isMobile ? 'flex-start' : 'center',
                              gap: isMobile ? 6 : 12,
                              width: '100%'
                            }}>
                              <span style={{ fontSize: isMobile ? 14 : 16, fontWeight: 500, flexShrink: 0 }}>
                                Chương {item.chapter_number}: {item.title}
                              </span>
                              <Space wrap size={isMobile ? 4 : 8}>
                                <Tag color={getStatusColor(item.status)}>{getStatusText(item.status)}</Tag>
                                <Badge count={`${item.word_count || 0} chữ`} style={{ backgroundColor: token.colorSuccess }} />
                                {renderAnalysisStatus(item.id)}
                                {!canGenerateChapter(item) && (
                                  <Tag icon={<LockOutlined />} color="warning" title={getGenerateDisabledReason(item)}>
                                    Cần chương trước
                                  </Tag>
                                )}
                                <Space size={4}>
                                  {item.expansion_plan && (
                                    <InfoCircleOutlined
                                      title="Xem chi tiết mở rộng"
                                      style={{ color: token.colorPrimary, cursor: 'pointer', fontSize: 16 }}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        showExpansionPlanModal(item);
                                      }}
                                    />
                                  )}
                                  <FormOutlined
                                    title={item.expansion_plan ? "Chỉnh sửa thông tin kế hoạch" : "Tạo thông tin kế hoạch"}
                                    style={{ color: token.colorSuccess, cursor: 'pointer', fontSize: 16 }}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleOpenPlanEditor(item);
                                    }}
                                  />
                                </Space>
                              </Space>
                            </div>
                          }
                          description={
                            item.content ? (
                              <div style={{ marginTop: 8, color: token.colorTextSecondary, lineHeight: 1.6, fontSize: isMobile ? 12 : 14 }}>
                                {item.content.substring(0, isMobile ? 80 : 150)}
                                {item.content.length > (isMobile ? 80 : 150) && '...'}
                              </div>
                            ) : (
                              <span style={{ color: token.colorTextTertiary, fontSize: isMobile ? 12 : 14 }}>Chưa có nội dung</span>
                            )
                          }
                        />

                        {isMobile && (
                          <Space style={{ marginTop: 12, width: '100%', justifyContent: 'flex-end' }} wrap>
                            <Button
                              type="text"
                              icon={<ReadOutlined />}
                              onClick={() => handleOpenReader(item)}
                              size="small"
                              disabled={!item.content || item.content.trim() === ''}
                              title={!item.content || item.content.trim() === '' ? 'Chưa có nội dung' : 'Đọc'}
                            />
                            <Button
                              type="text"
                              icon={<EditOutlined />}
                              onClick={() => handleOpenEditor(item.id)}
                              size="small"
                              title="Chỉnh sửa"
                            />
                            {(() => {
                              const task = analysisTasksMap[item.id];
                              const isAnalyzing = task && (task.status === 'pending' || task.status === 'running');
                              const hasContent = item.content && item.content.trim() !== '';

                              return (
                                <Button
                                  type="text"
                                  icon={isAnalyzing ? <SyncOutlined spin /> : <FundOutlined />}
                                  onClick={() => handleShowAnalysis(item.id)}
                                  size="small"
                                  disabled={!hasContent || isAnalyzing}
                                  loading={isAnalyzing}
                                  title={
                                    !hasContent ? 'Hãy tạo nội dung chương trước' :
                                      isAnalyzing ? 'Đang phân tích' :
                                        'Phân tích'
                                  }
                                />
                              );
                            })()}
                            <Button
                              type="text"
                              icon={<SettingOutlined />}
                              onClick={() => handleOpenModal(item.id)}
                              size="small"
                              title="Sửa"
                            />
                            {/* 只在 one-to-many 模式下显示Xóa按钮 */}
                            {currentProject.outline_mode === 'one-to-many' && (
                              <Popconfirm
                                title="Xác nhận xóa?"
                                description="Không thể khôi phục sau khi xóa"
                                onConfirm={() => handleDeleteChapter(item.id)}
                                okText="Xóa"
                                cancelText="Hủy"
                                okButtonProps={{ danger: true }}
                              >
                                <Button
                                  type="text"
                                  danger
                                  icon={<DeleteOutlined />}
                                  size="small"
                                  title="Xóa chương"
                                />
                              </Popconfirm>
                            )}
                          </Space>
                        )}
                      </div>
                    </List.Item>
                  )}
                />
              </Collapse.Panel>
            ))}
          </Collapse>
        )}
      </div>

      {filteredSortedChapters.length > 0 && (
        <div style={{ paddingTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <Pagination
            current={chapterPage}
            pageSize={chapterPageSize}
            total={filteredSortedChapters.length}
            showSizeChanger
            pageSizeOptions={['10', '20', '50', '100']}
            onChange={(page, size) => {
              setChapterPage(page);
              if (size !== chapterPageSize) {
                setChapterPageSize(size);
                setChapterPage(1);
              }
            }}
            showTotal={(total) => `Tổng ${total} mục`}
            size={isMobile ? 'small' : 'default'}
          />
        </div>
      )}

      <Modal
        title={editingId ? 'Chỉnh sửa thông tin chương' : 'Thêm chương'}
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        centered
        width={isMobile ? 'calc(100vw - 32px)' : 520}
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(80vh - 110px)',
            overflowY: 'auto'
          }
        }}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            label="Tiêu đề chương"
            name="title"
            tooltip={
              currentProject.outline_mode === 'one-to-one'
                ? "Tiêu đề chương do dàn ý quản lý, hãy sửa ở trang dàn ý"
                 : "Ở chế độ một-nhiều có thể sửa tiêu đề chương"
            }
            rules={
              currentProject.outline_mode === 'one-to-many'
                ? [{ required: true, message: 'Vui lòng nhập tiêu đề chương' }]
                : undefined
            }
          >
            <Input
              placeholder="Nhập tiêu đề chương"
              disabled={currentProject.outline_mode === 'one-to-one'}
            />
          </Form.Item>

          <Form.Item
            label="Số thứ tự chương"
            name="chapter_number"
            tooltip="Không cho sửa số thứ tự chương; hãy xóa dàn ý tương ứng rồi tạo lại"
          >
            <Input type="number" placeholder="Số thứ tự sắp xếp chương" disabled />
          </Form.Item>

          <Form.Item label="Trạng thái" name="status">
            <Select placeholder="Chọn trạng thái">
              <Select.Option value="draft">Bản nháp</Select.Option>
              <Select.Option value="pending">Chờ xử lý</Select.Option>
              <Select.Option value="writing">Đang sáng tác</Select.Option>
              <Select.Option value="completed">Đã hoàn tất</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item>
            <Space style={{ float: 'right' }}>
              <Button onClick={() => setIsModalOpen(false)}>Hủy</Button>
              <Button type="primary" htmlType="submit">
                Cập nhật
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Chỉnh sửa nội dung chương"
        open={isEditorOpen}
        onCancel={() => {
          if (isGenerating) {
            message.warning('AI đang sáng tác, hãy đợi xong rồi đóng');
            return;
          }
          setIsEditorOpen(false);
        }}
        closable={!isGenerating}
        maskClosable={false}
        keyboard={!isGenerating}
        width={isMobile ? 'calc(100vw - 32px)' : '85%'}
        centered
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(100vh - 110px)',
            overflowY: 'auto',
            padding: isMobile ? '16px 12px' : '8px'
          }
        }}
        footer={null}
      >
        <Form form={editorForm} layout="vertical" onFinish={handleEditorSubmit}>
          {/* 章节标题和AI创作按钮 */}
          <Form.Item
            label="Tiêu đề chương"
            tooltip="(Chế độ 1-1 sửa ở dàn ý; chế độ 1-N dùng nút Sửa để chỉnh)"
            style={{ marginBottom: isMobile ? 16 : 12 }}
          >
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="title" noStyle>
                <Input disabled style={{ flex: 1 }} />
              </Form.Item>
              {editingId && (() => {
                const currentChapter = chapters.find(c => c.id === editingId);
                const canGenerate = currentChapter ? canGenerateChapter(currentChapter) : false;
                const disabledReason = currentChapter ? getGenerateDisabledReason(currentChapter) : '';

                return (
                  <>
                  <Button
                    type="primary"
                    icon={canGenerate ? <ThunderboltOutlined /> : <LockOutlined />}
                    onClick={() => currentChapter && showGenerateModal(currentChapter)}
                    loading={isContinuing}
                    disabled={!canGenerate}
                    danger={!canGenerate}
                    style={{ fontWeight: 'bold' }}
                    title={!canGenerate ? disabledReason : 'Sáng tác theo dàn ý và chương trước (stream)'}
                  >
                    {isMobile ? 'AI' : 'AI sáng tác'}
                  </Button>
                  <Button
                    icon={<RocketOutlined />}
                    onClick={handleBackgroundGenerate}
                    disabled={!canGenerate || isContinuing}
                    style={{ fontWeight: 'bold' }}
                    title={!canGenerate ? disabledReason : 'Tạo nền: đóng trình duyệt cũng không ảnh hưởng, xong sẽ tự lưu'}
                  >
                    {isMobile ? 'Nền' : 'Tạo nền'}
                  </Button>
                  </>
                );
              })()}
            </Space.Compact>
          </Form.Item>


          {/* 第一行：写作风格 + 叙事角度 */}
          <div style={{
            display: isMobile ? 'block' : 'flex',
            gap: isMobile ? 0 : 16,
            marginBottom: isMobile ? 0 : 12
          }}>
            <Form.Item
              label="Phong cách viết"
              tooltip="Chọn phong cách viết dùng khi AI sáng tác"
              required
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder="Vui lòng chọn phong cách viết"
                value={selectedStyleId}
                onChange={setSelectedStyleId}
                disabled={isGenerating}
                status={!selectedStyleId ? 'error' : undefined}
              >
                {writingStyles.map(style => (
                  <Select.Option key={style.id} value={style.id}>
                    {style.name}{style.is_default && ' (mặc định)'}
                  </Select.Option>
                ))}
              </Select>
              {!selectedStyleId && (
                <div style={{ color: token.colorError, fontSize: 12, marginTop: 4 }}>Vui lòng chọn phong cách viết</div>
              )}
            </Form.Item>

            <Form.Item
              label="Góc kể chuyện"
              tooltip="Ngôi thứ nhất (tôi) nhập vai mạnh; ngôi thứ ba (anh/cô ấy) khách quan hơn; toàn tri nhìn thấu mọi thứ"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder={`Mặc định dự án: ${getNarrativePerspectiveText(currentProject?.narrative_perspective)}`}
                value={temporaryNarrativePerspective}
                onChange={setTemporaryNarrativePerspective}
                allowClear
                disabled={isGenerating}
              >
                <Select.Option value="第一人称">Ngôi thứ nhất (tôi)</Select.Option>
                <Select.Option value="第三人称">Ngôi thứ ba (anh/cô ấy)</Select.Option>
                <Select.Option value="全知视角">Toàn tri</Select.Option>
              </Select>
              {temporaryNarrativePerspective && (
                <div style={{ color: token.colorSuccess, fontSize: 12, marginTop: 4 }}>
                  ✓ {getNarrativePerspectiveText(temporaryNarrativePerspective)}
                </div>
              )}
            </Form.Item>
          </div>

          {/* 第二行：目标字数 + AI模型 + Skill */}
          <div style={{
            display: isMobile ? 'block' : 'flex',
            gap: isMobile ? 0 : 16,
            marginBottom: isMobile ? 16 : 12
          }}>
            <Form.Item
              label="Áp dụng Skill"
              tooltip="Chọn một Skill workflow để hướng dẫn AI sáng tác; không chọn thì dùng quy trình chuẩn"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder="Không dùng Skill (sáng tác chuẩn)"
                value={selectedSkillKey}
                onChange={setSelectedSkillKey}
                allowClear
                disabled={isGenerating}
                showSearch
                optionFilterProp="label"
              >
                {availableSkills.map(skill => (
                  <Select.Option key={skill.template_key} value={skill.template_key} label={skill.template_name}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span>{skill.template_name}</span>
                      <Tag style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px' }}>{skill.category}</Tag>
                    </div>
                  </Select.Option>
                ))}
              </Select>
              {selectedSkillKey && (() => {
                const skill = availableSkills.find(s => s.template_key === selectedSkillKey);
                return skill ? (
                  <div style={{ color: token.colorSuccess, fontSize: 12, marginTop: 4 }}>
                    ✓ {skill.description}
                  </div>
                ) : null;
              })()}
            </Form.Item>

            <Form.Item
              label="Số chữ mục tiêu"
              tooltip="Số chữ mục tiêu khi AI tạo chương; thực tế có thể lệch nhẹ (sau khi sửa sẽ tự nhớ)"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <InputNumber
                min={500}
                max={10000}
                step={100}
                value={targetWordCount}
                onChange={(value) => {
                  const newValue = value || DEFAULT_WORD_COUNT;
                  setTargetWordCount(newValue);
                  setCachedWordCount(newValue);
                }}
                disabled={isGenerating}
                style={{ width: '100%' }}
                formatter={(value) => `${value} chữ`}
                parser={(value) => parseInt(value?.replace(' chữ', '') || '0', 10) as unknown as 500}
              />
            </Form.Item>

            <Form.Item
              label="Mô hình AI"
              tooltip="Chọn mô hình AI để tạo nội dung chương; không chọn thì dùng mặc định"
              style={{ flex: 1, marginBottom: isMobile ? 16 : 0 }}
            >
              <Select
                placeholder={selectedModel ? `Mặc định: ${availableModels.find(m => m.value === selectedModel)?.label || selectedModel}` : "Dùng mô hình mặc định"}
                value={selectedModel}
                onChange={setSelectedModel}
                allowClear
                disabled={isGenerating}
                showSearch
                optionFilterProp="label"
              >
                {availableModels.map(model => (
                  <Select.Option key={model.value} value={model.value} label={model.label}>
                    {model.label}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
          </div>

          <Form.Item label="Nội dung chương" name="content">
            <TextArea
              ref={contentTextAreaRef}
              rows={isMobile ? 12 : 20}
              placeholder="Bắt đầu viết..."
              style={{ fontFamily: 'monospace', fontSize: isMobile ? 12 : 14 }}
              disabled={isGenerating}
            />
          </Form.Item>

          {/* 局部重写浮动工具栏 */}
          <div data-partial-regenerate-toolbar>
            <PartialRegenerateToolbar
              visible={partialRegenerateToolbarVisible && !isGenerating}
              position={partialRegenerateToolbarPosition}
              selectedText={selectedTextForRegenerate}
              onRegenerate={handleOpenPartialRegenerate}
            />
          </div>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end', flexDirection: isMobile ? 'column' : 'row', alignItems: isMobile ? 'stretch' : 'center' }}>
              <Space style={{ width: isMobile ? '100%' : 'auto' }}>
                <Button
                  onClick={() => {
                    if (isGenerating) {
                      message.warning('AI đang sáng tác, hãy đợi xong rồi đóng');
                      return;
                    }
                    setIsEditorOpen(false);
                  }}
                  block={isMobile}
                  disabled={isGenerating}
                >
                  Hủy
                </Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  block={isMobile}
                  disabled={isGenerating}
                >
                  Lưu chương
                </Button>
              </Space>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {analysisChapterId && (
        <ChapterAnalysis
          chapterId={analysisChapterId}
          visible={analysisVisible}
          onClose={() => {
            setAnalysisVisible(false);

            // 刷新章节列表以显示最新内容
            refreshChapters();

            // 刷新项目信息以Cập nhật字数统计
            if (currentProject) {
              projectApi.getProject(currentProject.id)
                .then(updatedProject => {
                  setCurrentProject(updatedProject);
                })
                .catch(error => {
                  console.error('Làm mới thông tin dự án thất bại:', error);
                });
            }

            // 延迟500ms后批量刷新分析状态，避免单章接口高频调用
            setTimeout(() => {
              loadAnalysisTasks();
            }, 500);

            setAnalysisChapterId(null);
          }}
        />
      )}

      {/* 批量生成对话框 */}
      <Modal
        title={
          <Space>
            <RocketOutlined style={{ color: token.colorInfo }} />
            <span>Tạo hàng loạt nội dung chương</span>
          </Space>
        }
        open={batchGenerateVisible}
        onCancel={() => {
          if (batchGenerating) {
            modal.confirm({
              title: 'Xác nhận hủy',
              content: 'Đang tạo hàng loạt, xác nhận hủy?',
              okText: 'Xác nhận hủy',
              cancelText: 'Tiếp tục tạo',
              centered: true,
              onOk: () => {
                handleCancelBatchGenerate();
                setBatchGenerateVisible(false);
              },
            });
          } else {
            setBatchGenerateVisible(false);
          }
        }}
        footer={!batchGenerating ? (
          <Space style={{ width: '100%', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <Button onClick={() => setBatchGenerateVisible(false)}>
              Hủy
            </Button>
            <Button type="primary" icon={<RocketOutlined />} onClick={() => batchForm.submit()}>
              Bắt đầu tạo hàng loạt
            </Button>
          </Space>
        ) : null}
        width={isMobile ? 'calc(100vw - 32px)' : 700}
        centered
        closable={!batchGenerating}
        maskClosable={!batchGenerating}
        style={isMobile ? {
          maxWidth: 'calc(100vw - 32px)',
          margin: '0 auto',
          padding: '0 16px'
        } : undefined}
        styles={{
          body: {
            maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(100vh - 260px)',
            overflowY: 'auto',
            overflowX: 'hidden'
          }
        }}
      >
        {!batchGenerating ? (
          <Form
            form={batchForm}
            layout="vertical"
            onFinish={handleBatchGenerate}
            initialValues={{
              startChapterNumber: sortedChapters.find(ch => !ch.content || ch.content.trim() === '')?.chapter_number || 1,
              count: 5,
              enableAnalysis: true,
              styleId: selectedStyleId,
              targetWordCount: getCachedWordCount(),
              model: selectedModel,
            }}
          >
            <Alert
              message="Hướng dẫn tạo hàng loạt: tạo đúng thứ tự | thống nhất phong cách/số chữ | lỗi bất kỳ sẽ dừng"
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            {/* 第一行：起始章节 + 生成数量 */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="Chương bắt đầu"
                name="startChapterNumber"
                rules={[{ required: true, message: 'Vui lòng chọn' }]}
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select placeholder="Chọn chương bắt đầu">
                  {sortedChapters
                    .filter(ch => !ch.content || ch.content.trim() === '')
                    .filter(ch => canGenerateChapter(ch))
                    .map(ch => (
                      <Select.Option key={ch.id} value={ch.chapter_number}>
                        Chương {ch.chapter_number}: {ch.title}
                      </Select.Option>
                    ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="Số lượng tạo"
                name="count"
                rules={[{ required: true, message: 'Vui lòng chọn' }]}
                style={{ marginBottom: 12 }}
              >
                <Radio.Group buttonStyle="solid" size={isMobile ? 'small' : 'middle'}>
                  <Radio.Button value={5}>5 chương</Radio.Button>
                  <Radio.Button value={10}>10 chương</Radio.Button>
                  <Radio.Button value={15}>15 chương</Radio.Button>
                  <Radio.Button value={20}>20 chương</Radio.Button>
                </Radio.Group>
              </Form.Item>
            </div>

            {/* 第二行：写作风格 + 目标字数 */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="Phong cách viết"
                name="styleId"
                rules={[{ required: true, message: 'Vui lòng chọn' }]}
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select placeholder="Vui lòng chọn phong cách viết" showSearch optionFilterProp="children">
                  {writingStyles.map(style => (
                    <Select.Option key={style.id} value={style.id}>
                      {style.name}{style.is_default && ' (mặc định)'}
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="Số chữ mục tiêu"
                name="targetWordCount"
                rules={[{ required: true, message: 'Vui lòng đặt' }]}
                tooltip="Sau khi sửa sẽ tự nhớ"
                style={{ flex: 1, marginBottom: 12 }}
              >
                <InputNumber
                  min={500}
                  max={10000}
                  step={100}
                  style={{ width: '100%' }}
                  formatter={(value) => `${value} chữ`}
                  parser={(value) => parseInt(value?.replace(' chữ', '') || '0', 10) as unknown as 500}
                  onChange={(value) => {
                    if (value) {
                      setCachedWordCount(value);
                    }
                  }}
                />
              </Form.Item>
            </div>

            {/* 第三行：AI模型 + Skill */}
            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 0 : 16 }}>
              <Form.Item
                label="Mô hình AI"
                tooltip="Không chọn thì dùng mô hình mặc định"
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select
                  placeholder={batchSelectedModel ? `Mặc định: ${availableModels.find(m => m.value === batchSelectedModel)?.label || batchSelectedModel}` : "Dùng mô hình mặc định"}
                  value={batchSelectedModel}
                  onChange={setBatchSelectedModel}
                  allowClear
                  showSearch
                  optionFilterProp="label"
                >
                  {availableModels.map(model => (
                    <Select.Option key={model.value} value={model.value} label={model.label}>
                      {model.label}
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                label="Áp dụng Skill"
                tooltip="Chọn một Skill workflow để hướng dẫn sáng tác hàng loạt; không chọn thì dùng quy trình chuẩn"
                style={{ flex: 1, marginBottom: 12 }}
              >
                <Select
                  placeholder="Không dùng Skill (sáng tác chuẩn)"
                  value={batchSelectedSkillKey}
                  onChange={setBatchSelectedSkillKey}
                  allowClear
                  showSearch
                  optionFilterProp="label"
                >
                  {availableSkills.map(skill => (
                    <Select.Option key={skill.template_key} value={skill.template_key} label={skill.template_name}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span>{skill.template_name}</span>
                        <Tag style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px' }}>{skill.category}</Tag>
                      </div>
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </div>

            {/* 同步分析（固定开启） */}
            <Form.Item
              label="Phân tích đồng bộ"
              name="enableAnalysis"
              tooltip="Bắt buộc bật để đảm bảo cốt truyện mạch lạc"
              style={{ marginBottom: 12 }}
            >
              <Radio.Group disabled>
                <Radio value={true}>
                  <span style={{ fontSize: 12, color: token.colorSuccess }}>✓ Tự cập nhật trạng thái nhân vật</span>
                </Radio>
              </Radio.Group>
            </Form.Item>
          </Form>
        ) : (
          <div>
            <Alert
              message="Lưu ý nhẹ"
              description={
                <ul style={{ margin: '8px 0 0 0', paddingLeft: 20 }}>
                  <li>Tạo hàng loạt cần thời gian, có thể chuyển sang trang khác</li>
                  <li>Đóng rồi mở lại trang sẽ tự khôi phục tiến độ nhiệm vụ</li>
                  <li>Có thể nhấn "Hủy nhiệm vụ" bất cứ lúc nào để dừng tạo</li>
                  {batchProgress?.estimated_time_minutes && batchProgress.completed === 0 && (
                    <li>⏱️ Thời gian dự kiến: khoảng {batchProgress.estimated_time_minutes} phút</li>
                  )}
                </ul>
              }
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />

            <div style={{ textAlign: 'center' }}>
              <Button
                danger
                icon={<StopOutlined />}
                onClick={() => {
                  modal.confirm({
                    title: 'Xác nhận hủy',
                    content: 'Xác nhận hủy tạo hàng loạt? Các chương đã tạo sẽ được giữ.',
                    okText: 'Xác nhận hủy',
                    cancelText: 'Tiếp tục tạo',
                    okButtonProps: { danger: true },
                    onOk: handleCancelBatchGenerate,
                  });
                }}
              >
                Hủy nhiệm vụ
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 单章节生成进度显示 */}
      <SSELoadingOverlay
        loading={isGenerating}
        progress={singleChapterProgress}
        message={singleChapterProgressMessage}
      />

      {/* 章节Đọc器 */}
      {readingChapter && (
        <ChapterReader
          visible={readerVisible}
          chapter={readingChapter}
          onClose={() => {
            setReaderVisible(false);
            setReadingChapter(null);
          }}
          onChapterChange={handleReaderChapterChange}
        />
      )}

      {/* 局部重写弹窗 */}
      {editingId && (
        <PartialRegenerateModal
          visible={partialRegenerateModalVisible}
          chapterId={editingId}
          selectedText={selectedTextForRegenerate}
          startPosition={selectionStartPosition}
          endPosition={selectionEndPosition}
          styleId={selectedStyleId}
          onClose={() => setPartialRegenerateModalVisible(false)}
          onApply={handleApplyPartialRegenerate}
        />
      )}

      {/* 规划Chỉnh sửa器 */}
      {editingPlanChapter && currentProject && (() => {
        let parsedPlanData = null;
        try {
          if (editingPlanChapter.expansion_plan) {
            parsedPlanData = JSON.parse(editingPlanChapter.expansion_plan);
          }
        } catch (error) {
          console.error('Phân tích dữ liệu kế hoạch thất bại:', error);
        }

        return (
          <ExpansionPlanEditor
            visible={planEditorVisible}
            planData={parsedPlanData}
            chapterSummary={editingPlanChapter.summary || null}
            projectId={currentProject.id}
            onSave={handleSavePlan}
            onCancel={() => {
              setPlanEditorVisible(false);
              setEditingPlanChapter(null);
            }}
          />
        );
      })()}
    </div>
  );
}
