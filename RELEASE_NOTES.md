## TTS Clone Studio 2.3.0

### Mới
- 📈 **Trang Mức dùng Inworld** (mục mới trên thanh bên trái), trình bày giống trang Usage của Inworld: chọn **24 giờ / 7 ngày / 30 ngày / 90 ngày**, xem **Theo model** hoặc **Tổng**, biểu đồ cột theo ngày (theo giờ khi xem 24 giờ), biểu đồ tròn, bảng ký tự, tiền ước tính và tỷ lệ của từng model.
- 🔄 **Đồng bộ với Inworld**: chép số dư ở trang Billing và số ký tự (tổng + từng model) ở trang Usage vào app. App lấy đúng số đó làm mốc, rồi tự cộng mỗi lần đọc sau đó, nên số trong app khớp với Inworld, kể cả phần đọc ở Playground, API key khác hay bản app cũ. Gõ được kiểu `2,755`, `2.5K`, `$22.10`; nếu bảng Inworld làm tròn (2.5K), app dùng số tổng chính xác để tính lại.
- 💳 Nút **Inworld còn …%** trên thanh tiêu đề bấm vào là mở trang Mức dùng.

### Lưu ý
- Inworld không có API để đọc số dư hay usage, nên cần bấm 🔄 Đồng bộ và chép số (mất khoảng 30 giây). Nên đồng bộ lại đầu tháng hoặc sau khi nạp tiền.
- Trang Usage của Inworld cập nhật khoảng mỗi giờ, nên các lần đọc trong 1–2 giờ gần nhất được app tự cộng thêm.
- Số liệu cũ của bản 2.2 được giữ nguyên và chuyển sang lịch sử mới.

### Tải bản nào?
| Máy | File |
|---|---|
| Windows (khuyên dùng) | `TTSCloneStudio-2.3.0-windows-setup.exe` |
| Windows, không muốn cài | `TTSCloneStudio-2.3.0-windows-portable.exe` |
| Mac chip Apple (M1–M4) | `TTSCloneStudio-2.3.0-mac-arm64.zip` |
| Mac chip Intel | `TTSCloneStudio-2.3.0-mac-x64.zip` |

Đang dùng bản 2.1.0 hoặc 2.2.0 thì không cần tải: app sẽ hiện nút **⬆ Có bản mới** và tự cài.
