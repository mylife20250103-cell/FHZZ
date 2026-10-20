"""国家由仓库地址决定，目录和店铺名称不作为事实来源。"""

from app.invoice_config import INVOICE_COUNTRIES
from app.services.address_library import load_warehouse_countries, normalize_country_code


class InvoiceCountryError(ValueError):
    pass


class WarehouseCountries:
    """每次操作按货代加载一次，不跨批次缓存中央地址库。"""

    def __init__(self):
        self._indexes: dict[str, dict[str, str]] = {}

    def country(self, carrier: str, warehouse: str) -> str:
        carrier = carrier.strip().upper()
        warehouse = warehouse.strip().upper()
        if carrier not in self._indexes:
            try:
                self._indexes[carrier] = load_warehouse_countries(carrier)
            except Exception as exc:
                raise InvoiceCountryError(str(exc)) from exc
        country = self._indexes[carrier].get(warehouse, "")
        if country not in INVOICE_COUNTRIES:
            raise InvoiceCountryError(
                f"{carrier} 仓库 {warehouse} 的国家缺失、冲突或不受支持，请检查中央地址库"
            )
        return country


def invoice_scope(records, *, carrier_code="", country_code="", verify_addresses=False,
                  countries: WarehouseCountries | None = None) -> tuple[str, str]:
    """校验单一货代、单一国家。旧快照缺国家时按中央地址库解析。"""
    countries = countries or WarehouseCountries()
    scopes = set()
    for record in records:
        item = record if isinstance(record, dict) else vars(record)
        carrier = str(item.get("carrier_code") or "").strip().upper()
        warehouse = str(item.get("warehouse_code") or "").strip().upper()
        country = normalize_country_code(item.get("country_code", ""))
        if verify_addresses or not country:
            actual = countries.country(carrier, warehouse)
            if country and country != actual:
                raise InvoiceCountryError(f"仓库 {warehouse} 的国家已变化，请重新原始扫描")
            country = actual
        if country not in INVOICE_COUNTRIES:
            raise InvoiceCountryError(f"仓库 {warehouse} 的国家不受支持：{country}")
        if country_code and country != country_code:
            raise InvoiceCountryError(
                f"仓库 {warehouse} 属于{INVOICE_COUNTRIES[country]}，"
                f"与所选国家 {country_code} 不一致，禁止混合合并"
            )
        if carrier_code and carrier != carrier_code:
            raise InvoiceCountryError(f"仓库 {warehouse} 的物流商 {carrier} 与所选物流商 {carrier_code} 不一致")
        scopes.add((carrier, country))
    if not scopes:
        raise InvoiceCountryError("没有可处理的发票")
    if len({scope[1] for scope in scopes}) != 1:
        raise InvoiceCountryError("批次包含不同国家的发票，禁止混合合并，请按国家重新扫描")
    if len(scopes) != 1:
        raise InvoiceCountryError("批次包含不同物流商的发票，请分别扫描")
    return next(iter(scopes))


def validate_plan_scope(snapshot: dict, plan: dict) -> tuple[str, str]:
    carrier, country = invoice_scope(
        snapshot.get("Files", []), carrier_code=snapshot.get("CarrierCode", ""),
        country_code=snapshot.get("CountryCode", ""),
    )
    if plan.get("CountryCode") != country or plan.get("CarrierCode", carrier) != carrier:
        raise InvoiceCountryError("MergePlan 国家/物流商缺失或与批次不一致，请重新原始扫描")
    invoice_scope(plan.get("Groups", []), carrier_code=carrier, country_code=country)
    snapshots = {(item["source_id"], item["carton_number"]): item
                 for item in snapshot.get("Files", [])}
    planned_keys = []
    for group in plan.get("Groups", []):
        if group.get("country_code") != country:
            raise InvoiceCountryError("MergePlan 分组国家缺失或不一致，请重新原始扫描")
        for key in group.get("machine_keys", []):
            key = tuple(key)
            item = snapshots.get(key)
            if item is None or (item["carrier_code"], item["warehouse_code"]) != (
                group["carrier_code"], group["warehouse_code"],
            ):
                raise InvoiceCountryError("MergePlan 箱身份/物流商/仓库与批次不一致")
            planned_keys.append(key)
    if len(planned_keys) != len(snapshots) or set(planned_keys) != set(snapshots):
        raise InvoiceCountryError("MergePlan 箱身份不完整或重复，请重新准备合并")
    return carrier, country
