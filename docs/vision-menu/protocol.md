# 菜單圖視覺辨識實驗協議

日期：2026-09-18  
刺激：repo 根目錄 `menu_example/`  
金鑰：不寫入本文件。

## 研究問題

1. Gemini / Mistral / iAI **模型目錄裡每一個 ID**，走 Chat Completions（`POST /v1/chat/completions`；`mistral-ocr-*` 則走 `/v1/ocr`）時，能不能接受影像？（Groq 預設排除，另見 [groq-eval.md](groq-eval.md)）
2. 能接受影像的模型，在真實台灣菜單照片上，品名與價格抽取能不能達到「可進點餐系統」的程度？
3. 「JSON 解析成功」與「OCR 誠實」是否分離？先前 `ministral-3b` 會吐可解析但內容全猜的 JSON。

評分是規則比對，不用另一個 LLM 當裁判。

## 刺激集

`docs/vision-menu/gold.json`。19 個檔案裡 1 張高解析 PNG 與對應 JPG 重複，實驗略過 PNG。

| 層 | 圖 | 難度 | 佈局 | 完整 gold |
|---|---|---|---|---|
| core | 優惠套餐 1–5 號 | easy | 大字手寫價 | 是 |
| core | 蘭州拉麵點菜單 | medium | 表格點菜單 | 是 |
| core | 三商巧福店頭照 | hard | 反光、多面板 | 否 |
| core | 四海豆漿大王 | hard | 直書價目表 | 否 |
| extended | 其餘 14 張 | easy–hard | 紙本、雙語、App、社群截圖 | 部分 |

錨點是高信心品名／價格，不是全量轉錄。`gold_complete=true` 的圖才把多出來的品項算幻覺。

## 自變項／依變項

- 自變項：provider × model × 圖片
- 控制：同一 prompt、temperature=0、圖不預先 OCR、序列送出
- 依變項：
  - 探針：`accept_correct` / `accept_wrong` / `accept_empty` / `reject` / `quota` / `error`
  - 抽取：JSON 可解析、schema、店名命中、品名召回、價格召回（JSON 欄 vs 原文）、延遲、幻覺數

## 程序

```
catalog  GET /v1/models（每家一次）
probe    16×16 紅 PNG × 每一個 chat 模型
core     探針通過者 × 4 張核心圖
extended 探針通過者 × 其餘圖
         Gemini 擴充集預設只跑 1 個模型（免費層約 20 RPD）
```

斷點續跑：已寫入 `docs/vision-menu/runs/<id>/extracts/` 的檔案不會重打。

探針順序：名稱含 flash / pro / pixtral / vision / lite / small / ocr 的先打。  
Gemini 免費層約 20 RPD，探針預設最多 8 個 chat 模型（其餘標 `deferred_quota_cap`），把日額留給 core 抽取。  
非 chat（embed / ASR / TTS / 繪圖 / rerank / imagen / veo / voxtral / live）標成 `skipped_wrong_endpoint`。  
`mistral-ocr-*` 走 `/v1/ocr`，不是 chat.completions。

## 配額

| Provider | 間隔 | 已知瓶頸 |
|---|---|---|
| Gemini | 13 s | 約 5 RPM / 20 RPD，KEY2/KEY3 共桶 |
| Mistral | 1.3 s | ~1 req/s，月額較大 |
| iAI | 1.2 s | Hub 未必回 ratelimit header |
| Groq | 未列入本協議預設 | 2026-09-18 另測：視覺只 `qwen/qwen3.8-27b`；16×16 探針 400（需 ≥32 px）；免費層 OTPM ≈ 1000。全文 [groq-eval.md](groq-eval.md) |

撞 429 時該 provider 本輪其餘模型標 `quota`，不是能力失敗。

## 指令

```bash
cd llm-capability-lab
python -m llmclab vision-menu --phase catalog
python -m llmclab vision-menu --phase probe --run-dir docs/vision-menu/runs/<id>
python -m llmclab vision-menu --phase core --run-dir docs/vision-menu/runs/<id>
python -m llmclab vision-menu --phase extended --run-dir docs/vision-menu/runs/<id>
```

一次跑完（可中斷後帶 `--run-dir` 續）：

```bash
python -m llmclab vision-menu
```

## 產出

全文：[gemini-mistral-iai-eval.md](gemini-mistral-iai-eval.md)  
匯總：[../實驗報告.md](../實驗報告.md) 第三日乙  
原始 JSON：`runs/vision-20260918-130204/`


- 錨點召回是下限，不是菜單覆蓋率。
- 直書、反光、社群截圖的人類標註本身有誤差。
- 紅正方形探針可能低估「只吃大圖」的模型（`accept_empty` 仍會進菜單抽取）。
- Gemini 未跑完 = 配額，不能解釋成該模型沒有視覺。
- Groq Qwen 3.8 拒 16×16 紅塊（每邊至少 32 像素）。現有探針會把唯一能看圖的 Groq 模型標成 `reject`。
