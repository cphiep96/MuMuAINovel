import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Table, Tag, Button, Space, message, Modal, Form, Select, Slider, Input, Tabs, AutoComplete, theme } from 'antd';
import { PlusOutlined, ApartmentOutlined, UserOutlined, EditOutlined } from '@ant-design/icons';
import { useStore } from '../store';
import axios from 'axios';

const { TextArea } = Input;

interface Relationship {
  id: string;
  character_from_id: string;
  character_to_id: string;
  relationship_name: string;
  intimacy_level: number;
  status: string;
  description?: string;
  source: string;
}

interface RelationshipType {
  id: number;
  name: string;
  category: string;
  reverse_name?: string;
  icon?: string;
}

interface Character {
  id: string;
  name: string;
  is_organization: boolean;
}

export default function Relationships() {
  const { projectId } = useParams<{ projectId: string }>();
  const { currentProject } = useStore();
  const navigate = useNavigate();
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [relationshipTypes, setRelationshipTypes] = useState<RelationshipType[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);
  const [editingRelationship, setEditingRelationship] = useState<Relationship | null>(null);
  const [form] = Form.useForm();
  const [modal, contextHolder] = Modal.useModal();
  const { token } = theme.useToken();
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [pageSize, setPageSize] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (projectId) {
      loadData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [relsRes, typesRes, charsRes] = await Promise.all([
        axios.get(`/api/relationships/project/${projectId}`),
        axios.get('/api/relationships/types'),
        axios.get(`/api/characters?project_id=${projectId}`)
      ]);

      setRelationships(relsRes.data);
      setRelationshipTypes(typesRes.data);
      setCharacters(charsRes.data.items || []);
    } catch (error) {
      message.error('Tải dữ liệu thất bại');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateRelationship = async (values: {
    character_from_id: string;
    character_to_id: string;
    relationship_name: string;
    intimacy_level: number;
    status: string;
    description?: string;
  }) => {
    try {
      await axios.post('/api/relationships/', {
        project_id: projectId,
        ...values
      });
      message.success('Tạo quan hệ thành công');
      setIsModalOpen(false);
      form.resetFields();
      loadData();
    } catch (error) {
      message.error('Tạo quan hệ thất bại');
      console.error(error);
    }
  };

  const handleEditRelationship = (record: Relationship) => {
    setEditingRelationship(record);
    setIsEditMode(true);
    form.setFieldsValue({
      character_from_id: record.character_from_id,
      character_to_id: record.character_to_id,
      relationship_name: record.relationship_name,
      intimacy_level: record.intimacy_level,
      status: record.status,
      description: record.description,
    });
    setIsModalOpen(true);
  };

  const handleUpdateRelationship = async (values: {
    character_from_id: string;
    character_to_id: string;
    relationship_name: string;
    intimacy_level: number;
    status: string;
    description?: string;
  }) => {
    if (!editingRelationship) return;

    try {
      await axios.put(`/api/relationships/${editingRelationship.id}`, {
        relationship_name: values.relationship_name,
        intimacy_level: values.intimacy_level,
        status: values.status,
        description: values.description,
      });
      message.success('Cập nhật quan hệ thành công');
      setIsModalOpen(false);
      setIsEditMode(false);
      setEditingRelationship(null);
      form.resetFields();
      loadData();
    } catch (error) {
      message.error('Cập nhật quan hệ thất bại');
      console.error(error);
    }
  };

  const handleDeleteRelationship = async (id: string) => {
    modal.confirm({
      title: 'Xác nhận xóa',
      content: 'Xác nhận xóa quan hệ này?',
      centered: true,
      okText: 'Xóa',
      okType: 'danger',
      cancelText: 'Hủy',
      onOk: async () => {
        try {
          await axios.delete(`/api/relationships/${id}`);
          message.success('Xóa quan hệ thành công');
          loadData();
        } catch (error) {
          message.error('Xóa thất bại');
          console.error(error);
        }
      }
    });
  };

  const getCharacterName = (id: string) => {
    const char = characters.find(c => c.id === id);
    return char?.name || 'Không rõ';
  };

  const getIntimacyColor = (level: number) => {
    if (level >= 75) return 'green';
    if (level >= 50) return 'blue';
    if (level >= 25) return 'orange';
    if (level >= 0) return 'volcano';
    return 'red';
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      active: 'green',
      broken: 'red',
      past: 'default',
      complicated: 'orange'
    };
    return colors[status] || 'default';
  };

  const getCategoryColor = (category: string) => {
    const colors: Record<string, string> = {
      family: 'magenta',
      social: 'blue',
      hostile: 'red',
      professional: 'cyan'
    };
    return colors[category] || 'default';
  };

  const columns = [
    {
      title: 'Nhân vật A',
      dataIndex: 'character_from_id',
      key: 'from',
      render: (id: string) => (
        <Tag icon={<UserOutlined />} color="blue">
          {getCharacterName(id)}
        </Tag>
      ),
      width: 120,
    },
    {
      title: 'Quan hệ',
      dataIndex: 'relationship_name',
      key: 'relationship',
      render: (name: string) => <strong>{name}</strong>,
      width: 120,
    },
    {
      title: 'Nhân vật B',
      dataIndex: 'character_to_id',
      key: 'to',
      render: (id: string) => (
        <Tag icon={<UserOutlined />} color="purple">
          {getCharacterName(id)}
        </Tag>
      ),
      width: 120,
    },
    {
      title: 'Độ thân thiết',
      dataIndex: 'intimacy_level',
      key: 'intimacy',
      render: (level: number) => (
        <Tag color={getIntimacyColor(level)}>{level}</Tag>
      ),
      width: 80,
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{status}</Tag>
      ),
      width: 80,
    },
    {
      title: 'Nguồn',
      dataIndex: 'source',
      key: 'source',
      render: (source: string) => (
        <Tag>{source === 'ai' ? 'AI tạo' : 'Tạo thủ công'}</Tag>
      ),
      width: 100,
    },
    {
      title: 'Thao tác',
      key: 'action',
      render: (_: unknown, record: Relationship) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEditRelationship(record)}
          >
            Chỉnh sửa
          </Button>
          <Button
            type="link"
            danger
            size="small"
            onClick={() => handleDeleteRelationship(record.id)}
          >
            Xóa
          </Button>
        </Space>
      ),
      width: 140,
      fixed: isMobile ? ('right' as const) : undefined,
    },
  ];

  // 按类别分组关系类型
  const groupedTypes = relationshipTypes.reduce((acc, type) => {
    if (!acc[type.category]) {
      acc[type.category] = [];
    }
    acc[type.category].push(type);
    return acc;
  }, {} as Record<string, RelationshipType[]>);

  const categoryLabels: Record<string, string> = {
    family: 'Quan hệ gia tộc',
    social: 'Quan hệ xã hội',
    professional: 'Quan hệ nghề nghiệp',
    hostile: 'Quan hệ thù địch'
  };

  return (
    <>
      {contextHolder}
      <div>
        <Card
        title={
          <Space wrap>
            <ApartmentOutlined />
            <span style={{ fontSize: isMobile ? 14 : 16 }}>Quản lý quan hệ</span>
            {!isMobile && <Tag color="blue">{currentProject?.title}</Tag>}
          </Space>
        }
        extra={
          <Space>
            <Button
              onClick={() => projectId && navigate(`/project/${projectId}/relationships-graph`)}
              size={isMobile ? 'small' : 'middle'}
            >
              Sơ đồ quan hệ
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setIsModalOpen(true)}
              size={isMobile ? 'small' : 'middle'}
            >
              {isMobile ? 'Thêm' : 'Thêm quan hệ'}
            </Button>
          </Space>
        }
      >
        <Tabs
          items={[
            {
              key: 'list',
              label: `Danh sách quan hệ (${relationships.length})`,
              children: (
                <Table
                  columns={columns}
                  dataSource={relationships}
                  rowKey="id"
                  loading={loading}
                  pagination={{
                    current: currentPage,
                    pageSize: isMobile ? 10 : pageSize,
                    pageSizeOptions: ['10', '20', '50', '100'],
                    position: ['bottomCenter'],
                    showSizeChanger: !isMobile,
                    showQuickJumper: !isMobile,
                    showTotal: (total) => `Tổng ${total} mục`,
                    simple: isMobile,
                    onChange: (page, size) => {
                      setCurrentPage(page);
                      if (size !== pageSize) {
                        setPageSize(size);
                        setCurrentPage(1);
                      }
                    },
                    onShowSizeChange: (_, size) => {
                      setPageSize(size);
                      setCurrentPage(1);
                    }
                  }}
                  scroll={{
                    x: 700,
                    y: isMobile ? 'calc(100vh - 360px)' : 'calc(100vh - 440px)'
                  }}
                  size={isMobile ? 'small' : 'middle'}
                />
              ),
            },
            {
              key: 'types',
              label: `Loại quan hệ (${relationshipTypes.length})`,
              children: (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(200px, 1fr))',
                  gap: isMobile ? '12px' : '16px',
                  maxHeight: isMobile ? 'calc(100vh - 400px)' : 'calc(100vh - 350px)',
                  overflow: 'auto'
                }}>
                  {Object.entries(groupedTypes).map(([category, types]) => (
                    <Card
                      key={category}
                      size="small"
                      title={categoryLabels[category] || category}
                      headStyle={{ backgroundColor: token.colorFillAlter }}
                    >
                      <Space direction="vertical" style={{ width: '100%' }}>
                        {types.map(type => (
                          <Tag key={type.id} color={getCategoryColor(category)}>
                            {type.icon} {type.name}
                            {type.reverse_name && ` ↔ ${type.reverse_name}`}
                          </Tag>
                        ))}
                      </Space>
                    </Card>
                  ))}
                </div>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={isEditMode ? 'Chỉnh sửa quan hệ' : 'Thêm quan hệ'}
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setIsEditMode(false);
          setEditingRelationship(null);
          form.resetFields();
        }}
        footer={null}
        centered={!isMobile}
        width={isMobile ? '100%' : 600}
        style={isMobile ? { top: 0, paddingBottom: 0, maxWidth: '100vw' } : undefined}
        styles={isMobile ? { body: { maxHeight: 'calc(100vh - 110px)', overflowY: 'auto' } } : undefined}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={isEditMode ? handleUpdateRelationship : handleCreateRelationship}
        >
          <Form.Item
            name="character_from_id"
            label="Nhân vật A"
            rules={[{ required: true, message: 'Vui lòng chọn nhân vật A' }]}
          >
            <Select
              placeholder="Chọn nhân vật"
              showSearch
              disabled={isEditMode}
              filterOption={(input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
              options={characters
                .filter(c => !c.is_organization)
                .map(c => ({ label: c.name, value: c.id }))}
            />
          </Form.Item>

          <Form.Item
            name="relationship_name"
            label="Loại quan hệ"
            rules={[{ required: true, message: 'Vui lòng chọn hoặc nhập loại quan hệ' }]}
          >
            <AutoComplete
              placeholder="Chọn loại có sẵn hoặc nhập quan hệ tùy chỉnh"
              options={relationshipTypes.map(t => ({
                label: `${t.icon || ''} ${t.name} (${categoryLabels[t.category]})`,
                value: t.name
              }))}
              filterOption={(inputValue, option) =>
                option!.value.toUpperCase().indexOf(inputValue.toUpperCase()) !== -1
              }
            />
          </Form.Item>

          <Form.Item
            name="character_to_id"
            label="Nhân vật B"
            rules={[{ required: true, message: 'Vui lòng chọn nhân vật B' }]}
          >
            <Select
              placeholder="Chọn nhân vật"
              showSearch
              disabled={isEditMode}
              filterOption={(input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
              options={characters
                .filter(c => !c.is_organization)
                .map(c => ({ label: c.name, value: c.id }))}
            />
          </Form.Item>

          <Form.Item
            name="intimacy_level"
            label="Độ thân thiết"
            initialValue={50}
          >
            <Slider
              min={-100}
              max={100}
              marks={{
                '-100': '-100',
                '-50': '-50',
                0: '0',
                50: '50',
                100: '100'
              }}
            />
          </Form.Item>

          <Form.Item
            name="status"
            label="Trạng thái"
            initialValue="active"
          >
            <Select>
              <Select.Option value="active">Đang hoạt động</Select.Option>
              <Select.Option value="broken">Đã đứt</Select.Option>
              <Select.Option value="past">Quá khứ</Select.Option>
              <Select.Option value="complicated">Phức tạp</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item name="description" label="Mô tả quan hệ">
            <TextArea rows={3} placeholder="Mô tả chi tiết quan hệ này..." />
          </Form.Item>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => {
                setIsModalOpen(false);
                setIsEditMode(false);
                setEditingRelationship(null);
                form.resetFields();
              }}>Hủy</Button>
              <Button type="primary" htmlType="submit">
                {isEditMode ? 'Cập nhật' : 'Tạo'}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
      </div>
    </>
  );
}
