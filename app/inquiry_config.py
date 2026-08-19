from pathlib import Path


SYSTEM_ROOT = Path(
    r"I:\OneDrive\OneDrive - Lion"
    r"\【采购仓储】"
    r"\【发货单】"
    r"\【发票合并】"
    r"\发票系统"
)


INQUIRY_SOURCE_ROOT = (
    SYSTEM_ROOT / "询价路径"
)

INQUIRY_RESULT_ROOT = (
    SYSTEM_ROOT / "询价结果"
)

INQUIRY_TEMPLATE_PATH = (
    SYSTEM_ROOT
    / "模板"
    / "询价表模板.xlsx"
)


# ==========================================
# 询价模板写入位置
#
# 后续如果你的真实模板位置不同，
# 只改这里，不改业务代码。
# ==========================================

INQUIRY_TEMPLATE_SHEET = "询价单"

INQUIRY_START_ROW = 2

INQUIRY_WAREHOUSE_COLUMN = "A"
INQUIRY_WEIGHT_COLUMN = "B"
INQUIRY_CARTON_COLUMN = "C"


# WarehouseCode 默认规则
WAREHOUSE_PATTERN = r"^[A-Z0-9]{3,10}$"