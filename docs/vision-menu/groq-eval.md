# Groq 視覺辨識評估報告

**日期：** 2026-09-18  
**Run：** `docs/vision-menu/runs/groq-20260918-131400/`  
**刺激集：** `menu_example/`（gold v1，與同日 Gemini / Mistral / iAI 菜單實驗同一套錨點）  
**金鑰：** 不寫入本報告。  
**對照 run：** [`vision-20260918-130204`](runs/vision-20260918-130204/report.md)（未含 Groq）

這不是 `vision-menu` 全目錄掃描。Groq 被協議預設排除（`supports_vision=False`、預設模型拒圖）。本輪只回答三件事：當時可見型錄裡誰能看圖、現有紅正方形探針會不會誤殺、Qwen 3.8 在四張核心菜單上能不能入庫。

---

## 1. 結論（先讀這段）

**能看圖的 Groq 模型，當時可見型錄裡只有 `qwen/qwen3.8-27b`（Preview）。**

| 問題 | 答案 |
|---|---|
| Groq 這家能不能視覺辨識？ | 能，但只限特定模型，不是整家 API |
| 預設 `openai/gpt-oss-20b` 能不能看圖？ | 不能。400：`content` 必須是字串 |
| 官方還寫的 `qwen/qwen3.6-27b`、Llama 4 Scout / Maverick？ | 文件有；**今日 `GET /v1/models` 沒有** |
| 簡單大字菜單能不能入庫？ | 能。優惠套餐 1–5 號：JSON／品名／價格 100%，2.7 s，幻覺 0 |
| 難圖呢？ | 三商巧福店頭：品名 67%、價格 60%（JSON 欄），12 s |
| 免費層卡在哪？ | **OTPM ≈ 1000**（每分鐘輸出 token），不是「看不看圖」 |
| 現有 16×16 探針？ | 會誤殺。Qwen 3.8 要求每邊至少 32 像素 |

聊天 Router 繼續 Groq 第一棒、預設 gpt-oss。菜單視覺另開 Qwen 3.8，不要把 Groq 當點餐入庫的唯一路徑。

---

## 2. 問題與方法

### 2.1 要回答的問題

1. 9/15 寫「Groq 不能接圖」是否過時？那次打的是預設 gpt-oss。
2. 官方視覺文件列出的模型，這個免費帳號今天實際看不看得到？
3. 若看得到，在真實台灣菜單照片上，品名／價格能不能進結構化 JSON？
4. 現有 `vision-menu` 探針（16×16 紅 PNG）套到 Groq 會發生什麼？

### 2.2 程序

```
catalog   GET https://api.groq.com/openai/v1/models
probe     16×16 紅 PNG × gpt-oss-20b、qwen/qwen3.8-27b
core      qwen/qwen3.8-27b × 4 張核心菜單（同一套 EXTRACT_PROMPT、temperature=0）
```

評分沿用 `llmclab.vision_menu.score_prediction`：規則比對 gold 錨點，不用另一個 LLM 當裁判。JSON 可解析 ≠ OCR 正確。

請求走現有 `llmclab.client.chat`，因此 Groq provider 的 `extra_body.reasoning_effort=low` 會套到 Qwen 3.8（該模型文件建議非思考模式用 `none`）。這影響輸出額度，見 §5。

未重跑 extended 14 張，也未把 Groq 併進 `vision-20260918-130204`。

---

## 3. 目錄：誰能看圖

今日 `GET /v1/models` 回 **13** 個 ID。

| 模型 ID | 分類 | 視覺 |
|---|---|---|
| `qwen/qwen3.8-27b` | chat / Preview | **能**。官方：圖+文、OCR、最多 3 張、單圖計 2048 input token、檔案 ≤20 MB |
| `qwen/qwen3.6-27b` | 文件仍列 | **此帳號目錄沒有** |
| `meta-llama/llama-4-scout-17b-16e-instruct` | 舊視覺文件 | **目錄沒有** |
| `meta-llama/llama-4-maverick-17b-128e-instruct` | 舊視覺文件 | **目錄沒有** |
| `openai/gpt-oss-20b`（lab 預設） | chat | 不能。400 `content` 必須是字串 |
| `openai/gpt-oss-120b`、`openai/gpt-oss-safeguard-20b` | chat | 未另探；同系列文字模型 |
| `groq/compound`、`groq/compound-mini` | 系統 | 未當視覺模型測 |
| `allam-2-7b`、`llama-prompt-guard-2-*` | chat 清單 | 非菜單視覺 |
| `canopylabs/orpheus-*` | 被標成 chat | 其實是 TTS；名稱不含 `tts`，現有分類器漏掉 |
| `whisper-large-v3`、`whisper-large-v3-turbo` | ASR | 正確跳過 |

官方視覺頁（[Images and Vision](https://console.groq.com/docs/vision)）此刻寫 Qwen 3.6 / 3.8。**以 API 目錄為準，不要以文件為準。**

---

## 4. 探針：16×16 紅塊會誤殺 Groq

| 模型 | 設定 | 結果 | 錯誤 |
|---|---|---|---|
| `qwen/qwen3.8-27b` | lab 預設 `max_tokens=32` | **reject** | 400：Image must have at least 32 pixels in each dimension |
| `qwen/qwen3.8-27b` | `max_tokens=256`、`reasoning_effort=none` | **reject** | 同上。不是思考模式問題，是圖太小 |
| `openai/gpt-oss-20b` | lab 預設 | **reject** | 400：`messages[0].content must be a string` |
| `openai/gpt-oss-20b` | `reasoning_effort=none` | **reject** | 400：gpt-oss 只接受 `low` / `medium` / `high` |

若把 Groq 原樣丟進 `python -m llmclab vision-menu`，唯一能看圖的模型會被標 `reject`，根本進不了 core。協議裡的「紅正方形可能低估只吃大圖的模型」在 Groq 上更嚴重：不是低估，是**直接拒**。

真實菜單 JPG（最小約 99 KB、遠大於 32×32）Qwen 3.8 吃得下去。要評 Groq 視覺，探針至少 32×32，或直接用一張小菜單當探針。

---

## 5. 核心菜單抽取

模型固定 `qwen/qwen3.8-27b`。prompt 與 gold 與同日其他家相同。

| 圖 | 難度 | JSON | schema | 店名 | 品名 | 價格 | JSON 品名 | JSON 價格 | 延遲 | in / out | 備註 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| 優惠套餐 1–5 | easy | 是 | 是 | 是 | 100% | 100% | 100% | 100% | 2.69 s | 1020 / 644 | 幻覺 0；`title=優惠套餐` |
| 三商巧福店頭 | hard | 是 | 是 | 是 | 67% | 60% | 67% | 60% | 12.02 s | 1020 / 1729 | 27 個品項；反光多面板 |
| 四海豆漿大王 | hard | 否 | 否 | 是（原文） | 25% | 25% | 0% | 0% | 2.64 s | 1020 / 800 | 先 429 OTPM；重打截在思考過程 |
| 蘭州拉麵點菜單 | medium | 否 | 否 | 是（原文） | 48% | 48% | 0% | 0% | 2.46 s | 2044 / 800 | JSON 開頭正確，800 token 截斷 |

**讀法：** 前兩張是能力；後兩張是配額。四海／蘭州的召回是截斷後的下限，不能解釋成「Qwen 3.8 讀不懂直書／點菜單」。

三商巧福未命中的錨點：超大盛牛肉壽喜飯、叻沙牛肉麵、番茄牛肉麵、紅燒四寶牛肉麵、揚州雙寶牛肉拉麵、醬滷黑豆干。店名「三商巧福」有進 title。

蘭州截斷前已寫出 `title=蘭州手工現做拉麵館`、`金牌牛三寶麵 / 180`。四海截斷原文裡看得到「四海豆漿大王」、杏仁茶 30。模型有在看圖。

### 5.1 同日其他家（四張核心平均，供對照）

資料來自 `vision-20260918-130204`，條件相近、不是同一毫秒。

| Provider | 模型 | 品名召回 | JSON 品名 | 延遲 | 幻覺 |
|---|---|---:|---:|---:|---:|
| Gemini | `gemini-3.1-flash-lite` | 97% | 97% | 5.6 s | 2 |
| iAI | `Furen-std` | 78% | 75% | 33.0 s | 3 |
| Groq | `qwen/qwen3.8-27b`（完整兩張） | 見上表 | 見上表 | 2.7–12 s | 套餐 0 |
| Mistral | `ministral-14b-2512` | 63% | 26% | 28.9 s | 9 |
| iAI | `Nkust` | 0% | 0% | 1.4 s | 0 |

Groq 在**簡單大字菜單**上，結構化完整度高於當日被截斷的 `gemini-3-flash-preview`（那張套餐 JSON 解析失敗、品名召回 80%）。難圖與全日額四張平均，仍是 Gemini 3.1 flash-lite 比較穩。Groq 的賣點是速度與「預設模型之外還有一條能看圖的 Preview」。

---

## 6. 配額：OTPM 才是瓶頸

公開表（Developer / Free 摘要）給 Qwen 3.8：30 RPM、1K RPD、8K TPM、200K TPD。  
**這個組織實際還卡 OTPM（output tokens per minute）= 1000。**

三商巧福一次吐 1729 個 completion token，下一張立刻 429：

- `Limit 1000, Used 928, Requested 644`
- 隨後：`Request too large … Requested 1061`（`max_tokens` 也算進剩餘 OTPM）

所以：

- 密集價目表一次請求就可能超過每分鐘輸出上限。
- 實驗若設 `max_tokens=4096`，剩餘 OTPM 不夠時連「開始產生」都會被拒。
- 免費層菜單抽取：間隔 ≥ 60 s，且把 `max_tokens` 壓在剩餘 OTPM 以內（約 800–900）。
- 同帳號三把 Groq key **共一個組織桶**（9/15 已證實）。KEY2 救不了 OTPM。

圖片 input：三張約 1020 prompt tokens，蘭州 2044。文件寫每張 2048；實測不是常數，但仍遠小於輸出瓶頸。

Qwen 3.8 在 `reasoning_effort=low`（lab 為 gpt-oss 設的全域值）時，四海那輪把額度花在思考過程而不是 JSON。視覺抽取應對 Qwen 設 `reasoning_effort=none`。不要把 `none` 套回 gpt-oss，它會 400。

---

## 7. 對 lab 設定的意義

| 位置 | 現況 | 本輪之後 |
|---|---|---|
| `config.py` Groq `supports_vision` | `False` | **對預設模型仍正確**；視覺是模型屬性，不是 provider 屬性 |
| `check` 視覺欄 | 略過 Groq | 維持略過，或允許指定 `qwen/qwen3.8-27b` 再測 |
| `vision-menu` 預設 | gemini / mistral / iai | 可加 Groq，但必須換 ≥32×32 探針，且只抽 Qwen 3.8 |
| Router 第一棒 | gpt-oss | **不要改成 Qwen 3.8**。聊天與看圖分通道 |
| 9/15「菜單圖：Groq 不能接」 | 針對 gpt-oss | 改成：gpt-oss 不能接；Qwen 3.8 能接，受 OTPM 限制 |

---

## 8. 威脅效度

- 後兩張核心圖被 OTPM 截斷，不能與 Gemini 四張完整平均直接比總召回。
- 未跑 extended 14 張（社群截圖、App、直書其餘）。
- 未對目錄裡每個 chat ID 送真實菜單（Orpheus / Guard / gpt-oss-120b 只靠名稱與一份 gpt-oss 探針排除）。
- Preview 模型可能無預告下架；今日目錄沒有的 ID，明天可能回來。
- `reasoning_effort=low` 不是 Qwen 視覺的最佳設定，可能低估「關思考後的 JSON 完整度」。
- 錨點召回是下限，不是菜單覆蓋率。

---

## 9. 建議

1. **聊天：** 維持 groq → gemini → mistral → iai → local，預設 `openai/gpt-oss-20b`。
2. **菜單看圖：** 獨立通道。候選順序仍以當日完整四張為準：Gemini 3.1 flash-lite 第一；Groq Qwen 3.8 當「快、且 Gemini 日額用完」的備援；不要當唯一入庫來源。
3. **若把 Groq 加進 `vision-menu`：** 探針 ≥32×32；只跑 `qwen/qwen3.8-27b`；gap ≥ 60 s；Qwen 用 `reasoning_effort=none`；`max_tokens` 配合 OTPM。
4. **上線前再 `python -m llmclab models -p groq`。** 視覺模型 ID 當組態，不當常數。

---

## 附錄：重跑

```bash
cd llm-capability-lab
python -m llmclab models -p groq
python -m llmclab ask groq "用一句話介紹高雄" --model qwen/qwen3.8-27b
```

菜單抽取尚未做成 Groq 專用 CLI 旗標。本輪是直接呼叫 `llmclab.vision_menu.run_extract`。原始分數在 [runs/groq-20260918-131400/scores.json](runs/groq-20260918-131400/scores.json)。
