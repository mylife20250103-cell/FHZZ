from __future__ import annotations

from app.services.sensitive_word_service import (
    apply_whitelist,
    keyword_hits_in_text,
    normalize_text,
    scan_paths,
)
from app.json_io import write_json


def test_normalize_and_case():

    assert normalize_text("  Hello\n  World  ") == "Hello World"
    assert keyword_hits_in_text("Hello Battery Pack", "battery", [])
    assert not keyword_hits_in_text("Hello Pack", "battery", [])


def test_chinese_contains_and_multi_keyword():

    text = "儿童玩具电池套装"
    assert keyword_hits_in_text(text, "电池", [])
    assert keyword_hits_in_text(text, "儿童", [])


def test_per_keyword_whitelist():

    text = "lithium battery for camera"
    assert keyword_hits_in_text(text, "battery", [])
    assert not keyword_hits_in_text(
        text,
        "battery",
        ["lithium battery"],
    )
    # whitelist of another keyword does not apply
    assert keyword_hits_in_text(
        text,
        "battery",
        ["camera"],
    )


def test_field_scope_and_aggregation(tmp_path, monkeypatch):

    from openpyxl import Workbook

    workbook = Workbook()
    ws = workbook.active
    ws.title = "Sheet1"
    ws.append(
        ["产品英文品名", "产品中文品名", "英文产品材质", "中文产品材质", "其他"]
    )
    ws.append(["Toy Battery", "玩具电池", "ABS", "塑料", "battery hidden"])
    file_path = tmp_path / "sample.xlsx"
    workbook.save(file_path)
    workbook.close()

    config = tmp_path / "sensitive_words.json"
    write_json(
        config,
        {
            "version": "1.0",
            "keywords": [
                {
                    "keyword": "battery",
                    "category": "合规",
                    "enabled": True,
                    "fields": ["ProductEN"],
                    "whitelist_phrases": [],
                },
                {
                    "keyword": "电池",
                    "category": "合规",
                    "enabled": True,
                    "fields": ["ProductCN"],
                    "whitelist_phrases": [],
                },
            ],
        },
    )

    result = scan_paths([file_path], config_path=config)

    assert result.hit_count == 2
    keywords = {hit.keyword for hit in result.hits}
    assert keywords == {"battery", "电池"}
    assert all(hit.field_code in {"ProductEN", "ProductCN"} for hit in result.hits)
    assert result.hit_file_count == 1
    assert len(result.aggregates) == 2
