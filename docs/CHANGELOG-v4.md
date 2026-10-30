# v4 — Setup không hoàn thành được vẽ đủ, mức mục tiêu đổi màu

File: `src/bandz_stdv_cisd.pine` (2513 dòng). Logic phát hiện (`detectLayer`) và lớp tín hiệu BUY/SELL v3 giữ nguyên.

---

## 1. Vấn đề của v3

Khi một setup chết (phá anchor = status 1, hoặc chạy hết −4 = status 2), code cũ gọi `deleteProjectionDrawings()` ngay
lập tức và chỉ để lại **một** đường chấm + một nhãn nhỏ. Hệ quả: setup thất bại chỉ còn là một vạch, không còn
thấy được nó đã được xây từ anchor nào, level nào, vùng nào — trong khi setup còn sống thì thấy đầy đủ.
Đó chính là kiểu "lọc lịch sử" mà bản v2 muốn xoá bỏ, chỉ là lần này nó xảy ra ở tầng **hình vẽ** thay vì tầng dữ liệu.

## 2. Thay đổi

### 2.1 Setup chết giữ nguyên 100% hình học

| Thành phần | Trước v4 | Sau v4 |
|---|---|---|
| Anchor 0 / 1 | bị xoá | giữ, màu `Retired structure` |
| Level −1 … −4 | bị xoá | giữ, màu `Retired objectives` ← **màu riêng** |
| Nhãn `-1 … -4` | bị xoá | giữ, cùng màu objective |
| Zone −1/−2/−3.5 | bị xoá | giữ, tô màu objective |
| Đường CISD | bị xoá | giữ, kéo đến đúng `endTime` (lúc chết) |
| BUY/SELL tag + SL/TP | bị xoá | bị xoá (đúng: setup chết thì không còn tín hiệu) |

Điểm khác duy nhất so với setup còn sống là **màu** (nhạt hơn, palette "đã nghỉ") và **không có live-extension box**
(phần đuôi −2/−2.5 kéo dài theo thời gian thực chỉ tồn tại khi setup còn sống).

### 2.2 Mức mục tiêu có màu riêng

```
Retired structure   rgb(120,130,145)  xám-xanh   ← anchor, CISD
Retired objectives  rgb(214,158,46)   hổ phách   ← -1, -1.5, -2, -2.5, -3.5, -4 + zone
```

Lý do chọn hổ phách: khác hẳn xanh/đỏ của tín hiệu, khác cả màu STDV mặc định, nên liếc qua là biết
"các mức này thuộc một setup đã chết", không nhầm với target đang theo.

### 2.3 Giới hạn ngân sách hình vẽ

Pine chỉ cho tối đa 500 line / 500 label / 500 box. Mỗi set đầy đủ tốn ~17 drawing, nên không thể vẽ đủ cho
cả 300 bản ghi. Cơ chế:

- Input mới **`Retired sets drawn in full`** (mặc định **12**): N setup chết **mới nhất** được vẽ đủ.
- Setup chết cũ hơn tự thu về **1 ghost mark** như v3 (nhãn `SL` / `-4`).
- `0` = chỉ ghost, giống hệt hành vi cũ.

Tính toán ngân sách ở mức mặc định: 12 set × 9 line = 108, + 60 ghost = 168 line (giới hạn 500) — còn dư nhiều.

### 2.4 Kỹ thuật

| Vị trí | Thay đổi |
|---|---|
| type `Projection` | + `bool ghosted` (42 field) |
| `newProjection` | truyền `false` cho `ghosted` |
| Khối retire (`deadTime`) | **không còn** gọi `deleteProjectionDrawings` và `pushGhost` |
| Trước vòng render | tính `deadFullCutoff` = `deadTime` của set chết thứ N (sort giảm dần) |
| `renderProjection` | palette `deadSetup` cho structure/anchor/CISD/zone/objective |
| `color ratioDraw` | `baseStructure` → `objectiveDraw` (2 chỗ) |
| Vòng render, nhánh `else` | vẽ đủ nếu trong cửa sổ, ngược lại xoá + ghost (1 lần) |
| `showInvalidatedSetups` | đổi nhãn thành "Show retired sets in full" |

### 2.5 Tính nhất quán realtime / reload

Setup chết vẫn được chốt **một lần** trên nến đã đóng (luật C1 giữ nguyên), và `deadTime` được ghi một lần.
Việc vẽ lại là hàm thuần của `(status, deadTime, anchor0, anchor1)` nên reload cho ra đúng cùng bức tranh.

---

## 3. Kiểm chứng

1. Compile không lỗi.
2. Chart 5m, để chạy đủ lâu cho vài setup chết: set mới nhất chết vẫn còn nguyên các level, khác màu.
3. Các level mục tiêu của set chết màu hổ phách; set còn sống vẫn màu gốc.
4. Đổi `Retired sets drawn in full` = 0 → tất cả thu về ghost.
5. Đổi = 30 → nhiều set cũ hiện đủ; kiểm tra không có cảnh báo vượt giới hạn drawing.
6. Reload trang → hình không đổi.
7. Tắt `Show retired sets in full` → sạch, chỉ còn setup sống.

---

## 4. Chưa làm (có chủ ý)

- Không thêm nhãn "thời điểm chết" cho set vẽ đủ (chỉ set bị thu về ghost mới có). Muốn có thì cần thêm 1 field + 1 label/set.
- Không vẽ lại live-extension box cho set chết (nó là phần đuôi động, không phải một phần cấu trúc).
- Lớp đo lường win-rate vẫn chưa làm.
