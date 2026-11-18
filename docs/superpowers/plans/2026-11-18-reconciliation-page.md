# 独立核对页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 独立侧栏核对页面，列间实线，醒目且不会残留的重测标记。

**Architecture:** 新页面包装现有Panel，由MainWindow接收合并通知和保护关闭；表格样式仅本地生效。

**Tech Stack:** Python / PySide6 / pytest，复用现有QSS及SVG图标。

**Spec:** `docs/superpowers/specs/2026-11-18-reconciliation-page-design.md`。

## Global Constraints

原七阶段及核对/导出逻辑保留；一份核对状态；异步切批次与关闭保护保留；原发票只读；保留已有工作，不自行发版。

## Review Focus

- 发票合并完成时新页面隐藏，也必须读取正确目录且不能重复订阅。
- 切页保留输入/结果，核对任务忙时主窗口仍不可关闭。
- 重测标签在选中行仍醒目，更新为允许重量后不残留。
- 最小1250×760及常用窗口下可滚动访问控件，分隔线不影响其他表格。
- 原17票仍11完整+6辅助、2需重测，导出保留全部50箱。

## Task 1：迁移及展示

Files：新增 `app/pages/reconciliation_page.py`；修改 `main_window.py`、`invoice_page.py`、`reconciliation_panel.py`、`ui_icons.py`；验证 `tests/test_reconciliation_ui.py` 和 `tests/test_customs_ui.py`。

- [x] 先更新旧嵌入式入口测试，新增真实新页面的合并通知、切换保留、全局关闭保护及重测标记清除测试，观察失败。
- [x] 实现单例新页面、局部网格和重测标签，相关回归通过。
- [x] 隔离配置离屏构建真实主窗口，检查常用与最小尺寸、选中行及真实17票；独立审阅。
- [x] 运行完整回归，更新说明与交接，记录真实验证结果及未打包范围。

## 执行记录

- 首次入口/关闭保护/标签及旧导航约束检查4 failed，17 passed；实现后21项UI回归通过。
- 真实窗口预览发现标签后原文字重影，增加局部delegate保留item数据而不重复绘制；选中行预览复核通过。另验证鼠标命中红标后双击仍打开全部3箱明细，更新为允许重量后不残留标签。
- 17票/6辅助/2重测及50箱导出回读通过，源SHA256不变；1600×1000及1250×760真实主窗口离屏检查通过。
- 独立只读审阅未发现生产阻断问题。最终完整回归376 passed / 1 failed / 2 warnings（47.18秒）；唯一失败为原有历史KYD规则样本断言，未跳过。
- 当前仅源码与维护文档更新，未改版本、提交、打包或发布。

后续用户已授权提交、打包发版，进入V1.1.23发布流程；实际状态见 `docs/releases/V1.1.23.md`。
