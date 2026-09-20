"""把一張菜單圖丟給三家，看誰能轉出可用的 JSON。"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmclab.client import chat
from llmclab.config import get, load_env

PROMPT = """這是一張餐廳菜單／價目表照片。
請把你看得見的內容轉成 JSON，不要 markdown 圍欄，不要解釋。
欄位用這個形狀：
{
  "title": "菜單標題或店名，看不見就空字串",
  "currency": "TWD",
  "categories": [
    {
      "name": "分類名稱",
      "items": [
        {"name": "品名", "price": 70, "unit": "份", "note": "看不見的註記就空字串"}
      ]
    }
  ],
  "notes": ["菜單上的其他文字"]
}
規則：價格用數字；看不清楚的字不要猜，note 寫「看不清」。
只輸出 JSON。"""


def main() -> int:
    load_env()
    img_path = Path(sys.argv[1])
    raw = img_path.read_bytes()
    mime = "image/jpeg" if img_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]

    jobs = [
        ("groq", None),
        ("gemini", "gemini-3.6-flash"),
        ("mistral", "ministral-3b-latest"),
        ("local", None),
    ]
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "menu-json-runs"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, model in jobs:
        print(f"\n=== {name} {model or '(default)'} ===")
        if not get(name).configured:
            print("  跳過：未設定（本機請填 LOCAL_BASE_URL）")
            continue
        started = time.perf_counter()
        try:
            result = chat(
                name,
                messages,
                model=model,
                max_tokens=2500,
                temperature=0,
                timeout=90,
            )
            text = result.text.strip()
            print(f"  {result.latency_s*1000:.0f} ms  key={result.key_env}  {result.rate_limit.summary()}")
            print(text[:1200] or "(空字串)")
            payload = {"ok": True, "provider": name, "model": result.model, "text": text}
            if text.startswith("```"):
                text = text.strip("`")
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            try:
                parsed = json.loads(text)
                payload["parsed"] = parsed
                items = sum(len(c.get("items") or []) for c in parsed.get("categories") or [])
                print(f"  JSON 可解析  分類 {len(parsed.get('categories') or [])}  品項 {items}")
            except json.JSONDecodeError as exc:
                payload["parse_error"] = str(exc)
                print(f"  JSON 解析失敗：{exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"  失敗：{exc}")
            payload = {"ok": False, "provider": name, "error": str(exc)[:400]}
        (out_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(1.5)

    print(f"\n結果寫在 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
