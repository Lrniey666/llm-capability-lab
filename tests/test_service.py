"""HTTP 服務層的測試。

不需金鑰、不連外網：起一個本機 mock 端點當成 provider，
再用 TestClient 走完整條 FastAPI 路由，確認轉移結果有正確翻譯成 HTTP。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastapi", reason="需要 [serve] 額外依賴")

from fastapi.testclient import TestClient  # noqa: E402

from llmclab import config as config_mod  # noqa: E402
from llmclab import service as service_mod  # noqa: E402
from llmclab.config import Provider  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


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
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "服務層收到"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("x-ratelimit-remaining-requests", "99")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


@pytest.fixture(scope="module")
def mock_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


@pytest.fixture
def mock_registered(mock_url, monkeypatch):
    """把 mock 註冊進 PROVIDERS，讓 Router.from_env 與 client.get 都找得到。"""
    provider = Provider(
        key="mock",
        label="Mock",
        base_url=mock_url,
        env_var="MOCK_API_KEY",
        default_model="mock-model",
        console_url="https://example.com",
        limits_url="https://example.com",
        supports_vision=True,
    )
    monkeypatch.setenv("MOCK_API_KEY", "key-1")
    monkeypatch.setitem(config_mod.PROVIDERS, "mock", provider)
    return provider


@pytest.fixture
def client(mock_registered):
    return TestClient(service_mod.create_app(token=TOKEN))


# --- 設定安全性 --------------------------------------------------------------


def test_refuses_to_start_without_token(monkeypatch):
    monkeypatch.delenv(service_mod.TOKEN_ENV, raising=False)
    monkeypatch.delenv(service_mod.ALLOW_ANON_ENV, raising=False)
    with pytest.raises(service_mod.ServiceConfigError, match=service_mod.TOKEN_ENV):
        service_mod.create_app(token="")


def test_anonymous_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv(service_mod.TOKEN_ENV, raising=False)
    monkeypatch.setenv(service_mod.ALLOW_ANON_ENV, "1")
    token, anon = service_mod.resolve_token()
    assert token == "" and anon is True


# --- meta 端點 ---------------------------------------------------------------


def test_healthz_needs_no_token(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert "providers_ready" in resp.json()


def test_providers_requires_token(client):
    assert client.get("/v1/providers").status_code == 401
    resp = client.get("/v1/providers", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["vision_order"] == service_mod.vision_order()
    # 不該把金鑰內容洩出去，只給數量
    assert all("api_key" not in p for p in body["providers"])


def test_vision_order_is_derived_from_config():
    order = service_mod.vision_order()
    assert order, "至少要有一家支援視覺"
    assert all(config_mod.PROVIDERS[name].supports_vision for name in order)
    assert "groq" not in order  # groq 在 config 裡標記為不支援視覺


# --- /v1/chat ----------------------------------------------------------------


def test_chat_returns_result_and_routing_metadata(client):
    resp = client.post(
        "/v1/chat",
        headers=AUTH,
        json={"prompt": "嗨", "system": "簡潔", "order": ["mock"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "服務層收到"
    assert body["provider"] == "mock"
    assert body["completion_tokens"] == 5
    assert body["latency_s"] > 0
    # 配額只在 header，翻譯層沒接好就會是空的
    assert "req 99" in body["rate_limit"]
    assert body["attempts"] and body["attempts"][-1]["ok"] is True


def test_chat_rejects_empty_request(client):
    resp = client.post("/v1/chat", headers=AUTH, json={"order": ["mock"]})
    assert resp.status_code == 422


def test_chat_requires_token(client):
    assert client.post("/v1/chat", json={"prompt": "嗨"}).status_code == 401


def test_chat_reports_attempts_when_everything_fails(client, monkeypatch):
    broken = Provider(
        key="mock",
        label="Mock",
        base_url="http://127.0.0.1:9/v1",  # discard port：必定連不上
        env_var="MOCK_API_KEY",
        default_model="mock-model",
        console_url="https://example.com",
        limits_url="https://example.com",
    )
    monkeypatch.setitem(config_mod.PROVIDERS, "mock", broken)
    resp = client.post(
        "/v1/chat",
        headers=AUTH,
        json={"prompt": "嗨", "order": ["mock"], "timeout": 1, "retries_per_key": 0},
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "all_providers_failed"
    assert detail["attempts"], "失敗時要把每一次嘗試回報出去，否則無從除錯"


# --- /v1/menu ----------------------------------------------------------------


def test_menu_rejects_empty_upload(client):
    resp = client.post("/v1/menu", headers=AUTH, files={"image": ("a.jpg", b"", "image/jpeg")})
    assert resp.status_code == 422


def test_menu_rejects_oversized_upload(client):
    blob = b"x" * (service_mod.MAX_UPLOAD_BYTES + 1)
    resp = client.post(
        "/v1/menu", headers=AUTH, files={"image": ("big.jpg", blob, "image/jpeg")}
    )
    assert resp.status_code == 413


def test_menu_requires_token(client):
    resp = client.post("/v1/menu", files={"image": ("a.jpg", b"xx", "image/jpeg")})
    assert resp.status_code == 401
