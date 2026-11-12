## TTS Clone Studio 3.1.1

### Sửa lỗi
- **OmniVoice đọc thêm một tiếng lạ (ví dụ "ten de") ở đầu mỗi câu/cụm.** Nguyên nhân: file mẫu dùng để clone giọng bị cắt **giữa lúc đang nói** (ví dụ "…a exten|"). Model tưởng phần cuối chưa được nói nên đọc bù nó ở đầu **mỗi lần tạo** — khi bật ⏸ Khoảng nghỉ giữa câu, mỗi cụm là một lần tạo nên tiếng này lặp lại ở mọi chỗ ngắt.
  - Khi clone giọng OmniVoice, app tự phát hiện mẫu bị cắt giữa lúc nói, **cắt về chỗ nghỉ gần nhất** (giữ ít nhất 3 giây) và chép lại lời thoại mẫu bằng Whisper cho khớp. Mẫu không có chỗ nghỉ để cắt thì app cảnh báo.
  - Giọng đã tạo từ trước bằng mẫu bị cắt: khi đọc, nhật ký hiện cảnh báo kèm cách sửa.

### Cách sửa giọng đang bị lỗi
1. Trang **🧬 Clone giọng** › nhà cung cấp **OmniVoice**.
2. Chọn lại file mẫu (file gốc, hoặc file `.wav` của giọng mà nhật ký cảnh báo chỉ ra).
3. **Để trống ô lời thoại mẫu**, đặt tên rồi bấm **Bắt đầu Clone** — app tự cắt về chỗ nghỉ và chép lời.
4. Dùng giọng mới, xoá giọng cũ.

### Tải bản nào?
| Máy | File |
|---|---|
| Windows (khuyên dùng) | `TTSCloneStudio-3.1.1-windows-setup.exe` |
| Windows, không muốn cài | `TTSCloneStudio-3.1.1-windows-portable.exe` |

Bản 3.1.1 **chỉ có Windows**; máy Mac tiếp tục dùng 3.1.0 (bản Mac sẽ có ở lần phát hành sau). Windows đang dùng bản 2.1 trở lên thì không cần tải: app sẽ hiện nút **⬆ Có bản mới** và tự cài.
