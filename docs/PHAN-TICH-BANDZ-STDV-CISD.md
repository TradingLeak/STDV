# Mổ xẻ `Bandz STDV & CISD` (Pine v6)

Tài liệu review kỹ thuật: kiến trúc, logic phương pháp, lỗi tiềm ẩn, rủi ro repaint/backtest, hiệu năng và hướng sửa.

---

## 0. Kết luận nhanh

| Hạng mục | Điểm | Nhận xét 1 dòng |
|---|---|---|
| Ý tưởng phương pháp | 8/10 | Chuỗi `quét thanh khoản → CISD → phá swing đối ứng → STDV` là chuỗi nhân quả rõ ràng, mô hình hoá được bằng state machine |
| Chất lượng triển khai | 7/10 | Có guard `na`, có cap mảng, dedupe theo revision, dọn drawing; code sạch hơn mặt bằng chung |
| **Khả năng kiểm chứng** | **3/10** | **Xoá sạch setup khi invalid/-4 → không có lịch sử, không alert, không plot → không thể đo win-rate** |
| Hiệu năng | 5/10 | 7 layer × `calc_bars_count` 500–1500 × O(n²) reference → nặng, lịch sử bị giới hạn |
| Bảo trì | 4/10 | ~1.200 dòng cho ~600 dòng logic thực; bull/bear nhân đôi, 7 layer nhân 7 khối gần giống nhau |
| Sẵn sàng automation | 2/10 | Không `plot`, không `alert()`, không `alertcondition` |

**Một câu tóm tắt:** đây là một *pattern engine* khá nghiêm túc (không phải indicator vẽ lung tung), nhưng nó đang tự che mất kết quả sai của chính nó — vì mọi setup thất bại đều bị xoá khỏi chart, nên nhìn chart luôn thấy "chỉ báo rất chuẩn".

---

## 1. Bản đồ kiến trúc

```
                    ┌──────────────────────────────────────────────┐
                    │ 7 "layer" = 7 preset (1m, 5m, 15m, 1H, 4H, D)│
                    │ mỗi layer: liquidityTf / confirmTf / compTf  │
                    └───────────────────┬──────────────────────────┘
                                        │ (khối if lặp lại 7 lần)
              ┌─────────────────────────┴─────────────────────────┐
              │ request.security_lower_tf(confirmTf)  ← confirm < chart
              │ request.security(confirmTf, lookahead_on) ← confirm ≥ chart
              └─────────────────────────┬─────────────────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │ detectLayer(...)  ← "bộ não", stateful │
                    │  • tự dựng nến liquidity TF (H/L)      │
                    │  • chọn reference (normal/swing/extreme)│
                    │  • phát hiện sweep tươi                 │
                    │  • quét delivery leg → CISD             │
                    │  • tìm pivot đối ứng                    │
                    │  • state machine Candidate 0 → 1 → xong │
                    │  • chấm điểm + competition window        │
                    └───────────────────┬───────────────────┘
                                        │ LayerSnapshot (UDT, bất biến)
                    ┌───────────────────▼───────────────────┐
                    │ ingestSnapshot / ingestSnapshotArray   │
                    │  • dedupe theo revision                │
                    │  • upsertWinner + near-duplicate       │
                    │  • lifecycle: -2 touch, -3.5 touch,    │
                    │    -4 exhaustion, anchor invalidation  │
                    └───────────────────┬───────────────────┘
                                        │ Projection[]  (unshift, cap 140)
                    ┌───────────────────▼───────────────────┐
                    │ chọn set hiển thị (primary + MTF)       │
                    │ renderProjection (line/label/box)       │
                    │ live rails -2 → -3.5 cho bull/bear mới  │
                    └───────────────────────────────────────┘
```

Điểm kiến trúc **đáng khen**: không dùng `request.security()` lồng nhau. Thay vào đó `detectLayer` tự gom nến liquidity TF từ nến native → tránh được toàn bộ lớp lỗi "nested security không ổn định / không tính được lịch sử" của Pine. Đây là lựa chọn đúng.

Điểm kiến trúc **đáng lo**: toàn bộ tri thức nằm trong **state của function chạy bên trong security context**. Việc này đúng nhưng khiến mọi thay đổi nhỏ ở `detectLayer` đều có thể làm lệch lịch sử mà không có test nào bắt được.

---

## 2. Giải phẫu logic cốt lõi

### 2.1. Tự dựng nến liquidity TF

```pine
int processedLiquidityTime = time(liquidityTf)[1]
if na(buildingLiquidityTime)            → mở bucket mới
else if processedLiquidityTime != buildingLiquidityTime → đóng bucket, push H/L
else                                     → mở rộng H/L
```

- Bucket chỉ lưu **high/low**, không lưu open/close.
- Hệ quả trực tiếp: input `"Liquidity sweep uses: Body close"` **không thể** so close của nến liquidity TF, nên code dùng `processedClose` (close của nến native) → nhãn input nói một đằng, logic làm một nẻo. Xem lỗi **H4**.
- `capacity 128` bucket: với liquidity 15m và confirm 1m, 128 nến 15m = 32 giờ → đủ. Với liquidity D trên confirm 4H, 128 nến D = 6 tháng → nhưng `calc_bars_count=500` nến 4H chỉ ~83 ngày → reference D gần như luôn "mới". Không sai, nhưng độ sâu lịch sử không đồng đều giữa các layer.

### 2.2. Chọn reference — `REF_NORMAL` thực chất là gì?

```pine
highUnresolved := highUnresolved and completedLiquidityHighs.get(newerIndex) < candidateHigh
```

Điều kiện = "không có nến nào **mới hơn** có high cao hơn". Đây chính là **suffix-maximum** (đỉnh không bị vượt bởi bất kỳ nến nào sau nó), không phải "swing high".

Hệ quả thực tế:
- Nến liquidity **cuối cùng luôn** là reference (không có nến mới hơn) → luôn có một đỉnh/đáy "tươi" để quét. Tốt cho việc bắt sweep.
- Nhưng khi giá đi ngang tạo chuỗi đỉnh giảm dần `12 → 10 → 11`, cả `12` và `11` đều "unresolved" → nhiều reference hơn trực giác. Không sai, chỉ là **không phải khái niệm liquidity cổ điển** (equal highs / old high / session high).
- Không có phân biệt "old high" vs "high vừa tạo 3 nến trước" → một sweep vào đỉnh vừa tạo 2 nến trước được tính ngang với sweep đỉnh 6 tháng. Về mặt ICT, hai thứ này không tương đương.

`REF_SWING` và `REF_EXTREME` có code nhưng **không được dùng** (mọi preset đều `REF_NORMAL`) → ~60 dòng dead weight.

### 2.3. Phát hiện sweep

```pine
float bullMeasure      = htfViolationMode == "Body close" ? processedClose : processedLow
float priorBullMeasure = htfViolationMode == "Body close" ? close[2] : low[2]
bool bullViolated      = bullMeasure < referenceLow - sweepTolerance
bool freshBullSweep    = referenceLowTime < processedTime and bullViolated and priorBullMeasure >= bullThreshold
```

- Chỉ tạo candidate tại **bar giao cắt đầu tiên** (`prior >= ngưỡng`, `hiện tại < ngưỡng`). Hợp lý, nhưng nghĩa là **sweep xảy ra trước khi indicator load / trước `calc_bars_count` sẽ không tồn tại** — chart không "nhớ" gì trước cửa sổ scan.
- `sweepToleranceTicks` = 0 / 1 / 2 tick theo `Setup sensitivity`. Đây là thứ duy nhất "sensitivity" tác động lên *định nghĩa* sweep; phần còn lại của sensitivity là nới/co cửa sổ thời gian (xem 2.6).
- `priorBullMeasure` dùng `[2]` vì bar đang xử lý là `[1]` → nhất quán. Nhưng xem **M1**: `[1]` tạo latency 1 native bar.

### 2.4. Delivery leg và CISD — chỗ dễ sai nhất

```pine
// bullish setup ⇒ cần leg GIẢM (bearish delivery), CISD = open CAO NHẤT của leg
[cisd, oldest, memberCount, genuineCount, firstDelivery, defining, hasStructure] =
     bearishDeliveryRun(1, effectiveDeliveryGap)
```

Cách làm:
1. Từ bar `1`, quét tiến tối đa `gap` bar để tìm nến giảm đầu tiên.
2. Từ đó quét **lùi** (offset tăng) tối đa `DELIVERY_SCAN_LIMIT = 12` nến, dừng khi gặp nến không thuộc leg.
3. CISD = `max(open)` của các nến giảm **thật** (nến inside/doji chỉ giữ liên tục, không tính vào ngưỡng).
4. Yêu cầu tối thiểu `MIN_DELIVERY_CANDLES = 2` nến giảm thật.

Đây là định nghĩa CISD **chuẩn**: close vượt qua open cao nhất của chân đẩy cuối. Điểm cộng: tách "nến inside giữ nhịp" khỏi "nến thật định nghĩa ngưỡng" là chi tiết rất đúng.

Vấn đề:
- **Trần 12 nến cắt chân dài.** Với 1m, một cú xả 15–20 phút sẽ bị cắt còn 12 nến cuối → CISD thấp hơn CISD thật → **xác nhận sớm**, và range `|a0−a1|` cũng sai theo. Xem **H3**.
- `deliverySearchGap = 1`: leg được phép cách bar hiện tại 1 nến. Nghĩa là sau khi giá đã quét đáy và có 1 nến xanh nhỏ, leg vẫn được tính là "leg của setup" dù nến xanh đó không thuộc leg. Chấp nhận được, nhưng làm mờ khái niệm "displacement liền mạch".
- `isInsideCandleAt(offset)` định nghĩa "nến cũ nằm trong nến mới" (`high[offset] <= high[offset+1]`) — ngược với định nghĩa inside bar thông thường (nến mới nằm trong nến cũ). Với mục đích "nến trung tính giữ liên tục" thì không sai kết quả, nhưng tên hàm dễ gây hiểu lầm khi bảo trì.
- `hasStructureClose` (nếu bật) kiểm tra `close[offset] < low[offset+1]` — tức close của nến cũ thấp hơn low của nến **cũ hơn nữa**? Không: `offset+1` là nến **cũ hơn** `offset`, nên đây đúng là "close thấp hơn low nến trước đó" → **đúng**. (Đã kiểm tra kỹ chiều index; không phải bug.)

### 2.5. Swing đối ứng

```pine
closestPriorSwingHigh(finalDeliveryOffset, effectiveSwingSearchBars)  // pivot strength 2, tìm 30 nến
```

- Tìm pivot **gần nhất phía sau** nến delivery cũ nhất → đúng ý "điểm 0" của STDV (đỉnh khởi phát chân đẩy).
- Nếu không tìm thấy trong 30 nến → setup bị loại (`useNearestSwingFallback = false`). Có những cấu trúc hợp lệ nhưng swing gần nhất nằm xa hơn 30 nến → **bị loại âm thầm**.
- Điều kiện `bullSwingHigh > processedLow` là gần như luôn đúng (swing high luôn > low hiện tại) → guard này không lọc được gì.

### 2.6. State machine của `Candidate`

```pine
if expired or cisdExpired or swingBreakExpired → remove
else if afterExtreme and cisd & swing not na:
    stage 0 + close > cisd            → stage 1, ghi cisdConfirmBar
    stage 1 + close > swing           → CONFIRMED: score, competition, revision++
```

Cửa sổ thời gian (đã nhân hệ số sensitivity 0.65 / 1.0 / 1.5):

| Biến | Ý nghĩa | 1m / 5m | Strict |
|---|---|---|---|
| `candidateLifetime` | sống tối đa từ **lần sweep đầu** | 24 | ~16 |
| `cisdLifetime` | phải có CISD trong X bar từ **lần sweep đầu** | 8 | ~5 |
| `swingBreakBars` | phải phá swing trong X bar từ **bar CISD confirm** | 8 | ~5 |

Điểm **không nhất quán**: khi giá làm đáy sâu hơn (`deepenCandidate`), code **reset** `cisd`, `cisdConfirmBar`, `stage := 0` — nhưng **không** reset `startBar` và `firstSweepTime`. Comment nói đây là chủ ý ("deeper extreme does not restart startBar timing"), nhưng hệ quả là:

> Một cú quét đáy sâu + CISD đúng, đến bar thứ 7 lại quét sâu hơn → CISD bị huỷ, đồng hồ `cisdLifetime` **vẫn đang cạn từ lần quét đầu** → setup chết oan ở bar thứ 9 dù cấu trúc vừa mới hình thành lại.

Xem **M3**.

Ngoài ra `stage 1` khi `orientationValid == false` (`projectionRange <= 0`) không bị xoá, chỉ chờ hết lifetime → treo vô ích.

### 2.7. Competition & scoring — **bộ lọc đang bị tắt**

```pine
bool winsCompetition = not competitionFilterEnabled or protectCompetitionExtremes or winnerIndex == -1 or
     (windowStillOpen and (...))
```

`protectCompetitionExtremes` được hard-code `true` (không có input). Vì là `or`, **`winsCompetition` luôn luôn `true`**. Nghĩa là:

- Không một setup nào bị loại vì thua competition.
- `bullWinnerWindows / bullWinnerScores / bullWinnerCisds` vẫn được cập nhật nhưng chỉ mang tính trang trí.
- "Competition 90m / 4H / D" trên thực tế chỉ còn tác dụng **chống trùng** ở `upsertWinner` (`findSameWinner`, `findNearDuplicate`), không còn là "chọn setup tốt nhất trong cửa sổ".

Đây là **lỗi thiết kế nặng nhất về mặt phương pháp**: tên preset và tooltip khiến người dùng tin rằng có lọc theo cửa sổ cạnh tranh, nhưng logic đã vô hiệu hoá nó. Xem **C2**.

Công thức điểm (khi được dùng):

```
score = importance×100 + deliveryQuality×15 + sweepDepth×12 + cisdDisplacement×10
      + swingDisplacement×8 + (projectionRange/ATR)×5
```

`importance` = 4 (swing ref) / 3 (extreme) / 2 (normal) → **400 / 300 / 200 điểm**, tức là thành phần "loại reference" áp đảo hoàn toàn các thành phần chất lượng giá. Vì mọi preset dùng `REF_NORMAL`, importance luôn = 2 → score thực chất chỉ còn 5 thành phần sau, thang ~0–50 điểm. `deliveryQuality` bị chặn ở 2.0 max (15 điểm) → biên độ rất hẹp so với 200 điểm cố định.

Và `projectionCompositeRank` cộng thêm `+250` nếu `status == 0` → tiêu chí "Strongest composite score" thực chất là "còn hiệu lực trước, điểm sau". Không sai, nhưng tên gọi gây hiểu lầm.

### 2.8. STDV projection

```pine
projectionPrice(a0, a1, r) = a0 + r × (a1 − a0)
```

Với bullish: `a0` = swing high (điểm 0), `a1` = đáy manipulation (điểm 1).

| r | Giá | Ý nghĩa |
|---|---|---|
| 0 | swing high | anchor, không có số |
| 1 | manipulation low | anchor, không có số |
| −1 | cao hơn swing 1 range | mục tiêu gần |
| −2 | cao hơn swing 2 range | **mốc kích hoạt vùng mục tiêu** |
| −2.5 | 2.5 range | đóng vùng mục tiêu 1 |
| −3.5 | 3.5 range | mở vùng mục tiêu sâu |
| −4 | 4 range | **exhaustion → xoá toàn bộ set** |

Lưu ý cách đọc quan trọng: **các mức âm được đo từ swing (0), không phải từ đáy manipulation (1)**. Khoảng cách từ đáy manipulation tới `−2` là **3 range**, không phải 2. Rất nhiều người đọc sai chỗ này.

Vòng đời hiển thị (`renderProjection`):
1. Vẽ 0/1 là line anchor (không có số), các mức âm có số.
2. Box tĩnh cho `-1..-1.5`, `-2..-2.5`, `-3.5..-4` (nếu bật).
3. **Live rail** chỉ cho set mới nhất bull + bear của layer primary:
   - `-2..-2.5` kéo dài tới `time_close` cho đến khi giá **chạm −2**;
   - chạm −2 → rail đóng băng tại `firstObjectiveHitTime`, đồng thời mở `-3.5..-4` kéo dài;
   - chạm −4 → xoá sạch CISD, anchor, levels, boxes.
4. Mọi set không được chọn → `deleteProjectionDrawings` mỗi bar (idempotent, nhưng gọi 140 lần/bar).

Vấn đề mỹ thuật nhưng ảnh hưởng nhận thức: `markerStart = anchor1Time` — tức **vẽ lùi về đúng nến manipulation**, trong khi setup chỉ được biết tại `confirmationTime` (sau đó vài nến). Trên chart, các con số và box xuất hiện ở vùng giá *trước khi* tín hiệu tồn tại → tạo ảo giác "biết trước". Nếu mục tiêu là minh bạch, nên bắt đầu marker tại `confirmationTime` hoặc tô mờ vùng "chưa khả dụng".

### 2.9. Lifecycle và xoá

```pine
if checkedProjection.status != 0
    Projection removedProjection = projections.remove(lifecycleIndex)
    removedProjection := deleteProjectionDrawings(removedProjection)
```

`status 1` (anchor bị phá) và `status 2` (chạm −4) đều **bị xoá ngay khỏi mảng**. Hệ quả kép:

1. **Không có lịch sử thất bại** → không tính được win-rate, R-multiple, thời gian tới mục tiêu.
2. Chart tự thanh lọc: chỉ những set "đẹp" còn lại → nhìn chart tưởng độ chính xác 90%.

Cộng với việc **không có `plot`/`alert`/`alertcondition`** ở bất kỳ đâu, chỉ báo này hiện **không thể kiểm chứng bằng dữ liệu**, chỉ có thể "nhìn".

---

## 3. Bảng lỗi / rủi ro (xếp theo mức độ)

### Critical

| # | Vị trí | Vấn đề | Hệ quả | Hướng sửa |
|---|---|---|---|---|
| **C1** | Khối lifecycle cuối file | Invalidation dùng `high`/`low` của **nến chart đang chạy**, không có `barstate.isconfirmed` | Một wick thoáng qua phá `anchor1` → `projections.remove()` **vĩnh viễn** (var array giữ state qua các tick). Set đúng bị xoá bởi dữ liệu không tồn tại lúc đóng nến | Chỉ xoá khi `barstate.isconfirmed`, hoặc để native snapshot quyết định; tách "cảnh báo mềm" (đổi màu) khỏi "xoá cứng" |
| **C2** | `detectLayer` → `winsCompetition` | `protectCompetitionExtremes` hard-code `true`, là toán hạng `or` → competition filter **không bao giờ chạy** | Mọi candidate confirm đều thành revision; "competition window" chỉ còn chống trùng; `winnerScores` vô dụng | Đưa thành input, bỏ `or` (dùng `and not`), hoặc xoá hẳn logic competition để code trung thực với hành vi |
| **C3** | Toàn bộ lifecycle | Setup invalid/−4 bị **xoá**, không lưu trạng thái | Survivorship bias; không thể audit, không thể backtest, không thể cải tiến có cơ sở | Giữ object với `status`, chỉ gỡ drawing; thêm bảng thống kê + alert; nếu sợ nặng thì archive sang mảng ring-buffer riêng |

### High

| # | Vị trí | Vấn đề | Hệ quả | Hướng sửa |
|---|---|---|---|---|
| **H1** | `consumedBullReferences` / `consumedBearReferences` | Reference bị đánh dấu "đã dùng" và chặn **vĩnh viễn** (FIFO 200) | Cùng một đáy 4H bị quét lại sau 3 tuần → **không có setup nào**, dù cấu trúc mới hoàn toàn | Cooldown theo thời gian/bar, hoặc reset khi reference "resolved" (bị phá bởi close), hoặc key theo `(refTime, structureSignature)` |
| **H2** | `relaxCompetitionSwingWindow`, `higherTimeframeNative` | Patch cứng theo TF: 15m/1H bỏ yêu cầu swing trong competition window + cho phép "acquire structure muộn"; ≥4H đổi gap/swing/lifetime | Cùng một preset cho hành vi khác nhau tuỳ TF; lỗi gốc (candidate tạo trước khi leg hình thành) **vẫn còn** ở 5m/4H/D | Thay bằng 1 cờ `allowLateStructure` + `structureGraceBars` áp dụng nhất quán; bỏ magic TF |
| **H3** | `DELIVERY_SCAN_LIMIT = 12` | Leg dài bị cắt còn 12 nến | CISD quá gần giá → confirm sớm; swing bị tìm **bên trong** chân đẩy thật → range nhỏ hơn thực → mục tiêu bị co lại | Nâng trần (48–96) hoặc dừng theo ATR/tick; tách thành tham số "max delivery bars" |
| **H4** | `htfViolationMode == "Body close"` | Dùng `processedClose` (native TF) thay vì close của nến liquidity TF | Nhãn "Liquidity sweep uses Body close" **sai ngữ nghĩa**: 1 nến 1m đóng dưới đáy 15m ≠ nến 15m đóng dưới đáy cũ | Lưu thêm `buildingLiquidityOpen/Close` và so `close` của bucket đã đóng |
| **H5** | Không có `plot`/`alert` | Không có output machine-readable | Không automation, không data window, không thống kê, không ghép với strategy | `plot(..., display=display.data_window)` cho CISD/level/status + `alert()` `freq_once_per_bar_close` |

### Medium

| # | Vị trí | Vấn đề | Hệ quả | Hướng sửa |
|---|---|---|---|---|
| **M1** | `detectLayer` xử lý `bar[1]` | Mỗi context chỉ xử lý nến **đã đóng trước đó**; ở nhánh `security_lower_tf`, phần tử cuối của chart bar chưa được xử lý | Trễ ≥1 native bar; trễ ~1 chart bar với nhánh lower_tf; tín hiệu live muộn hơn cảm giác | Dùng `barstate.isconfirmed` thay cho offset `[1]` khi context đã là nến đóng; hoặc offset theo nhánh |
| **M2** | `request.security(..., lookahead=lookahead_on)` | Red flag kinh điển | Hiện **an toàn** vì `detectLayer` chỉ đọc dữ liệu đã đóng (`[1]`, `[2]`); nhưng nếu ai thêm `close`/`high` hiện tại vào detectLayer → **leak tương lai ngay lập tức** | Giữ + comment cảnh báo rõ + test bar-replay; hoặc chuyển sang `barmerge.lookahead_off` và chấp nhận trễ |
| **M3** | `deepenCandidate` | Reset `cisd`, `stage` nhưng không reset `startBar`/`firstSweepTime` | Sweep sâu muộn làm setup chết oan vì đồng hồ `cisdLifetime` đã cạn | Reset cửa sổ CISD khi extreme mới (và ghi rõ trong tooltip), hoặc tách `startBar` vs `structureBar` |
| **M4** | `firstObjectiveHitTime` | Bỏ qua nến confirmation (`nativeTime > confirmationTime`) | Nếu giá đã vượt −2 ngay tại nến confirm → rail −2 không đóng băng, rail −3.5 không xuất hiện | Đổi `>` thành `>=` hoặc kiểm tra riêng high/low của nến confirm |
| **M5** | Trần drawing 500/500/500 | Cấu hình tối đa: `maxVisibleSets` 10 × (1 primary + 5 MTF) ≈ 60 set × 8 line ≈ 480 line + 288 label | TradingView **tự xoá hình cũ nhất** → mất anchor/CISD ngẫu nhiên, chart "lởm chởm" | Giảm trần set, chỉ vẽ level trong ±X range quanh giá, hoặc gộp 3 zone thành 1 box |
| **M6** | `calc_bars_count` 500–1500 × 7 layer + O(n²) reference | CPU: ước tính ~10k bar × ~2–4k phép tính/bar | Load chậm, nguy cơ "Calculation takes too long"; lịch sử hiển thị bị giới hạn (~25h trên 1m) | Cache reference list theo bucket; giảm scan depth theo TF; chỉ request layer thực sự hiển thị (đã làm một phần) |
| **M7** | `upsertWinner` + `findNearDuplicate` | `shouldUse` so `winnerScore > old.selectionScore` khi `sameWindow` na → event của cửa sổ **khác** có thể ghi đè event mới hơn | Mất set mới vì một bản trùng cũ "điểm cao hơn" | Ưu tiên `confirmationTime`, chỉ so score trong cùng window |
| **M8** | Layout vẽ | Vẽ từ `anchor1Time` (quá khứ) dù biết tại `confirmationTime` | Ảo giác hindsight khi review chart | Bắt đầu marker tại `confirmationTime`, hoặc vẽ vùng "pre-confirmation" bằng nét mờ |

### Low / cosmetic

| # | Vấn đề |
|---|---|
| **L1** | `eventId` được build (4 lần `str.tostring` mỗi projection) nhưng **không dùng để dedupe** → tốn CPU, dead field |
| **L2** | Chart < 1 phút (seconds charts): `supportedChart = false` → indicator im lặng, không vẽ, không cảnh báo |
| **L3** | Checkbox "Fill −1 to −1.5" phụ thuộc `showMinusOnePointFive` (mặc định **off**) → bật Fill mà không thấy gì |
| **L4** | Số `0` và `1` không bao giờ được vẽ (đúng chủ ý), nhưng `showZero`/`showOne` vẫn điều khiển line anchor → nhãn input gây hiểu lầm |
| **L5** | Mapping TF lẻ: 2m → preset 5m; 3H → preset 1H (primary confirmation **thấp hơn** chart TF) → "primary" không còn là primary |
| **L6** | `REF_SWING`, `REF_EXTREME`, `layer5*`, `alsoShowLegacyDailyInGroup5`, `useNearestSwingFallback`, `requireStructureClose`, `showStatusTable`, `useChartForeground` — dead code / không có input, ~200 dòng |
| **L7** | Bull và bear code nhân đôi ~600 dòng; đã thấy dấu hiệu patch lệch (khối "15m/1H fix" xuất hiện 2 lần, điều kiện `relaxCompetitionSwingWindow` lặp 4 chỗ) |
| **L8** | `int bullPendingId = na` + `pendingBullId.set(...)` mỗi bar — ống dẫn trạng thái dài, dễ lệch nếu thêm field mới vào `LayerSnapshot` (đã 43 field) |
| **L9** | Comment `//test` và `// Publication preview refreshed.` còn sót trong bản publish |

---

## 4. Rủi ro repaint — phân tích riêng

| Nhánh | Cơ chế | Repaint? |
|---|---|---|
| `security_lower_tf` + `[1]` | Chỉ dùng nến đã đóng | **Không** (chỉ trễ) |
| `security(..., lookahead_on)` | Hàm chỉ đọc `[1]`, `[2]`, `atr[1]` | **Không leak giá**, nhưng `lookahead_on` khiến giá trị của HTF bar N xuất hiện sớm hơn thời điểm nến N đóng — hợp lệ vì giá trị đó chỉ chứa dữ liệu tới N−1 |
| Lifecycle dùng `high`/`low` nến live | Có đọc dữ liệu đang hình thành | **CÓ** — và xoá là vĩnh viễn (C1) |
| `time_close` cho rail/box live | Chỉ ảnh hưởng bar cuối | Cosmetic |
| `pendingCisd` | Chỉ `barstate.islast` | Cosmetic |

→ Chỉ báo **không repaint về mặt phát hiện setup**, nhưng **repaint về mặt huỷ setup**. Đây là dạng nguy hiểm hơn khi dùng live: bạn có thể mất một set đúng vì một wick, và không có log nào ghi lại chuyện đó đã xảy ra.

---

## 5. Chấm phương pháp: đâu là chỗ "ảo" và đâu là chỗ thật

**Thật (có cơ sở cấu trúc):**
- CISD định nghĩa đúng (open cực trị của chân đẩy cuối, yêu cầu ≥2 nến thật).
- "0" của STDV là swing khởi phát chân đẩy — đúng bản chất STDV.
- Yêu cầu phá swing đối ứng sau CISD là điều kiện nhân quả hợp lý (buộc có displacement thật, không chỉ 1 nến hồi).
- Thứ tự sweep → CISD → swing break → projection là một chuỗi có thể phát biểu lại bằng lời, tức là **có thể test độc lập**.

**Ảo / thiếu:**
- "Competition 90m/4H" **không hoạt động** (C2) → không có khái niệm "cửa sổ cạnh tranh" thực sự.
- Không có bộ lọc bias HTF, session (Asia/London/NY), draw-on-liquidity, FVG/OB, volume → nó là **pattern matcher thuần**, không phải framework.
- Không có khái niệm "setup đã thất bại" → system không có bộ nhớ → không học được gì.
- Không có phân biệt chất lượng reference (đỉnh 5 phút trước vs đỉnh 3 tháng trước) dù `importance` có biến để làm việc đó.
- Không có điều kiện vô hiệu hoá theo `a0` (chỉ `a1`) → một set có thể "sống" dù cấu trúc gốc đã bị phá theo hướng ngược.

---

## 6. Patch gợi ý (theo thứ tự ưu tiên)

### P0 — Không xoá, chỉ retire + thống kê

```pine
// thay khối cuối:
Projection checked = projections.get(lifecycleIndex)
if checked.status != 0
    checked := deleteProjectionDrawings(checked)   // chỉ gỡ hình
    // KHÔNG remove: giữ để thống kê / alert / audit
    projections.set(lifecycleIndex, checked)
```

Thêm bộ đếm và 1 bảng nhỏ:

```pine
var int statConfirmed = 0, var int statHit2 = 0, var int statHit4 = 0, var int statInvalid = 0
// tăng statConfirmed khi revision tăng; statHit2/4 khi firstObjectiveHitTime/deepObjectiveHitTime được set lần đầu;
// statInvalid khi status := 1. Hiển thị: win-rate = statHit2 / statConfirmed.
```

> Chỉ cần thêm phần này là bạn có thể **trả lời được câu hỏi quan trọng nhất**: phương pháp này đúng bao nhiêu %, thay vì tin vào cảm giác.

### P0 — Chống xoá do wick

```pine
bool chartCanInvalidateLive = chartSeconds <= safeTfSeconds(projection.confirmationTf)
if projection.status == 0 and chartCanInvalidateLive and time > projection.confirmationTime
    // intrabar: chỉ cảnh báo, không xoá
    if not barstate.isconfirmed
        // optional: đổi màu / ghi nhãn "wick risk"
    else
        // chốt invalidation theo close (hoặc theo snapshot native)
```

### P1 — Reference cooldown thay vì khoá vĩnh viễn

```pine
// thay arrayHasInt(consumed...) bằng kiểm tra thời gian
int lastUseBar = consumedRefBars.get(refTime)     // map<refTime, bar_index>
bool reusable = na(lastUseBar) or bar_index - lastUseBar > effectiveCandidateLifetime * 4
```

### P1 — Sửa `Body close` cho sweep

```pine
var float buildingLiquidityClose = na
// trong nhánh cập nhật bucket: buildingLiquidityClose := processedClose
// khi đóng bucket: completedLiquidityCloses.push(buildingLiquidityClose)
float bullMeasure = htfViolationMode == "Body close" ? completedLiquidityCloses.get(liquidityCount - 1) : processedLow
```

### P2 — Alert + plot (để dùng được thật)

```pine
plot(layerVisible(0) ? projections.size() : na, "Active projections", display=display.data_window)
alertcondition(newRevision6, "New 1m CISD", "Bandz: new 1m confirmed setup")
// hoặc alert() ở ingestSnapshot: alert(msg, alert.freq_once_per_bar_close)
```

### P2 — Giảm tải

- `cache` danh sách reference theo `buildingLiquidityTime` (chỉ tính lại khi đóng bucket mới) thay vì mỗi native bar.
- Giảm `calc_bars_count` cho layer nặng (1m: 1500 → 500) và nêu rõ trong tooltip "history limited".
- Bỏ build `eventId` nếu không dùng, hoặc dùng nó làm khoá dedupe (thay 4 phép so sánh chuỗi/giá).

---

## 7. Kế hoạch kiểm chứng đề xuất (quan trọng hơn mọi refactor)

1. **Bar replay 3 tháng trên 1 khung** (ví dụ 5m/BTC): đếm tay `confirmed`, `hit -2`, `hit -4`, `invalid`. So với bảng thống kê sau khi patch P0. Nếu lệch → logic lifecycle sai.
2. **So sánh realtime vs reload**: mở chart realtime, ghi lại các set đang hiện; F5; so sánh. Bất kỳ set nào biến mất sau reload = repaint.
3. **Kiểm tra tính bất biến theo TF**: chạy preset 15m trực tiếp trên chart 15m và dưới dạng MTF trên chart 1m → danh sách setup phải **trùng nhau** (vì `detectLayer` chỉ phụ thuộc confirmation TF). Nếu lệch → nhánh `[1]`/`lookahead` có vấn đề.
4. **Đo tải**: đổi `calc_bars_count` và xem thời gian load; xác định ngưỡng gây timeout.
5. **Kiểm tra C2**: tạm đặt `protectCompetitionExtremes = false` và so số setup — bạn sẽ thấy chênh lệch lớn, xác nhận bộ lọc đang bị tắt.

---

## 8. Nếu được refactor, nên chia thành 3 file

1. **`Bandz Detector`** (không vẽ): state machine + `alert()` + `plot(display=data_window)` + bảng thống kê. Có thể ghép với strategy.
2. **`Bandz Renderer`** (chỉ vẽ): nhận state qua `input` thủ công hoặc tự detect, tập trung vào drawing budget, level selection, fade.
3. **`Bandz Lab`**: thống kê win-rate theo layer/TF/session, phân bố thời gian tới −2/−4, để trả lời "preset nào thật sự tốt".

Việc tách này giải quyết luôn M5 (drawing limit), M6 (hiệu năng) và C3 (audit).

---

## 9. Tóm lại

- **Chất lượng code**: trên trung bình. Có ý thức về `na`, về cap bộ nhớ, về dedupe, về dọn drawing. Comment giải thích *tại sao* chứ không chỉ *cái gì* — điều hiếm gặp.
- **Chất lượng phương pháp**: CISD và STDV làm đúng. Nhưng "competition" đang bị tắt âm thầm, patch theo TF làm hành vi không nhất quán, và việc xoá setup thất bại khiến toàn bộ hệ thống **không thể đánh giá**.
- **Rủi ro lớn nhất khi dùng live**: C1 — một wick xoá vĩnh viễn một set đúng.
- **Việc đáng làm nhất, rẻ nhất**: giữ setup đã chết + đếm + hiển thị win-rate. Không cần sửa logic phát hiện, chỉ cần ngừng xoá.

> Nếu bạn muốn, bước tiếp theo tôi có thể: (a) viết bản patch Pine v6 cho C1 + C3 + H5 (giữ nguyên logic phát hiện), hoặc (b) tách thành detector + renderer, hoặc (c) dựng bảng thống kê win-rate theo layer để so sánh 6 preset.
