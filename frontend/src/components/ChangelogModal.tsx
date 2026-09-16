import { Modal, Timeline, Tag, Avatar, Empty, Spin, Button, Space } from 'antd';
import { useState, useEffect } from 'react';
import {
  BugOutlined,
  StarOutlined,
  FileTextOutlined,
  BgColorsOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  ToolOutlined,
  QuestionCircleOutlined,
  GithubOutlined,
  ReloadOutlined,
  ClockCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import {
  fetchChangelog,
  groupChangelogByDate,
  cacheChangelog,
  clearChangelogCache,
  type ChangelogEntry,
} from '../services/changelogService';

interface ChangelogModalProps {
  visible: boolean;
  onClose: () => void;
}

// 提交类型图标和颜色配置
const typeConfig: Record<ChangelogEntry['type'], { icon: React.ReactNode; color: string; label: string }> = {
  feature: { icon: <StarOutlined />, color: 'green', label: 'Tính năng mới' },
  update: { icon: <SyncOutlined />, color: 'geekblue', label: 'Cập nhật' },
  fix: { icon: <BugOutlined />, color: 'red', label: 'Sửa lỗi' },
  docs: { icon: <FileTextOutlined />, color: 'blue', label: 'Tài liệu' },
  style: { icon: <BgColorsOutlined />, color: 'purple', label: 'Giao diện' },
  refactor: { icon: <ThunderboltOutlined />, color: 'orange', label: 'Tái cấu trúc' },
  perf: { icon: <ThunderboltOutlined />, color: 'gold', label: 'Hiệu năng' },
  test: { icon: <ExperimentOutlined />, color: 'cyan', label: 'Kiểm thử' },
  chore: { icon: <ToolOutlined />, color: 'default', label: 'Khác' },
  other: { icon: <QuestionCircleOutlined />, color: 'default', label: 'Khác' },
};

export default function ChangelogModal({ visible, onClose }: ChangelogModalProps) {
  const [changelog, setChangelog] = useState<ChangelogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  // 加载更新日志
  // 每次用户打开窗口时才同步获取最新数据，不自动刷新
  const loadChangelog = async (pageNum: number = 1, append: boolean = false) => {
    setLoading(true);
    setError(null);

    try {
      // 每次打开都从网络获取最新数据
      const entries = await fetchChangelog(pageNum, 30);

      if (entries.length === 0) {
        setHasMore(false);
      } else {
        if (append) {
          setChangelog(prev => [...prev, ...entries]);
        } else {
          setChangelog(entries);
          // 缓存第一页数据（用于分页加载时的数据持久化）
          if (pageNum === 1) {
            cacheChangelog(entries);
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lấy nhật ký cập nhật thất bại');
    } finally {
      setLoading(false);
    }
  };

  // 初始加载
  useEffect(() => {
    if (visible) {
      loadChangelog(1, false);
      setPage(1);
      setHasMore(true);
    }
  }, [visible]);

  // 加载更多
  const handleLoadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    loadChangelog(nextPage, true);
  };

  // 刷新（清除缓存并重新加载）
  const handleRefresh = () => {
    clearChangelogCache();
    setPage(1);
    setHasMore(true);
    loadChangelog(1, false);
  };

  // 按日期分组
  const groupedChangelog = groupChangelogByDate(changelog);
  const sortedDates = Array.from(groupedChangelog.keys()).sort((a, b) => b.localeCompare(a));

  // 格式化日期
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Hôm nay';
    if (diffDays === 1) return 'Hôm qua';
    if (diffDays < 7) return `${diffDays} ngày trước`;

    return date.toLocaleDateString('vi-VN', { year: 'numeric', month: 'long', day: 'numeric' });
  };

  // 格式化时间
  const formatTime = (dateStr: string) => {
    return new Date(dateStr).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <Modal
      title={
        <Space>
          <GithubOutlined />
          <span>Nhật ký cập nhật</span>
          <Button
            type="text"
            size="small"
            icon={<ReloadOutlined />}
            onClick={handleRefresh}
            loading={loading}
            title="Làm mới"
          />
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
      centered
      styles={{
        body: {
          maxHeight: '70vh',
          overflowY: 'auto',
          padding: '24px',
        },
      }}
    >
      {error && (
        <div style={{
          padding: '16px',
          marginBottom: '16px',
          background: 'var(--color-error-bg)',
          border: '1px solid var(--color-error-border)',
          borderRadius: '4px',
          color: 'var(--color-error)',
        }}>
          {error}
        </div>
      )}

      {loading && changelog.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" tip="Đang tải nhật ký cập nhật..." />
        </div>
      ) : changelog.length === 0 ? (
        <Empty description="Chưa có nhật ký cập nhật" />
      ) : (
        <>
          {sortedDates.map(date => {
            const entries = groupedChangelog.get(date) || [];

            return (
              <div key={date} style={{ marginBottom: '32px' }}>
                <div style={{
                  fontSize: '16px',
                  fontWeight: 600,
                  color: 'var(--color-primary)',
                  marginBottom: '16px',
                  paddingBottom: '8px',
                  borderBottom: '2px solid var(--color-border-secondary)',
                }}>
                  <ClockCircleOutlined style={{ marginRight: '8px' }} />
                  {formatDate(date)}
                </div>

                <Timeline>
                  {entries.map(entry => {
                    const config = typeConfig[entry.type] || typeConfig.other;

                    return (
                      <Timeline.Item
                        key={entry.id}
                        dot={
                          <div style={{
                            width: '24px',
                            height: '24px',
                            borderRadius: '50%',
                            background: 'var(--color-bg-container)',
                            border: `2px solid ${config.color === 'default' ? 'var(--color-border)' : config.color}`,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '12px',
                          }}>
                            {config.icon}
                          </div>
                        }
                      >
                        <div style={{ marginLeft: '8px' }}>
                          <Space size="small" wrap>
                            <Tag color={config.color} icon={config.icon}>
                              {config.label}
                            </Tag>
                            {entry.scope && (
                              <Tag color="blue">{entry.scope}</Tag>
                            )}
                            <span style={{ color: 'var(--color-text-tertiary)', fontSize: '12px' }}>
                              {formatTime(entry.date)}
                            </span>
                          </Space>

                          <div style={{
                            marginTop: '8px',
                            fontSize: '14px',
                            lineHeight: '1.6',
                            color: 'var(--color-text-primary)',
                          }}>
                            {entry.message}
                          </div>

                          <Space size="small" style={{ marginTop: '8px' }}>
                            {entry.author.avatar && (
                              <Avatar size="small" src={entry.author.avatar} />
                            )}
                            <span style={{ color: 'var(--color-text-secondary)', fontSize: '13px' }}>
                              {entry.author.username || entry.author.name}
                            </span>
                            <a
                              href={entry.commitUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ fontSize: '12px' }}
                            >
                              Xem commit
                            </a>
                          </Space>
                        </div>
                      </Timeline.Item>
                    );
                  })}
                </Timeline>
              </div>
            );
          })}

          {
            hasMore && (
              <div style={{ textAlign: 'center', marginTop: '24px' }}>
                <Button
                  type="default"
                  onClick={handleLoadMore}
                  loading={loading}
                >
                  Tải thêm
                </Button>
              </div>
            )
          }

          {
            !hasMore && changelog.length > 0 && (
              <div style={{
                textAlign: 'center',
                color: 'var(--color-text-tertiary)',
                padding: '16px 0',
                fontSize: '14px',
              }}>
                Đã hiển thị toàn bộ nhật ký cập nhật
              </div>
            )
          }
        </>
      )}

      <div style={{
        marginTop: '24px',
        padding: '12px',
        background: 'var(--color-info-bg)',
        borderRadius: '4px',
        border: '1px solid var(--color-info-border)',
        fontSize: '13px',
        color: 'var(--color-primary)',
      }}>
        💡 Gợi ý: Mỗi lần mở cửa sổ sẽ tự lấy nhật ký cập nhật mới nhất, dữ liệu từ lịch sử commit GitHub
      </div>
    </Modal >
  );
}