"""延遲／吞吐量量測。

刻意做成序列而非並發：免費層的 RPM 很低，並發打過去只會量到 429 的速度。
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

from .client import chat, is_transient
from .config import Provider

DEFAULT_PROMPT = "用三句話說明什麼是 rate limit。"


@dataclass
class BenchResult:
    provider: str
    model: str
    runs: int
    ttft_ms: list[float] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)
    tps: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rate_limited: int = 0

    @property
    def ok_runs(self) -> int:
        return len(self.total_ms)

    def _p(self, data: list[float], q: float) -> float | None:
        if not data:
            return None
        ordered = sorted(data)
        idx = min(int(q * len(ordered)), len(ordered) - 1)
        return ordered[idx]

    @property
    def ttft_p50(self) -> float | None:
        return self._p(self.ttft_ms, 0.5)

    @property
    def total_p50(self) -> float | None:
        return self._p(self.total_ms, 0.5)

    @property
    def total_p95(self) -> float | None:
        return self._p(self.total_ms, 0.95)

    @property
    def mean_tps(self) -> float | None:
        return statistics.mean(self.tps) if self.tps else None


def benchmark(
    provider: Provider,
    *,
    runs: int = 5,
    prompt: str = DEFAULT_PROMPT,
    model: str | None = None,
    gap_s: float = 1.2,
    max_tokens: int = 200,
    on_run=None,
) -> BenchResult:
    """跑 runs 次串流請求，量 TTFT / 總時長 / TPS。

    gap_s 預設 1.2 秒是為了配合 Mistral 約 1 req/s 的限制——
    調低會讓 Mistral 那欄變成在量 429 而不是在量效能。
    """
    model = model or provider.resolved_model
    result = BenchResult(provider=provider.key, model=model, runs=runs)

    for i in range(runs):
        try:
            res = chat(
                provider.key,
                [{"role": "user", "content": prompt}],
                model=model,
                stream=True,
                max_tokens=max_tokens,
                temperature=0.2,
            )
            result.total_ms.append(res.latency_s * 1000)
            if res.ttft_s:
                result.ttft_ms.append(res.ttft_s * 1000)
            if res.tokens_per_s:
                result.tps.append(res.tokens_per_s)
        except Exception as exc:  # noqa: BLE001
            if is_transient(exc):
                result.rate_limited += 1
            result.errors.append(" ".join(str(exc).split())[:120])

        if on_run:
            on_run(i + 1, runs)
        if i < runs - 1:
            time.sleep(gap_s)

    return result
