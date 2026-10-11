# Tạo video bằng Muse Tool

MuMuAINovel gọi API Muse Tool từ backend chạy native trên cùng máy Windows. Mỗi phân cảnh gửi một prompt, lưu ID tác vụ, theo dõi trạng thái và tải MP4 vào thư mục video của MuMuAINovel. Khi thử lại tác vụ đang chạy, backend tiếp tục theo dõi ID cũ. Request tạo video có khóa chống tạo trùng.

1. Mở Muse Tool bằng `npm start`, đăng nhập Muse và kiểm tra kết nối.
2. Trong `.env` của thư mục chạy backend, thêm:

   ```dotenv
   VIDEO_MOTION_MUSE_CONFIG_FILE=C:/Users/YOUR_USER/AppData/Roaming/muse-tool/video-api.json
   ```

   Đây là đường dẫn tới cấu hình local, backend đọc key và port từ file. Không đưa file này vào Git. Có thể dùng `VIDEO_MOTION_MUSE_API_KEY` và `VIDEO_MOTION_MUSE_BASE_URL=http://127.0.0.1:8910` thay thế. Base URL không có `/v1`.
3. Khởi động lại backend. Mở **Xuất video**, chọn chế độ **remote** và provider **Muse Tool (local)**, model `muse-video`.
4. Chọn tỉ lệ, tạo storyboard/video như bình thường. Provider chọn thời lượng gần nhất trong 5, 10, 15 giây theo độ dài phân cảnh. Độ phân giải chọn **Theo Muse**.

Provider tạo video từ prompt. Ảnh bìa và ảnh phân cảnh không được gửi sang Muse; có thể tắt tạo ảnh phân cảnh để tránh tạo ảnh không cần thiết. Không bắt buộc có ảnh bìa. Muse hỗ trợ ghép một giọng kể TTS riêng sau khi tải clip: audio Muse được thay hoàn toàn; nếu lời kể dài hơn clip thì chuyển động cả clip được giảm tốc; nếu ngắn hơn thì cắt clip theo lời kể, không lặp khung cuối. Các provider remote khác vẫn chưa ghép TTS. Muse quyết định độ phân giải và thời lượng thực tế; phụ đề dùng độ dài clip tải về.

Muse Tool cần mở trong suốt quá trình xử lý. Hủy trong MuMuAINovel dừng theo dõi/tải, chưa hủy được tác vụ trong Muse. Có thể thử lại để tiếp tục cùng tác vụ. Nếu Muse Tool báo lỗi sau khi prompt đã gửi, kiểm tra chat Muse trước khi yêu cầu tạo lại vì Muse có thể vẫn xử lý.

API chỉ nghe trên `127.0.0.1`; backend trong Docker không truy cập được localhost Windows. Với tích hợp này hãy chạy backend native cùng máy; không đặt `host.docker.internal` làm base URL khi Muse Tool vẫn chỉ nghe loopback. Không cần mở API ra LAN.

Ví dụ chạy backend từ thư mục gốc để đọc `.env` tại đó:

```powershell
py -3 -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Kiểm thử adapter dùng mock HTTP, không tiêu hao hạn mức:

```powershell
py -3 -m pytest backend/tests/test_muse_tool_provider.py -q
```

## Hạn chế lỗi nối cảnh

Với Muse Tool, tạo phim mới dùng storyboard theo đoạn/sự kiện, giữ trọn lời thoại trong dấu ngoặc kép và tách mốc chuyển ngày/đêm. Trước khi gửi video, màn hình duyệt cho phép sửa trạng thái đầu/cuối, địa điểm, thời điểm, ánh sáng và danh sách người xuất hiện. Phải giữ trạng thái cuối cảnh trước trùng với trạng thái đầu cảnh sau; chỉ cho phép đổi thời gian khi có chủ ý. Preview không gọi Muse hay tạo video. Nếu nội dung chương đổi sau preview, request tạo job bị từ chối để duyệt lại.

- **Im lặng** (mặc định): prompt yêu cầu không nói, và hậu kỳ loại track audio Muse để bảo đảm không có lời kể tự sinh.
- **Tiếng môi trường**: prompt yêu cầu ambience, không lời nói; đây chỉ là chỉ dẫn, cần nghe duyệt.
- **Giữ audio Muse**: giữ giọng do Muse sinh; có nguy cơ lệch giọng hoặc đọc văn xuôi.
- **TTS**: bật một provider/model giọng kể cố định. Muse được yêu cầu im lặng, rồi backend thay track bằng lời kể. Đây là một người kể đọc nội dung truyện; chưa phải hệ thống thoại đa nhân vật hay lip-sync.

Các ràng buộc chỉ bằng chữ, không có frame tham chiếu/seed. Không bảo đảm nhân vật/ánh sáng khớp tuyệt đối. Storyboard tự chia theo cấu trúc văn bản, chưa tự hiểu mọi trạng thái hành động; cần duyệt, đặc biệt ở chỗ đến/rời bến và đổi thời gian. Khi TTS/hậu kỳ lỗi, tác vụ báo lỗi; nếu clip Muse đã hoàn tất thì thử lại tiếp tục tải clip cũ, không tự tạo clip mới.

Phim và tác vụ cũ giữ options trước đây. Muốn áp dụng storyboard/audio mới cần tạo job mới; chưa tự dựng lại hay tiêu hao thêm hạn mức từ thay đổi code.