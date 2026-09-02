from __future__ import annotations

from pathlib import Path

from app.invoice_config import SYSTEM_ROOT

# 【采购仓储】\【装箱明细】 — 发货追踪只读扫描根目录
PACKING_LIST_ROOT = SYSTEM_ROOT.parent.parent.parent / "【装箱明细】"

# 按 FBA 保存运单号（人工或以后 API），不写发票合并库
TRACKING_STORE_PATH = SYSTEM_ROOT / "发货追踪" / "fba_tracking.json"
