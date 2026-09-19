import { useState, type ReactNode } from 'react';
import { Card, Row, Col, Typography, Image, Divider, Modal, Button, theme } from 'antd';
import {
    HeartOutlined,
    CheckCircleOutlined,
    FileTextOutlined,
    RocketOutlined,
    MessageOutlined,
    // StarOutlined,
    WechatOutlined
} from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

interface SponsorOption {
    amount: number | string;
    label: string;
    image: string;
    description: string;
}

interface SponsorBenefit {
    icon: ReactNode;
    title: string;
    description: string;
    price?: string;
}

const sponsorOptions: SponsorOption[] = [
    { amount: 5, label: '🌶️ Một gói snack cay', image: '/5.png', description: '¥5' },
    { amount: 10, label: '🍱 Một suất cơm ghép', image: '/10.png', description: '¥10' },
    { amount: 20, label: '☕ Một tách cà phê', image: '/20.png', description: '¥20' },
    { amount: 50, label: '🍖 Một buổi nướng', image: '/50.png', description: '¥50' },
    { amount: 99, label: '🍲 Một bữa Haidilao', image: '/99.png', description: '¥99' },
];

const benefits: SponsorBenefit[] = [
    {
        icon: <WechatOutlined style={{ fontSize: '32px', color: 'var(--ant-color-primary)' }} />,
        title: 'Tham gia nhóm ủng hộ',
        description: 'Vào nhóm nội bộ để nhận cập nhật dự án sớm nhất',
        price: '(🌶️ Một gói snack cay)'
    },
    {
        icon: <FileTextOutlined style={{ fontSize: '32px', color: 'var(--ant-color-primary)' }} />,
        title: 'Ưu tiên phản hồi nhu cầu',
        description: 'Nhu cầu tính năng và phản hồi của bạn sẽ được ưu tiên xử lý',
        price: '(🌶️ Một gói snack cay)'
    },
    {
        icon: <RocketOutlined style={{ fontSize: '32px', color: 'var(--ant-color-success)' }} />,
        title: 'Khởi chạy một cú nhấp trên Windows',
        description: 'Nhận gói khởi chạy một cú nhấp không cần cài, dùng ngay',
        price: '(🌶️ Một gói snack cay)'
    },
    {
        icon: <MessageOutlined style={{ fontSize: '32px', color: 'var(--ant-color-warning)' }} />,
        title: 'Hỗ trợ kỹ thuật riêng',
        description: 'Nhận hỗ trợ từ xa và hướng dẫn cấu hình',
        price: '(☕ Một tách cà phê)'
    }
];

export default function Sponsor() {
    const [modalVisible, setModalVisible] = useState(false);
    const [selectedOption, setSelectedOption] = useState<SponsorOption | null>(null);
    const { token } = theme.useToken();
    const alphaColor = (color: string, alpha: number) =>
        `color-mix(in srgb, ${color} ${(alpha * 100).toFixed(0)}%, transparent)`;

    const handleCardClick = (option: SponsorOption) => {
        setSelectedOption(option);
        setModalVisible(true);
    };

    return (
        <div style={{
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden'
        }}>
            <div style={{
                flex: 1,
                overflowY: 'auto',
                overflowX: 'hidden',
                // padding: 'clamp(16px, 3vh, 24px) clamp(12px, 2vw, 16px)'
            }}>
                <div style={{
                    // maxWidth: '1200px',
                    height: '100%',
                    margin: '0 auto',
                    width: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    minHeight: 'fit-content'
                }}>
                    {/* 头部标题区域 */}
                    <div style={{ textAlign: 'center', marginBottom: 'clamp(20px, 4vh, 32px)' }}>
                        <div style={{
                            padding: 'clamp(12px, 2vh, 16px)',
                            background: token.colorPrimary,
                            borderRadius: '12px',
                            color: token.colorWhite
                        }}>
                            <Title level={1} style={{ color: token.colorWhite, marginBottom: '8px', fontSize: 'clamp(24px, 5vw, 32px)', fontWeight: 'bold' }}>
                                Ủng hộ MuMuAINovel
                            </Title>
                            <Text type="secondary" style={{ color: token.colorWhite, fontSize: 'clamp(11px, 2vw, 13px)', letterSpacing: '2px' }}>
                                SUPPORT MuMuAINovel
                            </Text>
                            <Title level={4} style={{ color: token.colorWhite, marginTop: '8px', marginBottom: '8px' }}>
                                📚 MuMuAINovel - Trợ lý sáng tác tiểu thuyết thông minh dựa trên AI
                            </Title>
                        </div>
                    </div>

                    {/* Quyền lợi riêng khi ủng hộ */}
                    <div style={{ marginBottom: 'clamp(24px, 4vh, 32px)' }}>
                        <Title level={3} style={{ textAlign: 'center', marginBottom: 'clamp(16px, 3vh, 20px)', fontSize: 'clamp(18px, 3vw, 24px)' }}>
                            <CheckCircleOutlined style={{ color: token.colorSuccess, marginRight: '8px' }} />
                            Quyền lợi riêng khi ủng hộ
                        </Title>

                        <Row
                            gutter={[{ xs: 8, sm: 12, md: 16 }, { xs: 8, sm: 12, md: 16 }]}
                            wrap={false}
                            style={{ overflowX: 'auto', paddingBottom: '4px' }}
                        >
                            {benefits.map((benefit, index) => (
                                <Col key={index} flex="1" style={{ minWidth: '200px' }}>
                                    <Card
                                        hoverable
                                        style={{
                                            height: '100%',
                                            textAlign: 'center',
                                            borderRadius: '10px',
                                            boxShadow: `0 2px 8px ${alphaColor(token.colorTextBase, 0.12)}`
                                        }}
                                        styles={{
                                            body: { padding: 'clamp(16px, 3vh, 20px) clamp(12px, 2vw, 16px)' }
                                        }}
                                    >
                                        <div style={{ marginBottom: '12px' }}>
                                            {benefit.icon}
                                        </div>
                                        <Title level={5} style={{ marginBottom: '8px', fontSize: 'clamp(14px, 2.5vw, 16px)' }}>{benefit.title}</Title>
                                        <Paragraph style={{ color: token.colorTextSecondary, marginBottom: 0, fontSize: 'clamp(12px, 2vw, 13px)' }}>
                                            {benefit.description}
                                        </Paragraph>
                                        {benefit.price && (
                                            <Paragraph style={{ color: token.colorWarning, margin: '4px 0 0', fontSize: 'clamp(12px, 2vw, 13px)', fontWeight: 600 }}>
                                                {benefit.price}
                                            </Paragraph>
                                        )}
                                    </Card>
                                </Col>
                            ))}
                        </Row>
                    </div>

                    {/* Chọn số tiền */}
                    <div>
                        <Title level={3} style={{ textAlign: 'center', marginBottom: 'clamp(16px, 3vh, 20px)', fontSize: 'clamp(18px, 3vw, 24px)' }}>
                            <HeartOutlined style={{ color: token.colorError, marginRight: '8px' }} />
                            Chọn số tiền
                        </Title>

                        <Row gutter={[{ xs: 8, sm: 12, md: 16 }, { xs: 8, sm: 12, md: 16 }]} justify="center">
                            {sponsorOptions.map((option, index) => (
                                <Col xs={12} sm={8} md={6} lg={6} xl={4} key={index}>
                                    <Card
                                        hoverable
                                        onClick={() => handleCardClick(option)}
                                        style={{
                                            textAlign: 'center',
                                            borderRadius: '10px',
                                            boxShadow: `0 2px 8px ${alphaColor(token.colorTextBase, 0.12)}`,
                                            cursor: 'pointer',
                                            transition: 'all 0.3s',
                                            border: `2px solid ${token.colorBorder}`
                                        }}
                                        styles={{
                                            body: { padding: 'clamp(16px, 3vh, 20px) clamp(10px, 2vw, 12px)' }
                                        }}
                                        onMouseEnter={(e) => {
                                            e.currentTarget.style.transform = 'translateY(-8px)';
                                            e.currentTarget.style.boxShadow = `0 8px 24px ${alphaColor(token.colorPrimary, 0.3)}`;
                                            e.currentTarget.style.borderColor = token.colorPrimary;
                                        }}
                                        onMouseLeave={(e) => {
                                            e.currentTarget.style.transform = 'translateY(0)';
                                            e.currentTarget.style.boxShadow = `0 2px 8px ${alphaColor(token.colorTextBase, 0.12)}`;
                                            e.currentTarget.style.borderColor = token.colorBorder;
                                        }}
                                    >
                                        <Title level={3} style={{
                                            color: token.colorPrimary,
                                            marginBottom: '4px',
                                            fontSize: 'clamp(20px, 4vw, 28px)',
                                            fontWeight: 'bold'
                                        }}>
                                            {option.description}
                                        </Title>
                                        <Text style={{ fontSize: 'clamp(12px, 2vw, 14px)', color: token.colorTextSecondary }}>
                                            {option.label}
                                        </Text>
                                    </Card>
                                </Col>
                            ))}
                        </Row>
                    </div>

                    <Divider style={{ margin: 'clamp(16px, 3vh, 18px) 0' }} />

                    {/* 感谢文案 */}
                    <div style={{
                        textAlign: 'center',
                        padding: 'clamp(16px, 3vw, 20px)',
                        background: token.colorFillQuaternary,
                        borderRadius: '10px',
                        marginTop: 'auto'
                    }}>
                        <Title level={4} style={{ marginBottom: '12px', fontSize: 'clamp(16px, 3vw, 20px)' }}>
                            💖 Cảm ơn bạn đã ủng hộ dự án MuMuAINovel
                        </Title>
                        <Paragraph style={{ fontSize: 'clamp(12px, 2vw, 14px)', color: token.colorTextSecondary, marginBottom: '12px' }}>
                            Sự ủng hộ của bạn là động lực để tôi tiếp tục cập nhật dự án và mang lại trải nghiệm sáng tác AI tốt hơn!
                        </Paragraph>
                        {/* <div style={{ fontSize: 'clamp(18px, 3vw, 24px)' }}>
                            <StarOutlined style={{ color: token.colorWarning, margin: '0 4px' }} />
                            <StarOutlined style={{ color: token.colorWarning, margin: '0 4px' }} />
                            <StarOutlined style={{ color: token.colorWarning, margin: '0 4px' }} />
                            <StarOutlined style={{ color: token.colorWarning, margin: '0 4px' }} />
                            <StarOutlined style={{ color: token.colorWarning, margin: '0 4px' }} />
                        </div> */}
                    </div>
                </div>
            </div>

            {/* 二维码弹窗 */}
            <Modal
                title={
                    <div style={{ textAlign: 'center' }}>
                        <Title level={3} style={{ marginBottom: '8px' }}>
                            {selectedOption?.description} {selectedOption?.label}
                        </Title>
                        <Text type="secondary">Vui lòng dùng WeChat quét mã để thanh toán</Text>
                    </div>
                }
                open={modalVisible}
                onCancel={() => setModalVisible(false)}
                footer={[
                    <Button key="close" type="primary" onClick={() => setModalVisible(false)}>
                        Đóng
                    </Button>
                ]}
                width={400}
                centered
            >
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                    <Image
                        src={selectedOption?.image}
                        alt={`Mã ủng hộ ${selectedOption?.description}`}
                        style={{
                            maxWidth: '280px',
                            borderRadius: '8px',
                            border: `1px solid ${token.colorBorderSecondary}`
                        }}
                        preview={false}
                    />
                    <Paragraph style={{ marginTop: '20px', color: token.colorTextSecondary }}>
                        Quét mã QR để hoàn tất thanh toán
                    </Paragraph>
                    <Paragraph style={{ color: token.colorTextTertiary, fontSize: '12px' }}>
                        Sau thanh toán có thể thêm WeChat/QQ để liên hệ nhận quyền lợi
                    </Paragraph>
                </div>
            </Modal>
        </div>
    );
}