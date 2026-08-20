from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from openpyxl import load_workbook

from app.excel_com import (
    close_workbook,
    excel_application,
    open_workbook,
)
from app.invoice_config import MC_TEMPLATE_PATH
from app.services.invoice_adapters.base import (
    AdapterError,
    AdapterTemplateConfig,
    InvoiceMergeAdapter,
    ProductFieldSpec,
)


class McAdapter(InvoiceMergeAdapter):
    """
    迈创适配器。

    源发票工作表【迈创发票】，表头第17行，明细从第18行起。
    产品图是 R 列 URL，不转浮动图。
    内容合并复制中央【迈创发票模板.xlsx】，只填复制件的【模板】表，
    保留地址 VLOOKUP 和模板自带渠道。
    """

    carrier_code = "MC"
    template_version = "1.0"
    carrier_name = "迈创"

    SOURCE_SHEET = "迈创发票"
    OUTPUT_SHEET = "模板"
    LAST_DATA_COL = 22
    EMPTY_CARTON_STOP = 8
    FLAG_CELLS = ("F1", "F2", "F3", "F4", "F5", "F6", "F8")

    def template_config(self) -> AdapterTemplateConfig:

        return AdapterTemplateConfig(
            sheet_name=self.SOURCE_SHEET,
            header_row=17,
            data_start_row=18,
            channel_cell="B2",
            warehouse_cell="B3",
            carton_count_cell="B16",
            product_fields=[
                ProductFieldSpec(
                    "ProductEN",
                    "产品英文品名",
                    7,
                    "产品英文品名*",
                ),
                ProductFieldSpec(
                    "ProductCN",
                    "产品中文品名",
                    8,
                    "产品中文品名*",
                ),
                ProductFieldSpec(
                    "MaterialEN",
                    "产品材质",
                    11,
                    "产品材质*",
                ),
                ProductFieldSpec(
                    "MaterialCN",
                    "产品材质",
                    11,
                    "产品材质*",
                ),
            ],
            notes=(
                "MC 从中央【迈创发票模板.xlsx】复制后填写【模板】表。"
                "B2 渠道用模板自带名称，不覆盖源发票旧服务名。"
                "产品图片在 R 列链接，不是浮动图。"
            ),
        )

    def output_extension(self) -> str:

        return ".xlsx"

    def validate_source(self, workbook_path, meta: dict) -> list[str]:

        errors = []
        path = Path(workbook_path)
        cfg = self.template_config()

        if meta.get("CarrierCode", "").upper() != self.carrier_code:
            errors.append(f"{path.name}：CarrierCode 不是 MC")

        if meta.get("TemplateVersion") != self.template_version:
            errors.append(
                f"{path.name}：TemplateVersion 不是 {self.template_version}"
            )

        try:
            workbook = load_workbook(
                path,
                read_only=True,
                data_only=False,
            )
        except Exception as exc:
            errors.append(f"{path.name}：无法打开：{exc}")
            return errors

        try:
            if cfg.sheet_name not in workbook.sheetnames:
                errors.append(
                    f"{path.name}：缺少工作表【{cfg.sheet_name}】"
                )
        finally:
            workbook.close()

        return errors

    def _is_data_carton(self, value) -> bool:

        return value not in (None, "")

    def _data_rows(self, worksheet, start_row: int) -> list[int]:

        rows = []
        empty_run = 0
        max_row = start_row + 200

        for row in range(start_row, max_row):
            carton = worksheet.Cells(row, 1).Value

            if self._is_data_carton(carton):
                rows.append(row)
                empty_run = 0
            else:
                empty_run += 1
                if empty_run >= self.EMPTY_CARTON_STOP:
                    break

        return rows

    def _count_data_rows_openpyxl(self, worksheet, start_row: int) -> list[str]:

        cartons = []
        empty_run = 0
        last = min(worksheet.max_row or start_row, start_row + 200)

        for row in range(start_row, last + 1):
            carton = worksheet.cell(row, 1).value

            if self._is_data_carton(carton):
                cartons.append(str(carton).strip())
                empty_run = 0
            else:
                empty_run += 1
                if empty_run >= self.EMPTY_CARTON_STOP:
                    break

        return cartons

    def _copy_official_template(self, dest: Path) -> None:

        if not MC_TEMPLATE_PATH.exists():
            raise AdapterError(f"迈创发票模板不存在：{MC_TEMPLATE_PATH}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            try:
                os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            dest.unlink()

        shutil.copy2(MC_TEMPLATE_PATH, dest)
        try:
            os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass

    def _copy_data_row(
        self,
        src_ws,
        src_row: int,
        dst_ws,
        dst_row: int,
    ) -> None:

        src_ws.Range(
            src_ws.Cells(src_row, 1),
            src_ws.Cells(src_row, self.LAST_DATA_COL),
        ).Copy()

        dst_ws.Cells(dst_row, 1).PasteSpecial()
        dst_ws.Application.CutCopyMode = False
        dst_ws.Rows(dst_row).RowHeight = src_ws.Rows(src_row).RowHeight

    def merge_group(self, group: dict, output_path) -> None:

        cfg = self.template_config()
        inputs = [Path(item) for item in group["input_files"]]

        if not inputs:
            raise AdapterError("MC 合并分组没有输入文件")

        output_path = Path(output_path)
        if output_path.suffix.lower() != ".xlsx":
            output_path = output_path.with_suffix(".xlsx")

        template_mtime = MC_TEMPLATE_PATH.stat().st_mtime
        self._copy_official_template(output_path)

        with excel_application() as excel:
            dest_book = open_workbook(excel, output_path, read_only=False)

            try:
                try:
                    dest_ws = dest_book.Worksheets(self.OUTPUT_SHEET)
                except Exception as exc:
                    raise AdapterError(
                        f"迈创发票模板缺少工作表【{self.OUTPUT_SHEET}】：{exc}"
                    ) from exc

                last_dest_row = cfg.data_start_row - 1

                for index, source in enumerate(inputs):
                    src_book = open_workbook(excel, source, read_only=True)

                    try:
                        try:
                            src_ws = src_book.Worksheets(self.SOURCE_SHEET)
                        except Exception as exc:
                            raise AdapterError(
                                f"{source.name}：缺少工作表【{self.SOURCE_SHEET}】：{exc}"
                            ) from exc

                        if index == 0:
                            for coord in self.FLAG_CELLS:
                                value = src_ws.Range(coord).Value
                                if value not in (None, ""):
                                    dest_ws.Range(coord).Value = value

                        src_rows = self._data_rows(src_ws, cfg.data_start_row)
                        if not src_rows:
                            raise AdapterError(
                                f"{source.name}：没有找到明细行"
                            )

                        for src_row in src_rows:
                            dest_row = last_dest_row + 1
                            carton = dest_ws.Cells(dest_row, 1).Value
                            if self._is_data_carton(carton):
                                dest_ws.Rows(dest_row).Insert()
                            self._copy_data_row(
                                src_ws,
                                src_row,
                                dest_ws,
                                dest_row,
                            )
                            last_dest_row = dest_row

                    finally:
                        close_workbook(src_book, save=False)

                dest_ws.Range(cfg.warehouse_cell).Value = str(
                    group["warehouse_code"]
                ).strip()
                dest_ws.Range(cfg.carton_count_cell).Value = len(
                    group["carton_numbers"]
                )

                excel.CutCopyMode = False
                excel.Calculate()
                dest_book.Save()
                close_workbook(dest_book, save=True)
                dest_book = None

            finally:
                close_workbook(dest_book, save=False)

        if MC_TEMPLATE_PATH.stat().st_mtime != template_mtime:
            raise AdapterError("官方迈创发票模板被改到了，请检查")

    def validate_output(self, output_path, group: dict) -> list[str]:

        errors = []
        path = Path(output_path)
        cfg = self.template_config()
        warehouse = str(group["warehouse_code"]).strip()

        if not path.exists():
            return [f"输出文件不存在：{path}"]
        if path.suffix.lower() != ".xlsx":
            return [f"{path.name}：MC 输出必须是 .xlsx"]
        if path.name.startswith("~$"):
            return [f"输出是临时锁文件：{path.name}"]

        try:
            workbook = load_workbook(path, data_only=False)
        except Exception as exc:
            return [f"{path.name}：无法打开：{exc}"]

        try:
            names = workbook.sheetnames
            for required in (self.OUTPUT_SHEET, "渠道列表", "地址库"):
                if required not in names:
                    errors.append(f"{path.name}：缺少工作表【{required}】")
            if errors:
                return errors

            if "_SystemMeta" in names:
                errors.append(f"{path.name}：不应保留 _SystemMeta")
            if "_MergeMeta" in names:
                errors.append(f"{path.name}：不应写入 _MergeMeta")

            ws = workbook[self.OUTPUT_SHEET]
            channel = ws[cfg.channel_cell].value
            if channel in (None, ""):
                errors.append(f"{path.name}：B2 渠道不能为空")

            b4 = ws["B4"].value
            if not (isinstance(b4, str) and b4.startswith("=")):
                errors.append(f"{path.name}：B4 必须保留公式")

            actual_wh = "" if ws[cfg.warehouse_cell].value is None else str(
                ws[cfg.warehouse_cell].value
            ).strip()
            if actual_wh.upper() != warehouse.upper():
                errors.append(
                    f"{path.name}：仓库单元格不是 {warehouse}"
                )

            carton_cell = ws[cfg.carton_count_cell].value
            try:
                carton_value = int(float(carton_cell))
            except (TypeError, ValueError):
                carton_value = None
            if carton_value != len(group["carton_numbers"]):
                errors.append(
                    f"{path.name}：{cfg.carton_count_cell} "
                    f"应为 {len(group['carton_numbers'])}"
                )

            found_cartons = self._count_data_rows_openpyxl(
                ws,
                cfg.data_start_row,
            )
            expected_cartons = [
                str(item).strip()
                for item in group["carton_numbers"]
            ]
            if len(found_cartons) != len(expected_cartons):
                errors.append(
                    f"{path.name}：明细行 {len(found_cartons)}，"
                    f"应为 {len(expected_cartons)} 箱"
                )
            elif sorted(found_cartons) != sorted(expected_cartons):
                errors.append(
                    f"{path.name}：明细箱号与 MergePlan 不一致"
                )

            for offset, carton in enumerate(found_cartons):
                url = ws.cell(cfg.data_start_row + offset, 18).value
                if url in (None, ""):
                    errors.append(
                        f"{path.name}：{carton} 的 R 列图片链接为空"
                    )

        finally:
            workbook.close()

        return errors
