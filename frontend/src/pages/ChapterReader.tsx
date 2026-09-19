import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Spin, Alert, Button, Space, Switch, Drawer, message, Progress, theme } from 'antd';
import {
  ArrowLeftOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
  MenuOutlined,
  ReloadOutlined,
  LeftOutlined,
  RightOutlined,
} from '@ant-design/icons';
import api from '../services/api';
import AnnotatedText, { type MemoryAnnotation } from '../components/AnnotatedText';
import MemorySidebar from '../components/MemorySidebar';

interface ChapterData {
  id: string;
  chapter_number: number;
  title: string;
  content: string;
  word_count: number;
}

interface AnnotationsData {
  chapter_id: string;
  chapter_number: number;
  title: string;
  word_count: number;
  annotations: MemoryAnnotation[];
  has_analysis: boolean;
  summary: {
    total_annotations: number;
    hooks: number;
    foreshadows: number;
    plot_points: number;
    character_events: number;
  };
}

interface NavigationData {
  current: {
    id: string;
    chapter_number: number;
    title: string;
  };
  previous: {
    id: string;
    chapter_number: number;
    title: string;
  } | null;
  next: {
    id: string;
    chapter_number: number;
    title: string;
  } | null;
}

interface AnalysisTaskStatus {
  status: 'none' | 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  error_message?: string | null;
}

const ANALYSIS_POLL_TIMEOUT_MS = 11 * 60 * 1000;

/**
 * 章节阅读器页面
 * 展示带有记忆标注的章节内容
 */
const ChapterReader: React.FC = () => {
  const { chapterId } = useParams<{ chapterId: string }>();
  const navigate = useNavigate();

  const { token } = theme.useToken();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chapter, setChapter] = useState<ChapterData | null>(null);
  const [annotationsData, setAnnotationsData] = useState<AnnotationsData | null>(null);
  const [showAnnotations, setShowAnnotations] = useState(true);
  const [activeAnnotationId, setActiveAnnotationId] = useState<string | undefined>();
  const [sidebarVisible, setSidebarVisible] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [navigation, setNavigation] = useState<NavigationData | null>(null);
  const analysisPollTimerRef = useRef<number | null>(null);
  const analysisRunIdRef = useRef(0);

  const loadChapterData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // 并行加载章节内容、标注数据和导航信息
      // 注意：api拦截器已经解析了response.data，所以直接Quay lại数据对象
      const [chapterData, annotationsData, navigationData] = await Promise.all([
        api.get<unknown, ChapterData>(`/chapters/${chapterId}`).catch(err => {
          console.error('Tải chương thất bại:', err);
          throw err;
        }),
        api.get<unknown, AnnotationsData>(`/chapters/${chapterId}/annotations`).catch(err => {
          console.warn('Tải chú thích thất bại:', err);
          return null;
        }), // 如果没有Phân tích数据也不报错
        api.get<unknown, NavigationData>(`/chapters/${chapterId}/navigation`).catch(err => {
          console.warn('Tải thông tin điều hướng thất bại:', err);
          return null;
        }),
      ]);

      console.log('Dữ liệu chương:', chapterData);
      console.log('Dữ liệu chú thích:', annotationsData);
      console.log('Dữ liệu điều hướng:', navigationData);

      // 验证数据
      if (!chapterData || !chapterData.content) {
        throw new Error('Dữ liệu chương không hợp lệ: thiếu nội dung');
      }

      setChapter(chapterData);
      setNavigation(navigationData);
      
      // 验证标注数据
      if (annotationsData) {
        const validAnnotations = annotationsData.annotations.filter(
          (a: MemoryAnnotation) => a.position >= 0 && a.position < chapterData.content.length
        );
        const invalidCount = annotationsData.annotations.length - validAnnotations.length;
        
        if (invalidCount > 0) {
          console.warn(`${invalidCount} chú thích có vị trí không hợp lệ, chỉ hiển thị ${validAnnotations.length} chú thích hợp lệ`);
        }
        
        setAnnotationsData(annotationsData);
      } else {
        setAnnotationsData(null);
      }
    } catch (err: unknown) {
      console.error('Tải dữ liệu chương thất bại:', err);
      const error = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(error.response?.data?.detail || error.message || 'Tải thất bại');
    } finally {
      setLoading(false);
    }
  }, [chapterId]);

  useEffect(() => {
    if (chapterId) {
      loadChapterData();
    }
  }, [chapterId, loadChapterData]);

  useEffect(() => {
    return () => {
      analysisRunIdRef.current += 1;
      if (analysisPollTimerRef.current !== null) {
        window.clearTimeout(analysisPollTimerRef.current);
        analysisPollTimerRef.current = null;
      }
    };
  }, [chapterId]);

  const handleAnnotationClick = (annotation: MemoryAnnotation) => {
    setActiveAnnotationId(annotation.id);
    // 移动端显示侧边栏
    if (window.innerWidth < 768) {
      setSidebarVisible(true);
    }
  };

  const handleBackClick = () => {
    navigate(-1);
  };

  const handlePreviousChapter = () => {
    if (navigation?.previous) {
      navigate(`/chapters/${navigation.previous.id}/reader`);
    }
  };

  const handleNextChapter = () => {
    if (navigation?.next) {
      navigate(`/chapters/${navigation.next.id}/reader`);
    }
  };

  const handleReanalyze = async () => {
    if (!chapterId) return;

    const requestedChapterId = chapterId;
    const runId = analysisRunIdRef.current + 1;
    analysisRunIdRef.current = runId;
    const deadline = Date.now() + ANALYSIS_POLL_TIMEOUT_MS;

    if (analysisPollTimerRef.current !== null) {
      window.clearTimeout(analysisPollTimerRef.current);
      analysisPollTimerRef.current = null;
    }

    try {
      setAnalyzing(true);
      setAnalysisProgress(0);
      message.loading({ content: 'Bắt đầu phân tích chương...', key: 'analyze', duration: 0 });

      // 触发Phân tích
      await api.post(`/chapters/${requestedChapterId}/analyze`);

      const pollStatus = async (): Promise<void> => {
        if (analysisRunIdRef.current !== runId) return;

        if (Date.now() >= deadline) {
          setAnalyzing(false);
          message.warning({ content: 'Phân tích hết thời gian, vui lòng làm mới sau để xem kết quả', key: 'analyze' });
          return;
        }

        try {
          const statusRes = await api.get<unknown, AnalysisTaskStatus>(
            `/chapters/${requestedChapterId}/analysis/status`
          );
          if (analysisRunIdRef.current !== runId) return;

          const { status, progress, error_message } = statusRes;

          setAnalysisProgress(progress || 0);

          if (status === 'completed') {
            setAnalyzing(false);
            message.success({ content: 'Phân tích hoàn tất!', key: 'analyze' });
            const annotationsRes = await api.get<unknown, AnnotationsData>(
              `/chapters/${requestedChapterId}/annotations`
            );
            if (analysisRunIdRef.current === runId) {
              setAnnotationsData(annotationsRes);
            }
            return;
          } else if (status === 'failed') {
            setAnalyzing(false);
            message.error({
              content: `Phân tích thất bại: ${error_message || 'Lỗi không xác định'}`,
              key: 'analyze'
            });
            return;
          }
        } catch (err) {
          console.error('Thăm dò trạng thái phân tích thất bại:', err);
        }

        if (analysisRunIdRef.current === runId) {
          analysisPollTimerRef.current = window.setTimeout(() => {
            void pollStatus();
          }, 2000);
        }
      };

      void pollStatus();
    } catch (err: unknown) {
      if (analysisRunIdRef.current === runId) {
        setAnalyzing(false);
      }
      const error = err as { response?: { data?: { detail?: string } } };
      message.error({
        content: error.response?.data?.detail || 'Kích hoạt phân tích thất bại',
        key: 'analyze'
      });
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0' }}>
        <Spin size="large" tip="Đang tải chương..." />
      </div>
    );
  }

  if (error || !chapter) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          message="Tải thất bại"
          description={error || 'Chương không tồn tại'}
          type="error"
          showIcon
        />
        <Button onClick={handleBackClick} style={{ marginTop: 16 }}>
          Quay lại
        </Button>
      </div>
    );
  }

  const hasAnnotations = annotationsData && annotationsData.annotations.length > 0;

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 顶部工具栏 */}
      <Card
        size="small"
        style={{
          borderRadius: 0,
          borderLeft: 0,
          borderRight: 0,
          borderTop: 0,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={handleBackClick}>
              Quay lại
            </Button>
            <Button
              icon={<LeftOutlined />}
              onClick={handlePreviousChapter}
              disabled={!navigation?.previous}
              title={navigation?.previous ? `Chương trước: ${navigation.previous.title}` : 'Đã là chương đầu'}
            >
              Chương trước
            </Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>
              Chương {chapter.chapter_number}: {chapter.title}
            </span>
            <Button
              icon={<RightOutlined />}
              onClick={handleNextChapter}
              disabled={!navigation?.next}
              title={navigation?.next ? `Chương sau: ${navigation.next.title}` : 'Đã là chương cuối'}
            >
              Chương sau
            </Button>
          </Space>

          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={handleReanalyze}
              loading={analyzing}
              disabled={analyzing}
            >
              {analyzing ? 'Đang phân tích...' : 'Phân tích lại'}
            </Button>
            {hasAnnotations && (
              <>
                <Switch
                  checked={showAnnotations}
                  onChange={setShowAnnotations}
                  checkedChildren={<EyeOutlined />}
                  unCheckedChildren={<EyeInvisibleOutlined />}
                />
                <span style={{ fontSize: 13, color: token.colorTextSecondary }}>Hiện chú thích</span>
                <Button
                  icon={<MenuOutlined />}
                  onClick={() => setSidebarVisible(true)}
                  style={{ display: window.innerWidth < 768 ? 'inline-block' : 'none' }}
                >
                  Phân tích
                </Button>
              </>
            )}
          </Space>
        </div>

        {analyzing && (
          <div style={{ marginTop: 12 }}>
            <Progress percent={analysisProgress} size="small" status="active" />
            <span style={{ fontSize: 12, color: token.colorTextSecondary, marginLeft: 8 }}>
              Đang phân tích chương...
            </span>
          </div>
        )}

        {!analyzing && hasAnnotations && annotationsData && (
          <div style={{ marginTop: 12, fontSize: 12, color: token.colorTextTertiary }}>
            Tổng {annotationsData.summary.total_annotations} chú thích:
            {annotationsData.summary.hooks > 0 && ` 🎣${annotationsData.summary.hooks} móc`}
            {annotationsData.summary.foreshadows > 0 &&
              ` 🌟${annotationsData.summary.foreshadows} phục bút`}
            {annotationsData.summary.plot_points > 0 &&
              ` 💎${annotationsData.summary.plot_points} điểm tình tiết`}
            {annotationsData.summary.character_events > 0 &&
              ` 👤${annotationsData.summary.character_events} sự kiện nhân vật`}
          </div>
        )}
      </Card>

      {/* 主内容区域 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左侧：章节内容 */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '32px 48px',
            maxWidth: hasAnnotations ? 'calc(100% - 400px)' : '100%',
          }}
        >
          <Card>
            <div style={{ maxWidth: 800, margin: '0 auto' }}>
              {!hasAnnotations && (
                <Alert
                  message="Chưa có dữ liệu phân tích"
                  description="Chương này chưa được AI phân tích, không thể hiện chú thích ghi nhớ."
                  type="info"
                  showIcon
                  style={{ marginBottom: 24 }}
                />
              )}

              {showAnnotations && hasAnnotations && annotationsData ? (
                <AnnotatedText
                  content={chapter.content}
                  annotations={annotationsData.annotations}
                  onAnnotationClick={handleAnnotationClick}
                  activeAnnotationId={activeAnnotationId}
                />
              ) : (
                <div
                  style={{
                    lineHeight: 2,
                    fontSize: 16,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {chapter.content}
                </div>
              )}

              {/* 底部翻页按钮 */}
              <div style={{ marginTop: 48, paddingTop: 24, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Button
                    size="large"
                    icon={<LeftOutlined />}
                    onClick={handlePreviousChapter}
                    disabled={!navigation?.previous}
                  >
                    {navigation?.previous
                      ? `Chương trước: Chương ${navigation.previous.chapter_number} - ${navigation.previous.title}`
                      : 'Đã là chương đầu'}
                  </Button>
                  <Button
                    size="large"
                    type="primary"
                    icon={<RightOutlined />}
                    onClick={handleNextChapter}
                    disabled={!navigation?.next}
                    iconPosition="end"
                  >
                    {navigation?.next
                      ? `Chương sau: Chương ${navigation.next.chapter_number} - ${navigation.next.title}`
                      : 'Đã là chương cuối'}
                  </Button>
                </Space>
              </div>
            </div>
          </Card>
        </div>

        {/* 右侧：记忆侧边栏（桌面端） */}
        {hasAnnotations && annotationsData && window.innerWidth >= 768 && (
          <div
            style={{
              width: 400,
              borderLeft: `1px solid ${token.colorBorderSecondary}`,
              overflowY: 'auto',
              background: token.colorBgLayout,
            }}
          >
            <MemorySidebar
              annotations={annotationsData.annotations}
              activeAnnotationId={activeAnnotationId}
              onAnnotationClick={handleAnnotationClick}
            />
          </div>
        )}
      </div>

      {/* 移动端抽屉 */}
      {hasAnnotations && annotationsData && (
        <Drawer
          title="Phân tích chương"
          placement="right"
          onClose={() => setSidebarVisible(false)}
          open={sidebarVisible}
          width="80%"
        >
          <MemorySidebar
            annotations={annotationsData.annotations}
            activeAnnotationId={activeAnnotationId}
            onAnnotationClick={(annotation) => {
              handleAnnotationClick(annotation);
              setSidebarVisible(false);
            }}
          />
        </Drawer>
      )}
    </div>
  );
};

export default ChapterReader;
