"""菜單圖視覺辨識實驗：catalog → probe → extract → score。

設計目標不是「誰比較會聊天」，而是在同一組真實菜單照片上，
量測各家「每一個」模型能不能看圖、能不能把品名／價格抽成可入庫 JSON。

免費層配額極不對稱（Gemini 約 20 RPD），所以分成四段、可斷點續跑：
  catalog  只打 GET /v1/models
  probe    每模型一張 16×16 紅 PNG，判定接不接受 image_url
  core     通過／弱通過的模型 × 4 張核心刺激
  extended 通過的模型 × 其餘菜單圖（Gemini 預設只跑一家，避免把日額打光）
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .checks import RED_SQUARE_PNG_B64
from .client import chat, make_client
from .compare import NON_CHAT_MARKERS, timeout_for_model
from .config import PROJECT_ROOT, Provider, get

MENU_DIR = PROJECT_ROOT / "menu_example"
GOLD_PATH = PROJECT_ROOT / "docs" / "vision-menu" / "gold.json"
RUNS_DIR = PROJECT_ROOT / "docs" / "vision-menu" / "runs"

PROVIDERS_DEFAULT = ("gemini", "mistral", "iai")

# 這些模型就算掛在 chat completions 清單上，也不是「看圖理解」。
WRONG_ENDPOINT_MARKERS = NON_CHAT_MARKERS + (
    "imagen",
    "veo",
    "lyria",
    "native-audio",
    "computer-use",
    "moderation",
    "aqa",
    "tts",
    "embedding",
    "embed",
    "rerank",
    "z-image",
    "image-generation",
    "voxtral",
    "transcribe",
    "nano-banana",
    "deep-research",
    "antigravity",
    "-live",
    "live-preview",
    "live-translate",
)

OCR_MARKERS = ("mistral-ocr",)

# Gemini 免費層大約 5 RPM / 20 RPD；Mistral ~1 rps。
GAP_S = {"gemini": 13.0, "mistral": 1.3, "iai": 1.2}

EXTRACT_PROMPT = """這是一張台灣餐廳菜單／價目表照片。
把你看得見的內容轉成 JSON。不要 markdown 圍欄，不要解釋，不要思考過程。
看不清楚的字不要猜、不要編造不存在的品項。
形狀：
{
  "title": "菜單標題或店名，看不見就空字串",
  "currency": "TWD",
  "categories": [
    {
      "name": "分類名稱",
      "items": [
        {"name": "品名", "price": 70, "unit": "份", "note": ""}
      ]
    }
  ],
  "notes": ["菜單上的其他文字"]
}
規則：
- price 用數字；同一品項有大小／套餐與單點兩個價就用較明顯的那個，另一個寫進 note
- 看不清就 note 寫「看不清」，不要填假價格
- 只輸出 JSON
"""

PROBE_PROMPT = "這張圖是什麼顏色？只回顏色名稱。"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_gold(path: Path | None = None) -> dict[str, Any]:
    gold_path = path or GOLD_PATH
    return json.loads(gold_path.read_text(encoding="utf-8"))


def gold_images(gold: dict[str, Any] | None = None, *, include_skip: bool = False) -> list[dict[str, Any]]:
    data = gold or load_gold()
    images = list(data.get("images") or [])
    if include_skip:
        return images
    return [img for img in images if not img.get("skip")]


def battery_images(battery: str, gold: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    want = {"core", "extended"} if battery == "all" else {battery}
    return [img for img in gold_images(gold) if img.get("battery") in want]


def slug(value: str) -> str:
    text = re.sub(r"[^\w.\-+]+", "-", value, flags=re.UNICODE).strip("-")
    return text[:120] or "model"


def classify_model(model_id: str) -> str:
    """chat / ocr / non_chat / wrong_endpoint。後兩者不打圖。"""
    n = (model_id or "").lower()
    if any(m in n for m in OCR_MARKERS):
        return "ocr"
    if any(m in n for m in WRONG_ENDPOINT_MARKERS):
        return "wrong_endpoint"
    if any(m in n for m in NON_CHAT_MARKERS):
        return "non_chat"
    return "chat"


def api_model_id(provider: str, model: str) -> str:
    """Gemini 的 /v1/models 會回 `models/gemini-…`，聊天端點要拿掉前綴。"""
    if provider == "gemini" and model.startswith("models/"):
        return model.split("/", 1)[1]
    return model


def extract_json_text(text: str) -> tuple[Any | None, str | None]:
    """從模型輸出裡挖 JSON。容忍 markdown 圍欄與前後廢話。"""
    raw = (text or "").strip()
    if not raw:
        return None, "empty"
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        snippet = raw[start : end + 1]
        try:
            return json.loads(snippet), None
        except json.JSONDecodeError as exc:
            return None, str(exc)
    return None, "no JSON object"


_WS_RE = re.compile(r"[\s\-_/·•、，,（）()【】\[\]|]+")
_DIGIT_TRANS = str.maketrans("０１２３４５６７８９", "0123456789")


def norm_name(text: str) -> str:
    s = (text or "").strip().lower().translate(_DIGIT_TRANS)
    s = s.replace("臺", "台").replace("麺", "麵").replace("麪", "麵")
    s = s.replace("鉄", "鐵")
    return _WS_RE.sub("", s)


def names_match(gold_name: str, predicted: str, aliases: list[str] | None = None) -> bool:
    cand = norm_name(predicted)
    if not cand:
        return False
    needles = [gold_name, *(aliases or [])]
    for needle in needles:
        g = norm_name(needle)
        if not g:
            continue
        if g == cand or (len(g) >= 2 and (g in cand or cand in g)):
            return True
    return False


def flatten_items(parsed: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(parsed, dict):
        return items
    for cat in parsed.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        cat_name = cat.get("name") or ""
        for item in cat.get("items") or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["_category"] = cat_name
            items.append(row)
    return items


def _price_nums(value: Any) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [int(value)]
    text = str(value or "")
    return [int(m) for m in re.findall(r"\d+", text)]


def _anchor_hit(anchor: dict[str, Any], items: list[dict[str, Any]], raw_text: str) -> dict[str, Any]:
    aliases = list(anchor.get("aliases") or [])
    gold_name = anchor["name"]
    gold_prices = [int(p) for p in anchor.get("prices") or []]
    matched_item = next(
        (it for it in items if names_match(gold_name, str(it.get("name") or ""), aliases)),
        None,
    )
    name_in_json = matched_item is not None
    price_in_json = False
    if matched_item is not None:
        pred_prices = _price_nums(matched_item.get("price"))
        price_in_json = any(p in pred_prices for p in gold_prices)

    name_in_text = False
    price_in_text = False
    blob = raw_text or ""
    for needle in [gold_name, *aliases]:
        n = needle.strip()
        if len(n) < 2:
            continue
        idx = blob.find(n)
        if idx < 0:
            # 大小寫不敏感的拉丁文
            idx = blob.lower().find(n.lower())
        if idx < 0:
            continue
        name_in_text = True
        window = blob[max(0, idx - 24) : idx + len(n) + 48]
        nums = [int(m) for m in re.findall(r"\d+", window)]
        if any(p in nums for p in gold_prices):
            price_in_text = True
            break
    return {
        "name": gold_name,
        "name_json": name_in_json,
        "price_json": price_in_json,
        "name_text": name_in_text,
        "price_text": price_in_text,
        "name_hit": name_in_json or name_in_text,
        "price_hit": price_in_json or price_in_text,
    }


def score_prediction(
    parsed: Any,
    raw_text: str,
    image_gold: dict[str, Any],
) -> dict[str, Any]:
    items = flatten_items(parsed)
    anchors = list(image_gold.get("anchors") or [])
    hits = [_anchor_hit(a, items, raw_text) for a in anchors]
    n = len(hits) or 1
    title = ""
    if isinstance(parsed, dict):
        title = str(parsed.get("title") or "")
    title_aliases = list(image_gold.get("title_aliases") or [])
    title_hit = any(a and a.lower() in (title + " " + (raw_text or "")).lower() for a in title_aliases)

    extras = []
    if image_gold.get("gold_complete"):
        for it in items:
            pname = str(it.get("name") or "")
            if not pname:
                continue
            if not any(names_match(a["name"], pname, a.get("aliases")) for a in anchors):
                extras.append(pname)

    schema_ok = isinstance(parsed, dict) and isinstance(parsed.get("categories"), list)
    return {
        "json_ok": parsed is not None,
        "schema_ok": schema_ok,
        "title": title,
        "title_hit": title_hit,
        "item_count": len(items),
        "anchor_n": len(anchors),
        "name_json_recall": sum(h["name_json"] for h in hits) / n,
        "price_json_recall": sum(h["price_json"] for h in hits) / n,
        "name_recall": sum(h["name_hit"] for h in hits) / n,
        "price_recall": sum(h["price_hit"] for h in hits) / n,
        "extra_names": extras,
        "hallucination_n": len(extras) if image_gold.get("gold_complete") else None,
        "anchors": hits,
    }


def encode_image(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
    data = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(data).decode()}", mime


def vision_messages(prompt: str, data_url: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]


def looks_red(text: str) -> bool:
    blob = (text or "").strip().lower()
    return any(w in blob for w in ("紅", "red", "scarlet", "crimson"))


@dataclass
class ModelEntry:
    provider: str
    model: str
    kind: str
    probe: str | None = None
    probe_detail: str = ""
    latency_s: float | None = None
    error: str | None = None


def catalog_provider(provider: Provider) -> list[ModelEntry]:
    if provider.key == "iai":
        from .compare import catalog_iai_models

        names = catalog_iai_models()
    else:
        client = make_client(provider, timeout=30)
        names = sorted({m.id for m in client.models.list()})
    return [ModelEntry(provider.key, mid, classify_model(mid)) for mid in names]


def new_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = RUNS_DIR / f"vision-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def probe_outcome(text: str, error: str | None, status: int | None) -> str:
    if error:
        blob = (error or "").lower()
        if status in {400, 404, 415, 422} or any(
            k in blob
            for k in (
                "image",
                "vision",
                "multimodal",
                "content part",
                "does not support",
                "unsupported",
                "invalid content",
                "media",
            )
        ):
            return "reject"
        if status == 429 or "rate" in blob or "quota" in blob:
            return "quota"
        return "error"
    if looks_red(text):
        return "accept_correct"
    if (text or "").strip():
        return "accept_wrong"
    return "accept_empty"


def _status_from_exc(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)


def mistral_ocr(provider: Provider, model: str, data_url: str, *, timeout: float = 90.0) -> tuple[str, float]:
    """Mistral 文件 OCR 端點（不是 chat.completions）。"""
    import urllib.error
    import urllib.request

    body = json.dumps(
        {
            "model": model,
            "document": {"type": "image_url", "image_url": data_url},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{provider.resolved_base_url}/ocr",
        data=body,
        headers={
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        err = RuntimeError(f"OCR HTTP {exc.code}: {detail}")
        setattr(err, "status_code", exc.code)
        raise err from exc
    elapsed = time.perf_counter() - started
    pages = payload.get("pages") or []
    texts = [p.get("markdown") or p.get("text") or "" for p in pages if isinstance(p, dict)]
    return "\n".join(texts).strip() or json.dumps(payload, ensure_ascii=False)[:4000], elapsed


def run_probe(provider: Provider, model: str, *, timeout: float | None = None) -> ModelEntry:
    data_url = f"data:image/png;base64,{RED_SQUARE_PNG_B64}"
    timeout = timeout or timeout_for_model(provider, model)
    entry = ModelEntry(provider.key, model, classify_model(model))
    try:
        if entry.kind == "ocr":
            text, latency = mistral_ocr(provider, model, data_url, timeout=min(timeout, 60.0))
            entry.latency_s = latency
            entry.probe_detail = (text or "")[:80]
            entry.probe = probe_outcome(text, None, None)
        else:
            result = chat(
                provider.key,
                vision_messages(PROBE_PROMPT, data_url),
                model=api_model_id(provider.key, model),
                max_tokens=32,
                temperature=0,
                timeout=min(timeout, 60.0),
            )
            entry.latency_s = result.latency_s
            entry.probe_detail = (result.text or "")[:80]
            entry.probe = probe_outcome(result.text, None, None)
    except Exception as exc:  # noqa: BLE001
        status = _status_from_exc(exc)
        entry.error = str(exc)[:240]
        entry.probe = probe_outcome("", entry.error, status)
    return entry


def run_extract(
    provider: Provider,
    model: str,
    image_path: Path,
    *,
    timeout: float | None = None,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    data_url, mime = encode_image(image_path)
    timeout = timeout or max(timeout_for_model(provider, model), 120.0)
    payload: dict[str, Any] = {
        "provider": provider.key,
        "model": model,
        "file": image_path.name,
        "mime": mime,
        "bytes": image_path.stat().st_size,
        "ok": False,
        "text": "",
        "parsed": None,
        "parse_error": None,
        "latency_s": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "error": None,
        "status": None,
    }
    try:
        if classify_model(model) == "ocr":
            text, latency = mistral_ocr(provider, model, data_url, timeout=timeout)
            payload["ok"] = True
            payload["text"] = text
            payload["latency_s"] = latency
            parsed, err = extract_json_text(text)
            payload["parsed"] = parsed
            payload["parse_error"] = err
            payload["endpoint"] = "ocr"
        else:
            result = chat(
                provider.key,
                vision_messages(EXTRACT_PROMPT, data_url),
                model=api_model_id(provider.key, model),
                max_tokens=max_tokens,
                temperature=0,
                timeout=timeout,
            )
            payload["ok"] = True
            payload["text"] = result.text or ""
            payload["latency_s"] = result.latency_s
            payload["prompt_tokens"] = result.prompt_tokens
            payload["completion_tokens"] = result.completion_tokens
            parsed, err = extract_json_text(result.text or "")
            payload["parsed"] = parsed
            payload["parse_error"] = err
            payload["endpoint"] = "chat"
    except Exception as exc:  # noqa: BLE001
        payload["error"] = str(exc)[:400]
        payload["status"] = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "response", None), "status_code", None
        )
    return payload


def extract_filename(provider: str, model: str, image_id: str) -> str:
    return f"{provider}__{slug(model)}__{image_id}.json"


def vision_ok(probe: str | None) -> bool:
    return probe in {"accept_correct", "accept_wrong", "accept_empty"}


def summarize_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r.get("score")]
    if not scored:
        return {"n": 0}
    n = len(scored)
    def avg(key: str) -> float:
        return sum(r["score"][key] for r in scored) / n

    return {
        "n": n,
        "json_ok": sum(1 for r in scored if r["score"]["json_ok"]) / n,
        "schema_ok": sum(1 for r in scored if r["score"]["schema_ok"]) / n,
        "title_hit": sum(1 for r in scored if r["score"]["title_hit"]) / n,
        "name_recall": avg("name_recall"),
        "price_recall": avg("price_recall"),
        "name_json_recall": avg("name_json_recall"),
        "price_json_recall": avg("price_json_recall"),
        "mean_latency_s": sum((r.get("latency_s") or 0) for r in scored) / n,
        "hallucination_n": sum((r["score"].get("hallucination_n") or 0) for r in scored),
    }


def render_report(run_dir: Path, gold: dict[str, Any]) -> str:
    catalog = load_json(run_dir / "catalog.json") if (run_dir / "catalog.json").exists() else []
    probe = load_json(run_dir / "probe.json") if (run_dir / "probe.json").exists() else []
    scores = load_json(run_dir / "scores.json") if (run_dir / "scores.json").exists() else {"rows": [], "by_model": []}

    lines = [
        "# 菜單圖視覺辨識實驗報告",
        "",
        f"**Run：** `{run_dir.name}`  ",
        f"**刺激集：** `menu_example/`（gold v{gold.get('version')}）  ",
        f"**標註：** {gold.get('annotator')}  ",
        f"**產出時間：** {utc_now()}",
        "",
        "## 1. 問題",
        "",
        "在真實台灣菜單照片上，Gemini / Mistral / iAI **目錄裡每一個模型**能不能看圖，",
        "以及通過視覺探針的模型，品名／價格抽取能不能達到可入庫的程度。",
        "",
        "評分是規則比對 gold 錨點，不是再用一個模型當裁判。",
        "JSON 解析成功 ≠ OCR 正確；先前 `ministral-3b` 就會產出可解析但內容全猜的 JSON。",
        "",
        "## 2. 目錄",
        "",
        "| Provider | 模型數 | chat | 非對話／錯端點 |",
        "|---|---:|---:|---:|",
    ]
    by_p: dict[str, list[dict[str, Any]]] = {}
    for row in catalog:
        by_p.setdefault(row["provider"], []).append(row)
    for name in PROVIDERS_DEFAULT:
        rows = by_p.get(name, [])
        chat_n = sum(1 for r in rows if r["kind"] == "chat")
        other = len(rows) - chat_n
        lines.append(f"| {name} | {len(rows)} | {chat_n} | {other} |")

    lines += ["", "## 3. 視覺探針（紅正方形）", "",
              "| Provider | 模型 | 結果 | 延遲 | 細節 |",
              "|---|---|---|---:|---|"]
    for row in probe:
        ms = f"{row['latency_s']*1000:.0f} ms" if row.get("latency_s") is not None else "—"
        detail = (row.get("probe_detail") or row.get("error") or "")[:60]
        lines.append(
            f"| {row['provider']} | `{row['model']}` | {row.get('probe') or row.get('kind')} | {ms} | {detail} |"
        )

    lines += ["", "## 4. 菜單抽取（模型 × 圖）", ""]
    by_model = scores.get("by_model") or []
    if by_model:
        lines += [
            "| Provider | 模型 | 圖數 | JSON | schema | 店名 | 品名召回 | 價格召回 | JSON品名 | JSON價格 | 延遲 | 幻覺 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for block in by_model:
            s = block["summary"]
            if not s.get("n"):
                continue
            lines.append(
                "| {provider} | `{model}` | {n} | {json_ok:.0%} | {schema_ok:.0%} | {title_hit:.0%} | "
                "{name_recall:.0%} | {price_recall:.0%} | {name_json_recall:.0%} | {price_json_recall:.0%} | "
                "{lat:.1f}s | {hall} |".format(
                    provider=block["provider"],
                    model=block["model"],
                    n=s["n"],
                    json_ok=s["json_ok"],
                    schema_ok=s["schema_ok"],
                    title_hit=s["title_hit"],
                    name_recall=s["name_recall"],
                    price_recall=s["price_recall"],
                    name_json_recall=s["name_json_recall"],
                    price_json_recall=s["price_json_recall"],
                    lat=s["mean_latency_s"],
                    hall=s.get("hallucination_n") if s.get("hallucination_n") is not None else "—",
                )
            )
    else:
        lines.append("_尚無抽取結果。_")

    lines += [
        "",
        "## 5. 讀法",
        "",
        "- **accept_correct**：API 吃圖，且紅正方形答對。這是「真的有視覺」。",
        "- **accept_wrong / accept_empty**：吃圖但顏色答錯或空白——仍丟菜單，因為紅塊太小可能被忽略。",
        "- **reject**：端點拒圖。不應接進菜單入庫路徑。",
        "- **品名召回**：gold 錨點有沒有出現在 JSON 或原文（含思考殘渣）。",
        "- **JSON 品名／價格**：只有進結構化欄位才算，這才是入庫指標。",
        "- **幻覺**：只在 `gold_complete=true` 的圖上計算多出來的品名。",
        "",
        "## 6. 限制",
        "",
        "- Gemini 免費層日額很低；未跑完的模型會標 `quota`，不是能力失敗。",
        "- 錨點不是全量轉錄；召回是下限，不是菜單覆蓋率。",
        "- 垂直中文、反光、社群截圖字極小，人類標註本身也有誤差。",
        "",
    ]
    return "\n".join(lines)


OnProgress = Callable[[str], None]


def _emit(on_progress: OnProgress | None, message: str) -> None:
    if on_progress:
        on_progress(message)


def _gap(provider: str, gap_override: float | None) -> float:
    if gap_override is not None:
        return gap_override
    return GAP_S.get(provider, 1.2)


def run_catalog(providers: list[Provider], run_dir: Path, on_progress: OnProgress | None = None) -> list[dict[str, Any]]:
    entries: list[ModelEntry] = []
    for p in providers:
        _emit(on_progress, f"catalog {p.key}")
        try:
            found = catalog_provider(p)
        except Exception as exc:  # noqa: BLE001
            found = [ModelEntry(p.key, p.resolved_model, "chat", error=str(exc)[:240], probe="error")]
        entries.extend(found)
        _emit(on_progress, f"  {p.key}: {len(found)} models")
    payload = [asdict(e) for e in entries]
    write_json(run_dir / "catalog.json", payload)
    return payload


def run_probes(
    providers: list[Provider],
    run_dir: Path,
    *,
    gap_s: float | None = None,
    gemini_probe_limit: int = 8,
    on_progress: OnProgress | None = None,
) -> list[dict[str, Any]]:
    catalog_path = run_dir / "catalog.json"
    if catalog_path.exists():
        catalog = load_json(catalog_path)
        for row in catalog:
            row["kind"] = classify_model(row["model"])
    else:
        catalog = run_catalog(providers, run_dir, on_progress)

    probe_path = run_dir / "probe.json"
    done: dict[tuple[str, str], dict[str, Any]] = {}
    if probe_path.exists():
        for row in load_json(probe_path):
            done[(row["provider"], row["model"])] = row

    def probe_priority(row: dict[str, Any]) -> tuple:
        n = (row.get("model") or "").lower()
        likely = any(tag in n for tag in ("flash", "pro", "pixtral", "vision", "lite", "small", "medium", "ocr"))
        kind_rank = 0 if row.get("kind") in {"chat", "ocr"} else 1
        return (kind_rank, 0 if likely else 1, row.get("provider") or "", n)

    catalog = sorted(catalog, key=probe_priority)
    by_provider = {p.key: p for p in providers}
    rows = list(done.values())
    quota_skip: set[str] = set()
    gemini_probed = sum(
        1
        for r in done.values()
        if r.get("provider") == "gemini"
        and r.get("probe") not in {None, "skipped_wrong_endpoint", "deferred_quota_cap"}
    )

    for row in catalog:
        key = (row["provider"], row["model"])
        if key in done:
            continue
        if row["provider"] not in by_provider:
            continue
        if row["kind"] not in {"chat", "ocr"}:
            rec = dict(row)
            rec["probe"] = "skipped_wrong_endpoint"
            rec["probe_detail"] = row["kind"]
            rows.append(rec)
            done[key] = rec
            write_json(probe_path, rows)
            continue
        if row["provider"] == "gemini" and gemini_probe_limit and gemini_probed >= gemini_probe_limit:
            rec = dict(row)
            rec["probe"] = "deferred_quota_cap"
            rec["probe_detail"] = f"Gemini 探針上限 {gemini_probe_limit}，把日額留給菜單抽取"
            rows.append(rec)
            done[key] = rec
            write_json(probe_path, rows)
            continue
        if row["provider"] in quota_skip and row["provider"] == "gemini":
            rec = dict(row)
            rec["probe"] = "quota"
            rec["probe_detail"] = "同家前序已 429，本輪不再打"
            rows.append(rec)
            done[key] = rec
            write_json(probe_path, rows)
            continue

        p = by_provider[row["provider"]]
        _emit(on_progress, f"probe {p.key}/{row['model']}")
        entry = run_probe(p, row["model"])
        rec = asdict(entry)
        rec["kind"] = row["kind"]
        rows.append(rec)
        done[key] = rec
        write_json(probe_path, rows)
        if p.key == "gemini":
            gemini_probed += 1
        _emit(on_progress, f"  → {entry.probe} {(entry.probe_detail or entry.error or '')[:80]}")
        if entry.probe == "quota":
            if p.key == "gemini":
                quota_skip.add(p.key)
            else:
                time.sleep(max(_gap(p.key, gap_s), 3.0))
            continue
        time.sleep(_gap(p.key, gap_s))
    return rows


def _targets_for_extract(
    probe_rows: list[dict[str, Any]],
    providers: list[Provider],
    *,
    gemini_extended_limit: int = 1,
    battery: str,
) -> list[tuple[Provider, str]]:
    by_provider = {p.key: p for p in providers}
    picked: list[tuple[Provider, str]] = []
    gemini_n = 0
    # 先正確、再弱通過；reject / quota 不跑菜單。
    order = {"accept_correct": 0, "accept_wrong": 1, "accept_empty": 2}
    eligible = [r for r in probe_rows if vision_ok(r.get("probe"))]
    eligible.sort(key=lambda r: (r["provider"], order.get(r.get("probe") or "", 9), r["model"]))
    for row in eligible:
        p = by_provider.get(row["provider"])
        if p is None:
            continue
        model = row["model"]
        if battery == "extended":
            if "mistral-ocr" in model and model != "mistral-ocr-latest":
                continue
            if re.search(r"-\d{4}$", model):
                continue
        if battery == "extended" and row["provider"] == "gemini":
            if gemini_n >= gemini_extended_limit:
                continue
            gemini_n += 1
        picked.append((p, row["model"]))
    return picked


def run_extracts(
    providers: list[Provider],
    run_dir: Path,
    *,
    battery: str,
    gold: dict[str, Any] | None = None,
    gap_s: float | None = None,
    gemini_extended_limit: int = 1,
    on_progress: OnProgress | None = None,
) -> list[dict[str, Any]]:
    gold = gold or load_gold()
    images = battery_images(battery, gold)
    probe_path = run_dir / "probe.json"
    if not probe_path.exists():
        raise SystemExit("還沒跑 probe。先 `python -m llmclab vision-menu --phase probe`")
    probe_rows = load_json(probe_path)
    targets = _targets_for_extract(
        probe_rows, providers, gemini_extended_limit=gemini_extended_limit, battery=battery
    )
    if not targets:
        _emit(on_progress, "沒有通過視覺探針的模型，略過抽取")
        return []

    extract_dir = run_dir / "extracts"
    extract_dir.mkdir(parents=True, exist_ok=True)
    quota_skip: set[str] = set()
    rows: list[dict[str, Any]] = []

    for p, model in targets:
        for img in images:
            image_id = img["id"]
            dest = extract_dir / extract_filename(p.key, model, image_id)
            if dest.exists():
                payload = load_json(dest)
                payload["score"] = score_prediction(payload.get("parsed"), payload.get("text") or "", img)
                payload["image_id"] = image_id
                payload["battery"] = img.get("battery")
                rows.append(payload)
                continue
            if p.key in quota_skip:
                payload = {
                    "provider": p.key,
                    "model": model,
                    "file": img["file"],
                    "image_id": image_id,
                    "ok": False,
                    "error": "quota skipped",
                    "status": 429,
                }
                write_json(dest, payload)
                rows.append(payload)
                continue
            path = MENU_DIR / img["file"]
            if not path.exists():
                payload = {"provider": p.key, "model": model, "file": img["file"], "error": "missing file"}
                write_json(dest, payload)
                rows.append(payload)
                continue
            _emit(on_progress, f"extract {p.key}/{model} {img['file']}")
            payload = run_extract(p, model, path)
            payload["image_id"] = image_id
            payload["battery"] = img.get("battery")
            payload["score"] = score_prediction(payload.get("parsed"), payload.get("text") or "", img)
            write_json(dest, payload)
            rows.append(payload)
            detail = payload.get("error") or (
                f"json={'ok' if payload.get('parsed') else 'fail'} "
                f"name={payload['score']['name_recall']:.0%} "
                f"price={payload['score']['price_recall']:.0%}"
            )
            _emit(on_progress, f"  → {detail}")
            if payload.get("status") == 429 or (payload.get("error") or "").lower().find("quota") >= 0:
                quota_skip.add(p.key)
                continue
            time.sleep(_gap(p.key, gap_s))
    return rows


def write_scores(run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row.get("provider"), row.get("model")), []).append(row)
    by_model = [
        {
            "provider": k[0],
            "model": k[1],
            "summary": summarize_scores(v),
        }
        for k, v in grouped.items()
    ]
    by_model.sort(key=lambda b: (-(b["summary"].get("name_recall") or 0), b["provider"], b["model"]))
    payload = {"rows": rows, "by_model": by_model, "updated_at": utc_now()}
    write_json(run_dir / "scores.json", payload)
    return payload


def collect_extract_rows(run_dir: Path, gold: dict[str, Any]) -> list[dict[str, Any]]:
    extract_dir = run_dir / "extracts"
    if not extract_dir.exists():
        return []
    index = {img["id"]: img for img in gold_images(gold, include_skip=True)}
    rows = []
    for path in sorted(extract_dir.glob("*.json")):
        payload = load_json(path)
        image_id = payload.get("image_id")
        img = index.get(image_id)
        if img and "score" not in payload:
            payload["score"] = score_prediction(payload.get("parsed"), payload.get("text") or "", img)
        rows.append(payload)
    return rows


def run_experiment(
    *,
    providers: list[str] | None = None,
    phase: str = "all",
    run_dir: Path | None = None,
    gap_s: float | None = None,
    gemini_extended_limit: int = 1,
    on_progress: OnProgress | None = None,
) -> Path:
    names = list(providers or PROVIDERS_DEFAULT)
    objs = [get(n) for n in names]
    missing = [p for p in objs if not p.configured]
    objs = [p for p in objs if p.configured]
    for p in missing:
        _emit(on_progress, f"跳過未設定：{p.key}")
    if not objs:
        raise SystemExit("沒有已設定的 Gemini / Mistral / iAI 金鑰")

    gold = load_gold()
    dest = run_dir or new_run_dir()
    dest.mkdir(parents=True, exist_ok=True)
    write_json(
        dest / "meta.json",
        {
            "started_at": utc_now(),
            "providers": [p.key for p in objs],
            "phase": phase,
            "menu_dir": str(MENU_DIR),
            "gold": str(GOLD_PATH),
        },
    )

    if phase in {"all", "catalog"}:
        run_catalog(objs, dest, on_progress)
    if phase in {"all", "probe"}:
        run_probes(objs, dest, gap_s=gap_s, on_progress=on_progress, gemini_probe_limit=8)
    rows: list[dict[str, Any]] = []
    if phase in {"all", "core"}:
        rows.extend(
            run_extracts(
                objs, dest, battery="core", gold=gold, gap_s=gap_s,
                gemini_extended_limit=99, on_progress=on_progress,
            )
        )
    if phase in {"all", "extended"}:
        rows.extend(
            run_extracts(
                objs, dest, battery="extended", gold=gold, gap_s=gap_s,
                gemini_extended_limit=gemini_extended_limit, on_progress=on_progress,
            )
        )
    if phase == "score" or rows or (dest / "extracts").exists():
        all_rows = collect_extract_rows(dest, gold)
        write_scores(dest, all_rows)
        report = render_report(dest, gold)
        (dest / "report.md").write_text(report, encoding="utf-8")
        (PROJECT_ROOT / "docs" / "vision-menu" / "最新報告.md").write_text(report, encoding="utf-8")
        _emit(on_progress, f"報告：{dest / 'report.md'}")
    return dest
