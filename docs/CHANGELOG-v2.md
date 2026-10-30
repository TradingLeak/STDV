# v2 — Audit pass 1: giữ setup đã chết + realtime = reload

File: `src/bandz_stdv_cisd.pine` (2306 dòng, thay đổi ~60 dòng so với bản gốc)
Phạm vi: **chỉ 2 thay đổi**. Toàn bộ logic phát hiện (`detectLayer`: reference, sweep, delivery leg, CISD, swing, state machine, competition, scoring) **không bị sửa một dòng nào**.

---

## 1. Setup đã chết được giữ lại (ghost)

### Trước

```pine
Projection checkedProjection = projections.get(lifecycleIndex)
if checkedProjection.status != 0
    Projection removedProjection = projections.remove(lifecycleIndex)
    removedProjection := deleteProjectionDrawings(removedProjection)
```

Setup invalid hoặc chạm −4 bị **xoá khỏi mảng**. Hệ quả: chart tự lọc chỉ còn setup thắng → không thể đánh giá, không thể audit, không thể thống kê.

### Sau

```pine
Projection checkedProjection = projections.get(lifecycleIndex)
if checkedProjection.status != 0 and na(checkedProjection.deadTime)
    checkedProjection := deleteProjectionDrawings(checkedProjection)   // chỉ gỡ hình "sống"
    checkedProjection.deadTime := nz(checkedProjection.endTime, time)
    if showInvalidatedSetups
        pushGhost(checkedProjection)                                   // để lại dấu vết
    projections.set(lifecycleIndex, checkedProjection)                 // GIỮ LẠI
```

Mỗi setup chết để lại **một** dấu:

| Loại | Hình | Màu | Nhãn |
|---|---|---|---|
| Bị phá anchor (`status 1`) | line chấm chấm tại giá `anchor1`, từ nến manipulation đến nến chết | đỏ mờ | `x` |
| Chạm −4 (`status 2`) | line chấm chấm tại mức −4 | xám mờ | `-4` |

Ghost nằm trong ring buffer riêng (`GHOST_LIMIT = 60`), **không** tiêu vào trần `max_lines_count` / `max_labels_count` của projection.

### Các thay đổi kèm theo (bắt buộc, nếu không sẽ sai logic)

| Vị trí | Thay đổi | Lý do |
|---|---|---|
| type `Projection` | thêm `int deadTime` (+ 1 tham số `na` trong `Projection.new`) | biết setup đã retire hay chưa, tránh vẽ ghost lặp lại mỗi bar |
| `findSameWinner` | chỉ nhận `status == 0` | xác chết không được chiếm slot cửa sổ |
| `findNearDuplicate` | `sameReference` / `sameSweep` / `nearAnchors` đều yêu cầu `status == 0` | xác chết không được coi là bản trùng và bị ghi đè |
| `upsertWinner` | đếm `storedForLayer` và trim chỉ trên `status == 0` | giới hạn 20/layer là giới hạn **hiển thị**, không phải giới hạn bản ghi |
| `GLOBAL_PROJECTION_LIMIT` | 140 → 300 | có thêm bản ghi trong bộ nhớ |
| `ingestSnapshot` | vòng lifecycle bỏ qua `status != 0` | đóng băng bản ghi, giảm việc vô ích |
| vòng render | bỏ qua `status != 0` | hình đã gỡ lúc retire, không gọi lại mỗi bar |
| Input mới | `Show invalidated / completed sets` (mặc định **on**) | có thể tắt ghost, nhưng bản ghi vẫn còn |

---

## 2. C1 — realtime khớp reload

### Trước

```pine
if projection.status == 0 and chartCanInvalidateLive and afterConfirmation
    ...
    bool anchorWickThrough = ...
    if minusFourWickThrough
        projection.status := 2
        projection.endTime := time
    else if anchorWickThrough
        projection.status := 1
        projection.endTime := time
    projections.set(lifecycleIndex, projection)
```

Quyết định "giết" projection được đưa ra **trên từng tick của nến đang chạy**. Trạng thái mảng `projections` tồn tại xuyên tick, nên quyết định đó **không thể đảo ngược**: một cú wick ở giữa nến giết setup ngay lập tức, và nến đóng lại không khôi phục nó.

### Sau

```pine
bool liveBarUnconfirmed = barstate.islast and not barstate.isconfirmed
...
if not liveBarUnconfirmed
    ... chỉ chốt status 1 / status 2 tại đây ...
```

- Nến lịch sử: `barstate.isconfirmed = true` → chốt như cũ, **kết quả quá khứ không đổi**.
- Nến realtime: **không** chốt giữa nến; chốt ở lần tính cuối cùng (bar close), đúng bằng thứ mà reload sẽ replay.
- Chạm mục tiêu (−2, −3.5) **vẫn** được ghi nhận trong nến, vì nó chỉ là thông tin hiển thị (đóng băng rail), không phá dữ liệu. High/low của nến chỉ mở rộng, nên giá trị ghi nhận live và giá trị replay luôn trùng nhau.

Kết quả: chuỗi tick trong một nến không còn ảnh hưởng tới tập projection sống sót ⇒ **F5 không làm danh sách thay đổi**.

### Điều người dùng sẽ thấy khác

| Trước | Sau |
|---|---|
| Setup biến mất ngay khi có wick phá anchor | Setup sống tới khi nến đóng, rồi mới retire (trễ tối đa 1 nến) |
| Chart chỉ còn setup thắng | Setup thua để lại dấu `x` / `-4` |
| Reload có thể khác trạng thái đang xem | Reload khớp |

---

## 3. Kiểm chứng (làm trên TradingView)

1. **Compile**: dán file, xem Pine console — không được có lỗi, chỉ có thể có warning "unused variable" (vô hại).
2. **Reload parity**: mở chart, ghi lại danh sách set đang thấy → F5 → so sánh. Phải trùng.
3. **Ghost invalid**: chờ một set bị phá `anchor1` → xuất hiện line đỏ chấm chấm + nhãn `x` tại mức anchor.
4. **Ghost −4**: chờ một set chạm −4 → line xám + nhãn `-4`; set đó **không** được xuất hiện lại dưới dạng live.
5. **Không hồi sinh**: sau khi ghost xuất hiện, các bar sau không được vẽ lại levels của set đó.
6. **Ngân sách hình**: bật `Show invalidated` và để chạy lâu → ghosts tối đa 60 cặp line/label, không làm mất line của set đang sống.
7. **Tắt ghost**: bỏ tick `Show invalidated / completed sets` → chỉ mất phần vẽ, không ảnh hưởng gì khác.

---

## 4. Giới hạn của lần sửa này (nói rõ để không hiểu nhầm)

- **Chưa có thống kê.** Setup chết giờ được *giữ trong bộ nhớ* nhưng chưa được *đếm*. Đó là Sprint 1 phần còn lại (bảng win-rate, MFE/MAE, Pine Logs).
- **Chưa sửa** competition filter bị vô hiệu (C2), `Body close` sai nghĩa (H4), trần delivery leg 12 nến (H3), cooldown reference (H1).
- **Không thể compile Pine trong môi trường này.** Đã kiểm tra tự động: cân bằng ngoặc, cân bằng quote, 0 lỗi block-indent, và khớp số field/tham số của cả 3 UDT (`Projection` 35/35, `LayerSnapshot` 43/43, `Candidate` 19/19). Vẫn cần bước compile thật trên TradingView.
- **Chi phí**: mảng projection lớn hơn (140 → 300 phần tử). Trên TF thấp với `calc_bars_count` 1500, thời gian load có thể tăng nhẹ; nếu thấy chậm, giảm `GLOBAL_PROJECTION_LIMIT` xuống 200.

---

## 5. Bước tiếp theo

Sprint 1 phần còn lại — biến các bản ghi này thành số:

- `SetupRecord` + đếm `confirmed / hit−2 / hit−3.5 / invalid / exhausted`;
- MFE/MAE theo R với **entry = giá CISD, stop = anchor1**;
- bảng thống kê + `log.info` để xuất CSV;
- `alert()` khi revision tăng.

Sau đó mới tới C2/H4/H3/H1.
