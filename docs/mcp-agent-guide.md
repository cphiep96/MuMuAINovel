# Hướng dẫn MCP cho agent (điều khiển MuMuAINovel không cần UI)

> **Đối tượng:** coding agent (Cursor, Claude Desktop, Grok, Paseo, hoặc agent nội bộ của app) muốn
> **tạo truyện, tạo danh mục, sinh chương và xuất video** hoàn toàn bằng công cụ MCP thay vì thao tác tay trên web UI.
>
> **Nguồn chân lý:** server thật nằm ở `backend/app/mcp_server/` (`server.py`). Tài liệu này mô tả **đúng** những gì
> server hiện expose. Nếu code đổi, hãy chạy `tools/list` để lấy danh sách mới nhất.

---

## 1. Vì sao dùng MCP thay vì UI

| Việc thường làm trên web UI | Làm bằng MCP | Lợi ích |
|---|---|---|
| Tạo truyện, chọn thể loại, nhập mô tả | `create_project` / `update_project` | Agent tạo hàng loạt truyện theo brief có sẵn |
| Tạo/quản lý danh mục (thể loại, nghề nghiệp, nhóm prompt) | `list_categories` / `create_category` | Chuẩn hoá danh mục trước khi sinh nội dung |
| Chạy wizard: bối cảnh → nghề → nhân vật → dàn ý | `wizard_world_building` → `wizard_career_system` → `wizard_characters` → `wizard_outline` | Chạy nền, không cần bấm từng bước |
| Viết chương | `list_chapters` + `generate_chapter` / `continue_chapters` | Sinh nhiều chương theo lô rồi poll `task_status` |
| Xuất video từ chương | `video_capabilities` → `create_video_export` → `get_video_export` → `video_download_paths` | Xuất phim theo pipeline, lấy đường dẫn MP4/SRT |

Nói ngắn: **một lệnh cho agent, thay cho vài chục cú click** — mọi bước đều poll/retry được bằng code.

---

## 2. Kiến trúc

```
Coding agent (Cursor / Claude Desktop / Grok / Paseo)
        │  MCP: stdio (mặc định) hoặc streamable HTTP (/mcp)
        ▼
backend/app/mcp_server/         ← MCP server first-party
        ├── đường DB trực tiếp (SQLAlchemy)  →  list/create/update project, chapter, category, video job
        └── HTTP + auth →  FastAPI  http://127.0.0.1:8000   →  wizard SSE, generate chapter, prompt/style
```

Hai đường này quan trọng vì chúng dùng **hai cơ chế xác thực khác nhau** (xem mục 4).

---

## 3. Chuẩn bị

### 3.1. Chạy backend

Backend là bắt buộc với các tool wizard/chương, và các tool dùng DB thì cần MCP server truy cập được cùng database.

```powershell
cd D:\project\tool\story-tool\MuMuAINovel\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Kiểm tra: `http://127.0.0.1:8000/health` phải trả JSON trạng thái khỏe.

### 3.2. Chạy MCP server

Luôn chạy từ thư mục `backend/` với `PYTHONPATH` trỏ vào chính `backend/`:

```powershell
cd D:\project\tool\story-tool\MuMuAINovel\backend
$env:PYTHONPATH    = "D:\project\tool\story-tool\MuMuAINovel\backend"
$env:MUMU_API_BASE = "http://127.0.0.1:8000"
$env:MUMU_MCP_TOKEN = "<session_token>"     # xem mục 4

# stdio (mặc định) — dùng cho Cursor/Claude/Grok/Paseo
python -m app.mcp_server

# hoặc HTTP (dùng cho plugin manager trong app) — mặc định cổng 8765, path /mcp
python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8765
```

Chế độ stdio **không in gì ra stdout** (stdout dành cho JSON-RPC; log đi ra stderr). Chạy tay mà không thấy gì là bình thường —
hãy để client MCP tự spawn tiến trình này.

### 3.3. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MUMU_API_BASE` | `http://127.0.0.1:8000` | Gốc REST API, **không** kèm `/api` |
| `MUMU_MCP_TOKEN` | — | Token xác thực (mục 4). Bắt buộc |
| `MUMU_SESSION_TOKEN` | — | Alias của `MUMU_MCP_TOKEN`, dùng khi bạn muốn nói rõ đây là session token |
| `MUMU_MCP_USER_ID` | suy ra từ session token | User id để cô lập dữ liệu. **Bắt buộc** nếu token không phải session token có chữ ký |
| `MUMU_USER_ID` | — | Alias tương thích ngược của `MUMU_MCP_USER_ID` |
| `MUMU_MCP_TRANSPORT` | `stdio` | `stdio` / `streamable-http` / `sse` (tương đương cờ `--transport`) |
| `MUMU_MCP_HOST` | `127.0.0.1` | Địa chỉ lắng nghe khi chạy HTTP |
| `MUMU_MCP_PORT` | `8765` | Cổng HTTP |
| `PYTHONPATH` | — | Phải trỏ tới `backend/` để `python -m app.mcp_server` import được `app` |

---

## 4. Xác thực

### 4.1. Hai chế độ, đừng lẫn lộn

MCP server dùng **hai cơ chế khác nhau** cho hai nhóm tool:

| Nhóm tool | Cơ chế | Cần gì |
|---|---|---|
| `list/create/update_project`, `*_chapter`, `*_category`, `video_*`, `list_*` | **DB trực tiếp** qua SQLAlchemy | `MUMU_MCP_USER_ID` (hoặc suy ra từ session token) + quyền truy cập database |
| `wizard_*`, `generate_chapter`, `continue_chapters`, `task_status` | **HTTP** vào FastAPI | Token phải được backend chấp nhận |

### 4.2. Cách A — session token (khuyến nghị)

Backend ký token vào cookie `session_token`. MCP server nhận token này và:

- gửi `Cookie: session_token=<token>` khi gọi HTTP → middleware xác thực bằng chữ ký HMAC;
- **tự suy ra `user_id`** từ token (bỏ được `MUMU_MCP_USER_ID`).

Lấy token:

```powershell
cd D:\project\tool\story-tool\MuMuAINovel
python backend\scripts\issue_mcp_token.py --username admin --password <mật-khẩu>
```

Script in ra token và hạn dùng; chỉ in ra màn hình, **không ghi ra đĩa**. Token hết hạn theo `SESSION_EXPIRE_MINUTES`
(mặc định **120 phút**) → với job dài, hãy tăng biến này hoặc lấy token mới.

Các cách lấy khác:

```powershell
# PowerShell thuần
$login = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/auth/local/login" `
  -Method POST -ContentType "application/json" `
  -Body '{"username":"admin","password":"<mật-khẩu>"}' `
  -SessionVariable s -UseBasicParsing
$s.Cookies.GetCookies("http://127.0.0.1:8000") | Where-Object Name -eq "session_token" |
  Select-Object -ExpandProperty Value
```

Hoặc: đăng nhập web UI → `F12` → **Application → Cookies → `session_token`** → copy giá trị.

Kiểm tra token còn sống:

```powershell
python backend\scripts\issue_mcp_token.py --check --token "<token>"
```

### 4.3. Cách B — shared MCP token (không hết hạn theo session)

Dùng một chuỗi bí mật cố định thay cho session token. Cách này tiện cho agent chạy dài, nhưng có **hai điều kiện bắt buộc**:

1. **Cả tiến trình backend VÀ tiến trình MCP server** phải có cùng `MUMU_MCP_TOKEN`.
   Middleware so sánh bearer token với `os.getenv("MUMU_MCP_TOKEN")` **trong tiến trình backend**, nên nếu chỉ đặt ở MCP server
   thì backend sẽ trả 401. Backend phải được **khởi động lại** sau khi thêm biến.
2. Phải có `MUMU_MCP_USER_ID`, vì token này không mang theo user id.

```powershell
# trong shell chạy backend
$env:MUMU_MCP_TOKEN = "<chuỗi-bí-mật-dài-ngẫu-nhiên>"
$env:MUMU_MCP_USER_ID = "local_xxxxxxxxxxxxxxxx"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> ⚠️ Đặt `MUMU_MCP_TOKEN` trong tiến trình backend mở ra một đường xác thực thay thế cho toàn bộ API.
> Chỉ dùng khi bạn kiểm soát được môi trường, dùng chuỗi random đủ mạnh, và đừng để lộ nó.

`MUMU_MCP_USER_ID` lấy ở đâu? Với tài khoản local, id có dạng `local_<md5(username)[:16]>` — login rồi đọc trường
`user_id` từ response `POST /api/auth/local/login` hoặc `GET /api/auth/user`.

### 4.4. Cấu hình `.env` liên quan

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `LOCAL_AUTH_ENABLED` | `true` | Phải bật để login `username`/`password` |
| `SESSION_EXPIRE_MINUTES` | `120` | Tăng nếu agent chạy job dài |
| `SESSION_COOKIE_SECURE` | theo `DEBUG` | Đặt `false` khi chạy HTTP nội bộ nếu gặp trục trặc cookie trên UI |

---

## 5. Cấu hình client MCP

Các file mẫu ở [`docs/mcp-configs/`](./mcp-configs/) **không chứa bí mật** — hãy thay `<session_token>` bằng token thật.

### 5.1. Cursor

File: `docs/mcp-configs/cursor-mcp.json.example` → copy vào `%USERPROFILE%\.cursor\mcp.json` (hoặc `.cursor/mcp.json` trong repo).

```json
{
  "mcpServers": {
    "mumuainovel": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "D:\\project\\tool\\story-tool\\MuMuAINovel\\backend",
      "env": {
        "PYTHONPATH": "D:\\project\\tool\\story-tool\\MuMuAINovel\\backend",
        "MUMU_API_BASE": "http://127.0.0.1:8000",
        "MUMU_MCP_TOKEN": "<session_token>"
      }
    }
  }
}
```

Nếu `python` không nằm trong `PATH`, dùng đường dẫn tuyệt đối:

```json
"command": "D:\\project\\tool\\story-tool\\MuMuAINovel\\backend\\.venv\\Scripts\\python.exe"
```

> `cwd` là tiện ích; `PYTHONPATH` một mình đã đủ để `import app`. Nếu client từ chối khoá `cwd`, cứ xoá nó.
> Khi dùng **Cách B** (shared token), thêm `"MUMU_MCP_USER_ID": "local_xxxxxxxxxxxxxxxx"` vào `env`.

### 5.2. Claude Desktop

File: `docs/mcp-configs/claude-desktop.json.example` → copy vào `%APPDATA%\Claude\claude_desktop_config.json`,
rồi **thoát hẳn và mở lại** Claude Desktop. Cấu trúc giống Cursor.

### 5.3. Grok

Grok Build đọc cấu hình MCP dạng TOML tại `~/.grok/config.toml`, đồng thời **import được file JSON kiểu `mcpServers`**
(`.mcp.json` trong repo, hoặc `~/.cursor/mcp.json`).

- JSON: `docs/mcp-configs/grok-mcp.json.example`
- TOML gốc: `docs/mcp-configs/grok-config.toml.example`

```toml
[mcp_servers.mumuainovel]
command = "python"
args = ["-m", "app.mcp_server"]
cwd = "D:\\project\\tool\\story-tool\\MuMuAINovel\\backend"

[mcp_servers.mumuainovel.env]
PYTHONPATH = "D:\\project\\tool\\story-tool\\MuMuAINovel\\backend"
MUMU_API_BASE = "http://127.0.0.1:8000"
MUMU_MCP_TOKEN = "<session_token>"
```

> Tên khoá của Grok (`mcp_servers` / `mcpServers`) thay đổi theo phiên bản. Nếu server không xuất hiện trong `grok mcp list`,
> dùng file JSON import hoặc đổi tên khoá theo tài liệu phiên bản bạn đang chạy.

### 5.4. Paseo

Paseo chạy agent trong workspace `D:\project\tool\story-tool\MuMuAINovel` và nhận cùng định dạng `mcpServers`. Thêm khối JSON
ở [5.1](#51-cursor) vào cấu hình MCP của Paseo (hoặc `.mcp.json` ở gốc repo) — dùng đường dẫn tuyệt đối như trên.

### 5.5. Chế độ HTTP

Khởi động server:

```powershell
cd D:\project\tool\story-tool\MuMuAINovel\backend
$env:PYTHONPATH = "D:\project\tool\story-tool\MuMuAINovel\backend"
$env:MUMU_MCP_TOKEN = "<session_token>"
python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8765
```

Endpoint: `http://127.0.0.1:8765/mcp`. Xác thực bằng **bearer đúng bằng `MUMU_MCP_TOKEN`** (server kiểm tra bằng so sánh
hằng thời gian và yêu cầu scope `mumu`):

```json
{
  "mcpServers": {
    "mumuainovel": {
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer <session_token>" }
    }
  }
}
```

---

## 6. Danh mục công cụ MCP

Đây là danh sách **thật** mà `backend/app/mcp_server/server.py` đăng ký (**26 tool**).

**Nhóm 1 — kiểm tra & auth**

| Tool | Tham số | Việc |
|---|---|---|
| `mumu_auth_status` | — | Cho biết token/user id đã cấu hình chưa, `api_base` đang dùng |
| `mumu_health` | — | Sức khỏe MCP + database + `api_base` |

**Nhóm 2 — truyện & danh mục (đường DB)**

| Tool | Tham số chính | Việc |
|---|---|---|
| `list_projects` | `skip=0`, `limit=100` | Liệt kê truyện của user |
| `create_project` | `title`, `description`, `theme`, `genre`, `target_words`, `outline_mode` | Tạo truyện |
| `update_project` | `project_id` + các trường cần sửa | Sửa truyện (gồm `genre`) |
| `list_categories` | `project_id` (tuỳ chọn) | Liệt kê taxonomy: prompt category, genre đã dùng, nhóm nghề |
| `create_category` | `kind` (`genre`/`career`/`prompt`), `name`, `project_id`, `career_id`, `template_key`, `template_content` | Tạo/gắn taxonomy |

> `kind="genre"` đặt `genre` cho **project đã tồn tại**; `kind="career"` đổi nhóm của **nghề đã tồn tại** (muốn tạo nghề mới
> thì dùng API nghề nghiệp của app); `kind="prompt"` tạo marker prompt-template để lưu category.

**Nhóm 3 — wizard (đường HTTP/SSE)**

| Tool | Tham số chính | Việc |
|---|---|---|
| `wizard_world_building` | `title`, `description`, `theme`, `genre`, `chapter_count`, `narrative_perspective`, `target_words`, `project_id`, `provider`, `model` | Sinh bối cảnh thế giới (**tạo project mới**) |
| `wizard_world_regenerate` | `project_id`, `provider`, `model` | Tạo lại bối cảnh thế giới của **project đã có** (SSE `/regenerate`) |
| `wizard_career_system` | `project_id`, `provider`, `model` | Sinh hệ nghề nghiệp |
| `wizard_characters` | `project_id`, `count=5`, `requirements`, `provider`, `model` | Sinh nhân vật |
| `wizard_outline` | `project_id`, `chapter_count=3`, `narrative_perspective`, `target_words`, `requirements`, `provider`, `model` | Sinh dàn ý |
| `wizard_status` | `project_id` | Đọc `wizard_status`/`wizard_step` + thông tin thế giới |

**Nhóm 4 — chương (đường DB + HTTP)**

| Tool | Tham số chính | Việc |
|---|---|---|
| `list_chapters` | `project_id` | Liệt kê chương theo `chapter_number` |
| `create_chapter` | `project_id`, `title`, `chapter_number`, `content`, `summary`, `status`, `outline_id`, `sub_index` | Tạo chương thủ công |
| `generate_chapter` | `chapter_id`, `target_word_count=3000`, `style_id`, `model`, `enable_mcp`, `wait_for_stream=False` | AI viết 1 chương (background task, hoặc SSE khi `wait_for_stream=True`) |
| `continue_chapters` | `project_id`, `start_chapter_number`, `count`, `target_word_count`, `style_id`, `model`, `enable_mcp` | Viết liên tiếp nhiều chương → batch task |
| `task_status` | `task_id` | Poll trạng thái background task |

**Nhóm 5 — prompt & style**

| Tool | Tham số chính | Việc |
|---|---|---|
| `list_prompt_templates` | `category`, `active_only=True` | Liệt kê prompt template của user |
| `list_writing_styles` | — | Liệt kê writing style preset + style riêng của user |

**Nhóm 6 — xuất video**

| Tool | Tham số chính | Việc |
|---|---|---|
| `video_capabilities` | — | FFmpeg/TTS/provider + giới hạn cấu hình |
| `create_video_export` | `project_id`, `chapter_ids` (list), `options` (dict) | Tạo job xuất video |
| `list_video_exports` | `project_id`, `limit=20` | Liệt kê job theo project |
| `get_video_export` | `job_id` | Chi tiết job + storyboard (dùng để poll tiến độ) |
| `video_export_action` | `job_id`, `action` (`retry`/`cancel`) | Retry hoặc hủy job |
| `video_download_paths` | `job_id` | Trả **đường dẫn file** MP4/SRT trên máy chủ (không trả nhị phân qua MCP) |

> `video_download_paths` cố ý **không** trả file nhị phân. Agent nhận đường dẫn rồi tự đọc/copy file trên máy chủ.

---

## 7. Playbook end-to-end cho agent

### Bước 0 — Kiểm tra sống còn

```json
{ "tool": "mumu_auth_status", "arguments": {} }
{ "tool": "mumu_health", "arguments": {} }
```

`mumu_auth_status` phải cho `authenticated: true`. Nếu không, dừng lại và sửa token/user id trước.

### Bước 1 — Tạo project

```json
{
  "tool": "create_project",
  "arguments": {
    "title": "Đêm Trắng Trên Phố Cổ",
    "description": "Trinh thám đô thị, nhân vật chính là cựu điều tra viên",
    "theme": "Chuộc lỗi và sự thật",
    "genre": "Trinh thám",
    "target_words": 120000,
    "outline_mode": "one-to-many"
  }
}
```

Ghi lại `id` (chính là `project_id`).

### Bước 2 — Chuẩn hoá thể loại/danh mục

```json
{ "tool": "create_category", "arguments": { "kind": "genre", "name": "Trinh thám đô thị", "project_id": "<project_id>" } }
{ "tool": "list_categories", "arguments": { "project_id": "<project_id>" } }
```

### Bước 3 — Wizard

> `wizard_world_building` **tạo project mới** ở backend. Nếu bạn đã tạo project ở bước 1, hãy dùng `project_id` trả về từ
> kết quả wizard làm chuẩn cho các bước sau (hoặc chấp nhận project riêng do wizard tạo).
> Muốn **tạo lại** bối cảnh của project đã có thì dùng `wizard_world_regenerate`, không gọi lại `wizard_world_building`.

```json
{
  "tool": "wizard_world_building",
  "arguments": {
    "title": "Đêm Trắng Trên Phố Cổ",
    "description": "Trinh thám đô thị",
    "theme": "Chuộc lỗi và sự thật",
    "genre": "Trinh thám đô thị",
    "chapter_count": 24,
    "narrative_perspective": "ngôi thứ ba giới hạn",
    "target_words": 120000
  }
}
```

Nếu project đã có bối cảnh và chỉ cần tạo lại:

```json
{ "tool": "wizard_world_regenerate", "arguments": { "project_id": "<project_id>" } }
```

```json
{ "tool": "wizard_career_system", "arguments": { "project_id": "<project_id>" } }
{ "tool": "wizard_characters", "arguments": { "project_id": "<project_id>", "count": 8, "requirements": "1 phản diện có động cơ rõ ràng" } }
{ "tool": "wizard_outline", "arguments": { "project_id": "<project_id>", "chapter_count": 24, "target_words": 120000 } }
{ "tool": "wizard_status", "arguments": { "project_id": "<project_id>" } }
```

Kết quả wizard trả về dạng `{ events, result, error, completed, progress }`. Hãy kiểm tra `error` trước khi dùng `result`.

### Bước 4 — Chương

```json
{ "tool": "list_chapters", "arguments": { "project_id": "<project_id>" } }
```

Nếu chưa có chương, tạo khung bằng `create_chapter`, rồi sinh nội dung:

```json
{ "tool": "generate_chapter", "arguments": { "chapter_id": "<chapter_id>", "target_word_count": 3000 } }
```

Trả về `task_id` → poll bằng `task_status`. Muốn viết liên tiếp nhiều chương:

```json
{
  "tool": "continue_chapters",
  "arguments": { "project_id": "<project_id>", "start_chapter_number": 1, "count": 5, "target_word_count": 3000 }
}
```

### Bước 5 — Xuất video

```json
{ "tool": "video_capabilities", "arguments": {} }
```

```json
{
  "tool": "create_video_export",
  "arguments": {
    "project_id": "<project_id>",
    "chapter_ids": ["<chapter_id>"],
    "options": { "resolution": "1280x720", "motion_mode": "local", "generate_scene_images": false }
  }
}
```

```json
{ "tool": "get_video_export", "arguments": { "job_id": "<job_id>" } }
```

Poll bằng `get_video_export` tới khi job xong. Nếu hỏng, `video_export_action` với `action="retry"`.
Khi xong:

```json
{ "tool": "video_download_paths", "arguments": { "job_id": "<job_id>" } }
```

`motion_mode`: `local` (FFmpeg, miễn phí) · `remote` (provider AI, **tính phí theo phân cảnh**) · `hybrid`.

---

## 8. Đăng ký MCP HTTP vào plugin manager trong app

Mục đích: để **Project Agent trong UI** cũng gọi được các tool này.

### 8.1. Luật chơi

- Bộ nạp tool chỉ dùng plugin kiểu **`http` / `streamable_http` / `sse`** (`backend/app/services/mcp_tools_loader.py`).
- Plugin kiểu **`stdio` được lưu trong DB nhưng KHÔNG được agent nội bộ nạp tool** → phải chạy MCP server ở chế độ HTTP.
- Endpoint thật là **`/api/mcp/plugins`** (không phải `/api/mcp-plugins`).
- Phải đăng ký bằng **session cookie của người dùng thật**: `require_login` cần `request.state.user` là một `User`.
  Xác thực bằng bearer `MUMU_MCP_TOKEN` cho ra `state.user = None`, nên **không** dùng được cho API này.

### 8.2. ⚠️ Ràng buộc SSRF: `127.0.0.1` bị chặn

Backend kiểm tra URL plugin bằng SSRF guard. Kết quả thực tế khi thử:

| URL đăng ký | Kết quả |
|---|---|
| `http://127.0.0.1:8765/mcp` | ❌ `400 URL không được trỏ tới địa chỉ nội bộ hoặc dành riêng` |
| `http://localhost:8765/mcp` | ❌ `400 URL không được trỏ tới địa chỉ máy cục bộ` |
| `http://192.168.1.50:8765/mcp` (IP LAN) | ❌ `400 URL không được trỏ tới địa chỉ nội bộ hoặc dành riêng` |
| `https://<host công khai>/mcp` | ✅ được chấp nhận |

Nghĩa là bạn **không thể** đăng ký thẳng `127.0.0.1:8765`. Chọn một trong hai:

1. **Expose qua tunnel/public host** (khuyến nghị cho dev): `cloudflared` / `ngrok`… trỏ tới cổng `8765`, rồi đăng ký
   `https://<tên-miền-công-khai>/mcp`.
2. Nếu MCP server nằm sau reverse proxy có domain công khai, đăng ký domain đó.

> Nếu bạn *cần* đăng ký URL loopback (ví dụ chạy hoàn toàn offline), phải nới lỏng kiểm tra SSRF trong
> `backend/app/api/mcp_plugins.py` / `backend/app/security.py` — đó là thay đổi code, xem như thay đổi bảo mật và cần cân nhắc riêng.

### 8.3. Tạo plugin

**Cách gọn — `config_json` chuẩn:**

```powershell
$cookie = "session_token=<session_token>"
$body = @{
  config_json = '{"mcpServers":{"mumuainovel":{"type":"streamable_http","url":"https://<tên-miền-công-khai>/mcp","headers":{"Authorization":"Bearer <session_token>"}}}}'
  category = "general"
  enabled = $true
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/mcp/plugins/simple" -Method POST `
  -ContentType "application/json" -Headers @{ Cookie = $cookie } -Body $body
```

**Cách đầy đủ:** `POST /api/mcp/plugins` với

```json
{
  "plugin_name": "mumuainovel",
  "display_name": "MuMuAINovel",
  "plugin_type": "streamable_http",
  "server_url": "https://<tên-miền-công-khai>/mcp",
  "headers": { "Authorization": "Bearer <session_token>" },
  "category": "general",
  "enabled": true
}
```

### 8.4. Kiểm tra bằng chứng

```powershell
$cookie = "session_token=<session_token>"

# status ban đầu là "pending" rồi chuyển "active" (đăng ký chạy ở background)
Invoke-RestMethod "http://127.0.0.1:8000/api/mcp/plugins" -Headers @{ Cookie = $cookie }

Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/mcp/plugins/<plugin_id>/test"  -Headers @{ Cookie = $cookie }
Invoke-RestMethod "http://127.0.0.1:8000/api/mcp/plugins/<plugin_id>/tools"        -Headers @{ Cookie = $cookie }
```

`status` = `active` và `/tools` trả danh sách công cụ nghĩa là Project Agent sẽ thấy chúng ở lượt chat kế tiếp.

---

## 9. Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `mumu_auth_status` → `authenticated: false` | Thiếu token, hoặc thiếu `MUMU_MCP_USER_ID` khi dùng shared token | Xem mục 4; dùng session token để khỏi cần user id |
| `Thiếu MUMU_MCP_USER_ID (hoặc MUMU_USER_ID)` | Token không phải session token có chữ ký nên không suy ra được user | Đặt `MUMU_MCP_USER_ID`, hoặc chuyển sang session token |
| `401` khi chạy `wizard_*` / `generate_chapter` | Backend không chấp nhận token | Với shared token: backend cũng phải có `MUMU_MCP_TOKEN` và đã restart |
| `MuMu API 401: Chưa đăng nhập` | Session token hết hạn (mặc định 120 phút) | Lấy token mới; hoặc tăng `SESSION_EXPIRE_MINUTES` |
| `ModuleNotFoundError: No module named 'app'` | Thiếu `PYTHONPATH` / chạy sai thư mục | Đặt `PYTHONPATH` = `...\MuMuAINovel\backend` |
| `mumu_health` → `degraded` | MCP server không kết nối được database | Kiểm tra `DATABASE_URL`, chạy MCP server trong cùng môi trường với backend |
| Client không thấy tool nào | Server crash lúc khởi động, hoặc `print()` làm bẩn stdout | Xem log stderr của client; chỉ log ra stderr |
| Wizard timeout / treo lâu | SSE chạy lâu; MCP client chờ (`timeout=None` ở phía server) | Kiểm tra log backend; **không** chạy lại tuỳ tiện (tạo dữ liệu trùng) |
| `create_category` lỗi `genre cần project_id` | Tool này chỉ gắn genre cho project có sẵn | Truyền `project_id` (hoặc tạo project trước) |
| `create_category` lỗi `career cần career_id` | Tool này chỉ đổi nhóm nghề có sẵn | Tạo nghề bằng API nghề nghiệp trước |
| Đăng ký plugin báo `URL không được trỏ tới địa chỉ nội bộ` | SSRF guard chặn loopback/LAN | Dùng tunnel/public host (mục 8.2) |
| `POST /api/mcp/plugins` trả `401 Cần đăng nhập` | Đang gọi bằng bearer token thay vì session cookie | Đăng ký bằng cookie của user thật |
| Plugin mãi `pending`/`error` | MCP HTTP server chưa bật, sai path `/mcp`, hoặc sai header bearer | Kiểm tra `/test`, đọc `last_error` |
| Xuất video `503` | Thiếu FFmpeg, hoặc thiếu API key cho `remote`/`hybrid` | Cài FFmpeg (`VIDEO_FFMPEG_BINARY`) hoặc dùng `motion_mode: "local"` |
| Tạo job bị từ chối khi đang có job chạy | `VIDEO_MAX_ACTIVE_JOBS` (mặc định 2) theo mỗi user | Poll/retry job cũ cho xong, hoặc tăng biến |

---

## 10. Ghi chú an toàn & giới hạn

- **Token/session = toàn bộ quyền của user đó.** Không commit, không dán vào issue, không đưa vào file mẫu.
- Các file trong `docs/mcp-configs/` cố tình **không chứa bí mật**.
- **Cách B (shared token) mở rộng bề mặt tấn công**: bất kỳ ai có token đó đều gọi được API với danh tính `user_id` cấu hình.
  Dùng chuỗi random mạnh, và chỉ bật khi MCP server/backend chạy trong mạng tin cậy.
- `remote`/`hybrid` **tốn tiền thật theo từng phân cảnh** — gọi `video_capabilities` và xác nhận với người dùng trước khi chạy.
- `video_download_paths` trả đường dẫn trên máy chủ; hãy kiểm tra quyền truy cập file trước khi đưa cho agent khác.
- Đừng expose cổng MCP HTTP (`8765`) ra Internet khi chưa có auth/tunnel kiểm soát.

---

## 11. Tài liệu liên quan

- [Mẫu cấu hình Cursor](./mcp-configs/cursor-mcp.json.example)
- [Mẫu cấu hình Claude Desktop](./mcp-configs/claude-desktop.json.example)
- [Mẫu cấu hình Grok (JSON)](./mcp-configs/grok-mcp.json.example) · [Grok (TOML)](./mcp-configs/grok-config.toml.example)
- [Script lấy token](../backend/scripts/issue_mcp_token.py)
- [Mô tả server (do tác giả server viết)](./mcp-server-implementation.md)
- Swagger UI: `http://127.0.0.1:8000/docs`
