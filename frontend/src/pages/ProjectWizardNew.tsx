import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Form, Input, InputNumber, Select, Button, Card,
  Row, Col, Typography, Space, message, Radio, theme
} from 'antd';
import {
  RocketOutlined, ArrowLeftOutlined, CheckCircleOutlined
} from '@ant-design/icons';
import { AIProjectGenerator, type GenerationConfig } from '../components/AIProjectGenerator';
import type { WizardBasicInfo } from '../types';

const { TextArea } = Input;
const { Title, Paragraph } = Typography;

export default function ProjectWizardNew() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [form] = Form.useForm();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const { token } = theme.useToken();

  // 状态管理
  const [currentStep, setCurrentStep] = useState<'form' | 'generating'>('form');
  const [generationConfig, setGenerationConfig] = useState<GenerationConfig | null>(null);
  const [resumeProjectId, setResumeProjectId] = useState<string | null>(null);
  const requestedProjectId = searchParams.get('project_id');

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 检查URL参数,如果有project_id则恢复生成
  useEffect(() => {
    if (!requestedProjectId) return;

    const projectId = requestedProjectId;

    const controller = new AbortController();
    const startTimer = window.setTimeout(() => {
      if (controller.signal.aborted) return;

      setResumeProjectId(projectId);
      void handleResumeGeneration(projectId, controller.signal);
    }, 0);

    return () => {
      window.clearTimeout(startTimer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedProjectId]);

  // 恢复未完成项目的生成
  const handleResumeGeneration = async (projectId: string, signal?: AbortSignal) => {
    try {
      const response = await fetch(`/api/projects/${projectId}`, {
        credentials: 'include',
        signal,
      });
      if (!response.ok) {
        throw new Error('Lấy thông tin dự án thất bại');
      }
      const project = await response.json();

      const config: GenerationConfig = {
        title: project.title,
        description: project.description || '',
        theme: project.theme || '',
        genre: project.genre || '',
        narrative_perspective: project.narrative_perspective || '第三人称',
        target_words: project.target_words || 100000,
        chapter_count: 3,
        character_count: project.character_count || 5,
      };

      setGenerationConfig(config);
      setCurrentStep('generating');
    } catch (error) {
      if (
        typeof error === 'object'
        && error !== null
        && 'name' in error
        && error.name === 'AbortError'
      ) {
        return;
      }

      console.error('Khôi phục quá trình tạo thất bại:', error);
      message.error('Khôi phục tạo thất bại, vui lòng thử lại');
      navigate('/');
    }
  };

  // 开始生成流程
  const handleAutoGenerate = async (values: WizardBasicInfo) => {
    const config: GenerationConfig = {
      title: values.title,
      description: values.description,
      theme: values.theme,
      genre: values.genre,
      narrative_perspective: values.narrative_perspective,
      target_words: values.target_words || 100000,
      chapter_count: 3, // 默认生成3章大纲
      character_count: values.character_count || 5,
      outline_mode: values.outline_mode || 'one-to-many', // 添加大纲模式
    };

    setGenerationConfig(config);
    setCurrentStep('generating');
  };

  // 生成完成回调
  const handleComplete = (projectId: string) => {
    console.log('Tạo dự án hoàn tất:', projectId);
  };

  // 返回表单页面
  const handleBack = () => {
    setCurrentStep('form');
    setGenerationConfig(null);
  };

  // 渲染表单页面
  const renderForm = () => (
    <Card>
      <Title level={isMobile ? 4 : 3} style={{ marginBottom: 24 }}>
        Tạo dự án mới
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 32 }}>
        Sau khi điền thông tin cơ bản, AI sẽ tự tạo bối cảnh thế giới, nhân vật và nút dàn ý (có thể mở rộng thủ công thành chương trong dự án)
      </Paragraph>

      <Form
        form={form}
        layout="vertical"
        onFinish={handleAutoGenerate}
        initialValues={{
          genre: ['玄幻'],
          chapter_count: 30,
          narrative_perspective: '第三人称',
          character_count: 5,
          target_words: 100000,
          outline_mode: 'one-to-one', // 默认为传统模式（1-1）
        }}
      >
        <Form.Item
          label="Tên sách"
          name="title"
          rules={[{ required: true, message: 'Vui lòng nhập tên sách' }]}
        >
          <Input placeholder="Nhập tiêu đề tiểu thuyết của bạn" size="large" />
        </Form.Item>

        <Form.Item
          label="Tóm tắt tiểu thuyết"
          name="description"
          rules={[{ required: true, message: 'Vui lòng nhập tóm tắt tiểu thuyết' }]}
        >
          <TextArea
            rows={3}
            placeholder="Giới thiệu tiểu thuyết bằng một đoạn..."
            showCount
          />
        </Form.Item>

        <Form.Item
          label="Chủ đề"
          name="theme"
          rules={[{ required: true, message: 'Vui lòng nhập chủ đề' }]}
        >
          <TextArea
            rows={4}
            placeholder="Mô tả chủ đề tiểu thuyết của bạn..."
            showCount
          />
        </Form.Item>

        <Form.Item
          label="Loại"
          name="genre"
          rules={[{ required: true, message: 'Vui lòng chọn thể loại tiểu thuyết' }]}
        >
          <Select
            mode="tags"
            placeholder="Chọn hoặc nhập nhãn thể loại (VD: huyền huyễn, đô thị, tu tiên)"
            size="large"
            tokenSeparators={[',']}
            maxTagCount={5}
          >
            <Select.Option value="玄幻">Huyền huyễn</Select.Option>
            <Select.Option value="都市">Đô thị</Select.Option>
            <Select.Option value="历史">Lịch sử</Select.Option>
            <Select.Option value="科幻">Khoa học viễn tưởng</Select.Option>
            <Select.Option value="武侠">Võ hiệp</Select.Option>
            <Select.Option value="仙侠">Tiên hiệp</Select.Option>
            <Select.Option value="奇幻">Kỳ ảo</Select.Option>
            <Select.Option value="悬疑">Huyền nghi</Select.Option>
            <Select.Option value="言情">Ngôn tình</Select.Option>
            <Select.Option value="修仙">Tu tiên</Select.Option>
          </Select>
        </Form.Item>

        <Form.Item
          label="Chế độ chương dàn ý"
          name="outline_mode"
          rules={[{ required: true, message: 'Vui lòng chọn chế độ chương dàn ý' }]}
          tooltip="Không thể đổi sau khi tạo, hãy chọn theo thói quen sáng tác"
        >
          <Radio.Group size="large">
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                <Card
                  hoverable
                  style={{
                    // borderColor: form.getFieldValue('outline_mode') === 'one-to-one' ? token.colorPrimary : token.colorBorder,
                    borderWidth: 2,
                    height: '100%',
                  }}
                  onClick={() => form.setFieldValue('outline_mode', 'one-to-one')}
                >
                  <Radio value="one-to-one" style={{ width: '100%' }}>
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <div style={{ fontSize: 16, fontWeight: 'bold' }}>
                        <CheckCircleOutlined style={{ marginRight: 8, color: token.colorSuccess }} />
                        Chế độ truyền thống (1→1)
                      </div>
                      <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                        Một dàn ý tương ứng một chương, đơn giản trực tiếp
                      </div>
                      <div style={{ fontSize: 11, color: token.colorTextTertiary }}>
                        💡 Phù hợp: cốt truyện đơn giản, sáng tác nhanh, truyện ngắn
                      </div>
                    </Space>
                  </Radio>
                </Card>
              </Col>

              <Col xs={24} sm={12}>
                <Card
                  hoverable
                  style={{
                    // borderColor: form.getFieldValue('outline_mode') === 'one-to-many' ? token.colorPrimary : token.colorBorder,
                    borderWidth: 2,
                    height: '100%',
                  }}
                  onClick={() => form.setFieldValue('outline_mode', 'one-to-many')}
                >
                  <Radio value="one-to-many" style={{ width: '100%' }}>
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <div style={{ fontSize: 16, fontWeight: 'bold' }}>
                        <CheckCircleOutlined style={{ marginRight: 8, color: token.colorSuccess }} />
                        Chế độ chi tiết (1→N) khuyến nghị
                      </div>
                      <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                        Một dàn ý có thể mở rộng thành nhiều chương, linh hoạt
                      </div>
                      <div style={{ fontSize: 11, color: token.colorTextTertiary }}>
                        💡 Phù hợp: cốt truyện phức tạp, sáng tác dài, cần kiểm soát chi tiết
                      </div>
                    </Space>
                  </Radio>
                </Card>
              </Col>
            </Row>
          </Radio.Group>
        </Form.Item>

        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item
              label="Góc kể chuyện"
              name="narrative_perspective"
              rules={[{ required: true, message: 'Vui lòng chọn góc kể chuyện' }]}
            >
              <Select size="large" placeholder="Chọn góc kể chuyện của tiểu thuyết">
                <Select.Option value="第一人称">Ngôi thứ nhất</Select.Option>
                <Select.Option value="第三人称">Ngôi thứ ba</Select.Option>
                <Select.Option value="全知视角">Toàn tri</Select.Option>
              </Select>
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item
              label="Số lượng nhân vật"
              name="character_count"
              rules={[{ required: true, message: 'Vui lòng nhập số lượng nhân vật' }]}
            >
              <InputNumber
                min={3}
                max={20}
                style={{ width: '100%' }}
                size="large"
                addonAfter=" cái"
                placeholder="Số nhân vật do AI tạo"
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          label="Số chữ mục tiêu"
          name="target_words"
          rules={[{ required: true, message: 'Vui lòng nhập số chữ mục tiêu' }]}
        >
          <InputNumber
            min={10000}
            style={{ width: '100%' }}
            size="large"
            addonAfter="chữ"
            placeholder="Số chữ mục tiêu của cả tiểu thuyết"
          />
        </Form.Item>

        <Form.Item>
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              icon={<RocketOutlined />}
            >
              Bắt đầu tạo dự án
            </Button>
            <Button
              size="large"
              block
              onClick={() => navigate('/')}
            >
              Về trang chủ
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );

  return (
    <div style={{
      minHeight: '100dvh',
      background: token.colorBgBase,
    }}>
      {/* 顶部标题栏 - 固定不滚动 */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        background: token.colorPrimary,
        boxShadow: `0 6px 20px color-mix(in srgb, ${token.colorPrimary} 30%, transparent)`,
      }}>
        <div style={{
          maxWidth: 1200,
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: isMobile ? '12px 16px' : '16px 24px',
        }}>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
            size={isMobile ? 'middle' : 'large'}
            disabled={currentStep === 'generating'}
            style={{
              background: `color-mix(in srgb, ${token.colorWhite} 20%, transparent)`,
              borderColor: `color-mix(in srgb, ${token.colorWhite} 30%, transparent)`,
              color: token.colorWhite,
            }}
          >
            {isMobile ? 'Quay lại' : 'Về trang chủ'}
          </Button>

          <Title level={isMobile ? 4 : 2} style={{
            margin: 0,
            color: token.colorWhite,
            textShadow: '0 2px 4px color-mix(in srgb, var(--ant-color-black) 18%, transparent)',
          }}>
            <RocketOutlined style={{ marginRight: 8 }} />
            Hướng dẫn tạo dự án
          </Title>

          <div style={{ width: isMobile ? 60 : 120 }}></div>
        </div>
      </div>

      {/* 内容区域 */}
      <div style={{
        maxWidth: 800,
        margin: '0 auto',
        padding: isMobile ? '8px 12px 12px' : '12px 20px 16px',
      }}>
        {currentStep === 'form' && renderForm()}
        {currentStep === 'generating' && generationConfig && (
          <AIProjectGenerator
            config={generationConfig}
            storagePrefix="wizard"
            onComplete={handleComplete}
            onBack={handleBack}
            isMobile={isMobile}
            resumeProjectId={resumeProjectId || undefined}
          />
        )}
      </div>
    </div>
  );
}
