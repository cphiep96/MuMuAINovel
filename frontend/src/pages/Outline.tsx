import { useState, useEffect, useMemo } from 'react';
import { Button, List, Modal, Form, Input, message, Empty, Space, Popconfirm, Card, Select, Radio, Tag, InputNumber, Tabs, Pagination, theme, Upload, Alert, Divider } from 'antd';
import { EditOutlined, DeleteOutlined, ThunderboltOutlined, BranchesOutlined, AppstoreAddOutlined, CheckCircleOutlined, ExclamationCircleOutlined, PlusOutlined, FileTextOutlined, UploadOutlined, DownloadOutlined } from '@ant-design/icons';
import { useStore } from '../store';
import { eventBus, EventNames } from '../store/eventBus';
import { getProjectTasks, type TaskStatus } from '../services/backgroundTaskService';
import { useOutlineSync } from '../store/hooks';
import { generateOutlineBackground } from '../services/backgroundTaskService';
import { outlineApi, chapterApi, projectApi, characterApi } from '../services/api';
import type { ApiError, Character, OutlineImportMode, OutlineImportPreview } from '../types';

// 大纲生成请求数据类型
interface OutlineGenerateRequestData {
  project_id: string;
  genre: string;
  theme: string;
  chapter_count: number;
  narrative_perspective: string;
  target_words: number;
  requirements?: string;
  mode: 'auto' | 'new' | 'continue';
  story_direction?: string;
  plot_stage: 'development' | 'climax' | 'ending';
  model?: string;
  provider?: string;
}

// 角色/组织条目类型（新格式）
interface CharacterEntry {
  name: string;
  type: 'character' | 'organization';
}

/**
 * 解析 characters 字段，兼容新旧格式
 * 旧格式: string[] -> 全部当作 character
 * 新格式: {name: string, type: "character"|"organization"}[]
 */
function parseCharacterEntries(characters: unknown): CharacterEntry[] {
  if (!Array.isArray(characters) || characters.length === 0) return [];
  
  return characters.map((entry) => {
    if (typeof entry === 'string') {
      // 旧格式：纯字符串，默认为 character
      return { name: entry, type: 'character' as const };
    }
    if (typeof entry === 'object' && entry !== null && 'name' in entry) {
      // 新格式：带类型标识的对象
      return {
        name: (entry as { name: string }).name,
        type: ((entry as { type?: string }).type === 'organization' ? 'organization' : 'character') as 'character' | 'organization'
      };
    }
    return null;
  }).filter((e): e is CharacterEntry => e !== null);
}

/** 从 entries 中提取角色名称列表 */
function getCharacterNames(entries: CharacterEntry[]): string[] {
  return entries.filter(e => e.type === 'character').map(e => e.name);
}

/** 从 entries 中提取组织名称列表 */
function getOrganizationNames(entries: CharacterEntry[]): string[] {
  return entries.filter(e => e.type === 'organization').map(e => e.name);
}

interface OutlineStructureData {
  key_events?: string[];
  key_points?: string[];
  characters_involved?: string[];
  characters?: unknown[];
  scenes?: string[] | Array<{
    location: string;
    characters: string[];
    purpose: string;
  }>;
  emotion?: string;
  goal?: string;
  title?: string;
  summary?: string;
  content?: string;
}

function parseOutlineStructure(structure?: string): OutlineStructureData {
  if (!structure) return {};
  try {
    return JSON.parse(structure) as OutlineStructureData;
  } catch (e) {
    console.error('Phân tích structure thất bại:', e);
    return {};
  }
}

function getOutlinePreview(content: string, maxLength = 120): { text: string; truncated: boolean } {
  const normalized = (content || '').replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) {
    return { text: normalized, truncated: false };
  }
  return {
    text: `${normalized.slice(0, maxLength).trimEnd()}...`,
    truncated: true
  };
}

const { TextArea } = Input;

export default function Outline() {
  const { currentProject, outlines, setCurrentProject } = useStore();
  const [isGenerating, setIsGenerating] = useState(false);
  const [editForm] = Form.useForm();
  const [generateForm] = Form.useForm();
  const [expansionForm] = Form.useForm();
  const [modalApi, contextHolder] = Modal.useModal();
  const [batchExpansionForm] = Form.useForm();
  const [manualCreateForm] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [isExpanding, setIsExpanding] = useState(false);
  const [projectCharacters, setProjectCharacters] = useState<Array<{ label: string; value: string }>>([]);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importMode, setImportMode] = useState<OutlineImportMode>('append');
  const [importPreview, setImportPreview] = useState<OutlineImportPreview | null>(null);
  const [isPreviewingImport, setIsPreviewingImport] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const { token } = theme.useToken();
  const alphaColor = (color: string, alpha: number) =>
    `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(0)}%, transparent)`;

  // ✅ 新增：记录大纲卡片内容的Mở rộng/折叠状态（默认折叠）
  const [outlineContentExpandStatus, setOutlineContentExpandStatus] = useState<Record<string, boolean>>({});

  // ✅ 新增：记录场景区域的Mở rộng/折叠状态
  const [scenesExpandStatus, setScenesExpandStatus] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 大纲查询与分页状态
  const [outlineSearchKeyword, setOutlineSearchKeyword] = useState('');
  const [outlinePage, setOutlinePage] = useState(1);
  const [outlinePageSize, setOutlinePageSize] = useState(20);

  // 使用同步 hooks
  const {
    refreshOutlines,
    updateOutline,
    deleteOutline
  } = useOutlineSync();

  // 初始加载大纲列表和角色列表
  useEffect(() => {
    if (currentProject?.id) {
      refreshOutlines();
      // 加载项目角色列表
      loadProjectCharacters();
      // 检查是否有活跃的大纲生成任务，恢复按钮禁用状态
      checkActiveOutlineTasks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject?.id]); // 只依赖 ID，不依赖函数

  // 检查是否有活跃的大纲生成任务（页面切换后恢复状态）
  const checkActiveOutlineTasks = async () => {
    if (!currentProject?.id) return;
    try {
      const result = await getProjectTasks(currentProject.id, 'outline_new', 5);
      const result2 = await getProjectTasks(currentProject.id, 'outline_continue', 5);
      const allTasks = [...(result.items || []), ...(result2.items || [])];
      const hasActive = allTasks.some((t: TaskStatus) => t.status === 'running' || t.status === 'pending');
      setIsGenerating(hasActive);
    } catch (error) {
      console.error('Kiểm tra tác vụ dàn ý đang chạy thất bại:', error);
    }
  };

  // 加载项目角色列表
  const loadProjectCharacters = async () => {
    if (!currentProject?.id) return;
    try {
      const characters = await characterApi.getCharacters(currentProject.id);
      setProjectCharacters(
        characters.map((char: Character) => ({
          label: char.name,
          value: char.name
        }))
      );
    } catch (error) {
      console.error('Tải danh sách nhân vật thất bại:', error);
    }
  };

  // 从后端返回字段直接构建Mở rộng状态，避免前端 N+1 请求
  const outlineExpandStatus = useMemo(() => {
    const statusMap: Record<string, boolean> = {};
    outlines.forEach((outline) => {
      statusMap[outline.id] = Boolean(outline.has_chapters);
    });
    return statusMap;
  }, [outlines]);

  // 统一预解析 structure，避免 render 阶段重复 JSON.parse
  const outlineStructureMap = useMemo(() => {
    const parsedMap: Record<string, OutlineStructureData> = {};
    outlines.forEach((outline) => {
      parsedMap[outline.id] = parseOutlineStructure(outline.structure);
    });
    return parsedMap;
  }, [outlines]);

  // 当角色确认数据变化时，初始化选中状态（默认全选）
  // 当组织确认数据变化时，初始化选中状态（默认全选）
  // 移除事件监听，避免无限循环
  // Hook 内部已经更新了 store，不需要再次刷新

  // 确保大纲按 order_index 排序
  const sortedOutlines = [...outlines].sort((a, b) => a.order_index - b.order_index);

  // 前端查询过滤
  const filteredOutlines = useMemo(() => {
    const keyword = outlineSearchKeyword.trim().toLowerCase();
    if (!keyword) return sortedOutlines;

    return sortedOutlines.filter((outline) => {
      return (
        String(outline.order_index).includes(keyword) ||
        outline.title.toLowerCase().includes(keyword) ||
        outline.content.toLowerCase().includes(keyword)
      );
    });
  }, [sortedOutlines, outlineSearchKeyword]);

  // 当前分页数据
  const pagedOutlines = useMemo(() => {
    const start = (outlinePage - 1) * outlinePageSize;
    return filteredOutlines.slice(start, start + outlinePageSize);
  }, [filteredOutlines, outlinePage, outlinePageSize]);

  // 搜索词或页大小变化时，回到第一页
  useEffect(() => {
    setOutlinePage(1);
  }, [outlineSearchKeyword, outlinePageSize]);

  // 数据变化导致页码越界时自动纠正
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredOutlines.length / outlinePageSize));
    if (outlinePage > maxPage) {
      setOutlinePage(maxPage);
    }
  }, [filteredOutlines.length, outlinePage, outlinePageSize]);

  if (!currentProject) return null;

  const handleOpenEditModal = (id: string) => {
    const outline = outlines.find(o => o.id === id);
    if (outline) {
      const structureData = outlineStructureMap[outline.id] || {};
      
      // 解析角色/组织条目（兼容新旧格式）
      const editEntries = parseCharacterEntries(structureData.characters);
      const editCharNames = getCharacterNames(editEntries);
      const editOrgNames = getOrganizationNames(editEntries);
      
      // 处理场景数据 - 可能是字符串数组或对象数组
      let scenesText = '';
      if (structureData.scenes) {
        if (typeof structureData.scenes[0] === 'string') {
          // 字符串数组格式
          scenesText = (structureData.scenes as string[]).join('\n');
        } else {
          // 对象数组格式
          scenesText = (structureData.scenes as Array<{location: string; characters: string[]; purpose: string}>)
            .map(s => `${s.location}|${(s.characters || []).join(', ')}|${s.purpose}`)
            .join('\n');
        }
      }
      
      // 处理情节要点数据
      const keyPointsText = structureData.key_points ? structureData.key_points.join('\n') : '';
      
      // 设置表单初始值
      editForm.setFieldsValue({
        title: outline.title,
        content: outline.content,
        characters: editCharNames,
        organizations: editOrgNames,
        scenes: scenesText,
        key_points: keyPointsText,
        emotion: structureData.emotion || '',
        goal: structureData.goal || ''
      });
      
      modalApi.confirm({
        title: 'Chỉnh sửa dàn ý',
        width: 800,
        centered: true,
        styles: {
          body: {
            maxHeight: 'calc(100vh - 200px)',
            overflowY: 'auto'
          }
        },
        content: (
          <Form
            form={editForm}
            layout="vertical"
            style={{ marginTop: 12 }}
          >
            <Form.Item
              label="Tiêu đề"
              name="title"
              rules={[{ required: true, message: 'Vui lòng nhập tiêu đề' }]}
              style={{ marginBottom: 12 }}
            >
              <Input placeholder="Nhập tiêu đề dàn ý" />
            </Form.Item>

            <Form.Item
              label="Nội dung"
              name="content"
              rules={[{ required: true, message: 'Vui lòng nhập nội dung' }]}
              style={{ marginBottom: 12 }}
            >
              <TextArea rows={4} placeholder="Nhập nội dung dàn ý..." />
            </Form.Item>
            
            <Form.Item
              label="Nhân vật liên quan"
              name="characters"
              tooltip="Chọn từ nhân vật dự án, cũng có thể nhập tên nhân vật mới"
              style={{ marginBottom: 12 }}
            >
              <Select
                mode="tags"
                style={{ width: '100%' }}
                placeholder="Chọn hoặc nhập tên nhân vật"
                options={projectCharacters}
                tokenSeparators={[',', '，']}
                maxTagCount="responsive"
              />
            </Form.Item>
            
            <Form.Item
              label="Tổ chức liên quan"
              name="organizations"
              tooltip="Chọn từ tổ chức dự án, cũng có thể nhập tên tổ chức mới"
              style={{ marginBottom: 12 }}
            >
              <Select
                mode="tags"
                style={{ width: '100%' }}
                placeholder="Chọn hoặc nhập tên tổ chức/thế lực"
                tokenSeparators={[',', '，']}
                maxTagCount="responsive"
              />
            </Form.Item>
            
            <Form.Item
              label="Thông tin cảnh"
              name="scenes"
              tooltip="Hỗ trợ 2 định dạng: mô tả đơn giản (mỗi dòng một cảnh) hoặc chi tiết (địa điểm|nhân vật|mục đích)"
              style={{ marginBottom: 12 }}
            >
              <TextArea
                rows={3}
                placeholder="Mỗi dòng một cảnh&#10;Định dạng chi tiết: địa điểm|nhân vật1, nhân vật2|mục đích"
              />
            </Form.Item>
            
            <Form.Item
              label="Điểm tình tiết chính"
              name="key_points"
              tooltip="Mỗi dòng một điểm tình tiết"
              style={{ marginBottom: 12 }}
            >
              <TextArea
                rows={2}
                placeholder="Mỗi dòng một điểm tình tiết"
              />
            </Form.Item>
            
            <Form.Item
              label="Sắc thái cảm xúc"
              name="emotion"
              tooltip="Mô tả không khí cảm xúc của chương này"
              style={{ marginBottom: 12 }}
            >
              <Input placeholder="Ví dụ: lạnh lẽo và bồn chồn cùng tồn tại" />
            </Form.Item>
            
            <Form.Item
              label="Mục tiêu kể chuyện"
              name="goal"
              tooltip="Mục đích kể chuyện cần đạt của chương này"
              style={{ marginBottom: 0 }}
            >
              <Input placeholder="Ví dụ: xây tương phản bối cảnh và hoàn tất lần gặp đầu của nhân vật chính" />
            </Form.Item>
          </Form>
        ),
        okText: 'Cập nhật',
        cancelText: 'Hủy',
        onOk: async () => {
          const values = await editForm.validateFields();
          try {
            // 解析并重构structure数据（使用预解析缓存，避免重复 JSON.parse）
            const originalStructure = outlineStructureMap[outline.id] || {};
            
            // 处理角色和组织数据 - 合并为带类型标识的新格式
            const charNames = Array.isArray(values.characters)
              ? values.characters.filter((c: string) => c && c.trim())
              : [];
            const orgNames = Array.isArray(values.organizations)
              ? values.organizations.filter((c: string) => c && c.trim())
              : [];
            const characters: CharacterEntry[] = [
              ...charNames.map((name: string) => ({ name: name.trim(), type: 'character' as const })),
              ...orgNames.map((name: string) => ({ name: name.trim(), type: 'organization' as const }))
            ];
            
            // 处理场景数据 - 检测原始格式
            let scenes: string[] | Array<{location: string; characters: string[]; purpose: string}> | undefined;
            if (values.scenes) {
              const lines = values.scenes.split('\n')
                .map((line: string) => line.trim())
                .filter((line: string) => line);
              
              // 检查是否包含管道符，判断格式
              const hasStructuredFormat = lines.some((line: string) => line.includes('|'));
              
              if (hasStructuredFormat) {
                // 尝试解析为对象数组格式
                scenes = lines
                  .map((line: string) => {
                    const parts = line.split('|');
                    if (parts.length >= 3) {
                      return {
                        location: parts[0].trim(),
                        characters: parts[1].split(/[、,]/).map(c => c.trim()).filter(c => c),
                        purpose: parts[2].trim()
                      };
                    }
                    return null;
                  })
                  .filter((s: { location: string; characters: string[]; purpose: string } | null): s is { location: string; characters: string[]; purpose: string } => s !== null);
              } else {
                // 保持字符串数组格式
                scenes = lines;
              }
            }
            
            // 处理情节要点数据
            const keyPoints = values.key_points
              ? values.key_points.split('\n')
                  .map((line: string) => line.trim())
                  .filter((line: string) => line)
              : undefined;
            
            // 合并structure数据，只包含AI实际生成的字段
            const newStructure = {
              ...originalStructure,
              title: values.title,
              summary: values.content,
              characters: characters.length > 0 ? characters : undefined,
              scenes: scenes && scenes.length > 0 ? scenes : undefined,
              key_points: keyPoints && keyPoints.length > 0 ? keyPoints : undefined,
              emotion: values.emotion || undefined,
              goal: values.goal || undefined
            };
            
            // 更新大纲
            await updateOutline(id, {
              title: values.title,
              content: values.content,
              structure: JSON.stringify(newStructure, null, 2)
            });
            
            message.success('Cập nhật dàn ý thành công');
          } catch (error) {
            console.error('Cập nhật thất bại:', error);
            message.error('Cập nhật thất bại');
          }
        },
      });
    }
  };

  const handleDeleteOutline = async (id: string) => {
    try {
      await deleteOutline(id);
      message.success('Xóa thành công');
      // Xóa后刷新大纲列表和项目信息，更新字数显示
      await refreshOutlines();
      if (currentProject?.id) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }
    } catch {
      message.error('Xóa thất bại');
    }
  };

  interface GenerateFormValues {
    theme?: string;
    chapter_count?: number;
    narrative_perspective?: string;
    requirements?: string;
    provider?: string;
    model?: string;
    mode?: 'auto' | 'new' | 'continue';
    story_direction?: string;
    plot_stage?: 'development' | 'climax' | 'ending';
    keep_existing?: boolean;
  }

  const handleGenerate = async (values: GenerateFormValues) => {
    try {
      setIsGenerating(true);

      // 添加详细的调试日志
      console.log('=== Thông tin gỡ lỗi tạo dàn ý ===');
      console.log('1. Dữ liệu gốc form values:', values);
      console.log('2. values.model:', values.model);
      console.log('3. values.provider:', values.provider);

      // Đóng生成表单Modal
      Modal.destroyAll();

      // 准备请求数据
      const requestData: OutlineGenerateRequestData = {
        project_id: currentProject.id,
        genre: currentProject.genre || 'Chung',
        theme: values.theme || currentProject.theme || '',
        chapter_count: values.chapter_count || 5,
        narrative_perspective: values.narrative_perspective || currentProject.narrative_perspective || '第三人称',
        target_words: currentProject.target_words || 100000,
        requirements: values.requirements,
        mode: values.mode || 'auto',
        story_direction: values.story_direction,
        plot_stage: values.plot_stage || 'development'
      };

      // 只有在用户选择了模型时才添加model参数
      if (values.model) {
        requestData.model = values.model;
        console.log('4. Thêm model vào request:', values.model);
      } else {
        console.log('4. values.model rỗng, không thêm vào request');
      }

      // 添加provider参数（如果有）
      if (values.provider) {
        requestData.provider = values.provider;
        console.log('5. Thêm provider vào request:', values.provider);
      }

      console.log('6. Dữ liệu request cuối cùng:', JSON.stringify(requestData, null, 2));
      console.log('=========================');

      // 使用后台任务生成（不怕断连，Đóng浏览器也继续运行）
      // 不再强制显示进度弹窗，任务进度在右下角悬浮任务框中显示
      await generateOutlineBackground(
        requestData,
        () => {
          // 进度更新由悬浮任务框处理，无需额外操作
        },
        (result) => {
          message.success(result.task_result?.message as string || 'Tạo dàn ý hoàn tất!');
          setIsGenerating(false);
          refreshOutlines();
        },
        (error) => {
          message.error(`Tạo thất bại: ${error}`);
          setIsGenerating(false);
        }
      );

      message.info('Đã gửi nhiệm vụ tạo dàn ý, xem tiến độ ở panel góc phải dưới');
      // 通知悬浮任务框刷新
      eventBus.emit('background-task-created');

    } catch (error) {
      console.error('Tạo bằng AI thất bại:', error);
      message.error('AI tạo thất bại');
      setIsGenerating(false);
    }
  };

  const showGenerateModal = async () => {
    const hasOutlines = outlines.length > 0;
    const initialMode = hasOutlines ? 'continue' : 'new';

    // 直接加载可用模型列表
    const settingsResponse = await fetch('/api/settings');
    const settings = await settingsResponse.json();
    const { api_key, api_base_url, api_provider } = settings;

    let loadedModels: Array<{ value: string, label: string }> = [];
    let defaultModel: string | undefined = undefined;

    if (api_base_url) {
      try {
        const modelsResponse = await fetch(
          `/api/settings/models?api_key=${encodeURIComponent(api_key || '')}&api_base_url=${encodeURIComponent(api_base_url)}&provider=${api_provider}`
        );
        if (modelsResponse.ok) {
          const data = await modelsResponse.json();
          if (data.models && data.models.length > 0) {
            loadedModels = data.models;
            defaultModel = settings.llm_model;
          }
        }
      } catch {
        console.log('Lấy danh sách model thất bại, sẽ dùng model mặc định');
      }
    }

    modalApi.confirm({
      title: hasOutlines ? (
        <Space>
          <span>AI tạo/viết tiếp dàn ý</span>
          <Tag color="blue">Hiện đã có {outlines.length} tập</Tag>
        </Space>
      ) : 'AI tạo dàn ý',
      width: 700,
      centered: true,
      content: (
        <Form
          form={generateForm}
          layout="vertical"
          style={{ marginTop: 16 }}
          initialValues={{
            mode: initialMode,
            chapter_count: 5,
            narrative_perspective: currentProject.narrative_perspective || '第三人称',
            plot_stage: 'development',
            keep_existing: true,
            theme: currentProject.theme || '',
            model: defaultModel,
          }}
        >
          {hasOutlines && (
            <Form.Item
              label="Chế độ tạo"
              name="mode"
              tooltip="Tự chọn theo có dàn ý hay không; tạo mới: xóa dàn ý cũ rồi tạo lại; viết tiếp: dựa dàn ý sẵn có"
            >
              <Radio.Group buttonStyle="solid">
                <Radio.Button value="auto">Tự phán đoán</Radio.Button>
                <Radio.Button value="new">Tạo mới hoàn toàn</Radio.Button>
                <Radio.Button value="continue">Chế độ viết tiếp</Radio.Button>
              </Radio.Group>
            </Form.Item>
          )}

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) => prevValues.mode !== currentValues.mode}
          >
            {({ getFieldValue }) => {
              const mode = getFieldValue('mode');
              const isContinue = mode === 'continue' || (mode === 'auto' && hasOutlines);

              // Chế độ viết tiếp不显示主题输入，使用项目原有主题
              if (isContinue) {
                return null;
              }

              // Tạo mới hoàn toàn模式需要输入主题
              return (
                <Form.Item
                  label="Chủ đề câu chuyện"
                  name="theme"
                  rules={[{ required: true, message: 'Vui lòng nhập chủ đề câu chuyện' }]}
                >
                  <TextArea rows={3} placeholder="Mô tả chủ đề, thiết lập cốt lõi và tình tiết chính..." />
                </Form.Item>
              );
            }}
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) => prevValues.mode !== currentValues.mode}
          >
            {({ getFieldValue }) => {
              const mode = getFieldValue('mode');
              const isContinue = mode === 'continue' || (mode === 'auto' && hasOutlines);

              return (
                <>
                  {isContinue && (
                    <>
                      <Form.Item
                        label="Hướng phát triển câu chuyện"
                        name="story_direction"
                        tooltip="Cho AI biết bạn muốn câu chuyện phát triển thế nào tiếp theo"
                      >
                        <TextArea
                          rows={3}
                          placeholder="Ví dụ: nhân vật chính gặp thử thách mới, giới thiệu nhân vật mới, tiết lộ bí mật then chốt..."
                        />
                      </Form.Item>

                      <Form.Item
                        label="Giai đoạn tình tiết"
                        name="plot_stage"
                        tooltip="Giúp AI hiểu giai đoạn hiện tại của câu chuyện"
                      >
                        <Select>
                          <Select.Option value="development">Giai đoạn phát triển - tiếp tục mở rộng tình tiết</Select.Option>
                          <Select.Option value="climax">Giai đoạn cao trào - mâu thuẫn gay gắt</Select.Option>
                          <Select.Option value="ending">Giai đoạn kết - thu phục bút</Select.Option>
                        </Select>
                      </Form.Item>
                    </>
                  )}

                  <Form.Item
                    label={isContinue ? "Số chương viết tiếp" : "Số lượng chương"}
                    name="chapter_count"
                    rules={[{ required: true, message: 'Vui lòng nhập số lượng chương' }]}
                  >
                    <Input
                      type="number"
                      min={1}
                      max={50}
                      placeholder={isContinue ? "Gợi ý 5-10 chương" : "VD: 30"}
                    />
                  </Form.Item>

                  <Form.Item
                    label="Góc kể chuyện"
                    name="narrative_perspective"
                    rules={[{ required: true, message: 'Vui lòng chọn góc kể chuyện' }]}
                  >
                    <Select>
                      <Select.Option value="第一人称">Ngôi thứ nhất</Select.Option>
                      <Select.Option value="第三人称">Ngôi thứ ba</Select.Option>
                      <Select.Option value="全知视角">Toàn tri</Select.Option>
                    </Select>
                  </Form.Item>

                  <Form.Item label="Yêu cầu khác" name="requirements">
                    <TextArea rows={2} placeholder="Yêu cầu đặc biệt khác (tùy chọn)" />
                  </Form.Item>

                </>
              );
            }}
          </Form.Item>

          {/* 自定义模型选择 - 移到外层，所有模式都显示 */}
          {loadedModels.length > 0 && (
            <Form.Item
              label="Mô hình AI"
              name="model"
              tooltip="Chọn mô hình AI để tạo; không chọn sẽ dùng mặc định hệ thống"
            >
              <Select
                placeholder={defaultModel ? `Mặc định: ${loadedModels.find(m => m.value === defaultModel)?.label || defaultModel}` : "Dùng mô hình mặc định"}
                allowClear
                showSearch
                optionFilterProp="label"
                options={loadedModels}
                onChange={(value) => {
                  console.log('Người dùng đã chọn model trong dropdown:', value);
                  // 手动同步到Form
                  generateForm.setFieldsValue({ model: value });
                  console.log('Đã đồng bộ vào Form, giá trị Form hiện tại:', generateForm.getFieldsValue());
                }}
              />
              <div style={{ color: token.colorTextTertiary, fontSize: 12, marginTop: 4 }}>
                {defaultModel ? `Mô hình mặc định hiện tại: ${loadedModels.find(m => m.value === defaultModel)?.label || defaultModel}` : 'Chưa cấu hình mô hình mặc định'}
              </div>
            </Form.Item>
          )}
        </Form>
      ),
      okText: hasOutlines ? 'Bắt đầu viết tiếp' : 'Bắt đầu tạo',
      cancelText: 'Hủy',
      onOk: async () => {
        const values = await generateForm.validateFields();
        await handleGenerate(values);
      },
    });
  };

  // Tạo thủ công大纲
  const showManualCreateOutlineModal = () => {
    const nextOrderIndex = outlines.length > 0
      ? Math.max(...outlines.map(o => o.order_index)) + 1
      : 1;

    modalApi.confirm({
      title: 'Tạo dàn ý thủ công',
      width: 600,
      centered: true,
      content: (
        <Form
          form={manualCreateForm}
          layout="vertical"
          initialValues={{ order_index: nextOrderIndex }}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="Số thứ tự dàn ý"
            name="order_index"
            rules={[{ required: true, message: 'Vui lòng nhập số thứ tự' }]}
            tooltip={currentProject?.outline_mode === 'one-to-one' ? 'Ở chế độ truyền thống, số thứ tự chính là số chương' : 'Ở chế độ chi tiết, số thứ tự là số tập'}
          >
            <InputNumber min={1} style={{ width: '100%' }} placeholder="Số thứ tự tiếp theo được tính tự động" />
          </Form.Item>

          <Form.Item
            label="Tiêu đề dàn ý"
            name="title"
            rules={[{ required: true, message: 'Vui lòng nhập tiêu đề' }]}
          >
            <Input placeholder={currentProject?.outline_mode === 'one-to-one' ? 'Ví dụ: Chương 1 Bước vào giang hồ' : 'Ví dụ: Tập 1 Bước vào giang hồ'} />
          </Form.Item>

          <Form.Item
            label="Nội dung dàn ý"
            name="content"
            rules={[{ required: true, message: 'Vui lòng nhập nội dung' }]}
          >
            <TextArea
              rows={6}
              placeholder="Mô tả tình tiết chính và hướng phát triển của chương/tập này..."
            />
          </Form.Item>
        </Form>
      ),
      okText: 'Tạo',
      cancelText: 'Hủy',
      onOk: async () => {
        const values = await manualCreateForm.validateFields();

        // 校验序号是否重复
        const existingOutline = outlines.find(o => o.order_index === values.order_index);
        if (existingOutline) {
          modalApi.warning({
            title: 'Xung đột số thứ tự',
            content: (
              <div>
                <p>Số thứ tự <strong>{values.order_index}</strong> đã được dùng:</p>
                <div style={{
                  padding: 12,
                  background: token.colorWarningBg,
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorWarningBorder}`,
                  marginTop: 8
                }}>
                  <div style={{ fontWeight: 500, color: token.colorWarning }}>
                    {currentProject?.outline_mode === 'one-to-one'
                      ? `Chương ${existingOutline.order_index}`
                      : `Tập ${existingOutline.order_index}`
                    }:{existingOutline.title}
                  </div>
                </div>
                <p style={{ marginTop: 12, color: token.colorTextSecondary }}>
                  💡 Nên dùng số thứ tự <strong>{nextOrderIndex}</strong>, hoặc chọn số chưa dùng khác
                </p>
              </div>
            ),
            okText: 'Đã hiểu',
            centered: true
          });
          throw new Error('Trùng số thứ tự');
        }

        try {
          await outlineApi.createOutline({
            project_id: currentProject.id,
            ...values
          });
          message.success('Tạo dàn ý thành công');
          await refreshOutlines();
          manualCreateForm.resetFields();
        } catch (error: unknown) {
          const err = error as Error;
          if (err.message === 'Trùng số thứ tự') {
            // 序号重复错误已经显示了Modal，不需要再显示message
            throw error;
          }
          message.error('Tạo thất bại: ' + (err.message || 'Lỗi không xác định'));
          throw error;
        }
      }
    });
  };

  // Mở rộng单个大纲为多章 - 提交后台任务并在悬浮任务面板显示进度
  const handleExpandOutline = async (outlineId: string, outlineTitle: string) => {
    try {
      setIsExpanding(true);

      // ✅ 新增：检查是否需要按顺序Mở rộng
      const currentOutline = sortedOutlines.find(o => o.id === outlineId);
      if (currentOutline) {
        // 获取所有在当前大纲之前的大纲
        const previousOutlines = sortedOutlines.filter(
          o => o.order_index < currentOutline.order_index
        );

        // 检查前面的大纲是否都Đã mở rộng
        for (const prevOutline of previousOutlines) {
          try {
            const prevChapters = await outlineApi.getOutlineChapters(prevOutline.id);
            if (!prevChapters.has_chapters) {
              // 如果前面有Chưa mở rộng的大纲，显示提示并阻止操作
              setIsExpanding(false);
              modalApi.warning({
                title: 'Vui lòng mở rộng dàn ý theo thứ tự',
                width: 600,
                centered: true,
                content: (
                  <div>
                    <p style={{ marginBottom: 12 }}>
                      Để giữ liên tục số chương và mạch nội dung, hãy mở rộng các dàn ý phía trước trước.
                    </p>
                    <div style={{
                      padding: 12,
                      background: token.colorWarningBg,
                      borderRadius: token.borderRadius,
                      border: `1px solid ${token.colorWarningBorder}`
                    }}>
                      <div style={{ fontWeight: 500, marginBottom: 8, color: token.colorWarning }}>
                        ⚠️ Cần mở rộng trước:
                      </div>
                      <div style={{ color: token.colorTextSecondary }}>
                        Tập {prevOutline.order_index}: «{prevOutline.title}»
                      </div>
                    </div>
                    <p style={{ marginTop: 12, color: token.colorTextSecondary, fontSize: 13 }}>
                      💡 Gợi ý: Bạn cũng có thể dùng «Mở rộng hàng loạt», hệ thống sẽ xử lý mọi dàn ý theo thứ tự.
                    </p>
                  </div>
                ),
                okText: 'Đã hiểu'
              });
              return;
            }
          } catch (error) {
            console.error(`Kiểm tra dàn ý ${prevOutline.id} thất bại:`, error);
            // 如果检查失败，继续处理（避免因网络问题阻塞）
          }
        }
      }

      // 第一步：检查是否已有Mở rộng的章节
      const existingChapters = await outlineApi.getOutlineChapters(outlineId);

      if (existingChapters.has_chapters && existingChapters.expansion_plans && existingChapters.expansion_plans.length > 0) {
        // 如果已有章节，显示已有的Mở rộng规划信息
        setIsExpanding(false);
        showExistingExpansionPreview(outlineTitle, existingChapters);
        return;
      }

      // 如果没有章节，显示Mở rộng表单
      setIsExpanding(false);
      modalApi.confirm({
        title: (
          <Space>
            <BranchesOutlined />
            <span>Mở rộng dàn ý thành nhiều chương</span>
          </Space>
        ),
        width: 600,
        centered: true,
        content: (
          <div>
            <div style={{ marginBottom: 16, padding: 12, background: token.colorBgLayout, borderRadius: token.borderRadius }}>
              <div style={{ fontWeight: 500, marginBottom: 4 }}>Tiêu đề dàn ý</div>
              <div style={{ color: token.colorTextSecondary }}>{outlineTitle}</div>
            </div>
            <Form
              form={expansionForm}
              layout="vertical"
              initialValues={{
                target_chapter_count: 3,
                expansion_strategy: 'balanced',
              }}
            >
              <Form.Item
                label="Số chương mục tiêu"
                name="target_chapter_count"
                rules={[{ required: true, message: 'Vui lòng nhập số chương mục tiêu' }]}
                tooltip="Mở rộng dàn ý này thành bao nhiêu chương"
              >
                <InputNumber
                  min={2}
                  max={10}
                  style={{ width: '100%' }}
                  placeholder="Gợi ý 2-5 chương"
                />
              </Form.Item>

              <Form.Item
                label="Chiến lược mở rộng"
                name="expansion_strategy"
                tooltip="Chọn cách phân bổ nội dung vào các chương"
              >
                <Radio.Group>
                  <Radio.Button value="balanced">Phân bổ cân bằng</Radio.Button>
                  <Radio.Button value="climax">Trọng tâm cao trào</Radio.Button>
                  <Radio.Button value="detail">Giàu chi tiết</Radio.Button>
                </Radio.Group>
              </Form.Item>
            </Form>
          </div>
        ),
        okText: 'Gửi nhiệm vụ nền',
        cancelText: 'Hủy',
        onOk: async () => {
          try {
            const values = await expansionForm.validateFields();

            Modal.destroyAll();
            setIsExpanding(true);

            const requestData = {
              ...values,
              auto_create_chapters: true,
              enable_scene_analysis: true
            };

            const response = await fetch(`/api/outlines/${outlineId}/expand-background`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(requestData),
            });

            if (!response.ok) {
              const err = await response.json().catch(() => ({ detail: response.statusText }));
              throw new Error(err.detail || 'Tạo nhiệm vụ mở rộng dàn ý thất bại');
            }

            message.success('Đã gửi nhiệm vụ mở rộng dàn ý, xem tiến độ ở panel góc phải dưới');
            eventBus.emit('background-task-created');
            setIsExpanding(false);

          } catch (error) {
            console.error('Mở rộng thất bại:', error);
            message.error(error instanceof Error ? error.message : 'Mở rộng thất bại');
            setIsExpanding(false);
          }
        },
      });
    } catch (error) {
      console.error('Kiểm tra chương thất bại:', error);
      message.error('Kiểm tra chương thất bại');
      setIsExpanding(false);
    }
  };

  // XóaMở rộng的章节内容（保留大纲）
  const handleDeleteExpandedChapters = async (outlineTitle: string, chapters: Array<{ id: string }>) => {
    try {
      // 使用顺序Xóa避免并发导致的字数计算竞态条件
      // 并发Xóa会导致多个请求同时读取项目字数并各自减去章节字数，造成计算错误
      for (const chapter of chapters) {
        await chapterApi.deleteChapter(chapter.id);
      }

      message.success(`Đã xóa tất cả ${chapters.length} chương mở rộng của «${outlineTitle}»`);
      await refreshOutlines();
      // 刷新项目信息以更新字数显示
      if (currentProject?.id) {
        const updatedProject = await projectApi.getProject(currentProject.id);
        setCurrentProject(updatedProject);
      }
    } catch (error: unknown) {
      const apiError = error as ApiError;
      message.error(apiError.response?.data?.detail || 'Xóa chương thất bại');
    }
  };

  // 显示已存在章节的Mở rộng规划
  const showExistingExpansionPreview = (
    outlineTitle: string,
    data: {
      chapter_count: number;
      chapters: Array<{ id: string; chapter_number: number; title: string }>;
      expansion_plans: Array<{
        sub_index: number;
        title: string;
        plot_summary: string;
        key_events: string[];
        character_focus: string[];
        emotional_tone: string;
        narrative_goal: string;
        conflict_type: string;
        estimated_words: number;
        scenes?: Array<{
          location: string;
          characters: string[];
          purpose: string;
        }> | null;
      }> | null;
    }
  ) => {
    modalApi.info({
      title: (
        <Space style={{ flexWrap: 'wrap' }}>
          <CheckCircleOutlined style={{ color: token.colorSuccess }} />
          <span>Thông tin mở rộng «{outlineTitle}»</span>
        </Space>
      ),
      width: isMobile ? '95%' : 900,
      centered: true,
      style: isMobile ? {
        top: 20,
        maxWidth: 'calc(100vw - 16px)',
        margin: '0 8px'
      } : undefined,
      styles: {
        body: {
          maxHeight: isMobile ? 'calc(100vh - 200px)' : 'calc(80vh - 60px)',
          overflowY: 'auto',
          overflowX: 'hidden'
        }
      },
      footer: (
        <Space wrap style={{ width: '100%', justifyContent: isMobile ? 'center' : 'flex-end' }}>
          <Button
            danger
            icon={<DeleteOutlined />}
            onClick={() => {
              Modal.destroyAll();
              modalApi.confirm({
                title: 'Xác nhận xóa',
                icon: <ExclamationCircleOutlined />,
                centered: true,
                content: (
                  <div>
                    <p>Thao tác này sẽ xóa tất cả <strong>{data.chapter_count}</strong> chương đã mở rộng từ dàn ý «{outlineTitle}».</p>
                    <p style={{ color: token.colorPrimary, marginTop: 8 }}>
                      📝 Lưu ý: bản thân dàn ý được giữ, bạn có thể mở rộng lại
                    </p>
                    <p style={{ color: token.colorError, marginTop: 8 }}>
                      ⚠️ Cảnh báo: nội dung chương sẽ bị xóa vĩnh viễn và không thể khôi phục!
                    </p>
                  </div>
                ),
                okText: 'Xác nhận xóa',
                okType: 'danger',
                cancelText: 'Hủy',
                onOk: () => handleDeleteExpandedChapters(outlineTitle, data.chapters || []),
              });
            }}
            block={isMobile}
            size={isMobile ? 'middle' : undefined}
          >
            Xóa tất cả chương đã mở rộng ({data.chapter_count} chương)
          </Button>
          <Button onClick={() => Modal.destroyAll()}>
            Đóng
          </Button>
        </Space>
      ),
      content: (
        <div>
          <div style={{ marginBottom: 16 }}>
            <Space wrap style={{ maxWidth: '100%' }}>
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
                Dàn ý: {outlineTitle}
              </Tag>
              <Tag color="green">Số chương: {data.chapter_count}</Tag>
              <Tag color="orange">Đã tạo chương</Tag>
            </Space>
          </div>
          <Tabs
            defaultActiveKey="0"
            type="card"
            items={data.expansion_plans?.map((plan, idx) => ({
              key: idx.toString(),
              label: (
                <Space size="small" style={{ maxWidth: isMobile ? '150px' : 'none' }}>
                  <span
                    style={{
                      fontWeight: 500,
                      whiteSpace: isMobile ? 'normal' : 'nowrap',
                      wordBreak: isMobile ? 'break-word' : 'normal',
                      fontSize: isMobile ? 12 : 14
                    }}
                  >
                    {plan.sub_index}. {plan.title}
                  </span>
                </Space>
              ),
              children: (
                <div style={{ maxHeight: '500px', overflowY: 'auto', padding: '8px 0' }}>
                  <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                    <Card size="small" title="Thông tin cơ bản">
                      <Space wrap style={{ maxWidth: '100%' }}>
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
                          {plan.emotional_tone}
                        </Tag>
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
                          {plan.conflict_type}
                        </Tag>
                        <Tag color="green">khoảng {plan.estimated_words} chữ</Tag>
                      </Space>
                    </Card>

                    <Card size="small" title="Tóm tắt tình tiết">
                      <div style={{
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}>
                        {plan.plot_summary}
                      </div>
                    </Card>

                    <Card size="small" title="Mục tiêu kể chuyện">
                      <div style={{
                        wordBreak: 'break-word',
                        whiteSpace: 'normal',
                        overflowWrap: 'break-word'
                      }}>
                        {plan.narrative_goal}
                      </div>
                    </Card>

                    <Card size="small" title="Sự kiện then chốt">
                      <Space direction="vertical" size="small" style={{ width: '100%' }}>
                        {plan.key_events.map((event, eventIdx) => (
                          <div
                            key={eventIdx}
                            style={{
                              wordBreak: 'break-word',
                              whiteSpace: 'normal',
                              overflowWrap: 'break-word'
                            }}
                          >
                            • {event}
                          </div>
                        ))}
                      </Space>
                    </Card>

                    <Card size="small" title="Nhân vật liên quan">
                      <Space wrap style={{ maxWidth: '100%' }}>
                        {plan.character_focus.map((char, charIdx) => (
                          <Tag
                            key={charIdx}
                            color="purple"
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
                    </Card>

                    {plan.scenes && plan.scenes.length > 0 && (
                      <Card size="small" title="Cảnh">
                        <Space direction="vertical" size="small" style={{ width: '100%' }}>
                          {plan.scenes.map((scene, sceneIdx) => (
                            <Card
                              key={sceneIdx}
                              size="small"
                              style={{
                                backgroundColor: token.colorFillQuaternary,
                                maxWidth: '100%',
                                overflow: 'hidden'
                              }}
                            >
                              <div style={{
                                wordBreak: 'break-word',
                                whiteSpace: 'normal',
                                overflowWrap: 'break-word'
                              }}>
                                <strong>Địa điểm: </strong>{scene.location}
                              </div>
                              <div style={{
                                wordBreak: 'break-word',
                                whiteSpace: 'normal',
                                overflowWrap: 'break-word'
                              }}>
                                <strong>Nhân vật: </strong>{scene.characters.join(', ')}
                              </div>
                              <div style={{
                                wordBreak: 'break-word',
                                whiteSpace: 'normal',
                                overflowWrap: 'break-word'
                              }}>
                                <strong>Mục đích: </strong>{scene.purpose}
                              </div>
                            </Card>
                          ))}
                        </Space>
                      </Card>
                    )
                    }
                  </Space>
                </div >
              )
            }))}
          />
        </div >
      ),
    });
  };

  // Mở rộng hàng loạt mọi dàn ý - 提交后台任务并在悬浮任务面板显示进度
  const handleBatchExpandOutlines = () => {
    if (!currentProject?.id || outlines.length === 0) {
      message.warning('Không có dàn ý để mở rộng');
      return;
    }

    modalApi.confirm({
      title: (
        <Space>
          <AppstoreAddOutlined />
          <span>Mở rộng hàng loạt mọi dàn ý</span>
        </Space>
      ),
      width: 600,
      centered: true,
      content: (
        <div>
          <div
            style={{
              marginBottom: 16,
              padding: 12,
              background: token.colorWarningBg,
              borderRadius: token.borderRadius,
              border: `1px solid ${token.colorWarningBorder}`,
            }}
          >
            <div style={{ color: token.colorWarningText }}>
              ⚠️ Sẽ mở rộng tất cả {outlines.length} dàn ý của dự án hiện tại
            </div>
          </div>
          <Form
            form={batchExpansionForm}
            layout="vertical"
            initialValues={{
              chapters_per_outline: 3,
              expansion_strategy: 'balanced',
            }}
          >
            <Form.Item
              label="Số chương mở rộng mỗi dàn ý"
              name="chapters_per_outline"
              rules={[{ required: true, message: 'Vui lòng nhập số chương' }]}
              tooltip="Mỗi dàn ý sẽ mở rộng thành bao nhiêu chương"
            >
              <InputNumber
                min={2}
                max={10}
                style={{ width: '100%' }}
                placeholder="Gợi ý 2-5 chương"
              />
            </Form.Item>

            <Form.Item
              label="Chiến lược mở rộng"
              name="expansion_strategy"
            >
              <Radio.Group>
                <Radio.Button value="balanced">Phân bổ cân bằng</Radio.Button>
                <Radio.Button value="climax">Trọng tâm cao trào</Radio.Button>
                <Radio.Button value="detail">Giàu chi tiết</Radio.Button>
              </Radio.Group>
            </Form.Item>
          </Form>
        </div>
      ),
      okText: 'Gửi nhiệm vụ nền',
      cancelText: 'Hủy',
      okButtonProps: { type: 'primary' },
      onOk: async () => {
        try {
          const values = await batchExpansionForm.validateFields();

          Modal.destroyAll();
          setIsExpanding(true);

          const requestData = {
            project_id: currentProject.id,
            ...values,
            auto_create_chapters: true,
            enable_scene_analysis: true
          };

          const response = await fetch('/api/outlines/batch-expand-background', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData),
          });

          if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(err.detail || 'Tạo nhiệm vụ mở rộng hàng loạt thất bại');
          }

          message.success('Đã gửi nhiệm vụ mở rộng hàng loạt, xem tiến độ ở panel góc phải dưới');
          eventBus.emit('background-task-created');
          setIsExpanding(false);

        } catch (error) {
          console.error('Mở rộng hàng loạt thất bại:', error);
          message.error(error instanceof Error ? error.message : 'Mở rộng hàng loạt thất bại');
          setIsExpanding(false);
        }
      },
    });
  };

  const resetImportDialog = () => {
    setImportFile(null);
    setImportMode('append');
    setImportPreview(null);
    setIsPreviewingImport(false);
  };

  const handleExportOutlines = async () => {
    if (!currentProject?.id) return;
    setIsExporting(true);
    try {
      await outlineApi.exportOutlines(currentProject.id);
      message.success(`Đã xuất ${outlines.length} dàn ý`);
    } catch (error) {
      console.error('Xuất dàn ý thất bại:', error);
      message.error('Xuất dàn ý thất bại, vui lòng thử lại sau');
    } finally {
      setIsExporting(false);
    }
  };

  const handlePreviewImport = async () => {
    if (!currentProject?.id || !importFile) {
      message.warning('Vui lòng chọn tệp JSON cần nhập trước');
      return;
    }

    setIsPreviewingImport(true);
    setImportPreview(null);
    try {
      const preview = await outlineApi.previewImport(currentProject.id, importMode, importFile);
      setImportPreview(preview);
    } catch (error) {
      console.error('Xem trước nhập dàn ý thất bại:', error);
    } finally {
      setIsPreviewingImport(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!currentProject?.id || !importFile || !importPreview?.valid) return;

    setIsImporting(true);
    try {
      const result = await outlineApi.importOutlines(currentProject.id, importMode, importFile);
      const chapterMessage = result.created_chapters > 0
        ? `, đã đồng bộ tạo ${result.created_chapters} chương`
        : '';
      message.success(`${result.message}${chapterMessage}`);
      setImportModalOpen(false);
      resetImportDialog();
      await refreshOutlines();
      if (result.created_chapters > 0) {
        eventBus.emit(EventNames.CHAPTER_NEEDS_REFRESH);
      }
    } catch (error) {
      console.error('Nhập dàn ý thất bại:', error);
      setImportPreview(null);
    } finally {
      setIsImporting(false);
    }
  };

  return (
    <>
      {contextHolder}

      <Modal
        title="Nhập dàn ý"
        open={importModalOpen}
        width={680}
        okText="Xác nhận nhập"
        cancelText="Hủy"
        confirmLoading={isImporting}
        okButtonProps={{ disabled: !importPreview?.valid || isPreviewingImport }}
        maskClosable={!isImporting}
        closable={!isImporting}
        onOk={handleConfirmImport}
        onCancel={() => {
          if (isImporting) return;
          setImportModalOpen(false);
          resetImportDialog();
        }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="Hỗ trợ tệp xuất dàn ý, cũng hỗ trợ trích dàn ý từ tệp xuất dự án đầy đủ. Phải là JSON, tối đa 10MB."
          />

          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>1. Chọn tệp</div>
            <Upload
              accept=".json,application/json"
              maxCount={1}
              fileList={importFile ? [{
                uid: 'outline-import-file',
                name: importFile.name,
                size: importFile.size,
                type: importFile.type,
                status: 'done',
              }] : []}
              beforeUpload={(file) => {
                if (!file.name.toLowerCase().endsWith('.json')) {
                  message.error('Chỉ hỗ trợ tệp định dạng JSON');
                  return Upload.LIST_IGNORE;
                }
                if (file.size > 10 * 1024 * 1024) {
                  message.error('Kích thước tệp không quá 10MB');
                  return Upload.LIST_IGNORE;
                }
                setImportFile(file);
                setImportPreview(null);
                return false;
              }}
              onRemove={() => {
                setImportFile(null);
                setImportPreview(null);
                return true;
              }}
            >
              <Button icon={<UploadOutlined />}>Chọn tệp JSON</Button>
            </Upload>
          </div>

          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>2. Chọn cách nhập</div>
            <Radio.Group
              value={importMode}
              onChange={(event) => {
                setImportMode(event.target.value as OutlineImportMode);
                setImportPreview(null);
              }}
            >
              <Space direction="vertical">
                <Radio value="append">Thêm vào cuối hiện tại, tự đánh số lại</Radio>
                <Radio value="merge">Gộp theo số thứ tự: cùng số thì cập nhật, khác số thì thêm</Radio>
              </Space>
            </Radio.Group>
          </div>

          <Button
            type="primary"
            ghost
            icon={<FileTextOutlined />}
            disabled={!importFile}
            loading={isPreviewingImport}
            onClick={handlePreviewImport}
          >
            Xem trước kết quả nhập
          </Button>

          {importPreview && (
            <>
              <Divider style={{ margin: '4px 0' }} />
              <Alert
                type={importPreview.valid ? 'success' : 'error'}
                showIcon
                message={importPreview.valid ? 'Kiểm tra tệp thành công' : 'Kiểm tra tệp thất bại'}
                description={
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <div>
                      Phiên bản định dạng tệp: {importPreview.version || 'Không rõ'}
                      {importPreview.source_project?.title && ` · Dự án nguồn: ${importPreview.source_project.title}`}
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      <Tag>Tổng {importPreview.statistics.total} mục</Tag>
                      <Tag color="green">Thêm mới {importPreview.statistics.will_create} mục</Tag>
                      <Tag color="blue">Cập nhật {importPreview.statistics.will_update} mục</Tag>
                      {importPreview.target_outline_mode === 'one-to-one' && (
                        <Tag color="purple">Tạo chương {importPreview.statistics.will_create_chapters}</Tag>
                      )}
                    </div>
                  </Space>
                }
              />

              {importPreview.errors.length > 0 && (
                <Alert
                  type="error"
                  showIcon
                  message="Không thể nhập"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {importPreview.errors.map((error, index) => <li key={`${index}-${error}`}>{error}</li>)}
                    </ul>
                  }
                />
              )}

              {importPreview.warnings.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="Lưu ý"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {importPreview.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}
                    </ul>
                  }
                />
              )}
            </>
          )}
        </Space>
      </Modal>

      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* 固定头部 */}
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
              <FileTextOutlined style={{ marginRight: 8 }} />
              Dàn ý câu chuyện
            </h2>
            {currentProject?.outline_mode && (
              <Tag color={currentProject.outline_mode === 'one-to-one' ? 'blue' : 'green'} style={{ width: 'fit-content' }}>
                {currentProject.outline_mode === 'one-to-one' ? 'Chế độ truyền thống (1→1)' : 'Chế độ chi tiết (1→N)'}
              </Tag>
            )}
          </div>
          <Space size="small" wrap={isMobile}>
            <Input.Search
              allowClear
              placeholder="Tìm dàn ý (số thứ tự/tiêu đề/nội dung)"
              value={outlineSearchKeyword}
              onChange={(e) => setOutlineSearchKeyword(e.target.value)}
              style={{ width: isMobile ? '100%' : 280 }}
            />
            <Button
              icon={<UploadOutlined />}
              onClick={() => {
                resetImportDialog();
                setImportModalOpen(true);
              }}
              block={isMobile}
            >
              Nhập dàn ý
            </Button>
            <Button
              icon={<DownloadOutlined />}
              onClick={handleExportOutlines}
              loading={isExporting}
              disabled={outlines.length === 0}
              block={isMobile}
            >
              Xuất dàn ý
            </Button>
            <Button
              icon={<PlusOutlined />}
              onClick={showManualCreateOutlineModal}
              block={isMobile}
            >
              Tạo thủ công
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={showGenerateModal}
              loading={isGenerating}
              block={isMobile}
            >
              {isMobile ? 'AI tạo/viết tiếp' : 'AI tạo/viết tiếp dàn ý'}
            </Button>
            {outlines.length > 0 && currentProject?.outline_mode === 'one-to-many' && (
              <Button
                icon={<AppstoreAddOutlined />}
                onClick={handleBatchExpandOutlines}
                loading={isExpanding}
                disabled={isGenerating}
                title="Mở rộng mọi dàn ý thành nhiều chương, quan hệ một-nhiều từ dàn ý tới chương"
              >
                {isMobile ? 'Mở rộng hàng loạt' : 'Mở rộng hàng loạt thành nhiều chương'}
              </Button>
            )}
          </Space>
        </div>

        {/* 可滚动内容区域 */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {outlines.length === 0 ? (
            <Empty description="Chưa có dàn ý, hãy bắt đầu tạo!" />
          ) : filteredOutlines.length === 0 ? (
            <Empty description="Không tìm thấy dàn ý khớp" />
          ) : (
            <List
              dataSource={pagedOutlines}
              renderItem={(item) => {
                  const structureData = outlineStructureMap[item.id] || {};

                  // 解析角色/组织条目（兼容新旧格式）
                  const characterEntries = parseCharacterEntries(structureData.characters);
                  const characterNames = getCharacterNames(characterEntries);
                  const organizationNames = getOrganizationNames(characterEntries);
                  const isOutlineExpanded = outlineContentExpandStatus[item.id] || false;
                  const previewContent = getOutlinePreview(item.content, isMobile ? 70 : 140);
                  
                  return (
                    <List.Item
                      style={{
                        marginBottom: 16,
                        padding: 0,
                        border: 'none'
                      }}
                    >
                      <Card
                        style={{
                          width: '100%',
                          borderRadius: isMobile ? 6 : 8,
                          border: `1px solid ${token.colorBorderSecondary}`,
                          boxShadow: `0 1px 2px ${alphaColor(token.colorTextBase, 0.08)}`,
                          transition: 'all 0.3s ease'
                        }}
                        bodyStyle={{
                          padding: isMobile ? '10px 12px' : 16
                        }}
                        onMouseEnter={(e) => {
                          if (!isMobile) {
                            e.currentTarget.style.boxShadow = `0 4px 12px ${alphaColor(token.colorTextBase, 0.16)}`;
                            e.currentTarget.style.borderColor = token.colorPrimary;
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (!isMobile) {
                            e.currentTarget.style.boxShadow = `0 1px 2px ${alphaColor(token.colorTextBase, 0.08)}`;
                            e.currentTarget.style.borderColor = token.colorBorderSecondary;
                          }
                        }}
                      >
                        <List.Item.Meta
                          style={{ width: '100%' }}
                          title={
                            <Space size="small" style={{ fontSize: isMobile ? 13 : 16, flexWrap: 'wrap', lineHeight: isMobile ? '1.4' : '1.5' }}>
                              <span style={{ color: token.colorPrimary, fontWeight: 'bold', fontSize: isMobile ? 13 : 16 }}>
                                {currentProject?.outline_mode === 'one-to-one'
                                  ? `Chương ${item.order_index || '?'}`
                                  : `Tập ${item.order_index || '?'}`
                                }
                              </span>
                              <span style={{ fontSize: isMobile ? 13 : 16 }}>{item.title}</span>
                              {/* ✅ 新增：Mở rộng状态标识 - 仅在一对多模式显示 */}
                              {currentProject?.outline_mode === 'one-to-many' && (
                                outlineExpandStatus[item.id] ? (
                                  <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: isMobile ? 11 : 12 }}>Đã mở rộng</Tag>
                                ) : (
                                  <Tag color="default" style={{ fontSize: isMobile ? 11 : 12 }}>Chưa mở rộng</Tag>
                                )
                              )}
                            </Space>
                          }
                          description={
                            <div style={{ fontSize: isMobile ? 12 : 14, lineHeight: isMobile ? '1.5' : '1.6' }}>
                              {/* 大纲内容 */}
                              <div style={{
                                marginBottom: isMobile ? 10 : 12,
                                padding: isMobile ? '8px 10px' : '10px 12px',
                                background: token.colorFillQuaternary,
                                borderLeft: `3px solid ${token.colorBorderSecondary}`,
                                borderRadius: token.borderRadius,
                                fontSize: isMobile ? 12 : 13,
                                color: token.colorText,
                                lineHeight: '1.6'
                              }}>
                                <div style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'space-between',
                                  gap: 8,
                                  marginBottom: isMobile ? 4 : 6,
                                  flexWrap: isMobile ? 'wrap' : 'nowrap'
                                }}>
                                  <div style={{
                                    fontWeight: 600,
                                    color: token.colorTextSecondary,
                                    fontSize: isMobile ? 12 : 13
                                  }}>
                                    📝 Nội dung dàn ý
                                  </div>
                                  <Button
                                    type="link"
                                    size="small"
                                    onClick={() => setOutlineContentExpandStatus(prev => ({
                                      ...prev,
                                      [item.id]: !isOutlineExpanded
                                    }))}
                                    style={{
                                      padding: 0,
                                      height: 'auto',
                                      fontSize: isMobile ? 12 : 13
                                    }}
                                  >
                                    {isOutlineExpanded ? 'Thu gọn' : 'Mở rộng'}
                                  </Button>
                                </div>
                                <div style={{
                                  padding: isMobile ? '6px 8px' : '6px 10px',
                                  background: token.colorBgContainer,
                                  border: `1px solid ${token.colorBorder}`,
                                  borderRadius: token.borderRadiusSM,
                                  fontSize: isMobile ? 12 : 13,
                                  color: token.colorText,
                                  lineHeight: '1.8',
                                  whiteSpace: isOutlineExpanded ? 'pre-wrap' : 'normal',
                                  wordBreak: 'break-word'
                                }}>
                                  {isOutlineExpanded ? item.content : previewContent.text || 'Chưa có nội dung'}
                                </div>
                              </div>

                              {isOutlineExpanded && (
                                <>
                              {/* ✨ 涉及角色展示 - 优化版（支持角色/组织分类显示） */}
                              {characterNames.length > 0 && (
                                <div style={{
                                  marginTop: isMobile ? 10 : 12,
                                  padding: isMobile ? '8px 10px' : '10px 12px',
                                  background: token.colorPrimaryBg,
                                  borderLeft: `3px solid ${token.colorPrimary}`,
                                  borderRadius: token.borderRadius
                                }}>
                                  <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: isMobile ? 6 : 8,
                                    marginBottom: isMobile ? 6 : 8
                                  }}>
                                    <span style={{
                                      fontSize: isMobile ? 12 : 13,
                                      fontWeight: 600,
                                      color: token.colorPrimary,
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: 4
                                    }}>
                                      👥 Nhân vật liên quan
                                      <Tag
                                        color="purple"
                                        style={{
                                          margin: 0,
                                          fontSize: 10,
                                          borderRadius: 10,
                                          padding: '0 6px'
                                        }}
                                      >
                                        {characterNames.length}
                                      </Tag>
                                    </span>
                                  </div>
                                  <Space wrap size={[4, 4]}>
                                    {characterNames.map((name, idx) => (
                                      <Tag
                                        key={idx}
                                        color="purple"
                                        style={{
                                          margin: 0,
                                          borderRadius: 4,
                                          padding: isMobile ? '2px 8px' : '3px 10px',
                                          fontSize: isMobile ? 11 : 12,
                                          fontWeight: 500,
                                          border: `1px solid ${token.colorPrimaryBorder}`,
                                          background: token.colorBgContainer,
                                          color: token.colorPrimary,
                                          whiteSpace: 'normal',
                                          wordBreak: 'break-word',
                                          height: 'auto',
                                          lineHeight: '1.5'
                                        }}
                                      >
                                        {name}
                                      </Tag>
                                    ))}
                                  </Space>
                                </div>
                              )}
                              
                              {/* 🏛️ Tổ chức liên quan展示 */}
                              {organizationNames.length > 0 && (
                                <div style={{
                                  marginTop: isMobile ? 10 : 12,
                                  padding: isMobile ? '8px 10px' : '10px 12px',
                                  background: token.colorWarningBg,
                                  borderLeft: `3px solid ${token.colorWarning}`,
                                  borderRadius: token.borderRadius
                                }}>
                                  <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: isMobile ? 6 : 8,
                                    marginBottom: isMobile ? 6 : 8
                                  }}>
                                    <span style={{
                                      fontSize: isMobile ? 12 : 13,
                                      fontWeight: 600,
                                      color: token.colorWarning,
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: 4
                                    }}>
                                      🏛️ Tổ chức liên quan
                                      <Tag
                                        color="orange"
                                        style={{
                                          margin: 0,
                                          fontSize: 10,
                                          borderRadius: 10,
                                          padding: '0 6px'
                                        }}
                                      >
                                        {organizationNames.length}
                                      </Tag>
                                    </span>
                                  </div>
                                  <Space wrap size={[4, 4]}>
                                    {organizationNames.map((name, idx) => (
                                      <Tag
                                        key={idx}
                                        color="orange"
                                        style={{
                                          margin: 0,
                                          borderRadius: 4,
                                          padding: isMobile ? '2px 8px' : '3px 10px',
                                          fontSize: isMobile ? 11 : 12,
                                          fontWeight: 500,
                                          border: `1px solid ${token.colorWarningBorder}`,
                                          background: token.colorBgContainer,
                                          color: token.colorWarning,
                                          whiteSpace: 'normal',
                                          wordBreak: 'break-word',
                                          height: 'auto',
                                          lineHeight: '1.5'
                                        }}
                                      >
                                        {name}
                                      </Tag>
                                    ))}
                                  </Space>
                                </div>
                              )}
                              
                              {/* ✨ 场景信息展示 - 优化版（支持折叠，最多显示3个） */}
                              {structureData.scenes && structureData.scenes.length > 0 ? (() => {
                                const isExpanded = scenesExpandStatus[item.id] || false;
                                const maxVisibleScenes = 4;
                                const hasMoreScenes = structureData.scenes!.length > maxVisibleScenes;
                                const visibleScenes = isExpanded ? structureData.scenes : structureData.scenes!.slice(0, maxVisibleScenes);
                                
                                return (
                                  <div style={{
                                    marginTop: isMobile ? 10 : 12,
                                    padding: isMobile ? '8px 10px' : '10px 12px',
                                    background: token.colorInfoBg,
                                    borderLeft: `3px solid ${token.colorInfo}`,
                                    borderRadius: token.borderRadius
                                  }}>
                                    <div style={{
                                      display: 'flex',
                                      alignItems: 'center',
                                      justifyContent: 'space-between',
                                      marginBottom: isMobile ? 6 : 8,
                                      flexWrap: isMobile ? 'wrap' : 'nowrap',
                                      gap: isMobile ? 4 : 0
                                    }}>
                                      <span style={{
                                        fontSize: isMobile ? 12 : 13,
                                        fontWeight: 600,
                                        color: token.colorInfo,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 4
                                      }}>
                                        🎬 Thiết lập cảnh
                                        <Tag
                                          color="cyan"
                                          style={{
                                            margin: 0,
                                            fontSize: 10,
                                            borderRadius: 10,
                                            padding: '0 6px'
                                          }}
                                        >
                                          {structureData.scenes!.length}
                                        </Tag>
                                      </span>
                                      {hasMoreScenes && (
                                        <Button
                                          type="text"
                                          size="small"
                                          onClick={() => setScenesExpandStatus(prev => ({
                                            ...prev,
                                            [item.id]: !isExpanded
                                          }))}
                                          style={{
                                            fontSize: isMobile ? 10 : 11,
                                            height: isMobile ? 20 : 22,
                                            padding: isMobile ? '0 6px' : '0 8px',
                                            color: token.colorInfo
                                          }}
                                        >
                                          {isExpanded ? 'Thu gọn ▲' : `Mở rộng (${structureData.scenes!.length - maxVisibleScenes}+) ▼`}
                                        </Button>
                                      )}
                                    </div>
                                    {/* 使用grid布局，移动端一列，桌面端两列 */}
                                    <div style={{
                                      display: 'grid',
                                      gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(280px, 1fr))',
                                      gap: isMobile ? 6 : 8,
                                      width: '100%',
                                      minWidth: 0  // 防止grid子元素溢出
                                    }}>
                                      {visibleScenes!.map((scene, idx) => {
                                      // 判断是字符串还是对象
                                      if (typeof scene === 'string') {
                                        // 字符串格式：简洁卡片
                                        return (
                                          <div
                                            key={idx}
                                            style={{
                                              padding: isMobile ? '6px 8px' : '8px 10px',
                                              background: token.colorBgContainer,
                                              border: `1px solid ${token.colorInfoBorder}`,
                                              borderRadius: token.borderRadius,
                                              fontSize: isMobile ? 11 : 12,
                                              color: token.colorText,
                                              display: 'flex',
                                              alignItems: 'flex-start',
                                              gap: isMobile ? 6 : 8,
                                              transition: 'all 0.2s ease',
                                              cursor: 'default',
                                              width: '100%',
                                              minWidth: 0,
                                              boxSizing: 'border-box'
                                            }}
                                            onMouseEnter={(e) => {
                                              if (!isMobile) {
                                                e.currentTarget.style.borderColor = token.colorInfo;
                                                e.currentTarget.style.boxShadow = `0 2px 8px ${alphaColor(token.colorInfo, 0.25)}`;
                                              }
                                            }}
                                            onMouseLeave={(e) => {
                                              if (!isMobile) {
                                                e.currentTarget.style.borderColor = token.colorInfoBorder;
                                                e.currentTarget.style.boxShadow = 'none';
                                              }
                                            }}
                                          >
                                            <Tag
                                              color="cyan"
                                              style={{
                                                margin: 0,
                                                fontSize: 10,
                                                borderRadius: 4,
                                                flexShrink: 0
                                              }}
                                            >
                                              {idx + 1}
                                            </Tag>
                                            <span style={{
                                              flex: 1,
                                              lineHeight: '1.6',
                                              overflow: 'hidden',
                                              textOverflow: 'ellipsis',
                                              whiteSpace: 'nowrap'
                                            }}>{scene}</span>
                                          </div>
                                        );
                                      } else {
                                        // 对象格式：详细卡片
                                        return (
                                          <div
                                            key={idx}
                                            style={{
                                              padding: isMobile ? '8px 10px' : '10px 12px',
                                              background: token.colorBgContainer,
                                              border: `1px solid ${token.colorInfoBorder}`,
                                              borderRadius: token.borderRadius,
                                              fontSize: isMobile ? 11 : 12,
                                              transition: 'all 0.2s ease',
                                              cursor: 'default',
                                              width: '100%',
                                              minWidth: 0,
                                              boxSizing: 'border-box'
                                            }}
                                            onMouseEnter={(e) => {
                                              if (!isMobile) {
                                                e.currentTarget.style.borderColor = token.colorInfo;
                                                e.currentTarget.style.boxShadow = `0 2px 8px ${alphaColor(token.colorInfo, 0.25)}`;
                                              }
                                            }}
                                            onMouseLeave={(e) => {
                                              if (!isMobile) {
                                                e.currentTarget.style.borderColor = token.colorInfoBorder;
                                                e.currentTarget.style.boxShadow = 'none';
                                              }
                                            }}
                                          >
                                            <div style={{
                                              display: 'flex',
                                              alignItems: 'center',
                                              gap: isMobile ? 6 : 8,
                                              marginBottom: isMobile ? 4 : 6,
                                              flexWrap: 'wrap'
                                            }}>
                                              <Tag
                                                color="cyan"
                                                style={{
                                                  margin: 0,
                                                  fontSize: 10,
                                                  borderRadius: 4
                                                }}
                                              >
                                                Cảnh {idx + 1}
                                              </Tag>
                                              <span style={{
                                                fontWeight: 600,
                                                color: token.colorText,
                                                fontSize: isMobile ? 12 : 13,
                                                flex: 1,
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap'
                                              }}>
                                                📍 {scene.location}
                                              </span>
                                            </div>
                                            {scene.characters && scene.characters.length > 0 && (
                                              <div style={{
                                                fontSize: isMobile ? 10 : 11,
                                                color: token.colorTextSecondary,
                                                marginBottom: 4,
                                                paddingLeft: isMobile ? 2 : 4,
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap'
                                              }}>
                                                <span style={{ fontWeight: 500 }}>👤 Nhân vật: </span>
                                                {scene.characters.join(' · ')}
                                              </div>
                                            )}
                                            {scene.purpose && (
                                              <div style={{
                                                fontSize: isMobile ? 10 : 11,
                                                color: token.colorTextSecondary,
                                                paddingLeft: isMobile ? 2 : 4,
                                                lineHeight: '1.5',
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap'
                                              }}>
                                                <span style={{ fontWeight: 500 }}>🎯 Mục đích: </span>
                                                {scene.purpose}
                                              </div>
                                            )}
                                          </div>
                                        );
                                      }
                                      })}
                                    </div>
                                  </div>
                                );
                              })() : null}
                            
                            {/* ✨ 关键事件展示 */}
                            {structureData.key_events && structureData.key_events.length > 0 && (
                              <div style={{
                                marginTop: 12,
                                padding: '10px 12px',
                                background: token.colorWarningBg,
                                borderLeft: `3px solid ${token.colorWarning}`,
                                borderRadius: token.borderRadius
                              }}>
                                <div style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 8,
                                  marginBottom: 8
                                }}>
                                  <span style={{
                                    fontSize: 13,
                                    fontWeight: 600,
                                    color: token.colorWarning,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 4
                                  }}>
                                    ⚡ Sự kiện then chốt
                                    <Tag
                                      color="orange"
                                      style={{
                                        margin: 0,
                                        fontSize: 11,
                                        borderRadius: 10,
                                        padding: '0 6px'
                                      }}
                                    >
                                      {structureData.key_events.length}
                                    </Tag>
                                  </span>
                                </div>
                                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                                  {structureData.key_events.map((event, idx) => (
                                    <div
                                      key={idx}
                                      style={{
                                        padding: '6px 10px',
                                        background: token.colorBgContainer,
                                        border: `1px solid ${token.colorWarningBorder}`,
                                        borderRadius: token.borderRadiusSM,
                                        fontSize: 12,
                                        color: token.colorWarningText,
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        gap: 8
                                      }}
                                    >
                                      <Tag
                                        color="orange"
                                        style={{
                                          margin: 0,
                                          fontSize: 11,
                                          borderRadius: 4,
                                          flexShrink: 0
                                        }}
                                      >
                                        {idx + 1}
                                      </Tag>
                                      <span style={{
                                        flex: 1,
                                        lineHeight: '1.6',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap'
                                      }}>{event}</span>
                                    </div>
                                  ))}
                                </Space>
                              </div>
                            )}
                            
                            {/* ✨ 情节要点展示 (key_points) */}
                            {structureData.key_points && structureData.key_points.length > 0 && (
                              <div style={{
                                marginTop: 12,
                                padding: '10px 12px',
                                background: token.colorSuccessBg,
                                borderLeft: `3px solid ${token.colorSuccess}`,
                                borderRadius: token.borderRadius
                              }}>
                                <div style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 8,
                                  marginBottom: 8
                                }}>
                                  <span style={{
                                    fontSize: 13,
                                    fontWeight: 600,
                                    color: token.colorSuccess,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 4
                                  }}>
                                    💡 Điểm tình tiết
                                    <Tag
                                      color="green"
                                      style={{
                                        margin: 0,
                                        fontSize: 11,
                                        borderRadius: 10,
                                        padding: '0 6px'
                                      }}
                                    >
                                      {structureData.key_points.length}
                                    </Tag>
                                  </span>
                                </div>
                                {/* 使用grid布局，移动端一列，桌面端两列 */}
                                <div style={{
                                  display: 'grid',
                                  gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(280px, 1fr))',
                                  gap: isMobile ? 6 : 8,
                                  width: '100%',
                                  minWidth: 0
                                }}>
                                  {structureData.key_points.map((point, idx) => (
                                    <div
                                      key={idx}
                                      style={{
                                        padding: isMobile ? '6px 8px' : '8px 10px',
                                        background: token.colorBgContainer,
                                        border: `1px solid ${token.colorSuccessBorder}`,
                                        borderRadius: token.borderRadius,
                                        fontSize: isMobile ? 11 : 12,
                                        color: token.colorText,
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        gap: isMobile ? 6 : 8,
                                        transition: 'all 0.2s ease',
                                        cursor: 'default',
                                        width: '100%',
                                        minWidth: 0,
                                        boxSizing: 'border-box'
                                      }}
                                      onMouseEnter={(e) => {
                                        if (!isMobile) {
                                          e.currentTarget.style.borderColor = token.colorSuccess;
                                          e.currentTarget.style.boxShadow = `0 2px 8px ${alphaColor(token.colorSuccess, 0.25)}`;
                                        }
                                      }}
                                      onMouseLeave={(e) => {
                                        if (!isMobile) {
                                          e.currentTarget.style.borderColor = token.colorSuccessBorder;
                                          e.currentTarget.style.boxShadow = 'none';
                                        }
                                      }}
                                    >
                                      <Tag
                                        color="green"
                                        style={{
                                          margin: 0,
                                          fontSize: 10,
                                          borderRadius: 4,
                                          flexShrink: 0
                                        }}
                                      >
                                        {idx + 1}
                                      </Tag>
                                      <span style={{
                                        flex: 1,
                                        lineHeight: '1.6',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap'
                                      }}>{point}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            
                            {/* ✨ 情感基调展示 (emotion) */}
                            {structureData.emotion && (
                              <div style={{
                                marginTop: 12,
                                padding: '10px 12px',
                                background: token.colorWarningBg,
                                borderLeft: `3px solid ${token.colorWarning}`,
                                borderRadius: token.borderRadius,
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8
                              }}>
                                <span style={{
                                  fontSize: 13,
                                  fontWeight: 600,
                                  color: token.colorWarning
                                }}>
                                  💫 Sắc thái cảm xúc:
                                </span>
                                <Tag
                                  color="gold"
                                  style={{
                                    margin: 0,
                                    fontSize: 12,
                                    padding: '2px 12px',
                                    borderRadius: 12,
                                    background: token.colorBgContainer,
                                    border: `1px solid ${token.colorWarningBorder}`,
                                    color: token.colorWarningText
                                  }}
                                >
                                  {structureData.emotion}
                                </Tag>
                              </div>
                            )}
                            
                            {/* ✨ 叙事目标展示 (goal) */}
                            {structureData.goal && (
                              <div style={{
                                marginTop: 12,
                                padding: '10px 12px',
                                background: token.colorInfoBg,
                                borderLeft: `3px solid ${token.colorInfo}`,
                                borderRadius: token.borderRadius
                              }}>
                                <div style={{
                                  fontSize: 13,
                                  fontWeight: 600,
                                  color: token.colorInfo,
                                  marginBottom: 6
                                }}>
                                  🎯 Mục tiêu kể chuyện
                                </div>
                                <div style={{
                                  fontSize: 12,
                                  color: token.colorText,
                                  lineHeight: '1.6',
                                  padding: '6px 10px',
                                  background: token.colorBgContainer,
                                  border: `1px solid ${token.colorInfoBorder}`,
                                  borderRadius: token.borderRadiusSM,
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap'
                                }}>
                                  {structureData.goal}
                                </div>
                              </div>
                            )}
                              </>
                            )}
                          </div>
                        }
                      />
                        
                        {/* 操作按钮区域 - 在卡片内部 */}
                        <div style={{
                          marginTop: 16,
                          paddingTop: 12,
                          borderTop: `1px solid ${token.colorBorderSecondary}`,
                          display: 'flex',
                          justifyContent: 'flex-end',
                          gap: 8
                        }}>
                          {currentProject?.outline_mode === 'one-to-many' && (
                            <Button
                              icon={<BranchesOutlined />}
                              onClick={() => handleExpandOutline(item.id, item.title)}
                              loading={isExpanding}
                              size={isMobile ? 'middle' : 'small'}
                            >
                              Mở rộng
                            </Button>
                          )}
                          <Button
                            icon={<EditOutlined />}
                            onClick={() => handleOpenEditModal(item.id)}
                            size={isMobile ? 'middle' : 'small'}
                          >
                            Chỉnh sửa
                          </Button>
                          <Popconfirm
                            title="Xác nhận xóa dàn ý này?"
                            onConfirm={() => handleDeleteOutline(item.id)}
                            okText="Xác nhận"
                            cancelText="Hủy"
                          >
                            <Button
                              danger
                              icon={<DeleteOutlined />}
                              size={isMobile ? 'middle' : 'small'}
                            >
                              Xóa
                            </Button>
                          </Popconfirm>
                        </div>
                      </Card>
                    </List.Item>
                  );
                }}
              />
          )}

        </div>

        {/* 固定底部分页栏 */}
        {outlines.length > 0 && (
          <div
            style={{
              position: 'sticky',
              bottom: 0,
              zIndex: 10,
              backgroundColor: token.colorBgContainer,
              borderTop: `1px solid ${token.colorBorderSecondary}`,
              padding: isMobile ? '8px 0' : '10px 0',
              display: 'flex',
              justifyContent: 'flex-end'
            }}
          >
            <Pagination
              current={outlinePage}
              pageSize={outlinePageSize}
              total={filteredOutlines.length}
              showSizeChanger
              pageSizeOptions={['10', '20', '50', '100']}
              onChange={(page, size) => {
                setOutlinePage(page);
                if (size !== outlinePageSize) {
                  setOutlinePageSize(size);
                  setOutlinePage(1);
                }
              }}
              showTotal={(total) => `Tổng ${total} mục`}
              size={isMobile ? 'small' : 'default'}
            />
          </div>
        )}
      </div>
    </>
  );
}
