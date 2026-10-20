## TTS Clone Studio 3.1.0

### Mới
- ⏸ **Khoảng nghỉ giữa câu** cho OmniVoice (trang 🌍 OmniVoice, thẻ mới dưới *Thông số tạo giọng*). OmniVoice hay đọc liền các câu ngắn như “Gold. pearls. silk. spice.”. Bật mục này thì app đọc từng cụm rồi chèn đúng số giây lặng bạn đặt sau mỗi dấu câu **nằm giữa đoạn**:

  | Dấu | Mặc định |
  |---|---|
  | Dấu phẩy `,` | 0,25 giây |
  | Chấm phẩy, hai chấm `; :` | 0,35 giây |
  | Dấu chấm, hỏi, than `. ? !` | 0,5 giây |
  | Ba chấm `…` `...` | 0,7 giây |

  - Cuối đoạn không thêm khoảng nghỉ; đoạn không có dấu câu ở giữa đọc như cũ.
  - Đặt 0 cho dấu nào thì không ngắt ở dấu đó. Số (`1,000`, `3.5`), viết tắt (`Dr.`, `U.S.`) và chữ cái viết tắt tên (`J. K.`) không bị ngắt.
  - Dùng được ở Đọc văn bản và Hàng loạt Excel. Không áp dụng khi đã đặt **Thời lượng (s)**.
  - Đoạn có nhiều dấu câu sẽ đọc lâu hơn một chút vì mỗi cụm là một lần tạo giọng.

### Tải bản nào?
| Máy | File |
|---|---|
| Windows (khuyên dùng) | `TTSCloneStudio-3.1.0-windows-setup.exe` |
| Windows, không muốn cài | `TTSCloneStudio-3.1.0-windows-portable.exe` |
| Mac chip Apple (M1–M4) | `TTSCloneStudio-3.1.0-mac-arm64.zip` |
| Mac chip Intel | `TTSCloneStudio-3.1.0-mac-x64.zip` |

Đang dùng bản 2.1 trở lên thì không cần tải: app sẽ hiện nút **⬆ Có bản mới** và tự cài. Những gì có từ 3.0 (OmniVoice, hai kiểu giao diện, bỏ MiniMax) giữ nguyên.
