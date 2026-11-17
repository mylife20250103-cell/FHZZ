"""固定预览快照，校验完成后发布整批修订；永不回写源目录。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from datetime import datetime
from pathlib import Path

from app.customs.models import CARRIERS, REGIONS, PreviewLine, ScanResult
from app.customs.rules import load_rules, match_rules
from app.customs.workbooks import detect_invoice, read_invoice, write_invoice


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _reject_links(path: Path):
    for part in (path, *path.parents):
        if not part.exists():
            continue
        info = part.lstat()
        # OneDrive占位符也是reparse point，只拒绝symlink和junction，不拒绝云占位符。
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in (0xA000000C, 0xA0000003):
            raise ValueError(f"不支持符号链接或目录联接：{part}")


def inventory(root: Path) -> tuple[tuple[str, str], ...]:
    _reject_links(root)
    if not root.is_dir():
        raise ValueError("发票目录不存在，请重新选择")
    files = []

    def visit(directory):
        for item in sorted(directory.iterdir()):
            _reject_links(item)
            if item.is_dir():
                visit(item)
            elif item.is_file() and item.suffix.lower() in (".xlsx", ".xls"):
                if item.name.startswith(("~$", ".~tmp", ".__")):
                    continue
                files.append((item.relative_to(root).as_posix(), digest(item)))
    visit(root)
    if not files:
        raise ValueError("目录内没有正式.xls/.xlsx发票")
    return tuple(sorted(files))


def verify_snapshot(scan: ScanResult):
    try:
        _reject_links(scan.rules.path)
        if digest(scan.rules.path) != scan.rules.sha256 or inventory(scan.root) != scan.hashes:
            raise ValueError("规则或发票内容/清单已变化，请重新扫描")
    except (OSError, ValueError) as exc:
        raise ValueError("规则或发票已变化/不可访问，请重新扫描") from exc


def scan_batch(root: Path, rules_path: Path, carrier: str, region: str, threshold: float = 95) -> ScanResult:
    if carrier not in (*CARRIERS, 'AUTO') or region not in REGIONS:
        raise ValueError("请选择物流商和规则区域")
    _reject_links(Path(root).absolute())
    _reject_links(Path(rules_path).absolute())
    root = Path(root).resolve()
    rules = load_rules(rules_path)
    # 即便没有产品也要校验阈值；禁止NaN绕过。
    match_rules("", rules, region, threshold)
    if not any(r.region == region for r in rules.rules):
        raise ValueError("规则表中没有所选区域的规则，请核对店铺前缀")
    hashes = inventory(root)
    invoices, rows = [], []
    actual_carrier = None if carrier == 'AUTO' else carrier
    for relative, _hash in hashes:
        invoice = detect_invoice(root / relative) if carrier == 'AUTO' else read_invoice(root / relative, carrier)
        if actual_carrier is not None and invoice.carrier != actual_carrier:
            raise ValueError(f"批次包含不同物流商：{CARRIERS[actual_carrier]}、{CARRIERS[invoice.carrier]}，请分别选择目录")
        actual_carrier = invoice.carrier
        if not invoice.lines:
            raise ValueError(f"{relative}没有产品明细，请勿将空白模板当成已合并发票")
        invoices.append(invoice)
        for line in invoice.lines:
            key = json.dumps([relative, invoice.sheet, line.row], ensure_ascii=False)
            rows.append(PreviewLine(key, relative, invoice.sheet, line,
                                    match_rules(line.values[0], rules, region, threshold)))
    scan = ScanResult(root, rules, actual_carrier, region, threshold, hashes, tuple(invoices), tuple(rows))
    verify_snapshot(scan)
    return scan


def apply_revision(scan: ScanResult, selections: dict[str, int], output_root: Path) -> Path:
    output_root = Path(output_root).absolute()
    _reject_links(output_root)
    output_root = output_root.resolve()
    if output_root.is_relative_to(scan.root) or scan.root.is_relative_to(output_root):
        raise ValueError("输出目录与源发票目录不能相同或互相包含")
    indexed = {row.key: row for row in scan.rows}
    if any(key not in indexed or type(index) is not int or not 0 <= index < len(indexed[key].candidates)
           for key, index in selections.items()):
        raise ValueError("选择不属于本次预览候选，请重新扫描")
    verify_snapshot(scan)
    revision = datetime.now().strftime("%H%M%S") + "_" + uuid.uuid4().hex[:12]
    batch = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", scan.root.name)[:60].rstrip(". ") or "批次"
    parent = output_root / datetime.now().strftime("%Y%m%d") / scan.carrier / ("批次_" + batch)
    _reject_links(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / (".进行中_" + revision)
    final = parent / ("修订_" + revision)
    stage.mkdir(exist_ok=False)
    audit_rows, output_hashes = [], {}
    try:
        uploads = stage / "上传发票"
        uploads.mkdir()
        hashes = dict(scan.hashes)
        for invoice in scan.invoices:
            relative = invoice.path.relative_to(scan.root).as_posix()
            dest = uploads / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            # 从固定哈希的字节复制，再在隔离副本上操作，避免读写期间改变源。
            raw = invoice.path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != hashes[relative]:
                raise ValueError("源文件已变化，请重新扫描")
            changes = {row.line.row: row.candidates[selections[row.key]].rule.after
                       for row in scan.rows if row.relative == relative and row.key in selections}
            if changes:
                snapshot_path = stage / (".原始_" + uuid.uuid4().hex + invoice.path.suffix)
                snapshot_path.write_bytes(raw)
                write_invoice(snapshot_path, dest, invoice, changes)
                # 原始临时副本保留在修改记录内，不混入上传文件。
                originals = stage / "修改记录" / "原始快照" / relative
                originals.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.rename(originals)
            else:
                dest.write_bytes(raw)
            output_hashes[relative] = digest(dest)
        for row in scan.rows:
            candidate = row.candidates[selections[row.key]] if row.key in selections else None
            audit_rows.append({"file": row.relative, "sheet": row.sheet, "row": row.line.row,
                               "before": row.line.values, "after": candidate.rule.after if candidate else row.line.values,
                               "selected": candidate is not None, "rule_row": candidate.rule.row if candidate else None,
                               "score": candidate.score if candidate else None,
                               "candidate_count": len(row.candidates)})
        verify_snapshot(scan)
        record = {"revision": revision, "created_at": datetime.now().astimezone().isoformat(),
                  "source": str(scan.root), "carrier": scan.carrier, "region": scan.region,
                  "threshold": scan.threshold, "rule_path": str(scan.rules.path),
                  "rule_sheet": scan.rules.sheet, "rule_sha256": scan.rules.sha256,
                  "source_sha256": dict(scan.hashes), "output_sha256": output_hashes,
                  "selected_rows": len(selections), "unchanged_rows": len(scan.rows) - len(selections),
                  "rows": audit_rows}
        reports = stage / "修改记录"
        reports.mkdir(exist_ok=True)
        (reports / "修改记录.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        # 最后一道检查在发布之前；同一文件系统 rename 不覆盖既有修订。
        verify_snapshot(scan)
        stage.rename(final)
        return final
    except Exception as exc:
        # 保留失败副本便于排查；不会回写、删除源文件或发布成修订目录。
        try:
            (stage / "未完成说明.txt").write_text("此目录未发布，不能上传。\n" + str(exc), encoding="utf-8")
        except OSError:
            pass
        raise
