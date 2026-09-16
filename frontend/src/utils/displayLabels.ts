// Một số giá trị vẫn được lưu bằng tiếng Trung (hợp đồng dữ liệu với backend và dữ liệu cũ),
// nên chỉ dịch sang tiếng Việt tại thời điểm hiển thị.

const GENDER_LABELS: Record<string, string> = {
  '男': 'Nam',
  '女': 'Nữ',
  '其他': 'Khác',
  male: 'Nam',
  female: 'Nữ',
  other: 'Khác',
};

export const genderLabel = (value?: string | null): string =>
  value ? GENDER_LABELS[value] || value : '';

const GENRE_LABELS: Record<string, string> = {
  '玄幻': 'Huyền huyễn',
  '仙侠': 'Tiên hiệp',
  '武侠': 'Võ hiệp',
  '都市': 'Đô thị',
  '历史': 'Lịch sử',
  '科幻': 'Khoa học viễn tưởng',
  '奇幻': 'Kỳ ảo',
  '悬疑': 'Huyền nghi',
  '言情': 'Ngôn tình',
  '修仙': 'Tu tiên',
  '通用': 'Chung',
  '游戏': 'Game',
  '电竞': 'Thể thao điện tử',
  '军事': 'Quân sự',
  '现实': 'Hiện thực',
  '其他': 'Khác',
};

export const genreLabel = (value?: string | null): string =>
  value ? GENRE_LABELS[value] || value : '';

// Thể loại có thể là một chuỗi nhiều giá trị ngăn cách bởi dấu phẩy (kể cả dấu phẩy tiếng Trung cũ).
export const genreLabels = (value?: string | null): string[] =>
  value
    ? value
        .split(/[,，、]/)
        .map((part) => part.trim())
        .filter(Boolean)
        .map((part) => genreLabel(part))
    : [];

const PERSPECTIVE_LABELS: Record<string, string> = {
  '第一人称': 'Ngôi thứ nhất (tôi)',
  '第三人称': 'Ngôi thứ ba (anh/cô ấy)',
  '全知视角': 'Góc nhìn toàn tri',
  first_person: 'Ngôi thứ nhất (tôi)',
  third_person: 'Ngôi thứ ba (anh/cô ấy)',
  omniscient: 'Góc nhìn toàn tri',
};

export const perspectiveLabel = (value?: string | null): string =>
  value ? PERSPECTIVE_LABELS[value] || value : '';
