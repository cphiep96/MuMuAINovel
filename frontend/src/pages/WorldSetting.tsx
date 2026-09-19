import { Card, Descriptions, Empty, Typography, Button, Modal, Form, Input, message, Flex, InputNumber, Select, theme } from 'antd';
import { GlobalOutlined, EditOutlined, SyncOutlined, FormOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { useStore } from '../store';
import { worldSettingCardStyles } from '../components/CardStyles';
import { genreLabels, perspectiveLabel } from '../utils/displayLabels';
import { projectApi, wizardStreamApi } from '../services/api';
import { SSELoadingOverlay } from '../components/SSELoadingOverlay';

const { Title, Paragraph } = Typography;
const { TextArea } = Input;

export default function WorldSetting() {
  const { currentProject, setCurrentProject } = useStore();
  const [isEditModalVisible, setIsEditModalVisible] = useState(false);
  const [editForm] = Form.useForm();
  const [isSaving, setIsSaving] = useState(false);
  const [isEditProjectModalVisible, setIsEditProjectModalVisible] = useState(false);
  const [editProjectForm] = Form.useForm();
  const [isSavingProject, setIsSavingProject] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenerateProgress, setRegenerateProgress] = useState(0);
  const [regenerateMessage, setRegenerateMessage] = useState('');
  const [isPreviewModalVisible, setIsPreviewModalVisible] = useState(false);
  const [newWorldData, setNewWorldData] = useState<{
    time_period: string;
    location: string;
    atmosphere: string;
    rules: string;
  } | null>(null);
  const [isSavingPreview, setIsSavingPreview] = useState(false);
  const [modal, contextHolder] = Modal.useModal();
  const { token } = theme.useToken();

  // AI tạo lại世界观
  const handleRegenerate = async () => {
    if (!currentProject) return;

    modal.confirm({
      title: 'Xác nhận tạo lại',
      content: 'Xác nhận dùng AI tạo lại thiết lập bối cảnh thế giới? Nội dung hiện tại sẽ bị thay.',
      centered: true,
      okText: 'Xác nhận tạo lại',
      cancelText: 'Hủy',
      onOk: async () => {
        setIsRegenerating(true);
        setRegenerateProgress(0);
        setRegenerateMessage('Chuẩn bị tạo lại bối cảnh thế giới...');

        try {
          await wizardStreamApi.regenerateWorldBuildingStream(
            currentProject.id,
            {},
            {
              onProgress: (msg: string, progress: number) => {
                setRegenerateProgress(progress);
                setRegenerateMessage(msg);
              },
              onChunk: (chunk: string) => {
                // 可以在这里显示生成的内容片段（可选）
                console.log('Tạo đoạn:', chunk);
              },
              onResult: (result: { time_period: string; location: string; atmosphere: string; rules: string }) => {
                // 保存新生成的数据
                const newData = {
                  time_period: result.time_period,
                  location: result.location,
                  atmosphere: result.atmosphere,
                  rules: result.rules,
                };
                setNewWorldData(newData);
              },
              onError: (errorMsg: string) => {
                console.error('Tạo lại thất bại:', errorMsg);
                message.error(errorMsg || 'Tạo lại thất bại, vui lòng thử lại');
              },
              onComplete: () => {
                setIsRegenerating(false);
                setRegenerateProgress(0);
                setRegenerateMessage('');
                // 显示预览对话框
                setIsPreviewModalVisible(true);
              }
            }
          );
        } catch (error) {
          console.error('Lỗi khi tạo lại:', error);
          message.error('Tạo lại bị lỗi, vui lòng thử lại');
          setIsRegenerating(false);
          setRegenerateProgress(0);
          setRegenerateMessage('');
        }
      }
    });
  };

  // 确认保存重新生成的内容
  const handleConfirmSave = async () => {
    if (!currentProject || !newWorldData) return;

    setIsSavingPreview(true);
    try {
      const updatedProject = await projectApi.updateProject(currentProject.id, {
        world_time_period: newWorldData.time_period,
        world_location: newWorldData.location,
        world_atmosphere: newWorldData.atmosphere,
        world_rules: newWorldData.rules,
      });

      setCurrentProject(updatedProject);
      message.success('Đã cập nhật bối cảnh thế giới!');
      setIsPreviewModalVisible(false);
      setNewWorldData(null);
    } catch (error) {
      console.error('Lưu thất bại:', error);
      message.error('Lưu thất bại, vui lòng thử lại');
    } finally {
      setIsSavingPreview(false);
    }
  };

  // 取消保存，关闭预览
  const handleCancelSave = () => {
    setIsPreviewModalVisible(false);
    setNewWorldData(null);
    message.info('Đã hủy, giữ nội dung cũ');
  };

  if (!currentProject) return null;

  // 检查是否有世界设定信息
  const hasWorldSetting = currentProject.world_time_period ||
    currentProject.world_location ||
    currentProject.world_atmosphere ||
    currentProject.world_rules;

  if (!hasWorldSetting) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* 固定头部 */}
        <div style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: token.colorBgContainer,
          padding: '16px 0',
          marginBottom: 16,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          display: 'flex',
          alignItems: 'center'
        }}>
          <GlobalOutlined style={{ fontSize: 24, marginRight: 12, color: token.colorPrimary }} />
          <h2 style={{ margin: 0 }}>Thiết lập thế giới</h2>
        </div>

        {/* 可滚动内容区域 */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <Empty
            description="Chưa có thông tin thiết lập thế giới"
            style={{ marginTop: 60 }}
          >
            <Paragraph type="secondary">
              Thông tin thiết lập thế giới được tạo trong hướng dẫn tạo dự án, dùng để dựng bối cảnh thế giới tiểu thuyết.
            </Paragraph>
          </Empty>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {contextHolder}
      {/* 固定头部 */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: token.colorBgContainer,
        padding: '16px 0',
        marginBottom: 24,
        borderBottom: `1px solid ${token.colorBorderSecondary}`
      }}>
        <Flex
          justify="space-between"
          align="flex-start"
          gap={12}
          wrap="wrap"
        >
          <div style={{ display: 'flex', alignItems: 'center', minWidth: 'fit-content' }}>
            <GlobalOutlined style={{ fontSize: 24, marginRight: 12, color: token.colorPrimary }} />
            <h2 style={{ margin: 0, whiteSpace: 'nowrap' }}>Thiết lập thế giới</h2>
          </div>
          <Flex gap={8} wrap="wrap" style={{ flex: '0 1 auto' }}>
            <Button
              icon={<SyncOutlined />}
              onClick={handleRegenerate}
              disabled={isRegenerating}
              style={{
                minWidth: 'fit-content',
                flex: '1 1 auto'
              }}
            >
              <span className="button-text-mobile">AI tạo lại</span>
            </Button>
            <Button
              type="primary"
              icon={<FormOutlined />}
              onClick={() => {
                editProjectForm.setFieldsValue({
                  title: currentProject.title || '',
                  description: currentProject.description || '',
                  theme: currentProject.theme || '',
                  genre: currentProject.genre || '',
                  narrative_perspective: currentProject.narrative_perspective || '',
                  target_words: currentProject.target_words || 0,
                });
                setIsEditProjectModalVisible(true);
              }}
              style={{
                minWidth: 'fit-content',
                flex: '1 1 auto'
              }}
            >
              <span className="button-text-mobile">Chỉnh sửa thông tin cơ bản</span>
            </Button>
            <Button
              type="primary"
              icon={<EditOutlined />}
              onClick={() => {
                editForm.setFieldsValue({
                  world_time_period: currentProject.world_time_period || '',
                  world_location: currentProject.world_location || '',
                  world_atmosphere: currentProject.world_atmosphere || '',
                  world_rules: currentProject.world_rules || '',
                });
                setIsEditModalVisible(true);
              }}
              style={{
                minWidth: 'fit-content',
                flex: '1 1 auto'
              }}
            >
              <span className="button-text-mobile">Chỉnh sửa bối cảnh thế giới</span>
            </Button>
          </Flex>
        </Flex>
      </div>

      {/* 可滚动内容区域 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <Card
          style={{
            ...worldSettingCardStyles.sectionCard,
            marginBottom: 16
          }}
          title={
            <span style={{ fontSize: 18, fontWeight: 500 }}>
              Thông tin cơ bản
            </span>
          }
        >
          <Descriptions bordered column={1} styles={{ label: { width: 120, fontWeight: 500 } }}>
            <Descriptions.Item label="Tên tiểu thuyết">{currentProject.title}</Descriptions.Item>
            {currentProject.description && (
              <Descriptions.Item label="Tóm tắt tiểu thuyết">{currentProject.description}</Descriptions.Item>
            )}
            <Descriptions.Item label="Chủ đề tiểu thuyết">{currentProject.theme || 'Chưa đặt'}</Descriptions.Item>
            <Descriptions.Item label="Thể loại tiểu thuyết">{genreLabels(currentProject.genre).join(', ') || 'Chưa đặt'}</Descriptions.Item>
            <Descriptions.Item label="Góc kể chuyện">{perspectiveLabel(currentProject.narrative_perspective) || 'Chưa đặt'}</Descriptions.Item>
            <Descriptions.Item label="Số chữ mục tiêu">
              {currentProject.target_words ? `${currentProject.target_words.toLocaleString()} chữ` : 'Chưa đặt'}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card
          style={{
            ...worldSettingCardStyles.sectionCard,
            marginBottom: 16
          }}
          title={
            <span style={{ fontSize: 18, fontWeight: 500 }}>
              <GlobalOutlined style={{ marginRight: 8 }} />
              Bối cảnh thế giới tiểu thuyết
            </span>
          }
        >
          <div style={{ padding: '16px 0' }}>
            {currentProject.world_time_period && (
              <div style={{ marginBottom: 24 }}>
                <Title level={5} style={{ color: token.colorPrimary, marginBottom: 12 }}>
                  Thiết lập thời gian
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorPrimary}`
                }}>
                  {currentProject.world_time_period}
                </Paragraph>
              </div>
            )}

            {currentProject.world_location && (
              <div style={{ marginBottom: 24 }}>
                <Title level={5} style={{ color: token.colorSuccess, marginBottom: 12 }}>
                  Thiết lập địa điểm
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorSuccess}`
                }}>
                  {currentProject.world_location}
                </Paragraph>
              </div>
            )}

            {currentProject.world_atmosphere && (
              <div style={{ marginBottom: 24 }}>
                <Title level={5} style={{ color: token.colorWarning, marginBottom: 12 }}>
                  Thiết lập không khí
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorWarning}`
                }}>
                  {currentProject.world_atmosphere}
                </Paragraph>
              </div>
            )}

            {currentProject.world_rules && (
              <div style={{ marginBottom: 0 }}>
                <Title level={5} style={{ color: token.colorError, marginBottom: 12 }}>
                  Thiết lập quy tắc
                </Title>
                <Paragraph style={{
                  fontSize: 15,
                  lineHeight: 1.8,
                  padding: 16,
                  background: token.colorBgLayout,
                  borderRadius: 8,
                  borderLeft: `4px solid ${token.colorError}`
                }}>
                  {currentProject.world_rules}
                </Paragraph>
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Chỉnh sửa bối cảnh thế giới模态框 */}
      <Modal
        title="Chỉnh sửa bối cảnh thế giới"
        open={isEditModalVisible}
        centered
        onCancel={() => {
          setIsEditModalVisible(false);
          editForm.resetFields();
        }}
        onOk={async () => {
          try {
            const values = await editForm.validateFields();
            setIsSaving(true);

            const updatedProject = await projectApi.updateProject(currentProject.id, {
              world_time_period: values.world_time_period,
              world_location: values.world_location,
              world_atmosphere: values.world_atmosphere,
              world_rules: values.world_rules,
            });

            setCurrentProject(updatedProject);
            message.success('Cập nhật bối cảnh thế giới thành công');
            setIsEditModalVisible(false);
            editForm.resetFields();
          } catch (error) {
            console.error('Cập nhật bối cảnh thế giới thất bại:', error);
            message.error('Cập nhật thất bại, vui lòng thử lại');
          } finally {
            setIsSaving(false);
          }
        }}
        confirmLoading={isSaving}
        width={800}
        okText="Lưu"
        cancelText="Hủy"
      >
        <Form
          form={editForm}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="Thiết lập thời gian"
            name="world_time_period"
            rules={[{ required: true, message: 'Vui lòng nhập thiết lập thời gian' }]}
          >
            <TextArea
              rows={4}
              placeholder="Mô tả bối cảnh thời đại của câu chuyện..."
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="Thiết lập địa điểm"
            name="world_location"
            rules={[{ required: true, message: 'Vui lòng nhập thiết lập địa điểm' }]}
          >
            <TextArea
              rows={4}
              placeholder="Mô tả vị trí địa lý và môi trường câu chuyện..."
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="Thiết lập không khí"
            name="world_atmosphere"
            rules={[{ required: true, message: 'Vui lòng nhập thiết lập không khí' }]}
          >
            <TextArea
              rows={4}
              placeholder="Mô tả không khí và tông tổng thể của câu chuyện..."
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="Thiết lập quy tắc"
            name="world_rules"
            rules={[{ required: true, message: 'Vui lòng nhập thiết lập quy tắc' }]}
          >
            <TextArea
              rows={4}
              placeholder="Mô tả quy tắc và thiết lập đặc biệt của thế giới này..."
              showCount
              maxLength={1000}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑项目Thông tin cơ bản模态框 */}
      <Modal
        title="Chỉnh sửa thông tin cơ bản dự án"
        open={isEditProjectModalVisible}
        centered
        onCancel={() => {
          setIsEditProjectModalVisible(false);
          editProjectForm.resetFields();
        }}
        onOk={async () => {
          try {
            const values = await editProjectForm.validateFields();
            setIsSavingProject(true);

            const updatedProject = await projectApi.updateProject(currentProject.id, {
              title: values.title,
              description: values.description,
              theme: values.theme,
              genre: values.genre,
              narrative_perspective: values.narrative_perspective,
              target_words: values.target_words,
            });

            setCurrentProject(updatedProject);
            message.success('Cập nhật thông tin cơ bản dự án thành công');
            setIsEditProjectModalVisible(false);
            editProjectForm.resetFields();
          } catch (error) {
            console.error('Cập nhật thông tin cơ bản của dự án thất bại:', error);
            message.error('Cập nhật thất bại, vui lòng thử lại');
          } finally {
            setIsSavingProject(false);
          }
        }}
        confirmLoading={isSavingProject}
        width={800}
        okText="Lưu"
        cancelText="Hủy"
      >
        <Form
          form={editProjectForm}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label="Tên tiểu thuyết"
            name="title"
            rules={[
              { required: true, message: 'Vui lòng nhập tên tiểu thuyết' },
              { max: 200, message: 'Tên không quá 200 chữ' }
            ]}
          >
            <Input
              placeholder="Vui lòng nhập tên tiểu thuyết"
              showCount
              maxLength={200}
            />
          </Form.Item>

          <Form.Item
            label="Tóm tắt tiểu thuyết"
            name="description"
            rules={[
              { max: 1000, message: 'Tóm tắt không quá 1000 chữ' }
            ]}
          >
            <TextArea
              rows={4}
              placeholder="Vui lòng nhập tóm tắt tiểu thuyết (tùy chọn)"
              showCount
              maxLength={1000}
            />
          </Form.Item>

          <Form.Item
            label="Chủ đề tiểu thuyết"
            name="theme"
            rules={[
              { max: 500, message: 'Chủ đề không quá 500 chữ' }
            ]}
          >
            <TextArea
              rows={3}
              placeholder="Vui lòng nhập chủ đề tiểu thuyết (tùy chọn)"
              showCount
              maxLength={500}
            />
          </Form.Item>

          <Form.Item
            label="Thể loại tiểu thuyết"
            name="genre"
            rules={[
              { max: 100, message: 'Loại không quá 100 chữ' }
            ]}
          >
            <Input
              placeholder="Vui lòng nhập thể loại, VD: huyền huyễn, đô thị, khoa học viễn tưởng... (tùy chọn)"
              showCount
              maxLength={100}
            />
          </Form.Item>

          <Form.Item
            label="Góc kể chuyện"
            name="narrative_perspective"
          >
            <Select
              placeholder="Vui lòng chọn góc kể chuyện (tùy chọn)"
              allowClear
              options={[
                { label: 'Ngôi thứ nhất', value: '第一人称' },
                { label: 'Ngôi thứ ba', value: '第三人称' },
                { label: 'Toàn tri', value: '全知视角' }
              ]}
            />
          </Form.Item>

          <Form.Item
            label="Số chữ mục tiêu"
            name="target_words"
            rules={[
              { type: 'number', min: 0, message: 'Số chữ mục tiêu không được âm' },
              { type: 'number', max: 2147483647, message: 'Số chữ mục tiêu ngoài phạm vi' }
            ]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="Vui lòng nhập số chữ mục tiêu (tùy chọn, tối đa 2.1 tỷ)"
              min={0}
              max={2147483647}
              step={1000}
              addonAfter="chữ"
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* AI tạo lại加载遮罩 */}
      <SSELoadingOverlay
        loading={isRegenerating}
        progress={regenerateProgress}
        message={regenerateMessage}
      />

      {/* 预览重新生成的内容模态框 */}
      <Modal
        title="Xem trước bối cảnh thế giới tạo lại"
        open={isPreviewModalVisible}
        centered
        width={900}
        onOk={handleConfirmSave}
        onCancel={handleCancelSave}
        confirmLoading={isSavingPreview}
        okText="Xác nhận thay thế"
        cancelText="Hủy"
        okButtonProps={{ danger: true }}
      >
        {newWorldData && (
          <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
            <div style={{ marginBottom: 24, padding: 16, background: token.colorWarningBg, border: `1px solid ${token.colorWarningBorder}`, borderRadius: 8 }}>
              <Typography.Text type="warning" strong>
                ⚠️ Lưu ý: nhấn "Xác nhận thay thế" sẽ thay thiết lập bối cảnh thế giới hiện tại bằng nội dung mới
              </Typography.Text>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ color: token.colorPrimary, marginBottom: 12 }}>
                Thiết lập thời gian
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorPrimary}`
              }}>
                {newWorldData.time_period}
              </Paragraph>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ color: token.colorSuccess, marginBottom: 12 }}>
                Thiết lập địa điểm
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorSuccess}`
              }}>
                {newWorldData.location}
              </Paragraph>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ color: token.colorWarning, marginBottom: 12 }}>
                Thiết lập không khí
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorWarning}`
              }}>
                {newWorldData.atmosphere}
              </Paragraph>
            </div>

            <div style={{ marginBottom: 0 }}>
              <Title level={5} style={{ color: token.colorError, marginBottom: 12 }}>
                Thiết lập quy tắc
              </Title>
              <Paragraph style={{
                fontSize: 15,
                lineHeight: 1.8,
                padding: 16,
                background: token.colorBgLayout,
                borderRadius: 8,
                borderLeft: `4px solid ${token.colorError}`
              }}>
                {newWorldData.rules}
              </Paragraph>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}