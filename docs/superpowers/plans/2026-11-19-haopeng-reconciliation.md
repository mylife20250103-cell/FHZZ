# 皓鹏货件数据核对 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans，在当前会话逐项实施；用户已授权执行和发布。

**Goal:** 在独立核对页支持皓鹏原文和官方成品发票，采用21kg整票下限并发布V1.1.24。
**Architecture:** 核对服务内新增HP读取/解析分支；沿用原模型、整票关联、结果和导出。
**Tech Stack:** Python 3.11、PySide6、xlrd、现有pytest/PyInstaller，无新依赖。
**Spec:** docs/superpowers/specs/2026-11-19-haopeng-reconciliation-design.md

## Global Constraints
- 只改app/reconciliation、核对页提示、相关测试与维护/发布文档、版本及spec名称；不修改中央规则/原件/Token。
- HP每边+2cm、除6000、整票取大后向上进位1kg、整票最低21kg；MC/KYD原样。

## Review Focus
- 跨行消息之间及通知边界不得串票；缺重量也要保留身份并阻断重复。
- 票内重复FBA合法；跨票重复仍阻断，MC票内重复仍异常。
- 文件无HP前缀也按真实HP结构识别；误后缀、错误表头、箱数或同箱冲突阻断。
- 辅助匹配不能跨货代、跨文件或使用重量猜测；完整货箱参与21kg边界比较。
- 导出源保护包含HP及非标准名的已扫描文件；原文和整票明细保留。

### Task 1: HP文本与计费
Files: app/reconciliation/parser.py、models.py、service.py；tests/test_reconciliation_hp.py。
Interfaces: parse_reports(text)->ParseResult；InvoiceEstimate.approved_weight；reconcile(scan,parsed)。
- [x] 先写两段原文、通知/换行、无效重量/重复身份、票内与跨票重复、HP21kg和21.01kg边界、跨货代及辅助整票测试，运行确认缺功能失败。
- [x] 最小实现HP解析、HP21kg下限及HP辅助匹配，运行新增和原核对测试。

### Task 2: HP只读文件、提示与导出
Files: app/reconciliation/invoices.py、export.py、app/pages/reconciliation_panel.py；相关测试。
Interfaces: scan_directory(Path)->ScanResult；export_results(...)保持现有签名及列序。
- [x] 先写官方模板副本的G～J列、B14、多箱/同箱重复、异常数据、非标准文件名、原件不变及导出保护测试，运行确认失败。
- [x] 实现真实模板识别和读取，更新局部提示及导出最低重说明，核对回归。

### Task 3: 验证、审阅、提交发布
Files: app/version.py、InvoiceMergeSystem.spec、README及维护/操作/版本/发布文档。
- [x] 完整pytest、原MC17票只读验证、HP样本集及UI验证；一次独立代码审阅，修正阻断问题。
- [ ] 版本1.1.24、全新构建、最终exe启动检查、归档和校验、打包；提交源码并推送dev/v1.1.24。
- [ ] GitHub正式发布及OneDrive新版本目录逐文件校验；补记交付记录提交，旧版本保留。
