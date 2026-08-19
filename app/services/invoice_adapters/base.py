from __future__ import annotations

from dataclasses import dataclass, field


class AdapterError(Exception):
    pass


@dataclass
class ProductFieldSpec:
    field_code: str
    field_name: str
    column: int
    header: str


@dataclass
class AdapterTemplateConfig:
    sheet_name: str
    header_row: int
    data_start_row: int
    channel_cell: str
    warehouse_cell: str
    carton_count_cell: str
    product_fields: list[ProductFieldSpec] = field(default_factory=list)
    notes: str = ""


class InvoiceMergeAdapter:
    """
    Carrier + TemplateVersion 适配器统一接口。
    """

    carrier_code: str = ""
    template_version: str = "1.0"
    carrier_name: str = ""

    def adapter_id(self) -> str:

        return f"{self.carrier_code}:{self.template_version}"

    def template_config(self) -> AdapterTemplateConfig:

        raise NotImplementedError

    def validate_source(self, workbook_path, meta: dict) -> list[str]:

        raise NotImplementedError

    def build_plan(self, group: dict) -> dict:

        return group

    def merge_group(self, group: dict, output_path) -> None:

        raise NotImplementedError

    def validate_output(self, output_path, group: dict) -> list[str]:

        raise NotImplementedError

    def product_field_specs(self) -> list[ProductFieldSpec]:

        return self.template_config().product_fields
