import React, { useState, useRef, useEffect } from 'react';
import { Modal, Input, Button, Space, Radio, InputNumber, Card, message, Alert, Spin, Typography, Divider, theme } from 'antd';
import { ThunderboltOutlined, CheckOutlined, ReloadOutlined, EditOutlined, LoadingOutlined } from '@ant-design/icons';
import { chapterApi } from '../services/api';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface PartialRegenerateModalProps {
  visible: boolean;
  chapterId: string;
  selectedText: string;
  startPosition: number;
  endPosition: number;
  styleId?: number;
  onClose: () => void;
  onApply: (newText: string, startPosition: number, endPosition: number) => void;
}

type LengthMode = 'similar' | 'expand' | 'condense' | 'custom';

/**
 * 局部重写弹窗组件
 * 用于配置和执行选中文本的AI重写
 */
export const PartialRegenerateModal: React.FC<PartialRegenerateModalProps> = ({
  visible,
  chapterId,
  selectedText,
  startPosition,
  endPosition,
  styleId,
  onClose,
  onApply,
}) => {
  const { token } = theme.useToken();
  const [userInstructions, setUserInstructions] = useState('');
  const [lengthMode, setLengthMode] = useState<LengthMode>('similar');
  const [customWordCount, setCustomWordCount] = useState<number>(selectedText.length);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedText, setGeneratedText] = useState('');
  const [hasGenerated, setHasGenerated] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const abortControllerRef = useRef<AbortController | null>(null);
  const generatedTextRef = useRef<HTMLDivElement>(null);

  // 重置状态
  useEffect(() => {
    if (visible) {
      setUserInstructions('');
      setLengthMode('similar');
      setCustomWordCount(selectedText.length);
      setIsGenerating(false);
      setGeneratedText('');
      setHasGenerated(false);
      setProgress(0);
      setProgressMessage('');
    }
  }, [visible, selectedText.length]);

  // 自动滚动到底部
  useEffect(() => {
    if (generatedTextRef.current && isGenerating) {
      generatedTextRef.current.scrollTop = generatedTextRef.current.scrollHeight;
    }
  }, [generatedText, isGenerating]);

  const handleGenerate = async () => {
    if (!userInstructions.trim()) {
      message.warning('Vui lòng nhập yêu cầu viết lại');
      return;
    }

    setIsGenerating(true);
    setGeneratedText('');
    setProgress(0);
    setProgressMessage('Chuẩn bị tạo...');

    // 创建 AbortController 用于取消请求
    abortControllerRef.current = new AbortController();

    try {
      await chapterApi.partialRegenerateStream(
        chapterId,
        {
          selected_text: selectedText,
          start_position: startPosition,
          end_position: endPosition,
          user_instructions: userInstructions,
          context_chars: 500,
          style_id: styleId,
          length_mode: lengthMode,
          target_word_count: lengthMode === 'custom' ? customWordCount : undefined,
        },
        {
          onProgress: (msg, prog) => {
            setProgress(prog);
            setProgressMessage(msg);
          },
          onChunk: (content) => {
            setGeneratedText(prev => prev + content);
          },
          onResult: () => {
            setProgress(100);
            setProgressMessage('Tạo hoàn tất');
            setHasGenerated(true);
          },
          onError: (error) => {
            console.error('Lỗi SSE:', error);
            message.error(error || 'Đã xảy ra lỗi trong quá trình tạo');
          },
          onComplete: () => {
            setIsGenerating(false);
            setHasGenerated(true);
          },
        }
      );
    } catch (error) {
      console.error('Tạo thất bại:', error);
      if ((error as Error).name !== 'AbortError') {
        message.error('Tạo thất bại, vui lòng thử lại');
      }
      setIsGenerating(false);
    }
  };

  const handleCancel = () => {
    if (isGenerating && abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsGenerating(false);
      message.info('Đã hủy tạo');
    }
    onClose();
  };

  const handleAccept = async () => {
    if (!generatedText.trim()) {
      message.warning('Không có nội dung để áp dụng');
      return;
    }

    try {
      // 调用后端应用更改
      await chapterApi.applyPartialRegenerate(chapterId, {
        new_text: generatedText,
        start_position: startPosition,
        end_position: endPosition,
      });

      message.success('Đã áp dụng nội dung viết lại');
      onApply(generatedText, startPosition, endPosition);
      onClose();
    } catch (error) {
      console.error('Áp dụng thất bại:', error);
      message.error('Áp dụng thất bại, vui lòng thử lại');
    }
  };

  const handleRegenerate = () => {
    setGeneratedText('');
    setHasGenerated(false);
    setProgress(0);
    setProgressMessage('');
    handleGenerate();
  };

  const getLengthModeDescription = (mode: LengthMode): string => {
    const descriptions: Record<LengthMode, string> = {
      similar: 'Giữ độ dài gần với bản gốc',
      expand: 'Mở rộng nội dung, thêm chi tiết',
      condense: 'Rút gọn nội dung, giữ điểm chính',
      custom: 'Chỉ định số chữ mục tiêu',
    };
    return descriptions[mode];
  };

  return (
    <Modal
      title={
        <Space>
          <EditOutlined style={{ color: token.colorPrimary }} />
          <span>AI viết lại cục bộ</span>
        </Space>
      }
      open={visible}
      onCancel={handleCancel}
      width={800}
      centered
      maskClosable={!isGenerating}
      closable={!isGenerating}
      keyboard={!isGenerating}
      footer={
        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
          <Button onClick={handleCancel} disabled={isGenerating}>
            Hủy
          </Button>
          {!hasGenerated ? (
            <Button
              type="primary"
              icon={isGenerating ? <LoadingOutlined /> : <ThunderboltOutlined />}
              onClick={handleGenerate}
              loading={isGenerating}
              disabled={!userInstructions.trim()}
              style={{
                background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
                border: 'none',
                boxShadow: token.boxShadowSecondary,
              }}
            >
              {isGenerating ? 'Đang tạo...' : 'Bắt đầu viết lại'}
            </Button>
          ) : (
            <>
              <Button
                icon={<ReloadOutlined />}
                onClick={handleRegenerate}
              >
                Tạo lại
              </Button>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                onClick={handleAccept}
                style={{ background: token.colorSuccess, borderColor: token.colorSuccess }}
              >
                Chấp nhận và áp dụng
              </Button>
            </>
          )}
        </Space>
      }
      styles={{
        body: {
          maxHeight: 'calc(100vh - 200px)',
          overflowY: 'auto',
        },
      }}
    >
      {/* 原文展示 */}
      <Card
        size="small"
        title={
          <Space>
            <Text strong>Nội dung gốc</Text>
            <Text type="secondary">({selectedText.length} chữ)</Text>
          </Space>
        }
        style={{ marginBottom: 16 }}
        styles={{
          body: {
            maxHeight: 150,
            overflowY: 'auto',
            background: token.colorFillAlter,
          },
        }}
      >
        <Paragraph
          style={{
            margin: 0,
            whiteSpace: 'pre-wrap',
            color: token.colorText,
            lineHeight: 1.8,
          }}
        >
          {selectedText}
        </Paragraph>
      </Card>

      {/* 重写要求输入 */}
      <div style={{ marginBottom: 16 }}>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          Yêu cầu viết lại <Text type="danger">*</Text>
        </Text>
        <TextArea
          value={userInstructions}
          onChange={(e) => setUserInstructions(e.target.value)}
          placeholder="Mô tả cách bạn muốn viết lại đoạn này, ví dụ:&#10;- Khiến miêu tả sống động, tinh tế hơn&#10;- Thêm miêu tả không khí môi trường&#10;- Tăng hoạt động tâm lý nhân vật&#10;- Thay đổi nhịp kể chuyện cho chặt hơn&#10;- Thêm hội thoại"
          rows={4}
          disabled={isGenerating}
          style={{ resize: 'none' }}
        />
      </div>

      {/* 长度模式选择 */}
      <div style={{ marginBottom: 16 }}>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          Kiểm soát độ dài
        </Text>
        <Radio.Group
          value={lengthMode}
          onChange={(e) => setLengthMode(e.target.value)}
          disabled={isGenerating}
          buttonStyle="solid"
        >
          <Radio.Button value="similar">Giữ độ dài</Radio.Button>
          <Radio.Button value="expand">Mở rộng</Radio.Button>
          <Radio.Button value="condense">Rút gọn</Radio.Button>
          <Radio.Button value="custom">Tùy chỉnh</Radio.Button>
        </Radio.Group>
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {getLengthModeDescription(lengthMode)}
          </Text>
        </div>
        {lengthMode === 'custom' && (
          <div style={{ marginTop: 12 }}>
            <Space>
              <Text>Số chữ mục tiêu: </Text>
              <InputNumber
                value={customWordCount}
                onChange={(value) => setCustomWordCount(value || selectedText.length)}
                min={10}
                max={10000}
                step={50}
                disabled={isGenerating}
                addonAfter="chữ"
                style={{ width: 150 }}
              />
            </Space>
          </div>
        )}
      </div>

      <Divider style={{ margin: '16px 0' }} />

      {/* 生成结果展示 */}
      {(isGenerating || hasGenerated) && (
        <div>
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center',
            marginBottom: 8 
          }}>
            <Space>
              <Text strong>Kết quả viết lại</Text>
              {generatedText && (
                <Text type="secondary">({generatedText.length} chữ)</Text>
              )}
            </Space>
            {isGenerating && (
              <Space>
                <Spin indicator={<LoadingOutlined style={{ fontSize: 14 }} spin />} />
                <Text type="secondary">{progressMessage || 'Đang tạo...'}</Text>
              </Space>
            )}
          </div>

          {/* 进度条 */}
          {isGenerating && (
            <div style={{ marginBottom: 12 }}>
              <div
                style={{
                  height: 4,
                  background: token.colorFillTertiary,
                  borderRadius: 2,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    background: `linear-gradient(90deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`,
                    width: `${progress}%`,
                    transition: 'width 0.3s ease',
                    borderRadius: 2,
                  }}
                />
              </div>
            </div>
          )}

          <Card
            size="small"
            ref={generatedTextRef}
            style={{
              background: generatedText ? token.colorSuccessBg : token.colorFillAlter,
              border: generatedText ? `1px solid ${token.colorSuccessBorder}` : `1px solid ${token.colorBorder}`,
            }}
            styles={{
              body: {
                maxHeight: 250,
                overflowY: 'auto',
                minHeight: 100,
              },
            }}
          >
            {generatedText ? (
              <Paragraph
                style={{
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  lineHeight: 1.8,
                }}
              >
                {generatedText}
                {isGenerating && (
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 16,
                      background: token.colorPrimary,
                      marginLeft: 2,
                      animation: 'blink 1s infinite',
                    }}
                  />
                )}
              </Paragraph>
            ) : (
              <div style={{ textAlign: 'center', padding: 20, color: token.colorTextTertiary }}>
                {isGenerating ? 'Đang tạo nội dung...' : 'Chờ tạo...'}
              </div>
            )}
          </Card>

          {hasGenerated && generatedText && (
            <Alert
              message="Tạo hoàn tất"
              description={
                <span>
                  Gốc {selectedText.length} chữ → Mới {generatedText.length} chữ
                  {generatedText.length > selectedText.length && (
                    <Text type="success"> (+{generatedText.length - selectedText.length} chữ)</Text>
                  )}
                  {generatedText.length < selectedText.length && (
                    <Text type="warning"> ({generatedText.length - selectedText.length} chữ)</Text>
                  )}
                </span>
              }
              type="success"
              showIcon
              style={{ marginTop: 12 }}
            />
          )}
        </div>
      )}

      {/* 添加闪烁光标动画 */}
      <style>{`
        @keyframes blink {
          0%, 50% { opacity: 1; }
          51%, 100% { opacity: 0; }
        }
      `}</style>
    </Modal>
  );
};

export default PartialRegenerateModal;