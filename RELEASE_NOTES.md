## TTS Clone Studio 3.0.0

### Mới
- 🌍 **OmniVoice — miễn phí, chạy ngay trên máy bạn** (model mã nguồn mở của k2-fsa, bản 0.2.1). Không cần API key, không tính tiền theo ký tự, hơn 600 ngôn ngữ. Trang mới **OmniVoice** trên thanh bên trái:
  - **⬇ Cài đặt bộ máy** một lần: app tự tải Python riêng, PyTorch (bản GPU nếu máy có card NVIDIA, không thì bản CPU; Mac chip Apple dùng GPU của máy) và OmniVoice. Không đụng tới Python hay phần mềm khác trên máy.
  - **🧬 Clone giọng** bằng OmniVoice ở trang Clone giọng: mẫu 3–10 giây, nhập lời thoại của mẫu hoặc bấm **📝 Tự chép lời** (Whisper). Giọng được lưu thành Voice ID dùng lại mãi.
  - **🎨 Thiết kế giọng** không cần file mẫu: chọn giới tính, độ tuổi, cao độ, thì thầm, giọng tiếng Anh (Mỹ, Anh, Úc…), phương ngữ tiếng Trung → **Tạo thử** → ưng thì **Lưu**. Để tất cả “Tự động” là để model tự chọn giọng (Auto Voice).
  - **🎛 Thông số tạo giọng** đầy đủ như OmniVoice: số bước, CFG, khử nhiễu, ép thời lượng, tốc độ, đọc số thành chữ, cắt khoảng lặng, t_shift, nhiệt độ, độ dài mỗi đoạn, đệm/fade.
  - **➕ Chèn tiếng động** (`[laughter]`, `[sigh]`…), sửa phát âm bằng pinyin / âm CMU, chọn model khác hoặc thư mục checkpoint riêng ở ô Model.
  - Giọng OmniVoice dùng được ở mọi nơi như giọng Inworld: Đọc văn bản, Hàng loạt Excel (kể cả chạy theo STT, gộp file), MP3/MP4.
- 🎨 **Hai kiểu giao diện** (Cài đặt API › Giao diện): **Cổ điển** như trước, hoặc **Youwee** — kính mờ, một màu nhấn, 6 chủ đề màu (Ocean, Midnight, Aurora, Sunset, Forest, Candy), có cả Sáng và Tối.

### Thay đổi
- **Đã bỏ nhà cung cấp MiniMax.** Giọng MiniMax trong thư viện được gỡ khi mở bản này (danh sách cũ lưu ở `voices_removed.json` trong thư mục dữ liệu); API key MiniMax đã lưu cũng được xóa khỏi máy. Inworld giữ nguyên mọi tính năng.

### Lưu ý về OmniVoice
- Cần ổ đĩa trống khoảng **8 GB (CPU / Mac)** đến **14 GB (GPU NVIDIA)** và mạng ổn định cho lần cài đầu; lần đọc đầu tiên tải thêm model. Tất cả nằm trong thư mục dữ liệu của app, gỡ được bằng nút **🗑 Gỡ**.
- Có card NVIDIA thì đọc nhanh hơn thời gian thực nhiều lần; chỉ có CPU vẫn chạy được nhưng chậm.
- Mac chip Intel không dùng được OmniVoice (PyTorch không còn hỗ trợ), các tính năng khác vẫn bình thường.
- Giọng OmniVoice chỉ nằm trên máy tạo ra nó. Chỉ clone giọng của bạn hoặc giọng đã được người nói cho phép.

### Tải bản nào?
| Máy | File |
|---|---|
| Windows (khuyên dùng) | `TTSCloneStudio-3.0.0-windows-setup.exe` |
| Windows, không muốn cài | `TTSCloneStudio-3.0.0-windows-portable.exe` |
| Mac chip Apple (M1–M4) | `TTSCloneStudio-3.0.0-mac-arm64.zip` |
| Mac chip Intel | `TTSCloneStudio-3.0.0-mac-x64.zip` |

Đang dùng bản 2.1–2.3 thì không cần tải: app sẽ hiện nút **⬆ Có bản mới** và tự cài.
