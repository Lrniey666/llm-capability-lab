"""菜單圖視覺實驗入口。等同 `python -m llmclab vision-menu`。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmclab.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or argv[0] != "vision-menu":
        argv = ["vision-menu", *argv]
    raise SystemExit(main(argv))
