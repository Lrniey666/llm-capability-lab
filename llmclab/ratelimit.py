"""把各家回傳的 rate-limit header 正規化成同一個形狀。

各家 header 名稱不完全一致，所以這裡用「包含 ratelimit / rate-limit」的模糊比對，
而不是寫死欄位名——某一家改名時不會整個壞掉。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

_RESET_RE = re.compile(r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$")


@dataclass
class RateLimitInfo:
    """一次請求之後，我們對剩餘配額知道的一切。"""

    remaining_requests: str | None = None
    limit_requests: str | None = None
    remaining_tokens: str | None = None
    limit_tokens: str | None = None
    reset_requests: str | None = None
    reset_tokens: str | None = None
    retry_after_s: float | None = None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return bool(self.raw)

    def summary(self) -> str:
        parts = []
        if self.remaining_requests is not None:
            total = f"/{self.limit_requests}" if self.limit_requests else ""
            parts.append(f"req {self.remaining_requests}{total}")
        if self.remaining_tokens is not None:
            total = f"/{self.limit_tokens}" if self.limit_tokens else ""
            parts.append(f"tok {self.remaining_tokens}{total}")
        if self.reset_requests:
            parts.append(f"reset {self.reset_requests}")
        if self.retry_after_s:
            parts.append(f"retry-after {self.retry_after_s:g}s")
        return "  ".join(parts) if parts else "（這家沒回傳配額 header）"


def parse_duration(value: str | None) -> float | None:
    """把 '6m11.52s'、'2.5s'、'45' 這類值轉成秒。無法解析時回 None。"""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    match = _RESET_RE.match(value)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parse_headers(headers: Mapping[str, Any] | None) -> RateLimitInfo:
    info = RateLimitInfo()
    if not headers:
        return info

    lowered = {str(k).lower(): str(v) for k, v in headers.items()}

    for name, value in lowered.items():
        if "ratelimit" in name or "rate-limit" in name or name == "retry-after":
            info.raw[name] = value

    def pick(*needles: str) -> str | None:
        for name, value in lowered.items():
            if ("ratelimit" in name or "rate-limit" in name) and all(n in name for n in needles):
                return value
        return None

    info.remaining_requests = pick("remaining", "request")
    info.limit_requests = pick("limit", "request")
    info.remaining_tokens = pick("remaining", "token")
    info.limit_tokens = pick("limit", "token")
    info.reset_requests = pick("reset", "request") or pick("reset")
    info.reset_tokens = pick("reset", "token")
    info.retry_after_s = parse_duration(lowered.get("retry-after"))

    return info


def retry_delay(exc: Exception, attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """優先聽 provider 的 Retry-After，沒有就指數退避。"""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    info = parse_headers(headers)
    if info.retry_after_s:
        return min(info.retry_after_s, cap)
    reset = parse_duration(info.reset_requests) or parse_duration(info.reset_tokens)
    if reset:
        return min(reset, cap)
    return min(base * (2 ** attempt), cap)
