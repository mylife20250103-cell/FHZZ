from __future__ import annotations

import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import ReconciliationRow
from .invoices import NAME

HEADERS = ['货代单号','所含FBA','仓库','货代','发票渠道','货代渠道','箱数',
           '实重合计(kg)','原体积重合计(kg)','公差体积重合计(kg)','仓库预估(kg)',
           '核准上限(kg)','货代计费重(kg)','超限差额(kg)','核对结果','说明','源文件',
           '关联方式','报数未列FBA']


def row_values(row: ReconciliationRow) -> list:
    inv, reply = row.invoice, row.report
    return [reply.order_number if reply else '', '\n'.join(inv.fba_ids if inv else reply.fba_ids),
            inv.warehouse if inv else '', inv.carrier if inv else reply.carrier,
            inv.channel if inv else '', reply.channel if reply else '', len(inv.cartons) if inv else None,
            inv.total_real if inv and inv.cartons else None,
            inv.original_volume if inv and inv.cartons else None,
            inv.tolerance_volume if inv and inv.cartons else None,
            inv.estimated_weight if inv else None, inv.approved_weight if inv else None,
            reply.billed_weight if reply else None, row.difference, row.status, row.message,
            str(inv.path) if inv else '', row.match_method, '\n'.join(row.unlisted_fbas)]


def _write(sheet, row: int, values):
    for col, value in enumerate(values, 1):
        if isinstance(value, Decimal):
            value = float(value)
        cell = sheet.cell(row, col, value)
        if isinstance(value, str):
            # 货代原文/渠道为外部输入，保存文本，不执行以等号开头的内容。
            cell.data_type = 's'


def _style(sheet, header_row: int, widths):
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = f'C{header_row+1}'
    for row in sheet.iter_rows():
        for cell in row:
            cell.font = Font(name='Microsoft YaHei', size=10)
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            if isinstance(cell.value, (int, float)):
                cell.number_format = '0.000'
    for cell in sheet[header_row]:
        cell.fill = PatternFill('solid', fgColor='244C73')
        cell.font = Font(name='Microsoft YaHei', size=10, bold=True, color='FFFFFF')
    for col, width in enumerate(widths, 1):
        sheet.column_dimensions[sheet.cell(1,col).column_letter].width = width
    sheet.row_dimensions[header_row].height = 32
    if sheet.max_row > header_row:
        sheet.auto_filter.ref = f'A{header_row}:{sheet.cell(sheet.max_row,sheet.max_column).coordinate}'


def export_results(rows: list[ReconciliationRow], destination: Path, *, raw_text: str,
                   source_directory: Path, scanned_at: str = '', protected_paths=()) -> Path:
    requested = Path(destination).resolve()
    destination = requested.with_suffix('.xlsx')
    protected = {Path(p).resolve() for p in protected_paths}
    protected.update(r.invoice.path.resolve() for r in rows if r.invoice)
    if requested in protected or destination in protected or NAME.fullmatch(destination.name):
        raise ValueError('核对结果不得覆盖源发票，请另选文件名')
    w = Workbook(); summary = w.active; summary.title = '货件核对'
    boxes = w.create_sheet('货箱明细'); raw = w.create_sheet('货代原文')
    _write(summary,1,['货件数据核对'])
    _write(summary,2,['体积重系数',6000,'单边尺寸公差(cm)',2,'整票向上进位(kg)',1])
    _write(summary,3,['数据目录',str(source_directory)])
    _write(summary,4,['扫描时间',scanned_at,'导出时间',datetime.now().isoformat(timespec='seconds')])
    _write(summary,5,['超限差额＝货代计费重－核准上限；皓鹏整票最低21kg，其他货代原规则不变；'
                      '完整集合优先，迈创/皓鹏允许唯一部分FBA辅助关联；'
                      '始终按发票全部货箱核算。仅总重量不能定位具体边长超差。'])
    _write(summary,6,HEADERS)
    for r, row in enumerate(rows,7):
        _write(summary,r,row_values(row))
        if row.needs_remeasure or row.status not in {'重量在允许范围','待货代报数'}:
            for cell in summary[r]: cell.fill = PatternFill('solid',fgColor='FFF1CE')
    _write(boxes,1,['源文件','完整箱号','FBA','实际重量(kg)','长(cm)','宽(cm)','高(cm)',
                    '原体积重(kg)','公差体积重(kg)','源行号','源SHA256'])
    seen = set(); r = 2
    for row in rows:
        inv = row.invoice
        if inv is None or inv.path in seen:
            continue
        seen.add(inv.path)
        for carton in inv.cartons:
            _write(boxes,r,[str(inv.path),carton.number,carton.fba_id,carton.weight,
                            carton.length,carton.width,carton.height,carton.volume,
                            carton.tolerance_volume,carton.source_row,inv.sha256])
            r += 1
    _write(raw,1,['原文行号','完整粘贴原文（含未匹配、异常和通知行）'])
    for r, line in enumerate(raw_text.splitlines(),2):
        _write(raw,r,[r-1,line])
    _style(summary,6,[20,28,12,10,26,26,9,15,18,20,16,16,18,17,20,55,60,24,28])
    _style(boxes,1,[60,26,23,18,12,12,12,18,20,10,70])
    _style(raw,1,[12,120])
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.__reconcile_',suffix='.xlsx',dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        w.save(temporary)
        os.replace(temporary,destination)
    finally:
        w.close()
        temporary.unlink(missing_ok=True)
    return destination
