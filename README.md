# MuMuAINovel 📚✨

<div align="center">

![Version](https://img.shields.io/badge/version-1.5.5-blue.svg)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-green.svg)
![React](https://img.shields.io/badge/react-18.3.1-blue.svg)
![License](https://img.shields.io/badge/license-GPL%20v3-blue.svg)

**基于 AI 的智能小说创作助手**

[特性](#-特性) • [快速开始](#-快速开始) • [配置说明](#%EF%B8%8F-配置说明) • [项目结构](#-项目结构)

</div>

---

<div align="center">

## 💬 加入交流群

欢迎扫码加入 QQ 交流群，一起交流 AI 小说创作心得、反馈问题、获取最新动态！

<img src="frontend/public/qq.jpg" alt="QQ交流群二维码" width="300" />

</div>

---

<div align="center">

## 💖 支持项目

如果这个项目对你有帮助，欢迎通过以下方式支持开发：

**[☕ 请我喝杯咖啡](https://mumuverse.space:1588/)**

**[🌐 MuMuのAPI站点](https://api.mumuverse.space/register?aff=4NN8)**

> 在 MuMu の API 站点充值满 50 元及以上，也可以获得下方赞助专属权益。

### 🎁 赞助专属权益

| 权益 | 说明 |
|------|------|
| 📋 **优先需求响应** | 您的功能需求和问题反馈将获得优先处理 |
| 🚀 **Windows一键启动** | 获取免安装 EXE 程序，双击即可使用 |
| 💬 **专属技术支持** | 加入赞助者内部群，获得远程协助和配置指导 |

### ☕ 赞助 / API 站点充值档位

| 金额 | 描述 |
|------|------|
| ¥5 | 🌶️ 一包辣条 |
| ¥10 | 🍱 一顿拼好饭 |
| ¥20 | ☕ 一杯咖啡 |
| ¥50 | 🍖 一次烧烤  |
| ¥99 | 🍲 一顿海底捞 |

您的支持是我持续开发的动力！🙏

</div>

---

## 🤝 合作推广

### 【ApophisCode 中转站合作&推广】

<div align="center">

<img src="https://mumuverse.space:1527/i/2026/09/15/6aa8efe7de888.png" alt="ApophisCode 中转站" width="600" />

</div>

📚 **灵感来了，别让额度先没了！**

MuMuAINovel 写大纲、搭世界观、生成章节、润色重写，长篇创作更需要稳定又实惠的模型补给。  
MuMuAINovel 支持第三方 AI API，获取 Key 后按站内文档配置即可。

🚀 **ApophisCode 中转站全新启航，限时福利倍率：**
- 🔥 **Claude Fable 5.1 满血 Max**：1.4x
- ⚡ **Claude Opus 5 Kiro**：0.25x
- 💫 **GPT-6 Astra**：0.08x

- 📍 **交流群**：425421707
- ✈️ **起飞站**：[https://www.apophis.uk/](https://www.apophis.uk/)

🔥 **给 MuMuAINovel 补足火力，今晚继续爆更！**  
🎁 **新用户进群绑定账号即赠尝鲜额度，每日签到还能继续领！**

---

## ✨ 特性

- 🤖 **多 AI 模型** - 支持 OpenAI、Gemini、Claude 等主流模型
- 📝 **智能向导** - AI 自动生成大纲、角色和世界观
- 👥 **角色管理** - 人物关系、组织架构可视化管理
- 📖 **章节编辑** - 支持创建、编辑、重新生成和润色
- 🌐 **世界观设定** - 构建完整的故事背景
- 🔐 **多种登录** - LinuxDO OAuth 或本地账户登录
- 💾 **PostgreSQL** - 生产级数据库，多用户数据隔离
- 🐳 **Docker 部署** - 一键启动，开箱即用

## 📸 项目预览

<details>

<summary>多图预警</summary>

<div align="center">

### 登录界面
![登录界面](images/1.png)

![登录界面](images/1-1.png)

### 主界面
![主界面](images/2.png)

![主界面（暗色）](images/2-1.png)

### 项目管理
![项目管理](images/3.png)

![项目管理](images/3-1.png)

### 赞助我 💖
![赞助我](images/4.png)

![赞助我](images/4-1.png)

</div>

</details>

## 📋 TODO List

### ✅ 已完成功能

- [x] **灵感模式** - 创作灵感和点子生成
- [x] **自定义写作风格** - 支持自定义 AI 写作风格
- [x] **数据导入导出** - 项目数据的导入导出
- [x] **Prompt 调整界面** - 可视化编辑 Prompt 模板
- [x] **章节字数限制** - 用户可设置生成字数
- [x] **思维链与章节关系图谱** - 可视化章节逻辑关系
- [x] **根据分析一键重写** - 根据分析建议重新生成
- [x] **Linux DO 自动创建账号** - OAuth 登录自动生成账号
- [x] **职业等级体系** - 自定义职业和等级系统，支持修仙境界、魔法等级等多种体系
- [x] **角色/组织卡片导入导出** - 单独导出角色和组织卡片，支持跨项目数据共享
- [x] **伏笔管理** - 智能追踪剧情伏笔，提醒未回收线索，可视化伏笔时间线
- [x] **提示词工坊** - 社区驱动的 Prompt 模板分享平台，一键导入优质提示词
- [x] **拆书功能** - 目前呼声比较高的功能，一键拆书，给当年的ta一个圆满的结局
- [x] **导出视频** - 章节一键生成 storyboard、MP4 成片与 SRT 字幕（本地 FFmpeg 兜底 + provider AI image-to-video: xAI Grok Imagine / Google Veo / OpenAI 兼容）

### 📝 规划中功能

......

> 💡 欢迎提交 Issue 或 Pull Request！

## 🎬 Xuất phim từ chương (storyboard → MP4/SRT, có provider chuyển động AI)

Chọn một hoặc nhiều chương → hệ thống tự chia **storyboard theo cảnh** → dựng **MP4** kèm **phụ đề SRT**.
Mỗi phân cảnh có thể được dựng theo một trong ba chế độ **chuyển động (motion)**:

| Chế độ | Cách dựng | Chi phí | Điều kiện |
|--------|-----------|---------|-----------|
| `local` (mặc định) | **FFmpeg cục bộ**: ảnh bìa/ảnh phân cảnh → hiệu ứng pan/zoom (Ken Burns); không có ảnh thì sinh nền gradient/placeholder | Miễn phí (CPU/GPU máy chủ) | Cần FFmpeg |
| `remote` | **Provider AI image-to-video**: ảnh phân cảnh làm khung đầu → clip thật do provider tạo | **Tính phí theo từng phân cảnh** | Cần FFmpeg (ghép/mux), API key và ảnh tham chiếu |
| `hybrid` | Ưu tiên provider AI; nếu provider lỗi và policy cho phép thì dựng lại phân cảnh đó bằng FFmpeg cục bộ | Chỉ tính phí cho các lần gọi AI đã thực hiện | Như `remote` + policy `hybrid_fallback_on_error` |

Ngoài ba chế độ trên, có thể bật thêm **tạo ảnh phân cảnh** (`generate_scene_images`) bằng image provider
(Meta Model API — **Muse Image 1.0**): mỗi phân cảnh được sinh một ảnh AI (`assets/scene_XXX.webp`), ảnh này được dùng làm
ảnh tham chiếu cho provider video (xAI/Veo/OpenAI) — hoặc làm nền Ken Burns ở chế độ `local`. Khi bật, ảnh cảnh do AI tạo
được ưu tiên hơn ảnh bìa dự án và placeholder.

> ⚠️ **Chế độ cục bộ không tạo cảnh AI mới**: nó chỉ đưa ảnh có sẵn (ảnh AI đã tạo, ảnh thủ công, ảnh bìa) vào chuyển
> động nhẹ (pan/zoom) hoặc dựng nền placeholder. Muốn có video chuyển động do AI sinh, phải chọn `remote`/`hybrid`
> **và** cấu hình API key — nếu thiếu key, API trả lỗi 503 nêu rõ tên biến môi trường còn thiếu, **không** âm thầm chạy tiếp.
> Tương tự, không bật tạo ảnh thì pipeline không gọi provider ảnh nào.

### 1. Yêu cầu FFmpeg

Mọi chế độ đều cần FFmpeg để ghép clip, chèn phụ đề và probe thời lượng.

```bash
# Debian/Ubuntu
sudo apt-get install -y ffmpeg

# macOS
brew install ffmpeg

# Windows: tải bản build tại https://www.gyan.dev/ffmpeg/builds/ rồi thêm vào PATH
ffmpeg -version
```

Nếu FFmpeg nằm ngoài `PATH`, đặt biến môi trường `VIDEO_FFMPEG_BINARY` trỏ tới file thực thi.
Khi thiếu FFmpeg, giao diện hiển thị cảnh báo và API trả lỗi 503 rõ ràng (không dựng nửa vời).

### 2. Provider chuyển động đã tích hợp

Hợp đồng provider rất nhỏ: `submit` → `poll` (backoff + giới hạn wall-clock + tín hiệu hủy) → `download` (kiểm tra
SSRF/MIME/dung lượng) → ghép phim. Thêm provider mới chỉ cần implement 4 phương thức trong
`backend/app/services/video_export/providers/` và đăng ký ở `registry.py`.

| Provider | Endpoint thực tế | Poll | Tải clip | Hủy | Idempotency |
|----------|------------------|------|----------|-----|-------------|
| `local_ffmpeg` | — (FFmpeg CLI) | — | — | ✅ (dừng tiến trình) | ✅ |
| `xai_grok_imagine` | `POST {base}/videos/generations` → `{"request_id"}` | `GET {base}/videos/{request_id}` (`status`: `pending`/`done`/`failed`/`expired`, `progress`) | `video.url` (CDN, **không** gửi kèm API key) | ❌ (API chưa có endpoint hủy) | ❌ |
| `google_veo` (Gemini API) | `POST {base}/models/{model}:predictLongRunning` → `{"name": "models/.../operations/..."}` | `GET {base}/{operation_name}` cho tới `done: true` | `response.generateVideoResponse.generatedSamples[0].video.uri` (kèm `x-goog-api-key`) | ❌ | ❌ |
| `openai_compatible` | `POST {base}/videos` (multipart: `model`, `prompt`, `size`, `seconds`, `input_reference`) | `GET {base}/videos/{id}` (`queued`/`in_progress`/`completed`/`failed`, `progress`) | `GET {base}/videos/{id}/content` | ❌ | ✅ (header `Idempotency-Key`) |

Chi tiết request/response tương ứng tài liệu công khai:
[xAI videos](https://docs.x.ai/developers/rest-api-reference/inference/videos) ·
[Gemini Veo](https://ai.google.dev/gemini-api/docs/veo) ·
[OpenAI Videos](https://developers.openai.com/api/reference/resources/videos).

### 2b. Provider tạo ảnh phân cảnh đã tích hợp

| Provider | Endpoint thực tế | Kích thước | Ghi chú |
|----------|------------------|------------|---------|
| `meta_muse_image` (Meta Model API — `muse-image-1.0`) | `POST {base}/images/generations` với body `{model, prompt, n:1, size, response_format:"b64_json", output_format:"webp"}`; auth `Authorization: Bearer <META_MUSE_API_KEY>`; base mặc định `https://api.meta.ai/v1` | 16:9 → `1792x1024`, 9:16 → `1024x1792`, 1:1 → `1024x1024` | Ưu tiên `data[0].b64_json`; nếu provider chỉ trả `url` thì tải qua validator SSRF hiện có và **không gửi Authorization/API key** (kể cả khi host trùng `api.meta.ai`) |

- `reasoning_strength` là tuỳ chọn: chỉ gửi khi chọn. Theo tài liệu Meta hiện hành chỉ hỗ trợ `low`/`high`
  (whitelist cấu hình qua `META_MUSE_REASONING_STRENGTHS`, mặc định `low,high`; giá trị khác bị **từ chối trước khi gọi API**).
- `output_format` hỗ trợ `webp`/`png`/`jpeg` (mặc định `webp`, đổi bằng `META_MUSE_OUTPUT_FORMAT`); phần mở rộng file
  tương ứng: `.webp`/`.png`/`.jpg`.
- **Chi phí & rate limit:** Meta tính phí theo từng ảnh; bật tạo ảnh nghĩa là **mỗi phân cảnh = một lần gọi API**.
  Rate limit/quota theo tài khoản Meta Model API (xem trang pricing/quota của Meta) — hệ thống tôn trọng `429` bằng retry
  có backoff (số lần qua `VIDEO_IMAGE_MAX_RETRIES`) rồi trả lỗi rõ ràng cho phân cảnh đó, không tự hạ cấp sang provider khác.
- Ảnh tạo thành công được lưu trong `storage/generated_videos/{user}/{job}/assets/scene_XXX.webp` và **tái sử dụng** khi
  bấm "Dựng lại" (không sinh lại ⇒ không tính phí hai lần). Ảnh lỗi sẽ được tạo lại ở lần dựng kế tiếp.
- Nếu **không** bật tạo ảnh: pipeline giữ nguyên hành vi cũ (ảnh cảnh thủ công → ảnh bìa dự án → placeholder FFmpeg).

Giới hạn đã kiểm tra trước khi gửi request. Trường `duration_options`/`resolutions` **phụ thuộc từng model** và được trả về
trong `capabilities.motion_providers[].model_limits` để UI chỉ hiển thị lựa chọn hợp lệ; độ dài phân cảnh luôn được **co về
giá trị hợp lệ gần nhất** (không trả 400 chỉ vì narration dài/ngắn hơn clip):

| Provider / model | Thời lượng mỗi clip | Tỉ lệ | Độ phân giải | Ghi chú |
|------------------|---------------------|-------|--------------|---------|
| `xai_grok_imagine` | 1–15 giây (số nguyên, làm tròn) | 16:9, 9:16, 1:1 | 480p/720p/1080p | Không nhận placeholder; `generate_audio` mặc định tắt |
| `google_veo` · `veo-3.1-generate-preview` / `veo-3.1-fast-generate-preview` | **8 giây** | 16:9, 9:16 | 720p/1080p/**4k** | Veo 3.1 chỉ tạo video 8 giây; 4k chỉ có trên bản generate/fast |
| `google_veo` · `veo-3.1-lite-generate-preview` | **8 giây** | 16:9, 9:16 | 720p/1080p | Lite **không** hỗ trợ 4k (chọn 4k sẽ báo lỗi rõ) |
| `google_veo` · `veo-2.0-generate-001` | 5/6/7/8 giây | 16:9, 9:16 | 720p | Model cũ, giữ để tương thích |
| `openai_compatible` · `sora-2` | 4/8/12 giây | 16:9, 9:16 | 720p (`1280x720` / `720x1280`) | `input_reference` phải khớp `size` — hệ thống tự resize bằng FFmpeg, thiếu FFmpeg sẽ báo lỗi rõ |
| `openai_compatible` · `sora-2-pro` | 4/8/12 giây | 16:9, 9:16 | 720p + 1024p (`1792x1024` / `1024x1792`) | Chỉ bản **Pro** mới có 1024p; `sora-2` + `1024p` bị từ chối trước khi gọi API |

**Quy trình mỗi phân cảnh** (`remote`/`hybrid`): storyboard → (nếu bật tạo ảnh) ảnh AI
`<job>/assets/scene_XXX.webp` → chọn ảnh tham chiếu (ảnh phân cảnh — đuôi `.webp`/`.png`/`.jpg` tùy
`META_MUSE_OUTPUT_FORMAT` — rồi tới ảnh bìa dự án) → gửi request kèm prompt/duration/aspect/resolution →
poll có **backoff thực sự** (5s → 10s → 20s, có trần; provider báo tiến độ thì quay lại 5s) trong giới hạn wall-clock →
tải MP4 vào thư mục tác vụ → kiểm tra MIME/magic bytes/dung lượng/đường dẫn → ghép clip → mux SRT. Nếu một phân cảnh
không có ảnh tham chiếu mà provider không nhận placeholder, phân cảnh đó **thất bại với thông báo rõ**
(chế độ `hybrid` được phép dựng dự phòng bằng FFmpeg).

Phụ đề luôn bám theo **thời lượng clip thực tế** (`clip_duration_seconds`), nên video AI ngắn/dài hơn ước lượng
narration vẫn không lệch tiếng.

> **Lưu ý với gateway "OpenAI compatible" tự dựng:** hợp đồng `/videos` yêu cầu `size` nằm trong whitelist
> (`1280x720`, `720x1280`, `1792x1024`, `1024x1792`) và `input_reference` khớp đúng kích thước đó. Hệ thống map
> `motion_resolution` + `motion_aspect_ratio` sang các giá trị này (không dùng công thức suy diễn), kiểm tra theo **model**
> (`sora-2` chỉ 720p, `sora-2-pro` thêm 1024p), resize ảnh tham chiếu bằng FFmpeg nếu cần, và **từ chối rõ ràng** khi cặp
> giá trị không hợp lệ hoặc không thể resize. Nếu gateway khai báo một model khác, hãy thêm nó vào danh sách model của
> adapter (giới hạn mặc định khi đó là 720p). Gateway không hỗ trợ `Idempotency-Key` vẫn chạy được nhưng sẽ mất khả năng
> chống trùng ở tầng HTTP.

### 3. Biến môi trường (tuỳ chọn)

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `VIDEO_EXPORT_ENABLED` | `true` | Tắt/bật toàn bộ chức năng xuất phim |
| `VIDEO_FFMPEG_BINARY` | `ffmpeg` | Đường dẫn FFmpeg |
| `VIDEO_EXPORT_STORAGE_DIR` | `backend/storage/generated_videos` | Nơi lưu MP4/SRT |
| `VIDEO_MAX_CHAPTERS` | `10` | Số chương tối đa mỗi tác vụ |
| `VIDEO_MAX_SCENES` | `40` | Số phân cảnh tối đa mỗi tác vụ |
| `VIDEO_MAX_DURATION_SECONDS` | `900` | Tổng thời lượng tối đa |
| `VIDEO_MAX_OUTPUT_MB` | `512` | Dung lượng tối đa của MP4 |
| `VIDEO_MAX_ACTIVE_JOBS` | `2` | Số tác vụ chưa hoàn tất tối đa **mỗi người dùng** (tránh chiếm hết FFmpeg/đĩa) |
| `VIDEO_JOB_TIMEOUT_SECONDS` | `1800` | Trần thời gian (wall-clock) cho **cả** một tác vụ dựng phim |
| `VIDEO_CLAIM_TTL_BUFFER_SECONDS` | `300` | Buffer cho lease (execution claim): sau `VIDEO_JOB_TIMEOUT_SECONDS` + giá trị này mà không có nhịp tim, worker khác mới được tiếp quản |
| `VIDEO_RENDER_TIMEOUT_SECONDS` | `900` | Timeout cho **một lệnh** FFmpeg |
| `VIDEO_CANCEL_POLL_SECONDS` | `1.0` | Chu kỳ kiểm tra tín hiệu hủy khi FFmpeg đang chạy |
| `VIDEO_DEFAULT_RESOLUTION` | `1280x720` | Độ phân giải mặc định |
| `VIDEO_ALLOWED_RESOLUTIONS` | `1280x720,1920x1080,854x480` | Whitelist độ phân giải |
| `VIDEO_TTS_ENABLED` | `false` | Bật tổng hợp giọng đọc (mặc định tắt → video im lặng) |
| `VIDEO_TTS_BASE_URL` / `VIDEO_TTS_API_KEY` / `VIDEO_TTS_MODEL` / `VIDEO_TTS_VOICE` | — | Cấu hình TTS tương thích OpenAI `/audio/speech` |
| `VIDEO_MOTION_MODE` | `local` | Chế độ mặc định: `local`/`remote`/`hybrid` |
| `VIDEO_MOTION_PROVIDER` | — | Provider mặc định khi client không chọn (bỏ trống = provider remote đã cấu hình đầu tiên) |
| `VIDEO_MOTION_MODEL` | — | Model mặc định (phải nằm trong danh sách model của provider) |
| `VIDEO_MOTION_RESOLUTION` | — | Độ phân giải AI mặc định (`480p`/`720p`/`1080p`/`1024p`) |
| `VIDEO_MOTION_HYBRID_FALLBACK_ON_ERROR` | `true` | Policy fallback mặc định cho chế độ `hybrid` |
| `VIDEO_MOTION_POLL_INTERVAL_SECONDS` / `VIDEO_MOTION_POLL_MAX_INTERVAL_SECONDS` | `5` / `20` | Khoảng poll khởi điểm và trần backoff |
| `VIDEO_MOTION_OPERATION_TIMEOUT_SECONDS` | `900` | Wall-clock tối đa cho **một phân cảnh** chờ provider |
| `VIDEO_MOTION_MAX_RETRIES` | `2` | Số lần thử lại HTTP (chỉ với lỗi mạng/408/429/5xx) |
| `VIDEO_MOTION_REQUEST_TIMEOUT_SECONDS` / `VIDEO_MOTION_DOWNLOAD_TIMEOUT_SECONDS` | `120` / `300` | Timeout submit/poll và tải clip |
| `VIDEO_MOTION_MAX_CLIP_MB` | `128` | Dung lượng tối đa **một** clip tải về |
| `VIDEO_MOTION_DOWNLOAD_ALLOWED_HOSTS` | — | Whitelist host tải clip (CSV). Bỏ trống = chấp nhận mọi HTTPS công khai |
| `VIDEO_MOTION_ALLOW_INSECURE_LOCALHOST` | `false` | Chỉ bật khi phát triển với provider nội bộ dùng `http://localhost` |
| `VIDEO_MOTION_XAI_API_KEY` / `VIDEO_MOTION_XAI_BASE_URL` / `VIDEO_MOTION_XAI_MODEL` | — / `https://api.x.ai/v1` / `grok-imagine-video-1.5` | xAI Grok Imagine |
| `VIDEO_MOTION_XAI_GENERATE_AUDIO` | `false` | Grok Imagine hỗ trợ âm thanh gốc; mặc định tắt để thời lượng clip khớp narration |
| `VIDEO_MOTION_GEMINI_API_KEY` / `VIDEO_MOTION_GEMINI_BASE_URL` / `VIDEO_MOTION_GEMINI_MODEL` | — / `https://generativelanguage.googleapis.com/v1beta` / `veo-3.1-generate-preview` | Google Veo qua Gemini API |
| `VIDEO_MOTION_VEO_PERSON_GENERATION` | `allow_adult` | Tham số `personGeneration` gửi cho Veo (một số khu vực yêu cầu `dont_allow`) |
| `VIDEO_MOTION_OPENAI_API_KEY` / `VIDEO_MOTION_OPENAI_BASE_URL` / `VIDEO_MOTION_OPENAI_MODEL` | — / — / `sora-2` | API video tương thích OpenAI (cần cả base URL và key) |
| `VIDEO_IMAGE_ENABLED` | `true` | Tắt/bật chức năng tạo ảnh phân cảnh (khi tắt, UI không cho bật và API trả 503) |
| `VIDEO_IMAGE_PROVIDER` | — | Provider ảnh mặc định (hiện có `meta_muse_image`) |
| `VIDEO_IMAGE_MODEL` / `VIDEO_IMAGE_ASPECT_RATIO` / `VIDEO_IMAGE_REASONING_STRENGTH` | — | Giá trị mặc định cho model/tỉ lệ/reasoning strength |
| `VIDEO_IMAGE_TIMEOUT_SECONDS` / `VIDEO_IMAGE_MAX_RETRIES` / `VIDEO_IMAGE_MAX_MB` | `120` / `2` / `16` | Timeout, số lần retry (mạng/408/429/5xx) và giới hạn dung lượng mỗi ảnh |
| `IMAGE_ALLOW_INSECURE_LOCALHOST` | `false` | Chỉ bật khi phát triển với image provider chạy `http://localhost` |
| `META_MUSE_API_KEY` (alias: `MODEL_API_KEY`) | — | API key Meta Model API — **không** trả về client, không ghi log/DB |
| `META_MUSE_BASE_URL` | `https://api.meta.ai/v1` | Base URL Meta Model API (phải là HTTPS, trừ localhost khi bật cờ dev) |
| `META_MUSE_MODEL` | `muse-image-1.0` | Model tạo ảnh |
| `META_MUSE_OUTPUT_FORMAT` | `webp` | `webp`/`png`/`jpeg` |
| `META_MUSE_REASONING_STRENGTHS` | `low,high` | Whitelist giá trị reasoning strength được gửi (docs Meta hiện chỉ có `low`/`high`) |

> Không có khoá API nào được hard-code. Không có chế độ nào tự động "thử provider cho vui": `local` không gọi API,
> `remote` không bao giờ âm thầm rơi về FFmpeg, `hybrid` chỉ fallback khi policy `hybrid_fallback_on_error` bật và
> luôn ghi lại `provider_error` + `motion_fallback_used` cho từng phân cảnh.

**Ví dụ `.env` (chỉ chọn một hoặc vài provider):**

```env
# Bật video AI thật bằng xAI Grok Imagine
VIDEO_MOTION_MODE=hybrid
VIDEO_MOTION_PROVIDER=xai_grok_imagine
VIDEO_MOTION_MODEL=grok-imagine-video-1.5
VIDEO_MOTION_RESOLUTION=720p
VIDEO_MOTION_XAI_API_KEY=xai-xxxxxxxxxxxxxxxx
VIDEO_MOTION_HYBRID_FALLBACK_ON_ERROR=true

# Hoặc Google Veo (Gemini API)
# VIDEO_MOTION_PROVIDER=google_veo
# VIDEO_MOTION_GEMINI_API_KEY=AIza...
# VIDEO_MOTION_GEMINI_MODEL=veo-3.1-generate-preview

# Hoặc endpoint tương thích OpenAI (Sora / gateway tự dựng)
# VIDEO_MOTION_PROVIDER=openai_compatible
# VIDEO_MOTION_OPENAI_BASE_URL=https://api.openai.com/v1
# VIDEO_MOTION_OPENAI_API_KEY=sk-...
# VIDEO_MOTION_OPENAI_MODEL=sora-2

# Chỉ phát triển nội bộ với provider chạy http://localhost
# VIDEO_MOTION_ALLOW_INSECURE_LOCALHOST=true
# IMAGE_ALLOW_INSECURE_LOCALHOST=true

# Tạo ảnh phân cảnh bằng Meta Model API (Muse Image 1.0)
# ⚠️ Key là bí mật: chỉ đặt trong .env cục bộ (đã bị .gitignore) hoặc secret manager của nền tảng triển khai.
#    Tuyệt đối không commit key, không dán vào issue/PR/log.
META_MUSE_API_KEY=<your-meta-model-api-key>
META_MUSE_BASE_URL=https://api.meta.ai/v1
META_MUSE_MODEL=muse-image-1.0
META_MUSE_OUTPUT_FORMAT=webp
VIDEO_IMAGE_ENABLED=true
# VIDEO_IMAGE_ASPECT_RATIO=16:9
# VIDEO_IMAGE_REASONING_STRENGTH=medium
```

> **Bảo mật key:** hệ thống chỉ đọc key từ biến môi trường; key không xuất hiện trong response, log hay database, và
> **không** bao giờ được gửi tới host khác host của provider (kể cả khi ảnh trả về dạng URL CDN). Biến môi trường còn thiếu
> chỉ được báo dưới dạng *tên biến* trong `capabilities`/thông báo lỗi.

### 4. Cách dùng

1. Vào dự án → menu bên trái → **Xuất phim từ chương**.
2. Chọn chương (chương chưa có nội dung sẽ bị khoá), chọn độ phân giải/FPS/số ký tự mỗi cảnh.
3. Chọn **Chuyển động video**:
   - **Cục bộ (FFmpeg)** — mặc định, miễn phí;
   - **Provider AI (tính phí)** — chọn provider/model/độ phân giải/tỉ lệ; UI hiển thị ghi chú chi phí và **vô hiệu hoá**
     provider chưa cấu hình (kèm danh sách biến môi trường còn thiếu);
   - **Kết hợp (AI ưu tiên)** — thêm công tắc "Cho phép dựng dự phòng bằng FFmpeg cục bộ".
   Khi chọn chế độ AI, công tắc TTS bị tắt (clip do provider trả về đã có âm thanh riêng, hệ thống không ghép TTS vào).
4. (Tuỳ chọn) bật **Tạo ảnh cảnh bằng Meta Muse (tính phí)** — chọn provider/model/kích thước/tỉ lệ/mức suy luận; UI chỉ cho
   bật khi provider đã được cấu hình và hiển thị rõ "mỗi phân cảnh là một lần gọi API". Ảnh tạo ra được dùng làm ảnh tham
   chiếu cho video AI (hoặc nền Ken Burns ở chế độ cục bộ).
5. Bấm **Tạo tác vụ xuất phim** → theo dõi tiến độ, xem storyboard từng cảnh (provider, model, trạng thái ảnh, trạng thái remote,
   lỗi provider, clip dài bao nhiêu giây).
6. Khi hoàn tất: **Tải MP4** / **Tải SRT**. Có thể **Dựng lại** toàn bộ hoặc **dựng lại từng phân cảnh** bị lỗi.

Tác vụ xuất phim cũng xuất hiện trong bảng **Tác vụ nền** (góc phải dưới), có thể hủy/xem tiến độ như các tác vụ khác.

**Chi phí & credentials (quan trọng):**

- Mỗi phân cảnh ở chế độ `remote`/`hybrid` là **một lần gọi API có tính phí** (giá theo giây × độ phân giải do provider quy định).
- Nút tạo tác vụ bị vô hiệu hoá nếu provider chưa được cấu hình; API trả **503 kèm tên biến môi trường thiếu** trước khi tạo job.
- Hủy tác vụ sẽ dừng poll và **không tải clip tiếp**, nhưng các provider hiện tại chưa có endpoint hủy nên tác vụ đã gửi
  vẫn có thể tiếp tục chạy phía provider (chi phí đã phát sinh) — trạng thái phân cảnh được ghi `cancelled` để minh bạch.
- `Idempotency-Key` được gửi cho provider có hỗ trợ để việc thử lại HTTP không tạo request trùng; khi người dùng bấm
  "Dựng lại", khoá được sinh mới (đây là chủ đích: tạo phiên bản mới).
- **Chống trùng ở tầng dữ liệu (multi-worker):** trước khi vào pipeline, mỗi worker phải **giành execution claim**
  bằng một `UPDATE ... WHERE status IN ('pending','failed') AND (worker_token IS NULL OR claimed_at < hết hạn)`
  (hoặc `status='running'` với lease đã hết hạn — worker trước đã chết giữa chừng); chỉ worker có `rowcount = 1` mới chạy.
  Claim được **giải phóng** ở trạng thái kết thúc (và khi khởi động lại dịch vụ). Khi tiếp quản, hệ thống **không đụng** vào
  phân cảnh nên `motion_operation_id` vẫn được giữ để resume (không submit lại). Worker cũ, nếu còn sống, sẽ phát hiện
  lease đã đổi chủ ở lần kiểm tra kế tiếp và **tự dừng** (không ghi đè job của worker mới).
  Lease quá hạn (`VIDEO_JOB_TIMEOUT_SECONDS` + `VIDEO_CLAIM_TTL_BUFFER_SECONDS`) mới cho phép tiếp quản.
  Vẫn khuyến nghị chạy **một** worker cho `remote`/`hybrid` để chi phí dễ kiểm soát.
- **Retry không nhân đôi chi phí:** nếu phân cảnh có operation của provider ở trạng thái *chưa chắc đã kết thúc*
  (`pending`/`running`/`cancelled`, ví dụ sau khi hủy hoặc khi hết thời gian chờ), nút "Dựng lại" sẽ **tiếp tục theo dõi
  operation cũ** (`motion_status` giữ `running`, UI hiển thị thông báo "không tạo yêu cầu mới") thay vì submit lần hai.
  Chỉ khi provider đã kết thúc rõ ràng (`failed`/`expired`/`completed`) thì lần dựng lại mới tạo request mới.
- **Dựng lại toàn bộ** reset *mọi* phân cảnh chưa hoàn tất (`pending`, `rendering` sót lại sau khi process bị giết, `failed`,
  `cancelled`) nhưng **giữ nguyên ảnh đã tạo thành công** (`image_status = ready`) — ảnh dở/`generating` sẽ được tạo lại.
  Nhờ vậy retry sau khi hủy giữa chừng không tính phí ảnh hai lần cho các cảnh đã có ảnh.
- Nếu credentials bị gỡ **sau khi** đã tạo tác vụ (kể cả `hybrid`), tác vụ dừng với lỗi nêu rõ biến môi trường còn thiếu —
  hệ thống không tự chuyển sang chế độ cục bộ để tránh gây hiểu nhầm về kết quả/chi phí.

**Vòng đời và giới hạn (quan trọng):**

- Phân cảnh được dựng **theo số thứ tự chương** (không theo thứ tự bấm chọn).
- Mỗi người dùng tối đa `VIDEO_MAX_ACTIVE_JOBS` tác vụ chưa hoàn tất; vượt sẽ bị từ chối 409 kèm hướng dẫn.
- **Hủy** có hiệu lực tức thì: tiến trình FFmpeg đang chạy bị dừng trong khoảng `VIDEO_CANCEL_POLL_SECONDS`,
  vòng poll provider dừng ở lần kiểm tra kế tiếp, file dở dang (`output.mp4`, `subtitles.srt`, `clips.txt`, `.part`)
  được dọn, tác vụ chuyển `cancelled`.
- **Xóa** chỉ cho phép khi tác vụ đã dừng hẳn (không ở trạng thái `pending`/`running` và không còn FFmpeg đang chạy);
  nếu chưa dừng, API trả 409 để tránh xóa khi đang ghi file.
- Xóa dự án sẽ xóa luôn `video_export_jobs`, `video_export_scenes`, bản ghi tác vụ nền tương ứng **và** thư mục
  `storage/generated_videos/{user}/{job}` (SQLite không bật FK nên được dọn tường minh; với tác vụ còn đang chạy,
  thư mục được xóa ngay sau khi FFmpeg kết thúc). “Dọn bản ghi tác vụ” của dự án cũng dọn theo tác vụ xuất phim đã
  kết thúc, không để lại job mồ côi. Nếu job bị xóa trong lúc đang chạy, worker phát hiện và dừng ngay, không ghi tiếp.

**Dữ liệu lưu cho mỗi phân cảnh (không chứa bí mật):** `motion_provider`, `motion_model`, `motion_status`,
`motion_fallback_used`, `provider_error`, `clip_duration_seconds`, `image_provider`, `image_model`, `image_status`,
`image_error`, `image_size`. `motion_operation_id`, `motion_idempotency_key` và `image_path` được lưu **trong database**
(dùng cho resume/chống trùng/định vị素材) nhưng **không** nằm trong response API; địa chỉ tải clip/ảnh của provider
**không** được lưu và **không** trả về client; base64/prompt nội bộ/API key không bao giờ xuất hiện trong log hay response.

### 5. Bảo mật

- Server giữ toàn bộ URL/credentials; client chỉ gửi `motion_mode`/provider/model/limit đã được whitelist.
- **Không bao giờ tin định danh do provider trả về**: `operation_id`/`request_id`/`video id` được validate chặt trước khi
  lưu **và** trước mỗi lần dựng URL (`/videos/{id}`, `/videos/{id}/content`, `{base}/{operation_name}`):
  chỉ chấp nhận `[A-Za-z0-9._:-]` (Veo còn phải đúng dạng `models/<model>/operations/<id>` và model phải khớp model đã
  yêu cầu), từ chối URL tuyệt đối, `..`, thêm path segment, `?`/`#`/`%` và ký tự điều khiển → response độc hại hoặc
  dữ liệu DB bị sửa tay cũng không thể khiến hệ thống gửi API key tới host khác.
- URL tải clip (do provider trả về) phải là **HTTPS công khai**; hệ thống từ chối URL có userinfo, phân giải DNS ra
  địa chỉ nội bộ/loopback/link-local (chặn SSRF tới metadata `169.254.169.254`) và có thể giới hạn thêm bằng
  `VIDEO_MOTION_DOWNLOAD_ALLOWED_HOSTS`. `http://localhost` chỉ mở khi bật `VIDEO_MOTION_ALLOW_INSECURE_LOCALHOST`.
- Mỗi bước chuyển hướng khi tải đều được kiểm tra lại; API key **không** được gửi tới host CDN khác host provider.
- Clip tải về bị giới hạn `VIDEO_MOTION_MAX_CLIP_MB`, **bắt buộc vượt qua kiểm tra magic bytes** (`ftyp`/`styp` box
  đúng vị trí hoặc EBML của WebM/MKV) — `Content-Type` chỉ dùng để loại trừ sớm, không bao giờ là bằng chứng "đây là video" —
  và được ghi qua file `.part` rồi mới `os.replace`; không tin `Content-Length` hay tên file do provider trả về.
- **Mọi lỗi provider đi vào DB/UI/log đều được sanitize**: che key/`Bearer` token, URL, đường dẫn tuyệt đối, inline base64 và
  chuỗi token-like; tên biến môi trường (ví dụ `META_MUSE_API_KEY`) vẫn hiển thị để admin biết cần cấu hình gì.
- **Hủy luôn được phân loại là hủy, không phải lỗi**: cancel trong lúc gọi provider (kể cả khi HTTP helper báo
  `MotionCancelledError`) được map thành `ImageCancelledError`/`JobCancelled`, tác vụ kết thúc `cancelled`, phân cảnh
  **không** bị đánh dấu `failed`, file dở dang (`.part`) được dọn, và không có request provider nào được gửi thêm.
- Endpoint capabilities chỉ trả tên biến môi trường còn thiếu, không trả giá trị, không trả đường dẫn máy chủ.

### 6. API chính

| Phương thức | Đường dẫn | Mô tả |
|-------------|-----------|-------|
| `GET` | `/api/video-export/capabilities` | Khả năng (FFmpeg/TTS, `motion_providers`, `image_providers` kèm `configured`/`missing_config`/giới hạn/`cost_note`) và các hạn mức |
| `POST` | `/api/video-export/jobs` | Tạo tác vụ từ `chapter_ids` + `options` (`motion_mode`, `motion_provider`, `motion_model`, `motion_resolution`, `motion_aspect_ratio`, `hybrid_fallback_on_error`, `generate_scene_images`, `image_provider`, `image_model`, `image_aspect_ratio`, `image_size`, `image_reasoning_strength`) |
| `GET` | `/api/video-export/jobs?project_id=` | Danh sách tác vụ của dự án |
| `GET` | `/api/video-export/jobs/{job_id}` | Chi tiết tác vụ + storyboard (kèm trạng thái provider từng cảnh) |
| `POST` | `/api/video-export/jobs/{job_id}/retry` | Dựng lại tác vụ (phân cảnh đã xong được giữ nguyên) |
| `POST` | `/api/video-export/jobs/{job_id}/scenes/{scene_id}/retry` | Dựng lại một phân cảnh |
| `POST` | `/api/video-export/jobs/{job_id}/cancel` | Hủy tác vụ (dừng FFmpeg và vòng poll) |
| `DELETE` | `/api/video-export/jobs/{job_id}` | Xóa tác vụ và tệp đã dựng |
| `GET` | `/api/video-export/jobs/{job_id}/download/video` | Tải MP4 |
| `GET` | `/api/video-export/jobs/{job_id}/download/subtitles` | Tải SRT |

Mọi endpoint đều yêu cầu đăng nhập và kiểm tra quyền sở hữu dự án; tệp chỉ được đọc từ thư mục lưu trữ
được quản lý (không nhận đường dẫn từ client).

Ví dụ tạo tác vụ bằng chế độ AI:

```bash
curl -X POST http://localhost:8000/api/video-export/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "<project-id>",
    "chapter_ids": ["<chapter-id>"],
    "options": {
      "resolution": "1280x720",
      "motion_mode": "hybrid",
      "motion_provider": "xai_grok_imagine",
      "motion_model": "grok-imagine-video-1.5",
      "motion_resolution": "720p",
      "motion_aspect_ratio": "16:9",
      "hybrid_fallback_on_error": true
    }
  }'
```

### 7. Kiểm thử cục bộ

```bash
cd backend
python -m pytest tests/ -q
```

| Bộ test | Nội dung |
|---------|----------|
| `tests/test_video_export_mvp.py` | SRT, heuristic chia phân cảnh, kiểm tra tham số/giới hạn, chống path traversal, quyền sở hữu, quota, hủy/timeout FFmpeg, pipeline FFmpeg end-to-end |
| `tests/test_video_export_motion_providers.py` | Provider registry/capabilities (không lộ secret, có `model_limits` theo từng model), **validate operation id trước khi dựng URL** (URL tuyệt đối, `..`, thêm path segment, `?`/`#`/`%`, model không khớp), SSRF + whitelist host + giới hạn dung lượng + redirect, **magic bytes bắt buộc** (kể cả khi `Content-Type: video/mp4`), hình dạng request/auth header của xAI/Veo/OpenAI (multipart, `Idempotency-Key`), **size whitelist chuẩn** + resize ảnh tham chiếu + fail rõ khi thiếu FFmpeg, giới hạn theo model của Veo (8s, 4k chỉ trên generate/fast) và của OpenAI Sora (720p vs Pro 1024p), poll → thành công/thất bại/hủy/timeout, **backoff tăng thật sự**, không gửi key tới CDN, service layer remote/hybrid (fallback + `provider_error`), **lease đa worker** (claim nguyên tử/tiếp quản lease cũ/giải phóng), **retry không nhân đôi chi phí**, tương thích job cũ, API capabilities/503/400, guard import cho `main.py` |
| `tests/test_video_export_image_providers.py` | Provider ảnh Meta Muse: cấu hình/能力 (chỉ trả tên env thiếu), base URL HTTPS-only, hình dạng request (endpoint/bearer/body/response_format/output_format), size theo tỉ lệ, **b64/magic bytes/dung lượng** validation, HTTP 403/5xx + retry, **cancel (trong lúc request, trước/sau khi tải URL) → ImageCancelledError + dọn `.part`**, URL fallback SSRF **không bao giờ gửi Authorization (kể cả host trùng provider)**, sanitize key/URL/path/raw token, reasoning strength `low/high`, service 503/400, pipeline tạo `assets/scene_XXX.webp` → motion provider nhận đúng reference, không bật thì giữ hành vi cũ, cancel giữa chừng → job `cancelled` (không failed), retry giữ ảnh `ready` / reset ảnh dở, lease takeover (stale `running` + worker cũ tự dừng), cleanup theo tác vụ/dự án, API không lộ path/base64 |
| `tests/test_video_export_migrations.py` | Đồ thị migration sqlite/postgres (single head, chuỗi `5c7d1e9a4b21 → 7d2f9b4c1e58 → b3e6c8a1d457 → c4f7d9b2e568`), upgrade/downgrade trên DB cũ giữ nguyên dữ liệu, đồng bộ cột lúc khởi động |

> Tất cả test provider dùng **mock HTTP transport**, không gọi API trả phí thật. Test cần FFmpeg/chromadb/alembic sẽ tự bỏ qua khi thiếu.

### 8. Migration & tương thích ngược

- Migration mới (cả hai cây sqlite và postgres, script idempotent chỉ `ADD COLUMN` cột còn thiếu):
  - `7d2f9b4c1e58` (revises `5c7d1e9a4b21`) — cột chuyển động cho `video_export_jobs`/`video_export_scenes`
  - `b3e6c8a1d457` (revises `7d2f9b4c1e58`) — `worker_token`/`claimed_at` cho execution claim đa worker
  - `c4f7d9b2e568` (revises `b3e6c8a1d457`) — cột ảnh phân cảnh (`image_provider/model/status/error/path/size`)
  - `e6b1f4a9c287` (revises `c4f7d9b2e568`) — bảng PDF export (`pdf_export_jobs`, `pdf_export_images`)
  - `f7c2a5d8b913` (revises `e6b1f4a9c287`) — cột phiên bản PDF (`output_generation`, `output_created_at`, `run_attempt`) để phân biệt PDF cũ với lần chạy mới
- Khi khởi động, `app/services/video_export/schema.py` và `app/services/pdf_export/schema.py` tự bổ sung bảng còn thiếu và
  tự thêm **các cột nullable mới** (tương thích triển khai chưa chạy migration); các cột cũ thiếu vẫn chỉ cảnh báo để admin
  chạy `alembic upgrade head`.
- Khi dịch vụ khởi động lại, tác vụ `pending`/`running` được đánh dấu `failed` kèm thông báo, **giải phóng execution claim**
  nhưng **giữ nguyên** `motion_operation_id`/`motion_status` của từng phân cảnh — nhờ vậy "Dựng lại" sẽ tiếp tục theo dõi
  thao tác đã gửi thay vì tạo request mới (tránh tính phí lần hai).
- Job cũ (không có `motion_mode`) được đọc như `local` — API trả `motion_mode: "local"`, các trường provider là `null`,
  pipeline vẫn dựng và tải được bình thường.


## 📕 Xuất PDF full truyện (ReportLab, có thể kèm ảnh minh họa AI)

Từ một dự án, hệ thống lấy **toàn bộ chương** (sắp xếp `chapter_number` → `sub_index` → `created_at` → `id`), dựng **một file
PDF** gồm: trang bìa (tiêu đề, tác giả tuỳ chọn, thể loại, mô tả, ảnh bìa dự án nếu có), **mục lục** có số trang, từng
chương với tiêu đề + nội dung (giữ xuống dòng), ảnh minh họa tuỳ chọn, header/footer và số trang. Việc dựng PDF chạy trong
**tác vụ nền** (progress/cancel/retry/delete/download), không chặn request.

### 1. Cài đặt ReportLab & font Unicode

```bash
cd backend
pip install -r requirements.txt      # đã bao gồm reportlab
# Debian/Ubuntu (image Docker đã cài sẵn font)
sudo apt-get install -y fonts-dejavu-core fonts-noto-core
```

Font được dò tự động theo thứ tự: `PDF_FONT_PATH` → font đóng gói trong `backend/assets/fonts` → font hệ thống
(Windows `Arial`, Linux `DejaVu Sans`/`Noto Sans`/`Liberation Sans`, macOS `Arial`). **Thiếu font ⇒ API trả 503 với hướng dẫn
cài đặt** và tuyệt đối không tạo PDF chữ vỡ/ô vuông. Đặt `PDF_FONT_PATH` khi muốn dùng font riêng (ví dụ
`PDF_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`).

### 2. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `PDF_EXPORT_ENABLED` | `true` | Tắt/bật toàn bộ chức năng xuất PDF |
| `PDF_FONT_PATH` | — | Đường dẫn tệp `.ttf`/`.otf` Unicode (bỏ trống ⇒ tự dò font hệ thống) |
| `PDF_EXPORT_STORAGE_DIR` | `backend/storage/generated_pdfs` | Nơi lưu PDF + ảnh minh họa |
| `PDF_MAX_CHAPTERS` | `300` | Số chương tối đa mỗi lần xuất full truyện |
| `PDF_MAX_TEXT_CHARS` | `2000000` | Tổng ký tự nội dung tối đa |
| `PDF_MAX_IMAGES` | `60` | Số ảnh minh họa tối đa (mỗi ảnh có thể là một lần gọi API trả phí) |
| `PDF_MAX_OUTPUT_MB` | `128` | Dung lượng PDF tối đa |
| `PDF_MAX_ACTIVE_JOBS` | `2` | Số tác vụ PDF chưa hoàn tất tối đa mỗi người dùng |
| `PDF_JOB_TIMEOUT_SECONDS` | `1800` | Trần thời gian mỗi tác vụ |
| `PDF_DEFAULT_PAGE_SIZE` | `A4` | `A4` hoặc `LETTER` |
| `PDF_INCLUDE_TOC` | `true` | Mặc định sinh mục lục |
| `PDF_IMAGE_WIDTH_RATIO` | `0.85` | Tỉ lệ bề rộng ảnh minh họa (giữ đúng tỉ lệ, không phóng to) |
| `PDF_CLAIM_TTL_BUFFER_SECONDS` / `PDF_CLAIM_RENEW_SECONDS` / `PDF_CANCEL_POLL_SECONDS` | `300` / `60` / `1.0` | Lease 接管缓冲, chu kỳ gia hạn lease khi đang chạy và chu kỳ kiểm tra tín hiệu hủy |
| `IMAGE_DOWNLOAD_ALLOWED_HOSTS` | — | Whitelist host **tải ảnh** (CSV) khi provider trả URL thay vì base64 |

Ảnh minh họa dùng lại toàn bộ cấu hình image provider của tính năng video: `META_MUSE_API_KEY` (alias `MODEL_API_KEY`),
`META_MUSE_BASE_URL`, `META_MUSE_MODEL`, `META_MUSE_OUTPUT_FORMAT`, `VIDEO_IMAGE_ENABLED`, `VIDEO_IMAGE_MAX_MB`.

> **Key là bí mật:** chỉ đặt trong `.env` cục bộ (đã gitignore) hoặc secret manager; ví dụ trong tài liệu luôn dùng
> placeholder `META_MUSE_API_KEY=<your-meta-model-api-key>`. Key không bao giờ xuất hiện trong response, log, PDF hay database.

### 3. Cách dùng

1. Vào dự án → menu trái → **Xuất PDF full truyện** (hoặc `/project/{id}/pdf-export`).
2. Chọn tuỳ chọn: dùng ảnh bìa, tạo mục lục, khổ giấy, tên tác giả.
3. (Tuỳ chọn) bật **Tạo ảnh minh họa bằng Meta Muse (tính phí)** → chọn provider/model/kích thước/tỉ lệ/mức suy luận và
   chính sách khi ảnh lỗi:
   - `skip` (mặc định): ảnh lỗi bị bỏ qua, PDF vẫn xuất đầy đủ chữ kèm cảnh báo;
   - `fail`: dừng tác vụ và báo lỗi rõ.
4. Bấm **Xuất PDF full truyện** → theo dõi tiến độ (poll 2 giây), xem danh sách chương/ảnh, hủy, thử lại, tải PDF, xóa.

**Chi phí & rate limit:** PDF chỉ có chữ **không phát sinh chi phí**. Khi bật ảnh minh họa, **mỗi chương tối đa một lần gọi
Meta Model API** (tính phí theo ảnh, hạn mức theo tài khoản Meta). Ảnh tạo thành công được lưu trong thư mục tác vụ và
**tái sử dụng khi thử lại** (`ready` không tạo lại); chỉ ảnh `failed`/`cancelled` mới được tạo lại ⇒ không tính phí hai lần.
Hủy tác vụ dừng ngay vòng tạo ảnh (không gọi thêm API) và tác vụ chuyển `cancelled` (không phải `failed`).

**Atomic output (giữ PDF cũ khi thử lại thất bại):** PDF được dựng vào **tệp tạm của lần chạy hiện tại**
(`story.pdf.<run>.building`) rồi mới thay thế tệp chính khi thành công. Vì vậy **thử lại thất bại/bị hủy không làm mất PDF
trước đó**: tệp cũ vẫn tải được, và API trả `artifact_stale = true` cùng `artifact_generation` / `run_attempt` để phân biệt
«artifact cũ» với «lần chạy mới». `has_pdf` được kiểm tra theo **tệp thật tồn tại** (không chỉ dựa vào đường dẫn trong DB).
Hủy giữa lúc dựng được builder phát hiện ở ranh giới mỗi chương/đoạn và trả về ngay (thread không bị treo vô hạn; quá
wall-clock ⇒ `failed` với thông báo rõ).

**Dữ liệu lưu trữ:** đặt `./storage/generated_pdfs` làm volume (`docker-compose.yml` đã cấu hình) để PDF/ảnh không mất khi
container được tạo lại; thư mục này cũng nằm trong `.gitignore` nên không bao giờ bị commit. Thư mục được tạo sẵn trong image
(`Dockerfile`) và có thể đổi bằng `PDF_EXPORT_STORAGE_DIR`.

**Bảo mật:** ảnh chỉ lấy từ thư mục được quản lý (ảnh bìa dự án + ảnh trong thư mục tác vụ); client không thể truyền
path/URL. Ảnh được kiểm tra tồn tại/dung lượng/**magic bytes** (PNG/WebP/JPEG) trước khi chèn; tải PDF dùng `FileResponse`
với đường dẫn đã kiểm tra traversal/liên kết tượng trưng (symlink) và tên tệp an toàn. Nội dung chương là user content nên
luôn được escape trước khi đưa vào ReportLab (không thể chèn markup).

### 4. API

| Phương thức | Đường dẫn | Mô tả |
|-------------|-----------|-------|
| `GET` | `/api/pdf-export/projects/{project_id}/capabilities` | ReportLab/font có sẵn sàng, các hạn mức, `image_providers` (kèm `missing_config`), chính sách ảnh lỗi |
| `POST` | `/api/pdf-export/projects/{project_id}/jobs` | Tạo tác vụ (body `{options}`); chương luôn là **toàn bộ dự án**, sắp xếp ổn định |
| `GET` | `/api/pdf-export/projects/{project_id}/jobs` | Danh sách tác vụ của dự án (`total` là tổng thật trước `limit`) |
| `GET` | `/api/pdf-export/jobs/{job_id}` | Chi tiết tác vụ + trạng thái từng ảnh chương |
| `POST` | `/api/pdf-export/jobs/{job_id}/retry` | Xuất lại (giữ ảnh `ready`, chỉ tạo lại ảnh lỗi) |
| `POST` | `/api/pdf-export/jobs/{job_id}/cancel` | Hủy tác vụ |
| `DELETE` | `/api/pdf-export/jobs/{job_id}` | Xóa tác vụ + PDF + ảnh |
| `GET` | `/api/pdf-export/jobs/{job_id}/download` | Tải PDF (`application/pdf`) |

Ví dụ tạo tác vụ:

```bash
curl -X POST http://localhost:8000/api/pdf-export/projects/<project-id>/jobs \
  -H "Content-Type: application/json" \
  -d '{"options": {"include_cover": true, "include_toc": true, "include_images": false,
                   "page_size": "A4", "author": "Nguyễn Văn A"}}'
```

Xóa dự án / "Dọn bản ghi tác vụ" cũng dọn `pdf_export_jobs` + `pdf_export_images` và thư mục
`storage/generated_pdfs/{user}/{job}` (PDF + ảnh).

### 5. Kiểm thử PDF

`backend/tests/test_pdf_export.py` bao phủ: font resolver (thiếu/hợp lệ/đuôi sai), unicode PDF nhúng font, thứ tự chương,
escape markup người dùng, ảnh fit theo tỉ lệ + bỏ qua ảnh hỏng, page count/metadata, giới hạn tham số, ảnh minh họa qua
Meta **mock HTTP** (không gọi API thật), chính sách `skip`/`fail`, hủy → `cancelled`, retry giữ ảnh `ready`, download
chống traversal, dọn dẹp khi xóa tác vụ/dự án, cùng API/ownership. Ngoài ra có các regression test cho:
**atomic output** (retry fail/cancel vẫn tải được PDF cũ + `artifact_stale`), **hoàn tác được** khi
`delete_project_artifacts(commit=False)` (rollback không để lại trạng thái xóa một nửa), **hủy queue không bị worker ghi đè**,
**timeout/hủy luồng dựng PDF**, `has_pdf` theo tệp thật, `total` trước `limit`, `Content-Disposition` khi tải, và
`DELETE /api/tasks/{id}` xóa luôn PDF job + tệp. Chạy:

```bash
cd backend
python -m pytest tests/test_pdf_export.py -q
```



## 💻 硬件配置要求

### 最低配置（个人使用/开发环境）

| 组件 | 要求 |
|------|------|
| **CPU** | 2 核 |
| **内存** | 2 GB RAM |
| **存储** | 10 GB 可用空间 |
| **网络** | 稳定互联网连接（用于调用 AI API） |

### 推荐配置（小型团队/生产环境）

| 组件 | 要求 |
|------|------|
| **CPU** | 4 核 |
| **内存** | 8 GB RAM |
| **存储** | 20 GB SSD |
| **网络** | 稳定互联网连接 |

### 高并发配置（80-150 用户）

| 组件 | 要求 |
|------|------|
| **CPU** | 8 核 |
| **内存** | 16 GB RAM |
| **存储** | 50 GB+ SSD |
| **网络** | 高带宽连接 |

> **📌 说明**
> - **Embedding 模型**：约 400 MB 磁盘空间，运行时加载到内存
> - **PostgreSQL**：默认配置使用 256 MB shared_buffers，1 GB effective_cache_size
> - **Docker 部署**：建议预留额外 1-2 GB 内存给容器运行时
> - 本项目主要依赖外部 AI API（OpenAI/Claude/Gemini），不需要本地 GPU

## 🚀 快速开始

### 前置要求

- Docker 和 Docker Compose
- 至少一个 AI 服务的 API Key（OpenAI/Gemini/Claude）

### Docker Compose 部署（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/xiamuceer-j/MuMuAINovel.git
cd MuMuAINovel

# 2. 配置环境变量（必需）
cp backend/.env.example .env
# 编辑 .env 文件，填入必要配置（API Key、数据库密码等）

# 3. 确保文件准备完整
# ⚠️ 重要：确保以下文件存在
# - .env（配置文件，必需挂载到容器）
# - backend/scripts/init_postgres.sql（数据库初始化脚本）

# 4. 启动服务
docker-compose up -d

# 5. 访问应用
# 打开浏览器访问 http://localhost:8000
```

> **📌 注意事项**
>
> 1. **`.env` 文件挂载**: `docker-compose.yml` 会自动将 `.env` 挂载到容器，确保文件存在
> 2. **数据库初始化**: `init_postgres.sql` 会在首次启动时自动执行，安装必要的PostgreSQL扩展
> 3. **自行构建**: 如需从源码构建，请先下载 embedding 模型文件（[加群获取](frontend/public/qq.jpg)）

### 使用 Docker Hub 镜像（推荐新手）

```bash
# 1. 拉取最新镜像（已包含模型文件）
docker pull mumujie/mumuainovel:latest

# 2. 创建 docker-compose.yml（点击下方展开查看完整配置）
```

<details>
<summary>📄 点击展开 docker-compose.yml 完整配置</summary>

```yaml
services:
  postgres:
    image: postgres:18-alpine
    container_name: mumuainovel-postgres
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-mumuai_novel}
      POSTGRES_USER: ${POSTGRES_USER:-mumuai}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-123456}
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"
      TZ: ${TZ:-Asia/Shanghai}
    volumes:
      - postgres_data:/var/lib/postgresql
      - ./backend/scripts/init_postgres.sql:/docker-entrypoint-initdb.d/init.sql:ro
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-mumuai} -d ${POSTGRES_DB:-mumuai_novel}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - ai-story-network
    command:
      - postgres
      - -c
      - max_connections=${POSTGRES_MAX_CONNECTIONS:-200}
      - -c
      - shared_buffers=${POSTGRES_SHARED_BUFFERS:-256MB}
      - -c
      - effective_cache_size=${POSTGRES_EFFECTIVE_CACHE_SIZE:-1GB}
      - -c
      - maintenance_work_mem=${POSTGRES_MAINTENANCE_WORK_MEM:-64MB}
      - -c
      - checkpoint_completion_target=${POSTGRES_CHECKPOINT_COMPLETION_TARGET:-0.9}
      - -c
      - wal_buffers=${POSTGRES_WAL_BUFFERS:-16MB}
      - -c
      - default_statistics_target=${POSTGRES_DEFAULT_STATISTICS_TARGET:-100}
      - -c
      - random_page_cost=${POSTGRES_RANDOM_PAGE_COST:-1.1}
      - -c
      - effective_io_concurrency=${POSTGRES_EFFECTIVE_IO_CONCURRENCY:-200}
      - -c
      - work_mem=${POSTGRES_WORK_MEM:-4MB}
      - -c
      - min_wal_size=${POSTGRES_MIN_WAL_SIZE:-1GB}
      - -c
      - max_wal_size=${POSTGRES_MAX_WAL_SIZE:-4GB}

  mumuainovel:
    image: mumujie/mumuainovel:latest
    container_name: mumuainovel
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "${APP_PORT:-8000}:8000"
    volumes:
      - ./logs:/app/logs
      - ./.env:/app/.env:ro
      - ./storage/generated_covers:/app/backend/storage/generated_covers
    environment:
      # 应用配置
      - APP_NAME=${APP_NAME:-MuMuAINovel}
      - APP_VERSION=${APP_VERSION:-1.5.4}
      - APP_HOST=${APP_HOST:-0.0.0.0}
      - APP_PORT=8000
      - DEBUG=${DEBUG:-false}
      # 数据库配置
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER:-mumuai}:${POSTGRES_PASSWORD:-123456}@postgres:5432/${POSTGRES_DB:-mumuai_novel}
      - DB_HOST=postgres
      - DB_PORT=5432
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-123456}
      # PostgreSQL 连接池配置
      - DATABASE_POOL_SIZE=${DATABASE_POOL_SIZE:-30}
      - DATABASE_MAX_OVERFLOW=${DATABASE_MAX_OVERFLOW:-20}
      - DATABASE_POOL_TIMEOUT=${DATABASE_POOL_TIMEOUT:-60}
      - DATABASE_POOL_RECYCLE=${DATABASE_POOL_RECYCLE:-1800}
      - DATABASE_POOL_PRE_PING=${DATABASE_POOL_PRE_PING:-True}
      - DATABASE_POOL_USE_LIFO=${DATABASE_POOL_USE_LIFO:-True}
      # 全局代理配置（可选）
      - HTTP_PROXY=${HTTP_PROXY:-}
      - HTTPS_PROXY=${HTTPS_PROXY:-}
      - NO_PROXY=${NO_PROXY:-localhost,127.0.0.1}
      # AI 服务配置
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.openai.com/v1}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - GEMINI_BASE_URL=${GEMINI_BASE_URL:-}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-}
      - DEFAULT_AI_PROVIDER=${DEFAULT_AI_PROVIDER:-openai}
      - DEFAULT_MODEL=${DEFAULT_MODEL:-gpt-4o-mini}
      - DEFAULT_TEMPERATURE=${DEFAULT_TEMPERATURE:-0.7}
      - DEFAULT_MAX_TOKENS=${DEFAULT_MAX_TOKENS:-32000}
      - ALLOW_PRIVATE_AI_ENDPOINTS=${ALLOW_PRIVATE_AI_ENDPOINTS:-false}
      - ALLOWED_AI_HOSTS=${ALLOWED_AI_HOSTS:-}
      # LinuxDO OAuth 配置
      - LINUXDO_CLIENT_ID=${LINUXDO_CLIENT_ID:-11111}
      - LINUXDO_CLIENT_SECRET=${LINUXDO_CLIENT_SECRET:-11111}
      - LINUXDO_REDIRECT_URI=${LINUXDO_REDIRECT_URI:-http://localhost:8000/api/auth/linuxdo/callback}
      - LINUXDO_PROXY_URL=${LINUXDO_PROXY_URL:-}
      - FRONTEND_URL=${FRONTEND_URL:-http://localhost:8000}
      # 本地账户登录配置
      - LOCAL_AUTH_ENABLED=${LOCAL_AUTH_ENABLED:-true}
      - LOCAL_AUTH_USERNAME=${LOCAL_AUTH_USERNAME:-admin}
      - LOCAL_AUTH_PASSWORD=${LOCAL_AUTH_PASSWORD:-admin123}
      - LOCAL_AUTH_DISPLAY_NAME=${LOCAL_AUTH_DISPLAY_NAME:-本地管理员}
      # 会话配置
      - SESSION_EXPIRE_MINUTES=${SESSION_EXPIRE_MINUTES:-120}
      - SESSION_REFRESH_THRESHOLD_MINUTES=${SESSION_REFRESH_THRESHOLD_MINUTES:-30}
      - SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-true}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - ai-story-network

volumes:
  postgres_data:
    driver: local

networks:
  ai-story-network:
    driver: bridge
```

</details>

```bash
# 3. 启动服务
docker-compose up -d

# 4. 查看日志
docker-compose logs -f

# 5. 更新到最新版本
docker-compose pull
docker-compose up -d
```

> **💡 提示**: Docker Hub 镜像已包含所有依赖和模型文件，无需额外下载

### 本地开发 / 从源码构建

#### 前置准备

```bash
# ⚠️ 重要：如果从源码构建，需要先下载 embedding 模型文件
# 模型文件较大（约 400MB），需放置到以下目录：
# backend/embedding/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/
#
# 📥 获取方式：
# - 加入项目 QQ 群或 Linux DO 讨论区获取下载链接
# - 群号：见项目主页
# - Linux DO：https://linux.do/t/topic/1100112
```

#### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 配置 .env 文件
cp .env.example .env
# 编辑 .env 填入必要配置

# 启动 PostgreSQL（可使用 Docker）
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=mumuai_novel \
  -p 5432:5432 \
  postgres:18-alpine

# 启动后端
python -m uvicorn app.main:app --host localhost --port 8000 --reload
```

#### 前端

```bash
cd frontend
npm install
npm run dev  # 开发模式
npm run build  # 生产构建
```

## ⚙️ 配置说明

### 必需配置

创建 `.env` 文件：

```bash
# PostgreSQL 数据库（必需）
DATABASE_URL=postgresql+asyncpg://mumuai:your_password@postgres:5432/mumuai_novel
POSTGRES_PASSWORD=your_secure_password

# AI 服务
OPENAI_API_KEY=your_openai_key
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_AI_PROVIDER=openai
DEFAULT_MODEL=gpt-4o-mini

# 本地账户登录
LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=your_password
```

### 可选配置

```bash
# LinuxDO OAuth
LINUXDO_CLIENT_ID=your_client_id
LINUXDO_CLIENT_SECRET=your_client_secret
LINUXDO_REDIRECT_URI=http://localhost:8000/api/auth/callback
# LinuxDO 登录专用代理（可选，仅影响 OAuth token 与用户信息请求）
LINUXDO_PROXY_URL=http://127.0.0.1:7890

# PostgreSQL 连接池（高并发优化）
DATABASE_POOL_SIZE=30
DATABASE_MAX_OVERFLOW=20

# 会话 Cookie Secure 标记
# 默认 true，适合 HTTPS 部署；如果使用 HTTP 访问并且浏览器不保存登录 Cookie，可设为 false
SESSION_COOKIE_SECURE=true

# 本地 / Docker 内网 LLM（默认关闭，保持 SSRF 防护）
# ALLOW_PRIVATE_AI_ENDPOINTS=true
# ALLOWED_AI_HOSTS=host.docker.internal,127.0.0.1
```

> **🔐 Cookie Secure 说明**
>
> - HTTPS 部署：建议保持 `SESSION_COOKIE_SECURE=true`，浏览器只会通过 HTTPS 发送登录 Cookie。
> - HTTP 部署：如果登录后浏览器没有保存 Cookie，请在 `.env` 中设置 `SESSION_COOKIE_SECURE=false`，然后重启后端或 Docker 容器。
> - Docker Compose 示例默认使用 `SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-true}`，如需关闭必须在 `.env` 中显式配置。
>
> **🌐 LinuxDO 专用代理说明**
>
> - 如果只有 LinuxDO 授权登录在当前网络不可达，优先配置 `LINUXDO_PROXY_URL`，不要配置全局 `HTTP_PROXY` / `HTTPS_PROXY`。
> - `LINUXDO_PROXY_URL` 只会用于 LinuxDO OAuth 的 token 交换和用户信息请求，不影响 AI 服务、SMTP、数据库等其他网络调用。
> - 常见示例：`LINUXDO_PROXY_URL=http://127.0.0.1:7890`；Docker 容器内访问宿主机代理时通常需要使用宿主机在 Docker 网络中的地址，而不是容器内的 `127.0.0.1`。
> - 当前示例按 HTTP 代理配置；如果需要 SOCKS 代理，请先确保运行环境安装了 httpx 的 SOCKS 支持依赖。
>
> **🖥️ 本地 / Docker 内网 LLM 说明**
>
> - 默认会拒绝 `localhost`、`127.0.0.1`、私网 IP 以及解析到内网的主机名（例如 `host.docker.internal`），用于降低 SSRF 风险。
> - 如果 AI 服务跑在本机 Ollama / llama.cpp，或 Docker 容器需要访问宿主机上的模型，请在 `.env` 中设置 `ALLOW_PRIVATE_AI_ENDPOINTS=true`，或把允许的主机名写入 `ALLOWED_AI_HOSTS`。
> - 即使开启本地放行，链路本地地址（如云厂商元数据 `169.254.169.254`）仍然会被拒绝。
> - MCP 插件 URL 不受该开关影响，继续走严格的公网校验。

### 中转 API 配置

支持所有 OpenAI 兼容格式的中转服务：

```bash
# New API 示例
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.new-api.com/v1

# 其他中转服务
OPENAI_BASE_URL=https://your-proxy-service.com/v1
```

## 🐳 Docker 部署详情

### 服务架构

- **postgres**: PostgreSQL 18 数据库
  - 端口: 5432
  - 数据持久化: `postgres_data` volume
  - 初始化脚本: `backend/scripts/init_postgres.sql`（自动挂载）
  - 优化配置: 支持 80-150 并发用户

- **mumuainovel**: 主应用服务
  - 端口: 8000
  - 日志目录: `./logs`
  - 配置挂载: `.env` 文件
  - 自动等待数据库就绪
  - 健康检查: 每 30 秒检测一次

### 重要文件说明

| 文件 | 说明 | 是否必需 |
|------|------|---------|
| `.env` | 环境配置（API Key、数据库密码等） | ✅ 必需 |
| `docker-compose.yml` | 服务编排配置 | ✅ 必需 |
| `backend/scripts/init_postgres.sql` | PostgreSQL 扩展安装脚本 | ✅ 自动挂载 |
| `backend/embedding/models--*/` | Embedding 模型文件 | ⚠️ 自建需要 |

> **注意**: 使用 Docker Hub 镜像时，模型文件已包含在镜像中，无需额外下载

### 常用命令

```bash
# 启动服务
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看资源使用
docker stats
```

### 数据持久化

- `./postgres_data` - PostgreSQL 数据库文件
- `./logs` - 应用日志文件

### 端口配置

修改 `docker-compose.yml` 中的端口映射：

```yaml
ports:
  - "8800:8000"  # 宿主机:容器
```

## 📁 项目结构

```
MuMuAINovel/
├── backend/                 # 后端服务
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── models/         # 数据模型
│   │   ├── services/       # 业务逻辑
│   │   ├── middleware/     # 中间件
│   │   ├── database.py     # 数据库连接
│   │   └── main.py         # 应用入口
│   ├── scripts/            # 工具脚本
│   └── requirements.txt    # Python 依赖
├── frontend/               # 前端应用
│   ├── src/
│   │   ├── pages/         # 页面组件
│   │   ├── components/    # 通用组件
│   │   ├── services/      # API 服务
│   │   └── store/         # 状态管理
│   └── package.json
├── docker-compose.yml      # Docker Compose 配置
├── Dockerfile             # Docker 镜像构建
└── README.md
```

## 🛠️ 技术栈

**后端**: FastAPI • PostgreSQL • SQLAlchemy • OpenAI/Claude/Gemini SDK

**前端**: React 18 • TypeScript • Ant Design • Zustand • Vite

## 📖 使用指南

1. **登录系统** - 使用本地账户或 LinuxDO 账户
2. **创建项目** - 选择"使用向导创建"
3. **AI 生成** - 输入基本信息，AI 自动生成大纲和角色
4. **编辑完善** - 管理角色关系，生成和编辑章节

### API 文档

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

### 贡献者

感谢所有为本项目做出贡献的开发者！

<a href="https://github.com/xiamuceer-j/MuMuAINovel/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=xiamuceer-j/MuMuAINovel" />
</a>

## 📝 许可证

本项目采用 [GNU General Public License v3.0](LICENSE)

**GPL v3 意味着：**
- ✅ 可自由使用、修改和分发
- ✅ 可用于商业目的
- 📝 必须开源修改版本
- 📝 必须保留原作者版权
- 📝 衍生作品必须使用 GPL v3 协议

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - Python Web 框架
- [React](https://react.dev/) - 前端框架
- [Ant Design](https://ant.design/) - UI 组件库
- [PostgreSQL](https://www.postgresql.org/) - 数据库

## 📧 联系方式

- 提交 [Issue](https://github.com/xiamuceer-j/MuMuAINovel/issues)
- Linux DO [讨论](https://linux.do/t/topic/1106333)
- 加入QQ群 [QQ群](frontend/public/qq.jpg)
- 加入WX群 [WX群](frontend/public/WX.png)

---

<div align="center">

**如果这个项目对你有帮助，请给个 ⭐️ Star！**

Made with ❤️

</div>

## Star History

<a href="https://star-history.dera.page/#xiamuceer-j/MuMuAINovel&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=xiamuceer-j/MuMuAINovel&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=xiamuceer-j/MuMuAINovel&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=xiamuceer-j/MuMuAINovel&type=date&legend=top-left" />
 </picture>
</a>

## History

![Alt](https://repobeats.axiom.co/api/embed/ee7141a5f269c64759302e067abe23b46796bafe.svg "Repobeats analytics image")
