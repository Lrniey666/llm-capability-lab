"""多金鑰輪替實機實驗。金鑰只印遮罩，不寫進任何檔案。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmclab.client import AllProvidersFailed, Router, chat, make_client
from llmclab.config import DEFAULT_ORDER, PROVIDERS, load_env, mask_secret

PROMPT = [{"role": "user", "content": "只回兩個字：收到"}]


def _status(exc: Exception) -> str:
    code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    text = " ".join(str(exc).split())[:100]
    return f"{code or type(exc).__name__} {text}"


def probe_slots() -> None:
    print("=== A. 九槽連通（models.list，不走聊天）===")
    for name in DEFAULT_ORDER:
        p = PROVIDERS[name]
        for slot in p.key_slots():
            try:
                started = time.perf_counter()
                models = list(make_client(p, timeout=20, api_key=slot.value).models.list())
                elapsed = (time.perf_counter() - started) * 1000
                print(f"  ✓ {name:8} {slot.env_var:18} {mask_secret(slot.value):12} {len(models):3} models  {elapsed:.0f} ms")
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {name:8} {slot.env_var:18} {mask_secret(slot.value):12} {_status(exc)}")
            time.sleep(0.4)


def fmt_attempts(attempts) -> str:
    parts = []
    for a in attempts:
        mark = "✓" if a.ok else "✗"
        err = f" {a.status or ''} {(a.error or '')[:70]}" if not a.ok else ""
        parts.append(f"{mark} {a.provider}/{a.key_env or '-'}{err}")
    return "\n    ".join(parts)


def exp_401_rotate() -> None:
    print("\n=== B. 401：把 Groq 第一把改成無效值，應立刻改用 KEY2 ===")
    original = os.environ.get("GROQ_API_KEY", "")
    os.environ["GROQ_API_KEY"] = "gsk_invalid_rotate_experiment"
    try:
        router = Router(["groq"], retries_per_key=0, timeout=30, verbose=True)
        result = router.chat(PROMPT, max_tokens=16)
        print(f"  成功：{result.provider}/{result.key_env}  {result.latency_s*1000:.0f} ms  {result.text[:20]!r}")
        print(f"  嘗試：\n    {fmt_attempts(result.attempts)}")
    except AllProvidersFailed as exc:
        print(f"  全部失敗：\n    {fmt_attempts(exc.attempts)}")
    finally:
        os.environ["GROQ_API_KEY"] = original


def exp_400_skip_sibling_keys() -> None:
    print("\n=== C. 400：Groq 用不存在的模型，應跳過 KEY2/KEY3 改打 Gemini ===")
    time.sleep(1.2)
    router = Router(["groq", "gemini"], retries_per_key=0, timeout=40, verbose=True)
    try:
        result = router.chat(PROMPT, model_overrides={"groq": "this-model-does-not-exist"}, max_tokens=16)
        print(f"  成功：{result.provider}/{result.key_env}  {result.latency_s*1000:.0f} ms  {result.text[:20]!r}")
        print(f"  嘗試：\n    {fmt_attempts(result.attempts)}")
    except AllProvidersFailed as exc:
        print(f"  全部失敗：\n    {fmt_attempts(exc.attempts)}")


def exp_natural_fallback() -> None:
    print("\n=== D. 正常 fallback：三家、每家最多 3 次、每把不重試 ===")
    time.sleep(1.2)
    router = Router(DEFAULT_ORDER, retries_per_key=0, max_attempts_per_provider=3, timeout=40, verbose=True)
    try:
        result = router.chat(PROMPT, max_tokens=16)
        print(f"  成功：{result.provider}/{result.key_env}  {result.latency_s*1000:.0f} ms  {result.text[:20]!r}")
        print(f"  嘗試：\n    {fmt_attempts(result.attempts)}")
        print(f"  配額：{result.rate_limit.summary()}")
    except AllProvidersFailed as exc:
        print(f"  全部失敗：\n    {fmt_attempts(exc.attempts)}")


def exp_same_provider_chat_keys() -> None:
    print("\n=== E. 同家三把金鑰各打一次聊天（看是否同分額度）===")
    for name in DEFAULT_ORDER:
        p = PROVIDERS[name]
        print(f"  {p.label}")
        for slot in p.key_slots():
            try:
                result = chat(name, PROMPT, api_key=slot.value, key_env=slot.env_var, max_tokens=16)
                print(
                    f"    ✓ {slot.env_var:18} {result.latency_s*1000:.0f} ms  "
                    f"{result.text[:12]!r}  {result.rate_limit.summary()}"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    ✗ {slot.env_var:18} {_status(exc)}")
            time.sleep(1.2)


def main() -> int:
    load_env()
    probe_slots()
    exp_401_rotate()
    exp_400_skip_sibling_keys()
    exp_natural_fallback()
    exp_same_provider_chat_keys()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
