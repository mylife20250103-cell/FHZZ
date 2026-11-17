# Shipment Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在发票中心加入可用的货件重量核对、异常筛选和留档导出。

**Architecture:** 新建独立reconciliation包负责模型、只读发票读取、文字解析、匹配与导出。独立Qt面板通过现有content_merge_succeeded信号接收目录，仅在发票页和窗口关闭逻辑加接线。

**Tech Stack:** Python 3.11 / Decimal / openpyxl / xlrd / PySide6 / pytest。

**Spec:** `docs/superpowers/specs/2026-11-17-shipment-reconciliation-design.md`

## Global Constraints

- 原件不改，顶部七阶段不改；体积重系数6000，单边公差2cm，整票向上进位1kg。
- 保留现有未提交工作；在当前dev目录增量修改，不切换到缺少现有功能的干净检出，不擅自提交/打包/发布。
- 仅完整集合且身份唯一、源数据有效时才能判重量通过；异常不可静默丢弃。

## Review Focus

- 同箱多SKU及相同箱号尺寸矛盾：不得重复统计或错误通过。
- 部分FBA、跨消息重叠和重复源集合：不得错误匹配。
- 目录或文字在异步任务前后变化：旧结果不能出现在新目录下。
- 导出原文/渠道以等号开头及选择源文件作输出：不得执行公式或覆盖原件。
- 今日默认路径及历史目录部分损坏：异常可见，其余文件仍可核对。

### Task 1: 解析、读取与整票计算

**Files:** `app/reconciliation/models.py`, `invoices.py`, `parser.py`; `tests/test_reconciliation_inputs.py`。
**Interfaces:** `scan_directory(Path)->ScanResult`; `parse_reports(str)->ParseResult`; `InvoiceEstimate`包含唯一箱、源哈希、问题和Decimal总量/上限。
- [x] 先写并运行失败测试：17条消息、中文符号、通知、非法/重复数据；MC/KYD表头、去重、冲突、41/54kg样例。
- [x] 最小实现；相关测试通过。

### Task 2: 匹配与导出

**Files:** `app/reconciliation/service.py`, `export.py`; `tests/test_reconciliation_service.py`。
**Interfaces:** `reconcile(ScanResult, ParseResult)->list[ReconciliationRow]`; `export_results(rows,Path,*,raw_text,source_directory)->Path`。
- [x] 先写并运行失败测试：完整集合匹配、41/42边界、部分集合不匹配、重复/渠道问题及当前过滤导出。
- [x] 实现结果与只读快照导出，阻止覆盖源文件，原文作为文本，验证后原子替换。
- [x] 核对真实样例及导出工作簿内容。

### Task 3: Qt面板与集成

**Files:** `app/pages/reconciliation_panel.py`; 修改`invoice_page.py`和`main_window.py`；`tests/test_reconciliation_ui.py`。
**Interfaces:** `ReconciliationPanel.receive_merge(dict)`, `can_close()`, `visible_rows()`；发票页保存`reconciliation_panel`并接收成功信号。
- [x] 先写并运行失败测试：文本/路径变化作废、筛选、接收目录、忙碌新批次与关闭。
- [x] 实现异步读取/核对/导出、消息区与明细，保留原界面行为。
- [x] 运行新增与现有UI回归，记录完整测试结果；更新说明书和交接记录。
- [x] 新鲜上下文审阅本次增量，修正重要问题并重跑相关回归。

完成记录：新增42项全部通过，联合UI回归62项通过；完整回归356通过、2项基线失败（Excel COM权限、旧报关历史规则数据），无新增失败。未提交、打包或发布。
