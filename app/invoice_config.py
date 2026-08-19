from pathlib import Path


SYSTEM_ROOT = Path(
    r"I:\OneDrive\OneDrive - Lion"
    r"\【采购仓储】"
    r"\【发货单】"
    r"\【发票合并】"
    r"\发票系统"
)


# VBA 询价明细
INQUIRY_SOURCE_ROOT = (
    SYSTEM_ROOT / "询价路径"
)


# Batch 轻量记录
BATCH_ROOT = (
    SYSTEM_ROOT / "批次记录"
)


# 后续正式由配置中心管理
INVOICE_SOURCES_INI = (
    SYSTEM_ROOT
    / "公共配置"
    / "invoice_sources.ini"
)


CURRENT_CONFIG_INI = (
    SYSTEM_ROOT
    / "公共配置"
    / "current_config.ini"
)


QUICK_MERGE_ROOT = (
    SYSTEM_ROOT / "全部发票汇总"
)


MERGE_RESULT_ROOT = (
    SYSTEM_ROOT / "合并结果"
)


LOCAL_ROOT = Path(r"D:\InvoiceMergeSystem")

LOG_ROOT = LOCAL_ROOT / "logs"

LOCAL_TEMP_ROOT = LOCAL_ROOT / "temp"


ALLOWED_EXTENSIONS = {
    ".xlsx",
}


EXCLUDE_DIR_NAMES = {
    "备份",
    "已合并",
    "历史归档",
    "临时",
}