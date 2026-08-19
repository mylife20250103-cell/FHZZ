from __future__ import annotations

from app.services.invoice_adapters.base import (
    AdapterError,
    InvoiceMergeAdapter,
)
from app.services.invoice_adapters.kyd_adapter import KydAdapter
from app.services.invoice_adapters.mc_adapter import McAdapter


_ADAPTERS: dict[tuple[str, str], type[InvoiceMergeAdapter]] = {
    ("KYD", "1.0"): KydAdapter,
    ("MC", "1.0"): McAdapter,
}


def adapter_id(carrier_code: str, template_version: str) -> str:

    return f"{carrier_code.upper()}:{template_version}"


def get_adapter(
    carrier_code: str,
    template_version: str,
) -> InvoiceMergeAdapter:

    key = (
        carrier_code.strip().upper(),
        str(template_version).strip(),
    )

    adapter_cls = _ADAPTERS.get(key)

    if adapter_cls is None:
        raise AdapterError(
            "没有匹配的发票适配器："
            f"{key[0]} + {key[1]}"
        )

    return adapter_cls()


def list_adapter_ids() -> list[str]:

    return [
        adapter_id(carrier, version)
        for carrier, version in sorted(_ADAPTERS)
    ]
