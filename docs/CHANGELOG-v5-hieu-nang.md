# v5 — Hiệu năng: sửa lỗi "too slow to run on this chart"

File: `src/bandz_stdv_cisd.pine` (2546 dòng). Logic phát hiện **không đổi một dòng nào**.

---

## 1. Lỗi nghĩa là gì

TradingView chạy Pine trong giới hạn ~500 ms cho mỗi nến và một tổng thời gian cho cả chart.
"Too slow to run on this chart" = script vượt giới hạn đó, nên công cụ bị **tắt hẳn** (không phải chỉ
chậm). Nó thường xuất hiện **sau khi chart đã chạy một lúc**, khi dữ liệu tích tụ — dấu hiệu của
thuật toán tăng theo bình phương, chứ không phải của việc "vẽ nhiều hình".

## 2. Chuỗi nhân quả (do chính các bản trước tạo ra)

| Bản | Thay đổi | Hệ quả phụ |
|---|---|---|
| v2 | Setup chết **không xoá** nữa, giữ làm bản ghi | mảng `projections` phình từ ~20–40 lên tới **300** |
| v2 | `GLOBAL_PROJECTION_LIMIT` 140 → 300 | trần cao hơn nữa |
| (có sẵn) | Vòng render có **quét lồng nhau** `for i` × `for j` để tính độ mờ | O(N²): 300 × 300 = **90.000 vòng mỗi nến** |

Trên M5 cả 5 nhóm (5m, 15m, 1H, 4H, D) cùng chạy và cùng đổ setup vào mảng, nên N chạm trần nhanh
nhất — đúng chart bạn báo lỗi.

## 3. Đã sửa

### 3.1 Bỏ quét lồng nhau (khoản lớn nhất)

Độ mờ của một setup chỉ phụ thuộc **các setup đang được vẽ**, không phải toàn bộ kho.

```pine
array<int> selectedIndices = array.new_int()
for i = 0 to projections.size() - 1
    if selectedProjection.get(i)
        selectedIndices.push(i)
...
for j = 0 to selectedIndices.size() - 1   // trước: projections.size() - 1
```

Kết quả **giống hệt** (vì chỉ đếm các set `selectedProjection == true`), nhưng 90.000 vòng → ~60.

### 3.2 Hoist phần tính theo từng setup ra khỏi vòng lặp theo nhóm

`projectionRetentionMs` và `projectionNearPrice` (mỗi hàm tính vài mức giá) trước đây được tính
**lại cho từng nhóm**: 7 nhóm × 300 setup = 2.100 lần/nến. Giờ tính một lần, lưu 2 mảng cờ:

```pine
array<bool> setLive = array.new_bool()
array<bool> setRelevant = array.new_bool()
```

300 lần/nến thay vì 2.100.

### 3.3 Setup chết chỉ tô lại **một lần**

Setup chết không còn di chuyển: anchor cố định, `endTime` cố định, độ mờ cố định. Bản v4 vẫn gọi
`renderProjection` cho nó **mỗi nến** (≈30 lệnh `line.set_*` / `label.set_*` / `box.set_*`).
Thêm cờ `retiredPainted`:

```pine
if not retired.retiredPainted
    retired := renderProjection(retired, true, layerHistoricalOpacity(retired.layer), 0, false, false)
    retired.retiredPainted := true
```

12 set chết × 30 lệnh × mỗi nến → 0.

### 3.4 Trần lưu trữ thành input

Nhóm mới **Performance** → `Max stored sets`, mặc định **120** (trước là hằng số 300).

Vì mọi vòng lặp đều đi qua danh sách này, đây là núm chỉnh trực tiếp: 300 → 120 giảm 60% khối lượng
ở **mọi** vòng.

## 4. Chi phí mỗi nến (ước tính theo số vòng lặp)

| Hạng mục | Trước (N=300) | Sau (N=120) |
|---|---|---|
| Quét lồng nhau tính độ mờ | 90.000 | ~60 |
| Retention / near-price theo nhóm | 2.100 | 120 |
| Tô lại set chết | ~360 lệnh vẽ | 0 |
| Quét candidate theo nhóm | 2.100 | 600 |
| Vòng lifecycle | 300 | 120 |

Đây là đếm vòng lặp, **không phải số đo thực** — sandbox không có TradingView.

## 5. Nếu vẫn báo lỗi — thang chẩn đoán

Làm lần lượt, dừng ở bước nào hết lỗi:

1. **Performance → Max stored sets = 60.** Nếu hết → chi phí ở tầng hiển thị/kho.
2. **Simple display → tắt "Show higher-timeframe sets".** Nếu hết → chi phí nằm ở các lệnh
   `request.security` của nhóm phụ (M5 đang chạy 5 nhóm).
3. Tắt bớt preset: 4H, Daily (Settings → nhóm tương ứng → Enable).
4. Nếu vẫn lỗi khi chỉ còn 1 nhóm: vấn đề nằm trong `detectLayer`, phải hạ độ sâu quét
   (`layerXScanDepth`, hiện 500–1500) — nói tôi, tôi làm thành input.

## 6. Điều tôi KHÔNG làm (và vì sao)

Không sửa `detectLayer`, không đổi `calc_bars_count`, không đổi ngưỡng phát hiện. Ba thứ đó vừa
quyết định tín hiệu vừa không kiểm chứng được trong sandbox này (không có compiler Pine). Sửa mù
phần lõi là cách nhanh nhất để tạo ra một chỉ báo sai một cách im lặng.
