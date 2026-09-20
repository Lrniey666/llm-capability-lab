# Gemini / Mistral / iAI 菜單圖視覺實驗報告

**日期：** 2026-09-18  
**Run：** `docs/vision-menu/runs/vision-20260918-130204/`  
**協議：** [protocol.md](protocol.md)  
**Gold：** [gold.json](gold.json)（人類目視錨點，v1）  
**刺激：** repo 根目錄 `menu_example/`（18 張有效圖；1 張 PNG 與 JPG 重複，略過）  
**環境：** Python 3.10.9、`openai` 3.15.0  
**金鑰：** 不寫入本報告。  
**同日 Groq：** [groq-eval.md](groq-eval.md)

評分是規則比對 gold 錨點，不是另一個 LLM 當裁判。JSON 可解析 ≠ OCR 正確。

---

## 1. 結論（先讀這段）

點餐入庫應走 **Gemini `gemini-3.1-flash-lite`**。四張核心台灣菜單上，品名召回 97%、價格 90%、JSON 與 schema 全過、平均 5.6 s。

| 用途 | 選 | 不要選 |
|---|---|---|
| 菜單圖 → 可入庫 JSON | Gemini 3.1 Flash Lite | ministral-3b（JSON 常過、內容常猜） |
| 校內備援 | iAI `Furen-std` 或 `gemma-4-31b` | `Nkust`（紅塊探針會過，菜單一律拒答） |
| 乾淨印刷／點菜單 OCR | Mistral `/v1/ocr`（`mistral-ocr-latest`）再另轉 JSON | 把 OCR 當 chat 模型；店頭反光照片 |
| 免費層 Mistral 看圖 | ministral-8b 勉強可看大字 | small / medium（今日全程 429） |

三家目錄共 **121** 個 ID。大多數不是「看圖理解」：embedding、TTS、繪圖、ASR、live、veo。真正吃 `image_url` 且紅塊答對的，Gemini 3 個、Mistral ministral 6 個（3 尺寸 × 2 個別名）、iAI 3 個（另 2 個 omni 吃圖但把思考倒出來）。

---

## 2. 要回答的問題

1. Gemini / Mistral / iAI **目錄裡每一個模型**，走 Chat Completions（OCR 則走 `/v1/ocr`）時，能不能接受影像？
2. 能接受影像的模型，在真實台灣菜單上，品名與價格能不能進點餐系統？
3. 第一日看到的現象是否仍成立：`ministral-3b` 會吐可解析但內容全猜的 JSON？

Groq 預設排除在本 run，見 [groq-eval.md](groq-eval.md)。

---

## 3. 方法

### 3.1 設計

四段、可斷點續跑。指令：`python -m llmclab vision-menu`。

```
catalog   GET /v1/models（Gemini 58、Mistral 46、iAI 17＝API∪CSV）
probe     16×16 紅 PNG × chat／ocr 模型
core      探針通過者 × 4 張核心圖
extended  通過者 × 其餘 14 張（未作為本報告主結論；中途中斷）
```

控制：同一 `EXTRACT_PROMPT`、`temperature=0`、圖不預先 OCR、序列送出。  
Gemini 聊天 ID 的 `models/` 前綴會在呼叫時拿掉。

### 3.2 核心刺激

| 圖 | 檔名 | 難度 | 佈局 | 完整 gold |
|---|---|---|---|---|
| 優惠套餐 1–5 號 | `Screenshot_20260916-1741242.jpg` | easy | 大字、手寫價 | 是 |
| 蘭州手工拉麵點菜單 | `Screenshot_20260916-1742312.jpg` | medium | 黃底表格 | 是（切盤漏列 2 項，見 §7） |
| 三商巧福店頭 | `20260916_122303549.jpg` | hard | 反光、多面板 | 否 |
| 四海豆漿大王 | `Screenshot_20260916-1235472.jpg` | hard | 直書價目表 | 否 |

錨點是高信心品名／價格，不是全量轉錄。召回是下限。`gold_complete=true` 才把多出來的品名算幻覺。

### 3.3 指標

| 欄 | 意義 |
|---|---|
| 品名／價格召回 | 錨點出現在 JSON **或** 原文（含思考殘渣） |
| JSON 品名／價格 | 只有進結構化欄位才算 → **入庫指標** |
| JSON / schema | `json.loads` 成功、且有 `categories` 陣列 |
| 幻覺 | 完整 gold 圖上，輸出品名對不上任何錨點 |

### 3.4 配額怎麼切

| Provider | 間隔 | 實測 |
|---|---|---|
| Gemini | 13 s | 約 5 RPM / 20 RPD；KEY2/KEY3 共桶。探針打到 `gemini-3.1-pro-preview` 開始 429 |
| Mistral | 1.3 s；單模型 429 不連坐整家 | small / medium / magistral / vibe 全程 429。ministral 與 OCR 可打 |
| iAI | 1.2 s | 無常見的 ratelimit header |

Gemini 探針上限 8 個 chat ID，其餘標 `deferred_quota_cap`／`quota`，**不能解釋成沒有視覺**。`gemini-3.6-flash`（lab 預設）因此沒進本輪抽取。

---

## 4. 目錄與探針

分類後：Gemini chat 22／錯端點 36；Mistral chat 25＋ocr 7／其他 14；iAI chat 10／錯端點 7。

### 4.1 視覺探針結果（節錄）

| 結果 | 模型 |
|---|---|
| **accept_correct** | Gemini：`gemini-3-flash-preview`、`gemini-3.1-flash-lite`、`gemini-3.1-flash-lite-preview`。Mistral：`ministral-{3,8,14}b` 的 `-latest` 與日期版。iAI：`Furen-std`、`gemma-4-31b`、`Nkust` |
| **accept_wrong**（吃圖，紅塊沒答對） | iAI `Furen-omni`、`nemotron-omni-30b`（把英文思考倒出來）。Mistral OCR 全系列（紅塊太小，有的幻覺成財報表格） |
| **reject** | Gemini 2.5-flash/pro（404：新帳號請改 3.x）。iAI `Furen-coder/large/max`、`nemotron-3-super-120b`、`nvidia-ultra-550b`。Mistral codestral / code-fim（Image input is not enabled） |
| **quota** | Gemini 從 3.1-pro 起含 3.5/3.6/3.7/3.8、flash-latest、pro-latest、gemma-4。Mistral small/medium/magistral/vibe |
| **skipped_wrong_endpoint** | embed、ASR、TTS、Pic-*、veo、lyria、live、voxtral、nano-banana、antigravity、deep-research |
| **403** | `labs-leanstral-*`（不在此帳號方案） |

`Nkust` 探針原文已寫「圖片為純紅色塊」卻又夾思考；菜單階段改口拒答。探針通過 ≠ 願意做 OCR。

### 4.2 別名

`ministral-8b-latest` 與 `ministral-8b-2512` 核心分數幾乎同一條線（品名 54%／價格 34%）。`gemini-3.1-flash-lite` 與其 `-preview` 亦同（97%／90%）。以後抽取只打 `*-latest` 即可，不必每個日期版都跑。

---

## 5. 核心四張：菜單抽取

21 個通過探針的 ID × 4 圖 = **84** 次請求。下表是入庫觀點：JSON 欄召回優先；品名召回含原文，給「看得到但結構壞掉」的模型留紀錄。

### 5.1 模型平均（n=4）

| Provider | 模型 | JSON | 品名 | 價格 | JSON品名 | JSON價格 | 延遲 | 幻覺合計 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Gemini | **`gemini-3.1-flash-lite`** | **100%** | **97%** | **90%** | **97%** | **84%** | **5.6 s** | 2 |
| Gemini | `gemini-3.1-flash-lite-preview` | 100% | 97% | 90% | 97% | 84% | 6.1 s | 2 |
| iAI | `Furen-std` | 100% | 78% | 75% | 75% | 68% | 33.0 s | 3 |
| iAI | `gemma-4-31b` | 100% | 75% | 72% | 72% | 68% | 34.4 s | 3 |
| iAI | `nemotron-omni-30b` | 25% | 71% | 63% | 20% | 20% | 11.6 s | 4 |
| Gemini | `gemini-3-flash-preview` | 25% | 70% | 65% | 25% | 25% | 16.0 s | 2 |
| iAI | `Furen-omni` | 25% | 68% | 55% | 0% | 0% | 12.4 s | 0 |
| Mistral | `ministral-8b-latest` | 75% | 54% | 34% | 32% | 32% | 16.6 s | 11 |
| Mistral | `mistral-ocr-latest` | 0% | 50% | 50% | 0% | 0% | 1.2 s | 0 |
| Mistral | `ministral-3b-latest` | 75% | 41% | 21% | 21% | 21% | 4.8 s | 16 |
| iAI | **`Nkust`** | **0%** | **0%** | **0%** | **0%** | **0%** | 1.4 s | 0 |

幻覺數列的是兩張完整 gold 圖加總。蘭州那 2 筆 Gemini「幻覺」其實是 gold 漏標的牛肚／牛筋切盤，見 §7。

### 5.2 分圖（代表模型）

**優惠套餐 1–5（easy，完整 gold）**

| 模型 | JSON | 品名 | 價格 | JSON品名 | 延遲 | 備註 |
|---|---|---:|---:|---:|---:|---|
| gemini-3.1-flash-lite | 是 | 100% | 100% | 100% | 3.1 s | 幻覺 0 |
| Furen-std / gemma-4-31b | 是 | 100% | 100% | 100% | 8 s | 幻覺 0 |
| mistral-ocr-latest | 否 | 100% | 100% | 0% | 1.3 s | 純文字逐行正確 |
| ministral-8b / 3b | 是 | 100% | 20% | 20% | 2–5 s | 品名扭曲（雞嚙、肉肉）；幻覺 4 |
| Nkust | 否 | 0% | 0% | 0% | 0.3 s | 「此問題不在本服務提供的範圍」 |

**蘭州拉麵點菜單（medium，表格）**

| 模型 | JSON | 品名 | 價格 | JSON品名 | 延遲 |
|---|---|---:|---:|---:|---:|
| gemini-3.1-flash-lite | 是 | 100% | 100% | 100% | 5.6 s |
| Furen-std / gemma-4-31b | 是 | 95% | 95% | 95% | 25 s |
| mistral-ocr-latest | 否 | 100% | 100% | 0% | 1.1 s |
| ministral-8b-latest | 是 | 76% | 76% | 76% | 15 s |
| ministral-3b-latest | 是 | 52% | 52% | 52% | 4.4 s |

**三商巧福店頭（hard，反光）**

| 模型 | JSON | 品名 | 價格 | JSON品名 | 延遲 | 備註 |
|---|---|---:|---:|---:|---:|---|
| gemini-3.1-flash-lite | 是 | 87% | 87% | 87% | 6.6 s | 揚州→蘭州、四寶→四喜 |
| Furen-std | 是 | 67% | 67% | 53% | 39 s | |
| gemma-4-31b | 是 | 67% | 67% | 53% | 49 s | |
| ministral-8b | 是 | 40% | 40% | 33% | 20 s | |
| ministral-3b | 是 | 13% | 13% | 13% | 6.6 s | |
| mistral-ocr-latest | 否 | 0% | 0% | 0% | 1.6 s | 整頁重複「香港中環大學」 |
| Nkust | 否 | 0% | 0% | 0% | 4.6 s | 拒答 |

**四海豆漿大王（hard，直書）**

| 模型 | JSON | 品名 | 價格 | JSON品名 | 延遲 | 備註 |
|---|---|---:|---:|---:|---:|---|
| gemini-3.1-flash-lite | 是 | 100% | 75% | 100% | 7.0 s | 價格欄較弱（直書對不齊） |
| Furen-std | 是 | 50% | 38% | 50% | 60 s | 店名對；大量錯字／錯價 |
| gemma-4-31b | 是 | 38% | 25% | 38% | 56 s | |
| ministral-8b / 3b / OCR | 否/弱 | 0% | 0% | 0% | — | 直書幾乎全滅 |
| Nkust | 否 | 0% | 0% | 0% | 0.3 s | 拒答 |

### 5.3 質性對照

- **Gemini 3.1 Flash Lite** 在三商巧福連旁邊的台新卡回饋、麵條可選白麵／細麵都寫進 `notes`。入庫前仍要人工核對近音錯字。
- **Gemini 3 Flash Preview** 看得到內容（原文召回 70%），輸出常在 JSON 中段截斷，`json.loads` 失敗。不能當入庫端。
- **iAI Furen-std / gemma-4-31b** 簡單與表格接近 Gemini；直書與反光掉一截，且 30–60 s，不適合作 Discord 當下回。
- **iAI omni** 會看圖，可見輸出是英文 CoT，JSON 欄幾乎為 0。與 9/16 對話對照同一病灶。
- **Nkust** 四張都是「此問題不在本服務提供的範圍」。第二日就建議不要當聊天預設；視覺同樣不能用。
- **ministral-3b** 第一日的診斷仍成立。優惠套餐 JSON 合法，品名變成「紅茶雞塊+雞嚙」「紅茶肉肉+雞蛋堡」。幻覺 16 為本輪最高。
- **Mistral OCR** 對大字招牌與黃底表格是最好的「純辨識」（1 s、品名價格 100%），但**不吐 JSON**；店頭照片會崩潰成重複幻覺句。產品路徑應是 OCR → 再交給語言模型結構化，且只用於印刷清楚的圖。

---

## 6. 分析

**看不看得见图，與能不能入庫，是兩件事。** 探針把 Nkust、omni、ministral-3b 都算「有視覺」。只有 Flash Lite 與（退而求其次）Furen-std／gemma 同時通過 JSON 與錨點。

**免費層目錄不能當能力清單。** Gemini 2.5 對新帳號 404；3.6-flash 有視覺但今日日額在探針就打滿，沒測到抽取。Mistral small 從 9/15 起持續 429，今天仍是。iAI `nvidia-ultra-550b` 仍 400。

**同尺寸別名不必重測。** 8b-latest ≈ 8b-2512。OCR-4 / 4-0 / 4-1 / latest 在核心四張上也是同一條線（易圖 100%、難圖 0%）。

**直書是現階段最大的產品風險。** 四海豆漿只有 Flash Lite 的品名召回還能看；Mistral 全家 0%。若使用者拍的是傳統早餐店牆面，不能假設「有視覺的模型」都能用。

**iAI 已能看圖，`supports_vision=False` 過時。** 應改成模型屬性：std／gemma／omni 能；coder／large／max／120b／550b 不能。Router 預設對話模型仍不該自動接圖。

---

## 7. 限制

- 錨點召回是下限，不是菜單覆蓋率。
- 蘭州 `gold_complete=true` 漏了菜單上確實有的「牛肚切盤」「牛筋切盤」，Gemini 幻覺 +2 是標註錯誤，不是模型編造。
- 垂直中文、反光的人類標註本身有誤差。
- 紅 16×16 探針會低估「拒小圖」的模型（Groq Qwen 3.8 要 ≥32 px，見 groq-eval）。
- Gemini 未跑完的 ID＝配額，不是能力失敗。
- extended 14 張有部分抽取（Gemini 3-flash-preview、Furen-std、gemma、Nkust 等）但未完整、未重算總表，**不以擴充集下結論**。
- 本輪把 7 個 OCR 別名與 6 個 ministral 別名都打了核心四張，耗時約 21 分鐘，對結論沒有增量。以後只打 `*-latest`。

---

## 8. 建議

1. **菜單入庫主路徑：`gemini-3.1-flash-lite`。** 不要用 3-flash-preview（截斷）、不要用 lab 預設 3.6-flash 當「唯一視覺」除非日額還在。
2. **校內備援：`Furen-std` 或 `gemma-4-31b`。** 預期 30 s 級延遲。`Nkust`、`Furen-omni` 不要接菜單。
3. **Mistral：** 聊天 ministral 不當入庫來源。印刷清楚的圖可走 `mistral-ocr-latest`，再由另一模型轉 JSON。small/medium 當視覺不存在。
4. **`config.py`：** iAI 視覺改為按模型；Groq 維持預設 `supports_vision=False`，Qwen 3.8 另開通道。
5. **探針：** 紅塊至少 32×32；OCR 端點不要用顏色題當通過條件。
6. **重跑：** `python -m llmclab vision-menu --phase core` 只帶  
   `gemini-3.1-flash-lite`、`Furen-std`、`gemma-4-31b`、`ministral-8b-latest`、`mistral-ocr-latest`。

### 重跑指令

```bash
cd llm-capability-lab
python -m pytest -q tests/test_vision_menu.py
python -m llmclab vision-menu --phase catalog -p gemini mistral iai
python -m llmclab vision-menu --phase probe --run-dir docs/vision-menu/runs/<id>
python -m llmclab vision-menu --phase core --run-dir docs/vision-menu/runs/<id>
```

原始探針與每張圖 JSON：`docs/vision-menu/runs/vision-20260918-130204/`。
