# Thí nghiệm trạng thái tập trung — Màn hình & Luồng chạy

Tài liệu này mô tả **toàn bộ màn hình người tham gia thấy** và **thứ tự (flow)** của một phiên đo, sinh tự động từ mã nguồn (`content.py` = chữ, `settings.py` = thời lượng/tham số). Xem bản trực quan tại [`experiment_scenes_timeline.html`](experiment_scenes_timeline.html).

> Chạy cả phiên: `python code/experiment/run_all_experiments.py` (cửa sổ **toàn màn hình**). Hộp thoại **MSSV / Age / Gender / Handedness** hiện trước, rồi phiên tự chạy.


## 1. Luồng một phiên đo

```
Hộp thoại thông tin (MSSV, Age, Gender, Handedness)
   │
   ▼
Chào mừng (WELCOME, ~6s)
   ▼
TRẠNG THÁI NỀN — 3 phút LIÊN TỤC (giới thiệu trước, rồi 6 bước):
   ├─ Kiểm tra tín hiệu (0–10s)   — nhìn dấu +
   ├─ Mở mắt nghỉ (10–70s)        — nhìn dấu +
   ├─ Chớp mắt (70–90s)           — 5 lần theo hiệu lệnh 'Chớp mắt'
   ├─ Nhìn ngang (90–105s)        — theo chấm: trái–giữa–phải–giữa
   ├─ Nhìn dọc (105–120s)         — theo chấm: lên–giữa–xuống–giữa
   └─ Nhắm mắt nghỉ (120–180s)    → tiếng bíp + 'Mở mắt'
   ▼
6 BÀI TẬP  (thứ tự NGẪU NHIÊN, nghỉ 1 phút giữa các bài)
   mỗi bài:  Hướng dẫn → Đếm ngược 5s → Nhiệm vụ (~3:00) → (phản hồi trong lúc làm)
   ▼
Tổng kết (FINAL, ~8s — nhấn SPACE để đóng)
```
- **ESC**: dừng cả phiên (dữ liệu đã làm vẫn được lưu).
- **SPACE không bỏ qua** hướng dẫn / trạng thái nền / nhiệm vụ; chỉ dùng để đóng màn hình **kết thúc**.


## 2. Dòng thời gian (một ví dụ thứ tự ngẫu nhiên)

| # | Khối | Thời lượng |
|---|------|-----------|
| 1 | Chào mừng + giới thiệu nền | 0:12 |
| 2 | Nền — Kiểm tra tín hiệu (0–10s) | 0:10 |
| 3 | Nền — Mở mắt nghỉ (10–70s) | 1:00 |
| 4 | Nền — Chớp mắt (5 lần) (70–90s) | 0:20 |
| 5 | Nền — Nhìn ngang (90–105s) | 0:15 |
| 6 | Nền — Nhìn dọc (105–120s) | 0:15 |
| 7 | Nền — Nhắm mắt nghỉ (120–180s) | 1:00 |
| 8 | Hướng dẫn — Passive Video | ~0:20 |
| 9 | Đếm ngược — Passive Video | 0:05 |
| 10 | **Passive Video** (nhiệm vụ) | 3:00 |
| 11 | Nghỉ | 1:00 |
| 12 | Hướng dẫn — Addition | ~0:30 |
| 13 | Đếm ngược — Addition | 0:05 |
| 14 | **Addition** (nhiệm vụ) | 3:00 |
| 15 | Nghỉ | 1:00 |
| 16 | Hướng dẫn — Fairy Tale | ~0:30 |
| 17 | Đếm ngược — Fairy Tale | 0:05 |
| 18 | **Fairy Tale** (nhiệm vụ) | 3:00 |
| 19 | Nghỉ | 1:00 |
| 20 | Hướng dẫn — CPT-X | ~0:30 |
| 21 | Đếm ngược — CPT-X | 0:05 |
| 22 | **CPT-X** (nhiệm vụ) | 3:00 |
| 23 | Nghỉ | 1:00 |
| 24 | Hướng dẫn — Multiplication | ~0:30 |
| 25 | Đếm ngược — Multiplication | 0:05 |
| 26 | **Multiplication** (nhiệm vụ) | 3:00 |
| 27 | Nghỉ | 1:00 |
| 28 | Hướng dẫn — Stroop A | ~0:30 |
| 29 | Đếm ngược — Stroop A | 0:05 |
| 30 | **Stroop A** (nhiệm vụ) | 3:00 |
| 31 | Tổng kết | 0:08 |

**Tổng thời lượng xấp xỉ: ~29:40** — Hướng dẫn / Đếm ngược / Nhiệm vụ được **tách riêng**; trạng thái nền là 3 phút liên tục chia 6 bước. Hướng dẫn ~30s/bài (20s cho video); đếm ngược 5s/bài. **Tín hiệu được ghi liên tục suốt phiên** — không đánh dấu ghi theo từng khối.


## 3. Các màn hình chung (phần phiên)


### Hộp thoại thông tin (trước khi bắt đầu)

> MSSV:  ______  
> Age:  ______  
> Gender:  [Female / Male / Other]  
> Handedness:  [Right / Left / Ambidextrous]

Hộp thoại PsychoPy hiện MỘT LẦN trước phiên; điền rồi bấm **OK** (Cancel để hủy). Giá trị MSSV = tên thư mục kết quả.

### Chào mừng (WELCOME)

> Chào mừng bạn!  
> &nbsp;  
> Hôm nay chúng ta sẽ có 7 nhiệm vụ.  
> Nhiệm vụ đầu tiên của bạn là đo trạng thái nền   
> (bạn sẽ được yêu cầu mở mắt trong 1 phút 30 giây rồi nhắm mắt trong 1 phút 30 giây),  
> tiếp theo đó sẽ là sáu bài tập ngắn.  
> Bạn sẽ thực hiện lần lượt từng nhiệm vụ.  
> Mọi thứ diễn ra tự động — bạn chỉ thực hiện theo  
> hướng dẫn trên màn hình trước mỗi bài tập.

Tự chuyển sau ~6s.

### Giới thiệu trạng thái nền (BASELINE_INTRO)

> Trạng thái nền (3 phút)  
> &nbsp;  
> Hãy làm theo hướng dẫn trên màn hình và GIỮ ĐẦU CỐ ĐỊNH:  
> nhìn dấu +, chớp mắt theo hiệu lệnh,  
> đưa mắt nhìn theo chấm (ngang rồi dọc),  
> cuối cùng nhắm mắt cho đến khi nghe tiếng bíp.

Hiện MỘT LẦN trước khối 3 phút, giải thích cả chuỗi 6 bước.

### Trạng thái nền — 3 phút LIÊN TỤC (6 bước)

Một lần ghi liên tục; màn hình đổi nội dung ở mỗi mốc thời gian, GIỮ ĐẦU CỐ ĐỊNH suốt quá trình:

| Khoảng | Bước | Màn hình | Việc cần làm |
|--------|------|----------|--------------|
| 0–10s | Kiểm tra tín hiệu | dấu **+** | nhìn dấu +, giữ yên (kỹ thuật viên kiểm tra) |
| 10–70s | Mở mắt nghỉ | dấu **+** | nhìn dấu +, thư giãn |
| 70–90s | Chớp mắt | chữ **“Chớp mắt”** nhấp nháy | chớp mắt 5 lần theo hiệu lệnh |
| 90–105s | Nhìn ngang | **chấm trắng** di chuyển | nhìn theo chấm: trái–giữa–phải–giữa |
| 105–120s | Nhìn dọc | **chấm trắng** di chuyển | nhìn theo chấm: lên–giữa–xuống–giữa |
| 120–180s | Nhắm mắt nghỉ | “Nhắm mắt lại” → dấu + | nhắm mắt đến khi nghe tiếng bíp |

Kết thúc: **tiếng bíp** + chữ **“Mở mắt”** (Windows `winsound.Beep` 1000Hz/500ms; macOS `afplay`).


### Nghỉ giữa các bài (REST)

> Nghỉ  
> &nbsp;  
> Ngồi yên, mở mắt, thư giãn.  
> Bài tập tiếp theo sẽ sớm bắt đầu.

**1:00** (1 phút), chỉ giữa các bài tập.

## 4. Sáu bài tập

| Bài tập | Thời lượng | Phím trả lời | Phản hồi sau khi trả lời | Đếm ngược |
|--------|:---------:|-------------|--------------------------|:---:|
| **Quan sát video** (Passive Video) | 3:00 | — (thụ động) | — | 5s |
| **Đọc truyện** (Fairy Tale) | 3:00 | SPACE/→ trang sau, ← trang trước | — | 5s |
| **Phép cộng** (Addition) | 3:00 | phím số + ENTER (BACKSPACE xóa) | “Đúng!” / “Sai! Đáp án: N” (~1.5s) | 5s |
| **CPT-X** | 3:00 | X→**C**, chữ khác→**SPACE** | “Đúng” / “Sai” (~400ms) | 5s |
| **Phép nhân** (Multiplication) | 3:00 | phím số + ENTER | “Đúng!” / “Sai! Đáp án: N” (~1.5s) | 5s |
| **Stroop** | 3:00 | XANH DƯƠNG/XANH LÁ→**C**, ĐỎ/VÀNG→**M** | **chỉ “Sai”** (đúng = trống; quá giờ = “Phản hồi chậm”) | 5s |

### Chuỗi màn hình của mỗi bài tập

Mỗi bài (trong phiên) diễn ra theo thứ tự:

1. **Hướng dẫn** — tiêu đề + mô tả + thanh thời gian (tự bắt đầu sau ~30s; passive ~20s). Không bỏ qua bằng SPACE.
2. **Đếm ngược** — 5 → … → 1 (mọi bài).
3. **Nhiệm vụ** — kích thích lặp lại đến khi hết giờ.
4. **Phản hồi** — hiện sau mỗi câu trả lời (xem bảng trên); Quan sát video & Đọc truyện không có.


### Nội dung hướng dẫn từng bài (chữ hiển thị)


**Quan sát video** — *Quan sát video*
> Trên màn hình sẽ hiển thị hình ảnh chuyển động liên tục.  
>   
> Hãy thư giãn và quan sát cho đến khi hết thời gian.  
> Không cần phản hồi hay thao tác gì.

**Đọc truyện** — *Đọc truyện*
> Đọc thầm câu chuyện theo tốc độ của bạn.  
>   
> SPACE hoặc mũi tên phải: trang sau  
> Mũi tên trái: trang trước  
>   
> Bài tập sẽ tự kết thúc khi hết thời gian.

**Phép cộng** — *Phép cộng*
> Cộng hai số hiển thị trên màn hình.  
>   
> Nhập đáp án bằng các phím số.  
> BACKSPACE để xóa, ENTER để xác nhận.  
>   
> Tiếp tục giải cho đến khi hết thời gian.

**CPT-X** — *Bài tập chú ý (CPT-X)*
> Các chữ cái sẽ xuất hiện lần lượt, thời gian hiển thị mỗi chữ rất ngắn.  
>   
> Nếu là chữ  X  → nhấn  C  
> Nếu là chữ khác → nhấn  SPACE  
>   
> Hãy phản hồi nhanh và chính xác nhất có thể.
> 
> X  =>  nhấn C            chữ khác  =>  nhấn SPACE

**Phép nhân** — *Phép nhân*
> Nhân hai số hiển thị trên màn hình.  
>   
> Nhập đáp án bằng các phím số.  
> BACKSPACE để xóa, ENTER để xác nhận.  
>   
> Tiếp tục giải cho đến khi hết thời gian.

**Stroop** — *Bài tập Stroop*
> Phản hồi theo MÀU của từ, không quan tâm đến nghĩa của từ.  
>   
> hãy nhấn nhanh nhất có thể khi từ xuất hiện
> 
> Chú thích màu: XANH DƯƠNG / XANH LÁ ⇒ C · ĐỎ / VÀNG ⇒ M

## 5. Ghi chú hành vi (đã cập nhật)

- **Toàn màn hình** (`fullscr=True`) cho mọi bài.
- **SPACE không bỏ qua** hướng dẫn / trạng thái nền / nhiệm vụ — chỉ **ESC** mới dừng; màn hình **kết thúc** vẫn đóng bằng SPACE.
- **Trạng thái nền = 3 phút liên tục, 6 bước** (kiểm tra tín hiệu → mở mắt → chớp mắt → nhìn ngang → nhìn dọc → nhắm mắt); các bước nghỉ chỉ hiện dấu '+', các bước chủ động có hiệu lệnh/chấm dẫn. Hướng dẫn hiện **trước**.
- **Tín hiệu ghi liên tục** suốt phiên — không phân biệt khối nào 'được ghi'.
- Mọi bài đều có đếm ngược **5s** trước khi bắt đầu.
- **Phép cộng & Phép nhân**: KHÔNG giới hạn thời gian mỗi câu (`response_window = None`) — giải liên tục đến khi hết giờ.
- **Stroop**: chỉ báo **“Sai”** (không báo “Đúng”); quá giờ = “Phản hồi chậm” (xám).
- **CPT-X**: báo **“Đúng”/“Sai”** ~400ms sau mỗi phản hồi (giữ nhịp cố định SOA 1500ms).
- **Tiếng báo mở mắt**: Windows tone 1000Hz/500ms; macOS phát `Ping.aiff`; nền tảng khác im lặng (không lỗi).

## 6. Dữ liệu & chỉnh tham số

- Kết quả: `code/results/<MSSV>_<thời gian>/` gồm `task.csv` (mọi trial) + `metadata.json`.
- Chỉnh **thời lượng / khoảng cách / màu / cỡ chữ / tiếng bíp**: `code/experiment/settings.py`.
- Chỉnh **chữ hiển thị**: `code/experiment/content.py`.

## 7. Ghi chú truyện đọc (bản quyền)

- Truyện hiện dùng: **“TẤM GƯƠNG ẢO ẢNH”** — là **tệp cục bộ có bản quyền**, KHÔNG đưa vào repo công khai và **không trích trong tài liệu này**.
- Phân trang: `chars_per_page = 450` → ~158 trang (đọc trong 3:00), đã hạ từ 650 để trang không tràn dọc.
- Muốn đổi truyện: đặt `code/experiment/fairy_tale.txt` (dòng 1 = tiêu đề, cách dòng trống giữa các đoạn); nếu không có, dùng truyện mặc định trong `fairy_tale_psychopy.py`.


---
*Tạo tự động từ mã nguồn. Cập nhật chữ trong `content.py`, số liệu trong `settings.py`, rồi sinh lại.*
