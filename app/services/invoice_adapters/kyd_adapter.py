from __future__ import annotations

import zipfile
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from app.excel_com import (
    MSO_PICTURE,
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


class KydAdapter(InvoiceMergeAdapter):

    carrier_code = "KYD"
    template_version = "1.0"
    carrier_name = "快越达"

    LAST_DATA_COL = 20

    def template_config(self) -> AdapterTemplateConfig:

        return AdapterTemplateConfig(
            sheet_name="快越达发票",
            header_row=29,
            data_start_row=30,
            channel_cell="B4",
            warehouse_cell="B5",
            carton_count_cell="B26",
            product_fields=[
                ProductFieldSpec(
                    "ProductEN",
                    "产品英文品名",
                    3,
                    "产品英文品名*",
                ),
                ProductFieldSpec(
                    "ProductCN",
                    "产品中文品名",
                    4,
                    "产品中文品名*",
                ),
                ProductFieldSpec(
                    "MaterialEN",
                    "产品材质",
                    13,
                    "产品材质*",
                ),
                ProductFieldSpec(
                    "MaterialCN",
                    "产品材质",
                    13,
                    "产品材质*",
                ),
            ],
            notes=(
                "KYD 模板只有一列产品材质，"
                "英文/中文材质字段都读取第13列。"
            ),
        )

    def validate_source(self, workbook_path, meta: dict) -> list[str]:

        errors = []
        path = Path(workbook_path)
        cfg = self.template_config()

        if meta.get("CarrierCode", "").upper() != self.carrier_code:
            errors.append(f"{path.name}：CarrierCode 不是 KYD")

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
            return [f"{path.name}：无法打开：{exc}"]

        try:
            if cfg.sheet_name not in workbook.sheetnames:
                errors.append(
                    f"{path.name}：缺少工作表【{cfg.sheet_name}】"
                )
        finally:
            workbook.close()

        return errors

    def _data_rows(self, worksheet, start_row: int) -> list[int]:

        used = worksheet.UsedRange
        last_row = int(used.Row + used.Rows.Count - 1)
        rows = []

        for row in range(start_row, last_row + 1):
            carton = worksheet.Cells(row, 1).Value
            product_en = worksheet.Cells(row, 3).Value
            if carton not in (None, "") or product_en not in (None, ""):
                rows.append(row)

        return rows

    def _extract_media(self, xlsx_path: Path, work_dir: Path) -> list[Path]:

        work_dir.mkdir(parents=True, exist_ok=True)
        files = []

        with zipfile.ZipFile(xlsx_path) as archive:
            media_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("xl/media/")
            )

            for index, name in enumerate(media_names):
                dest = work_dir / f"{xlsx_path.stem}_{index}{Path(name).suffix}"
                dest.write_bytes(archive.read(name))
                files.append(dest)

        return files

    def _add_picture(
        self,
        dst_ws,
        dest_row: int,
        image_path: Path,
        width: float,
        height: float,
    ) -> None:

        if not image_path.exists():
            return

        cell = dst_ws.Cells(dest_row, 19)
        image = str(Path(image_path).resolve())
        dst_ws.Activate()
        picture = dst_ws.Pictures().Insert(image)
        picture.Left = cell.Left
        picture.Top = cell.Top
        if width:
            picture.Width = width
        if height:
            picture.Height = height

    def _source_picture_size(self, src_ws, src_row: int) -> tuple[float, float]:

        for index in range(1, src_ws.Shapes.Count + 1):
            shape = src_ws.Shapes(index)
            if int(shape.Type) != MSO_PICTURE:
                continue
            if int(shape.TopLeftCell.Row) != src_row:
                continue
            return float(shape.Width), float(shape.Height)

        return 48.0, 48.0

    def _copy_data_row(
        self,
        src_ws,
        src_row: int,
        dst_ws,
        dst_row: int,
        image_path: Path | None = None,
    ) -> None:

        src_ws.Range(
            src_ws.Cells(src_row, 1),
            src_ws.Cells(src_row, 18),
        ).Copy()

        dst_ws.Cells(dst_row, 1).PasteSpecial()
        dst_ws.Application.CutCopyMode = False

        src_ws.Range(
            src_ws.Cells(src_row, 20),
            src_ws.Cells(src_row, self.LAST_DATA_COL),
        ).Copy()

        dst_ws.Cells(dst_row, 20).PasteSpecial()
        dst_ws.Application.CutCopyMode = False

        dst_ws.Rows(dst_row).RowHeight = src_ws.Rows(src_row).RowHeight

        self._copy_row_pictures(src_ws, src_row, dst_ws, dst_row)

    def _copy_row_pictures(self, src_ws, src_row: int, dst_ws, dst_row: int) -> None:

        XL_MOVE_AND_SIZE = 1

        for index in range(1, src_ws.Shapes.Count + 1):
            shape = src_ws.Shapes(index)

            if int(shape.Type) != MSO_PICTURE:
                continue

            if int(shape.TopLeftCell.Row) != src_row:
                continue

            width = float(shape.Width)
            height = float(shape.Height)
            shape.Placement = XL_MOVE_AND_SIZE
            shape.Copy()
            dst_ws.Activate()
            dst_ws.Paste()
            dst_ws.Application.CutCopyMode = False

            pasted = dst_ws.Shapes(dst_ws.Shapes.Count)
            anchor = dst_ws.Cells(dst_row, 19)
            pasted.Top = anchor.Top
            pasted.Left = anchor.Left
            pasted.Width = width
            pasted.Height = height
            pasted.Placement = XL_MOVE_AND_SIZE

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
            raise AdapterError("KYD 合并分组没有输入文件")

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
                    media_files = self._extract_media(
                        extra,
                        output_path.parent / "media_tmp",
                    )

                    if not media_files:
                        raise AdapterError(
                            f"{extra.name}：源文件没有可跟随明细的图片"
                        )

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

                        for row_index, src_row in enumerate(src_rows):
                            dest_row = last_dest_row + 1
                            carton = dest_ws.Cells(dest_row, 1).Value
                            product = dest_ws.Cells(dest_row, 3).Value

                            if carton not in (None, "") or product not in (None, ""):
                                dest_ws.Rows(dest_row).Insert()

                            image_path = None
                            if row_index < len(media_files):
                                image_path = media_files[row_index]

                            self._copy_data_row(
                                src_ws,
                                src_row,
                                dest_ws,
                                dest_row,
                                image_path=image_path,
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
            data_rows = 0
            for row in range(cfg.data_start_row, ws.max_row + 1):
                carton = ws.cell(row, 1).value
                product = ws.cell(row, 3).value
                if carton not in (None, "") or product not in (None, ""):
                    data_rows += 1

            if data_rows < group["input_count"]:
                errors.append(
                    f"{path.name}：明细行 {data_rows}，"
                    f"少于箱数 {group['input_count']}"
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

            with zipfile.ZipFile(path) as archive:
                picture_count = 0
                for name in archive.namelist():
                    if not name.startswith("xl/drawings/drawing"):
                        continue
                    if not name.endswith(".xml"):
                        continue
                    xml = archive.read(name).decode(
                        "utf-8",
                        errors="ignore",
                    )
                    picture_count += xml.count("<xdr:pic")

            if picture_count < group["input_count"]:
                errors.append(
                    f"{path.name}：浮动图片 {picture_count} 张，"
                    f"少于箱数 {group['input_count']}"
                )

        finally:
            workbook.close()

        return errors
