"""模擬多位用戶打 Discord bot 時，三家獨立 vs 每家三把 key 的影響。

配額數字來自 2026-09-15 實驗與 Gemini 免費層實測。
同專案多把 key 共用一個桶（實驗 E）；獨立帳號才會複製桶。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# ----- 免費層上限（實驗當日）-----
GROQ_RPM, GROQ_TPM = 1000, 8000  # gpt-oss-20b header
GEMINI_RPM, GEMINI_RPD = 5, 20
MISTRAL_RPS = 1.0
MISTRAL_TPD = 1_300_000

# 一則短對話（含 system prompt）。Groq 推理模型輸出特別肥。
TOKENS = {"groq": 400, "gemini": 130, "mistral": 130, "local": 130}
LATENCY = {"groq": 0.8, "gemini": 5.0, "mistral": 0.7, "local": 8.0}
FAIL_LAT = 0.25
COOLDOWN_S = 10
THINK_S = 35  # 冷卻後到下一則的平均思考時間
HORIZON_S = 20 * 60
RNG = random.Random(42)


@dataclass
class Bucket:
    """單一廠商的配額桶。rolling 60s + 日額。"""

    rpm: float
    tpm: float
    rpd: float | None = None
    tpd: float | None = None
    min_gap_s: float = 0.0
    reqs: list[float] = field(default_factory=list)
    toks: list[tuple[float, int]] = field(default_factory=list)
    day_req: int = 0
    day_tok: int = 0
    last_ok: float = -1e9

    def prune(self, now: float) -> None:
        cut = now - 60
        self.reqs = [t for t in self.reqs if t > cut]
        self.toks = [(t, n) for t, n in self.toks if t > cut]

    def would_accept(self, now: float, tokens: int) -> bool:
        self.prune(now)
        if now - self.last_ok < self.min_gap_s:
            return False
        if len(self.reqs) >= self.rpm:
            return False
        if sum(n for _, n in self.toks) + tokens > self.tpm:
            return False
        if self.rpd is not None and self.day_req >= self.rpd:
            return False
        if self.tpd is not None and self.day_tok + tokens > self.tpd:
            return False
        return True

    def consume(self, now: float, tokens: int) -> None:
        self.reqs.append(now)
        self.toks.append((now, tokens))
        self.day_req += 1
        self.day_tok += tokens
        self.last_ok = now

    def hit_rpm(self, now: float) -> None:
        """429 仍可能佔一個 request 名額（保守）。"""
        self.reqs.append(now)


def new_pool(independent_keys: int) -> list[Bucket]:
    """independent_keys=1：三把共用一桶；=3：三把各一桶（不同帳號）。"""
    def one() -> dict[str, Bucket]:
        return {
            "groq": Bucket(GROQ_RPM, GROQ_TPM),
            "gemini": Bucket(GEMINI_RPM, 1e9, rpd=GEMINI_RPD),
            "mistral": Bucket(10_000, 1e9, tpd=MISTRAL_TPD, min_gap_s=1.0 / MISTRAL_RPS),
            "local": Bucket(1e9, 1e9),  # 本機無雲端配額，只受機器速度限制
        }

    if independent_keys <= 1:
        return [one()]
    return [one() for _ in range(independent_keys)]


@dataclass
class Outcome:
    ok: bool
    provider: str | None
    attempts: int
    latency: float
    wasted_429: int


def route(
    now: float,
    pools: list[dict[str, Bucket]],
    order: list[str],
    keys_per: int,
    retries_per_key: int,
    shared: bool,
) -> Outcome:
    """shared=True：每家所有 key 打同一個桶。"""
    attempts = 0
    wasted = 0
    lat = 0.0
    for name in order:
        for ki in range(keys_per):
            bucket = pools[0][name] if shared else pools[min(ki, len(pools) - 1)][name]
            for _ in range(retries_per_key + 1):
                attempts += 1
                tokens = TOKENS[name]
                if bucket.would_accept(now + lat, tokens):
                    bucket.consume(now + lat, tokens)
                    lat += LATENCY[name]
                    return Outcome(True, name, attempts, lat, wasted)
                wasted += 1
                lat += FAIL_LAT
    return Outcome(False, None, attempts, lat, wasted)


def arrivals(users: int) -> list[float]:
    """每位用戶：冷卻 + 指數思考。到達與成敗無關，才能公平比架構。"""
    times: list[float] = []
    for _ in range(users):
        t = RNG.random() * 8
        while t < HORIZON_S:
            times.append(t)
            t += COOLDOWN_S + RNG.expovariate(1 / THINK_S)
    times.sort()
    return times


def simulate(
    users: int,
    *,
    order: list[str],
    keys_per: int,
    shared: bool,
    retries_per_key: int,
    schedule: list[float],
) -> dict:
    pools = new_pool(1 if shared else keys_per)
    ok = fail = 0
    by: dict[str, int] = {n: 0 for n in order}
    wasted = 0
    att = 0
    lat_ok: list[float] = []
    lat_all: list[float] = []
    for t in schedule:
        out = route(t, pools, order, keys_per, retries_per_key, shared)
        att += out.attempts
        wasted += out.wasted_429
        lat_all.append(out.latency)
        if out.ok:
            ok += 1
            by[out.provider or ""] += 1
            lat_ok.append(out.latency)
        else:
            fail += 1
    total = ok + fail
    lat_ok.sort()
    p95 = lat_ok[int(0.95 * (len(lat_ok) - 1))] if lat_ok else None
    return {
        "users": users,
        "total": total,
        "ok": ok,
        "fail": fail,
        "ok_rate": ok / total if total else 0,
        "by": by,
        "wasted": wasted,
        "attempts": att,
        "p95_lat": p95,
        "demand_per_min": total / (HORIZON_S / 60),
    }


SHORT = {"groq": "groq", "gemini": "gem", "mistral": "mis", "local": "local"}


def fmt(r: dict) -> str:
    by = " ".join(f"{SHORT.get(k, k)}={v}" for k, v in r["by"].items())
    p95 = f"{r['p95_lat']:.1f}s" if r["p95_lat"] is not None else "—"
    return (
        f"n={r['users']:2}  需求 {r['demand_per_min']:.1f}/min  "
        f"成功 {r['ok_rate']*100:5.1f}%  ({r['ok']}/{r['total']})  "
        f"429浪費 {r['wasted']:4}  p95 {p95:>6}  接手 {by}"
    )


CONFIGS = [
    ("只要 Groq 1 key", ["groq"], 1, True, 0),
    ("Groq 1 key 重試 5 次", ["groq"], 1, True, 5),
    ("Groq 同專案 3 key", ["groq"], 3, True, 1),
    ("只要 Gemini 1 key", ["gemini"], 1, True, 0),
    ("三家各 1 key", ["groq", "gemini", "mistral"], 1, True, 0),
    ("三家各 1 key 重試 5 次", ["groq", "gemini", "mistral"], 1, True, 5),
    ("現況 3×3 共桶 retries=1", ["groq", "gemini", "mistral"], 3, True, 1),
    ("現況 3×3 共桶 retries=0", ["groq", "gemini", "mistral"], 3, True, 0),
    ("若 9 把獨立帳號 retries=0", ["groq", "gemini", "mistral"], 3, False, 0),
    ("三家 + 本機 Qwen 保底", ["groq", "gemini", "mistral", "local"], 1, True, 0),
    ("現況 3×3 + 本機保底", ["groq", "gemini", "mistral", "local"], 3, True, 0),
]


def main() -> None:
    print(f"時長 {HORIZON_S//60} min，冷卻 {COOLDOWN_S}s，思考平均 {THINK_S}s，seed=42\n")
    for users in (5, 15, 30):
        RNG.seed(42)
        schedule = arrivals(users)
        print(f"=== {users} 位用戶 · 同一組到達 {len(schedule)} 則（{len(schedule)/(HORIZON_S/60):.1f}/min）===")
        for title, order, keys, shared, retries in CONFIGS:
            r = simulate(
                users,
                order=order,
                keys_per=keys,
                shared=shared,
                retries_per_key=retries,
                schedule=schedule,
            )
            print(f"  {title:28} {fmt(r)}")
        print()


if __name__ == "__main__":
    main()
