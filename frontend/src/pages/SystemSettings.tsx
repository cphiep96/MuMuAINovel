import { useCallback, useEffect, useState } from 'react';
import dayjs, { Dayjs } from 'dayjs';
import { Alert, Button, Card, Col, DatePicker, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Spin, Switch, Table, Tag, Tabs, Typography, message, theme } from 'antd';
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';
import { BellOutlined, CheckCircleOutlined, DeleteOutlined, EditOutlined, EyeInvisibleOutlined, MailOutlined, PlusOutlined, ReloadOutlined, SaveOutlined, SendOutlined, SettingOutlined } from '@ant-design/icons';
import { announcementApi, authApi, settingsApi } from '../services/api';
import type { Announcement, AnnouncementCreate, AnnouncementLevel, AnnouncementStatus, AnnouncementStatusResponse, AnnouncementUpdate, SystemSMTPSettings, SystemSMTPSettingsUpdate, User } from '../types';
import MarkdownRenderer from '../components/MarkdownRenderer';

const { Title, Text, Paragraph } = Typography;
const { Option } = Select;
const { TextArea, Search } = Input;

const qqDefaults: Pick<SystemSMTPSettings, 'smtp_provider' | 'smtp_host' | 'smtp_port' | 'smtp_use_ssl' | 'smtp_use_tls'> = {
  smtp_provider: 'qq',
  smtp_host: 'smtp.qq.com',
  smtp_port: 465,
  smtp_use_ssl: true,
  smtp_use_tls: false,
};

const announcementLevelText: Record<AnnouncementLevel, string> = {
  info: 'Thông báo',
  success: 'Thành công',
  warning: 'Cảnh báo',
  error: 'Quan trọng',
};

const announcementLevelColor: Record<AnnouncementLevel, string> = {
  info: 'blue',
  success: 'green',
  warning: 'orange',
  error: 'red',
};

const announcementStatusText: Record<AnnouncementStatus, string> = {
  draft: 'Bản nháp',
  published: 'Đã đăng',
  hidden: 'Đã ẩn',
};

const announcementStatusColor: Record<AnnouncementStatus, string> = {
  draft: 'default',
  published: 'green',
  hidden: 'red',
};

type AnnouncementStatusFilter = AnnouncementStatus | 'all';

interface AnnouncementFormValues {
  title: string;
  content: string;
  summary?: string;
  level: AnnouncementLevel;
  status: AnnouncementStatus;
  pinned?: boolean;
  publish_at?: Dayjs | null;
  expire_at?: Dayjs | null;
}

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return '-';
  }
  return dayjs(value).format('YYYY-MM-DD HH:mm');
};

const toIsoStringOrNull = (value?: Dayjs | null) => {
  if (!value) {
    return null;
  }
  return value.toISOString();
};

export default function SystemSettingsPage() {
  const { token } = theme.useToken();
  const [form] = Form.useForm<SystemSMTPSettingsUpdate>();
  const [announcementForm] = Form.useForm<AnnouncementFormValues>();
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testTargetEmail, setTestTargetEmail] = useState('');
  const [announcementStatus, setAnnouncementStatus] = useState<AnnouncementStatusResponse | null>(null);
  const [announcementStatusLoading, setAnnouncementStatusLoading] = useState(false);
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [announcementLoading, setAnnouncementLoading] = useState(false);
  const [announcementSaving, setAnnouncementSaving] = useState(false);
  const [announcementModalOpen, setAnnouncementModalOpen] = useState(false);
  const [editingAnnouncement, setEditingAnnouncement] = useState<Announcement | null>(null);
  const [announcementStatusFilter, setAnnouncementStatusFilter] = useState<AnnouncementStatusFilter>('all');
  const [announcementSearchKeyword, setAnnouncementSearchKeyword] = useState('');
  const [announcementPagination, setAnnouncementPagination] = useState({ current: 1, pageSize: 10, total: 0 });
  const { current: announcementCurrentPage, pageSize: announcementPageSize } = announcementPagination;

  const announcementContent = Form.useWatch('content', announcementForm) || '';

  const pageBackground = `linear-gradient(180deg, ${token.colorBgLayout} 0%, ${token.colorFillSecondary} 100%)`;
  const headerBackground = `linear-gradient(135deg, ${token.colorPrimary} 0%, ${token.colorPrimaryHover} 100%)`;
  const footerSafeOffset = 88;
  const announcementAdminAvailable = announcementStatus?.mode === 'server';

  const loadAnnouncementStatus = useCallback(async () => {
    setAnnouncementStatusLoading(true);
    try {
      const status = await announcementApi.getStatus();
      setAnnouncementStatus(status);
      return status;
    } catch (error) {
      console.error('Tải trạng thái dịch vụ thông báo thất bại:', error);
      message.error('Tải trạng thái dịch vụ thông báo thất bại');
      return null;
    } finally {
      setAnnouncementStatusLoading(false);
    }
  }, []);

  const loadAnnouncements = useCallback(async (page: number, pageSize: number, keyword: string) => {
    if (!announcementAdminAvailable) {
      setAnnouncements([]);
      setAnnouncementPagination(prev => ({ ...prev, total: 0 }));
      return;
    }

    setAnnouncementLoading(true);
    try {
      const result = await announcementApi.adminList({
        status: announcementStatusFilter,
        q: keyword.trim() || undefined,
        page,
        limit: pageSize,
        include_expired: true,
      });
      setAnnouncements(result.data?.items || []);
      setAnnouncementPagination({
        current: result.data?.page || page,
        pageSize: result.data?.limit || pageSize,
        total: result.data?.total || 0,
      });
    } catch (error) {
      console.error('Tải danh sách thông báo thất bại:', error);
      message.error('Tải danh sách thông báo thất bại, vui lòng xác nhận instance hiện tại là chế độ máy chủ và tài khoản có quyền quản trị viên');
    } finally {
      setAnnouncementLoading(false);
    }
  }, [announcementAdminAvailable, announcementStatusFilter]);

  const loadData = async () => {
    setInitialLoading(true);
    try {
      const [user, smtpSettings, status] = await Promise.all([
        authApi.getCurrentUser(),
        settingsApi.getSystemSMTPSettings(),
        announcementApi.getStatus().catch(() => null),
      ]);
      setCurrentUser(user);
      setAnnouncementStatus(status);
      form.setFieldsValue(smtpSettings);
    } catch (error) {
      console.error('Tải cài đặt hệ thống thất bại:', error);
      message.error('Tải cài đặt hệ thống thất bại');
    } finally {
      setInitialLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (currentUser?.is_admin && announcementAdminAvailable) {
      void loadAnnouncements(announcementCurrentPage, announcementPageSize, announcementSearchKeyword);
    }
    if (currentUser?.is_admin && announcementStatus && !announcementAdminAvailable) {
      setAnnouncements([]);
      setAnnouncementPagination(prev => ({ ...prev, total: 0 }));
    }
  }, [currentUser?.is_admin, announcementAdminAvailable, announcementStatus, announcementStatusFilter, loadAnnouncements, announcementCurrentPage, announcementPageSize, announcementSearchKeyword]);

  const handleProviderChange = (value: string) => {
    if (value === 'qq') {
      form.setFieldsValue(qqDefaults);
    }
  };

  const handleSave = async (values: SystemSMTPSettingsUpdate) => {
    setSaving(true);
    try {
      const payload = values.smtp_provider === 'qq'
        ? {
            ...values,
            ...qqDefaults,
            smtp_username: values.smtp_username,
            smtp_password: values.smtp_password,
            smtp_from_email: values.smtp_from_email,
            smtp_from_name: values.smtp_from_name,
            email_auth_enabled: values.email_auth_enabled,
            email_register_enabled: values.email_register_enabled,
            verification_code_ttl_minutes: values.verification_code_ttl_minutes,
            verification_resend_interval_seconds: values.verification_resend_interval_seconds,
          }
        : values;
      const result = await settingsApi.updateSystemSMTPSettings(payload);
      form.setFieldsValue(result);
      message.success('Đã lưu cài đặt SMTP hệ thống');
    } catch (error) {
      console.error('Lưu cài đặt hệ thống thất bại:', error);
      message.error('Lưu cài đặt hệ thống thất bại');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    const toEmail = testTargetEmail.trim();
    if (!toEmail) {
      message.warning('Vui lòng nhập email nhận thử nghiệm trước');
      return;
    }

    setTesting(true);
    try {
      const result = await settingsApi.testSystemSMTPSettings({ to_email: toEmail });
      if (result.success) {
        message.success(result.message);
      } else {
        message.error(result.message || 'Kiểm tra SMTP thất bại');
      }
    } catch (error) {
      console.error('Kiểm tra cấu hình SMTP thất bại:', error);
      message.error('Kiểm tra cấu hình SMTP thất bại');
    } finally {
      setTesting(false);
    }
  };

  const openCreateAnnouncementModal = () => {
    if (!announcementAdminAvailable) {
      message.warning('Chỉ có thể đăng thông báo ở chế độ máy chủ');
      return;
    }
    setEditingAnnouncement(null);
    announcementForm.setFieldsValue({
      title: '',
      summary: '',
      content: '',
      level: 'info',
      status: 'published',
      pinned: false,
      publish_at: dayjs(),
      expire_at: null,
    });
    setAnnouncementModalOpen(true);
  };

  const openEditAnnouncementModal = (announcement: Announcement) => {
    setEditingAnnouncement(announcement);
    announcementForm.setFieldsValue({
      title: announcement.title,
      summary: announcement.summary || '',
      content: announcement.content,
      level: announcement.level,
      status: announcement.status || 'published',
      pinned: announcement.pinned,
      publish_at: announcement.publish_at ? dayjs(announcement.publish_at) : null,
      expire_at: announcement.expire_at ? dayjs(announcement.expire_at) : null,
    });
    setAnnouncementModalOpen(true);
  };

  const closeAnnouncementModal = () => {
    setAnnouncementModalOpen(false);
    setEditingAnnouncement(null);
    announcementForm.resetFields();
  };

  const validateAnnouncementWindow = (values: AnnouncementFormValues) => {
    if (values.publish_at && values.expire_at && !values.expire_at.isAfter(values.publish_at)) {
      message.warning('Thời gian hết hạn phải sau thời gian đăng');
      return false;
    }
    return true;
  };

  const appendMarkdownSnippet = (snippet: string) => {
    const currentContent = announcementForm.getFieldValue('content') || '';
    const separator = currentContent && !currentContent.endsWith('\n') ? '\n\n' : '';
    announcementForm.setFieldsValue({ content: `${currentContent}${separator}${snippet}` });
  };

  const buildAnnouncementCreatePayload = (values: AnnouncementFormValues): AnnouncementCreate => {
    const publishAt = toIsoStringOrNull(values.publish_at);
    const expireAt = toIsoStringOrNull(values.expire_at);
    const payload: AnnouncementCreate = {
      title: values.title.trim(),
      content: values.content.trim(),
      summary: values.summary?.trim() || undefined,
      level: values.level,
      status: values.status,
      pinned: Boolean(values.pinned),
    };

    if (publishAt) {
      payload.publish_at = publishAt;
    }
    if (expireAt) {
      payload.expire_at = expireAt;
    }

    return payload;
  };

  const buildAnnouncementUpdatePayload = (values: AnnouncementFormValues): AnnouncementUpdate => ({
    title: values.title.trim(),
    content: values.content.trim(),
    summary: values.summary?.trim() || undefined,
    level: values.level,
    status: values.status,
    pinned: Boolean(values.pinned),
    publish_at: toIsoStringOrNull(values.publish_at),
    expire_at: toIsoStringOrNull(values.expire_at),
  });

  const handleSaveAnnouncement = async (values: AnnouncementFormValues) => {
    if (!validateAnnouncementWindow(values)) {
      return;
    }

    setAnnouncementSaving(true);
    try {
      if (editingAnnouncement) {
        await announcementApi.adminUpdate(editingAnnouncement.id, buildAnnouncementUpdatePayload(values));
        message.success('Đã cập nhật thông báo');
      } else {
        await announcementApi.adminCreate(buildAnnouncementCreatePayload(values));
        message.success('Đã tạo thông báo');
      }
      closeAnnouncementModal();
      await loadAnnouncements(announcementPagination.current, announcementPagination.pageSize, announcementSearchKeyword);
    } catch (error) {
      console.error('Lưu thông báo thất bại:', error);
      message.error('Lưu thông báo thất bại, vui lòng xác nhận instance hiện tại là chế độ máy chủ và tài khoản có quyền quản trị viên');
    } finally {
      setAnnouncementSaving(false);
    }
  };

  const handleDeleteAnnouncement = async (announcementId: string) => {
    try {
      await announcementApi.adminDelete(announcementId);
      message.success('Đã xóa thông báo');
      await loadAnnouncements(announcementPagination.current, announcementPagination.pageSize, announcementSearchKeyword);
    } catch (error) {
      console.error('Xóa thông báo thất bại:', error);
      message.error('Xóa thông báo thất bại');
    }
  };

  const handleAnnouncementStatusChange = async (announcementId: string, action: 'publish' | 'hide') => {
    try {
      if (action === 'publish') {
        await announcementApi.adminPublish(announcementId);
        message.success('Đã đăng thông báo');
      } else {
        await announcementApi.adminHide(announcementId);
        message.success('Đã ẩn thông báo');
      }
      await loadAnnouncements(announcementPagination.current, announcementPagination.pageSize, announcementSearchKeyword);
    } catch (error) {
      console.error('Cập nhật trạng thái thông báo thất bại:', error);
      message.error('Cập nhật trạng thái thông báo thất bại');
    }
  };

  const handleAnnouncementSearch = (value: string) => {
    const keyword = value.trim();
    setAnnouncementSearchKeyword(keyword);
    setAnnouncementPagination(prev => ({ ...prev, current: 1 }));
    void loadAnnouncements(1, announcementPagination.pageSize, keyword);
  };

  const handleAnnouncementTableChange = (pagination: TablePaginationConfig) => {
    const nextPage = pagination.current || 1;
    const nextPageSize = pagination.pageSize || announcementPagination.pageSize;
    void loadAnnouncements(nextPage, nextPageSize, announcementSearchKeyword);
  };

  const announcementColumns: ColumnsType<Announcement> = [
    {
      title: 'Tiêu đề',
      dataIndex: 'title',
      key: 'title',
      width: 240,
      render: (title: string, record) => (
        <Space direction="vertical" size={4}>
          <Space size={6} wrap>
            <Text strong>{title}</Text>
            {record.pinned && <Tag color="gold">Ghim</Tag>}
          </Space>
          {record.summary && <Text type="secondary" style={{ fontSize: 12 }}>{record.summary}</Text>}
        </Space>
      ),
    },
    {
      title: 'Mức độ',
      dataIndex: 'level',
      key: 'level',
      width: 100,
      render: (level: AnnouncementLevel) => <Tag color={announcementLevelColor[level]}>{announcementLevelText[level]}</Tag>,
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status?: AnnouncementStatus) => {
        const currentStatus = status || 'published';
        return <Tag color={announcementStatusColor[currentStatus]}>{announcementStatusText[currentStatus]}</Tag>;
      },
    },
    {
      title: 'Thời gian đăng',
      dataIndex: 'publish_at',
      key: 'publish_at',
      width: 150,
      render: (value?: string | null) => <Text type="secondary">{formatDateTime(value)}</Text>,
    },
    {
      title: 'Thời gian hết hạn',
      dataIndex: 'expire_at',
      key: 'expire_at',
      width: 150,
      render: (value?: string | null) => <Text type="secondary">{formatDateTime(value)}</Text>,
    },
    {
      title: 'Tác giả',
      dataIndex: 'author_name',
      key: 'author_name',
      width: 120,
      render: (value?: string | null) => value || '-',
    },
    {
      title: 'Thao tác',
      key: 'actions',
      fixed: 'right',
      width: 240,
      render: (_, record) => {
        const currentStatus = record.status || 'published';
        return (
          <Space size="small" wrap>
            <Button size="small" icon={<EditOutlined />} disabled={!announcementAdminAvailable} onClick={() => openEditAnnouncementModal(record)}>
              Chỉnh sửa
            </Button>
            {currentStatus !== 'published' ? (
              <Button size="small" type="primary" icon={<SendOutlined />} disabled={!announcementAdminAvailable} onClick={() => void handleAnnouncementStatusChange(record.id, 'publish')}>
                Đăng
              </Button>
            ) : (
              <Button size="small" icon={<EyeInvisibleOutlined />} disabled={!announcementAdminAvailable} onClick={() => void handleAnnouncementStatusChange(record.id, 'hide')}>
                Ẩn
              </Button>
            )}
            <Popconfirm
              title="Xóa thông báo"
              description="Sau khi xóa, máy khách sẽ không đồng bộ thông báo này nữa, xác nhận xóa?"
              okText="Xóa"
              cancelText="Hủy"
              okButtonProps={{ danger: true }}
              onConfirm={() => void handleDeleteAnnouncement(record.id)}
              disabled={!announcementAdminAvailable}
            >
              <Button size="small" danger icon={<DeleteOutlined />} disabled={!announcementAdminAvailable}>
                Xóa
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  if (initialLoading) {
    return (
      <div style={{ minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: token.colorBgLayout }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!currentUser?.is_admin) {
    return (
      <div style={{ padding: 24 }}>
        <Alert type="error" showIcon message="Không có quyền truy cập" description="Chỉ quản trị viên mới có thể truy cập cài đặt hệ thống." />
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: `calc(100vh - ${footerSafeOffset}px)`,
        boxSizing: 'border-box',
        background: pageBackground,
        padding: 24,
        paddingBottom: footerSafeOffset,
      }}
    >
      <div style={{ maxWidth: 1400, margin: '0 auto', width: '100%' }}>
      <Card
        bordered={false}
        style={{
          marginBottom: 24,
          borderRadius: 20,
          overflow: 'hidden',
          boxShadow: `0 12px 32px ${token.colorFillSecondary}`,
        }}
        bodyStyle={{ padding: 0 }}
      >
        <div style={{ background: headerBackground, padding: '28px 32px', color: '#fff' }}>
          <Space direction="vertical" size={6}>
            <Space>
              <SettingOutlined />
              <Title level={3} style={{ color: '#fff', margin: 0 }}>Cài đặt hệ thống</Title>
            </Space>
            <Paragraph style={{ color: 'rgba(255,255,255,0.88)', margin: 0 }}>
              Chỉ quản trị viên có thể xem, dùng để duy trì khả năng gửi thư SMTP, tham số đăng ký bằng email và việc đăng thông báo phía máy chủ.
            </Paragraph>
          </Space>
        </div>
      </Card>

      <Tabs
        defaultActiveKey="smtp"
        items={[
          {
            key: 'smtp',
            label: (
              <Space>
                <MailOutlined />
                Cấu hình SMTP
              </Space>
            ),
            children: (
              <Form form={form} layout="vertical" onFinish={handleSave}>
                <Row gutter={24}>
                  <Col xs={24} xl={16}>
                    <Card title="Cấu hình dịch vụ email" bordered={false} style={{ borderRadius: 16 }}>
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 20 }}
                        message="Hướng dẫn cấu hình email QQ"
                        description="Nếu chọn email QQ, vui lòng dùng địa chỉ email QQ đầy đủ làm tên đăng nhập, mục mật khẩu điền mã ủy quyền SMTP chứ không phải mật khẩu đăng nhập QQ. Mặc định khuyến nghị smtp.qq.com + SSL 465."
                      />

                      <Row gutter={16}>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_provider" label="Nhà cung cấp dịch vụ email" rules={[{ required: true, message: 'Vui lòng chọn nhà cung cấp dịch vụ email' }]}>
                            <Select onChange={handleProviderChange}>
                              <Option value="qq">Email QQ</Option>
                              <Option value="custom">SMTP tùy chỉnh</Option>
                            </Select>
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_host" label="Máy chủ SMTP" rules={[{ required: true, message: 'Vui lòng nhập máy chủ SMTP' }]}>
                            <Input placeholder="Ví dụ: smtp.qq.com" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_port" label="Cổng SMTP" rules={[{ required: true, message: 'Vui lòng nhập cổng SMTP' }]}>
                            <InputNumber style={{ width: '100%' }} min={1} max={65535} />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_username" label="Tên đăng nhập SMTP" rules={[{ required: true, message: 'Vui lòng nhập tên đăng nhập SMTP' }]}>
                            <Input placeholder="Địa chỉ email đầy đủ" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_password" label="Mật khẩu SMTP / mã ủy quyền" rules={[{ required: true, message: 'Vui lòng nhập mã ủy quyền SMTP' }]}>
                            <Input.Password placeholder="Email QQ vui lòng điền mã ủy quyền" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_from_email" label="Email người gửi">
                            <Input placeholder="Mặc định có thể giống tên đăng nhập" />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_from_name" label="Tên người gửi" rules={[{ required: true, message: 'Vui lòng nhập tên người gửi' }]}>
                            <Input placeholder="MuMuAINovel" />
                          </Form.Item>
                        </Col>
                      </Row>

                      <Row gutter={16}>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_use_ssl" label="Bật SSL" valuePropName="checked">
                            <Switch />
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={12}>
                          <Form.Item name="smtp_use_tls" label="Bật TLS" valuePropName="checked">
                            <Switch />
                          </Form.Item>
                        </Col>
                      </Row>
                    </Card>
                  </Col>

                  <Col xs={24} xl={8}>
                    <Card title="Chiến lược đăng ký và mã xác minh" bordered={false} style={{ borderRadius: 16, marginBottom: 24 }}>
                      <Form.Item name="email_auth_enabled" label="Bật xác thực email" valuePropName="checked">
                        <Switch />
                      </Form.Item>
                      <Form.Item name="email_register_enabled" label="Bật đăng ký bằng email" valuePropName="checked">
                        <Switch />
                      </Form.Item>
                      <Form.Item name="verification_code_ttl_minutes" label="Hiệu lực mã xác minh (phút)" rules={[{ required: true, message: 'Vui lòng nhập hiệu lực mã xác minh' }]}>
                        <InputNumber style={{ width: '100%' }} min={1} max={120} />
                      </Form.Item>
                      <Form.Item name="verification_resend_interval_seconds" label="Khoảng cách gửi lại mã xác minh (giây)" rules={[{ required: true, message: 'Vui lòng nhập khoảng cách gửi lại mã xác minh' }]}>
                        <InputNumber style={{ width: '100%' }} min={10} max={3600} />
                      </Form.Item>
                    </Card>

                    <Card title="Thao tác" bordered={false} style={{ borderRadius: 16 }}>
                      <Space direction="vertical" style={{ width: '100%' }} size={12}>
                        <Input
                          value={testTargetEmail}
                          onChange={(e) => setTestTargetEmail(e.target.value)}
                          placeholder="Vui lòng nhập email nhận thử nghiệm, ví dụ 123456@qq.com"
                        />
                        <Button icon={<ReloadOutlined />} onClick={loadData} block>
                          Tải lại
                        </Button>
                        <Button icon={<SendOutlined />} loading={testing} onClick={handleTest} block>
                          Gửi email thử nghiệm
                        </Button>
                        <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving} block onClick={() => form.submit()}>
                          Lưu cài đặt hệ thống
                        </Button>
                        <Alert
                          type="success"
                          showIcon
                          icon={<CheckCircleOutlined />}
                          message="Khuyến nghị dùng cấu hình QQ mặc định"
                          description={<Text type="secondary">Lưu cấu hình SMTP trước, sau đó điền email nhận thử nghiệm, nhấn "Gửi email thử nghiệm" để backend thực sự gửi thư qua SMTP.</Text>}
                        />
                      </Space>
                    </Card>
                  </Col>
                </Row>
              </Form>
            ),
          },
          {
            key: 'announcements',
            label: (
              <Space>
                <BellOutlined />
                Quản lý thông báo
              </Space>
            ),
            children: (
              <Card bordered={false} style={{ borderRadius: 16 }}>
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <Alert
                    type={announcementAdminAvailable ? 'info' : 'warning'}
                    showIcon
                    message={announcementAdminAvailable ? 'Khu vực đăng thông báo' : 'Instance hiện tại không phải phía đăng thông báo'}
                    description={announcementAdminAvailable
                      ? 'Thông báo chỉ có thể được đăng, chỉnh sửa, ẩn hoặc xóa bởi quản trị viên ở chế độ máy chủ; instance máy khách sẽ định kỳ đồng bộ thông báo đã đăng và chưa hết hạn từ máy chủ.'
                      : `Chỉ có thể đăng thông báo ở máy chủ đám mây. Chế độ hiện tại: ${announcementStatus?.mode || 'không xác định'}${announcementStatus?.cloud_url ? `, địa chỉ đám mây: ${announcementStatus.cloud_url}` : ''}`}
                  />

                  <Row gutter={[16, 16]} justify="space-between" align="middle">
                    <Col xs={24} lg={14}>
                      <Space wrap>
                        <Button type="primary" icon={<PlusOutlined />} disabled={!announcementAdminAvailable} onClick={openCreateAnnouncementModal}>
                          Tạo thông báo
                        </Button>
                        <Button icon={<ReloadOutlined />} loading={announcementLoading || announcementStatusLoading} onClick={() => { void loadAnnouncementStatus(); void loadAnnouncements(announcementPagination.current, announcementPagination.pageSize, announcementSearchKeyword); }}>
                          Làm mới danh sách
                        </Button>
                        {announcementStatus && (
                          <Tag color={announcementAdminAvailable ? 'green' : 'orange'}>
                            {announcementStatus.mode === 'server' ? 'Chế độ máy chủ' : 'Chế độ máy khách'}
                          </Tag>
                        )}
                      </Space>
                    </Col>
                    <Col xs={24} lg={10} style={{ textAlign: 'right' }}>
                      <Space wrap>
                        <Search
                          allowClear
                          placeholder="Tìm kiếm tiêu đề, tóm tắt hoặc nội dung"
                          style={{ width: 220 }}
                          onSearch={handleAnnouncementSearch}
                          disabled={!announcementAdminAvailable}
                        />
                        <Text type="secondary">Trạng thái</Text>
                        <Select<AnnouncementStatusFilter>
                          style={{ width: 120, textAlign: 'left' }}
                          value={announcementStatusFilter}
                          disabled={!announcementAdminAvailable}
                          onChange={(value) => {
                            setAnnouncementStatusFilter(value);
                            setAnnouncementPagination(prev => ({ ...prev, current: 1 }));
                          }}
                          options={[
                            { label: 'Tất cả', value: 'all' },
                            { label: 'Bản nháp', value: 'draft' },
                            { label: 'Đã đăng', value: 'published' },
                            { label: 'Đã ẩn', value: 'hidden' },
                          ]}
                        />
                      </Space>
                    </Col>
                  </Row>

                  <Table<Announcement>
                    rowKey="id"
                    columns={announcementColumns}
                    dataSource={announcements}
                    loading={announcementLoading}
                    pagination={{
                      current: announcementPagination.current,
                      pageSize: announcementPagination.pageSize,
                      total: announcementPagination.total,
                      showSizeChanger: true,
                      showTotal: (total) => `Tổng ${total} thông báo`,
                    }}
                    onChange={handleAnnouncementTableChange}
                    scroll={{ x: 1200 }}
                  />
                </Space>
              </Card>
            ),
          },
        ]}
      />
      </div>

      <Modal
        title={editingAnnouncement ? 'Chỉnh sửa thông báo' : 'Tạo thông báo'}
        open={announcementModalOpen}
        onCancel={closeAnnouncementModal}
        onOk={() => announcementForm.submit()}
        confirmLoading={announcementSaving}
        okText={editingAnnouncement ? 'Lưu thay đổi' : 'Tạo thông báo'}
        cancelText="Hủy"
        width={1200}
        destroyOnClose
      >
        <Form form={announcementForm} layout="vertical" onFinish={handleSaveAnnouncement} preserve={false}>
          <Row gutter={16}>
            <Col xs={24} md={16}>
              <Form.Item
                name="title"
                label="Tiêu đề thông báo"
                rules={[
                  { required: true, message: 'Vui lòng nhập tiêu đề thông báo' },
                  { max: 120, message: 'Tiêu đề thông báo không được vượt quá 120 ký tự' },
                  { whitespace: true, message: 'Tiêu đề thông báo không được chỉ chứa khoảng trắng' },
                ]}
              >
                <Input placeholder="Vui lòng nhập tiêu đề thông báo" maxLength={120} showCount />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="level" label="Mức độ thông báo" rules={[{ required: true, message: 'Vui lòng chọn mức độ thông báo' }]}>
                <Select>
                  <Option value="info">Thông báo</Option>
                  <Option value="success">Thành công</Option>
                  <Option value="warning">Cảnh báo</Option>
                  <Option value="error">Quan trọng</Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="summary" label="Tóm tắt" rules={[{ max: 255, message: 'Tóm tắt không được vượt quá 255 ký tự' }]}>
            <Input placeholder="Tùy chọn, mô tả ngắn dùng cho danh sách và dòng thời gian" maxLength={255} showCount />
          </Form.Item>

          <Card
            size="small"
            title="Nội dung thông báo (Markdown / HTML an toàn)"
            style={{ marginBottom: 24, borderRadius: 12 }}
            extra={<Text type="secondary">Hỗ trợ Markdown, cùng HTML an toàn như ảnh căn giữa, ngắt dòng, nhấn mạnh</Text>}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Space wrap>
                <Button size="small" onClick={() => appendMarkdownSnippet('## Tiêu đề nhỏ')}>Tiêu đề</Button>
                <Button size="small" onClick={() => appendMarkdownSnippet('**Nội dung quan trọng**')}>In đậm</Button>
                <Button size="small" onClick={() => appendMarkdownSnippet('- Mục danh sách\n- Mục danh sách')}>Danh sách</Button>
                <Button size="small" onClick={() => appendMarkdownSnippet('> Ghi chú trích dẫn')}>Trích dẫn</Button>
                <Button size="small" onClick={() => appendMarkdownSnippet('[Văn bản liên kết](https://example.com)')}>Liên kết</Button>
                <Button size="small" onClick={() => appendMarkdownSnippet('<p align="center">\n  <img src="https://avatars.githubusercontent.com/u/283105808?s=48&v=4" alt="DolOffer Logo" width="200"/>\n  <br>\n  <em>Nền tảng hàng đầu chuyên giới thiệu sản phẩm số chất lượng và chia sẻ ưu đãi giá trị</em>\n</p>')}>Ảnh căn giữa</Button>
                <Button size="small" onClick={() => appendMarkdownSnippet('```\nNội dung mã\n```')}>Khối mã</Button>
              </Space>

              <Row gutter={16}>
                <Col xs={24} lg={12}>
                  <Form.Item
                    name="content"
                    label="Chỉnh sửa"
                    rules={[
                      { required: true, message: 'Vui lòng nhập nội dung thông báo' },
                      { whitespace: true, message: 'Nội dung thông báo không được chỉ chứa khoảng trắng' },
                    ]}
                    style={{ marginBottom: 0 }}
                  >
                    <TextArea
                      style={{ height: 420, resize: 'vertical' }}
                      placeholder={[
                        'Nhập nội dung thông báo bằng Markdown hoặc HTML an toàn, ví dụ:',
                        '## Ghi chú cập nhật',
                        '- Hỗ trợ danh sách',
                        '- Hỗ trợ **nội dung quan trọng**',
                        '> Hỗ trợ ghi chú trích dẫn',
                        '[Xem chi tiết](https://example.com)',
                        '',
                        '<p align="center">',
                        '  <img src="https://avatars.githubusercontent.com/u/283105808?s=48&v=4" alt="DolOffer Logo" width="200"/>',
                        '  <br>',
                        '  <em>Nền tảng hàng đầu chuyên giới thiệu sản phẩm số chất lượng và chia sẻ ưu đãi giá trị</em>',
                        '</p>',
                      ].join('\n')}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} lg={12}>
                  <Text strong>Xem trước</Text>
                  <div
                    style={{
                      marginTop: 8,
                      minHeight: 336,
                      maxHeight: 420,
                      overflow: 'auto',
                      padding: 16,
                      borderRadius: 10,
                      border: `1px solid ${token.colorBorderSecondary}`,
                      background: token.colorFillQuaternary,
                    }}
                  >
                    <MarkdownRenderer content={announcementContent} />
                  </div>
                </Col>
              </Row>
            </Space>
          </Card>

          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item name="status" label="Trạng thái đăng" rules={[{ required: true, message: 'Vui lòng chọn trạng thái đăng' }]}>
                <Select>
                  <Option value="draft">Bản nháp</Option>
                  <Option value="published">Đăng ngay</Option>
                  <Option value="hidden">Ẩn</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="publish_at" label="Thời gian đăng">
                <DatePicker style={{ width: '100%' }} showTime={{ format: 'HH:mm' }} format="YYYY-MM-DD HH:mm" allowClear />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="expire_at"
                label="Thời gian hết hạn"
                dependencies={['publish_at']}
                rules={[
                  ({ getFieldValue }) => ({
                    validator(_, value: Dayjs | null) {
                      const publishAt = getFieldValue('publish_at') as Dayjs | null;
                      if (!value || !publishAt || value.isAfter(publishAt)) {
                        return Promise.resolve();
                      }
                      return Promise.reject(new Error('Thời gian hết hạn phải sau thời gian đăng'));
                    },
                  }),
                ]}
              >
                <DatePicker style={{ width: '100%' }} showTime={{ format: 'HH:mm' }} format="YYYY-MM-DD HH:mm" allowClear />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="pinned" label="Ghim thông báo" valuePropName="checked" extra="Thông báo ghim sẽ được hiển thị ưu tiên ở đầu dòng thời gian thông báo của máy khách.">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
