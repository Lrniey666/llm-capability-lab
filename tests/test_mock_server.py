"""用本機假伺服器驗證 client 的接線是否正確。

不用金鑰、不連外網，但走的是真正的本機 HTTP + 真正的 PyPI `openai` 用戶端，
所以能抓到「header 沒讀到」「串流沒解析」這類只有實際跑才會現形的錯。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmclab import client as client_mod  # noqa: E402
from llmclab.config import Provider  # noqa: E402

RATE_LIMIT_HEADERS = {
    "x-ratelimit-limit-requests": "14400",
    "x-ratelimit-remaining-requests": "14399",
    "x-ratelimit-limit-tokens": "6000",
    "x-ratelimit-remaining-tokens": "5987",
    "x-ratelimit-reset-requests": "2m30s",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 別把測試輸出洗版
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("stream"):
            self._stream()
        else:
            self._json(body)

    def _headers(self, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        for key, value in RATE_LIMIT_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()

    def _json(self, body):
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "收到"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        }
        self._headers("application/json")
        self.wfile.write(json.dumps(payload).encode())

    def _stream(self):
        self._headers("text/event-stream")
        for piece in ("一", "二", "三"):
            chunk = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "mock",
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


@pytest.fixture(scope="module")
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


@pytest.fixture
def mock_provider(mock_server, monkeypatch):
    provider = Provider(
        key="mock",
        label="Mock",
        base_url=mock_server,
        env_var="MOCK_API_KEY",
        default_model="mock-model",
        console_url="https://example.com",
        limits_url="https://example.com",
        supports_vision=True,
    )
    monkeypatch.setenv("MOCK_API_KEY", "test-key")
    monkeypatch.setitem(client_mod.__dict__, "get", lambda name: provider)
    return provider


def test_non_stream_reads_body_and_headers(mock_provider):
    result = client_mod.chat("mock", [{"role": "user", "content": "hi"}])

    assert result.text == "收到"
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 3
    assert result.latency_s > 0
    # 關鍵：配額資訊只存在於 header，with_raw_response 沒接好就會是空的
    assert result.rate_limit.remaining_requests == "14399"
    assert result.rate_limit.remaining_tokens == "5987"
    assert "req 14399/14400" in result.rate_limit.summary()


def test_stream_measures_ttft(mock_provider):
    result = client_mod.chat("mock", [{"role": "user", "content": "hi"}], stream=True)

    assert result.text == "一二三"
    assert result.ttft_s is not None and result.ttft_s > 0
    assert result.ttft_s <= result.latency_s


def test_make_client_returns_project_class(mock_provider):
    client = client_mod.make_client(mock_provider)
    assert type(client) is client_mod.ChatCompletionsClient
    assert type(client).__module__.startswith("llmclab")


def test_missing_key_gives_actionable_error(mock_provider, monkeypatch):
    monkeypatch.delenv("MOCK_API_KEY")
    with pytest.raises(RuntimeError, match="MOCK_API_KEY"):
        client_mod.chat("mock", [{"role": "user", "content": "hi"}])
