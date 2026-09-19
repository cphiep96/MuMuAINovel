import { useState, useEffect, useCallback } from 'react';
import { Card, Button, Modal, Form, Select, InputNumber, Input, message, Progress, Tag, Space, Divider, Typography, theme } from 'antd';
import { EditOutlined, PlusOutlined, DeleteOutlined, TrophyOutlined } from '@ant-design/icons';
import axios from 'axios';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

interface CareerDetail {
    id: string;
    character_id: string;
    career_id: string;
    career_name: string;
    career_type: 'main' | 'sub';
    current_stage: number;
    stage_name: string;
    stage_description?: string;
    stage_progress: number;
    max_stage: number;
    started_at?: string;
    reached_current_stage_at?: string;
    notes?: string;
}

interface Career {
    id: string;
    name: string;
    type: 'main' | 'sub';
    max_stage: number;
}

interface Props {
    characterId: string;
    projectId: string;
    editable?: boolean;
    onUpdate?: () => void;
}

export const CharacterCareerCard: React.FC<Props> = ({
    characterId,
    projectId,
    editable = false,
    onUpdate
}) => {
    const { token } = theme.useToken();
    const [mainCareer, setMainCareer] = useState<CareerDetail | null>(null);
    const [subCareers, setSubCareers] = useState<CareerDetail[]>([]);
    const [allCareers, setAllCareers] = useState<Career[]>([]);
    const [loading, setLoading] = useState(true);

    const [isMainModalOpen, setIsMainModalOpen] = useState(false);
    const [isSubModalOpen, setIsSubModalOpen] = useState(false);
    const [isProgressModalOpen, setIsProgressModalOpen] = useState(false);
    const [selectedCareer, setSelectedCareer] = useState<CareerDetail | null>(null);

    const [mainForm] = Form.useForm();
    const [subForm] = Form.useForm();
    const [progressForm] = Form.useForm();
    const [modal, contextHolder] = Modal.useModal();

    const fetchCharacterCareers = useCallback(async () => {
        try {
            setLoading(true);
            const response = await axios.get(
                `${API_BASE_URL}/api/careers/character/${characterId}/careers`,
                { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
            );
            setMainCareer(response.data.main_career || null);
            setSubCareers(response.data.sub_careers || []);
        } catch (error: unknown) {
            const axiosError = error as { response?: { data?: { detail?: string } } };
            message.error(axiosError.response?.data?.detail || 'Lấy thông tin nghề thất bại');
        } finally {
            setLoading(false);
        }
    }, [characterId]);

    const fetchAllCareers = useCallback(async () => {
        try {
            const response = await axios.get(`${API_BASE_URL}/api/careers`, {
                params: { project_id: projectId },
                headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
            });
            const main = response.data.main_careers || [];
            const sub = response.data.sub_careers || [];
            setAllCareers([...main, ...sub]);
        } catch (error: unknown) {
            console.error('Lấy danh sách nghề nghiệp thất bại:', error);
        }
    }, [projectId]);

    useEffect(() => {
        fetchCharacterCareers();
        if (editable) {
            fetchAllCareers();
        }
    }, [characterId, editable, fetchCharacterCareers, fetchAllCareers]);

    const handleSetMainCareer = async (values: { career_id: string; current_stage?: number; started_at?: string }) => {
        try {
            await axios.post(
                `${API_BASE_URL}/api/careers/character/${characterId}/careers/main`,
                values,
                { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
            );
            message.success('Đặt nghề chính thành công');
            setIsMainModalOpen(false);
            mainForm.resetFields();
            fetchCharacterCareers();
            onUpdate?.();
        } catch (error: unknown) {
            const axiosError = error as { response?: { data?: { detail?: string } } };
            message.error(axiosError.response?.data?.detail || 'Đặt nghề chính thất bại');
        }
    };

    const handleAddSubCareer = async (values: { career_id: string; current_stage?: number; started_at?: string }) => {
        try {
            await axios.post(
                `${API_BASE_URL}/api/careers/character/${characterId}/careers/sub`,
                values,
                { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
            );
            message.success('Thêm nghề phụ thành công');
            setIsSubModalOpen(false);
            subForm.resetFields();
            fetchCharacterCareers();
            onUpdate?.();
        } catch (error: unknown) {
            const axiosError = error as { response?: { data?: { detail?: string } } };
            message.error(axiosError.response?.data?.detail || 'Thêm nghề phụ thất bại');
        }
    };

    const handleUpdateProgress = async (values: { current_stage: number; stage_progress: number; reached_current_stage_at?: string; notes?: string }) => {
        if (!selectedCareer) return;

        try {
            await axios.put(
                `${API_BASE_URL}/api/careers/character/${characterId}/careers/${selectedCareer.career_id}/stage`,
                values,
                { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
            );
            message.success('Cập nhật giai đoạn nghề thành công');
            setIsProgressModalOpen(false);
            progressForm.resetFields();
            fetchCharacterCareers();
            onUpdate?.();
        } catch (error: unknown) {
            const axiosError = error as { response?: { data?: { detail?: string } } };
            message.error(axiosError.response?.data?.detail || 'Cập nhật giai đoạn nghề thất bại');
        }
    };

    const handleRemoveSubCareer = (careerId: string) => {
        modal.confirm({
            title: 'Xác nhận xóa',
            content: 'Xác nhận gỡ nghề phụ này?',
            centered: true,
            onOk: async () => {
                try {
                    await axios.delete(
                        `${API_BASE_URL}/api/careers/character/${characterId}/careers/${careerId}`,
                        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
                    );
                    message.success('Xóa nghề phụ thành công');
                    fetchCharacterCareers();
                    onUpdate?.();
                } catch (error: unknown) {
                    const axiosError = error as { response?: { data?: { detail?: string } } };
                    message.error(axiosError.response?.data?.detail || 'Xóa nghề phụ thất bại');
                }
            }
        });
    };

    const openEditProgress = (career: CareerDetail) => {
        setSelectedCareer(career);
        progressForm.setFieldsValue({
            current_stage: career.current_stage,
            stage_progress: career.stage_progress,
            reached_current_stage_at: career.reached_current_stage_at || '',
            notes: career.notes || ''
        });
        setIsProgressModalOpen(true);
    };

    const renderCareerInfo = (career: CareerDetail, isMain: boolean = false) => (
        <div key={career.id} style={{ marginBottom: 16 }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Space>
                    <TrophyOutlined style={{ color: isMain ? token.colorPrimary : token.colorTextTertiary }} />
                    <Text strong={isMain}>{career.career_name}</Text>
                    {isMain && <Tag color="blue">Chính</Tag>}
                </Space>
                {editable && (
                    <Space>
                        <Button size="small" icon={<EditOutlined />} onClick={() => openEditProgress(career)} />
                        {!isMain && (
                            <Button
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={() => handleRemoveSubCareer(career.career_id)}
                            />
                        )}
                    </Space>
                )}
            </Space>

            <div style={{ marginLeft: 24, marginTop: 8 }}>
                <Text type="secondary">
                    {career.stage_name} (Giai đoạn {career.current_stage}/{career.max_stage})
                </Text>
                {career.stage_description && (
                    <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
                        {career.stage_description}
                    </Paragraph>
                )}
                <Progress
                    percent={career.stage_progress}
                    size="small"
                    style={{ marginTop: 8 }}
                    format={(percent) => `${percent}%`}
                />
                {career.started_at && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                        Thời gian bắt đầu: {career.started_at}
                    </Text>
                )}
                {career.notes && (
                    <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
                        Ghi chú: {career.notes}
                    </Paragraph>
                )}
            </div>
        </div>
    );

    if (loading) {
        return <Card loading />;
    }

    return (
        <>
            {contextHolder}
            <Card
                title={
                    <Space>
                        <TrophyOutlined />
                        Thông tin nghề
                    </Space>
                }
                extra={
                    editable && !mainCareer && (
                        <Button
                            size="small"
                            icon={<PlusOutlined />}
                            onClick={() => {
                                mainForm.resetFields();
                                setIsMainModalOpen(true);
                            }}
                        >
                            Đặt nghề chính
                        </Button>
                    )
                }
            >
                {mainCareer ? (
                    <>
                        {renderCareerInfo(mainCareer, true)}

                        {subCareers.length > 0 && (
                            <>
                                <Divider />
                                <Text type="secondary">Nghề phụ</Text>
                                <div style={{ marginTop: 8 }}>
                                    {subCareers.map(career => renderCareerInfo(career, false))}
                                </div>
                            </>
                        )}

                        {editable && subCareers.length < 5 && (
                            <div style={{ textAlign: 'center', marginTop: 16 }}>
                                <Button
                                    size="small"
                                    icon={<PlusOutlined />}
                                    onClick={() => {
                                        subForm.resetFields();
                                        setIsSubModalOpen(true);
                                    }}
                                >
                                    Thêm nghề phụ
                                </Button>
                            </div>
                        )}
                    </>
                ) : (
                    <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: '20px 0' }}>
                        Chưa có thông tin nghề
                    </Text>
                )}
            </Card>

            {/* Đặt nghề chính */}
            <Modal
                title="Đặt nghề chính"
                open={isMainModalOpen}
                onCancel={() => setIsMainModalOpen(false)}
                footer={null}
            >
                <Form form={mainForm} layout="vertical" onFinish={handleSetMainCareer}>
                    <Form.Item label="Chọn nghề chính" name="career_id" rules={[{ required: true }]}>
                        <Select placeholder="Chọn nghề nghiệp">
                            {allCareers.filter(c => c.type === 'main').map(career => (
                                <Select.Option key={career.id} value={career.id}>
                                    {career.name} ({career.max_stage} giai đoạn)
                                </Select.Option>
                            ))}
                        </Select>
                    </Form.Item>
                    <Form.Item label="Giai đoạn hiện tại" name="current_stage" initialValue={1}>
                        <InputNumber min={1} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item label="Thời gian bắt đầu" name="started_at">
                        <Input placeholder="VD: lịch tu tiên năm 3000" />
                    </Form.Item>
                    <Form.Item>
                        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                            <Button onClick={() => setIsMainModalOpen(false)}>Hủy</Button>
                            <Button type="primary" htmlType="submit">Xác nhận</Button>
                        </Space>
                    </Form.Item>
                </Form>
            </Modal>

            {/* 添加Nghề phụ */}
            <Modal
                title="Thêm nghề phụ"
                open={isSubModalOpen}
                onCancel={() => setIsSubModalOpen(false)}
                footer={null}
            >
                <Form form={subForm} layout="vertical" onFinish={handleAddSubCareer}>
                    <Form.Item label="Chọn nghề phụ" name="career_id" rules={[{ required: true }]}>
                        <Select placeholder="Chọn nghề nghiệp">
                            {allCareers.filter(c => c.type === 'sub').map(career => (
                                <Select.Option key={career.id} value={career.id}>
                                    {career.name} ({career.max_stage} giai đoạn)
                                </Select.Option>
                            ))}
                        </Select>
                    </Form.Item>
                    <Form.Item label="Giai đoạn hiện tại" name="current_stage" initialValue={1}>
                        <InputNumber min={1} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item label="Thời gian bắt đầu" name="started_at">
                        <Input placeholder="VD: lịch tu tiên năm 3000" />
                    </Form.Item>
                    <Form.Item>
                        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                            <Button onClick={() => setIsSubModalOpen(false)}>Hủy</Button>
                            <Button type="primary" htmlType="submit">Thêm</Button>
                        </Space>
                    </Form.Item>
                </Form>
            </Modal>

            {/* 更新职业进度 */}
            <Modal
                title="Cập nhật giai đoạn nghề"
                open={isProgressModalOpen}
                onCancel={() => setIsProgressModalOpen(false)}
                footer={null}
            >
                {selectedCareer && (
                    <Form form={progressForm} layout="vertical" onFinish={handleUpdateProgress}>
                        <Text>Nghề: {selectedCareer.career_name}</Text>
                        <Divider style={{ margin: '12px 0' }} />
                        <Form.Item label="Giai đoạn hiện tại" name="current_stage" rules={[{ required: true }]}>
                            <InputNumber min={1} max={selectedCareer.max_stage} style={{ width: '100%' }} />
                        </Form.Item>
                        <Form.Item label="Tiến độ giai đoạn (0-100)" name="stage_progress" rules={[{ required: true }]}>
                            <InputNumber min={0} max={100} style={{ width: '100%' }} />
                        </Form.Item>
                        <Form.Item label="Thời điểm đạt tới" name="reached_current_stage_at">
                            <Input placeholder="VD: lịch tu tiên năm 3001" />
                        </Form.Item>
                        <Form.Item label="Ghi chú" name="notes">
                            <TextArea rows={2} placeholder="VD: đột phá tới Kim Đan kỳ" />
                        </Form.Item>
                        <Form.Item>
                            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                                <Button onClick={() => setIsProgressModalOpen(false)}>Hủy</Button>
                                <Button type="primary" htmlType="submit">Cập nhật</Button>
                            </Space>
                        </Form.Item>
                    </Form>
                )}
            </Modal>
        </>
    );
};

export default CharacterCareerCard;