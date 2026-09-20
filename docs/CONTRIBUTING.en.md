<p align="center">
  <a href="README.en.md">← Front page</a> ·
  <a href="../CONTRIBUTING.md">繁體中文</a>
</p>

# Contributing

Issues and pull requests are welcome. This page covers getting set up, making
changes, and which changes are worth an issue first.

---

## Setting up

```bash
git clone https://github.com/Lrniey666/llm-capability-lab.git
cd llm-capability-lab

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[serve,dev]"
cp .env.example .env             # the tests pass with no keys at all
```

```bash
pytest
```

**82 tests: no outbound network, no provider keys.** “Offline” does not mean
“no sockets”: `test_mock_server.py` and `test_service.py` start a local HTTP
server and drive the real `openai` package and FastAPI. If a change makes the
tests require a provider key or the public internet, the design has probably
drifted — use the local-server approach instead.

---

## Before opening a pull request

- [ ] `pytest` is green
- [ ] New behaviour has a test
- [ ] If the public API changed, `__all__` in `llmclab/__init__.py` is updated too
- [ ] `CHANGELOG.md` has an entry
- [ ] No `.env`, no keys, and no images outside `menu_example/` added to version control

---

## Adding a provider

This should touch one place: the `PROVIDERS` entry in `llmclab/config.py`, plus the
name in `CLOUD_ORDER`.

```python
"newco": Provider(
    key="newco",
    label="NewCo",
    base_url="https://api.newco.com/v1",
    env_var="NEWCO_API_KEY",
    default_model="newco-small",
    console_url="https://newco.com/keys",
    limits_url="https://newco.com/limits",
    supports_vision=False,
    note="Quota behaviour and gotchas, written for the next maintainer",
),
```

Please add the key name and sign-up URL to `.env.example` as well.

**If you find yourself editing three or more files, the abstraction has sprung a
leak.** Open an issue so the right hook can be added, rather than writing
`if provider == "newco"` at the call site. Existing hooks are listed in
[`architecture.md`](architecture.md).

This assumes the provider speaks Chat Completions HTTP
(`POST /v1/chat/completions`). If it does not, the project's core assumption
no longer holds — please open an issue to discuss. That is not the OpenAPI
Specification (the service's `/docs`).

---

## Changing the experiment

Everything under `docs/vision-menu/runs/` is an **archived record and is not edited
retrospectively**, including the older project name it mentions. To re-run, produce
a new run; do not overwrite an old one.

When changing scoring rules, say what it does to existing runs. If the new rules
invalidate old scores, make that explicit in `CHANGELOG.md` and consider bumping
the gold version.

To add stimuli to `menu_example/`:

- Only **publicly displayed** menus — nothing private or internal
- Annotate anchors in `gold.json`, and set `gold_complete` honestly
- State the source and collection date in the pull request

---

## Version numbers

The only source is `__version__` in `llmclab/__init__.py`. `pyproject.toml` reads it
through setuptools `dynamic = ["version"]` — do not hard-code a second copy.
Bump that string for a release, and add a `CHANGELOG.md` section. The string must
be a [PEP 440](https://peps.python.org/pep-0440/) public version (this project
uses SemVer `X.Y.Z`).

## Publishing to PyPI

Dependencies live in `pyproject.toml` only — do not add a parallel `requirements.txt`.

Publishing a GitHub Release (tag `vX.Y.Z`) runs `.github/workflows/publish.yml`:
**TestPyPI first**, then PyPI. **Do not** store a PyPI token in the repo or in
Actions secrets.

To try a package without touching production, run `publish.yml` with
**Run workflow** (`workflow_dispatch`); that uploads to TestPyPI only.

Before the first upload, configure a trusted publisher on both TestPyPI and
PyPI, and create matching GitHub Environments:

| Field | TestPyPI | PyPI |
|---|---|---|
| Owner | `Lrniey666` | `Lrniey666` |
| Repository | `llm-capability-lab` | `llm-capability-lab` |
| Workflow name | `publish.yml` | `publish.yml` |
| Environment | `testpypi` | `pypi` |

See [Publishing to PyPI with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/).

Pull requests run `.github/workflows/package.yml`: pytest on Ubuntu/Windows ×
Python 3.10–3.13, plus build, `twine check`, and an install of the wheel
outside the repository.

## Code style

There is no enforced formatter; follow the surrounding code. A few things this
project does care about:

- **Comments explain why, not what.** Next to `max_retries=0` the useful comment is "retries are Router's job", not "sets retries to zero"
- **Error messages must be actionable.** "No key configured" is not enough — name the environment variable and where to get one
- **Annotate types fully**; this package ships `py.typed`
- `llmclab/service.py` **deliberately omits** `from __future__ import annotations` — PEP 563 turns annotations into strings, and FastAPI cannot resolve types imported inside the function. Keep that in mind when editing it

---

## Reporting problems

Please include:

- The output of `llmclab keys` (**keys are already masked; it is safe to paste**)
- The full error, especially `.attempts` from `AllProvidersFailed`
- Your Python version and operating system

Reports that a provider's behaviour has changed — renamed headers, retired models,
a moved endpoint — are especially valuable. The whole premise of this project is
that catalogues change.
