from pathlib import Path
import sys


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


INVOICE_MANUAL_SCAN_ROOT = (
    SYSTEM_ROOT.parent / "物流商发票"
)


QUICK_MERGE_ROOT = (
    SYSTEM_ROOT / "全部发票汇总"
)


MERGE_RESULT_ROOT = (
    SYSTEM_ROOT / "合并结果"
)


KYD_TEMPLATE_PATH = (
    SYSTEM_ROOT
    / "模板"
    / "快越达发票模版.xls"
)


MC_TEMPLATE_PATH = (
    SYSTEM_ROOT
    / "模板"
    / "迈创发票模板.xlsx"
)


CENTRAL_ADDRESS_PATH = (
    SYSTEM_ROOT.parent.parent
    / "发货单各源抓取"
    / "各物流地址库.xlsx"
)


def _local_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(r"D:\InvoiceMergeSystem")


LOCAL_ROOT = _local_root()

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


def is_excel_junk_file(path: Path) -> bool:
    """
    Excel / OneDrive 保存时会留下锁文件和临时副本，
    不能当成正式询价单或发票。
    """

    name = path.name
    if name.startswith("~$"):
        return True
    if name.startswith(".~tmp"):
        return True
    if name.startswith(".__"):
        return True
    return False


def try_remove_excel_junk(path: Path) -> bool:

    if not is_excel_junk_file(path):
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False