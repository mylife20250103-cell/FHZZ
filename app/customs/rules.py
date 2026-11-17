"""只读规则加载及确定性的中文品名匹配。"""
from __future__ import annotations

import hashlib
import math
import re
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from app.customs.models import Candidate, FIELDS, REGIONS, Rule, RuleSet


def text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def header_field(value) -> str:
    label = re.sub(r"\s+", "", text(value)).rstrip("*＊").casefold()
    aliases = {field.casefold(): field for field in FIELDS}
    aliases.update({"店铺名称": "店铺名称", "英文材质": "产品材质", "英文产品材质": "产品材质",
                    "hscode": "产品海关编码", "中文材质": "中文材质", "中文产品材质": "中文材质"})
    return aliases.get(label, "")


def load_rules(path: Path) -> RuleSet:
    path = Path(path).resolve()
    if path.suffix.lower() != ".xlsx":
        raise ValueError("规则文件请选择 .xlsx；按“修改前/修改后”左右并列填写")
    raw = path.read_bytes()
    wb = load_workbook(BytesIO(raw), read_only=True, data_only=False)
    try:
        found = []
        diagnostics = []
        required = [("修改前", "店铺名称")] + [(g, f) for g in ("修改前", "修改后") for f in FIELDS]
        for ws in wb.worksheets:
            rows = list(ws.iter_rows())
            if len(rows) < 2:
                continue
            groups = {}
            active = ""
            for c, cell in enumerate(rows[0]):
                if text(cell.value) in ("修改前", "修改后"):
                    active = text(cell.value)
                groups[c] = active
            if not {"修改前", "修改后"}.issubset(set(groups.values())):
                diagnostics.append(f"【{ws.title}】第1行缺少“修改前/修改后”分组")
                continue
            mapping = {}
            for c, cell in enumerate(rows[1]):
                label = header_field(cell.value)
                if not label:
                    continue  # 产品内部名称、备注或分隔列不参与替换。
                key = (groups.get(c), label)
                if key in mapping:
                    raise ValueError(f"规则表【{ws.title}】第2行{key[0]}的{label}列重复（{cell.coordinate}），不能确定使用哪一列")
                mapping[key] = c
            missing = [f"{group}/{field}" for group, field in required if (group, field) not in mapping]
            if missing:
                diagnostics.append(f"【{ws.title}】缺少：" + "、".join(missing))
                continue
            found.append((ws.title, rows, mapping))
        if not found:
            detail = "；".join(diagnostics[:5])
            raise ValueError("未识别到完整规则表。第1行为修改前/修改后，第2行为字段名；材质可用“产品材质/英文材质”，编码可用“产品海关编码/HS CODE”。" + detail)
        if len(found) > 1:
            raise ValueError("发现多张完整规则表，请只保留一张启用表：" + "、".join(item[0] for item in found))
        sheet, rows, mapping = found[0]
        rules = []
        skipped_empty_rows = 0
        for r, cells in enumerate(rows[2:], 3):
            relevant = [cells[mapping[key]] for key in required]
            if not any(text(cell.value) for cell in relevant):
                continue
            after_columns = [c for (group, label), c in mapping.items() if group == "修改后"]
            if not any(text(cells[c].value) for c in after_columns):
                skipped_empty_rows += 1  # 原产品目录中未配置替换内容的行，不是启用规则。
                continue
            if any(cell.data_type == "f" or cell.data_type == "e" for cell in relevant):
                raise ValueError(f"规则表第{r}行含公式或错误值，请填写固定内容")
            store = text(cells[mapping[("修改前", "店铺名称")]].value)
            region = {"美": "US", "欧": "EU", "英": "GB", "加": "CA"}.get(store[:1])
            if not region:
                raise ValueError(f"规则表第{r}行店铺前缀不明：{store}；请使用美/欧/英/加")
            before = tuple(text(cells[mapping[("修改前", field)]].value) for field in FIELDS)
            after = tuple(text(cells[mapping[("修改后", field)]].value) for field in FIELDS)
            if not before[0]:
                raise ValueError(f"规则表第{r}行缺少原产品中文品名")
            missing = [field for field, value in zip(FIELDS, after) if not value]
            if missing:
                raise ValueError(f"规则表第{r}行修改后缺少：{'、'.join(missing)}；四项必须完整，材质使用英文材质")
            if not after[3].isascii() or not after[3].isdigit():
                raise ValueError(f"规则表第{r}行海关编码应为数字文本，不能含小数点或科学计数法")
            if any(len(v) > 3000 or any(ord(ch) < 32 and ch not in '\t\n\r' for ch in v) for v in after):
                raise ValueError(f"规则表第{r}行内容过长或含不可写入的控制字符")
            rules.append(Rule(r, region, before, after))
        if not rules:
            raise ValueError(f"规则表中没有可用规则；{skipped_empty_rows}行修改后全空，尚未启用")
        return RuleSet(path, hashlib.sha256(raw).hexdigest(), sheet, tuple(rules), skipped_empty_rows)
    finally:
        wb.close()


def match_rules(name: str, rules: RuleSet, region: str, threshold: float) -> tuple[Candidate, ...]:
    if region not in REGIONS or not math.isfinite(threshold) or not 1 <= threshold <= 100:
        raise ValueError("请选择有效区域，相似度应在1%至100%之间")
    source = normalized(name)
    if not source:
        return ()
    relevant = [r for r in rules.rules if r.region == region]
    exact = [r for r in relevant if normalized(r.before[0]) == source]
    candidates = [Candidate(r, 100.0) for r in exact] if exact else [
        Candidate(r, SequenceMatcher(None, source, normalized(r.before[0]), autojunk=False).ratio() * 100)
        for r in relevant
    ]
    unique = {}
    for candidate in sorted(candidates, key=lambda c: (-c.score, c.rule.row)):
        if candidate.score >= threshold:
            unique.setdefault(candidate.rule.after, candidate)
    return tuple(unique.values())
