"""逐項能力檢查：連通、模型清單、串流、JSON 模式、視覺輸入。

每一項都獨立，某一項失敗不影響其他項——這樣才看得出「是這家掛了」
還是「只是這個功能這家不支援」。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from .client import chat, make_client
from .config import Provider
from .ratelimit import RateLimitInfo

# 16x16 純紅色 PNG，內嵌避免測試要連外網抓圖。
RED_SQUARE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR42mO4o6FBEmIY"
    "1TCqYfhqAAAyBCwQhCQ/2gAAAABJRU5ErkJggg=="
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    elapsed_s: float | None = None
    skipped: bool = False
    rate_limit: RateLimitInfo | None = None

    @property
    def mark(self) -> str:
        if self.skipped:
            return "—"
        return "✓" if self.ok else "✗"


@dataclass
class ProviderReport:
    provider: Provider
    results: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results if not r.skipped)

    @property
    def rate_limit(self) -> RateLimitInfo | None:
        for r in self.results:
            if r.rate_limit and r.rate_limit.has_data:
                return r.rate_limit
        return None


def _timed(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    started = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name, False, detail=_short(exc), elapsed_s=time.perf_counter() - started)
    if result.elapsed_s is None:
        result.elapsed_s = time.perf_counter() - started
    return result


def _short(exc: Exception, limit: int = 140) -> str:
    text = " ".join(str(exc).split())
    return text[:limit] + ("…" if len(text) > limit else "")


def check_ping(provider: Provider, model: str | None = None) -> CheckResult:
    def run() -> CheckResult:
        result = chat(
            provider.key,
            [{"role": "user", "content": "回覆兩個字：收到"}],
            model=model,
            max_tokens=16,
            temperature=0,
        )
        return CheckResult(
            "連通",
            True,
            detail=f"{result.model} → {result.text.strip()[:20]!r}",
            elapsed_s=result.latency_s,
            rate_limit=result.rate_limit,
        )

    return _timed("連通", run)


def check_models(provider: Provider) -> CheckResult:
    def run() -> CheckResult:
        client = make_client(provider, timeout=30)
        models = [m.id for m in client.models.list()]
        preview = ", ".join(models[:3])
        return CheckResult("模型清單", True, detail=f"{len(models)} 個（{preview}…）")

    return _timed("模型清單", run)


def check_streaming(provider: Provider, model: str | None = None) -> CheckResult:
    def run() -> CheckResult:
        result = chat(
            provider.key,
            [{"role": "user", "content": "從 1 數到 20，只回數字。"}],
            model=model,
            stream=True,
            max_tokens=120,
            temperature=0,
        )
        ttft = f"{result.ttft_s * 1000:.0f} ms" if result.ttft_s else "n/a"
        tps = f"{result.tokens_per_s:.0f} tok/s" if result.tokens_per_s else "n/a"
        return CheckResult("串流", bool(result.text), detail=f"TTFT {ttft}，{tps}", elapsed_s=result.latency_s)

    return _timed("串流", run)


def check_json_mode(provider: Provider, model: str | None = None) -> CheckResult:
    if not provider.supports_json_mode:
        return CheckResult("JSON 模式", True, detail="這家不支援，略過", skipped=True)

    def run() -> CheckResult:
        result = chat(
            provider.key,
            [
                {"role": "system", "content": "只輸出 JSON，不要有任何其他文字或 markdown 圍欄。"},
                {"role": "user", "content": '產生 {"city": "高雄", "ok": true} 這個物件。'},
            ],
            model=model,
            response_format={"type": "json_object"},
            max_tokens=100,
            temperature=0,
        )
        payload = json.loads(result.text)
        return CheckResult("JSON 模式", isinstance(payload, dict), detail=f"解析成功：{payload}")

    return _timed("JSON 模式", run)


def check_vision(provider: Provider, model: str | None = None) -> CheckResult:
    if not provider.supports_vision:
        return CheckResult("視覺輸入", True, detail="這家不支援，略過", skipped=True)

    def run() -> CheckResult:
        result = chat(
            provider.key,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "這張圖是什麼顏色？只回顏色名稱。"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{RED_SQUARE_PNG_B64}"},
                        },
                    ],
                }
            ],
            model=model,
            max_tokens=20,
            temperature=0,
        )
        answer = result.text.strip()
        hit = any(word in answer.lower() for word in ("紅", "red"))
        return CheckResult("視覺輸入", hit, detail=f"回答 {answer[:30]!r}（預期紅色）")

    return _timed("視覺輸入", run)


ALL_CHECKS = [check_ping, check_models, check_streaming, check_json_mode, check_vision]


def run_all(provider: Provider, model: str | None = None) -> ProviderReport:
    report = ProviderReport(provider=provider)
    for check in ALL_CHECKS:
        if check is check_models:
            report.results.append(check(provider))
        else:
            report.results.append(check(provider, model))
    return report
