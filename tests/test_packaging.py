"""打包 metadata 是否符合 pip / PyPI 會讀的那幾份規格。

這些測試只讀 repo 裡的宣告與套件本身，不連網、不需要金鑰。
真正建出 wheel／sdist 由 CI 的 python -m build 再驗一次。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import llmclab  # noqa: E402
from llmclab.cli import main as cli_main  # noqa: E402

PYPROJECT = ROOT / "pyproject.toml"

# PEP 440 公開版本（不含 local identifier）。
_PEP440_PUBLIC = re.compile(
    r"""
    ^(?:(?:0|[1-9]\d*)!)?
    (?:0|[1-9]\d*)
    (?:\.(?:0|[1-9]\d*))*
    (?:(?:a|b|rc)(?:0|[1-9]\d*))?
    (?:\.post(?:0|[1-9]\d*))?
    (?:\.dev(?:0|[1-9]\d*))?
    $
    """,
    re.VERBOSE,
)

# PEP 503 / name normalization：[-_.]+ → -，再小寫。
_NORMALIZE_NAME = re.compile(r"[-_.]+")


def _pyproject_text() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def _field(pattern: str) -> str:
    match = re.search(pattern, _pyproject_text(), re.MULTILINE)
    assert match, pattern
    return match.group(1)


def test_pep503_name_already_normalized():
    name = _field(r'^name = "([^"]+)"')
    normalized = _NORMALIZE_NAME.sub("-", name).lower()
    assert name == normalized, f"PyPI simple API 會把 {name!r} 正規化成 {normalized!r}"


def test_pep440_version_from_package_attr():
    assert _PEP440_PUBLIC.match(llmclab.__version__), llmclab.__version__
    tree = ast.parse((ROOT / "llmclab" / "__init__.py").read_text(encoding="utf-8"))
    assigned = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    assert assigned == [llmclab.__version__]


def test_version_is_dynamic_setuptools_attr():
    text = _pyproject_text()
    assert re.search(r'^version\s*=\s*"', text, re.MULTILINE) is None
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "llmclab.__version__"}' in text


def test_pep639_license_expression_and_files():
    text = _pyproject_text()
    assert 'license = "MIT"' in text
    assert 'license-files = ["LICENSE"]' in text
    assert (ROOT / "LICENSE").is_file()
    assert "License ::" not in text


def test_pep518_build_backend_and_setuptools_floor():
    text = _pyproject_text()
    assert 'build-backend = "setuptools.build_meta"' in text
    match = re.search(r'"setuptools>=(\d+(?:\.\d+)*)"', text)
    assert match, text
    parts = [int(p) for p in match.group(1).split(".")]
    assert parts >= [77, 0, 3], match.group(0)


def test_packages_discovered_by_find():
    text = _pyproject_text()
    assert "[tool.setuptools.packages.find]" in text
    assert 'include = ["llmclab*"]' in text
    assert "namespaces = false" in text
    assert not re.search(r'^packages = \["llmclab"\]', text, re.MULTILINE)


def test_project_urls_use_well_known_labels():
    text = _pyproject_text()
    assert "[project.urls]" in text
    required = {
        "Homepage": "https://github.com/Lrniey666/llm-capability-lab",
        "Documentation": "https://github.com/Lrniey666/llm-capability-lab#readme",
        "Repository": "https://github.com/Lrniey666/llm-capability-lab",
        "Issues": "https://github.com/Lrniey666/llm-capability-lab/issues",
        "Changelog": "https://github.com/Lrniey666/llm-capability-lab/blob/main/CHANGELOG.md",
    }
    for label, url in required.items():
        assert f'{label} = "{url}"' in text


def test_console_scripts_entry_point():
    assert 'llmclab = "llmclab.cli:main"' in _pyproject_text()
    assert callable(cli_main)
    assert (ROOT / "llmlab").exists() is False
    assert (ROOT / "llmclab" / "__init__.py").is_file()


def test_pep561_py_typed_is_package_data():
    typed = ROOT / "llmclab" / "py.typed"
    assert typed.is_file()
    assert 'llmclab = ["py.typed"]' in _pyproject_text()
    assert "Typing :: Typed" in _pyproject_text()
    assert "Programming Language :: Python :: 3.13" in _pyproject_text()


def test_env_prefix_matches_import_name():
    from llmclab.config import WORKSPACE_ENV
    from llmclab.service import ALLOW_ANON_ENV, TOKEN_ENV

    assert WORKSPACE_ENV == "LLMCLAB_WORKSPACE"
    assert TOKEN_ENV == "LLMCLAB_API_TOKEN"
    assert ALLOW_ANON_ENV == "LLMCLAB_ALLOW_ANONYMOUS"


def test_requires_python_and_core_dependencies():
    text = _pyproject_text()
    assert 'requires-python = ">=3.10"' in text
    assert "openai>=" in text
    assert "python-dotenv>=" in text
    assert "[project.optional-dependencies]" in text
    assert "serve =" in text
    assert "dev =" in text
