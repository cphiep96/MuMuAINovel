import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  Layout,
  Row,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
  message,
  theme,
} from 'antd';
import {
  BookOutlined,
  LockOutlined,
  MailOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { authApi } from '../services/api';
import { useNavigate, useSearchParams } from 'react-router-dom';
import AnnouncementModal from '../components/AnnouncementModal';
import ThemeSwitch from '../components/ThemeSwitch';

const { Title, Paragraph, Text } = Typography;

interface AuthConfig {
  local_auth_enabled: boolean;
  linuxdo_enabled: boolean;
  email_auth_enabled: boolean;
  email_register_enabled: boolean;
}

interface LocalLoginValues {
  username: string;
  password: string;
}

interface EmailLoginValues {
  email: string;
  code: string;
}

interface EmailRegisterValues {
  email: string;
  code: string;
  password: string;
  confirmPassword: string;
  display_name?: string;
}

interface ResetPasswordValues {
  email: string;
  code: string;
  new_password: string;
  confirmNewPassword: string;
}

export default function Login() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [authConfig, setAuthConfig] = useState<AuthConfig>({
    local_auth_enabled: false,
    linuxdo_enabled: false,
    email_auth_enabled: false,
    email_register_enabled: false,
  });
  const [localForm] = Form.useForm<LocalLoginValues>();
  const [emailLoginForm] = Form.useForm<EmailLoginValues>();
  const [emailRegisterForm] = Form.useForm<EmailRegisterValues>();
  const [resetPasswordForm] = Form.useForm<ResetPasswordValues>();
  const { token } = theme.useToken();
  const alphaColor = (color: string, alpha: number) => `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(0)}%, transparent)`;
  const primaryButtonShadow = `0 8px 20px ${alphaColor(token.colorPrimary, 0.28)}`;
  const hoverButtonShadow = `0 12px 28px ${alphaColor(token.colorPrimary, 0.36)}`;
  const [showAnnouncement, setShowAnnouncement] = useState(false);
  const [loginCodeSending, setLoginCodeSending] = useState(false);
  const [registerCodeSending, setRegisterCodeSending] = useState(false);
  const [resetCodeSending, setResetCodeSending] = useState(false);
  const [loginCountdown, setLoginCountdown] = useState(0);
  const [registerCountdown, setRegisterCountdown] = useState(0);
  const [resetCountdown, setResetCountdown] = useState(0);
  const [showResetPassword, setShowResetPassword] = useState(false);

  const localAuthEnabled = authConfig.local_auth_enabled;
  const linuxdoEnabled = authConfig.linuxdo_enabled;
  const emailAuthEnabled = authConfig.email_auth_enabled;
  const emailRegisterEnabled = authConfig.email_register_enabled;

  useEffect(() => {
    const timers = [
      { value: loginCountdown, setter: setLoginCountdown },
      { value: registerCountdown, setter: setRegisterCountdown },
      { value: resetCountdown, setter: setResetCountdown },
    ].map(({ value, setter }) => {
      if (value <= 0) {
        return null;
      }

      return window.setInterval(() => {
        setter((prev) => {
          if (prev <= 1) {
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    });

    return () => {
      timers.forEach((timer) => {
        if (timer) {
          window.clearInterval(timer);
        }
      });
    };
  }, [loginCountdown, registerCountdown, resetCountdown]);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        await authApi.getCurrentUser();
        const redirect = searchParams.get('redirect') || '/';
        navigate(redirect);
      } catch {
        try {
          const config = await authApi.getAuthConfig();
          setAuthConfig(config);
        } catch (error) {
          console.error('Lấy cấu hình xác thực thất bại:', error);
          setAuthConfig({
            local_auth_enabled: false,
            linuxdo_enabled: true,
            email_auth_enabled: false,
            email_register_enabled: false,
          });
        }
        setChecking(false);
      }
    };
    checkAuth();
  }, [navigate, searchParams]);

  const handleLoginSuccess = () => {
    message.success('Đăng nhập thành công!');

    const hideForever = localStorage.getItem('announcement_hide_forever');
    const hideToday = localStorage.getItem('announcement_hide_today');
    const today = new Date().toDateString();

    if (hideForever === 'true' || hideToday === today) {
      const redirect = searchParams.get('redirect') || '/';
      navigate(redirect);
    } else {
      setShowAnnouncement(true);
    }
  };

  const handleLocalLogin = async (values: LocalLoginValues) => {
    try {
      setLoading(true);
      const response = await authApi.localLogin(values.username, values.password);
      if (response.success) {
        handleLoginSuccess();
      }
    } catch (error) {
      console.error('Đăng nhập cục bộ thất bại:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleEmailLogin = async (values: EmailLoginValues) => {
    try {
      setLoading(true);
      const response = await authApi.emailLogin({
        email: values.email,
        code: values.code,
      });
      if (response.success) {
        handleLoginSuccess();
      }
    } catch (error) {
      console.error('Đăng nhập bằng mã qua email thất bại:', error);
    } finally {
      setLoading(false);
    }
  };

  const sendLoginCode = async () => {
    try {
      const values = await emailLoginForm.validateFields(['email']);
      setLoginCodeSending(true);
      const result = await authApi.sendEmailCode({ email: values.email, scene: 'login' });
      message.success(result.message || 'Đã gửi mã xác minh');
      setLoginCountdown(result.resend_interval_seconds || 60);
    } catch (error) {
      console.error('Gửi mã xác minh login thất bại:', error);
    } finally {
      setLoginCodeSending(false);
    }
  };

  const sendRegisterCode = async () => {
    try {
      const values = await emailRegisterForm.validateFields(['email']);
      setRegisterCodeSending(true);
      const result = await authApi.sendEmailCode({ email: values.email, scene: 'register' });
      message.success(result.message || 'Đã gửi mã xác minh');
      setRegisterCountdown(result.resend_interval_seconds || 60);
    } catch (error) {
      console.error('Gửi mã xác minh register thất bại:', error);
    } finally {
      setRegisterCodeSending(false);
    }
  };

  const sendResetCode = async () => {
    try {
      const values = await resetPasswordForm.validateFields(['email']);
      setResetCodeSending(true);
      const result = await authApi.sendEmailCode({ email: values.email, scene: 'reset_password' });
      message.success(result.message || 'Đã gửi mã xác minh');
      setResetCountdown(result.resend_interval_seconds || 60);
    } catch (error) {
      console.error('Gửi mã xác minh reset_password thất bại:', error);
    } finally {
      setResetCodeSending(false);
    }
  };

  const handleEmailRegister = async (values: EmailRegisterValues) => {
    try {
      setLoading(true);
      const response = await authApi.emailRegister({
        email: values.email,
        code: values.code,
        password: values.password,
        display_name: values.display_name?.trim() || undefined,
      });
      if (response.success) {
        message.success('Đăng ký thành công, đã tự đăng nhập');
        emailRegisterForm.resetFields(['code', 'password', 'confirmPassword']);
        setRegisterCountdown(0);
        handleLoginSuccess();
      }
    } catch (error) {
      console.error('Đăng ký bằng email thất bại:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (values: ResetPasswordValues) => {
    try {
      setLoading(true);
      const result = await authApi.resetEmailPassword({
        email: values.email,
        code: values.code,
        new_password: values.new_password,
      });
      message.success(result.message || 'Đặt lại mật khẩu thành công');
      resetPasswordForm.resetFields(['code', 'new_password', 'confirmNewPassword']);
      setResetCountdown(0);
      setShowResetPassword(false);
    } catch (error) {
      console.error('Đặt lại mật khẩu thất bại:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleLinuxDOLogin = async () => {
    try {
      setLoading(true);
      const response = await authApi.getLinuxDOAuthUrl();

      const redirect = searchParams.get('redirect');
      if (redirect) {
        sessionStorage.setItem('login_redirect', redirect);
      }

      window.location.href = response.auth_url;
    } catch (error) {
      console.error('Lấy địa chỉ cấp quyền thất bại:', error);
      message.error('Lấy địa chỉ ủy quyền thất bại, vui lòng thử lại sau');
      setLoading(false);
    }
  };

  const handleAnnouncementClose = () => {
    setShowAnnouncement(false);
    const redirect = searchParams.get('redirect') || '/';
    navigate(redirect);
  };

  const handleDoNotShowToday = () => {
    const today = new Date().toDateString();
    localStorage.setItem('announcement_hide_today', today);
  };

  const handleNeverShow = () => {
    localStorage.setItem('announcement_hide_forever', 'true');
  };

  const loginTips = useMemo(() => {
    const tips = [
      'Lần đăng nhập LinuxDO đầu sẽ tự tạo tài khoản.',
    ];

    if (localAuthEnabled) {
      tips.unshift('Tài khoản mặc định đăng nhập local: admin / admin123');
    }

    if (emailAuthEnabled) {
      tips.push('Người dùng đăng ký email có thể đặt lại mật khẩu bằng mã email.');
    }

    return tips;
  }, [emailAuthEnabled, localAuthEnabled]);

  const featureItems = [
    {
      icon: <RobotOutlined />,
      title: 'Đa mô hình AI phối hợp',
      description: 'Hỗ trợ OpenAI, Gemini, Claude..., chuyển linh hoạt theo tình huống.',
    },
    {
      icon: <ThunderboltOutlined />,
      title: 'Điều khiển bởi hướng dẫn thông minh',
      description: 'Tự tạo dàn ý, nhân vật và bối cảnh thế giới, dựng khung câu chuyện nhanh.',
    },
    {
      icon: <TeamOutlined />,
      title: 'Quản lý nhân vật và tổ chức',
      description: 'Quản lý trực quan quan hệ nhân vật và tổ chức, thiết lập phức tạp cũng nắm rõ.',
    },
    {
      icon: <BookOutlined />,
      title: 'Vòng khép kín sáng tác chương',
      description: 'Hỗ trợ tạo/chỉnh sửa/viết lại/trau chuốt chương, liên tục nâng chất lượng.',
    },
  ];

  const renderLocalLogin = () => (
    <>
      <Form
        form={localForm}
        layout="vertical"
        onFinish={handleLocalLogin}
        size="large"
        style={{ marginTop: 16 }}
      >
        <Form.Item
          name="username"
          label="Tài khoản quản trị"
          rules={[{ required: true, message: 'Vui lòng nhập tài khoản quản trị/email' }]}
        >
          <Input
            prefix={<UserOutlined style={{ color: token.colorTextTertiary }} />}
            placeholder="Vui lòng nhập tài khoản quản trị/email"
            autoComplete="username"
            style={{ height: 46, borderRadius: 12 }}
          />
        </Form.Item>
        <Form.Item
          name="password"
          label="Khóa truy cập"
          rules={[{ required: true, message: 'Vui lòng nhập khóa truy cập' }]}
        >
          <Input.Password
            prefix={<LockOutlined style={{ color: token.colorTextTertiary }} />}
            placeholder="Vui lòng nhập khóa truy cập"
            autoComplete="current-password"
            style={{ height: 46, borderRadius: 12 }}
          />
        </Form.Item>
        <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
          <Button
            type="primary"
            htmlType="submit"
            loading={loading}
            block
            style={{
              height: 46,
              fontSize: 16,
              fontWeight: 600,
              background: `linear-gradient(90deg, ${token.colorPrimary} 0%, ${alphaColor(token.colorPrimary, 0.86)} 100%)`,
              border: 'none',
              borderRadius: '12px',
              boxShadow: primaryButtonShadow,
            }}
          >
            Đăng nhập hệ thống
          </Button>
        </Form.Item>
      </Form>

      {linuxdoEnabled ? (
        <>
          <Divider style={{ margin: '18px 0 16px' }}>Đăng nhập bên thứ ba</Divider>
          {renderLinuxDOLogin()}
        </>
      ) : null}
    </>
  );

  const renderEmailLogin = () => {
    if (showResetPassword) {
      return (
        <div style={{ marginTop: 16 }}>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Title level={5} style={{ margin: 0 }}>Quên mật khẩu / Đặt lại mật khẩu</Title>
              <Button type="link" style={{ paddingInline: 0 }} onClick={() => setShowResetPassword(false)}>
                Quay lại đăng nhập bằng mã
              </Button>
            </Space>

            <Card size="small" bordered={false} style={{ borderRadius: 12, background: token.colorFillAlter }}>
              <Form
                form={resetPasswordForm}
                layout="vertical"
                onFinish={handleResetPassword}
                size="middle"
              >
                <Form.Item
                  name="email"
                  label="Email đăng ký"
                  rules={[
                    { required: true, message: 'Vui lòng nhập email đăng ký' },
                    { type: 'email', message: 'Vui lòng nhập địa chỉ email hợp lệ' },
                  ]}
                >
                  <Input prefix={<MailOutlined />} placeholder="Vui lòng nhập email đăng ký" />
                </Form.Item>
                <Form.Item label="Mã đặt lại" required style={{ marginBottom: 12 }}>
                  <Space.Compact style={{ width: '100%' }}>
                    <Form.Item
                      name="code"
                      noStyle
                      rules={[
                        { required: true, message: 'Vui lòng nhập mã xác minh đặt lại' },
                        { len: 6, message: 'Mã xác minh dài 6 ký tự' },
                      ]}
                    >
                      <Input placeholder="Vui lòng nhập mã xác minh đặt lại" maxLength={6} />
                    </Form.Item>
                    <Button
                      onClick={sendResetCode}
                      loading={resetCodeSending}
                      disabled={resetCountdown > 0}
                    >
                      {resetCountdown > 0 ? `Gửi lại sau ${resetCountdown}s` : 'Gửi mã xác minh'}
                    </Button>
                  </Space.Compact>
                </Form.Item>
                <Form.Item
                  name="new_password"
                  label="Mật khẩu mới"
                  rules={[
                    { required: true, message: 'Vui lòng nhập mật khẩu mới' },
                    { min: 6, message: 'Mật khẩu dài ít nhất 6 ký tự' },
                  ]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="Vui lòng nhập mật khẩu mới" />
                </Form.Item>
                <Form.Item
                  name="confirmNewPassword"
                  label="Xác nhận mật khẩu mới"
                  dependencies={['new_password']}
                  rules={[
                    { required: true, message: 'Vui lòng nhập lại mật khẩu mới' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('new_password') === value) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error('Hai lần nhập mật khẩu mới không khớp'));
                      },
                    }),
                  ]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="Vui lòng nhập lại mật khẩu mới" />
                </Form.Item>
                <Button type="default" htmlType="submit" loading={loading} block>
                  Đặt lại mật khẩu
                </Button>
              </Form>
            </Card>
          </Space>
        </div>
      );
    }

    return (
      <Form
        form={emailLoginForm}
        layout="vertical"
        onFinish={handleEmailLogin}
        size="large"
        style={{ marginTop: 16 }}
      >
        <Form.Item
          name="email"
          label="Địa chỉ email"
          rules={[
            { required: true, message: 'Vui lòng nhập địa chỉ email' },
            { type: 'email', message: 'Vui lòng nhập địa chỉ email hợp lệ' },
          ]}
        >
          <Input
            prefix={<MailOutlined style={{ color: token.colorTextTertiary }} />}
            placeholder="Vui lòng nhập email đã đăng ký"
            autoComplete="email"
            style={{ height: 46, borderRadius: 12 }}
          />
        </Form.Item>

        <Form.Item label="Mã xác minh đăng nhập" required style={{ marginBottom: 24 }}>
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item
              name="code"
              noStyle
              rules={[
                { required: true, message: 'Vui lòng nhập mã xác minh đăng nhập' },
                { len: 6, message: 'Mã xác minh dài 6 ký tự' },
              ]}
            >
              <Input
                prefix={<SafetyCertificateOutlined style={{ color: token.colorTextTertiary }} />}
                placeholder="Vui lòng nhập mã đăng nhập 6 số"
                maxLength={6}
                style={{ height: 46, borderRadius: '12px 0 0 12px' }}
              />
            </Form.Item>
            <Button
              style={{ height: 46 }}
              onClick={sendLoginCode}
              loading={loginCodeSending}
              disabled={loginCountdown > 0}
            >
              {loginCountdown > 0 ? `Gửi lại sau ${loginCountdown}s` : 'Gửi mã xác minh'}
            </Button>
          </Space.Compact>
        </Form.Item>

        <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
          <Button
            type="primary"
            htmlType="submit"
            loading={loading}
            block
            style={{
              height: 46,
              fontSize: 16,
              fontWeight: 600,
              background: `linear-gradient(90deg, ${token.colorPrimary} 0%, ${alphaColor(token.colorPrimary, 0.86)} 100%)`,
              border: 'none',
              borderRadius: '12px',
              boxShadow: primaryButtonShadow,
            }}
          >
            Đăng nhập bằng mã
          </Button>
        </Form.Item>

        <div style={{ marginTop: 12, textAlign: 'right' }}>
          <Button type="link" style={{ paddingInline: 0 }} onClick={() => setShowResetPassword(true)}>
            Quên mật khẩu? Nhấn đặt lại
          </Button>
        </div>
      </Form>
    );
  };

  const renderEmailRegister = () => (
    <Form
      form={emailRegisterForm}
      layout="vertical"
      onFinish={handleEmailRegister}
      size="large"
      style={{ marginTop: 16 }}
    >
      <Form.Item
        name="email"
        label="Email đăng ký"
        rules={[
          { required: true, message: 'Vui lòng nhập email đăng ký' },
          { type: 'email', message: 'Vui lòng nhập địa chỉ email hợp lệ' },
        ]}
      >
        <Input
          prefix={<MailOutlined style={{ color: token.colorTextTertiary }} />}
          placeholder="Vui lòng nhập email đăng ký"
          autoComplete="email"
          style={{ height: 46, borderRadius: 12 }}
        />
      </Form.Item>

      <Form.Item label="Mã xác minh email" required style={{ marginBottom: 12 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Form.Item
            name="code"
            noStyle
            rules={[
              { required: true, message: 'Vui lòng nhập mã xác minh email' },
              { len: 6, message: 'Mã xác minh dài 6 ký tự' },
            ]}
          >
            <Input
              prefix={<SafetyCertificateOutlined style={{ color: token.colorTextTertiary }} />}
              placeholder="Vui lòng nhập mã xác minh 6 số"
              maxLength={6}
              style={{ height: 46, borderRadius: '12px 0 0 12px' }}
            />
          </Form.Item>
          <Button
            style={{ height: 46 }}
            onClick={sendRegisterCode}
            loading={registerCodeSending}
            disabled={registerCountdown > 0}
          >
            {registerCountdown > 0 ? `Gửi lại sau ${registerCountdown}s` : 'Gửi mã xác minh'}
          </Button>
        </Space.Compact>
      </Form.Item>

      <Form.Item
        name="display_name"
        label="Biệt danh"
        rules={[{ max: 50, message: 'Biệt danh không quá 50 ký tự' }]}
      >
        <Input
          prefix={<UserOutlined style={{ color: token.colorTextTertiary }} />}
          placeholder="Tùy chọn, mặc định dùng phần trước @ của email"
          autoComplete="nickname"
          style={{ height: 46, borderRadius: 12 }}
        />
      </Form.Item>

      <Form.Item
        name="password"
        label="Mật khẩu đăng nhập"
        rules={[
          { required: true, message: 'Vui lòng nhập mật khẩu đăng nhập' },
          { min: 6, message: 'Mật khẩu dài ít nhất 6 ký tự' },
        ]}
      >
        <Input.Password
          prefix={<LockOutlined style={{ color: token.colorTextTertiary }} />}
          placeholder="Vui lòng nhập mật khẩu đăng nhập"
          autoComplete="new-password"
          style={{ height: 46, borderRadius: 12 }}
        />
      </Form.Item>

      <Form.Item
        name="confirmPassword"
        label="Xác nhận mật khẩu"
        dependencies={['password']}
        rules={[
          { required: true, message: 'Vui lòng nhập lại mật khẩu đăng nhập' },
          ({ getFieldValue }) => ({
            validator(_, value) {
              if (!value || getFieldValue('password') === value) {
                return Promise.resolve();
              }
              return Promise.reject(new Error('Hai lần nhập mật khẩu không khớp'));
            },
          }),
        ]}
      >
        <Input.Password
          prefix={<LockOutlined style={{ color: token.colorTextTertiary }} />}
          placeholder="Vui lòng nhập lại mật khẩu đăng nhập"
          autoComplete="new-password"
          style={{ height: 46, borderRadius: 12 }}
        />
      </Form.Item>

      <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
        <Button
          type="primary"
          htmlType="submit"
          loading={loading}
          block
          style={{
            height: 46,
            fontSize: 16,
            fontWeight: 600,
            background: `linear-gradient(90deg, ${token.colorPrimary} 0%, ${alphaColor(token.colorPrimary, 0.86)} 100%)`,
            border: 'none',
            borderRadius: '12px',
            boxShadow: primaryButtonShadow,
          }}
        >
          Đăng ký và đăng nhập
        </Button>
      </Form.Item>

      <Text type="secondary" style={{ marginTop: 12, display: 'block' }}>
        Mã xác minh sẽ được gửi tới email bạn nhập; nếu chưa nhận hãy kiểm tra hộp thư rác hoặc thử lại sau. Sau khi đăng ký có thể đăng nhập bằng mã email, cũng hỗ trợ đặt lại mật khẩu qua email.
      </Text>
    </Form>
  );

  const renderLinuxDOLogin = () => (
    <div>
      <Button
        type="primary"
        size="large"
        icon={(
          <img
            src="/favicon.ico"
            alt="LinuxDO"
            style={{
              width: 20,
              height: 20,
              marginRight: 8,
              verticalAlign: 'middle',
            }}
          />
        )}
        loading={loading}
        onClick={handleLinuxDOLogin}
        block
        style={{
          height: 46,
          fontSize: 16,
          fontWeight: 600,
          background: `linear-gradient(90deg, ${token.colorPrimary} 0%, ${alphaColor(token.colorPrimary, 0.86)} 100%)`,
          border: 'none',
          borderRadius: '12px',
          boxShadow: primaryButtonShadow,
          transition: 'all 0.3s ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translateY(-2px)';
          e.currentTarget.style.boxShadow = hoverButtonShadow;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translateY(0)';
          e.currentTarget.style.boxShadow = primaryButtonShadow;
        }}
      >
        Đăng nhập bằng LinuxDO OAuth
      </Button>
    </div>
  );

  const authTabs = [
    ...(localAuthEnabled
      ? [
          {
            key: 'local-login',
            label: 'Đăng nhập local',
            children: renderLocalLogin(),
          },
        ]
      : []),
    ...(emailAuthEnabled
      ? [
          {
            key: 'email-login',
            label: 'Đăng nhập email',
            children: renderEmailLogin(),
          },
        ]
      : []),
    ...(emailAuthEnabled && emailRegisterEnabled
      ? [
          {
            key: 'email-register',
            label: 'Đăng ký email',
            children: renderEmailRegister(),
          },
        ]
      : []),
  ];

  if (checking) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: '100vh',
          background: token.colorBgLayout,
        }}
      >
        <Spin size="large" style={{ color: token.colorPrimary }} />
      </div>
    );
  }

  return (
    <>
      <AnnouncementModal
        visible={showAnnouncement}
        onClose={handleAnnouncementClose}
        onDoNotShowToday={handleDoNotShowToday}
        onNeverShow={handleNeverShow}
      />
      <Layout style={{ minHeight: '100vh', background: token.colorBgLayout }}>
        <div
          style={{
            position: 'fixed',
            top: 20,
            right: 20,
            zIndex: 10,
            padding: '8px 10px',
            borderRadius: 12,
            background: alphaColor(token.colorBgContainer, 0.9),
            border: `1px solid ${token.colorBorderSecondary}`,
            backdropFilter: 'blur(6px)',
          }}
        >
          <ThemeSwitch size="small" />
        </div>
        <Row style={{ minHeight: '100vh' }}>
          <Col xs={0} lg={11}>
            <section
              style={{
                height: '100%',
                padding: '44px 64px 88px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                position: 'relative',
                overflow: 'hidden',
                backgroundColor: alphaColor(token.colorBgContainer, 0.78),
                backgroundImage: `linear-gradient(${alphaColor(token.colorTextSecondary, 0.06)} 1px, transparent 1px), linear-gradient(90deg, ${alphaColor(token.colorTextSecondary, 0.06)} 1px, transparent 1px)`,
                backgroundSize: '68px 68px',
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  background: `radial-gradient(circle at 25% 20%, ${alphaColor(token.colorPrimary, 0.12)} 0%, transparent 50%)`,
                  pointerEvents: 'none',
                }}
              />

              <div
                style={{
                  position: 'relative',
                  zIndex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: 34,
                  width: '100%',
                }}
              >
                <Space align="center" size={14}>
                  <div
                    style={{
                      width: 46,
                      height: 46,
                      borderRadius: 14,
                      background: `linear-gradient(135deg, ${token.colorPrimary} 0%, ${alphaColor(token.colorPrimary, 0.7)} 100%)`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: primaryButtonShadow,
                    }}
                  >
                    <img
                      src="/logo.svg"
                      alt="MuMuAINovel"
                      style={{ width: 26, height: 26, filter: 'brightness(0) invert(1)' }}
                    />
                  </div>
                  <Title level={3} style={{ margin: 0, color: token.colorText }}>
                    MuMuAINovel
                  </Title>
                </Space>

                <Space direction="vertical" size={32} style={{ width: '100%' }}>
                  <div style={{ maxWidth: 'min(860px, 100%)' }}>
                    <Title
                      level={1}
                      style={{
                        marginBottom: 22,
                        color: token.colorText,
                        lineHeight: 1.12,
                        fontWeight: 800,
                        fontSize: 'clamp(52px, 3vw, 78px)',
                      }}
                    >
                      Dựa trên AI
                      <br />
                      <span
                        style={{
                          backgroundImage: `linear-gradient(90deg, ${token.colorPrimary} 0%, #d946ef 100%)`,
                          WebkitBackgroundClip: 'text',
                          backgroundClip: 'text',
                          WebkitTextFillColor: 'transparent',
                          color: token.colorPrimary,
                        }}
                      >
                        Trợ lý sáng tác tiểu thuyết thông minh
                      </span>
                    </Title>
                    <Paragraph
                      style={{
                        fontSize: 'clamp(18px, 1vw, 22px)',
                        lineHeight: 1.85,
                        color: token.colorTextSecondary,
                        marginBottom: 0,
                        maxWidth: 800,
                      }}
                    >
                      Từ cảm hứng tới bản thảo, xây bàn làm việc sáng tác thống nhất quanh «đa mô hình, tự động hóa quy trình, quản lý quan hệ nhân vật, tinh chỉnh chương».
                    </Paragraph>
                  </div>

                  <Row gutter={[20, 20]} style={{ width: '100%', maxWidth: 'min(920px, 100%)' }}>
                    {featureItems.map((item) => (
                      <Col span={12} key={item.title}>
                        <Card
                          size="small"
                          bordered={false}
                          style={{
                            height: '100%',
                            minHeight: 120,
                            borderRadius: 16,
                            background: alphaColor(token.colorBgContainer, 0.9),
                          }}
                          bodyStyle={{ padding: 16 }}
                        >
                          <Space direction="vertical" size={8}>
                            <Space size={10} style={{ color: token.colorPrimary, fontWeight: 700, fontSize: 15 }}>
                              {item.icon}
                              <span>{item.title}</span>
                            </Space>
                            <Paragraph style={{ marginBottom: 0, color: token.colorTextSecondary, fontSize: 14, lineHeight: 1.65 }}>
                              {item.description}
                            </Paragraph>
                          </Space>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                </Space>

                <Space size={[10, 14]} wrap style={{ maxWidth: 'min(860px, 100%)' }}>
                  <Tag color="blue">OpenAI</Tag>
                  <Tag color="geekblue">Gemini</Tag>
                  <Tag color="purple">Claude</Tag>
                  <Tag color="cyan">LinuxDO OAuth</Tag>
                  <Tag color="green">Docker Compose</Tag>
                  <Tag color="gold">PostgreSQL</Tag>
                </Space>
              </div>

              <Paragraph
                style={{
                  marginBottom: 0,
                  fontSize: 12,
                  color: token.colorTextTertiary,
                  position: 'relative',
                  zIndex: 1,
                  letterSpacing: 0.4,
                }}
              >
                © 2026 MuMuAINovel · GPLv3 License
              </Paragraph>
            </section>
          </Col>

          <Col xs={24} lg={13}>
            <section
              style={{
                minHeight: '100vh',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '48px min(7vw, 72px)',
                background: token.colorBgLayout,
              }}
            >
              <div style={{ width: '100%', maxWidth: 520 }}>
                <Space direction="vertical" size={4}>
                  <Title level={2} style={{ marginBottom: 0, fontWeight: 700, color: token.colorText }}>
                    Chào mừng trở lại
                  </Title>
                  <Paragraph style={{ marginBottom: 0, color: token.colorTextSecondary }}>
                    Đăng nhập MuMuAINovel và tiếp tục dự án sáng tác tiểu thuyết của bạn.
                  </Paragraph>
                </Space>

                <div style={{ marginTop: 22 }}>
                  {authTabs.length > 0 ? (
                    <Tabs defaultActiveKey={authTabs[0].key} items={authTabs} />
                  ) : null}

                  {!localAuthEnabled && !linuxdoEnabled && !emailAuthEnabled ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="Chưa bật phương thức đăng nhập khả dụng"
                      description="Hãy liên hệ quản trị viên để bật đăng nhập local, email hoặc LinuxDO OAuth trong cấu hình hệ thống."
                    />
                  ) : null}

                  {emailAuthEnabled && !emailRegisterEnabled ? (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginTop: 12, borderRadius: 12 }}
                      message="Đăng ký email tạm chưa mở"
                      description="Hiện chỉ mở đăng nhập mã email và lấy lại mật khẩu; cần đăng ký hãy liên hệ quản trị viên."
                    />
                  ) : null}

                  <Divider style={{ margin: '20px 0 14px' }} />
                  <Alert
                    type="info"
                    showIcon
                    icon={<SafetyCertificateOutlined />}
                    style={{ background: alphaColor(token.colorPrimary, 0.06), borderRadius: 12 }}
                    message="Hướng dẫn đăng nhập"
                    description={(
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {loginTips.map((tip) => (
                          <li key={tip} style={{ marginBottom: 4 }}>
                            {tip}
                          </li>
                        ))}
                      </ul>
                    )}
                  />
                </div>
              </div>
            </section>
          </Col>
        </Row>
      </Layout>
    </>
  );
}
