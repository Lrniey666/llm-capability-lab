# 菜單圖視覺辨識實驗報告

**Run：** `vision-20260918-130204`  
**刺激集：** `menu_example/`（gold v1）  
**標註：** human-visual-2026-09-18  
**產出時間：** 2026-09-18T06:34:46.817886+00:00

## 1. 問題

在真實台灣菜單照片上，Gemini / Mistral / iAI **目錄裡每一個模型**能不能看圖，
以及通過視覺探針的模型，品名／價格抽取能不能達到可入庫的程度。

評分是規則比對 gold 錨點，不是再用一個模型當裁判。
JSON 解析成功 ≠ OCR 正確；先前 `ministral-3b` 就會產出可解析但內容全猜的 JSON。

## 2. 目錄

| Provider | 模型數 | chat | 非對話／錯端點 |
|---|---:|---:|---:|
| gemini | 58 | 22 | 36 |
| mistral | 46 | 25 | 21 |
| iai | 17 | 10 | 7 |

## 3. 視覺探針（紅正方形）

| Provider | 模型 | 結果 | 延遲 | 細節 |
|---|---|---|---:|---|
| gemini | `models/gemini-2.5-flash` | reject | — | Error code: 404 - [{'error': {'code': 404, 'message': 'This  |
| gemini | `models/gemini-2.5-flash-lite` | reject | — | Error code: 404 - [{'error': {'code': 404, 'message': 'This  |
| gemini | `models/gemini-2.5-pro` | reject | — | Error code: 404 - [{'error': {'code': 404, 'message': 'This  |
| gemini | `models/gemini-3-flash-preview` | accept_correct | 2437 ms | 紅色 |
| gemini | `models/gemini-3.1-flash-lite` | accept_correct | 3193 ms | 紅色 |
| gemini | `models/gemini-3.1-flash-lite-preview` | accept_correct | 1728 ms | 紅色 |
| gemini | `models/gemini-3.1-pro-preview` | quota | — | Error code: 429 - [{'error': {'code': 429, 'message': 'You e |
| gemini | `models/gemini-3.1-pro-preview-customtools` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-3.5-flash` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-3.5-flash-lite` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-3.6-flash` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-3.7-flash` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-3.8-flash` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-flash-latest` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-flash-lite-latest` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-omni-1.1-flash` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-omni-flash-preview` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-pro-latest` | quota | — | 同家前序已 429，本輪不再打 |
| mistral | `magistral-medium-latest` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| gemini | `models/gemini-robotics-er-2-preview` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemini-robotics-er-2-streaming-preview` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemma-4-26b-a4b-it` | quota | — | 同家前序已 429，本輪不再打 |
| gemini | `models/gemma-4-31b-it` | quota | — | 同家前序已 429，本輪不再打 |
| iai | `Furen-coder` | reject | — | Error code: 400 - {'error': {'message': 'litellm.BadRequestE |
| iai | `Furen-large` | reject | — | Error code: 400 - {'error': {'message': 'litellm.BadRequestE |
| iai | `Furen-max` | reject | — | Error code: 400 - {'error': {'message': 'litellm.BadRequestE |
| iai | `Furen-omni` | accept_wrong | 537 ms | The user asks: "這張圖是什麼顏色？只回顏色名稱。" Means "What color is this |
| iai | `Furen-std` | accept_correct | 761 ms | 紅色 |
| iai | `gemma-4-31b` | accept_correct | 404 ms | 紅色 |
| iai | `nemotron-3-super-120b` | reject | — | Error code: 400 - {'error': {'message': 'litellm.BadRequestE |
| iai | `nemotron-omni-30b` | accept_wrong | 527 ms | The user asks: "這張圖是什麼顏色？只回顏色名稱。" Means "What color is this |
| iai | `Nkust` | accept_correct | 1026 ms | 用戶詢問圖片顏色，要求只回顏色名稱。圖片為純紅色塊，無其他元素。需簡潔回答，僅輸出顏色名稱，符合 |
| iai | `nvidia-ultra-550b` | reject | — | Error code: 400 - {'error': {'message': '/chat/completions:  |
| gemini | `models/deep-research-pro-preview-12-2025` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-2.5-flash-image` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-2.5-flash-native-audio-latest` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-2.5-flash-native-audio-preview-09-2025` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-2.5-flash-native-audio-preview-12-2025` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-2.5-flash-preview-tts` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-2.5-pro-preview-tts` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3-pro-image` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3-pro-image-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.1-flash-image` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.1-flash-image-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.1-flash-lite-image` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.1-flash-live-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.1-flash-tts-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/lyria-3-pro-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/nano-banana-pro-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/veo-3.1-lite-generate-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| iai | `Pic-small` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-small-2507` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-small-latest` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/antigravity-preview-05-2026` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/antigravity-preview-09-2026` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/aqa` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/deep-research-max-preview-04-2026` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/deep-research-preview-04-2026` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-2.5-computer-use-preview-10-2025` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.5-live-translate-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.5-transcribe` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.5-transcribe-live` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.8-live` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-3.8-live-extended-thinking` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-embedding-001` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-embedding-2` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/gemini-embedding-2-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/lyria-3-clip-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/lyria-3.5` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/lyria-realtime-exp` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/veo-3.1-fast-generate-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| gemini | `models/veo-3.1-generate-preview` | skipped_wrong_endpoint | — | wrong_endpoint |
| iai | `Asr` | skipped_wrong_endpoint | — | wrong_endpoint |
| iai | `bge-m3-embedding` | skipped_wrong_endpoint | — | wrong_endpoint |
| iai | `Embedding` | skipped_wrong_endpoint | — | wrong_endpoint |
| iai | `Furen-reranker` | skipped_wrong_endpoint | — | wrong_endpoint |
| iai | `Pic-large` | skipped_wrong_endpoint | — | wrong_endpoint |
| iai | `Speaker` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `codestral-embed` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `codestral-embed-2505` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `mistral-embed` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `mistral-embed-2312` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `mistral-moderation-2603` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-mini-2602` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-mini-latest` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-mini-realtime-2602` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-mini-realtime-latest` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-mini-transcribe-realtime-2602` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-mini-tts-2603` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `voxtral-mini-tts-latest` | skipped_wrong_endpoint | — | wrong_endpoint |
| mistral | `magistral-small-latest` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-medium` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-medium-2604` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-medium-3` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-medium-3-5` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-medium-3.5` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-medium-latest` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-ocr-2512` | accept_wrong | 2458 ms | |  Net cash used in financing activities | Net cash used in  |
| mistral | `mistral-ocr-3` | accept_wrong | 620 ms | |  Net cash used in financing activities | Net cash used in  |
| mistral | `mistral-ocr-3-0` | accept_wrong | 1148 ms | |  Net cash used in financing activities | Net cash used in  |
| mistral | `mistral-ocr-4` | accept_wrong | 723 ms | {"pages": [{"index": 0, "markdown": "", "images": [], "table |
| mistral | `mistral-ocr-4-0` | accept_wrong | 3498 ms | |  In millions | Net cash provided by operating activities | |
| mistral | `mistral-ocr-4-1` | accept_wrong | 614 ms | {"pages": [{"index": 0, "markdown": "", "images": [], "table |
| mistral | `mistral-ocr-latest` | accept_wrong | 554 ms | {"pages": [{"index": 0, "markdown": "", "images": [], "table |
| mistral | `mistral-small-2603` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-small-latest` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `codestral-2508` | reject | — | Error code: 400 - {'object': 'error', 'message': 'Image inpu |
| mistral | `codestral-latest` | reject | — | Error code: 400 - {'object': 'error', 'message': 'Image inpu |
| mistral | `labs-leanstral-1-5` | error | — | Error code: 403 - {'object': 'error', 'message': 'Model labs |
| mistral | `labs-leanstral-1-5-1` | error | — | Error code: 403 - {'object': 'error', 'message': 'Model labs |
| mistral | `ministral-14b-2512` | accept_correct | 594 ms | 紅色 |
| mistral | `ministral-14b-latest` | accept_correct | 677 ms | 紅色 |
| mistral | `ministral-3b-2512` | accept_correct | 732 ms | 這張圖是紅色。 |
| mistral | `ministral-3b-latest` | accept_correct | 658 ms | 這張圖是紅色。 |
| mistral | `ministral-8b-2512` | accept_correct | 930 ms | 紅色 |
| mistral | `ministral-8b-latest` | accept_correct | 603 ms | 紅色 |
| mistral | `mistral-code-fim-latest` | reject | — | Error code: 400 - {'object': 'error', 'message': 'Image inpu |
| mistral | `mistral-code-latest` | reject | — | Error code: 400 - {'object': 'error', 'message': 'Image inpu |
| mistral | `mistral-vibe-cli-fast` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-vibe-cli-latest` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |
| mistral | `mistral-vibe-cli-with-tools` | quota | — | Error code: 429 - {'object': 'error', 'message': 'Rate limit |

## 4. 菜單抽取（模型 × 圖）

| Provider | 模型 | 圖數 | JSON | schema | 店名 | 品名召回 | 價格召回 | JSON品名 | JSON價格 | 延遲 | 幻覺 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gemini | `models/gemini-3.1-flash-lite` | 4 | 100% | 100% | 100% | 97% | 90% | 97% | 84% | 5.6s | 2 |
| gemini | `models/gemini-3.1-flash-lite-preview` | 4 | 100% | 100% | 100% | 97% | 90% | 97% | 84% | 6.1s | 2 |
| gemini | `models/gemini-3-flash-preview` | 18 | 50% | 50% | 94% | 77% | 69% | 48% | 43% | 13.6s | 23 |
| iai | `nemotron-omni-30b` | 18 | 11% | 11% | 89% | 77% | 63% | 10% | 10% | 14.9s | 4 |
| mistral | `mistral-ocr-latest` | 18 | 0% | 0% | 78% | 76% | 70% | 0% | 0% | 6.3s | 0 |
| iai | `Furen-omni` | 18 | 22% | 17% | 89% | 75% | 63% | 11% | 11% | 13.0s | 0 |
| iai | `gemma-4-31b` | 18 | 83% | 83% | 78% | 70% | 64% | 67% | 59% | 52.9s | 49 |
| mistral | `ministral-14b-2512` | 4 | 50% | 50% | 75% | 63% | 27% | 26% | 17% | 28.9s | 9 |
| mistral | `ministral-8b-latest` | 18 | 83% | 83% | 72% | 63% | 52% | 49% | 41% | 22.1s | 73 |
| iai | `Furen-std` | 18 | 72% | 72% | 67% | 62% | 57% | 60% | 54% | 30.6s | 49 |
| mistral | `ministral-14b-latest` | 18 | 61% | 61% | 67% | 59% | 49% | 37% | 35% | 28.3s | 54 |
| mistral | `ministral-8b-2512` | 4 | 75% | 75% | 100% | 54% | 34% | 34% | 34% | 22.3s | 11 |
| mistral | `mistral-ocr-4` | 4 | 0% | 0% | 75% | 50% | 50% | 0% | 0% | 6.0s | 0 |
| mistral | `mistral-ocr-4-0` | 4 | 0% | 0% | 50% | 50% | 50% | 0% | 0% | 2.3s | 0 |
| mistral | `mistral-ocr-4-1` | 4 | 0% | 0% | 75% | 50% | 50% | 0% | 0% | 1.3s | 0 |
| mistral | `ministral-3b-latest` | 18 | 78% | 78% | 67% | 44% | 38% | 28% | 25% | 10.0s | 82 |
| mistral | `ministral-3b-2512` | 4 | 75% | 75% | 75% | 43% | 21% | 23% | 21% | 5.0s | 14 |
| mistral | `mistral-ocr-2512` | 4 | 0% | 0% | 25% | 21% | 21% | 0% | 0% | 5.6s | 0 |
| mistral | `mistral-ocr-3` | 4 | 0% | 0% | 25% | 21% | 21% | 0% | 0% | 5.4s | 0 |
| mistral | `mistral-ocr-3-0` | 4 | 0% | 0% | 25% | 21% | 21% | 0% | 0% | 1.5s | 0 |
| iai | `Nkust` | 18 | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 2.1s | 0 |

## 5. 讀法

- **accept_correct**：API 吃圖，且紅正方形答對。這是「真的有視覺」。
- **accept_wrong / accept_empty**：吃圖但顏色答錯或空白——仍丟菜單，因為紅塊太小可能被忽略。
- **reject**：端點拒圖。不應接進菜單入庫路徑。
- **品名召回**：gold 錨點有沒有出現在 JSON 或原文（含思考殘渣）。
- **JSON 品名／價格**：只有進結構化欄位才算，這才是入庫指標。
- **幻覺**：只在 `gold_complete=true` 的圖上計算多出來的品名。

## 6. 限制

- Gemini 免費層日額很低；未跑完的模型會標 `quota`，不是能力失敗。
- 錨點不是全量轉錄；召回是下限，不是菜單覆蓋率。
- 垂直中文、反光、社群截圖字極小，人類標註本身也有誤差。
