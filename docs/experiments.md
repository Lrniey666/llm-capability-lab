# 免費層 API 實驗紀錄

日期：2026-09-15  
環境：Python 3.14.3、`openai` 3.14.0  
指令：`python -m llmclab keys|check|models|ask`

金鑰本身不寫進這份文件。`.env` 已在 `.gitignore`。

完整整理見 [實驗報告.md](實驗報告.md)（2026-09-15 能力與保底；2026-09-16 iAI 與 compare；2026-09-18 Groq 視覺與 Gemini／Mistral／iAI 菜單全目錄）。

---

## 1. 預設模型已過期

第一次 `check` 用套件內建 ID，三家金鑰都通（`GET /v1/models` 成功），但聊天端點失敗：

| Provider | 當時預設模型 | 結果 |
|---|---|---|
| Groq | `llama-3.1-8b-instant` | 404，模型已下架 |
| Gemini | `gemini-2.5-flash` | 404，新帳號不可用 |
| Mistral | `mistral-small-latest` | 429，免費層 small 額度打滿 |

當時從 API 撈到的可用聊天模型（節錄）：

- Groq：`openai/gpt-oss-20b`、`groq/compound-mini`、`qwen/qwen3.6-27b`
- Gemini：`gemini-3.6-flash`、`gemini-flash-latest`、`gemini-3.1-flash-lite`
- Mistral：`ministral-3b-latest` 可用；`mistral-small-latest` 持續 429

已把 `llmclab/config.py` 預設改成：

| Provider | 新預設 |
|---|---|
| Groq | `openai/gpt-oss-20b` |
| Gemini | `gemini-3.6-flash` |
| Mistral | `ministral-3b-latest` |

---

## 2. 改模型後的 `check`

| 項目 | Groq `openai/gpt-oss-20b` | Gemini `gemini-3.6-flash` | Mistral `ministral-3b-latest` |
|---|---|---|---|
| 連通 | 過（回覆常是空字串） | 過（回覆常是空字串） | 過（「謝謝！」） |
| 模型清單 | 14 個 | 56 個 | 46 個 |
| 串流 | 過，TTFT ~0.7–1.8 s | 過，TTFT ~2–5 s | 過，TTFT ~0.4–0.5 s |
| JSON 模式 | 失敗（JSON 驗證不過） | 失敗（字串不完整） | 過 |
| 視覺 | 略過（不支援） | 失敗（空字串） | 過（正確回紅色） |

連通回空字串的原因：`check_ping` 的 `max_tokens=16`，推理模型把額度用在思考過程，可見輸出被截斷。改用 `ask`（較高 token 上限）就有完整句子。

### `ask`「用一句話介紹高雄」

| Provider / 模型 | 延遲 | 結果 |
|---|---|---|
| Groq `openai/gpt-oss-20b` | ~1.4 s | 正常中文 |
| Groq `groq/compound-mini` | ~2.7 s | 正常中文 |
| Gemini `gemini-3.6-flash` | ~13 s | 正常中文 |
| Mistral `mistral-small-latest` | — | 429 |
| Mistral `ministral-3b-latest` | ~1.1 s | 正常中文 |

### 當日配額 header

- Groq `gpt-oss-20b`：`req ~998/1000`，`tok ~7906/8000`（TPM 很緊）
- Groq `compound-mini`：`req 249/250`，`tok 67040/70000`
- Gemini：沒回傳配額 header
- Mistral `ministral-3b`：`tok ~1299984/1300000`

---

## 3. 多金鑰輪替架構

`.env.example` 本來就預留 `KEY` / `KEY2` / `KEY3`，但舊程式只讀第一把。
免費層常見失敗是單一把 429 或 401，需要在**有限呼叫次數**內換下一把，而不是無限重試。

### 嘗試順序

```
groq/KEY  → groq/KEY2 → groq/KEY3
        → gemini/KEY → gemini/KEY2 → gemini/KEY3
        → mistral/KEY → …
```

可再往後加 `KEY4`…`KEY9`，有填才會納入。

### 何時換鑰匙、何時換下一家

| 錯誤 | 行為 |
|---|---|
| 429 / 5xx / timeout | 同一把依 `Retry-After` 重試；次數用完換下一把（換鑰匙不等待） |
| 401 / 403 | 這把無效，立刻換下一把 |
| 400 | 請求本身有問題，跳過這家剩下的金鑰，換下一家 |
| 沒填的槽 | 自動略過 |

次數上限：

- `retries_per_key`（CLI `--retries`，預設 1）：同一把遇暫時性錯誤再試幾次
- `max_attempts_per_provider`（CLI `--max-attempts`）：這家最多打幾次就換下一家  
  未指定時 = 已填金鑰數 × (`retries_per_key` + 1)

三家各 3 把、每把重試 1 次時，最壞會打 3 × 3 × 2 = 18 次；用 `--max-attempts 3` 可把每家壓在 3 次。

### 誰會走這條路

- `python -m llmclab ask …`：單一 provider，失敗換同一家下一把
- `python -m llmclab fallback …`：金鑰輪替 + 跨 provider
- `Router(...)`：函式庫與 Discord 範例同一套
- `check` / `bench`：診斷用，固定第一把，避免一次測把備用額度打光

### 實作位置

- `llmclab/config.py`：`KeySlot`、`slot_env_names()`、`Provider.key_slots()`
- `llmclab/client.py`：`Router` 依槽位輪替；`ChatResult.key_env` / `Attempt.key_env` 記下用了哪一把
- `python -m llmclab keys`：列出每家 KEY / KEY2 / KEY3 是否已填

### 限制

同一 Google / Groq / Mistral **組織或專案**下的多把 key，配額通常是共用的。
`KEY2` 要能救命，最好是另一個帳號；否則 429 換鑰匙多半還是 429，真正接住請求的是下一家 provider。
401 失效的單一把 key，換備用鑰匙仍然有用。

---

## 4. 多金鑰輪替實機實驗（2026-09-15）

指令：`python scripts/key_rotate_experiment.py`  
條件：`.env` 九槽都有值；過程只印遮罩，不寫金鑰。聊天一律 `max_tokens=16`。

### A. 九槽連通（`GET /v1/models`）

九把都過。模型數 Groq 14、Gemini 56、Mistral 46，與先前 `llmclab models` 一致。金鑰本身有效。

### B. 401 → 換同一家下一把

把行程內的 `GROQ_API_KEY` 改成無效值（不改 `.env`），`Router(["groq"], retries_per_key=0)`：

```
✗ groq/GROQ_API_KEY   401 Invalid API Key
✓ groq/GROQ_API_KEY2  408 ms
```

第一把沒有重試、沒有等待，立刻改打 KEY2。輪替路徑正確。

### C. 404/400 → 跳過同家剩餘金鑰

Groq 指定不存在的模型 `this-model-does-not-exist`，`retries_per_key=0`：

```
✗ groq/GROQ_API_KEY     404（模型不存在）
✓ gemini/GEMINI_API_KEY 4289 ms
```

沒有再打 `GROQ_API_KEY2` / `KEY3`（換鑰匙也會 404），直接換下一家。路徑正確。

### D. 正常 fallback

`Router(["groq","gemini","mistral"], retries_per_key=0, max_attempts_per_provider=3)`：

```
✓ groq/GROQ_API_KEY  339 ms
配額：req 993/1000  tok 7906/8000  reset 10m4.8s
```

第一把就成功，沒有動到備用鑰匙或下一家。

### E. 同家三把各打一次聊天（看配額是否共用）

| Provider | KEY | KEY2 | KEY3 | 配額觀察 |
|---|---|---|---|---|
| Groq | ✓ 308 ms | ✓ 1.7 s | ✓ 2.9 s | `req` 992→991→990，三把共一個請求桶 |
| Gemini | ✓ 4.6 s | ✗ 429 | ✗ 429 | 第一把過了，另外兩把立刻 quota exceeded |
| Mistral | ✓ 644 ms「确认。」 | ✓ 428 ms | ✓ 413 ms | `tok` 1299940→1299925→1299910，三把共一個 token 桶 |

結論：這組 `.env` 裡，**同一家的 KEY / KEY2 / KEY3 配額是綁在一起的**（同一組織或專案）。  
401 換鑰匙有用（實驗 B）。429 換同一家下一把多半還是 429（實驗 E 的 Gemini）；要撐住免費層，真正的備援是換下一家 provider，不是同帳號多開 key。

### 這次沒測到的

- 真 429 後同一把的 `Retry-After` 退避（避免把剩餘 TPM 打光）
- `--max-attempts` 在三把都 429 時提前改換下一家（離線測試已覆蓋）

---

## 5. 本機 Qwen3.5-4B 保底

日期：2026-09-15

雲端三家（含同專案多把 key）仍可能同時 429。本機模型是獨立故障域：不吃 Groq TPM、Gemini 日額、Mistral 1 req/s。

### 架構

```
groq/KEY… → gemini/KEY… → mistral/KEY… → local/Qwen3.5-4B
```

- provider key：`local`
- 預設端點：`http://127.0.0.1:11434/v1`（本機路徑會轉成 Ollama 官方 `/api/chat`）
- 預設模型：`qwen3.5:4b`（可用 `LOCAL_MODEL` 覆寫）
- **opt-in**：`.env` 填了 `LOCAL_BASE_URL` 或 `LOCAL_API_KEY` 才納入 Router；沒填就跳過
- 不需要真金鑰：只有網址時用佔位字串 `ollama`
- 本機 timeout 180 秒；請求帶 `think: false`，避免思考過程吃掉短回覆
- Qwen3.5-4B 有視覺，`check` 的視覺項不會略過

啟用後：

```bash
ollama pull qwen3.5:4b
python -m llmclab keys
python -m llmclab check -p local
python -m llmclab fallback "用一句話介紹高雄"
```

離線測試已覆蓋「三家 429 → local 接手」。實機延遲與繁中品質要本機 Ollama 起來後再記。

---

## 6. 多用戶模擬（含本機 Qwen 保底）

日期：2026-09-15  
指令：`python scripts/sim_multiuser_bot.py`  
條件：20 分鐘、冷卻 10s、思考平均 35s、seed=42。配額用當日實測（Groq TPM 8000、Gemini 5 RPM / 20 RPD、Mistral 1 req/s）。本機無雲端配額、延遲假設 8s、**不模擬 GPU 排隊**。

### 5 人 · 139 則（7.0/min）

Groq 獨力 100%。本機 0 次上場。Gemini 獨力只有 20 則（撞日額）。

### 15 人 · 390 則（19.5/min）

| 架構 | 成功 | 429 浪費 | p95 | 接手 |
|---|---|---|---|---|
| 只要 Groq 1 key | 88.2% (344/390) | 46 | 0.8s | groq 344 |
| Groq 同專案 3 key | 89.2% (348/390) | 325 | 1.3s | groq 348 |
| 三家各 1 key | 98.5% (384/390) | 78 | 1.2s | groq 344 · gem 20 · mis 20 |
| 現況 3×3 共桶 retries=0 | 99.2% (387/390) | 239 | 2.7s | groq 344 · gem 20 · mis 23 |
| 9 把獨立帳號 | 100% | 46 | 1.1s | groq 390 |
| 三家 + 本機 Qwen | **100%** (390/390) | 78 | 5.2s | groq 344 · gem 20 · mis 20 · **local 6** |
| 現況 3×3 + 本機 | **100%** | 239 | 5.8s | groq 344 · gem 20 · mis 23 · **local 3** |

### 30 人 · 791 則（39.5/min）

| 架構 | 成功 | 429 浪費 | p95 | 接手 |
|---|---|---|---|---|
| 只要 Groq 1 key | 48.5% (384/791) | 407 | 0.8s | groq 384 |
| Groq 同專案 3 key | 49.4% (391/791) | 2786 | 2.0s | groq 391 |
| 三家各 1 key | 82.7% (654/791) | 931 | 1.2s | groq 384 · gem 20 · mis 250 |
| 現況 3×3 共桶 retries=1 | 95.2% (753/791) | 5704 | 4.7s | groq 391 · gem 20 · mis 342 |
| 現況 3×3 共桶 retries=0 | 88.5% (700/791) | 2807 | 2.7s | groq 387 · gem 20 · mis 293 |
| 9 把獨立帳號 | 100% | 480 | 1.1s | groq 791 |
| 三家 + 本機 Qwen | **100%** (791/791) | 931 | 8.8s | groq 384 · gem 20 · mis 250 · **local 137** |
| 現況 3×3 + 本機 | **100%** | 2807 | 10.2s | groq 387 · gem 20 · mis 293 · **local 91** |

### 結論

- 5 人 Groq 就夠；本機保底此時沒差。
- 15 人開始撞 Groq TPM。換雲端下一家能抬到約 98–99%；本機把剩下幾則補成 100%，p95 從約 1s 升到約 5s。
- 30 人時，同專案多 key **幾乎不提高成功率**（49.4% vs 48.5%），只是多打 429。真正拉開差距的是換 provider。
- 同專案 3×3 + 重試 1 次：成功率 95.2%，但浪費 5704 次 429，不划算。
- 本機 Qwen 是在「共桶、沒有 9 個獨立帳號」時，把 30 人打到 100% 的那條路；代價是 p95 8–10s，且模擬沒算本機排隊，實機 CPU 上 137 則／20 分鐘可能更慢。
- 若真有 9 個獨立 Groq 帳號，不必靠本機也能 100%，而且 p95 仍約 1.3s。

---

## 2026-09-18 Groq 視覺補測

整理報告：[vision-menu/groq-eval.md](vision-menu/groq-eval.md)  
原始 JSON：[vision-menu/runs/groq-20260918-131400/](vision-menu/runs/groq-20260918-131400/)

- `GET /v1/models`：13 個 ID。視覺只有 `qwen/qwen3.8-27b`。文件上的 `qwen/qwen3.6-27b`、Llama 4 Scout/Maverick 此帳號沒有。
- 16×16 紅 PNG：Qwen 3.8 → 400「至少 32 像素」；gpt-oss-20b → 400「content 必須是字串」。
- 優惠套餐 1–5：JSON 品名／價格 100%，2.69 s，in=1020 out=644，幻覺 0。
- 三商巧福：品名 67%、價格 60%，12.02 s，out=1729。
- 隨後 OTPM 1000：四海／蘭州先 429，等約 60 s 後 `max_tokens=800` 重打被截斷。模型有在讀圖（四海豆漿大王、蘭州金牌牛三寶麵 180）。
- `reasoning_effort=none` 不能套回 gpt-oss（只接受 low/medium/high）。

同日 Gemini/Mistral/iAI 菜單全掃：`vision-menu --phase …`，run `vision-20260918-130204`。Groq 不在那次預設清單裡。

