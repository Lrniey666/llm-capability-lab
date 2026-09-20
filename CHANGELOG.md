# 變更紀錄

版本號依循 [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)。

---

## [Unreleased]

### 變更

- 匯入名與 CLI 從 `llmlab` 改成 `llmclab`，避開 PyPI 上 `llmlab-ai` 的套件目錄／`console_scripts` 撞名。發行名仍是 `llm-capability-lab`
- 環境變數前綴從 `LLMLAB_*` 改成 `LLMCLAB_*`（`LLMCLAB_API_TOKEN`、`LLMCLAB_ALLOW_ANONYMOUS`、`LLMCLAB_WORKSPACE`）。尚未上架，現在改不必當破壞性變更
- 公開首發版本改為 `0.1.0`（Beta）。內部曾用 1.0.0，但不把 Router／HTTP 契約當成已凍結的 1.x
- CI：`package.yml` 在 Ubuntu／Windows × Python 3.10–3.13 跑 pytest；build 後檢查 wheel 內有 `llmclab/py.typed`，並在 repo 外的 venv 安裝驗證
- `publish.yml` 先上 TestPyPI；GitHub Release 才上正式 PyPI。也可 `workflow_dispatch` 只打 TestPyPI
- 刪除 `requirements.txt`，依賴只寫在 `pyproject.toml`
- classifiers 補 `Typing :: Typed` 與 `Python :: 3.13`
- 打包 metadata 對齊現行 PyPA 規格，讓 `pip install` 從 sdist／wheel／Git 都能裝：
  - `license = "MIT"` + `license-files = ["LICENSE"]`（[PEP 639](https://peps.python.org/pep-0639/)），刪掉已棄用的 `License ::` classifier
  - build 後端下限改為 `setuptools>=77.0.3`
  - 版本改 `dynamic = ["version"]`，單一來源是 `llmclab.__version__`
  - 補上 `[project.urls]`（Homepage／Documentation／Repository／Issues／Changelog）
  - `packages` 改 `find` 自動探索 `llmclab*`
- 發 GitHub Release 可走 [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)（`.github/workflows/publish.yml`）
- Docker 映像改裝「這一顆」wheel 的 `[serve]` extra，不再向 PyPI 解析同名專案
- 對外說明對齊程式與 `vision-20260918-130204`：`mistral-ocr-*` 走 `/v1/ocr` 不是
  Chat Completions；`/v1/menu` 不走 `Router`；本機保底是 Ollama `/api/chat`，
  不是任意 Chat Completions 端點。抽取數字仍是 224／218／99，
  但寫明擴充 14 張只跑到一部分。
- README 收成功能 → 安裝 → 快速入門（含公開函式），發現改放 `docs/findings.md`；
  121 寫成「型錄 ID」而非對話模型；菜單圖標成測試案例。用語把 Chat Completions、
  PyPI `openai` 套件、OpenAPI Specification（OAS）分開，避免與 OpenAI 公司混為一談。
  測試改寫成「不連外網、不需金鑰；本機仍可起 HTTP 伺服器」。
- 公開用戶端改為本專案的 `ChatCompletionsClient`（`make_client()` 回這個類）。PyPI `openai` 只當傳輸，不是上架名稱。
- 本檔版本規範改為 [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html)。
- 標語改為「規格上有，實際情形？」／ “It's in the spec. What's the actual case?”

---

## [0.1.0] — 2026-09-19

從未上架 PyPI。內部曾編號 1.0.0；公開首發改回 0.1.0（Beta），不承諾凍結公開 API。

從 `llm-free-tier-lab` 獨立出來，重新定位為**能力驗證 + 故障轉移路由**的模組。
舊名字只描述了「免費層探測」那半邊，但最大的模組其實是視覺抽取評測；
而且「free-tier」會隨各家方案改動而過期。

### 新增

- **可安裝**：加入 `pyproject.toml`，現在可以 `pip install -e .` 或
  `pip install git+...` 接進其他 Python 專案
- **HTTP 服務層** `llmlab.service`：`/v1/chat`、`/v1/menu`、`/v1/providers`、
  `/healthz`，讓 TypeScript／Go 等非 Python 專案共用同一套轉移策略
  - 預設要求 `LLMLAB_API_TOKEN`，**未設定就拒絕啟動**
  - `--host` 預設只綁 `127.0.0.1`
  - 上傳上限 8 MB
- **`llmlab serve`** 子指令（第 9 個）
- **`Router.achat()`**：非同步版本，阻塞呼叫自動丟到執行緒，不卡 event loop
- **`Router.from_env()`**：載入 `.env` 並只採用金鑰已就位的 provider
- **`llmlab.ask()`** 與 `default_router()`：最短路徑的模組級進入點
- **`workspace_root()` / `require_workspace()`**：研究產物的路徑解析，
  可用 `LLMLAB_WORKSPACE` 覆寫
- **`py.typed`**：對外宣告型別資訊
- `LICENSE`（MIT）、`CONTRIBUTING.md`、本變更紀錄
- 雙語 README、`docs/architecture.md`、`docs/http-api.md`、`docs/assets/hero.svg`
- 新測試檔 `tests/test_module_api.py`、`tests/test_service.py`

### 變更

- **`load_env()` 改為從呼叫端 CWD 往上搜尋** `.env`，不再寫死套件所在目錄。
  被其他專案匯入時，金鑰在對方的專案裡
- 公開 API 從 5 個擴充到 20 個，不必再從子模組挖
- `examples/discord_bot.py` 改用 `Router.from_env()` 與 `achat()`，
  不再需要手動 `asyncio.to_thread`
- `menu_example/` 與 iAI 參考資料收進 repo，專案自給自足
- README 改以研究結論開場，而非安裝步驟

### 修正

- **`.env` 搜尋不再逃出專案邊界**。原本的無界向上搜尋會一路撈到家目錄的 `.env`，
  可能載入完全無關的金鑰。現在遇到 `.git` 或 `pyproject.toml` 就停
- `.gitignore` 原本只擋 `.venv/` 與 `venv/`，漏掉實際在用的 `.venv-py310/`。
  改為 `.venv*/`
- 修正 `MENU_DIR` 與 `IAI_CSV` 指向 repo 外部的路徑

### 安全性

- HTTP 服務預設不可匿名。這個服務背後是有配額、甚至要付費的金鑰，
  開成匿名等於把額度送給整個網路
- `/healthz` 不需 token，但也不透露任何金鑰內容；`/v1/providers` 只回金鑰**數量**

### 備註

- `docs/vision-menu/runs/` 底下的存檔實驗紀錄**維持原樣**，包含其中提到的舊專案名稱。
  那是實驗當下的紀錄，不回頭竄改
- 打包時只含函式庫本身；`menu_example/`（19 張圖）與 `docs/` 不進 wheel

---

## 更早之前

本專案獨立前的歷史屬於 `llm-free-tier-lab`，主要成果為：

- 2026-09-18 — 視覺抽取實驗 `vision-20260918-130204`：121 個模型探針、
  224 次抽取。發現 7 個 `mistral-ocr-*` 會「收圖卻答錯」
- 2026-09-16 — 四輪 `compare` 對照實驗
- 免費層配額、TTFT／tok-s 基準、金鑰輪替與跨 provider 轉移的初版實作
