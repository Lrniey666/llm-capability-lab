<div align="center">
  <a href="../README.md">← 回到專案首頁</a> ·
  <a href="README.en.md">English (UK)</a>
</div>

# 文件索引

## 開始使用

| 文件 | 內容 |
|---|---|
| [`../README.md`](../README.md) | 專案首頁：功能、安裝、快速入門 |
| [`README.en.md`](README.en.md) | English (UK) front page |
| [`http-api.md`](http-api.md) | HTTP 端點：請求、回應、錯誤碼、部署 |
| [`architecture.md`](architecture.md) | 分層、設計取捨、擴充方式 |
| [`findings.md`](findings.md) | 型錄能力與視覺抽取評測結論 |

## 研究

| 文件 | 內容 |
|---|---|
| [`vision-menu/protocol.md`](vision-menu/protocol.md) | **實驗協議**：研究問題、刺激集、自變項／依變項、程序 |
| [`vision-menu/最新報告.md`](vision-menu/最新報告.md) | 最新一輪的完整結果 |
| [`vision-menu/gold.json`](vision-menu/gold.json) | 黃金標註集：品名與價格錨點 |
| [`vision-menu/groq-eval.md`](vision-menu/groq-eval.md) | Groq 為何排除在視覺實驗之外 |
| [`vision-menu/gemini-mistral-iai-eval.md`](vision-menu/gemini-mistral-iai-eval.md) | 三家視覺能力的逐模型評估 |
| [`實驗報告.md`](實驗報告.md) | 早期的免費層能力與配額實驗 |
| [`vision-menu/runs/`](vision-menu/runs/) | 存檔的實驗執行：`meta` / `probe` / `scores` / `extracts` / `report` |

> 存檔的 run 是當時的實驗紀錄，內容不回頭修改——包含其中提到的舊專案名稱。

## 貢獻

| 文件 | 內容 |
|---|---|
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | 開發流程、測試要求、新增 provider 的方式 |
| [`CONTRIBUTING.en.md`](CONTRIBUTING.en.md) | English version |
| [`../CHANGELOG.md`](../CHANGELOG.md) | 版本紀錄 |

## 名詞

| 詞 | 意思 |
|---|---|
| **Chat Completions** | 雲端供應商的聊天 HTTP：`POST /v1/chat/completions`。換一家等於換 `base_url`、金鑰、模型 ID |
| **`ChatCompletionsClient`** | 本專案的 Chat Completions 用戶端（`make_client()` 回這個類） |
| **`openai`（PyPI）** | 傳輸依賴，不是本專案要上架的套件，也不是 OpenAI 公司的帳號 |
| **OpenAPI Specification（OAS）** | HTTP 服務在 `/docs`、`/openapi.json` 露出的機器可讀 API 規格。**不是** Chat Completions，也**不是** OpenAI 公司 |
| **探針（probe）** | 送一張 16×16 純紅 PNG 問「這是什麼顏色」，用來判斷模型到底吃不吃圖 |
| **`accept_wrong`** | 收了圖、沒報錯，但答錯——本專案最關心的失敗模式 |
| **錨點（anchor）** | gold 裡標好的高信心品名／價格，評分只比對這些，不要求全量轉錄 |
| **`gold_complete`** | 該圖的標註是否完整。只有完整時，多出來的品項才計為幻覺 |
| **金鑰槽（key slot）** | 同一家可填 `KEY` / `KEY2` / `KEY3`⋯，轉移時依序用 |
| **工作區（workspace）** | 研究產物的輸出根目錄，用 `LLMCLAB_WORKSPACE` 覆寫 |
