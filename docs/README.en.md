<div align="center">
  <a href="../README.md"><img alt="繁體中文" src="https://img.shields.io/badge/%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87-5b4bd6?style=for-the-badge&labelColor=1d1a3d"></a>
  <a href="#readme"><img alt="English" src="https://img.shields.io/badge/English-0f9d8f?style=for-the-badge&labelColor=1d1a3d"></a>
</div>

<div align="center">
  <img src="assets/hero.svg" alt="llm-capability-lab" width="820">
</div>

<h1 align="center">llm-capability-lab</h1>

<div align="center">
  <strong>It's in the spec. What's the actual case?</strong><br>
  Capability verification and failover routing across LLM providers.
</div>

<div align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.1.0-5b4bd6?style=flat-square&labelColor=1d1a3d">
  <img alt="python" src="https://img.shields.io/badge/python-%E2%89%A53.10-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=1d1a3d">
  <img alt="fastapi" src="https://img.shields.io/badge/HTTP-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white&labelColor=1d1a3d">
  <img alt="tests" src="https://img.shields.io/badge/tests-82-0f9d8f?style=flat-square&labelColor=1d1a3d">
  <img alt="licence" src="https://img.shields.io/badge/licence-MIT-6b6b6b?style=flat-square&labelColor=1d1a3d">
</div>

<div align="center">
  <a href="#features">Features</a> ·
  <a href="#install">Install</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#documentation">Docs</a> ·
  <a href="#contributing">Contributing</a> ·
  <a href="#licence">Licence</a>
</div>

---

## Features

One provider registry, three ways in:

| | Entry point |
|---|---|
| Python library | `import llmclab` |
| HTTP service | `llmclab serve` |
| Research bench | `llmclab vision-menu` |

Failover order: exhaust a provider's key slots, then the next provider, then a local endpoint if one is enabled.

- **`429` / `5xx` / timeout** — retry the same key first (prefer `Retry-After`), then move on
- **`401` / `403`** — the key is invalid; switch immediately
- **`400`** — the request itself is wrong; skip the provider
- **Everything fails** — raises `AllProvidersFailed`; `.attempts` records every try

Built-in Groq, Gemini, Mistral, an optional institutional endpoint, and local [Ollama](https://ollama.com). Cloud calls use Chat Completions (`/v1/chat/completions`); local Ollama uses the native `/api/chat`. The service's `/docs` is the [OpenAPI Specification](https://spec.openapis.org/oas/latest.html) (OAS). That is not Chat Completions, and it is not OpenAI the company. Terms: [docs index](README.md#名詞).

**82 tests:** no outbound network, no provider keys. Some cases start a local HTTP server and drive the real `openai` package and FastAPI routes.

---

## Install

Python 3.10+.

```bash
pip install "git+https://github.com/Lrniey666/llm-capability-lab.git"
pip install "git+https://github.com/Lrniey666/llm-capability-lab.git[serve]"
```

From a source checkout:

```bash
git clone https://github.com/Lrniey666/llm-capability-lab.git
cd llm-capability-lab
pip install -e ".[serve,dev]"
```

Copy `.env.example` to `.env` and fill in the provider keys you want. Unconfigured providers are skipped; import does not fail. Key slots are `GROQ_API_KEY`, `GROQ_API_KEY2`, … (up to `KEY9`). Local fallback also needs `LOCAL_BASE_URL`.

Research modules (vision eval, comparison) need `menu_example/` and `docs/` from a checkout. If the package is installed elsewhere, set `LLMCLAB_WORKSPACE` back at the repo.

---

## Quickstart

### Functions

| Function | Role |
|---|---|
| `llmclab.ask(prompt, *, system=None, **kwargs)` | One prompt; rotates keys and providers on failure |
| `llmclab.Router.from_env(...)` | Build a router from the environment |
| `Router.chat(messages, **kwargs)` | Synchronous chat |
| `await Router.achat(messages, **kwargs)` | Async; blocking I/O is not on the event-loop thread |
| `llmclab.default_router()` / `reset_default_router()` | Process-wide cached `Router` |

Returns `ChatResult` (`.text`, `.provider`, `.model`, `.rate_limit`, `.attempts`). Total failure raises `AllProvidersFailed`. Full list: `llmclab.__all__`.

```python
import llmclab

result = llmclab.ask("Explain RAG in one sentence")
print(result.text, "via", result.provider)
```

```python
from llmclab import Router

router = Router.from_env(retries_per_key=1, timeout=45)
result = router.chat([{"role": "user", "content": "Hello"}])
print(result.provider, result.rate_limit.summary())
```

```python
result = await router.achat(messages, max_tokens=500)
```

### HTTP

```bash
export LLMCLAB_API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
llmclab serve --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/v1/chat \
  -H "Authorization: Bearer $LLMCLAB_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain RAG in one sentence"}'
```

Interactive spec at `/docs` (OAS). Endpoints: [`http-api.md`](http-api.md).

### CLI

```bash
llmclab keys
llmclab models
llmclab ask groq "Hello"
llmclab fallback "Hello"
llmclab vision-menu --phase core
```

---

## Documentation

| | |
|---|---|
| [Docs index](README.md) | Terms, architecture, HTTP, protocol |
| [Architecture](architecture.md) | Layers, failover order, adding a provider |
| [HTTP API](http-api.md) | `/v1/chat`, `/v1/menu`, auth |
| [Findings](findings.md) | Catalogue vs actual capability; vision extract results |
| [Protocol](vision-menu/protocol.md) | Stimuli, probes, rule-based scoring |

---

## Contributing

Issues and pull requests are welcome. Run `pytest` before a PR, and read [CONTRIBUTING.md](../CONTRIBUTING.md) ([English](CONTRIBUTING.en.md)).

A new provider is usually one entry in `llmclab/config.py` `PROVIDERS`. The remote API must speak Chat Completions HTTP.

---

## Licence

Code: [MIT](../LICENSE).

Experiment data and reports under `docs/vision-menu/`: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

`menu_example/` is publicly displayed menus and app screenshots, used only as evaluation stimuli.
