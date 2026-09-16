import { useContext } from 'react';
import { ThemeModeContext } from './themeContext';
import type { ThemeContextValue } from './themeContext';

export const useThemeMode = (): ThemeContextValue => {
  const context = useContext(ThemeModeContext);
  if (!context) {
    throw new Error('useThemeMode must be used inside ThemeProvider');
  }
  return context;
};
