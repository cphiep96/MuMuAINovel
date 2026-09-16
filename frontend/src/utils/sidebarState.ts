const SIDEBAR_COLLAPSED_STORAGE_KEY = 'mumu_sidebar_collapsed';

export const getStoredSidebarCollapsed = (): boolean => {
  if (typeof window === 'undefined') {
    return false;
  }

  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === '1';
  } catch (error) {
    console.warn('Đọc trạng thái thanh bên thất bại:', error);
    return false;
  }
};

export const setStoredSidebarCollapsed = (collapsed: boolean): void => {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, collapsed ? '1' : '0');
  } catch (error) {
    console.warn('Lưu trạng thái thanh bên thất bại:', error);
  }
};

export const getSidebarCollapsedStorageKey = (): string => SIDEBAR_COLLAPSED_STORAGE_KEY;
