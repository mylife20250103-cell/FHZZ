from pathlib import Path

import pytest
from openpyxl import Workbook


def rule_file(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "替换规则"
    ws.append(["修改前", None, None, None, None, "修改后"])
    ws.merge_cells("A1:E1")
    ws.merge_cells("F1:I1")
    fields = ["产品中文品名", "产品英文品名", "产品材质", "产品海关编码"]
    ws.append(["店铺名称", *fields, *fields])
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


def row(store="美1", before="树脂发箍", after="树脂发饰", hs="0096151900"):
    return [store, before, "", "", "", after, "resin hair accessory", "resin", hs]


def test_rules_are_shared_within_region_and_exact_precedes_fuzzy(tmp_path):
    from app.customs.rules import load_rules, match_rules
    rules = load_rules(rule_file(tmp_path / "rules.xlsx", [row(), row("加1"), row(before="树脂发箍套装")]))
    found = match_rules("树脂发箍", rules, "US", 60)
    assert len(found) == 1
    assert found[0].score == 100
    assert found[0].rule.after == ("树脂发饰", "resin hair accessory", "resin", "0096151900")
    assert not match_rules("树脂发箍", rules, "GB", 95)


@pytest.mark.parametrize("column,value", [(6, ""), (7, ""), (8, ""), (9, ""), (6, '=A3'), (1, "未知1")])
def test_invalid_rule_never_executes(tmp_path, column, value):
    from app.customs.rules import load_rules
    data = row()
    data[column - 1] = value
    with pytest.raises(ValueError):
        load_rules(rule_file(tmp_path / "rules.xlsx", [data]))


def test_duplicate_outputs_coalesce_but_conflicts_remain_candidates(tmp_path):
    from app.customs.rules import load_rules, match_rules
    rules = load_rules(rule_file(tmp_path / "rules.xlsx", [row(), row("美2"), row("美3", after="头饰")]))
    found = match_rules("树脂发箍", rules, "US", 95)
    assert len(found) == 2
    assert {c.rule.after[0] for c in found} == {"树脂发饰", "头饰"}


def test_threshold_uses_unrounded_score_and_keeps_negation(tmp_path):
    from app.customs.rules import load_rules, match_rules
    rules = load_rules(rule_file(tmp_path / "rules.xlsx", [row(before="abcdefghij")]))
    assert len(match_rules("abcdefghiX", rules, "US", 90)) == 1
    assert not match_rules("abcdefghiX", rules, "US", 90.01)
    assert not match_rules("不abcdefghij", rules, "US", 100)


def custom_rule_file(path, rows):
    """对应用户实际表：额外产品名、分开的中英文材质和HS CODE、中间空列。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "全店铺产品清单"
    ws.append(["修改前", None, None, None, None, None, None, None, "修改后"])
    ws.merge_cells("A1:G1")
    ws.merge_cells("I1:M1")
    ws.append(["产品名称", "店铺名称", "产品英文品名", "产品中文品名", "英文材质", "中文材质", "HS CODE", None,
               "产品英文品名", "产品中文品名", "英文材质", "中文材质", "HS CODE"])
    for values in rows:
        ws.append(values)
    wb.save(path)
    wb.close()
    return path


def custom_row(after=None):
    return ["内部产品名称", "美13", "old pants", "原裤子", "cotton", "棉", "6104620000", None,
            *(after if after is not None else ["Pants", "裤子", "Polyester", "涤纶", 6104620090])]


def test_custom_layout_uses_english_material_hscode_and_skips_unconfigured_products(tmp_path):
    from app.customs.rules import load_rules, match_rules
    path = custom_rule_file(tmp_path / "custom.xlsx", [custom_row([None] * 5), custom_row()])
    raw = path.read_bytes()
    rules = load_rules(path)
    assert len(rules.rules) == 1
    assert rules.skipped_empty_rows == 1
    assert rules.rules[0].row == 4
    assert rules.rules[0].after == ("裤子", "Pants", "Polyester", "6104620090")
    assert match_rules("原裤子", rules, "US", 95)[0].rule.before[2] == "cotton"
    assert path.read_bytes() == raw


@pytest.mark.parametrize('after', [
    [None, None, None, "涤纶", None],
    ["Pants", "裤子", None, "涤纶", 6104620090],
    ["Pants", "裤子", "=A3", "涤纶", 6104620090],
])
def test_custom_layout_partial_or_formula_rules_still_block_execution(tmp_path, after):
    from app.customs.rules import load_rules
    with pytest.raises(ValueError, match='第3行'):
        load_rules(custom_rule_file(tmp_path / 'partial.xlsx', [custom_row(after)]))


def test_two_columns_mapping_to_same_material_field_are_rejected(tmp_path):
    from app.customs.rules import load_rules
    path = custom_rule_file(tmp_path / 'duplicate.xlsx', [custom_row()])
    from openpyxl import load_workbook
    wb = load_workbook(path)
    wb.active['L2'] = '产品材质'
    wb.save(path)
    wb.close()
    with pytest.raises(ValueError, match='重复|多个'):
        load_rules(path)
