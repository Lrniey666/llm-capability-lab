"""跨供應商的 LLM 能力驗證與故障轉移路由。

三種用法，共用同一組 provider 註冊表：

輪換呼叫（把它當模組匯入）::

    import llmclab
    result = llmclab.ask("用一句話解釋 RAG")
    print(result.text, "via", result.provider)

HTTP 服務::

    python -m llmclab serve

研究（需要原始碼 checkout）::

    python -m llmclab vision-menu --phase core
    python -m llmclab compare
"""

from .client import (
    AllProvidersFailed,
    Attempt,
    ChatCompletionsClient,
    ChatResult,
    Router,
    chat,
    make_client,
)
from .config import (
    CLOUD_ORDER,
    DEFAULT_ORDER,
    PROVIDERS,
    Provider,
    configured_providers,
    is_source_checkout,
    load_env,
    workspace_root,
)
from .config import get as get_provider
from .ratelimit import RateLimitInfo

__version__ = "0.1.0"

__all__ = [
    "AllProvidersFailed",
    "Attempt",
    "CLOUD_ORDER",
    "ChatCompletionsClient",
    "ChatResult",
    "DEFAULT_ORDER",
    "PROVIDERS",
    "Provider",
    "RateLimitInfo",
    "Router",
    "__version__",
    "ask",
    "chat",
    "configured_providers",
    "default_router",
    "get_provider",
    "is_source_checkout",
    "load_env",
    "make_client",
    "reset_default_router",
    "workspace_root",
]

_DEFAULT_ROUTER: Router | None = None


def default_router(**kwargs) -> Router:
    """取得行程共用的 Router（第一次呼叫時依 .env 建立並快取）。

    傳入 kwargs 會強制重建，方便改 timeout 或重試次數。
    """
    global _DEFAULT_ROUTER
    if _DEFAULT_ROUTER is None or kwargs:
        _DEFAULT_ROUTER = Router.from_env(**kwargs)
    return _DEFAULT_ROUTER


def reset_default_router() -> None:
    """丟掉快取的 Router（改了 .env 或測試時用）。"""
    global _DEFAULT_ROUTER
    _DEFAULT_ROUTER = None


def ask(prompt: str, *, system: str | None = None, **kwargs) -> ChatResult:
    """最短路徑：送一句話，回一個必定有內容或拋 AllProvidersFailed 的結果。

    429 / 5xx / 金鑰失效都在內部處理掉——先換同一家的下一把金鑰，
    再換下一家，最後落到本機保底。
    """
    messages: list[dict[str, object]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return default_router().chat(messages, **kwargs)
