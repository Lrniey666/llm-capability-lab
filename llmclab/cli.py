"""命令列介面：python -m llmclab <子指令>

刻意不依賴 rich——只用標準函式庫做對齊，少一個安裝失敗的理由。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata

from . import bench as bench_mod
from . import checks as checks_mod
from . import compare as compare_mod
from . import vision_menu as vision_mod
from .client import AllProvidersFailed, Router
from .config import DEFAULT_ORDER, PROVIDERS, configured_providers, get, load_env, mask_secret

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
GREEN, RED, YELLOW = "\033[32m", "\033[31m", "\033[33m"


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _w(text: str) -> int:
    """算顯示寬度：先拿掉顏色碼，中日韓全形字算 2 格。"""
    plain = _ANSI_RE.sub("", text)
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in plain)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _w(text))


def table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(_w(h), *(_w(r[i]) for r in rows)) if rows else _w(h) for i, h in enumerate(headers)]
    lines = ["  ".join(_pad(h, w) for h, w in zip(headers, widths))]
    lines.append("  ".join("─" * w for w in widths))
    lines += ["  ".join(_pad(c, w) for c, w in zip(row, widths)) for row in rows]
    return "\n".join(lines)


def _fmt(value: float | None, suffix: str = "") -> str:
    return f"{value:.0f}{suffix}" if value is not None else "—"


# ---------------------------------------------------------------- 子指令


def cmd_keys(args) -> int:
    rows = []
    for name in DEFAULT_ORDER:
        p = PROVIDERS[name]
        for env_name in p.slot_names(display_only=True):
            value = os.environ.get(env_name, "").strip()
            state = f"{GREEN}已設定{RESET}" if value else f"{YELLOW}未設定{RESET}"
            rows.append([p.label, env_name, state, mask_secret(value or None), p.console_url])
        if p.is_local and p.base_url_env:
            url = os.environ.get(p.base_url_env, "").strip()
            state = f"{GREEN}已設定{RESET}" if url else f"{YELLOW}未設定{RESET}"
            display = url if url else f"（預設）{p.base_url}"
            rows.append([p.label, p.base_url_env, state, display, "填了才納入保底"])
    print(table(["Provider", "環境變數", "狀態", "金鑰", "申請網址"], rows))

    local = PROVIDERS["local"]
    if local.configured:
        print(
            f"\n{DIM}本機保底已啟用：{local.resolved_base_url}  model={local.resolved_model}。"
            f"Router 順序為雲端用盡後才打 Qwen。{RESET}"
        )
    else:
        print(
            f"\n{DIM}本機保底未啟用。在 .env 填 LOCAL_BASE_URL={local.base_url}，"
            f"並 `ollama pull {local.default_model}`。{RESET}"
        )

    missing = [p for p in PROVIDERS.values() if not p.configured and p.requires_key]
    if missing:
        print(f"{DIM}把缺的雲端金鑰填進專案根目錄的 .env（可從 .env.example 複製）。失敗時會依 KEY → KEY2 → KEY3 輪替。{RESET}")
    else:
        print(f"{DIM}同一家若填了多把金鑰，Router 失敗時會先換 KEY2 / KEY3，再換下一家，最後才是本機 Qwen。{RESET}")
    return 0


def cmd_check(args) -> int:
    providers = [get(n) for n in (args.providers or DEFAULT_ORDER)]
    exit_code = 0

    for p in providers:
        print(f"\n{BOLD}{p.label}{RESET}  {DIM}{p.base_url}{RESET}")
        if not p.configured:
            if p.is_local:
                print(f"  {YELLOW}跳過：未設定 {p.base_url_env}（本機 Ollama / llama.cpp）{RESET}")
            else:
                print(f"  {YELLOW}跳過：{p.env_var} 未設定 → {p.console_url}{RESET}")
            continue

        slots = p.key_slots()
        if p.is_local:
            print(f"  {DIM}端點：{p.resolved_base_url}  model={p.resolved_model}{RESET}")
        else:
            print(f"  {DIM}金鑰池：{', '.join(s.env_var for s in slots)}（{len(slots)} 把，本次用第一把）{RESET}")
        report = checks_mod.run_all(p, model=args.model)
        rows = []
        for r in report.results:
            colour = GREEN if r.ok else RED
            if r.skipped:
                colour = DIM
            rows.append([
                f"{colour}{r.mark}{RESET}",
                r.name,
                _fmt(r.elapsed_s * 1000 if r.elapsed_s else None, " ms"),
                r.detail,
            ])
        print(table(["", "項目", "耗時", "結果"], rows))

        rl = report.rate_limit
        if rl:
            print(f"  {DIM}配額 header：{rl.summary()}{RESET}")
        if not report.ok:
            exit_code = 1
        print(f"  {DIM}{p.note}{RESET}")

    return exit_code


def cmd_models(args) -> int:
    from .client import make_client

    for p in (get(n) for n in (args.providers or DEFAULT_ORDER)):
        print(f"\n{BOLD}{p.label}{RESET}")
        if not p.configured:
            hint = p.base_url_env if p.is_local else p.env_var
            print(f"  {YELLOW}未設定 {hint}{RESET}")
            continue
        try:
            models = sorted(m.id for m in make_client(p, timeout=30).models.list())
        except Exception as exc:  # noqa: BLE001
            print(f"  {RED}撈不到清單：{exc}{RESET}")
            continue
        keyword = (args.grep or "").lower()
        shown = [m for m in models if keyword in m.lower()]
        print(f"  共 {len(models)} 個" + (f"，符合 {args.grep!r} 的 {len(shown)} 個" if keyword else ""))
        for m in shown[: args.limit]:
            print(f"    {m}")
    return 0


def cmd_ask(args) -> int:
    messages = [{"role": "user", "content": args.prompt}]
    router = Router(
        [args.provider],
        retries_per_key=args.retries,
        max_attempts_per_provider=args.max_attempts,
        verbose=True,
    )
    try:
        result = router.chat(messages, model_overrides={args.provider: args.model} if args.model else None, stream=args.stream)
    except AllProvidersFailed as exc:
        for a in exc.attempts:
            print(f"{RED}✗ {a.provider}/{a.key_env or '?'}：{a.error}{RESET}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"{RED}{exc}{RESET}", file=sys.stderr)
        return 1

    print(result.text)
    used = f"{result.provider}/{result.model}"
    if result.key_env:
        used += f"  key={result.key_env}"
    print(
        f"\n{DIM}{used}  "
        f"{result.latency_s * 1000:.0f} ms  "
        f"in={result.prompt_tokens} out={result.completion_tokens}  "
        f"{result.rate_limit.summary()}{RESET}"
    )
    return 0


def cmd_bench(args) -> int:
    providers = [p for p in (get(n) for n in (args.providers or DEFAULT_ORDER)) if p.configured]
    if not providers:
        print(f"{YELLOW}沒有任何已設定的 provider，先跑 `python -m llmclab keys`。{RESET}")
        return 1

    rows = []
    for p in providers:
        print(f"{DIM}測 {p.label}…{RESET}", end="", flush=True)
        res = bench_mod.benchmark(
            p, runs=args.runs, model=args.model, gap_s=args.gap,
            on_run=lambda i, n: print(f" {i}/{n}", end="", flush=True),
        )
        print()
        rows.append([
            p.label,
            res.model,
            f"{res.ok_runs}/{res.runs}",
            _fmt(res.ttft_p50, " ms"),
            _fmt(res.total_p50, " ms"),
            _fmt(res.total_p95, " ms"),
            _fmt(res.mean_tps),
            str(res.rate_limited) if res.rate_limited else "—",
        ])

    print()
    print(table(["Provider", "模型", "成功", "TTFT p50", "總時長 p50", "p95", "tok/s", "429"], rows))
    print(f"\n{DIM}序列送出、每次間隔 {args.gap}s。並發打免費層只會量到 429 的速度。{RESET}")
    return 0


def cmd_fallback(args) -> int:
    order = args.providers or DEFAULT_ORDER
    router = Router(
        order,
        retries_per_key=args.retries,
        max_attempts_per_provider=args.max_attempts,
        verbose=True,
    )
    print(f"{DIM}嘗試順序：{' → '.join(order)}（每家最多 {args.max_attempts or '不限'} 次，每把金鑰重試 {args.retries}）{RESET}\n")

    try:
        result = router.chat([{"role": "user", "content": args.prompt}], max_tokens=args.max_tokens)
    except AllProvidersFailed as exc:
        for a in exc.attempts:
            print(f"  {RED}✗{RESET} {a.provider}: {a.error}")
        return 1

    print(result.text)
    print(f"\n{DIM}嘗試紀錄：{RESET}")
    for a in result.attempts:
        mark = f"{GREEN}✓{RESET}" if a.ok else f"{RED}✗{RESET}"
        note = "" if a.ok else f" — {a.error}"
        key = f" {a.key_env}" if a.key_env else ""
        print(f"  {mark} {a.provider}/{a.model}{key}{note}")
    used = f"{result.provider}"
    if result.key_env:
        used += f"/{result.key_env}"
    print(f"{DIM}最終由 {used} 回應，耗時 {result.latency_s * 1000:.0f} ms{RESET}")
    return 0


def cmd_compare(args) -> int:
    providers = [p for p in (get(n) for n in (args.providers or DEFAULT_ORDER)) if p.configured]
    if not providers:
        print(f"{YELLOW}沒有任何已設定的 provider，先跑 `python -m llmclab keys`。{RESET}")
        return 1

    skipped = [p.label for p in (get(n) for n in (args.providers or DEFAULT_ORDER)) if not p.configured]
    print(f"{DIM}對照：{' / '.join(p.label for p in providers)}{RESET}")
    if getattr(args, "iai_all", False):
        print(f"{DIM}iAI 展開全部模型（對話題 + 非對話探針）{RESET}")
    if getattr(args, "iai_models", None):
        print(f"{DIM}iAI 指定模型：{', '.join(args.iai_models)}{RESET}")
    print(f"{DIM}套件：{getattr(args, 'suite', 'simple')}{RESET}")
    if skipped:
        print(f"{DIM}略過未設定：{' / '.join(skipped)}{RESET}")
    print()

    def on_case(provider, case, run, i, n):
        mark = f"{GREEN}✓{RESET}" if run.ok else f"{RED}✗{RESET}"
        extra = run.error or run.note
        who = run.model or provider.label
        print(
            f"  {mark} {who}  {case.title}  "
            f"{run.latency_s * 1000:.0f} ms  {DIM}{extra}{RESET}"
        )

    report = compare_mod.run_compare(
        providers,
        category=args.category,
        model=args.model,
        gap_s=args.gap,
        iai_all=getattr(args, "iai_all", False),
        iai_models=getattr(args, "iai_models", None),
        suite=getattr(args, "suite", "simple"),
        on_case=on_case,
    )

    chat_blocks = [p for p in report.providers if p.kind == "chat"]
    other_blocks = [p for p in report.providers if p.kind != "chat"]
    case_ids = [r.case_id for r in chat_blocks[0].runs] if chat_blocks else []
    titles = {r.case_id: r.title for p in chat_blocks for r in p.runs}
    headers = ["題目", *[p.model for p in chat_blocks]]
    rows = []
    for cid in case_ids:
        row = [titles.get(cid, cid)]
        for block in chat_blocks:
            run = next(r for r in block.runs if r.case_id == cid)
            if run.error:
                cell = f"{RED}錯誤{RESET}"
            elif run.ok:
                cell = f"{GREEN}通過{RESET} {run.latency_s * 1000:.0f}ms"
            else:
                cell = f"{RED}未過{RESET} {run.latency_s * 1000:.0f}ms"
            row.append(cell)
        rows.append(row)

    print()
    if rows:
        print(table(headers, rows))

    if other_blocks:
        print()
        print(table(
            ["模型", "類型", "探針"],
            [[
                b.model,
                b.kind,
                (b.runs[0].error or b.runs[0].note)[:60] if b.runs else "—",
            ] for b in other_blocks],
        ))

    print()
    cats = []
    for block in report.providers:
        for run in block.runs:
            if run.category not in cats and run.category != "non_chat":
                cats.append(run.category)
    summary = []
    for block in report.providers:
        total_ok, total_n = block.score()
        mean = f"{block.mean_latency_s * 1000:.0f} ms" if block.mean_latency_s is not None else "—"
        row = [block.model]
        for cat in cats:
            ok, n = block.score(cat)
            row.append(f"{ok}/{n}" if n else "—")
        row += [f"{total_ok}/{total_n}", mean]
        summary.append(row)
    headers = ["模型", *[ {"conversation": "對話", "logic": "邏輯", "instruction": "指令", "reasoning": "推理", "code": "程式", "language": "用語"}.get(c, c) for c in cats ], "合計", "平均延遲"]
    print(table(headers, summary))

    dest = compare_mod.save_report(report)
    print(f"\n{DIM}結果已寫入 {dest}{RESET}")
    all_errored = all(r.error for block in report.providers for r in block.runs)
    return 1 if all_errored else 0


def cmd_vision_menu(args) -> int:
    from pathlib import Path

    names = args.providers or list(vision_mod.PROVIDERS_DEFAULT)
    run_dir = Path(args.run_dir) if args.run_dir else None
    print(f"{DIM}視覺菜單實驗  phase={args.phase}  providers={' '.join(names)}{RESET}")

    def on_progress(message: str) -> None:
        print(message)

    dest = vision_mod.run_experiment(
        providers=names,
        phase=args.phase,
        run_dir=run_dir,
        gap_s=args.gap,
        gemini_extended_limit=args.gemini_extended_limit,
        on_progress=on_progress,
    )
    print(f"\n{DIM}結果目錄：{dest}{RESET}")
    report = dest / "report.md"
    if report.exists():
        print(f"{DIM}報告：{report}{RESET}")
    return 0


# ---------------------------------------------------------------- 進入點


def cmd_serve(args) -> int:
    """啟動 HTTP 服務，讓非 Python 的專案也能共用同一套轉移策略。"""
    from .service import ServiceConfigError, serve

    try:
        serve(host=args.host, port=args.port, reload=args.reload)
    except ServiceConfigError as exc:
        print(f"無法啟動：{exc}")
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmclab",
        description="跨供應商的 LLM 能力驗證與故障轉移路由（Groq / Gemini / Mistral / iAI，本機 Ollama 保底）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="範例：\n  python -m llmclab keys\n  python -m llmclab check\n"
               "  python -m llmclab ask iai '你好'\n  python -m llmclab compare",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_providers(p):
        p.add_argument("-p", "--providers", nargs="*", choices=list(PROVIDERS),
                       help="只跑指定的 provider（預設全部）")
        return p

    sub.add_parser("keys", help="列出金鑰設定狀態").set_defaults(func=cmd_keys)

    c = add_providers(sub.add_parser("check", help="逐項能力檢查"))
    c.add_argument("-m", "--model", help="覆寫模型 ID")
    c.set_defaults(func=cmd_check)

    m = add_providers(sub.add_parser("models", help="列出各家可用模型"))
    m.add_argument("-g", "--grep", help="關鍵字過濾")
    m.add_argument("-n", "--limit", type=int, default=20, help="每家最多顯示幾個")
    m.set_defaults(func=cmd_models)

    a = sub.add_parser("ask", help="對單一 provider 問一句（失敗時換同一家的下一把金鑰）")
    a.add_argument("provider", choices=list(PROVIDERS))
    a.add_argument("prompt")
    a.add_argument("-m", "--model")
    a.add_argument("-s", "--stream", action="store_true")
    a.add_argument("--retries", type=int, default=1, help="同一把金鑰遇暫時性錯誤時重試幾次")
    a.add_argument("--max-attempts", type=int, default=None, help="這家最多呼叫幾次（預設＝金鑰數×(retries+1)）")
    a.set_defaults(func=cmd_ask)

    b = add_providers(sub.add_parser("bench", help="延遲／吞吐量比較"))
    b.add_argument("-n", "--runs", type=int, default=5)
    b.add_argument("-m", "--model")
    b.add_argument("--gap", type=float, default=1.2, help="每次請求間隔秒數")
    b.set_defaults(func=cmd_bench)

    f = add_providers(sub.add_parser("fallback", help="示範金鑰輪替 + 跨 provider 自動切換"))
    f.add_argument("prompt", nargs="?", default="用一句話介紹高雄。")
    f.add_argument("--retries", type=int, default=1, help="同一把金鑰遇暫時性錯誤時重試幾次")
    f.add_argument("--max-attempts", type=int, default=None, help="每家最多呼叫幾次（預設不另設上限）")
    f.add_argument("--max-tokens", type=int, default=200)
    f.set_defaults(func=cmd_fallback)

    q = add_providers(sub.add_parser("compare", help="對話與邏輯題對照（iAI / 外部 API / 本機）"))
    q.add_argument("-m", "--model", help="所有 provider 共用的模型覆寫（通常只測單家時用）")
    q.add_argument("-c", "--category", help="只跑某個類別（如 instruction / reasoning / code）")
    q.add_argument("--suite", choices=["simple", "deep"], default="simple", help="simple=入門 8 題；deep=進階題")
    q.add_argument("--gap", type=float, default=1.2, help="每題間隔秒數")
    q.add_argument(
        "--iai-all",
        action="store_true",
        help="把 iAI 展開成 API＋價目表上的每一個模型各跑一輪",
    )
    q.add_argument(
        "--iai-models",
        nargs="*",
        help="只展開這些 iAI 模型（例如 Furen-std gemma-4-31b）",
    )
    q.set_defaults(func=cmd_compare)

    v = add_providers(sub.add_parser("vision-menu", help="菜單圖視覺辨識：catalog / probe / core / extended"))
    v.add_argument(
        "--phase",
        choices=["all", "catalog", "probe", "core", "extended", "score"],
        default="all",
        help="all=四段依序；可搭配 --run-dir 斷點續跑",
    )
    v.add_argument("--run-dir", help="續跑時指定 docs/vision-menu/runs/<id>")
    v.add_argument("--gap", type=float, default=None, help="覆寫請求間隔秒數")
    v.add_argument(
        "--gemini-extended-limit",
        type=int,
        default=1,
        help="extended 階段最多跑幾個 Gemini 模型（預設 1，保住免費層日額）",
    )
    v.set_defaults(func=cmd_vision_menu)

    srv = sub.add_parser("serve", help="啟動 HTTP 服務（需要 [serve] 額外依賴）")
    srv.add_argument("--host", default="127.0.0.1", help="預設只綁本機；要對外請明確指定 0.0.0.0")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--reload", action="store_true", help="開發用自動重載")
    srv.set_defaults(func=cmd_serve)

    return parser


def _configure_stdio() -> None:
    """Windows cp950 印不出 ✓／✗；改成 UTF-8 並在失敗時取代字元。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    load_env()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已中斷。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
