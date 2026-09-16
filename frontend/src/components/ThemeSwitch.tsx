import { Segmented, Tooltip } from 'antd';
import { BulbOutlined, MoonOutlined, DesktopOutlined } from '@ant-design/icons';
import { useThemeMode } from '../theme/useThemeMode';
import type { ThemeMode } from '../theme/themeStorage';
import type { ReactNode } from 'react';

interface ThemeSwitchProps {
  size?: 'small' | 'middle' | 'large';
  block?: boolean;
}

const options: Array<{ value: ThemeMode; label: ReactNode }> = [
  {
    value: 'light',
    label: (
      <Tooltip title="Chế độ sáng">
        <BulbOutlined />
      </Tooltip>
    ),
  },
  {
    value: 'dark',
    label: (
      <Tooltip title="Chế độ tối">
        <MoonOutlined />
      </Tooltip>
    ),
  },
  {
    value: 'system',
    label: (
      <Tooltip title="Theo hệ thống">
        <DesktopOutlined />
      </Tooltip>
    ),
  },
];

export default function ThemeSwitch({ size = 'middle', block = false }: ThemeSwitchProps) {
  const { mode, setMode } = useThemeMode();

  return (
    <Segmented
      size={size}
      value={mode}
      onChange={(value) => setMode(value as ThemeMode)}
      options={options}
      block={block}
    />
  );
}
