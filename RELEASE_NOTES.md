## TTS Clone Studio 3.3.0

### Mới: ⏱ Ghi mốc thời gian từng từ vào MP3 (cho CapCut Draft Studio)
Mỗi file MP3 tạo ra giờ mang theo **mốc thời gian chính xác của từng từ** được đọc. CapCut Draft Studio 0.6.3+ đọc mốc này để đồ họa chữ hiện **đúng lúc giọng nói tới** thay vì ước lượng (bản trước có thể lệch 0,5–1 giây ở câu dài).

- **Inworld:** máy chủ Inworld trả sẵn mốc cùng lúc đọc — **không tốn thêm phí**, chỉ chậm thêm rất ít. Văn bản dài được chia đoạn thì mốc vẫn được nối đúng giờ.
- **OmniVoice:** Whisper (đã có trong bộ máy) nghe lại file vừa tạo để lấy mốc — mỗi file chậm thêm vài giây; lần đầu phải tải model Whisper ~1,6 GB. Nếu Whisper lỗi, file giọng vẫn được tạo bình thường (chỉ không có mốc).
- Mốc nằm **ngay trong file MP3**, âm thanh không bị đổi chút nào. Chép MP3 vào thư mục `Audio/` của CapCut Draft Studio như mọi khi là đủ — không có file phụ nào phải nhớ chép theo.
- Bật/tắt: ô **⏱ Ghi mốc thời gian từng từ vào MP3** ở trang 📊 Hàng loạt (hoặc **⏱ Ghi mốc từng từ** ở trang 🗣 Đọc văn bản). Mặc định **bật**.
- Bảng kết quả hàng loạt có thêm dấu ⏱ ở dòng đã ghi mốc.
- Model Inworld nào không hỗ trợ mốc thì app tự đọc bình thường và báo trong nhật ký.

File giọng tạo bằng bản cũ không có mốc: CapCut Draft Studio vẫn chạy kiểu ước lượng. Muốn khớp chính xác cho video đang làm thì tạo lại giọng bằng bản 3.3.0.

### Tải bản nào?
| Máy | File |
|---|---|
| Windows (khuyên dùng) | `TTSCloneStudio-3.3.0-windows-setup.exe` |
| Windows, không muốn cài | `TTSCloneStudio-3.3.0-windows-portable.exe` |

Bản 3.3.0 **chỉ có Windows**; máy Mac tiếp tục dùng 3.1.0. Windows đang dùng bản 2.1 trở lên thì không cần tải: app sẽ hiện nút **⬆ Có bản mới** và tự cài.
