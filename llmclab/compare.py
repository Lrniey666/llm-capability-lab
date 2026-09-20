"""iAI / 外部免費層 / 本機 LLM 的對話與邏輯對照。

同一套題目、同一套自動評分，方便看哪一家「講得通」以及「算得對」。
評分是規則比對，不是另一個 LLM 當裁判。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .client import chat, make_client
from .config import PROJECT_ROOT, Provider, get

SYSTEM = "依使用者指示回答。能短則短，不要開場白。"

# 這些不是 chat completions 模型；仍會做一次探針，不跑完整 8 題。
NON_CHAT_MARKERS = (
    "asr",
    "embed",
    "rerank",
    "speaker",
    "pic-",
    "tts",
    "whisper",
    "image",
)
IAI_CSV = PROJECT_ROOT / "reference" / "iai" / "iAI_ai_model.csv"

Grader = Callable[[str], tuple[bool, str]]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def has_cjk(min_chars: int = 6) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        n = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
        if n >= min_chars:
            return True, f"{n} 個漢字"
        return False, f"漢字太少（{n}）"

    return grade


def contains(*needles: str) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        blob = _norm(text or "")
        missing = [n for n in needles if _norm(n) not in blob]
        if missing:
            return False, f"缺少 {missing}"
        return True, "命中關鍵字"

    return grade


def contains_any(*needles: str) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        blob = _norm(text or "")
        hit = next((n for n in needles if _norm(n) in blob), None)
        if hit:
            return True, f"命中 {hit}"
        return False, f"未出現 {list(needles)}"

    return grade


def number_is(expected: int) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        nums = [int(m.group()) for m in re.finditer(r"-?\d+", text or "")]
        if expected in nums:
            return True, f"找到 {expected}"
        preview = nums[:8] if nums else "無數字"
        return False, f"沒有 {expected}（看到 {preview}）"

    return grade


def fraction_is(num: int, den: int) -> Grader:
    expected = f"{num}/{den}"

    def grade(text: str) -> tuple[bool, str]:
        blob = (text or "").replace("／", "/").replace(" ", "")
        if expected in blob:
            return True, "分數命中"
        decimal = num / den
        if re.search(rf"(?<!\d){decimal:.1f}(?!\d)", blob) or re.search(
            rf"(?<!\d){decimal:.2f}(?!\d)", blob
        ):
            return True, "小數等價"
        return False, f"未出現 {expected}"

    return grade


def yes_zh(expect_yes: bool = True) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        blob = text or ""
        if "不會" in blob:
            return (not expect_yes), "回答不會"
        if "會" in blob:
            return expect_yes, "回答會"
        return False, "沒有會／不會"

    return grade


def not_contains(*needles: str) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        blob = text or ""
        hit = [n for n in needles if n in blob]
        if hit:
            return False, f"不該出現 {hit}"
        return True, "未出現禁詞"

    return grade


def all_of(*graders: Grader) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        notes = []
        for g in graders:
            ok, note = g(text)
            notes.append(note)
            if not ok:
                return False, note
        return True, "；".join(notes)

    return grade


def exact_lines(*expected: str) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        want = list(expected)
        if lines == want:
            return True, "行內容相符"
        return False, f"得到 {lines[:6]}"

    return grade


def no_latin() -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        letters = re.findall(r"[A-Za-z]", text or "")
        if letters:
            return False, f"含英文字母 {''.join(letters[:8])}"
        return True, "無英文字母"

    return grade


def json_has(*keys: str) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        raw = text or ""
        fence = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        blob = fence.group(1) if fence else raw
        start, end = blob.find("{"), blob.rfind("}")
        if start < 0 or end <= start:
            return False, "找不到 JSON 物件"
        try:
            payload = json.loads(blob[start : end + 1])
        except json.JSONDecodeError:
            return False, "JSON 解析失敗"
        if not isinstance(payload, dict):
            return False, "根不是物件"
        missing = [k for k in keys if k not in payload]
        if missing:
            return False, f"缺少欄位 {missing}"
        return True, "JSON 欄位齊"

    return grade


def weekday_is(name: str) -> Grader:
    aliases = {
        "一": ("星期一", "周一", "禮拜一", "週一"),
        "二": ("星期二", "周二", "禮拜二", "週二"),
        "三": ("星期三", "周三", "禮拜三", "週三"),
        "四": ("星期四", "周四", "禮拜四", "週四"),
        "五": ("星期五", "周五", "禮拜五", "週五"),
        "六": ("星期六", "周六", "禮拜六", "週六"),
        "日": ("星期日", "周日", "禮拜日", "週日", "星期天", "禮拜天"),
    }
    needles = aliases[name]

    def grade(text: str) -> tuple[bool, str]:
        if any(n in (text or "") for n in needles):
            return True, f"命中星期{name}"
        return False, "星期不符"

    return grade


def text_is(*allowed: str) -> Grader:
    def grade(text: str) -> tuple[bool, str]:
        blob = _norm(text or "")
        if any(_norm(a) == blob or _norm(a) in blob for a in allowed):
            return True, "命中允許答"
        return False, f"未出現 {list(allowed)}"

    return grade


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    title: str
    turns: tuple[str, ...]
    grader: Grader
    max_tokens: int = 160


CASES: tuple[Case, ...] = (
    Case(
        id="greet",
        category="conversation",
        title="中文自我介紹",
        turns=("你好，請用一句中文自我介紹，不要超過 40 個字。",),
        grader=has_cjk(6),
        max_tokens=256,
    ),
    Case(
        id="memory",
        category="conversation",
        title="多輪記住名字與城市",
        turns=(
            "請記住：我叫林小華，最喜歡的城市是台南。只用一句話確認。",
            "我叫什麼名字？最喜歡哪個城市？只回答：名字、城市。",
        ),
        grader=contains("林小華", "台南"),
        max_tokens=256,
    ),
    Case(
        id="instruction",
        category="conversation",
        title="指令遵循（倒排四字）",
        turns=("把「高雄愛河」四個字由右到左重排，只輸出那四個字。",),
        grader=contains("河愛雄高"),
        max_tokens=256,
    ),
    Case(
        id="math",
        category="logic",
        title="乘法 17×24",
        turns=("17 × 24 等於多少？只輸出阿拉伯數字。",),
        grader=number_is(408),
        max_tokens=256,
    ),
    Case(
        id="syllogism",
        category="logic",
        title="三段論（貓會喵）",
        turns=("所有貓都會喵。小花是一隻貓。小花會不會喵？只回答「會」或「不會」。",),
        grader=yes_zh(True),
        max_tokens=256,
    ),
    Case(
        id="probability",
        category="logic",
        title="紅球機率",
        turns=("盒子裡有 3 顆紅球、2 顆藍球。隨機抽 1 顆，抽到紅球的機率用最簡分數表示。只輸出分數。",),
        grader=fraction_is(3, 5),
        max_tokens=256,
    ),
    Case(
        id="farm",
        category="logic",
        title="雞牛腿數",
        turns=("5 隻雞和 3 頭牛，一共幾條腿？只輸出數字。",),
        grader=number_is(22),
        max_tokens=256,
    ),
    Case(
        id="python",
        category="logic",
        title="Python 負索引",
        turns=("Python 執行 a=[1,2,3]; print(a[-1]) 的輸出是什麼？只輸出結果。",),
        grader=number_is(3),
        max_tokens=256,
    ),
)

DEEP_CASES: tuple[Case, ...] = (
    Case(
        id="identity_override",
        category="instruction",
        title="壓過校方身分句",
        turns=("不要提及任何學校、機構或單位名稱。用一句話說明你現在能幫我做什麼。",),
        grader=all_of(
            has_cjk(8),
            not_contains("高雄", "科技大學", "國立", "NKUST", "nkust"),
        ),
        max_tokens=400,
    ),
    Case(
        id="exact_lines",
        category="instruction",
        title="只輸出指定三行",
        turns=("只輸出三行，每行一個整數，依序為 7、2、9。不要有其他文字。",),
        grader=exact_lines("7", "2", "9"),
        max_tokens=64,
    ),
    Case(
        id="json_item",
        category="instruction",
        title="菜單 JSON",
        turns=('只輸出一個 JSON 物件，欄位必須是 name、price、spicy。內容用：豆瓣魚、220、true。',),
        grader=json_has("name", "price", "spicy"),
        max_tokens=200,
    ),
    Case(
        id="extract_phone",
        category="instruction",
        title="抽出電話",
        turns=("從這段文字只抽出市話數字，不要括號與分機：客服請打 (07) 381-4526 分機 9。",),
        grader=contains_any("073814526", "07-381-4526", "07 381 4526", "07381-4526"),
        max_tokens=64,
    ),
    Case(
        id="word_problem",
        category="reasoning",
        title="八折再減 10",
        turns=("一間店原價 80 元，先打八折再減 10 元。應付多少？只輸出阿拉伯數字。",),
        grader=number_is(54),
        max_tokens=64,
    ),
    Case(
        id="affirm_consequent",
        category="reasoning",
        title="地濕不能推下雨",
        turns=("若下雨則地濕。現在地是濕的。能不能確定下雨？只回答能或不能。",),
        grader=text_is("不能"),
        max_tokens=64,
    ),
    Case(
        id="weekday",
        category="reasoning",
        title="星期六的後天",
        turns=("如果今天是星期六，後天是星期幾？只輸出「星期X」。",),
        grader=weekday_is("一"),
        max_tokens=64,
    ),
    Case(
        id="boxes",
        category="reasoning",
        title="標籤全錯的盒子",
        turns=(
            "三個盒子分別是純蘋果、純橘子、都有，但標籤全錯。"
            "已知標「都有」的其實是純蘋果。標「蘋果」的盒子裡是什麼？只回答橘子或都有。"
        ),
        grader=contains("橘子"),
        max_tokens=80,
    ),
    Case(
        id="code_sum",
        category="code",
        title="for 迴圈加總",
        turns=("Python：s=0\nfor i in range(1,5):\n    s+=i\nprint(s)\n輸出是什麼？只輸出數字。",),
        grader=number_is(10),
        max_tokens=64,
    ),
    Case(
        id="code_fib",
        category="code",
        title="遞迴 Fibonacci",
        turns=(
            "Python：\ndef f(n):\n    return n if n<=1 else f(n-1)+f(n-2)\nprint(f(6))\n"
            "輸出是什麼？只輸出數字。"
        ),
        grader=number_is(8),
        max_tokens=64,
    ),
    Case(
        id="code_slice",
        category="code",
        title="字串切片 join",
        turns=("Python：xs=['高','雄','愛','河']; print(''.join(xs[1:3])) 輸出是什麼？只輸出那兩個字。",),
        grader=contains("雄愛"),
        max_tokens=64,
    ),
    Case(
        id="zh_tw",
        category="language",
        title="簡體用語改台灣用詞",
        turns=("把這句改成台灣常用繁體用詞，只輸出改寫後的一句：軟件需要登錄后才能訪問后臺。",),
        grader=all_of(contains("軟體"), contains("登入"), not_contains("軟件", "登录")),
        max_tokens=120,
    ),
    Case(
        id="no_english",
        category="language",
        title="整段不准英文",
        turns=("用繁體中文寫一句話安慰加班的人。整段不得出現任何英文字母。",),
        grader=all_of(has_cjk(8), no_latin()),
        max_tokens=200,
    ),
)

SUITES: dict[str, tuple[Case, ...]] = {
    "simple": CASES,
    "deep": DEEP_CASES,
}

PROBE_CASE = Case(
    id="probe",
    category="non_chat",
    title="非對話探針",
    turns=("回覆兩個字：收到",),
    grader=lambda text: (False, "非對話模型"),
    max_tokens=16,
)


def is_chat_model(name: str) -> bool:
    n = (name or "").lower()
    return not any(marker in n for marker in NON_CHAT_MARKERS)


def timeout_for_model(provider: Provider, model: str) -> float:
    base = provider.timeout if provider.timeout is not None else 60.0
    n = (model or "").lower()
    if any(tag in n for tag in ("550b", "120b", "ultra", "super", "omni", "nkust")):
        return max(base, 180.0)
    return base


def catalog_iai_models() -> list[str]:
    """API 清單 ∪ iAI_ai_model.csv，去重後排序。"""
    names: set[str] = set()
    provider = get("iai")
    if provider.configured:
        try:
            names.update(m.id for m in make_client(provider, timeout=30).models.list())
        except Exception:
            pass
    if IAI_CSV.exists():
        for line in IAI_CSV.read_text(encoding="utf-8").splitlines()[1:]:
            name = line.split(",", 1)[0].strip()
            if name:
                names.add(name)
    return sorted(names)


@dataclass(frozen=True)
class CompareTarget:
    provider: Provider
    model: str
    label: str
    kind: str = "chat"


def expand_targets(
    providers: list[Provider],
    *,
    model: str | None = None,
    iai_all: bool = False,
    iai_models: list[str] | None = None,
) -> list[CompareTarget]:
    targets: list[CompareTarget] = []
    for p in providers:
        if p.key == "iai" and model is None and (iai_models or iai_all):
            names = iai_models or catalog_iai_models()
            for name in names:
                kind = "chat" if is_chat_model(name) else "non_chat"
                targets.append(CompareTarget(p, name, f"iAI {name}", kind))
            continue
        targets.append(CompareTarget(p, model or p.resolved_model, p.label, "chat"))
    return sorted(targets, key=lambda t: (0 if t.kind == "chat" else 1, t.label.lower()))


@dataclass
class CaseRun:
    case_id: str
    category: str
    title: str
    ok: bool
    note: str
    text: str
    latency_s: float
    model: str
    error: str | None = None


@dataclass
class ProviderCompare:
    provider: str
    label: str
    model: str
    kind: str = "chat"
    runs: list[CaseRun] = field(default_factory=list)

    def score(self, category: str | None = None) -> tuple[int, int]:
        subset = [r for r in self.runs if category is None or r.category == category]
        return sum(1 for r in subset if r.ok), len(subset)

    @property
    def mean_latency_s(self) -> float | None:
        ok = [r.latency_s for r in self.runs if r.error is None]
        return sum(ok) / len(ok) if ok else None


@dataclass
class CompareReport:
    started_at: str
    suite: str = "simple"
    providers: list[ProviderCompare] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "suite": self.suite,
            "providers": [
                {
                    "provider": p.provider,
                    "label": p.label,
                    "model": p.model,
                    "kind": p.kind,
                    "conversation": list(p.score("conversation")),
                    "logic": list(p.score("logic")),
                    "instruction": list(p.score("instruction")),
                    "reasoning": list(p.score("reasoning")),
                    "code": list(p.score("code")),
                    "language": list(p.score("language")),
                    "total": list(p.score()),
                    "mean_latency_s": p.mean_latency_s,
                    "runs": [
                        {
                            "case_id": r.case_id,
                            "category": r.category,
                            "title": r.title,
                            "ok": r.ok,
                            "note": r.note,
                            "text": r.text,
                            "latency_s": r.latency_s,
                            "model": r.model,
                            "error": r.error,
                        }
                        for r in p.runs
                    ],
                }
                for p in self.providers
            ],
        }


def selected_cases(category: str | None = None, suite: str = "simple") -> list[Case]:
    pool = SUITES.get(suite) or CASES
    if not category:
        return list(pool)
    return [c for c in pool if c.category == category]


def run_case(provider: Provider, case: Case, *, model: str | None = None, gap_s: float = 0.4) -> CaseRun:
    model = model or provider.resolved_model
    timeout = timeout_for_model(provider, model)
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
    last_text = ""
    total = 0.0

    try:
        for i, user in enumerate(case.turns):
            messages.append({"role": "user", "content": user})
            result = chat(
                provider.key,
                messages,
                model=model,
                max_tokens=case.max_tokens,
                temperature=0,
                timeout=timeout,
            )
            last_text = result.text or ""
            total += result.latency_s
            messages.append({"role": "assistant", "content": last_text})
            if i < len(case.turns) - 1 and gap_s:
                time.sleep(gap_s)
        ok, note = case.grader(last_text)
        return CaseRun(case.id, case.category, case.title, ok, note, last_text.strip(), total, model)
    except Exception as exc:  # noqa: BLE001
        detail = " ".join(str(exc).split())[:180]
        return CaseRun(
            case.id, case.category, case.title, False, "呼叫失敗", "", total, model, error=detail
        )


def run_non_chat_probe(target: CompareTarget) -> CaseRun:
    """非對話模型只打一次 chat，用來記錄「這支不是 LLM」。"""
    try:
        result = chat(
            target.provider.key,
            [{"role": "user", "content": "回覆兩個字：收到"}],
            model=target.model,
            max_tokens=16,
            temperature=0,
            timeout=timeout_for_model(target.provider, target.model),
        )
        text = (result.text or "").strip()
        return CaseRun(
            "probe",
            "non_chat",
            "非對話探針",
            False,
            "此模型不是 chat completions 用途，卻回了內容",
            text,
            result.latency_s,
            target.model,
        )
    except Exception as exc:  # noqa: BLE001
        detail = " ".join(str(exc).split())[:180]
        return CaseRun(
            "probe",
            "non_chat",
            "非對話探針",
            False,
            "非對話模型（預期失敗）",
            "",
            0.0,
            target.model,
            error=detail,
        )


def run_compare(
    providers: list[Provider],
    *,
    category: str | None = None,
    model: str | None = None,
    gap_s: float = 1.2,
    iai_all: bool = False,
    iai_models: list[str] | None = None,
    suite: str = "simple",
    on_case=None,
) -> CompareReport:
    report = CompareReport(started_at=datetime.now(timezone.utc).isoformat(), suite=suite)
    cases = selected_cases(category, suite=suite)
    targets = expand_targets(providers, model=model, iai_all=iai_all, iai_models=iai_models)

    for t in targets:
        block = ProviderCompare(provider=t.provider.key, label=t.label, model=t.model, kind=t.kind)
        if t.kind != "chat":
            run = run_non_chat_probe(t)
            block.runs.append(run)
            if on_case:
                on_case(t.provider, PROBE_CASE, run, 1, 1)
            report.providers.append(block)
            time.sleep(gap_s)
            continue
        for i, case in enumerate(cases):
            run = run_case(t.provider, case, model=t.model)
            block.runs.append(run)
            if on_case:
                on_case(t.provider, case, run, i + 1, len(cases))
            if i < len(cases) - 1:
                time.sleep(gap_s)
        report.providers.append(block)
        time.sleep(gap_s)
    return report


def save_report(report: CompareReport, dest: Path | None = None) -> Path:
    out_dir = PROJECT_ROOT / "docs" / "compare-runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest or (out_dir / f"compare-{stamp}.json")
    dest.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return dest
