# v3 — BUY / SELL confirmation với SL & TP + ghost đổi màu

File: `src/bandz_stdv_cisd.pine` (2465 dòng). Phần phát hiện (`detectLayer`) vẫn **không bị sửa**.

---

## 1. Tín hiệu BUY / SELL

### Thời điểm bắn
Setup được coi là "confirmed" đúng lúc chỉ báo tự xác nhận nó: **close phá qua swing đối ứng sau CISD**
(`confirmationTime`). Không bắn sớm hơn ở CISD, vì luật của chỉ báo cần cả hai điều kiện.

### Giá trị hiển thị
| Thành phần | Lấy từ | Ghi chú |
|---|---|---|
| Entry | `close` của nến xác nhận | giá thị trường thật tại thời điểm tín hiệu, không phải giá CISD (tránh entry đẹp ảo) |
| SL | `anchor1` — đỉnh/đáy manipulation | đúng điểm vô hiệu hoá của phương pháp |
| TP | mức **−2** | mục tiêu đầu tiên mà chỉ báo vẫn theo dõi |
| TP2 (tuỳ chọn) | mức **−4** | bật bằng `Show second target (-4)` |
| R:R | `|TP − Entry| / |Entry − SL|` | có trong alert, không in lên label để đỡ rối |

### Hiển thị
- **1 tag duy nhất** cho mỗi hướng: `BUY 5m` / `SELL 5m` + `E / SL / TP` (nhiều dòng, font mono).
- Chỉ dành cho **set mới nhất còn sống của nhóm primary** (không vẽ cho MTF, không vẽ cho set cũ).
- Khi có set mới hơn cùng hướng → tag + line của set cũ **tự gỡ**, nên trên chart tối đa 1 long + 1 short.
- **Line SL** (đỏ, nét đứt) và **line TP** (xanh, nét đứt) kéo dài sang phải (`extend.right`), tự xoá khi set chết.
- **Nhãn `TP`** nhỏ xuất hiện đúng nến giá chạm −2 (ring buffer 60 nhãn, không rò rỉ ngân sách hình).

### Input mới — nhóm "Buy / Sell signals"
```
BUY / SELL confirmation        on
Draw SL / TP lines             on
Show second target (-4)        off
Mark TP hits                   on
BUY  / SELL  (màu)             teal / red
SL   / TP    (màu)             red  / teal
```

### Alert
```pine
alert("BUY 5m | Entry 1.2345 | SL 1.2301 | TP 1.2450 | RR 2.43", alert.freq_once_per_bar_close)
```
Tạo alert trên TradingView chọn **"Any alert() function call"**.
Bắn khi revision của nhóm primary tăng (mỗi setup confirmed = 1 alert), `freq_once_per_bar_close`.

---

## 2. Ghost (setup đã chết) đổi màu

| Trước (v2) | Sau (v3) |
|---|---|
| Đỏ mờ `color.new(color.red, 40)` cho invalid | **Xám-xanh nhạt** `rgb(120,130,145)` @ 68% trong suốt |
| Xám cho −4 | cùng màu, @ 55% |
| Nhãn `x` | Nhãn **`SL`** (bị phá anchor) / **`-4`** (đạt mục tiêu sâu) |

Có input `Invalidated / completed sets` để đổi màu tuỳ ý. Mục đích: ghost vẫn nhìn thấy (không che lịch sử thất bại) nhưng **không tranh mắt** với level đang sống.

---

## 3. Thay đổi kỹ thuật (để bạn đối chiếu)

| Vị trí | Thay đổi |
|---|---|
| type `Projection` | + `float entry`, `label signalLabel`, `line slLine`, `line tpLine`, `line tpLine2`, `bool tpMarked` (41 field) |
| `newProjection` / `upsertWinner` | + tham số `entryPrice` |
| `ingestSnapshot` | truyền `snapshot.nativeClose` làm entry — chính là close của nến xác nhận |
| `deleteProjectionDrawings` | dọn thêm 4 drawing của signal |
| `deleteSignalDrawings` (mới) | gỡ tag/line khi set không còn là mới nhất |
| `pushTpHit` (mới) | ring 60 nhãn `TP` |
| `renderProjection` | + tham số `drawSignal`, khối vẽ signal ở cuối |
| Vòng render | `drawSignal = showSignals and liveExtensionOwner` |
| Cuối file | khối `CONFIRMATION ALERTS` |

---

## 4. Kiểm chứng nhanh

1. Compile: chỉ có warning "unused variable" (nếu có) — không lỗi.
2. Chart 5m: chờ 1 setup bullish confirm → thấy tag `BUY 5m` + đường SL đỏ + TP xanh.
3. Giá chạm −2 → nhãn `TP` nhỏ xuất hiện tại nến đó.
4. Giá phá SL → tag + line biến mất, ghost xám có nhãn `SL`.
5. Có setup mới cùng hướng → tag cũ tự gỡ, chỉ còn tag mới.
6. Alert: tạo alert "Any alert() function call" → kiểm tra message có Entry/SL/TP/RR.

---

## 5. Lưu ý

- Entry là **close nến xác nhận**, nên nếu giá đã chạy xa khỏi CISD thì R:R hiển thị đúng thực tế (không phải R:R lý thuyết).
- Chỉ primary group mới có signal; MTF chỉ để đọc bối cảnh.
- Chưa có thống kê win-rate (Sprint 1 còn lại): hiện ghost đã giữ lịch sử, chỉ thiếu phần đếm.
