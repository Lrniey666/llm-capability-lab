"""把 Router 包成 HTTP 服務，讓非 Python 的專案也能用同一套轉移策略。

設計取捨：
  - 這層只做「翻譯」。轉移、重試、配額解析全都留在 Router，服務不重複實作。
  - 預設要求 Bearer token。這個服務背後是有配額、甚至要付費的金鑰，
    開成匿名等於把自己的額度送給整個網路。
  - 視覺端點的嘗試順序由 Provider.supports_vision 推導，不寫死模型 ID
    （模型 ID 會改版，config.py 已經講過這件事）。

啟動：
    pip install "llm-capability-lab[serve]"
    set LLMCLAB_API_TOKEN=...
    llmclab serve
"""

# 這裡刻意不用 from __future__ import annotations：
# PEP 563 會把註解變成字串，而 FastAPI 的型別是在 create_app() 內才匯入的，
# 解析 ForwardRef 時看不到它們。requires-python >= 3.10，X | None 本來就能在執行期用。
import asyncio
import dataclasses
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .client import AllProvidersFailed, ChatResult, Router
from .config import DEFAULT_ORDER, PROVIDERS, configured_providers, load_env

#: 未設定就拒絕啟動，除非明確允許匿名。
TOKEN_ENV = "LLMCLAB_API_TOKEN"
ALLOW_ANON_ENV = "LLMCLAB_ALLOW_ANONYMOUS"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class ServiceConfigError(RuntimeError):
    """服務設定本身有問題，啟動前就該擋下。"""


def vision_order(order: Iterable[str] | None = None) -> list[str]:
    """能吃圖的 provider，依 DEFAULT_ORDER 排。"""
    names = list(order) if order else DEFAULT_ORDER
    return [n for n in names if n in PROVIDERS and PROVIDERS[n].supports_vision]


def _result_payload(result: ChatResult) -> dict[str, Any]:
    return {
        "text": result.text,
        "provider": result.provider,
        "model": result.model,
        "latency_s": round(result.latency_s, 4),
        "ttft_s": round(result.ttft_s, 4) if result.ttft_s else None,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "tokens_per_s": round(result.tokens_per_s, 2) if result.tokens_per_s else None,
        "key_env": result.key_env,
        "rate_limit": result.rate_limit.summary(),
        "attempts": [dataclasses.asdict(a) for a in result.attempts],
    }


def resolve_token(token: str | None = None, allow_anonymous: bool | None = None) -> tuple[str, bool]:
    """決定服務要用的 token 與是否允許匿名，設定不安全時直接擋下。"""
    token = token if token is not None else os.environ.get(TOKEN_ENV, "").strip()
    if allow_anonymous is None:
        allow_anonymous = os.environ.get(ALLOW_ANON_ENV, "").strip().lower() in {"1", "true", "yes"}
    if not token and not allow_anonymous:
        raise ServiceConfigError(
            f"未設定 {TOKEN_ENV}。這個服務會用掉你的 API 配額，不該匿名對外開放。"
            f" 產生一把：python -c \"import secrets; print(secrets.token_urlsafe(32))\"。"
            f" 只在本機測試才用 {ALLOW_ANON_ENV}=1 略過。"
        )
    return token, bool(allow_anonymous)


def create_app(*, token: str | None = None, allow_anonymous: bool | None = None):
    """建立 FastAPI app。fastapi 未安裝時給出可執行的錯誤。"""
    try:
        from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover - 取決於安裝方式
        raise ServiceConfigError(
            'HTTP 服務需要額外依賴。請執行：pip install "llm-capability-lab[serve]"'
        ) from exc

    load_env()
    token, allow_anonymous = resolve_token(token, allow_anonymous)

    app = FastAPI(
        title="llm-capability-lab",
        version=__version__,
        description="跨供應商的 LLM 故障轉移路由。轉移策略在 Router，這層只做 HTTP 翻譯。",
    )

    def require_token(authorization: str | None = Header(default=None)) -> None:
        if allow_anonymous:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="缺少或錯誤的 Bearer token")

    class Message(BaseModel):
        role: str
        content: Any

    class ChatRequest(BaseModel):
        messages: list[Message] | None = None
        prompt: str | None = None
        system: str | None = None
        order: list[str] | None = Field(default=None, description="覆寫嘗試順序")
        model_overrides: dict[str, str] | None = None
        max_tokens: int | None = None
        temperature: float | None = None
        timeout: float = 60.0
        retries_per_key: int = 1

        def to_messages(self) -> list[dict[str, Any]]:
            if self.messages:
                return [m.model_dump() for m in self.messages]
            if not self.prompt:
                raise HTTPException(status_code=422, detail="messages 或 prompt 至少要給一個")
            out: list[dict[str, Any]] = []
            if self.system:
                out.append({"role": "system", "content": self.system})
            out.append({"role": "user", "content": self.prompt})
            return out

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, Any]:
        """liveness：不需 token，也不透露金鑰內容。"""
        ready = [p.key for p in configured_providers()]
        return {"status": "ok" if ready else "no_provider_configured", "providers_ready": ready}

    @app.get("/v1/providers", tags=["meta"])
    def providers(_: None = Depends(require_token)) -> dict[str, Any]:
        return {
            "order": DEFAULT_ORDER,
            "vision_order": vision_order(),
            "providers": [
                {
                    "key": p.key,
                    "label": p.label,
                    "model": p.resolved_model,
                    "configured": p.configured,
                    "keys_loaded": len(p.key_slots()),
                    "supports_vision": p.supports_vision,
                    "is_local": p.is_local,
                }
                for p in PROVIDERS.values()
            ],
        }

    @app.post("/v1/chat", tags=["inference"])
    async def chat_endpoint(body: ChatRequest, _: None = Depends(require_token)) -> dict[str, Any]:
        router = Router.from_env(
            body.order,
            retries_per_key=body.retries_per_key,
            timeout=body.timeout,
        )
        kwargs: dict[str, Any] = {}
        if body.max_tokens is not None:
            kwargs["max_tokens"] = body.max_tokens
        if body.temperature is not None:
            kwargs["temperature"] = body.temperature
        try:
            result = await router.achat(
                body.to_messages(), model_overrides=body.model_overrides, **kwargs
            )
        except AllProvidersFailed as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "all_providers_failed",
                    "attempts": [dataclasses.asdict(a) for a in exc.attempts],
                },
            ) from exc
        return _result_payload(result)

    @app.post("/v1/menu", tags=["inference"])
    async def menu_endpoint(
        image: UploadFile = File(..., description="菜單照片"),
        provider: str | None = Form(default=None),
        model: str | None = Form(default=None),
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        """菜單照片 → 結構化 JSON。

        沒指定 provider 時，依 supports_vision 逐家嘗試，第一個吐出可解析 JSON 的就回傳。
        注意「呼叫成功」與「JSON 可解析」是兩件事——回應同時給 parsed 與 parse_error。
        """
        from .config import get as get_provider
        from .vision_menu import run_extract

        raw = await image.read()
        if not raw:
            raise HTTPException(status_code=422, detail="檔案是空的")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail=f"檔案超過 {MAX_UPLOAD_BYTES // 1024 // 1024} MB"
            )

        suffix = Path(image.filename or "upload.jpg").suffix or ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(raw)
            tmp.close()
            targets = [provider] if provider else vision_order()
            attempts: list[dict[str, Any]] = []
            for name in targets:
                p = get_provider(name)
                if not p.configured:
                    attempts.append({"provider": name, "error": "未設定金鑰"})
                    continue
                payload = await asyncio.to_thread(
                    run_extract, p, model or p.resolved_model, Path(tmp.name)
                )
                payload.pop("file", None)
                attempts.append(
                    {
                        "provider": name,
                        "model": payload.get("model"),
                        "ok": payload.get("ok"),
                        "parse_error": payload.get("parse_error"),
                        "error": payload.get("error"),
                    }
                )
                if payload.get("parsed") is not None:
                    payload["attempts"] = attempts
                    return payload
            raise HTTPException(
                status_code=503,
                detail={"error": "no_parseable_extraction", "attempts": attempts},
            )
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    return app


def serve(host: str = "127.0.0.1", port: int = 8000, *, reload: bool = False) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ServiceConfigError(
            '需要 uvicorn。請執行：pip install "llm-capability-lab[serve]"'
        ) from exc
    create_app()  # 先驗證設定，讓錯誤在啟動前就出現
    uvicorn.run("llmclab.service:create_app", host=host, port=port, reload=reload, factory=True)
