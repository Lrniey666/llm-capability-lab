"""視覺菜單實驗的離線評分測試。不連外網。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmclab.vision_menu import (  # noqa: E402
    GOLD_PATH,
    MENU_DIR,
    api_model_id,
    classify_model,
    extract_json_text,
    gold_images,
    names_match,
    norm_name,
    score_prediction,
)


def test_gold_files_exist_and_unique():
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    images = gold["images"]
    ids = [i["id"] for i in images]
    files = [i["file"] for i in images]
    assert len(ids) == len(set(ids))
    assert len(files) == len(set(files))
    active = gold_images(gold)
    assert any(i["battery"] == "core" for i in active)
    assert any(i["gold_complete"] for i in active)
    for img in active:
        assert (MENU_DIR / img["file"]).exists(), img["file"]
        assert img["anchors"], img["id"]


def test_classify_skips_non_vision_endpoints():
    assert classify_model("gemini-3.6-flash") == "chat"
    assert classify_model("pixtral-12b-latest") == "chat"
    assert classify_model("Furen-std") == "chat"
    assert classify_model("text-embedding-004") == "wrong_endpoint"
    assert classify_model("bge-m3-embedding") == "wrong_endpoint"
    assert classify_model("Pic-small") == "wrong_endpoint"
    assert classify_model("mistral-ocr-latest") == "ocr"
    assert classify_model("mistral-ocr-4") == "ocr"
    assert classify_model("voxtral-mini-latest") == "wrong_endpoint"
    assert classify_model("models/gemini-3.5-transcribe") == "wrong_endpoint"
    assert classify_model("models/gemini-3.8-live") == "wrong_endpoint"


def test_gemini_api_model_strips_models_prefix():
    assert api_model_id("gemini", "models/gemini-3.6-flash") == "gemini-3.6-flash"
    assert api_model_id("mistral", "ministral-3b-latest") == "ministral-3b-latest"


def test_extract_json_from_fences_and_preamble():
    parsed, err = extract_json_text('```json\n{"title": "老余", "categories": []}\n```')
    assert err is None and parsed["title"] == "老余"
    parsed, err = extract_json_text('思考中...\n{"title": "三商巧福", "categories": [{"name": "麵", "items": []}]}')
    assert err is None and parsed["title"] == "三商巧福"
    parsed, err = extract_json_text("")
    assert parsed is None and err == "empty"


def test_names_match_aliases_and_normalization():
    assert names_match("半筋半肉牛肉麵", "半筋半肉套餐", ["半筋半肉"])
    assert names_match("紐西蘭菲力牛排", "菲力牛排 $790", ["菲力"])
    assert names_match("Pecel ayam", "pecel ayam (nasi)", ["Pecel ayam"])
    assert not names_match("紅茶", "綠茶", ["紅茶"])
    assert "台" in norm_name("臺灣松阪豬") or "台灣" in "台灣松阪豬"


def test_score_json_and_raw_text_and_hallucination():
    gold = {
        "title_aliases": ["優惠套餐"],
        "gold_complete": True,
        "anchors": [
            {"name": "鐵板麵", "aliases": ["1號"], "prices": [60]},
            {"name": "香雞蛋堡", "aliases": ["2號"], "prices": [75]},
        ],
    }
    parsed = {
        "title": "優惠套餐",
        "categories": [
            {
                "name": "套餐",
                "items": [
                    {"name": "鐵板麵+紅茶", "price": 60},
                    {"name": "清炒青菜", "price": 120},
                ],
            }
        ],
    }
    score = score_prediction(parsed, "", gold)
    assert score["json_ok"] and score["schema_ok"] and score["title_hit"]
    assert score["name_json_recall"] == 0.5
    assert score["price_json_recall"] == 0.5
    assert "清炒青菜" in score["extra_names"]

    text_only = score_prediction(None, "牆上寫優惠套餐，1號鐵板麵 60元，2號香雞蛋堡75", gold)
    assert text_only["json_ok"] is False
    assert text_only["name_recall"] == 1.0
    assert text_only["price_recall"] == 1.0
