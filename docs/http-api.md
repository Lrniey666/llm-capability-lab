<p align="center">
  <a href="../README.md">← 專案首頁</a> ·
  <a href="README.md">文件索引</a>
</p>

# HTTP API 參考

`llmclab.service` 把 `Router` 包成 HTTP 服務，讓 TypeScript、Go 或任何語言的專案
共用同一套故障轉移策略，而不必各自重寫。

> **`/v1/chat` 只做翻譯。** 轉移、重試、配額解析全都留在 `Router`。
> `/v1/menu` 例外：依 `supports_vision` 逐家抽取，不走 `Router`。
> `service.py` 約 246 行。

---

## 啟動

```bash
pip install "llm-capability-lab[serve]"

# 產一把 token
export LLMCLAB_API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

llmclab serve --host 127.0.0.1 --port 8000
```

| 參數 | 預設 | 說明 |
|---|---|---|
| `--host` | `127.0.0.1` | **預設只綁本機。** 要對外必須明確寫 `0.0.0.0` |
| `--port` | `8000` | |
| `--reload` | 關閉 | 開發用自動重載 |

啟動後 `/docs` 是 [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
（OAS）互動文件，`/openapi.json` 是機器可讀的同一份規格。
這是**本服務自己的 HTTP 契約**，與雲端供應商的 Chat Completions、與 OpenAI 公司無關。
用語見 [文件索引](README.md#名詞)。

### 授權

| 環境變數 | 說明 |
|---|---|
| `LLMCLAB_API_TOKEN` | Bearer token。**未設定就拒絕啟動** |
| `LLMCLAB_ALLOW_ANONYMOUS` | 設為 `1` 才允許匿名，只給本機測試用 |

這個服務背後是有配額、甚至要付費的金鑰。開成匿名等於把自己的額度送給整個網路，
所以預設是「沒有 token 就不啟動」，而不是「沒有 token 就不檢查」。

```
$ llmclab serve
無法啟動：未設定 LLMCLAB_API_TOKEN。這個服務會用掉你的 API 配額，不該匿名對外開放。
```

---

## 端點

### `GET /healthz`

Liveness。**不需要 token**，也不透露任何金鑰內容。

```json
{ "status": "ok", "providers_ready": ["groq", "gemini", "local"] }
```

`status` 在沒有任何 provider 設定金鑰時會是 `no_provider_configured`。
適合直接餵給 Docker healthcheck 或 Kubernetes probe。

---

### `GET /v1/providers`

目前的路由設定與各家狀態。需要 token。

```json
{
  "order": ["groq", "gemini", "mistral", "iai", "local"],
  "vision_order": ["gemini", "mistral", "local"],
  "providers": [
    {
      "key": "groq",
      "label": "Groq",
      "model": "openai/gpt-oss-20b",
      "configured": true,
      "keys_loaded": 3,
      "supports_vision": false,
      "is_local": false
    }
  ]
}
```

`keys_loaded` 只給數量，不給內容。`vision_order` 由 `supports_vision` 推導，
不是另一份手寫清單。

---

### `POST /v1/chat`

走完整的轉移鏈送一次對話請求。需要 token。

**請求**

```jsonc
{
  "prompt": "用一句話解釋 RAG",        // 與 messages 二選一
  "system": "簡潔回答",                 // 選用，搭配 prompt
  "messages": [                          // 或直接給完整對話
    { "role": "user", "content": "你好" }
  ],
  "order": ["groq", "gemini"],          // 選用，覆寫嘗試順序
  "model_overrides": { "groq": "llama-3.3-70b-versatile" },
  "max_tokens": 500,
  "temperature": 0,
  "timeout": 60,
  "retries_per_key": 1
}
```

`prompt` 與 `messages` 至少要給一個，否則回 `422`。

**回應 `200`**

```json
{
  "text": "RAG 先檢索相關文件，再讓模型根據這些文件作答。",
  "provider": "groq",
  "model": "openai/gpt-oss-20b",
  "latency_s": 0.8421,
  "ttft_s": null,
  "prompt_tokens": 24,
  "completion_tokens": 31,
  "tokens_per_s": 36.81,
  "key_env": "GROQ_API_KEY",
  "rate_limit": "req 14399/14400  tok 5987/6000  reset 2m30s",
  "attempts": [
    { "provider": "groq", "model": "openai/gpt-oss-20b", "ok": true, "key_env": "GROQ_API_KEY" }
  ]
}
```

`attempts` 是完整的嘗試紀錄——包含失敗後換掉的那幾把。`rate_limit` 來自 response
header，某一家沒回傳時會是「這家沒回傳配額 header」。

**回應 `503`**（全部 provider 都失敗）

```json
{
  "detail": {
    "error": "all_providers_failed",
    "attempts": [
      { "provider": "groq", "ok": false, "status": 429, "error": "Rate limit reached", "key_env": "GROQ_API_KEY" },
      { "provider": "gemini", "ok": false, "status": 401, "error": "API key not valid", "key_env": "GEMINI_API_KEY" }
    ]
  }
}
```

失敗時把每一次嘗試都回報出去，否則呼叫端無從判斷是配額問題還是金鑰問題。

---

### `POST /v1/menu`

菜單照片 → 結構化 JSON。`multipart/form-data`，需要 token。

| 欄位 | 必填 | 說明 |
|---|:---:|---|
| `image` | ✓ | 圖片檔，上限 8 MB |
| `provider` | | 指定一家；省略則依 `vision_order` 逐家嘗試 |
| `model` | | 指定模型；省略則用該家的預設 |

```bash
curl -X POST http://127.0.0.1:8000/v1/menu \
  -H "Authorization: Bearer $LLMCLAB_API_TOKEN" \
  -F image=@menu.jpg
```

**回應 `200`**

```jsonc
{
  "provider": "gemini",
  "model": "gemini-3.6-flash",
  "ok": true,
  "parsed": {                       // 解析後的結構
    "title": "蘭州拉麵",
    "currency": "TWD",
    "categories": [
      { "name": "麵食", "items": [ { "name": "牛肉麵", "price": 130, "unit": "碗", "note": "" } ] }
    ]
  },
  "parse_error": null,              // 解析失敗時的原因
  "text": "{ ... }",                // 模型的原始輸出
  "latency_s": 4.12,
  "endpoint": "chat",               // chat 或 ocr
  "attempts": [ { "provider": "gemini", "ok": true, "parse_error": null } ]
}
```

> **`ok` 與 `parsed` 是兩回事。** `ok: true` 只代表 API 呼叫成功；
> 內容能不能用要看 `parsed` 是否為 `null`、以及 `parse_error`。
> 這正是本專案量出「224 次呼叫、218 次成功、只有 99 次可解析」的那個區別
> （核心四張跑完；擴充 14 張只跑到一部分）。

**其他狀態碼**

| 碼 | 情況 |
|---|---|
| `401` | 缺少或錯誤的 Bearer token |
| `413` | 檔案超過 8 MB |
| `422` | 檔案是空的，或 `/v1/chat` 沒給 `prompt` 也沒給 `messages` |
| `503` | 所有嘗試過的 provider 都沒吐出可解析的 JSON（`detail.attempts` 有明細） |

---

## 從 TypeScript 呼叫

```ts
type ChatResponse = {
  text: string;
  provider: string;
  model: string;
  latency_s: number;
  rate_limit: string;
};

async function ask(prompt: string): Promise<ChatResponse> {
  const res = await fetch("http://127.0.0.1:8000/v1/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.LLMCLAB_API_TOKEN}`,
    },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(`llmclab ${res.status}: ${await res.text()}`);
  return res.json();
}
```

---

## 部署

```bash
docker build -t llm-capability-lab .
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e LLMCLAB_API_TOKEN=... \
  llm-capability-lab
```

映像檔只裝函式庫與服務層，不含 `menu_example/` 與 `docs/`——
研究資產不需要跟著上線。要在容器裡跑研究模組的話，把 repo 掛進去並設
`LLMCLAB_WORKSPACE`。

### 上線前

- **綁定位址**：`--host 0.0.0.0` 才會對外，預設只綁本機
- **反向代理**：TLS 與速率限制交給前面的 nginx／Caddy／Cloudflare，服務本身不做
- **token 輪替**：`LLMCLAB_API_TOKEN` 換掉就重啟，沒有持久化狀態
- **配額共用**：所有呼叫端共用同一批金鑰，`/v1/providers` 可以看剩餘量
