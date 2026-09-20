<p align="center">
  <a href="README.md">← 專案首頁</a> ·
  <a href="docs/CONTRIBUTING.en.md">English (UK)</a>
</p>

# 貢獻指南

歡迎 issue 與 PR。這份文件說明怎麼跑起來、怎麼改、以及哪些地方請先開 issue 討論。

---

## 環境

```bash
git clone https://github.com/Lrniey666/llm-capability-lab.git
cd llm-capability-lab

python -m venv .venv
source .venv/bin/activate        # Windows：.venv\Scripts\activate

pip install -e ".[serve,dev]"
cp .env.example .env             # 一把金鑰都不填也能跑測試
```

```bash
pytest
```

**82 項測試不連外網、不需供應商金鑰。** 「離線」不是「完全不開 socket」：
`test_mock_server.py` 與 `test_service.py` 會在本機起 HTTP 伺服器，走真實的
`openai` 套件與 FastAPI。如果你的改動讓測試必須有外網或金鑰才能過，
那多半是設計走偏了——請改用本機伺服器做法。

---

## 送 PR 前

- [ ] `pytest` 全綠
- [ ] 新行為有對應的測試
- [ ] 公開 API 有改動的話，`llmclab/__init__.py` 的 `__all__` 也更新
- [ ] `CHANGELOG.md` 加一筆
- [ ] 沒有把 `.env`、金鑰、或 `menu_example/` 以外的圖片加進版控

---

## 新增一家 provider

正常情況只要動 `llmclab/config.py` 的 `PROVIDERS` 一個地方，再把名字加進 `CLOUD_ORDER`：

```python
"newco": Provider(
    key="newco",
    label="NewCo",
    base_url="https://api.newco.com/v1",
    env_var="NEWCO_API_KEY",
    default_model="newco-small",
    console_url="https://newco.com/keys",
    limits_url="https://newco.com/limits",
    supports_vision=False,
    note="配額特性與雷區，寫給下一個維護者看",
),
```

也請在 `.env.example` 補上鍵名與申請網址。

**如果你發現得改三個以上的檔案，那是抽象漏了。** 請開 issue，我們把鉤子補好，
而不是在呼叫端寫 `if provider == "newco"`。現有的鉤子見
[`docs/architecture.md`](docs/architecture.md#新增一家-provider)。

前提是對方提供 Chat Completions HTTP（`POST /v1/chat/completions`）。
不相容的話這個專案的核心假設就不成立了，請先開 issue 討論。
這與 OpenAPI Specification（本服務 `/docs`）不是同一件事。

---

## 改實驗

`docs/vision-menu/runs/` 底下是**存檔的實驗紀錄，不回頭修改**——包含其中提到的
舊專案名稱。要重跑就產生新的 run，不要覆蓋舊的。

改動評分規則時請一併說明對既有 run 的影響。如果新規則會讓舊分數失效，
在 `CHANGELOG.md` 裡講清楚，並考慮把 gold 的版本號往上加。

刺激集 (`menu_example/`) 要加圖的話：

- 只收**公開張貼**的菜單，不收私人或內部文件
- 在 `gold.json` 標好錨點，並誠實設定 `gold_complete`
- 在 PR 描述裡說明來源與蒐集日期

---

## 版本號

只寫在 `llmclab/__init__.py` 的 `__version__`。`pyproject.toml` 用 setuptools 的
`dynamic = ["version"]` 去讀，不要在 toml 再寫死一筆。發新版時改那一處，
並在 `CHANGELOG.md` 加對應章節。版本字串必須符合
[PEP 440](https://peps.python.org/pep-0440/)（本專案用 SemVer `X.Y.Z`）。

## 發佈到 PyPI

依賴只寫在 `pyproject.toml`，不要另開 `requirements.txt`。

發一個 GitHub Release（tag 建議 `vX.Y.Z`）會跑 `.github/workflows/publish.yml`：
先上 **TestPyPI**，成功才上正式 PyPI。**不要**把 PyPI token 放進 repo 或 Actions secrets。

只想試包、不上正式站：Actions 裡對 `publish.yml` 跑 **Run workflow**（`workflow_dispatch`），只打 TestPyPI。

第一次發佈前，到 TestPyPI 與 PyPI 各設一個 Trusted Publisher，GitHub 建同名 Environment：

| 欄位 | TestPyPI | PyPI |
|---|---|---|
| Owner | `Lrniey666` | `Lrniey666` |
| Repository | `llm-capability-lab` | `llm-capability-lab` |
| Workflow name | `publish.yml` | `publish.yml` |
| Environment | `testpypi` | `pypi` |

說明見 [Publishing to PyPI with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/)。

Pull request 會跑 `.github/workflows/package.yml`：Ubuntu／Windows × Python 3.10–3.13 的 pytest，以及 build + `twine check` + 在 repo 外安裝 wheel。

## 程式風格

沒有強制的 formatter，跟著周圍的寫法即可。幾個這個專案在意的：

- **註解寫「為什麼」，不寫「做什麼」。** `max_retries=0` 旁邊要寫的是「重試由 Router 控制」，不是「把重試設成 0」
- **錯誤訊息要可執行。** 「沒設定金鑰」不夠，要講清楚填哪個環境變數、去哪裡申請
- **型別註解盡量寫完整**，這個套件有 `py.typed`
- `llmclab/service.py` **刻意不用** `from __future__ import annotations`——PEP 563 會把註解變成字串，FastAPI 解析不到在函式內才匯入的型別。改動這個檔案時請留意

---

## 回報問題

開 issue 時請附上：

- `llmclab keys` 的輸出（**金鑰已經遮罩過，可以直接貼**）
- 完整的錯誤訊息，特別是 `AllProvidersFailed` 的 `.attempts`
- Python 版本與作業系統

如果是某一家 provider 的行為變了（改了 header 名稱、模型下架、端點搬家），
這類 issue 特別有價值——這個專案的前提就是型錄會變。
