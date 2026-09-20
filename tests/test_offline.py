"""不用連外網、不用金鑰就能跑的測試。

用途是在你還沒申請完 key 之前，先確認整套邏輯（尤其是 fallback router）是對的。
跑法：pytest -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmclab import client as client_mod  # noqa: E402
from llmclab.client import AllProvidersFailed, Attempt, ChatResult, Router, _message_text, _ollama_root, _with_provider_options  # noqa: E402
from llmclab.compare import (  # noqa: E402
    CASES,
    DEEP_CASES,
    contains,
    exact_lines,
    fraction_is,
    has_cjk,
    is_chat_model,
    json_has,
    no_latin,
    not_contains,
    number_is,
    selected_cases,
    yes_zh,
)
from llmclab.config import DEFAULT_ORDER, PROVIDERS, slot_env_names  # noqa: E402
from llmclab.ratelimit import parse_duration, parse_headers  # noqa: E402


# ------------------------------------------------------------ 註冊表


def test_registry_is_consistent():
    assert set(DEFAULT_ORDER) == set(PROVIDERS)
    assert DEFAULT_ORDER == ["groq", "gemini", "mistral", "iai", "local"]
    assert DEFAULT_ORDER[-1] == "local"
    for name, p in PROVIDERS.items():
        assert p.key == name
        assert p.env_var.endswith("_API_KEY")
        if p.is_local:
            assert p.base_url.startswith("http://")
            assert not p.requires_key
        else:
            assert p.base_url.startswith("https://")
            assert p.console_url.startswith("https://")
            assert p.requires_key


def test_masked_key_hides_secret(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_abcdefghijklmnop")
    masked = PROVIDERS["groq"].masked_key()
    assert "efghijkl" not in masked
    assert masked.startswith("gsk_ab")


def test_slot_env_names_match_dotenv_example():
    assert slot_env_names("GROQ_API_KEY", 3) == (
        "GROQ_API_KEY",
        "GROQ_API_KEY2",
        "GROQ_API_KEY3",
    )


def test_key_slots_collects_numbered_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "aaa")
    monkeypatch.setenv("GROQ_API_KEY2", "bbb")
    monkeypatch.setenv("GROQ_API_KEY3", "ccc")
    slots = PROVIDERS["groq"].key_slots()
    assert [s.env_var for s in slots] == ["GROQ_API_KEY", "GROQ_API_KEY2", "GROQ_API_KEY3"]
    assert [s.value for s in slots] == ["aaa", "bbb", "ccc"]


def test_only_key2_still_counts_as_configured(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY2", "backup")
    p = PROVIDERS["groq"]
    assert p.configured
    assert p.api_key == "backup"
    assert p.key_slots()[0].env_var == "GROQ_API_KEY2"


# ------------------------------------------------------------ 配額 header


@pytest.mark.parametrize(
    "value,expected",
    [("2.5s", 2.5), ("6m11.52s", 371.52), ("1h", 3600.0), ("45", 45.0), ("", None), ("abc", None)],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


def test_parse_headers_normalises_names():
    info = parse_headers({
        "x-ratelimit-limit-requests": "14400",
        "x-ratelimit-remaining-requests": "14392",
        "x-ratelimit-remaining-tokens": "5800",
        "x-ratelimit-reset-requests": "6m11.52s",
        "retry-after": "12",
        "content-type": "application/json",
    })
    assert info.remaining_requests == "14392"
    assert info.limit_requests == "14400"
    assert info.remaining_tokens == "5800"
    assert info.retry_after_s == 12.0
    assert "content-type" not in info.raw
    assert "req 14392/14400" in info.summary()


def test_parse_headers_empty():
    assert parse_headers(None).has_data is False
    assert "沒回傳" in parse_headers({}).summary()


# ------------------------------------------------------------ Router


class FakeError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status_code = status


@pytest.fixture
def all_keys(monkeypatch):
    for p in PROVIDERS.values():
        monkeypatch.setenv(p.env_var, "test-key")


def _patch_chat(monkeypatch, behaviour: dict[str, object]):
    """behaviour: provider -> 例外實例，或代表成功的字串。"""

    def fake_chat(provider_name, messages, *, model=None, **kwargs):
        outcome = behaviour[provider_name]
        if isinstance(outcome, Exception):
            raise outcome
        return ChatResult(provider=provider_name, model=model or "m", text=str(outcome), latency_s=0.01)

    monkeypatch.setattr(client_mod, "chat", fake_chat)


def test_router_uses_first_healthy_provider(all_keys, monkeypatch):
    _patch_chat(monkeypatch, {"groq": "來自 groq", "gemini": "x", "mistral": "x", "iai": "x", "local": "x"})
    result = Router(DEFAULT_ORDER, sleep=lambda s: None).chat([{"role": "user", "content": "hi"}])
    assert result.provider == "groq"
    assert len(result.attempts) == 1


def test_router_falls_through_on_429(all_keys, monkeypatch):
    _patch_chat(monkeypatch, {
        "groq": FakeError(429),
        "gemini": FakeError(429),
        "mistral": "由 mistral 接手",
        "iai": "不該輪到 iAI",
        "local": "不該輪到本機",
    })
    slept: list[float] = []
    router = Router(DEFAULT_ORDER, retries_per_provider=1, sleep=slept.append)
    result = router.chat([{"role": "user", "content": "hi"}])

    assert result.provider == "mistral"
    assert result.text == "由 mistral 接手"
    assert slept, "遇到 429 應該要有退避等待"
    assert [a.provider for a in result.attempts if not a.ok][:1] == ["groq"]


def test_router_does_not_retry_auth_errors(all_keys, monkeypatch):
    """401 重試幾次都一樣，應該立刻換下一家而不是浪費時間等。"""
    _patch_chat(monkeypatch, {"groq": FakeError(401), "gemini": "ok", "mistral": "x", "iai": "x", "local": "x"})
    slept: list[float] = []
    result = Router(DEFAULT_ORDER, retries_per_provider=3, sleep=slept.append).chat([])
    assert result.provider == "gemini"
    assert slept == []


def test_router_skips_unconfigured_providers(monkeypatch):
    for p in PROVIDERS.values():
        monkeypatch.delenv(p.env_var, raising=False)
        if p.base_url_env:
            monkeypatch.delenv(p.base_url_env, raising=False)
        if p.model_env:
            monkeypatch.delenv(p.model_env, raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    _patch_chat(monkeypatch, {"mistral": "只有它有 key"})

    result = Router(DEFAULT_ORDER, sleep=lambda s: None).chat([])
    assert result.provider == "mistral"
    skipped = [a for a in result.attempts if not a.ok]
    assert all("未設定" in (a.error or "") for a in skipped)


def test_router_raises_when_everything_fails(all_keys, monkeypatch):
    _patch_chat(monkeypatch, {n: FakeError(503) for n in DEFAULT_ORDER})
    with pytest.raises(AllProvidersFailed) as excinfo:
        Router(DEFAULT_ORDER, retries_per_provider=0, sleep=lambda s: None).chat([])
    assert len(excinfo.value.attempts) == len(DEFAULT_ORDER)


def test_router_rotates_to_next_key_on_429(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "key-a")
    monkeypatch.setenv("GROQ_API_KEY2", "key-b")
    seen: list[str | None] = []

    def fake_chat(provider_name, messages, *, model=None, api_key=None, **kwargs):
        seen.append(api_key)
        if api_key == "key-a":
            raise FakeError(429)
        return ChatResult(provider=provider_name, model=model or "m", text="第二把接手", latency_s=0.01)

    monkeypatch.setattr(client_mod, "chat", fake_chat)
    result = Router(["groq"], retries_per_key=0, sleep=lambda s: None).chat([])
    assert result.text == "第二把接手"
    assert seen == ["key-a", "key-b"]
    assert result.attempts[0].key_env == "GROQ_API_KEY"
    assert result.attempts[1].key_env == "GROQ_API_KEY2"


def test_router_skips_dead_key_on_401(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dead")
    monkeypatch.setenv("GROQ_API_KEY2", "live")
    slept: list[float] = []

    def fake_chat(provider_name, messages, *, model=None, api_key=None, **kwargs):
        if api_key == "dead":
            raise FakeError(401)
        return ChatResult(provider=provider_name, model=model or "m", text="ok", latency_s=0.01)

    monkeypatch.setattr(client_mod, "chat", fake_chat)
    result = Router(["groq"], retries_per_key=3, sleep=slept.append).chat([])
    assert result.text == "ok"
    assert slept == []


def test_router_400_skips_remaining_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "a")
    monkeypatch.setenv("GROQ_API_KEY2", "b")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    seen: list[tuple[str, str | None]] = []

    def fake_chat(provider_name, messages, *, model=None, api_key=None, **kwargs):
        seen.append((provider_name, api_key))
        if provider_name == "groq":
            raise FakeError(400)
        return ChatResult(provider=provider_name, model=model or "m", text="gemini", latency_s=0.01)

    monkeypatch.setattr(client_mod, "chat", fake_chat)
    result = Router(["groq", "gemini"], retries_per_key=2, sleep=lambda s: None).chat([])
    assert result.provider == "gemini"
    assert seen == [("groq", "a"), ("gemini", "g")]


def test_router_respects_max_attempts_per_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "a")
    monkeypatch.setenv("GROQ_API_KEY2", "b")
    monkeypatch.setenv("GROQ_API_KEY3", "c")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    seen: list[str | None] = []

    def fake_chat(provider_name, messages, *, model=None, api_key=None, **kwargs):
        seen.append(api_key)
        if provider_name == "groq":
            raise FakeError(429)
        return ChatResult(provider=provider_name, model=model or "m", text="gemini", latency_s=0.01)

    monkeypatch.setattr(client_mod, "chat", fake_chat)
    result = Router(
        ["groq", "gemini"], retries_per_key=0, max_attempts_per_provider=2, sleep=lambda s: None
    ).chat([])
    assert result.provider == "gemini"
    assert seen == ["a", "b", "g"]


def test_router_falls_through_to_local(all_keys, monkeypatch):
    _patch_chat(
        monkeypatch,
        {
            "groq": FakeError(429),
            "gemini": FakeError(429),
            "mistral": FakeError(429),
            "iai": FakeError(429),
            "local": "本機 Qwen 接手",
        },
    )
    result = Router(DEFAULT_ORDER, retries_per_provider=0, sleep=lambda s: None).chat([])
    assert result.provider == "local"
    assert result.text == "本機 Qwen 接手"
    assert [a.provider for a in result.attempts if not a.ok] == ["groq", "gemini", "mistral", "iai"]


def test_local_opt_in_via_base_url_without_key(monkeypatch):
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")
    p = PROVIDERS["local"]
    assert p.configured
    assert p.api_key == "ollama"
    assert p.resolved_base_url == "http://127.0.0.1:11434/v1"
    assert p.key_slots()[0].env_var == "LOCAL_API_KEY"


def test_local_model_override(monkeypatch):
    monkeypatch.delenv("LOCAL_MODEL", raising=False)
    assert PROVIDERS["local"].resolved_model == "qwen3.5:4b"
    monkeypatch.setenv("LOCAL_MODEL", "qwen3.5:4b-q4_K_M")
    assert PROVIDERS["local"].resolved_model == "qwen3.5:4b-q4_K_M"


def test_local_not_configured_by_default(monkeypatch):
    monkeypatch.delenv("LOCAL_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_BASE_URL", raising=False)
    assert not PROVIDERS["local"].configured


def test_local_extra_body_disables_think():
    kwargs = _with_provider_options(PROVIDERS["local"], {"max_tokens": 16})
    assert kwargs["max_tokens"] == 16
    assert kwargs["extra_body"]["think"] is False


def test_groq_extra_body_lowers_reasoning():
    kwargs = _with_provider_options(PROVIDERS["groq"], {"max_tokens": 16})
    assert kwargs["extra_body"]["reasoning_effort"] == "low"


class _Msg:
    def __init__(self, content=None, **extra):
        self.content = content
        self.model_extra = extra


def test_message_text_prefers_content():
    assert _message_text(_Msg(content="你好", reasoning="思考中")) == "你好"


def test_message_text_falls_back_to_reasoning():
    assert _message_text(_Msg(content="", reasoning_content="會")) == "會"


def test_ollama_root_strips_openai_suffix():
    assert _ollama_root("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"
    assert _ollama_root("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434"


def test_local_extra_body_caller_override():
    kwargs = _with_provider_options(PROVIDERS["local"], {"extra_body": {"think": True}})
    assert kwargs["extra_body"]["think"] is True


def test_router_uses_local_timeout(monkeypatch):
    monkeypatch.setenv("LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")
    seen: list[float | None] = []

    def fake_chat(provider_name, messages, *, timeout=None, **kwargs):
        seen.append(timeout)
        return ChatResult(provider=provider_name, model="m", text="ok", latency_s=0.01)

    monkeypatch.setattr(client_mod, "chat", fake_chat)
    Router(["local"], sleep=lambda s: None, timeout=30).chat([])
    assert seen == [180.0]


# ------------------------------------------------------------ 其他


def test_tokens_per_second_math():
    r = ChatResult("groq", "m", "x", latency_s=2.0, ttft_s=0.5, completion_tokens=150)
    assert r.tokens_per_s == pytest.approx(100.0)


def test_attempt_defaults():
    a = Attempt("groq", "m", False, error="boom")
    assert a.waited_s == 0.0 and a.status is None


def test_iai_provider_shape():
    p = PROVIDERS["iai"]
    assert p.base_url.endswith("/aihub/v1")
    assert p.env_var == "IAI_API_KEY"
    assert p.default_model == "Furen-large"
    assert p.model_env == "IAI_MODEL"
    assert DEFAULT_ORDER[-2] == "iai"


def test_compare_suite_covers_conversation_and_logic():
    cats = {c.category for c in CASES}
    assert cats == {"conversation", "logic"}
    assert len(CASES) >= 6


def test_compare_graders():
    assert has_cjk(6)("你好，我是評測助手，很高興認識你。")[0]
    assert not has_cjk(6)("hello")[0]
    assert contains("林小華", "台南")("你是林小華，喜歡台南。")[0]
    assert not contains("林小華", "台南")("我叫小華，住高雄。")[0]
    assert contains("河愛雄高")("河愛雄高")[0]
    assert number_is(408)("答案是 408。")[0]
    assert not number_is(408)("17 和 24")[0]
    assert yes_zh(True)("會")[0]
    assert not yes_zh(True)("不會")[0]
    assert fraction_is(3, 5)("3/5")[0]
    assert fraction_is(3, 5)("0.6")[0]


def test_deep_suite_has_harder_categories():
    cats = {c.category for c in DEEP_CASES}
    assert cats == {"instruction", "reasoning", "code", "language"}
    assert len(selected_cases(suite="deep")) == len(DEEP_CASES)
    assert len(selected_cases(suite="simple")) == len(CASES)


def test_deep_graders():
    assert exact_lines("7", "2", "9")("7\n2\n9")[0]
    assert not exact_lines("7", "2", "9")("7\n2\n9\n謝謝")[0]
    assert json_has("name", "price")('{"name":"豆瓣魚","price":220}')[0]
    assert no_latin()("加油，辛苦了。")[0]
    assert not no_latin()("加油 OK")[0]
    assert not_contains("高雄")("我可以幫你寫程式。")[0]
    assert not not_contains("高雄")("我是高雄的助理")[0]


def test_iai_chat_model_classifier():
    assert is_chat_model("Furen-large")
    assert is_chat_model("Nkust")
    assert is_chat_model("nemotron-3-super-120b")
    assert not is_chat_model("Embedding")
    assert not is_chat_model("bge-m3-embedding")
    assert not is_chat_model("Furen-reranker")
    assert not is_chat_model("Pic-small")
    assert not is_chat_model("Asr")
    assert not is_chat_model("Speaker")
