"""統一的 client 包裝 + 跨 provider / 多金鑰的 fallback router。

雲端走 Chat Completions（POST /v1/chat/completions），因此用 PyPI `openai`
用戶端指向各家 base_url；換 provider 等於換 base_url + api_key + model。
本機 Ollama 例外，走官方 /api/chat。這與 OpenAPI Specification（OAS）無關。
同一家若填了 KEY2 / KEY3，失敗時會先換金鑰再換下一家；本機排最後。
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .config import Provider, get
from .ratelimit import RateLimitInfo, parse_headers, retry_delay

Messages = Sequence[dict[str, Any]]

# 這些錯誤代表「這把金鑰或這家現在不行」，而不是「你的程式寫錯了」。
TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
# 金鑰本身無效：同一把重試沒意義，立刻換下一把。
AUTH_STATUS = {401, 403}


class AllProvidersFailed(RuntimeError):
    def __init__(self, attempts: list["Attempt"]):
        self.attempts = attempts
        detail = "; ".join(f"{a.provider}: {a.error}" for a in attempts)
        super().__init__(f"所有 provider 都失敗了 → {detail}")


@dataclass
class Attempt:
    provider: str
    model: str
    ok: bool
    error: str | None = None
    status: int | None = None
    waited_s: float = 0.0
    key_env: str | None = None


@dataclass
class ChatResult:
    provider: str
    model: str
    text: str
    latency_s: float
    ttft_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    rate_limit: RateLimitInfo = field(default_factory=RateLimitInfo)
    attempts: list[Attempt] = field(default_factory=list)
    key_env: str | None = None

    @property
    def tokens_per_s(self) -> float | None:
        if not self.completion_tokens:
            return None
        window = self.latency_s - (self.ttft_s or 0.0)
        if window <= 0:
            window = self.latency_s
        return self.completion_tokens / window if window > 0 else None


class ChatCompletionsClient:
    """本專案的 Chat Completions HTTP 用戶端。

    `make_client()` 回的就是這個類，不是上游套件裡的類。
    傳輸目前交給 PyPI `openai`（max_retries=0，重試由 Router 控制）。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float = 60.0,
        max_retries: int = 0,
    ):
        import openai as chat_http

        self._transport = chat_http.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    @property
    def chat(self):
        return self._transport.chat

    @property
    def models(self):
        return self._transport.models


def make_client(provider: Provider, timeout: float = 60.0, api_key: str | None = None) -> ChatCompletionsClient:
    """建立指向某一家的 ChatCompletionsClient。max_retries=0：重試由我們自己控制。"""
    key = api_key if api_key is not None else provider.api_key
    if not key:
        if provider.is_local:
            raise RuntimeError(
                f"{provider.label} 未啟用。請在 .env 填 {provider.base_url_env}="
                f"{provider.base_url}，並先 `ollama pull {provider.default_model}`。"
            )
        raise RuntimeError(
            f"{provider.label} 沒有設定金鑰。請在 .env 裡填 {provider.env_var}／"
            f"{provider.env_var}2／{provider.env_var}3，申請網址：{provider.console_url}"
        )
    return ChatCompletionsClient(
        api_key=key,
        base_url=provider.resolved_base_url,
        timeout=timeout,
        max_retries=0,
    )


def _with_provider_options(provider: Provider, kwargs: dict[str, Any]) -> dict[str, Any]:
    extra = provider.extra_body
    if not extra:
        return kwargs
    merged = dict(kwargs)
    body = dict(extra)
    body.update(merged.get("extra_body") or {})
    merged["extra_body"] = body
    return merged


def _status_of(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status


def is_transient(exc: Exception) -> bool:
    status = _status_of(exc)
    if status in TRANSIENT_STATUS:
        return True
    name = type(exc).__name__
    return name in {"APIConnectionError", "APITimeoutError", "InternalServerError", "RateLimitError"}


def chat(
    provider_name: str,
    messages: Messages,
    *,
    model: str | None = None,
    stream: bool = False,
    timeout: float = 60.0,
    api_key: str | None = None,
    key_env: str | None = None,
    **kwargs: Any,
) -> ChatResult:
    """對單一 provider 送一次請求（不做 fallback）。可指定要用哪一把金鑰。"""
    provider = get(provider_name)
    client = make_client(provider, timeout=timeout, api_key=api_key)
    model = model or provider.resolved_model
    used_env = key_env or (provider.key_slots()[0].env_var if provider.key_slots() else provider.env_var)
    kwargs = _with_provider_options(provider, kwargs)

    if stream:
        result = _chat_stream(provider, client, model, messages, **kwargs)
    else:
        result = _chat_once(provider, client, model, messages, timeout=timeout, **kwargs)
    result.key_env = used_env
    return result


def _message_text(message) -> str:
    """取出可見回覆。推理模型常把正文放空、只留 reasoning 欄位。"""
    content = getattr(message, "content", None) or ""
    if str(content).strip():
        return content
    extra = getattr(message, "model_extra", None) or {}
    for key in ("reasoning_content", "reasoning"):
        val = extra.get(key) if isinstance(extra, dict) else None
        if not val:
            val = getattr(message, key, None)
        if val and str(val).strip():
            return str(val)
    return content


def _ollama_root(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url.rstrip("/")


def _chat_ollama_native(provider, model, messages, *, timeout: float = 180.0, **kwargs) -> ChatResult:
    """Ollama 的 /v1 端點不會把 think=false 傳到模型；改打官方 /api/chat。"""
    extra = kwargs.get("extra_body") or {}
    body = {
        "model": model,
        "messages": list(messages),
        "stream": False,
        "think": bool(extra.get("think", False)),
        "options": {"temperature": kwargs.get("temperature", 0)},
    }
    if kwargs.get("max_tokens") is not None:
        body["options"]["num_predict"] = kwargs["max_tokens"]

    req = urllib.request.Request(
        f"{_ollama_root(provider.resolved_base_url)}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:160]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    elapsed = time.perf_counter() - started
    msg = payload.get("message") or {}
    return ChatResult(
        provider=provider.key,
        model=model,
        text=msg.get("content") or "",
        latency_s=elapsed,
        prompt_tokens=payload.get("prompt_eval_count"),
        completion_tokens=payload.get("eval_count"),
    )


def _chat_once(provider, client, model, messages, **kwargs) -> ChatResult:
    timeout = kwargs.pop("timeout", provider.timeout or 60.0)
    if provider.is_local:
        return _chat_ollama_native(provider, model, messages, timeout=timeout, **kwargs)
    started = time.perf_counter()
    # with_raw_response 讓我們同時拿到 body 和 header——配額資訊只在 header 裡。
    raw = client.chat.completions.with_raw_response.create(
        model=model, messages=list(messages), **kwargs
    )
    elapsed = time.perf_counter() - started
    completion = raw.parse()
    usage = getattr(completion, "usage", None)

    return ChatResult(
        provider=provider.key,
        model=model,
        text=_message_text(completion.choices[0].message),
        latency_s=elapsed,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        rate_limit=parse_headers(raw.headers),
    )


def _chat_stream(provider, client, model, messages, **kwargs) -> ChatResult:
    started = time.perf_counter()
    ttft: float | None = None
    chunks: list[str] = []
    usage = None

    stream = client.chat.completions.create(
        model=model, messages=list(messages), stream=True, **kwargs
    )
    for event in stream:
        if getattr(event, "usage", None):
            usage = event.usage
        if not event.choices:
            continue
        piece = event.choices[0].delta.content
        if piece:
            if ttft is None:
                ttft = time.perf_counter() - started
            chunks.append(piece)

    elapsed = time.perf_counter() - started
    text = "".join(chunks)
    return ChatResult(
        provider=provider.key,
        model=model,
        text=text,
        latency_s=elapsed,
        ttft_s=ttft,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        # 串流不一定回 usage，退而求其次用粗估值，僅供 TPS 參考。
        completion_tokens=getattr(usage, "completion_tokens", None) or max(len(text) // 4, 1),
    )


class Router:
    """先換同一家的下一把金鑰，再換下一家；全掛才拋例外。

    順序：provider1/KEY → provider1/KEY2 → provider1/KEY3 → provider2/KEY → …
    429 / 5xx / timeout：同一把可重試，用盡次數就換下一把（換鑰匙不等待）。
    401 / 403：這把金鑰無效，立刻換下一把。
    400：請求本身有問題，跳過這家剩下的金鑰。
    """

    def __init__(
        self,
        order: Iterable[str],
        *,
        retries_per_provider: int | None = None,
        retries_per_key: int | None = None,
        max_attempts_per_provider: int | None = None,
        timeout: float = 60.0,
        sleep=time.sleep,
        verbose: bool = False,
    ):
        if retries_per_key is None:
            retries_per_key = retries_per_provider if retries_per_provider is not None else 1
        self.order = list(order)
        self.retries_per_key = retries_per_key
        self.retries_per_provider = retries_per_key  # 舊參數別名，既有呼叫端不用改
        self.max_attempts_per_provider = max_attempts_per_provider
        self.timeout = timeout
        self._sleep = sleep
        self.verbose = verbose

    def chat(self, messages: Messages, *, model_overrides: dict[str, str] | None = None, **kwargs) -> ChatResult:
        attempts: list[Attempt] = []
        overrides = model_overrides or {}

        for name in self.order:
            provider = get(name)
            model = overrides.get(name, provider.resolved_model)
            slots = provider.key_slots()

            if not slots:
                hint = (provider.base_url_env or provider.env_var) if provider.is_local else provider.env_var
                attempts.append(Attempt(name, model, False, error=f"未設定 {hint}"))
                continue

            budget = self.max_attempts_per_provider
            used = 0
            skip_provider = False
            timeout = provider.timeout if provider.timeout is not None else self.timeout

            for slot in slots:
                if skip_provider:
                    break
                for attempt_no in range(self.retries_per_key + 1):
                    if budget is not None and used >= budget:
                        skip_provider = True
                        break
                    used += 1
                    try:
                        result = chat(
                            name,
                            messages,
                            model=model,
                            timeout=timeout,
                            api_key=slot.value,
                            key_env=slot.env_var,
                            **kwargs,
                        )
                        attempts.append(Attempt(name, model, True, key_env=slot.env_var))
                        result.attempts = attempts
                        result.key_env = slot.env_var
                        return result
                    except Exception as exc:  # noqa: BLE001 - 這裡就是要攔下全部
                        status = _status_of(exc)
                        transient = is_transient(exc)
                        waited = 0.0
                        same_key_retry = transient and attempt_no < self.retries_per_key
                        if same_key_retry:
                            waited = retry_delay(exc, attempt_no)
                            if self.verbose:
                                print(
                                    f"  [{name}/{slot.env_var}] {status or type(exc).__name__}，"
                                    f"等 {waited:.1f}s 再試同一把"
                                )
                            self._sleep(waited)
                        elif self.verbose:
                            nxt = "下一把金鑰" if status in AUTH_STATUS or transient else "下一家"
                            print(f"  [{name}/{slot.env_var}] {status or type(exc).__name__}，改試{nxt}")
                        attempts.append(
                            Attempt(
                                name,
                                model,
                                False,
                                error=str(exc)[:160],
                                status=status,
                                waited_s=waited,
                                key_env=slot.env_var,
                            )
                        )
                        if status in AUTH_STATUS:
                            break  # 這把無效，換下一把
                        if not transient:
                            skip_provider = True  # 400 換鑰匙也一樣
                            break
                        if not same_key_retry:
                            break  # 這把次數用完，換下一把

        raise AllProvidersFailed(attempts)

    @classmethod
    def from_env(
        cls,
        order: Iterable[str] | None = None,
        *,
        env_path: str | None = None,
        **kwargs: Any,
    ) -> "Router":
        """載入 .env，只用「金鑰已就位」的 provider 建 Router。

        沒填的那幾家會被跳過而不是在執行期才炸開，適合當成其他專案的進入點：

            router = Router.from_env()
            result = router.chat([{"role": "user", "content": "你好"}])
        """
        from .config import configured_providers, load_env

        load_env(env_path)
        names = [p.key for p in configured_providers(list(order) if order else None)]
        if not names:
            raise RuntimeError(
                "沒有任何 provider 設定了金鑰。請複製 .env.example 成 .env 並至少填一家，"
                "或設定 LOCAL_BASE_URL 啟用本機保底。"
            )
        return cls(names, **kwargs)

    async def achat(self, messages: Messages, **kwargs: Any) -> ChatResult:
        """chat() 的非同步版本。

        底層 HTTP 是阻塞的，這裡用 to_thread 丟到執行緒，
        讓 Discord bot / ASGI 應用不會卡住 event loop。
        """
        return await asyncio.to_thread(self.chat, messages, **kwargs)
