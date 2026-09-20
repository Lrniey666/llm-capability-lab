<p align="center">
  <a href="../README.md">← 專案首頁</a> ·
  <a href="README.md">文件索引</a>
</p>

# 架構

## 分層

```
┌──────────────────────────────────────────────────────────────┐
│  進入點                                                       │
│    llmclab.ask() / Router          cli.py            service.py │
│    （函式庫）                      （研究工作台）     （HTTP）   │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  策略層  client.Router                                        │
│    金鑰輪替 → 跨 provider 轉移 → 本機保底                      │
│    重試時機、退避秒數、何時放棄                                 │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  傳輸層  client.chat() / make_client()                        │
│    Chat Completions：PyPI `openai`，max_retries=0             │
│    本機 Ollama：官方 /api/chat                                 │
│    ratelimit.parse_headers() 正規化配額                        │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  設定層  config.PROVIDERS                                     │
│    單一註冊表：base_url、金鑰槽、預設模型、能力旗標              │
└──────────────────────────────────────────────────────────────┘
```

研究模組（`vision_menu`、`compare`、`bench`、`checks`）直接用傳輸層與設定層，
不經過 `Router`——實驗要的是「這一家這個模型的原始行為」，不是「幫我找一個能用的」。

---

## 四個設計取捨

### 1. 聊天轉移集中在 Router；菜單抽取另走一條

`/v1/chat` 與 CLI 的 `fallback` 不知道什麼是 429，也不知道退避要等多久——
它們只是把 `Router` 的結果翻成 JSON 或印出來。

`/v1/menu` 不走 `Router`。它依 `supports_vision` 逐家呼叫 `vision_menu.run_extract`，
第一個吐出可解析 JSON 的就回。這條路徑沒有金鑰輪替與 `Retry-After`。

好處是聊天轉移只有一份，函式庫與 `/v1/chat` 同時生效；壞處是 `Router` 承擔的責任
偏多（金鑰輪替 + provider 轉移 + 重試 + 退避），而菜單抽取是另一條路徑。
目前規模下這個取捨是划算的，但如果之後要加上熔斷（circuit breaker）或權重路由，
就該把重試策略抽成獨立物件。

### 2. `max_retries=0`，不讓用戶端在底下偷偷重試

雲端走 Chat Completions。公開類型是本專案的 `ChatCompletionsClient`
（`make_client()` 的回傳值）。HTTP 傳輸目前用 PyPI `openai`，並把
`max_retries=0`，避免它在 Router 底下偷偷重試。這與服務的 OpenAPI（OAS）無關。

```python
from llmclab import ChatCompletionsClient
ChatCompletionsClient(api_key=key, base_url=..., timeout=timeout, max_retries=0)
```

若放著讓傳輸層自己重試，`Router` 看到的「一次失敗」其實已經試了好幾次——
轉移時序、`Retry-After` 的遵守、以及配額計算全都會失真。
所以重試權完全收回到 `Router`。

本機 Ollama 不走 Chat Completions：官方 `/v1` 不會把 `think=false` 傳下去，
因此本機分支打 `/api/chat`。Mistral 的 OCR 模型另走 `/v1/ocr`。

### 3. 能力寫在設定裡，模型 ID 不寫死

```python
Provider(key="gemini", supports_vision=True, default_model="gemini-3.6-flash", ...)
```

`supports_vision` 是 provider 層級的旗標，`service.vision_order()` 直接由它推導，
不維護第二份「哪些模型能看圖」的清單。

模型 ID 則刻意只當預設值，因為它們改版很快——`llmclab models` 是跟 API 撈的，
`vision-menu` 的 `catalog` 階段也是。這個專案的整個出發點就是「不要相信型錄」，
所以更不該把型錄抄進原始碼。

### 4. 配額 header 模糊比對

各家的 header 名稱不一致（`x-ratelimit-remaining-requests`、`ratelimit-remaining`、
`retry-after`⋯），而且會改。寫死欄位名的話，某一家改版就整包讀不到配額。

`ratelimit.py` 先把所有含 `ratelimit` / `rate-limit` 的 header 收下來，
再用「包含哪些關鍵字」挑出 remaining／limit／reset。少一家、多一家都不會壞，
最差情況是 `summary()` 回「這家沒回傳配額 header」。
`parse_duration()` 另外處理 `6m11.52s`、`2.5s`、`45` 這幾種 reset 格式。

---

## 內建供應商

預設模型 ID 寫在 `config.py`，型錄會改版——用 `llmclab models` 跟 API 撈最準。
某把金鑰看得到哪些 ID，依方案與時間而變，不要寫成「這個帳號永遠如此」。

| Provider | 預設模型 | 視覺 | 備註 |
|---|---|:---:|---|
| Groq | `openai/gpt-oss-20b` | ✗ | 預設模型拒圖；部分 Qwen ID 能看，見 [groq-eval](vision-menu/groq-eval.md) |
| Gemini (AI Studio) | `gemini-3.6-flash` | ✓ | 預設模型支援影像與長 context |
| Mistral (Experiment) | `ministral-3b-latest` | ✓ | 速率偏低（約 1 req/s），適合批次 |
| iAI | `Furen-large` | ✗ | 可選機構端點；預設對話模型拒圖 |
| Local (Ollama) | `qwen3.5:4b` | ✓ | 需設 `LOCAL_BASE_URL`；打官方 `/api/chat` |

同一家可以填 `KEY` / `KEY2` / `KEY3`（最多到 `KEY9`）。同一組織／專案下的多把金鑰，
配額通常共用，換鑰匙救不了 `429`。

---

## 轉移的實際順序

```
for provider in order:
    for key_slot in provider.keys:          # KEY → KEY2 → KEY3
        for attempt in range(retries + 1):
            try: return chat(...)
            except:
                429/5xx/timeout → 等 retry_delay() 後重試同一把
                401/403         → break，換下一把金鑰
                400             → break 整家，換下一個 provider
raise AllProvidersFailed(attempts)
```

`retry_delay()` 的優先序：provider 回的 `Retry-After` > `reset` header > 指數退避，
上限 60 秒。換金鑰不等待——換一把新的額度，等待沒有意義。

`max_attempts_per_provider` 可以額外設一個總預算，避免某一家有 9 把金鑰時
在它身上耗掉太久。

---

## 路徑與工作區

模組化最容易壞在這裡，所以分成三個概念：

| 名稱 | 意思 | 安裝後 |
|---|---|---|
| `PACKAGE_DIR` | `llmclab/` 本身 | site-packages 裡 |
| `PROJECT_ROOT` | 原始碼 checkout 的根 | 沒有意義 |
| `workspace_root()` | 研究產物的根 | 退回 CWD |

`load_env()` 從**呼叫端的 CWD 往上找** `.env`，而不是讀套件所在目錄——
被其他專案匯入時，金鑰在對方的專案裡。搜尋在遇到 `.git` 或 `pyproject.toml`
時停止，避免撈到家目錄或別的專案的金鑰。

研究模組用 `require_workspace()`：找不到 `menu_example/` 與 `docs/` 時直接報錯，
並告訴你設 `LLMCLAB_WORKSPACE`，而不是默默寫到錯的地方。

---

## 新增一家 provider

正常情況只要動一個地方：

```python
PROVIDERS["newco"] = Provider(
    key="newco",
    label="NewCo",
    base_url="https://api.newco.com/v1",
    env_var="NEWCO_API_KEY",
    default_model="newco-small",
    console_url="https://newco.com/keys",
    limits_url="https://newco.com/limits",
    supports_vision=False,
    note="給維護者看的備註：配額特性、雷區",
)
```

然後把 `"newco"` 加進 `CLOUD_ORDER`。函式庫、CLI、HTTP 服務、研究工具同時生效。

需要特殊處理時有這些鉤子：

| 欄位 | 用途 |
|---|---|
| `extra_body` | 每次請求都要帶的額外參數（如 `reasoning_effort`） |
| `base_url_env` / `model_env` | 允許用環境變數覆寫 |
| `timeout` | 這家特別慢時的專屬逾時 |
| `requires_key` / `placeholder_key` | 本機端點不需要真金鑰 |
| `max_key_slots` | 限制金鑰槽數量 |

**如果你發現要改三個以上的檔案，那是抽象漏了**，請開 issue 而不是繞過去。

---

## 測試策略

| 檔案 | 測什麼 | 怎麼測 |
|---|---|---|
| `test_offline.py` | 純邏輯：header 解析、退避、金鑰槽 | 直接呼叫 |
| `test_mock_server.py` | 傳輸層接線 | 本機 HTTP 伺服器 + 真 `openai` 套件 |
| `test_module_api.py` | 公開 API、路徑解析、async 契約 | 直接呼叫 + tmp_path |
| `test_vision_menu.py` | gold 標註完整性、評分規則 | 讀真實 gold.json |
| `test_service.py` | HTTP 路由、授權、上傳限制 | FastAPI TestClient + 本機 mock 端點 |

**82 項測試不連外網、不需供應商金鑰。** 「離線」指的是不打 Groq／Gemini 等真實 API；
`test_mock_server.py` 與 `test_service.py` 仍會在本機起 HTTP 伺服器，走真實的
`openai` 套件與 FastAPI 路由。用真伺服器而不是把用戶端整個 mock 掉，是因為
「配額 header 沒接到」「串流沒解析」這類錯誤只有實際走一次 HTTP 才會現形。
若改動讓測試必須有外網或金鑰才能過，設計多半走偏了。

async 的測試特別說明：`achat` 的契約是「不在 event loop 執行緒上跑阻塞呼叫」，
所以測試直接比對 `threading.get_ident()`。曾經用心跳計數來測，但那在 Windows 上
量到的是計時器解析度（約 15 ms），localhost 請求比它快，結果恆為 0。
