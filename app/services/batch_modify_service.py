from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from app.invoice_config import (
    EXCLUDE_DIR_NAMES,
    LOCAL_TEMP_ROOT,
    is_excel_junk_file,
)
from app.services.invoice_scan_service import read_system_meta


BATCH_MODIFY_EXTENSIONS = {".xlsx", ".xls"}
META_SHEET_NAMES = {"_SystemMeta", "_MergeMeta"}
KYD_OUTPUT_SHEET = "模板"
KYD_CHANNEL_CELL = "B4"
MERGE_OUTPUT_NAME = re.compile(
    r"^.+_.+_\d+箱\.(xlsx|xls)$",
    re.IGNORECASE,
)
SOURCE_INVOICE_NAME = re.compile(
    r"发票\.(xlsx)$",
    re.IGNORECASE,
)


def looks_like_merge_output(path: Path) -> bool:
    return bool(MERGE_OUTPUT_NAME.match(path.name))


def looks_like_source_invoice(path: Path) -> bool:
    if looks_like_merge_output(path):
        return False
    name = path.name
    if SOURCE_INVOICE_NAME.search(name):
        return True
    return path.suffix.lower() == ".xlsx" and "箱" not in name


@dataclass
class ModifyPreviewRow:
    path: str
    file_name: str
    carrier_code: str
    sheet_name: str
    cell: str
    current_value: str
    new_value: str
    selected: bool = True
    status: str = "待处理"
    error: str = ""


@dataclass
class ModifyResult:
    passed: bool
    success_count: int
    fail_count: int
    rows: list[ModifyPreviewRow]
    errors: list[str] = field(default_factory=list)


def is_kyd_xls(path: Path) -> bool:
    return path.suffix.lower() == ".xls"


def normalize_cell_address(address: str) -> str:
    """
    把用户输入收成 Excel 地址，例如：
    B2、b2、B4单元格、单元格B4 → B4
    """

    text = (address or "").strip().upper()
    text = (
        text.replace("单元格", "")
        .replace("CELL", "")
        .replace("$", "")
        .replace("：", "")
        .replace(":", "")
        .strip()
    )

    letters = ""
    digits = ""

    for char in text:
        if "A" <= char <= "Z":
            if digits:
                break
            letters += char
        elif char.isdigit():
            if not letters:
                continue
            digits += char

    if not letters or not digits:
        return ""

    return f"{letters}{digits}"


def parse_cell(address: str) -> tuple[str, int]:

    text = normalize_cell_address(address)

    if not text:
        raise ValueError(f"无效单元格：{address}")

    letters = "".join(
        char for char in text if "A" <= char <= "Z"
    )
    digits = "".join(
        char for char in text if char.isdigit()
    )

    if not letters or not digits:
        raise ValueError(f"无效单元格：{address}")

    return letters, int(digits)


def _collect_modify_files(
    paths: list[Path],
    recursive: bool = True,
) -> list[Path]:

    files: list[Path] = []
    seen: set[Path] = set()

    def add_file(path: Path) -> None:
        if is_excel_junk_file(path):
            return
        if path.suffix.lower() not in BATCH_MODIFY_EXTENSIONS:
            return
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        files.append(path)

    for path in paths:
        if path.is_file():
            add_file(path)
            continue
        if not path.is_dir():
            continue
        iterator = path.rglob("*") if recursive else path.glob("*")
        for item in iterator:
            if not item.is_file():
                continue
            if recursive:
                relative_parts = set(item.relative_to(path).parts[:-1])
                if relative_parts & EXCLUDE_DIR_NAMES:
                    continue
            add_file(item)

    merge_files = [item for item in files if looks_like_merge_output(item)]
    if merge_files:
        files = merge_files

    return sorted(files, key=lambda item: str(item).lower())


def preview_files(
    paths: list[Path],
    new_value: str,
    manual_cell: str = "",
    recursive: bool = True,
) -> list[ModifyPreviewRow]:

    files = _collect_modify_files(paths, recursive=recursive)
    rows = []

    for path in files:
        carrier = ""
        cell = normalize_cell_address(manual_cell)
        sheet_name = ""
        current = ""
        error = ""
        names: list[str] = []

        if is_kyd_xls(path):
            try:
                names = load_sheet_names(path)
            except Exception as exc:
                error = str(exc)
            if KYD_OUTPUT_SHEET in names:
                carrier = "KYD"
                sheet_name = KYD_OUTPUT_SHEET
                cell = cell or KYD_CHANNEL_CELL
            elif names:
                sheet_name = names[0]
        else:
            meta, meta_error = read_system_meta(path)
            if meta:
                carrier = meta.get("CarrierCode", "")
                cell = (
                    normalize_cell_address(meta.get("ChannelCell", ""))
                    or cell
                )
            elif meta_error and "缺少 _SystemMeta" not in meta_error:
                error = meta_error

            try:
                names = load_sheet_names(path)
            except Exception as exc:
                error = error or str(exc)

            sheet_name = next(
                (name for name in names if name not in META_SHEET_NAMES),
                names[0] if names else "",
            )

        if cell and sheet_name and not error:
            try:
                current = read_cell_value(path, sheet_name, cell)
            except Exception as exc:
                error = str(exc)

        rows.append(
            ModifyPreviewRow(
                path=str(path),
                file_name=path.name,
                carrier_code=carrier,
                sheet_name=sheet_name,
                cell=cell,
                current_value=current,
                new_value=new_value,
                selected=True,
                status="待处理" if not error else "预检失败",
                error=error,
            )
        )

    return rows


def load_sheet_names(path: Path) -> list[str]:

    if is_kyd_xls(path):
        import xlrd

        workbook = xlrd.open_workbook(str(path), on_demand=True)
        try:
            return list(workbook.sheet_names())
        finally:
            workbook.release_resources()

    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def read_cell_value(path: Path, sheet_name: str, cell: str) -> str:

    if is_kyd_xls(path):
        import xlrd

        letters, excel_row = parse_cell(cell)
        col = column_index_from_string(letters) - 1
        workbook = xlrd.open_workbook(str(path), on_demand=True)
        try:
            names = workbook.sheet_names()
            if sheet_name not in names:
                raise ValueError(f"找不到工作表：{sheet_name}")
            value = workbook.sheet_by_name(sheet_name).cell_value(
                excel_row - 1,
                col,
            )
            return "" if value is None else str(value)
        finally:
            workbook.release_resources()

    workbook = load_workbook(path, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"找不到工作表：{sheet_name}")
        value = workbook[sheet_name][cell].value
        return "" if value is None else str(value)
    finally:
        workbook.close()


def precheck_rows(rows: list[ModifyPreviewRow]) -> list[str]:

    errors = []

    for row in rows:
        if not row.selected:
            continue

        path = Path(row.path)

        if not path.exists():
            errors.append(f"{row.file_name}：文件不存在")
            continue

        lock_file = path.parent / f"~${path.name}"
        if lock_file.exists():
            errors.append(f"{row.file_name}：文件可能已被 Excel 打开")

        if not row.cell:
            errors.append(f"{row.file_name}：未指定目标单元格")
            continue

        try:
            parse_cell(row.cell)
        except Exception as exc:
            errors.append(f"{row.file_name}：{exc}")
            continue

        if not row.sheet_name:
            errors.append(f"{row.file_name}：未找到目标工作表")

    return errors


def _backup_file(backup_root: Path, path: Path) -> Path:
    backup = backup_root / path.name
    shutil.copy2(path, backup)
    return backup


def _verify_written(row: ModifyPreviewRow) -> None:
    actual = read_cell_value(Path(row.path), row.sheet_name, row.cell)
    if actual != str(row.new_value):
        raise ValueError(
            f"{row.file_name} 回读校验失败："
            f"期望 {row.new_value}，实际 {actual}"
        )
    row.status = "成功"
    row.current_value = actual


def _modify_kyd_xls(row: ModifyPreviewRow, backup_root: Path) -> Path:
    from app.services.kyd_xls_io import set_kyd_text_cell

    path = Path(row.path)
    backup = _backup_file(backup_root, path)
    letters, excel_row = parse_cell(row.cell)
    col = column_index_from_string(letters) - 1
    set_kyd_text_cell(
        path,
        row.sheet_name or KYD_OUTPUT_SHEET,
        excel_row - 1,
        col,
        row.new_value,
    )
    _verify_written(row)
    return backup


def _modify_xlsx_with_excel(excel, row: ModifyPreviewRow, backup_root: Path) -> Path:
    from app.excel_com import close_workbook, open_workbook

    path = Path(row.path)
    backup = _backup_file(backup_root, path)
    workbook = open_workbook(excel, path, read_only=False)
    try:
        ws = workbook.Worksheets(row.sheet_name)
        ws.Range(row.cell).Value = row.new_value
        workbook.Save()
    finally:
        close_workbook(workbook, save=True)
    _verify_written(row)
    return backup


def apply_modifications(rows: list[ModifyPreviewRow]) -> ModifyResult:

    selected = [row for row in rows if row.selected]
    errors = precheck_rows(selected)

    if errors:
        return ModifyResult(
            passed=False,
            success_count=0,
            fail_count=len(selected),
            rows=rows,
            errors=errors,
        )

    backup_root = LOCAL_TEMP_ROOT / "batch_modify_backup"
    if backup_root.exists():
        shutil.rmtree(backup_root, ignore_errors=True)
    backup_root.mkdir(parents=True, exist_ok=True)

    changed: list[tuple[ModifyPreviewRow, Path]] = []

    try:
        xls_rows = [row for row in selected if is_kyd_xls(Path(row.path))]
        xlsx_rows = [row for row in selected if not is_kyd_xls(Path(row.path))]

        for row in xls_rows:
            backup = _modify_kyd_xls(row, backup_root)
            changed.append((row, backup))

        if xlsx_rows:
            from app.excel_com import excel_application

            with excel_application() as excel:
                for row in xlsx_rows:
                    backup = _modify_xlsx_with_excel(excel, row, backup_root)
                    changed.append((row, backup))

        shutil.rmtree(backup_root, ignore_errors=True)

        return ModifyResult(
            passed=True,
            success_count=len(selected),
            fail_count=0,
            rows=rows,
            errors=[],
        )

    except Exception as exc:
        for row, backup in reversed(changed):
            try:
                shutil.copy2(backup, row.path)
                row.status = "已回滚"
            except Exception:
                row.status = "回滚失败"

        for row in selected:
            if row.status == "待处理":
                row.status = "失败"
                row.error = str(exc)

        return ModifyResult(
            passed=False,
            success_count=0,
            fail_count=len(selected),
            rows=rows,
            errors=[str(exc)],
        )
