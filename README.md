# 🎙 TTS Clone Studio 2.2

Ứng dụng **Windows & macOS**: **clone giọng nói → đọc văn bản → xuất MP3 / MP4**, chạy lẻ hoặc hàng loạt từ file Excel.
Hỗ trợ 2 nhà cung cấp: **Inworld** và **MiniMax** (API chính thức). **Tự cập nhật** qua GitHub Releases.

---

## 0. Tải & cài (cách dễ nhất — không cần Python)

Vào mục **Releases** của kho GitHub này, tải file hợp với máy:

| Máy | File | Cách cài |
|---|---|---|
| Windows 10/11 (khuyên dùng) | `TTSCloneStudio-x.y.z-windows-setup.exe` | Nháy đúp → Next → Install. Không cần quyền quản trị |
| Windows, không muốn cài | `TTSCloneStudio-x.y.z-windows-portable.exe` | Chép vào thư mục bất kỳ, nháy đúp để chạy |
| Mac chip Apple (M1–M4) | `TTSCloneStudio-x.y.z-mac-arm64.zip` | Nháy đúp file zip → kéo **TTSCloneStudio** vào **Applications** |
| Mac chip Intel | `TTSCloneStudio-x.y.z-mac-x64.zip` | như trên |

- **Windows**: nếu SmartScreen báo *Windows protected your PC / Unknown publisher* → bấm **More info › Run anyway** (bình thường với phần mềm chưa mua chứng chỉ ký số).
- **macOS 13 trở lên.** Lần đầu mở, macOS chặn vì app chưa ký bằng Apple Developer ID:
  - macOS 14 trở xuống: **chuột phải vào app › Open › Open**.
  - macOS 15 trở lên: mở app 1 lần (bị chặn) → **System Settings › Privacy & Security** → kéo xuống bấm **Open Anyway**.
  - Hoặc mở Terminal và chạy: `xattr -dr com.apple.quarantine /Applications/TTSCloneStudio.app`
- Lần cập nhật sau, macOS có thể hỏi lại quyền đọc Keychain (nơi lưu API key) → bấm **Always Allow**.

### Tự cập nhật
App tự kiểm tra bản mới khi mở (và 6 giờ/lần). Có bản mới sẽ hiện nút cam **⬆ Có bản mới** trên thanh tiêu đề, hoặc vào trang **🔄 Cập nhật** → **Tải & cài bản mới**. App tự tải, kiểm tra mã SHA-256, đóng lại, cài và mở lại. Giọng, cài đặt và API key giữ nguyên.
Bản **cài đặt** được cài đè im lặng; bản **portable** được thay file; bản **Mac** được thay trong Applications (có hoàn tác nếu lỗi). Nhật ký cập nhật: trang Cập nhật › **📝 Nhật ký cập nhật**.

---

## 1. Chạy từ mã nguồn (cho người muốn tự build)

1. Cài **Python 3.12** từ https://www.python.org/downloads/ — khi cài **nhớ tích ô "Add python.exe to PATH"**.
2. Giải nén thư mục này ra một chỗ cố định (ví dụ `D:\TTS_Clone_Studio`).
3. Nháy đúp **`install.bat`** → chờ 1–3 phút (cần Internet).
   Xong sẽ có biểu tượng **TTS Clone Studio** ngoài Desktop.

> Nếu báo *"Không tìm thấy Python"* dù đã cài: vào **Settings › Apps › Advanced app settings › App execution aliases**, tắt 2 mục `python.exe` và `python3.exe`, rồi chạy lại `install.bat`.

**Mở ứng dụng:** nháy đúp `run.bat` hoặc biểu tượng ngoài Desktop.

### Muốn có 1 file .exe để mang sang máy khác?
Nháy đúp **`build_exe.bat`** → nhận `dist\TTSCloneStudio.exe` (không cần cài Python trên máy dùng).
Lần đầu mở, Windows SmartScreen có thể báo *Unknown publisher* → bấm **More info › Run anyway** (bình thường với phần mềm tự đóng gói).

---

## 2. Sử dụng

| Bước | Trang | Việc cần làm |
|---|---|---|
| 1 | ⚙ **Cài đặt API** | Dán API key Inworld và/hoặc MiniMax → **🔌 Kiểm tra kết nối** → **💾 Lưu** |
| 2 | 🧬 **Clone giọng** | Chọn nhà cung cấp, chọn file giọng mẫu, đặt tên, tích xác nhận quyền → **Bắt đầu Clone**. Hoặc **☁ Duyệt giọng Inworld** (lọc, nghe thử, dùng ngay) / **🔄 Đồng bộ Inworld** / **☁ Lấy từ MiniMax** |
| 3 | 🗣 **Đọc văn bản** | Chọn giọng, dán nội dung, chọn **MP3 / MP4 / Cả hai** → **🔊 Tạo giọng đọc** |
| – | 🎭 **Delivery (Inworld)** | Ổn định / Cân bằng / Sáng tạo, ✨ khử nhiễu, 💬 chỉ dẫn phong cách (model inworld-tts-2). Model mặc định: `inworld-tts-2-flash` |
| 4 | 📊 **Hàng loạt Excel** | Chọn file `.xlsx`, chọn cột nội dung và cột tên file → **🚀 Chạy hàng loạt** |
| – | 💳 **Gói & mức dùng** | Ở trang Cài đặt API: chọn gói Inworld, nhập số dư đang thấy trên Billing → app tự tính ký tự/tiền đã dùng, còn lại và % |
| – | 🎬 **Video MP4** | Chọn ảnh nền, màu nền, khung hình (16:9, 9:16 Shorts/TikTok, 1:1) |

### File Excel
Dòng đầu là tiêu đề. Ví dụ (bấm **📥 Tạo file Excel mẫu** để có sẵn):

| filename | text |
|---|---|
| 0001 | Xin chào, đây là dòng thứ nhất. |
| 0002 | Đây là dòng thứ hai. |

- Cột tên file có thể để **🔢 Tự đánh số** (0001, 0002…). Tên trùng sẽ tự thêm `_2`, `_3`.
- **🔢 Chỉ chạy STT**: gõ `1-10, 15, 20-` để chỉ chạy các dòng có số thứ tự đó (cột STT trong bảng); để trống = chạy tất cả.
- **Bỏ qua dòng đã có file**: chạy tiếp từ chỗ dừng mà không tốn phí tạo lại.
- **Gộp tất cả thành 1 file**: tạo thêm `TenExcel_GOP.mp3/.mp4` theo thứ tự dòng.
- **Số luồng**: 2–3 là an toàn; cao quá dễ bị nhà cung cấp giới hạn tốc độ.
- **🔁 Chạy lại dòng lỗi**: chỉ chạy lại các dòng lỗi.

### Giọng mẫu để clone
| | Inworld | MiniMax |
|---|---|---|
| Định dạng | WAV, MP3 | WAV, MP3, M4A |
| Độ dài | 5–30 giây (tốt nhất 10–30) | 10 giây – 5 phút |
| Lưu ý | | Giọng clone **bị xóa nếu 7 ngày không dùng** → bấm **▶ Nghe thử** ngay sau khi clone |

Mẫu tốt: 1 người nói, rõ, không nhạc nền, không vang. Chỉ clone giọng của bạn hoặc giọng đã được người nói cho phép.

---

## 3. Dữ liệu & bảo mật

- API key lưu trong **Windows Credential Manager** / **macOS Keychain** (không ghi ra file). Có thể dùng biến môi trường `INWORLD_API_KEY` / `MINIMAX_API_KEY`.
- Danh sách giọng, cài đặt, nhật ký: Windows `%APPDATA%\TTSCloneStudio\`, macOS `~/Library/Application Support/TTSCloneStudio/` (nút **📁 Mở thư mục dữ liệu** trong app).
- ffmpeg được cài sẵn qua gói `imageio-ffmpeg` — không cần tự cài. Nếu muốn dùng ffmpeg riêng, đặt `ffmpeg.exe` cạnh ứng dụng.

## 4. Gặp lỗi?

| Hiện tượng | Cách xử lý |
|---|---|
| `API key sai…(HTTP 401/403)` / `MiniMax lỗi 1004` | Kiểm tra lại key ở trang Cài đặt |
| `MiniMax lỗi 2042` | Giọng đã bị xóa do 7 ngày không dùng → clone lại |
| `HTTP 429` / `MiniMax bận` | Giảm số luồng; app tự thử lại 4 lần |
| Không mở được app | Xem `TTSCloneStudio_crash.log` cạnh ứng dụng hoặc `%APPDATA%\TTSCloneStudio\app.log` |
| `install.bat` lỗi | Gửi file `install_log.txt` cho người hỗ trợ |

## 5. Cho người phát triển

```
launcher.py   điểm khởi động, bắt lỗi khởi động       app_info.py  PHIÊN BẢN + kho GitHub (sửa ở đây)
main.py       giao diện (PyQt6)                       theme.py     màu sắc sáng/tối
widgets.py    thành phần UI dùng lại                  dialogs.py   hộp thoại thêm/lấy giọng
providers.py  API Inworld + MiniMax                   workers.py   luồng chạy nền, batch
media.py      ffmpeg: ghép audio, MP4                 storage.py   cấu hình, thư viện giọng, keyring
updater.py    tự cập nhật qua GitHub Releases         selfcheck.py tự kiểm tra app đã đóng gói (CI)
usage.py      bảng giá + bộ đếm gói/số dư Inworld
installer/    Inno Setup (.iss) cho bộ cài Windows    tools/       kiểm tra tĩnh + chạy tự kiểm tra CI
tests/        kiểm thử (unittest, GUI, cập nhật)      .github/workflows/build.yml  build & phát hành
```

Chạy kiểm thử: `python self_test.py`, `python -m unittest discover -s tests -v`,
`QT_QPA_PLATFORM=offscreen python tests/smoke_gui.py -`, `… tests/update_gui_test.py`, `python tools/check_repo.py`.

### Phát hành bản mới
1. Sửa `APP_VERSION` trong `app_info.py` (ví dụ `2.1.1`) và viết `RELEASE_NOTES.md` (phải nhắc số phiên bản).
2. `git commit` + `git push` → GitHub Actions tự build & kiểm thử trên Windows + 2 loại Mac.
3. Khi build xanh: **Actions › Build & Release › Run workflow › tick “publish” › Run**
   (hoặc đẩy tag `v2.1.1`). Workflow tạo Release với đủ 4 file + `SHA256SUMS.txt`.
4. Máy người dùng tự thấy bản mới. Kho GitHub phải để **Public** thì app mới đọc được Releases.

Workflow kiểm tra trên máy thật: chạy toàn bộ kiểm thử trên cả 3 hệ điều hành; đóng gói; mở app đã đóng gói ở chế độ
tự kiểm tra (vẽ đủ 7 trang, chạy ffmpeg đi kèm tạo MP4, keyring, chứng chỉ HTTPS); cài im lặng bộ cài → tự kiểm tra →
gỡ cài đặt; chạy thật script cập nhật (thay file portable trong thư mục tên tiếng Việt, cài đè bằng setup.exe, thay
.app trên Mac rồi xác minh chữ ký); kiểm tra kiến trúc arm64/x86_64 và chữ ký `codesign --verify --strict`.
