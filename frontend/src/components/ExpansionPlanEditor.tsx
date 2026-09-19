import { Modal, Form, Input, InputNumber, Select, Tag, Space, Button, message, Divider } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useState, useEffect, useCallback } from 'react';
import type { ExpansionPlanData, Character } from '../types';
import { characterApi } from '../services/api';

const { TextArea } = Input;

interface ExpansionPlanEditorProps {
  visible: boolean;
  planData: ExpansionPlanData | null;
  chapterSummary: string | null;
  projectId: string;
  onSave: (data: ExpansionPlanData & { summary?: string }) => Promise<void>;
  onCancel: () => void;
}

export default function ExpansionPlanEditor({
  visible,
  planData,
  chapterSummary,
  projectId,
  onSave,
  onCancel
}: ExpansionPlanEditorProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  
  // 关键事件标签输入
  const [keyEventInput, setKeyEventInput] = useState('');
  const [keyEvents, setKeyEvents] = useState<string[]>([]);
  
  // 角色列表和选择
  const [availableCharacters, setAvailableCharacters] = useState<Character[]>([]);
  const [characters, setCharacters] = useState<string[]>([]);
  const [loadingCharacters, setLoadingCharacters] = useState(false);

  // 加载项目角色列表
  const loadCharacters = useCallback(async () => {
    try {
      setLoadingCharacters(true);
      setAvailableCharacters([]); // 重置为空数组
      const response = await characterApi.getCharacters(projectId);
      console.log('Dữ liệu nhân vật đã tải:', response);
      
      // API返回的是 {total, items} 格式,需要提取items
      let chars: Character[] = [];
      if (Array.isArray(response)) {
        chars = response;
      } else if (response && typeof response === 'object' && 'items' in response) {
        const responseObj = response as { items?: Character[] };
        if (Array.isArray(responseObj.items)) {
          chars = responseObj.items;
        }
      } else {
        console.error('Định dạng API nhân vật trả về không hợp lệ:', response);
        message.warning('Định dạng dữ liệu nhân vật bất thường');
      }
      
      setAvailableCharacters(chars);
      console.log('Danh sách nhân vật đã đặt:', chars);
    } catch (error: unknown) {
      console.error('Tải danh sách nhân vật thất bại:', error);
      setAvailableCharacters([]);
      const err = error as Error;
      message.error('Tải danh sách nhân vật thất bại: ' + (err?.message || 'Lỗi không xác định'));
    } finally {
      setLoadingCharacters(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (visible && projectId) {
      loadCharacters();
    }
  }, [visible, projectId, loadCharacters]);

  // 当planData或chapterSummary变化时更新状态
  useEffect(() => {
    if (visible) {
      if (planData) {
        setKeyEvents(planData.key_events || []);
        setCharacters(planData.character_focus || []);
        form.setFieldsValue({
          summary: chapterSummary || '',
          emotional_tone: planData.emotional_tone,
          narrative_goal: planData.narrative_goal,
          conflict_type: planData.conflict_type,
          estimated_words: planData.estimated_words
        });
      } else {
        // 重置状态
        setKeyEvents([]);
        setCharacters([]);
        form.setFieldsValue({
          summary: chapterSummary || ''
        });
      }
    }
  }, [planData, chapterSummary, form, visible]);

  const handleAddKeyEvent = () => {
    if (keyEventInput.trim()) {
      setKeyEvents([...keyEvents, keyEventInput.trim()]);
      setKeyEventInput('');
    }
  };

  const handleAddCharacter = (characterName: string) => {
    if (characterName && !characters.includes(characterName)) {
      setCharacters([...characters, characterName]);
    }
  };

  const handleSubmit = async () => {
    try {
      setLoading(true);
      const values = await form.validateFields();
      
      // 验证至少有一个关键事件
      if (keyEvents.length === 0) {
        message.warning('Vui lòng thêm ít nhất một sự kiện then chốt');
        setLoading(false);
        return;
      }
      
      // 验证至少有一个角色
      if (characters.length === 0) {
        message.warning('Vui lòng thêm ít nhất một nhân vật liên quan');
        setLoading(false);
        return;
      }
      
      const updatedPlan: ExpansionPlanData & { summary?: string } = {
        summary: values.summary,
        key_events: keyEvents,
        character_focus: characters,
        emotional_tone: values.emotional_tone,
        narrative_goal: values.narrative_goal,
        conflict_type: values.conflict_type,
        estimated_words: values.estimated_words,
        scenes: planData?.scenes || null
      };
      
      await onSave(updatedPlan);
      // message.success('规划信息保存成功');
    } catch (error) {
      console.error('Lưu thất bại:', error);
      message.error('Lưu thất bại, vui lòng thử lại');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    form.resetFields();
    setKeyEvents([]);
    setCharacters([]);
    setKeyEventInput('');
    onCancel();
  };

  return (
    <Modal
      title="Chỉnh sửa kế hoạch chương"
      open={visible}
      onCancel={handleCancel}
      width={700}
      centered
      footer={[
        <Button key="cancel" onClick={handleCancel} disabled={loading}>
          Hủy
        </Button>,
        <Button key="submit" type="primary" loading={loading} onClick={handleSubmit}>
          Lưu
        </Button>
      ]}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          emotional_tone: 'Căng thẳng dữ dội',
          conflict_type: 'Xung đột nhân vật',
          estimated_words: 3000
        }}
      >
        {/* 情节概要 */}
        <Form.Item
          label="Tóm tắt tình tiết"
          name="summary"
          tooltip="Tóm tắt tình tiết chính và hướng câu chuyện của chương"
        >
          <TextArea
            rows={3}
            placeholder="Tóm tắt tình tiết chính của chương, ví dụ: nhân vật chính gặp sự cố, bắt đầu cuộc phiêu lưu mới..."
            maxLength={500}
            showCount
          />
        </Form.Item>

        <Divider orientation="left">Kế hoạch chi tiết</Divider>

        {/* 关键事件 */}
        <Form.Item
          label="Sự kiện then chốt"
          tooltip="Thêm ít nhất một sự kiện then chốt"
          required
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                placeholder="Nhập sự kiện then chốt rồi Enter hoặc nhấn thêm"
                value={keyEventInput}
                onChange={(e) => setKeyEventInput(e.target.value)}
                onPressEnter={handleAddKeyEvent}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleAddKeyEvent}
              >
                Thêm
              </Button>
            </Space.Compact>
            <Space wrap>
              {keyEvents.map((event, idx) => (
                <Tag
                  key={idx}
                  closable
                  onClose={(e) => {
                    e.preventDefault();
                    setKeyEvents(keyEvents.filter((_, i) => i !== idx));
                  }}
                  color="purple"
                  style={{ marginBottom: 8 }}
                >
                  <span style={{ fontWeight: 'bold', marginRight: 4 }}>#{idx + 1}</span>
                  {event}
                </Tag>
              ))}
            </Space>
          </Space>
        </Form.Item>

        {/* 涉及角色 */}
        <Form.Item
          label="Nhân vật liên quan"
          tooltip="Chọn từ nhân vật hiện có của dự án"
          required
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <Select
              placeholder="Chọn nhân vật"
              style={{ width: '100%' }}
              loading={loadingCharacters}
              onChange={handleAddCharacter}
              value={undefined}
              showSearch
              optionFilterProp="children"
              filterOption={(input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
              options={Array.isArray(availableCharacters)
                ? availableCharacters
                    .filter(char => !characters.includes(char.name))
                    .map(char => ({
                      label: char.name,
                      value: char.name,
                    }))
                : []}
              notFoundContent={
                loadingCharacters ? 'Đang tải...' :
                !Array.isArray(availableCharacters) ? 'Tải nhân vật thất bại' :
                availableCharacters.length === 0 ? 'Chưa có nhân vật, hãy tạo trong quản lý nhân vật trước' :
                'Đã thêm mọi nhân vật'
              }
            />
            <Space wrap>
              {characters.map((char, idx) => (
                <Tag
                  key={idx}
                  closable
                  onClose={() => setCharacters(characters.filter((_, i) => i !== idx))}
                  color="cyan"
                >
                  {char}
                </Tag>
              ))}
            </Space>
          </Space>
        </Form.Item>

        {/* 情感基调 */}
        <Form.Item
          label="Sắc thái cảm xúc"
          name="emotional_tone"
          rules={[{ required: true, message: 'Vui lòng nhập sắc thái cảm xúc' }]}
          tooltip="Ví dụ: căng thẳng dữ dội, ấm áp cảm động, hồi hộp kinh dị..."
        >
          <Input
            placeholder="Nhập sắc thái cảm xúc, ví dụ: căng thẳng dữ dội, ấm áp cảm động..."
            maxLength={20}
          />
        </Form.Item>

        {/* 冲突类型 */}
        <Form.Item
          label="Loại xung đột"
          name="conflict_type"
          rules={[{ required: true, message: 'Vui lòng nhập loại xung đột' }]}
          tooltip="Ví dụ: xung đột nhân vật, xung đột nội tâm, xung đột môi trường..."
        >
          <Input
            placeholder="Nhập loại xung đột, ví dụ: xung đột nhân vật, xung đột nội tâm..."
            maxLength={20}
          />
        </Form.Item>

        {/* 预估字数 */}
        <Form.Item
          label="Số chữ ước tính"
          name="estimated_words"
          rules={[{ required: true, message: 'Vui lòng nhập số chữ ước tính' }]}
        >
          <InputNumber
            min={500}
            max={10000}
            step={100}
            style={{ width: '100%' }}
            formatter={(value) => `${value} chữ`}
            parser={(value) => Number(value?.replace(' chữ', '')) as 500 | 10000}
          />
        </Form.Item>

        {/* 叙事目标 */}
        <Form.Item
          label="Mục tiêu kể chuyện"
          name="narrative_goal"
          rules={[{ required: true, message: 'Vui lòng nhập mục tiêu kể chuyện' }]}
        >
          <TextArea
            rows={3}
            placeholder="Mô tả mục tiêu kể chuyện của chương, ví dụ: đẩy tuyến chính, đào sâu quan hệ nhân vật, tiết lộ thông tin quan trọng..."
            maxLength={500}
            showCount
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}