from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from app.excel_com import (
    XL_SHEET_VERY_HIDDEN,
    close_workbook,
    excel_application,
    open_workbook,
)
from app.services.invoice_adapters.base import (
    AdapterError,
    AdapterTemplateConfig,
    InvoiceMergeAdapter,
    ProductFieldSpec,
)


class McAdapter(InvoiceMergeAdapter):
    """
    迈创适配器。

    已用 20260819 真实未合并发票确认：
    工作表【迈创发票】，表头第17行，明细从第18行起。
    产品图是 R 列 URL，没有 KYD 那种浮动图片。
    第19行起模板预填了公式，空箱号行不能当成明细。
    """

    carrier_code = "MC"
    template_version = "1.0"
    carrier_name = "迈创"

    LAST_DATA_COL = 22
    EMPTY_CARTON_STOP = 8

    def template_config(self) -> AdapterTemplateConfig:

        return AdapterTemplateConfig(
            sheet_name="迈创发票",
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
                "MC 模板只有一列产品材质，"
                "英文/中文材质字段都读取第11列。"
                "产品图片在 R 列链接，不是浮动图。"
            ),
        )

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
        last = min(worksheet.max_row, start_row + 200)

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

    def _delete_sheet(self, workbook, name: str) -> None:

        try:
            sheet = workbook.Worksheets(name)
        except Exception:
            return

        app = workbook.Application
        app.DisplayAlerts = False
        sheet.Visible = -1
        sheet.Delete()
        app.DisplayAlerts = False

    def _write_merge_meta(self, workbook, group: dict) -> None:

        self._delete_sheet(workbook, "_SystemMeta")
        self._delete_sheet(workbook, "_MergeMeta")

        ws = workbook.Worksheets.Add()
        ws.Name = "_MergeMeta"

        fields = [
            ("MetaSchemaVersion", "1.0"),
            ("BatchID", group["batch_id"]),
            ("CarrierCode", group["carrier_code"]),
            ("CarrierName", self.carrier_name),
            ("TemplateVersion", group["template_version"]),
            ("WarehouseCode", group["warehouse_code"]),
            ("DateID", group["date_id"]),
            ("CreatedAt", datetime.now().isoformat(timespec="seconds")),
            ("InputFileCount", group["input_count"]),
            ("CartonCount", len(group["carton_numbers"])),
            ("SourceIDCount", len(group["source_ids"])),
            ("MergePlanHash", group["merge_plan_hash"]),
        ]

        for index, (key, value) in enumerate(fields, start=1):
            ws.Cells(index, 1).NumberFormat = "@"
            ws.Cells(index, 2).NumberFormat = "@"
            ws.Cells(index, 1).Value = str(key)
            ws.Cells(index, 2).Value = str(value)

        ws.Visible = XL_SHEET_VERY_HIDDEN

    def merge_group(self, group: dict, output_path) -> None:

        cfg = self.template_config()
        inputs = [Path(item) for item in group["input_files"]]

        if not inputs:
            raise AdapterError("MC 合并分组没有输入文件")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists():
            output_path.unlink()

        shutil.copy2(inputs[0], output_path)

        with excel_application() as excel:
            dest_book = open_workbook(excel, output_path, read_only=False)

            try:
                try:
                    dest_ws = dest_book.Worksheets(cfg.sheet_name)
                except Exception as exc:
                    raise AdapterError(
                        f"缺少工作表【{cfg.sheet_name}】：{exc}"
                    ) from exc

                first_rows = self._data_rows(dest_ws, cfg.data_start_row)

                if not first_rows:
                    raise AdapterError(
                        f"{inputs[0].name}：没有找到明细行"
                    )

                last_dest_row = first_rows[-1]

                for extra in inputs[1:]:
                    src_book = open_workbook(excel, extra, read_only=False)

                    try:
                        src_ws = src_book.Worksheets(cfg.sheet_name)
                        src_rows = self._data_rows(
                            src_ws,
                            cfg.data_start_row,
                        )

                        if not src_rows:
                            raise AdapterError(
                                f"{extra.name}：没有找到明细行"
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

                dest_ws.Range(cfg.carton_count_cell).Value = len(
                    group["carton_numbers"]
                )

                warehouse = dest_ws.Range(cfg.warehouse_cell).Value
                if str(warehouse).strip() != group["warehouse_code"]:
                    dest_ws.Range(cfg.warehouse_cell).Value = group[
                        "warehouse_code"
                    ]

                self._write_merge_meta(dest_book, group)

                excel.CutCopyMode = False
                dest_book.Save()
                close_workbook(dest_book, save=True)
                dest_book = None

            finally:
                close_workbook(dest_book, save=False)

    def validate_output(self, output_path, group: dict) -> list[str]:

        errors = []
        path = Path(output_path)
        cfg = self.template_config()

        if not path.exists():
            return [f"输出文件不存在：{path}"]

        if path.name.startswith("~$"):
            return [f"输出是临时锁文件：{path.name}"]

        try:
            workbook = load_workbook(path, data_only=False)
        except Exception as exc:
            return [f"{path.name}：无法打开：{exc}"]

        try:
            if cfg.sheet_name not in workbook.sheetnames:
                errors.append(f"{path.name}：缺少【{cfg.sheet_name}】")
                return errors

            if "_SystemMeta" in workbook.sheetnames:
                errors.append(f"{path.name}：不应保留 _SystemMeta")

            if "_MergeMeta" not in workbook.sheetnames:
                errors.append(f"{path.name}：缺少 _MergeMeta")
            else:
                meta_ws = workbook["_MergeMeta"]
                if meta_ws.sheet_state != "veryHidden":
                    errors.append(
                        f"{path.name}：_MergeMeta 必须为 veryHidden"
                    )

                values = {}
                for row in meta_ws.iter_rows(
                    min_col=1,
                    max_col=2,
                    values_only=True,
                ):
                    if row[0] is None:
                        continue
                    values[str(row[0]).strip()] = (
                        "" if row[1] is None else str(row[1]).strip()
                    )

                expected = {
                    "BatchID": group["batch_id"],
                    "CarrierCode": group["carrier_code"],
                    "WarehouseCode": group["warehouse_code"],
                    "MergePlanHash": group["merge_plan_hash"],
                }

                for key, value in expected.items():
                    if values.get(key) != str(value):
                        errors.append(
                            f"{path.name}：_MergeMeta.{key} "
                            f"期望 {value}，实际 {values.get(key)}"
                        )

                carton_count = values.get("CartonCount")
                if carton_count != str(len(group["carton_numbers"])):
                    errors.append(
                        f"{path.name}：CartonCount "
                        f"期望 {len(group['carton_numbers'])}，"
                        f"实际 {carton_count}"
                    )

            ws = workbook[cfg.sheet_name]
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

            if sorted(found_cartons) != sorted(expected_cartons):
                errors.append(
                    f"{path.name}：明细箱号与 MergePlan 不一致"
                )

            warehouse = ws[cfg.warehouse_cell].value
            if str(warehouse).strip() != group["warehouse_code"]:
                errors.append(
                    f"{path.name}：仓库单元格不是 {group['warehouse_code']}"
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

        finally:
            workbook.close()

        return errors
