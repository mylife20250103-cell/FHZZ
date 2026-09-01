from __future__ import annotations

from pathlib import Path

from app.invoice_config import SYSTEM_ROOT

# 【采购仓储】\【装箱明细】 — 发货追踪只读扫描根目录
PACKING_LIST_ROOT = SYSTEM_ROOT.parent.parent.parent / "【装箱明细】"
