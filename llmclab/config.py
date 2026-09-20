"""Provider 註冊表與環境變數載入。

新增一家 provider 只要在 PROVIDERS 裡加一筆，其餘程式碼不用動。
雲端四家提供 Chat Completions HTTP，用戶端是 PyPI `openai`；本機 Ollama 走官方 /api/chat。
差別在 base_url / 金鑰 / 模型 ID。這與 OpenAPI Specification 無關。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

PACKAGE_DIR = Path(__file__).resolve().parent
# 原始碼 checkout 的根目錄。裝進 site-packages 之後這個路徑沒有意義，
# 所以只有 research 那半邊（需要 menu_example/ 與 docs/）才依賴它。
PROJECT_ROOT = PACKAGE_DIR.parent

#: 環境變數：覆寫研究產物的輸出根目錄。
WORKSPACE_ENV = "LLMCLAB_WORKSPACE"

# .env.example 預留 KEY / KEY2 / KEY3；多填 KEY4… 也會自動納入輪替。
DISPLAY_KEY_SLOTS = 3
MAX_KEY_SLOTS = 9


def slot_env_names(base: str, max_slots: int = MAX_KEY_SLOTS) -> tuple[str, ...]:
    """GROQ_API_KEY → GROQ_API_KEY, GROQ_API_KEY2, …（不含 KEY1，與 .env.example 一致）。"""
    if max_slots < 1:
        return ()
    return (base, *(f"{base}{i}" for i in range(2, max_slots + 1)))


def mask_secret(key: str | None) -> str:
    if not key:
        return "(未設定)"
    if len(key) <= 10:
        return key[:2] + "…"
    return f"{key[:6]}…{key[-4:]}"


@dataclass(frozen=True)
class KeySlot:
    env_var: str
    index: int
    value: str

    def masked(self) -> str:
        return mask_secret(self.value)


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    env_var: str
    default_model: str
    console_url: str
    limits_url: str
    supports_vision: bool = False
    supports_json_mode: bool = True
    note: str = ""
    is_local: bool = False
    requires_key: bool = True
    base_url_env: str = ""
    model_env: str = ""
    placeholder_key: str = "local"
    timeout: float | None = None
    max_key_slots: int = MAX_KEY_SLOTS
    extra_body: dict[str, Any] | None = None

    def slot_names(self, *, display_only: bool = False) -> tuple[str, ...]:
        cap = DISPLAY_KEY_SLOTS if display_only else self.max_key_slots
        cap = min(cap, self.max_key_slots)
        names = list(slot_env_names(self.env_var, cap))
        if display_only:
            for extra in slot_env_names(self.env_var, self.max_key_slots)[cap:]:
                if os.environ.get(extra, "").strip():
                    names.append(extra)
        return tuple(names)

    def key_slots(self) -> list[KeySlot]:
        """已填值的金鑰槽，依 KEY → KEY2 → KEY3 順序。"""
        slots: list[KeySlot] = []
        for index, name in enumerate(self.slot_names(), start=1):
            value = os.environ.get(name, "").strip()
            if value:
                slots.append(KeySlot(env_var=name, index=index, value=value))
        if slots:
            return slots
        if not self.requires_key and self.opted_in:
            return [KeySlot(env_var=self.env_var, index=1, value=self.placeholder_key)]
        return []

    @property
    def opted_in(self) -> bool:
        if os.environ.get(self.env_var, "").strip():
            return True
        return bool(self.base_url_env and os.environ.get(self.base_url_env, "").strip())

    @property
    def resolved_base_url(self) -> str:
        if self.base_url_env:
            override = os.environ.get(self.base_url_env, "").strip()
            if override:
                return override.rstrip("/")
        return self.base_url.rstrip("/")

    @property
    def resolved_model(self) -> str:
        if self.model_env:
            override = os.environ.get(self.model_env, "").strip()
            if override:
                return override
        return self.default_model

    @property
    def api_key(self) -> str | None:
        slots = self.key_slots()
        return slots[0].value if slots else None

    @property
    def configured(self) -> bool:
        return bool(self.key_slots())

    def masked_key(self) -> str:
        return mask_secret(self.api_key)


# 模型 ID 會改版，跑 `python -m llmclab models` 用 API 撈一次最準，別寫死在程式裡。
PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        key="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        env_var="GROQ_API_KEY",
        default_model="openai/gpt-oss-20b",
        console_url="https://console.groq.com/keys",
        limits_url="https://console.groq.com/settings/limits",
        supports_vision=False,
        note="延遲最低；真正的瓶頸是 TPM 不是 RPD。固定 system prompt 記得開 prompt caching。gpt-oss 預設 reasoning_effort=low，避免思考吃光 max_tokens。",
        extra_body={"reasoning_effort": "low"},
    ),
    "gemini": Provider(
        key="gemini",
        label="Gemini (AI Studio)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        env_var="GEMINI_API_KEY",
        default_model="gemini-3.6-flash",
        console_url="https://aistudio.google.com/apikey",
        limits_url="https://aistudio.google.com/",
        supports_vision=True,
        note="免費層預設就能看圖，且有長 context；限制綁在專案不是綁在 key。",
    ),
    "mistral": Provider(
        key="mistral",
        label="Mistral (Experiment)",
        base_url="https://api.mistral.ai/v1",
        env_var="MISTRAL_API_KEY",
        default_model="ministral-3b-latest",
        console_url="https://console.mistral.ai/api-keys",
        limits_url="https://admin.mistral.ai",
        supports_vision=True,
        note="Experiment 方案速率約 1 req/s；適合批次與離線處理，不適合高併發。",
    ),
    "iai": Provider(
        key="iai",
        label="iAI (NKUST)",
        base_url="https://www.iai.nkust.edu.tw/aihub/v1",
        env_var="IAI_API_KEY",
        default_model="Furen-large",
        console_url="https://www.iai.nkust.edu.tw/apply",
        limits_url="https://www.iai.nkust.edu.tw/models",
        supports_vision=False,
        note=(
            "機構端點（iAI Hub），Chat Completions。預設 Furen-large 拒圖。"
            "Furen-std / gemma-4-31b 探針能看；Nkust 是推理模型，短回覆常被思考吃光。"
        ),
        model_env="IAI_MODEL",
        base_url_env="IAI_BASE_URL",
        timeout=90.0,
    ),
    "local": Provider(
        key="local",
        label="Local (Qwen3.5-4B)",
        base_url="http://127.0.0.1:11434/v1",
        env_var="LOCAL_API_KEY",
        default_model="qwen3.5:4b",
        console_url="https://ollama.com/library/qwen3.5",
        limits_url="https://github.com/ollama/ollama",
        supports_vision=True,
        note=(
            "雲端用盡後的本機保底。需已設 LOCAL_BASE_URL，且本機已開 Ollama。"
            "沒有雲端配額；Qwen3.5 預設關掉 think，避免思考過程吃掉短回覆。"
        ),
        is_local=True,
        requires_key=False,
        base_url_env="LOCAL_BASE_URL",
        model_env="LOCAL_MODEL",
        placeholder_key="ollama",
        timeout=180.0,
        max_key_slots=1,
        extra_body={"think": False},
    ),
}

# 雲端先依延遲排；iAI 接在免費層之後；本機 Qwen 永遠最後。
CLOUD_ORDER: list[str] = ["groq", "gemini", "mistral", "iai"]
DEFAULT_ORDER: list[str] = [*CLOUD_ORDER, "local"]


def find_dotenv(start: Path | None = None) -> Path | None:
    """從 start（預設 CWD）往上找最近的 .env。

    搜尋在遇到專案邊界（.git 或 pyproject.toml）後停止，
    避免不小心撈到家目錄或其他專案的金鑰。
    """
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists() or (directory / "pyproject.toml").is_file():
            break
    fallback = PROJECT_ROOT / ".env"
    return fallback if fallback.is_file() else None


def load_env(path: str | Path | None = None, *, override: bool = False) -> Path | None:
    """載入 .env，回傳實際載入的檔案路徑；沒載到則 None。

    llmclab 被其他專案匯入時，金鑰通常放在「呼叫端」的 .env，
    所以這裡從 CWD 往上找，而不是寫死套件所在目錄。
    已存在於真實環境變數的值預設不覆蓋。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None
    env_path = Path(path).expanduser() if path else find_dotenv()
    if env_path and env_path.is_file():
        load_dotenv(env_path, override=override)
        return env_path
    load_dotenv(override=override)
    return None


def get(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        known = ", ".join(PROVIDERS)
        raise SystemExit(f"未知的 provider：{name}（可用：{known}）") from None


def iter_providers(names: list[str] | None = None) -> Iterator[Provider]:
    for name in names or DEFAULT_ORDER:
        yield get(name)


def configured_providers(names: list[str] | None = None) -> list[Provider]:
    return [p for p in iter_providers(names) if p.configured]


def is_source_checkout() -> bool:
    """是否從原始碼 checkout 執行（而非已安裝進 site-packages）。"""
    return (PROJECT_ROOT / "pyproject.toml").is_file()


def workspace_root() -> Path:
    """研究產物（runs、報告）的根目錄。

    優先序：LLMCLAB_WORKSPACE > 原始碼 checkout 的 repo 根 > 目前工作目錄。
    """
    override = os.environ.get(WORKSPACE_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_source_checkout():
        return PROJECT_ROOT
    return Path.cwd()


def require_workspace(what: str = "研究資產") -> Path:
    """取得含有研究資產的工作區，缺少時給出可執行的錯誤訊息。"""
    root = workspace_root()
    if (root / "menu_example").is_dir() or (root / "docs" / "vision-menu").is_dir():
        return root
    raise RuntimeError(
        f"找不到{what}。llmclab 的研究模組需要原始程式碼 checkout"
        f"（menu_example/ 與 docs/）。目前工作區：{root}。"
        f"請在 repo 內執行，或設定 {WORKSPACE_ENV}=/path/to/llm-capability-lab。"
    )
