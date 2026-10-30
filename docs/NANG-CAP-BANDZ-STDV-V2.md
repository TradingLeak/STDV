# Nâng cấp `Bandz STDV & CISD` lên bản tốt nhất

Kế hoạch sửa + nâng cấp, có code Pine v6 sẵn để dán. Thứ tự được chọn theo **giá trị trên mỗi giờ bỏ ra**, không theo độ "hay" của tính năng.

---

## 1. Trước khi sửa: "tốt nhất" nghĩa là gì?

Một chỉ báo tốt nhất không phải chỉ báo có nhiều tính năng nhất. Nó cần 5 thứ, theo đúng thứ tự này:

1. **Đo được** — có log, có thống kê, có thể export để phân tích ngoài TradingView.
2. **Không nói dối bằng hình ảnh** — setup sai vẫn phải nhìn thấy được.
3. **Có một quyết định rõ ràng cho mỗi hướng** — không phải 10 cái hộp để tự chọn cái đẹp.
4. **Rẻ** — không ăn CPU, không đụng trần drawing, load nhanh.
5. **Nói đúng những gì nó làm** — tooltip khớp code.

Hiện tại chỉ báo đang mạnh ở (2) một phần, yếu ở (1) và (3). Vì vậy **80% giá trị nằm ở việc biến nó thành công cụ đo**, không phải thêm mức giá hay thêm mẫu hình.

> Nguyên tắc: *không thêm một tính năng phân tích nào cho tới khi có bảng thống kê.* Nếu thêm FVG/OB/session filter trước khi đo, bạn sẽ không bao giờ biết cái nào thực sự tạo edge.

---

## 2. Kiến trúc đích (v2)

Giữ nguyên phần phát hiện (nó đúng), chỉ tách trách nhiệm:

```
detectLayer()                ← giữ nguyên, chỉ sửa 5 điểm (mục 3)
      │
      ▼
SetupRecord (nhẹ, ring 500)  ← MỚI: bản ghi bất biến của mọi setup, sống mãi
      │   layer | dir | refTime | a0 | a1 | cisd | entry | confirmTime
      │   hit-1 | hit-2 | hit-3.5 | hit-4 | invalidTime | MFE(R) | MAE(R)
      ▼
┌─────────────┬──────────────┬───────────────┐
│ RENDER      │ REPORT       │ ALERT         │
│ ghost + live│ bảng thống kê│ alert() + log │
│ focus mode  │ win-rate, R  │ payload JSON  │
└─────────────┴──────────────┴───────────────┘
```

Ba thay đổi khái niệm quan trọng:

- **Entry quy ước = giá CISD** (không phải "giá đẹp nhất bạn có thể vào"). Stop = `anchor1`. Vậy mọi setup đều có **1R xác định**, so sánh được giữa các layer và các TF.
- **Setup chết vẫn tồn tại** dưới dạng "ghost" (1 line + 1 label), và luôn tồn tại dưới dạng record trong thống kê.
- **`eventId` trở thành khoá dedupe thật** (hiện đang build mà không dùng) — thay vì so 4 phép so sánh giá.

---

## 3. Lộ trình 5 sprint

| Sprint | Nội dung | Tác động | Công sức |
|---|---|---|---|
| **1. Đo lường** | SetupRecord + stats + ghost + log + alert + plot | ★★★★★ | Trung bình |
| **2. Trung thực** | Chặn wick xoá set, competition thật, body-close đúng, deadline CISD | ★★★★☆ | Thấp |
| **3. Chất lượng tín hiệu** | Trần delivery leg, cooldown reference, displacement gate, fallback pivot | ★★★★☆ | Trung bình |
| **4. UX & hiệu năng** | Focus mode, budget drawing, cache reference, xoá dead code, sửa tooltip | ★★★☆☆ | Thấp |
| **5. Bộ lọc (chỉ khi có data)** | Session filter, HTF bias, premium/discount | ★★☆☆☆ (chưa biết) | Trung bình |

---

## 4. Sprint 1 — Đo lường (làm trước tiên)

### 4.1. Bản ghi setup

Đặt ở global scope (không đụng `detectLayer`):

```pine
type SetupRecord
    int layer
    int direction
    int referenceTime
    float anchor0
    float anchor1
    float cisd
    float entry
    int confirmTime
    int hit1Time
    int hit2Time
    int hit35Time
    int hit4Time
    int invalidTime
    float mfeR
    float maeR

var array<SetupRecord> setupLog = array.new<SetupRecord>()
const int SETUP_LOG_LIMIT = 500
```

Ghi record ngay khi `upsertWinner` thật sự thêm mới:

```pine
if shouldUse
    // ... code cũ ...
    SetupRecord rec = SetupRecord.new(layer, direction, referenceTime, anchor0, anchor1, cisd,
         cisd, confirmationTime, na, na, na, na, na, na, na)   // entry = cisd
    setupLog.push(rec)
    if setupLog.size() > SETUP_LOG_LIMIT
        setupLog.shift()
```

### 4.2. Cập nhật MFE/MAE và các mốc hit

Trong `ingestSnapshot`, chỗ đang xử lý lifecycle — thêm phần excursion:

```pine
if projection.status == 0 and snapshot.nativeTime > projection.confirmationTime
    float risk = math.abs(projection.cisd - projection.anchor1)
    if not na(risk) and risk > 0
        float favorable = projection.direction == 1 ?
             (snapshot.nativeHigh - projection.cisd) / risk : (projection.cisd - snapshot.nativeLow) / risk
        float adverse = projection.direction == 1 ?
             (projection.cisd - snapshot.nativeLow) / risk : (snapshot.nativeHigh - projection.cisd) / risk
        projection.mfeR := na(projection.mfeR) ? favorable : math.max(projection.mfeR, favorable)
        projection.maeR := na(projection.maeR) ? adverse   : math.max(projection.maeR, adverse)
```

(Cần thêm `float mfeR`, `float maeR` vào type `Projection` và vào cuối lời gọi `Projection.new` → thêm `na, na`.)

### 4.3. Giữ setup chết + ghost

Thêm 4 field vào `Projection` (và 4 giá trị vào cuối `Projection.new`):

```pine
    int  deadTime          // thời điểm chết
    bool statsRecorded
    float mfeR
    float maeR
```

Thay khối cuối hiện tại:

```pine
// CŨ
// Projection removedProjection = projections.remove(lifecycleIndex)
// removedProjection := deleteProjectionDrawings(removedProjection)

// MỚI
Projection dead = projections.get(lifecycleIndex)
if dead.status != 0
    dead := deleteProjectionDrawings(dead)          // chỉ gỡ hình "sống"
    if showGhosts and na(dead.deadTime)
        pushGhost(dead.anchor1Time, dead.anchor1, dead.endTime,
             dead.status == 2 ? "−4" : "×",
             dead.status == 2 ? color.new(color.gray, 55) : color.new(color.red, 55))
        dead.deadTime := dead.endTime
    if not dead.statsRecorded
        recordOutcome(dead)                          // cộng vào bảng thống kê
        dead.statsRecorded := true
    projections.set(lifecycleIndex, dead)            // GIỮ LẠI
lifecycleIndex -= 1
```

Ghost dùng ring buffer riêng, **không** đụng trần 500 line của projection:

```pine
var array<line>  ghostLines  = array.new_line()
var array<label> ghostLabels = array.new_label()
const int GHOST_LIMIT = 40

pushGhost(int x1, float y, int x2, string txt, color c) =>
    if not na(x2) and x2 > x1
        ghostLines.push(line.new(x1, y, x2, y, xloc=xloc.bar_time, color=c,
             style=line.style_dotted, width=1))
        ghostLabels.push(label.new(x2, y, txt, xloc=xloc.bar_time, yloc=yloc.price,
             style=label.style_none, textcolor=c, size=size.tiny))
        if ghostLines.size() > GHOST_LIMIT
            line.delete(ghostLines.shift())
            label.delete(ghostLabels.shift())
    0
```

**Bắt buộc kèm theo:**

- thêm `projection.status == 0` vào các nhánh `sameReference / sameSweep / nearAnchors` trong `findNearDuplicate`, nếu không ghost sẽ bị coi là "bản trùng" và bị ghi đè;
- nâng `GLOBAL_PROJECTION_LIMIT` 140 → 300 (giờ có thêm set chết);
- trong vòng render, bỏ qua sớm `if projection.status != 0` để không gọi `deleteProjectionDrawings` mỗi bar cho mọi xác chết.

### 4.4. Bảng thống kê (phần quan trọng nhất)

Lưu ý Pine: **function không được gán biến global**, nên dùng array làm accumulator (mutate qua `array.set` là hợp lệ):

```pine
// 0=N, 1=hit2, 2=hit35, 3=invalid, 4=exhausted, 5=sumBars2, 6=sumMFE, 7=sumMAE
var array<float> stats = array.new_float(8, 0.0)

recordOutcome(Projection p) =>
    stats.set(0, stats.get(0) + 1)
    if p.status == 2
        stats.set(4, stats.get(4) + 1)
    else
        stats.set(3, stats.get(3) + 1)
    if not na(p.firstObjectiveHitTime)
        stats.set(1, stats.get(1) + 1)
        stats.set(5, stats.get(5) + float(p.firstObjectiveHitTime - p.confirmationTime) /
             float(safeTfSeconds(p.confirmationTf) * 1000))
    if not na(p.deepObjectiveHitTime)
        stats.set(2, stats.get(2) + 1)
    stats.set(6, stats.get(6) + nz(p.mfeR))
    stats.set(7, stats.get(7) + nz(p.maeR))     // kết thúc bằng array.set → function void, gọi như statement được
```

Hiển thị (bảng 2 cột, chỉ ở `barstate.islast`):

```
Setup đã đóng       : 187
Chạm −2             : 61.0%      (114/187)
Chạm −3.5           : 27.8%      (52/187)
Invalid trước −2    : 73
Exhausted (−4)      : 39
Số nến TB tới −2    : 14.2
MFE TB / MAE TB     : 1.83R / 0.71R
```

Đây là **thứ duy nhất** trả lời được câu hỏi "chỉ báo này có edge không". Không có nó, mọi đánh giá khác đều là cảm tính.

### 4.5. Pine Logs + alert

```pine
var array<string> eventQueue = array.new_string()

// trong ingestSnapshot, khi revision tăng:
eventQueue.push(str.format("{0}|{1}|{2}|cisd={3}|a1={4}|t={5}",
     layer, direction, "CONFIRM", snapshot.bullCisd,
     snapshot.bullA1, str.format_time(snapshot.bullConfirmTime, "yyyy-MM-dd HH:mm")))

// global, cuối script:
if eventQueue.size() > 0 and barstate.isconfirmed
    for i = 0 to eventQueue.size() - 1
        log.info("{0}", eventQueue.get(i))
    alert(eventQueue.get(0), alert.freq_once_per_bar_close)
    eventQueue.clear()
```

- `log.info` → Pine Logs panel → copy ra CSV → phân tích bằng Python. Đây là **audit trail** thật.
- `alert()` → webhook/Discord/automation, payload đã có layer/giá/thời gian.

### 4.6. Plot cho Data Window

```pine
plot(activeBullCount, "Active bull", display=display.data_window)
plot(primaryBullCisd, "5m bull CISD", display=display.data_window)
plot(stats.get(0) > 0 ? 100.0 * stats.get(1) / stats.get(0) : na, "Hit −2 %", display=display.data_window)
plot(stats.get(0) > 0 ? stats.get(6) / stats.get(0) : na, "Avg MFE (R)", display=display.data_window)
```

Từ đây có thể ghép sang strategy/risk manager mà không cần sửa gì.

---

## 5. Sprint 2 — Trung thực (sửa 4 lỗi, ~40 dòng)

### 5.1. Chặn wick xoá set (C1)

```pine
if projection.status == 0 and chartCanInvalidateLive and time > projection.confirmationTime
    // objective touch vẫn cập nhật intrabar: chỉ để hiển thị, không phá dữ liệu
    if na(projection.firstObjectiveHitTime) and projectionTargetTouched(projection, -2.0, high, low)
        projection.firstObjectiveHitTime := time

    // CHỈ chốt invalidation/-4 khi nến đã đóng
    if barstate.isconfirmed or not barstate.islast
        float minusFour = projectionPrice(projection.anchor0, projection.anchor1, -4.0)
        bool anchorWick = anchorInvalidationMode == "Wick" and
             (projection.direction == 1 ? low < projection.anchor1 : high > projection.anchor1)
        bool minusFourWick = minusFourCompletionMode == "Wick" and
             (projection.direction == 1 ? high >= minusFour : low <= minusFour)
        if minusFourWick
            projection.status := 2
            projection.endTime := time
        else if anchorWick
            projection.status := 1
            projection.endTime := time
    projections.set(lifecycleIndex, projection)
```

Lưu ý: `barstate.isconfirmed` luôn `true` trên nến lịch sử → kết quả historical **không đổi**, chỉ nến realtime mới an toàn.

### 5.2. Competition thật (C2)

```pine
bool protect = input.bool(true, "Protect most extreme CISD in window",
     tooltip="On: chỉ setup có CISD cực trị hơn mới thay thế setup trong cùng cửa sổ. Off: setup điểm cao hơn thắng.")

// bỏ hẳn toán hạng "protectCompetitionExtremes or"
bool winsCompetition = not competitionFilterEnabled or winnerIndex == -1 or
     (windowStillOpen and (protect ? moreExtremeCisd : candidateScore > bullWinnerScores.get(winnerIndex)))
```

Hệ quả cần biết trước: **số setup sẽ giảm đáng kể**. Đây chính là điều bạn muốn thấy khi đo — nếu chất lượng không tăng thì giả thuyết "cửa sổ cạnh tranh" là sai.

### 5.3. `Body close` đúng nghĩa (H4)

```pine
var float buildingLiquidityClose = na
var array<float> completedLiquidityCloses = array.new_float()

// khi cập nhật bucket:
buildingLiquidityClose := processedClose
// khi đóng bucket:
completedLiquidityCloses.push(buildingLiquidityClose)
if completedLiquidityCloses.size() > 128
    completedLiquidityCloses.shift()

// đo sweep:
float bullMeasure = htfViolationMode == "Body close" ?
     completedLiquidityCloses.get(completedLiquidityCloses.size() - 1) : processedLow
```

Và vì sweep theo close chỉ được xác định tại **nến liquidity đóng**, chỉ tạo candidate khi `completedLiquidityBar` (hoặc chấp nhận trễ 1 nến HTF — trung thực hơn nhiều so với hiện tại).

### 5.4. Deadline CISD phải reset khi sweep sâu hơn (M3)

```pine
type Candidate
    ...
    int cisdDeadlineBar          // MỚI

// tạo mới:
cisdDeadlineBar = processedBarIndex + effectiveCisdLifetime

// deepen:
updated.cisdDeadlineBar := processedBarIndex + effectiveCisdLifetime
updated.stage := 0
// startBar và firstSweepTime giữ nguyên (đúng: đó là thời điểm quét đầu)

// expire:
bool cisdExpired = requireRapidReclaim and candidate.stage == 0 and
     processedBarIndex > candidate.cisdDeadlineBar
```

Tổng lifetime vẫn bị chặn bởi `candidateLifetime` nên không có chuyện sống vô hạn.

### 5.5. Objective hit trên nến confirmation (M4)

```pine
if projection.status == 0 and snapshot.nativeTime >= projection.confirmationTime
```
(`>=` thay `>`; cao lắm chỉ lệch 1 nến, nhưng tránh được trường hợp giá đã vượt −2 ngay tại nến confirm làm rail không bao giờ đóng băng.)

---

## 6. Sprint 3 — Chất lượng tín hiệu

### 6.1. Bỏ trần 12 nến của delivery leg (H3)

```pine
const int DELIVERY_SCAN_LIMIT = 36      // 12 → 36
```

Chi phí: 2 hướng × 7 layer × 36 vòng/bar ≈ 500 vòng/bar — không đáng kể so với phần còn lại. Lợi ích: CISD và range không còn bị bóp méo bởi chân đẩy dài.

### 6.2. Cooldown reference thay vì khoá vĩnh viễn (H1)

```pine
var map<int, int> consumedBullRefBar = map.new<int, int>()
var map<int, int> consumedBearRefBar = map.new<int, int>()
int refCooldownBars = effectiveCandidateLifetime * 3

// thay cho arrayHasInt(consumedBullReferences, referenceLowTime):
int usedAt = consumedBullRefBar.get(referenceLowTime)
bool refBlocked = not na(usedAt) and (processedBarIndex - usedAt) <= refCooldownBars

// khi confirm:
consumedBullRefBar.put(candidate.referenceTime, processedBarIndex)
```

Quy tắc kèm theo: **chỉ setup đã confirm mới "khoá" reference**. Setup fail (hết hạn) không khoá — vì level đó chưa bị "xử lý" theo nghĩa liquidity.

### 6.3. Displacement gate (chống leg quá nhỏ)

```pine
float legRange = cisd - nz(oldestLow)            // bull: từ đáy leg tới CISD
bool legHasDisplacement = math.abs(legRange) >= math.max(nativeAtr * 0.35, 2 * syminfo.mintick)
bool bullSetupBaseValid = ... and legHasDisplacement
```

Lọc bỏ các "CISD 2 nến" trong vùng sideway — nhóm này thường là nguồn false positive lớn nhất.

### 6.4. Fallback pivot có kiểm soát

`useNearestSwingFallback` đang `false` cứng → mất setup khi pivot gần nhất nằm ngoài 30 nến. Nâng cấp:

```pine
// nếu không có pivot: dùng đỉnh cao nhất trong 30 nến gần nhất, nhưng đánh dấu quality thấp
if na(swing) and useNearestSwingFallback
    swing := ta.highest(high, 30)[1]
    // và: candidate.deliveryQuality -= 0.5  → score thấp hơn, không được ưu tiên
```

Đo xem nhóm fallback có win-rate khác nhóm pivot không — nếu giống nhau thì bỏ luôn khái niệm pivot.

---

## 7. Sprint 4 — UX, hiệu năng, minh bạch

### 7.1. Focus mode (giải quyết "quá nhiều hộp")

```pine
bool focusMode = input.bool(true, "Focus: 1 setup mỗi hướng mỗi layer",
     tooltip="Chỉ giữ CISD cực trị theo hướng trong cửa sổ hiện tại. Giảm từ 10 set xuống tối đa 2 set/layer.")
```

Cách lọc trong khối selection: sau khi có `candidates`, nếu `focusMode` thì chỉ giữ:
- bull: `cisd` thấp nhất (mua từ dưới);
- bear: `cisd` cao nhất.

Đây là thay đổi **cải thiện trải nghiệm nhiều nhất** mà tốn ít code nhất.

### 7.2. Budget drawing

```pine
// chỉ vẽ level nằm trong ±1.5 range quanh giá; xa hơn thì gộp thành 1 dòng "+N"
bool nearPrice = math.abs(price - close) <= result.projectionRange * 1.5
```
Giữ line count dưới ~200 thay vì chạm trần 500 và bị TradingView xoá hình cũ.

### 7.3. Cache reference (giảm tải O(n²))

Reference chỉ thay đổi khi có nến liquidity mới đóng:

```pine
var array<int>   referenceHighTimes  = array.new_int()
var array<int>   referenceLowTimes   = array.new_int()
var array<float> referenceHighPrices = array.new_float()
var array<float> referenceLowPrices  = array.new_float()

if completedLiquidityBar or na(lastReferenceBuildTime)
    referenceHighTimes.clear() ... // rebuild
    lastReferenceBuildTime := processedTime
```

Sau đó mỗi bar chỉ cần merge reference của candidate đang sống. Ước tính giảm 60–80% CPU ở layer 1m/5m.

### 7.4. Sửa những chỗ "nói một đằng làm một nẻo"

| Hiện tại | Sửa |
|---|---|
| Tooltip "Liquidity sweep uses Body close" | Implement đúng (5.3) hoặc đổi nhãn thành "Native close" |
| "Fill −1→−1.5" phụ thuộc `showMinusOnePointFive` (mặc định off) | Bỏ điều kiện, fill độc lập |
| "Competition 90m/4H" | Sau 5.2 nó mới thật; thêm tooltip nêu rõ hệ quả |
| `showZero` / `showOne` | Đổi nhãn thành "anchor lines (0/1)" |
| `eventId` build mà không dùng | Dùng làm khoá dedupe (thay 4 phép so sánh trong `findNearDuplicate`) |
| Chart < 1 phút im lặng | Thêm 1 label/table báo "unsupported timeframe" |
| Mapping 2m → preset 5m, 3H → preset 1H | Chọn layer có confirmation TF **lớn nhất ≤ chart TF**; nếu không có thì dùng layer gần nhất |

### 7.5. Xoá dead code

`REF_SWING`, `REF_EXTREME` (~60 dòng), `layer5*` (legacy), `useNearestSwingFallback` (nếu không dùng), `showStatusTable` (đang ẩn cứng → đưa thành input Diagnostics), `useChartForeground`, `//test`.

---

## 8. Sprint 5 — Bộ lọc (chỉ sau khi có số liệu)

Chỉ làm nếu bảng thống kê cho thấy vấn đề cụ thể:

| Bộ lọc | Khi nào đáng làm | Cách đo hiệu quả |
|---|---|---|
| Session (London/NY) | Nếu hit-rate giờ Á thấp hơn rõ rệt | So hit-rate theo giờ, xuất từ Pine Logs |
| HTF bias (chỉ trade cùng hướng draw của D) | Nếu setup ngược HTF có MFE thấp hơn | So MFE trung bình 2 nhóm |
| Premium/discount (bull chỉ khi giá dưới 50% dealing range) | Nếu nhóm "mua ở discount" thắng rõ | So 2 nhóm |
| Re-entry sau −4 | Nếu sau exhaustion thường có đảo chiều | Đếm tỷ lệ đảo sau −4 |

Điểm mấu chốt: **mỗi bộ lọc phải chứng minh nó tăng expectancy**, nếu không thì bỏ. Đây là khác biệt giữa công cụ và sở thích.

---

## 9. Những thứ tôi sẽ **không** làm

- **Không thêm preset/TF mới.** 6 preset đã là quá nhiều để đo.
- **Không thêm level** (−1.5, −3.5…). Mỗi level thêm vào là một cơ hội cherry-pick.
- **Không thêm FVG/OB/volume profile** trước khi có thống kê. Chúng sẽ làm indicator "có vẻ" chính xác hơn mà không đo được.
- **Không chuyển thành strategy** với tham số mặc định để "khoe backtest đẹp". Nếu chuyển, phải dùng đúng entry/stop trong mục 2 và báo cáo cả slippage.
- **Không giữ `lookahead_on` mà không có comment cảnh báo** và test reload.

---

## 10. Định nghĩa "xong"

Bản v2 chỉ được coi là tốt hơn bản v1 khi thoả **cả 6 điều**:

1. Reload chart → danh sách setup **không đổi** (không repaint huỷ set).
2. Setup sai vẫn nhìn thấy (ghost) và vẫn nằm trong thống kê.
3. Bảng thống kê chạy được trên ≥ 100 setup và xuất được ra CSV qua Pine Logs.
4. `alert()` bắn đúng 1 lần/setup, có payload layer + giá + hướng.
5. Focus mode: tối đa 2 set/layer, line count < 250.
6. Tooltip khớp hành vi 100% (đặc biệt: Body close, competition).

Thứ tự làm: **1 → 2 → 3 → 4 → 6 → 5**. Nếu chỉ làm được 1 việc, làm việc số 1.

---

## 11. Đề nghị của tôi

Nếu bạn muốn đi tiếp, tôi đề nghị làm **Sprint 1 + 5.1 + 5.2** trong một lần (khoảng 120–150 dòng thay đổi, không đụng vào `detectLayer`): đó là điểm mà chỉ báo chuyển từ "nhìn đẹp" sang "đo được", và là điều kiện để mọi nâng cấp sau đó có ý nghĩa.

Để tôi sửa chính xác thay vì đoán, hãy đưa file `.pine` vào repo (ví dụ `src/bandz_stdv.pine`) — tôi sẽ commit bản v2 kèm diff từng khối, giữ nguyên phần phát hiện.
