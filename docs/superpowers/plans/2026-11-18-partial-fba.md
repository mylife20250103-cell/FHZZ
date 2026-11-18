# 部分 FBA 辅助关联 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 原批次17票全部能唯一关联，6票部分关联，整票核算后SWF2与ONT8各超1kg。

**Architecture:** 完整索引优先，迈创报数以非空子集唯一命中同货代文件作为辅助关联。沿用既有冲突及异常防线；结果增加可导出的关联方式与未列FBA，UI显示同一份结果。

**Tech Stack:** Python 3.11 / PySide6 / Decimal / openpyxl / pytest。

**Spec:** `docs/superpowers/specs/2026-11-18-partial-fba-design.md`。

## Global Constraints

用户确认计费重量覆盖整票；原发票只读；公差每边2cm、除数6000、整票向上进位1kg。保持TaskWorker与源文件导出保护。保存已有未提交工作，不自行发版。

## Review Focus

- 只要一个报数FBA不在候选中，不能靠其余交集匹配。
- 多候选、旧新文件FBA交叠、同文件多条报数必须阻断比较。
- 部分关联也必须阻断重复单号/FBA和无效报数、无效源数据。
- 重测判定使用整票所有箱，UI筛选及导出不能漏掉未列FBA货箱。
- 原批次的17文件/50箱/17报数复现，前后SHA256一致。

## Task 1: 关联、留档及展示

修改 `app/reconciliation/service.py`、`models.py`、`export.py`、`app/pages/reconciliation_panel.py`；回归位于 `tests/test_reconciliation_service.py`、`tests/test_reconciliation_ui.py`。

- [x] 先更新原禁止子集匹配的业务决策测试，新增唯一子集整票取大/进位、未列FBA留档、真假子集、多候选、同文件多报数、异常及跨货代边界测试，观察预期失败。
- [x] 实现辅助关联、元数据、UI与导出，运行相关回归通过；旧安全测试不删除。
- [x] 对本批17份原文件只读复现，断言17行、6部分关联、2需重测（各+1kg），导出到本机临时目录并回读50箱和原文；核对源SHA256。
- [x] 正常Windows权限执行完整测试，报告既有失败；新鲜上下文审阅差异并处理实际发现。
- [x] 同步操作说明、维护交接及本次排查记录；记录结果，保留未提交源码供用户后续提交/发版。

## 执行记录

- 已观察旧逻辑无法唯一子集关联、元数据/导出列缺失及UI双行展示的失败，然后实现对应行为。旧“部分匹配禁止”用例按新业务口径更新，冲突和异常安全用例保留。
- 相关回归最终57 passed（2.96秒）。完整回归373 passed / 1 failed / 2 warnings（35.34秒），失败为原有 `test_uploaded_kyd_batch_can_publish_complete_revision_to_test_directory` 历史KYD样本对现行规则无唯一命中；未跳过或改规则。
- 原17文件全部关联，11完整+6辅助，50箱保留，未列FBA共13；SWF2 50对49kg、ONT8 76对75kg，各超1kg。源文件SHA256未变，导出回读50箱和全部原文。
- 离屏检查重测筛选2行、关联方式、未列FBA与整票上限；独立只读审阅未发现生产阻断问题，并补核23项内存边界。README、操作说明与交接记录已更新。
- 默认范围决定：本次用户要求改关联行为，未请求新一轮提交/发版，因此保留维护分支上的未提交源码与文档，不改变版本号或已发布安装包。

后续用户已授权Git提交、打包和发版，转入V1.1.22发布流程；最终验证与交付见 `docs/releases/V1.1.22.md`。
