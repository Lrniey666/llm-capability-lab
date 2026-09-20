"""驗證「被其他專案當模組匯入」這條路徑。

這些測試不需要金鑰也不連外網，但會實際走 import、路徑解析與 Router 接線，
因為模組化最容易壞在「裝到別的地方就找不到 .env / 研究資產」這類問題上。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llmclab  # noqa: E402
from llmclab import client as client_mod  # noqa: E402
from llmclab import config as config_mod  # noqa: E402
from llmclab.config import Provider  # noqa: E402


def test_public_api_all_resolves():
    missing = [name for name in llmclab.__all__ if not hasattr(llmclab, name)]
    assert missing == [], f"__all__ 列了但實際沒有：{missing}"


def test_version_is_declared():
    assert llmclab.__version__, "版本號寫在 llmclab.__version__，由 setuptools dynamic metadata 讀入"


def test_find_dotenv_does_not_escape_project(tmp_path, monkeypatch):
    outer = tmp_path / "outer"
    proj = outer / "proj"
    sub = proj / "app" / "deep"
    sub.mkdir(parents=True)
    (proj / ".git").mkdir()
    (outer / ".env").write_text("LEAKED=1", encoding="utf-8")

    # 套件自己的 repo 根有 .env 時會是 fallback，測試裡要排除這個干擾
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path / "nowhere")

    assert config_mod.find_dotenv(sub) is None, "不該撈到專案邊界之外的 .env"

    (proj / ".env").write_text("OK=1", encoding="utf-8")
    assert config_mod.find_dotenv(sub) == proj / ".env"


def test_workspace_root_honours_override(tmp_path, monkeypatch):
    monkeypatch.setenv(config_mod.WORKSPACE_ENV, str(tmp_path))
    assert config_mod.workspace_root() == tmp_path.resolve()


def test_require_workspace_message_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setenv(config_mod.WORKSPACE_ENV, str(tmp_path))
    with pytest.raises(RuntimeError) as excinfo:
        config_mod.require_workspace()
    assert config_mod.WORKSPACE_ENV in str(excinfo.value)


def test_require_workspace_accepts_real_checkout(monkeypatch):
    monkeypatch.delenv(config_mod.WORKSPACE_ENV, raising=False)
    assert (config_mod.require_workspace() / "menu_example").is_dir()


def test_from_env_errors_when_nothing_configured(monkeypatch):
    for provider in config_mod.PROVIDERS.values():
        for name in provider.slot_names():
            monkeypatch.delenv(name, raising=False)
        if provider.base_url_env:
            monkeypatch.delenv(provider.base_url_env, raising=False)
    monkeypatch.setattr(config_mod, "load_env", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match=r"\.env"):
        client_mod.Router.from_env()


# --- achat 需要一個會回話的端點 ---------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": body["model"],
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "非同步收到"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


@pytest.fixture(scope="module")
def mock_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


@pytest.fixture
def mock_provider(mock_url, monkeypatch):
    provider = Provider(
        key="mock",
        label="Mock",
        base_url=mock_url,
        env_var="MOCK_API_KEY",
        default_model="mock-model",
        console_url="https://example.com",
        limits_url="https://example.com",
    )
    monkeypatch.setenv("MOCK_API_KEY", "test-key")
    monkeypatch.setitem(client_mod.__dict__, "get", lambda name: provider)
    return provider


def test_achat_runs_chat_off_the_event_loop(mock_provider):
    """achat 的契約是「不要在 event loop 執行緒上跑阻塞呼叫」。

    直接比對執行緒 id，比量心跳可靠——Windows 的計時器解析度約 15ms，
    用 sleep 當探針只會測到計時器精度。
    """
    router = client_mod.Router(["mock"])
    seen: dict[str, int] = {}
    real_chat = router.chat

    def recording_chat(*args, **kwargs):
        seen["worker"] = threading.get_ident()
        return real_chat(*args, **kwargs)

    router.chat = recording_chat  # type: ignore[method-assign]

    async def scenario():
        seen["loop"] = threading.get_ident()
        return await router.achat([{"role": "user", "content": "hi"}])

    result = asyncio.run(scenario())
    assert result.text == "非同步收到"
    assert seen["worker"] != seen["loop"], "achat 在 event loop 執行緒上跑了阻塞呼叫"


def test_ask_delegates_to_default_router(mock_provider, monkeypatch):
    llmclab.reset_default_router()
    monkeypatch.setattr(llmclab, "_DEFAULT_ROUTER", client_mod.Router(["mock"]))
    result = llmclab.ask("嗨", system="簡潔回答")
    assert result.text == "非同步收到"
    llmclab.reset_default_router()
