# 项目维护入口

本文件适用于整个仓库。沟通、维护记录和业务解释优先使用中文。

## 先读

- `README.md`：用途、启动、测试与 Git 入口。
- `docs/项目理解与维护交接.md`：当前实现和接手基线；业务变化时同步更新。
- `docs/发票合并系统应用说明书.md`、`docs/V1.1发版说明.md`：操作方式和已修复问题。
- `docs/shipment_tracking/current_system_map.md` 是早期调查，不可直接作为当前实现依据。

## 实现与业务约束

- Windows + Python + PySide6 桌面程序；入口 `main.py`，页面在 `app/pages/`，业务服务在 `app/services/`。
- 中央业务路径主要在 `app/invoice_config.py`、`app/inquiry_config.py`；追踪路径在 `app/shipment_tracking/paths.py`。
- 发票扫描依据 veryHidden 的 `_SystemMeta`；箱身份为 `(SourceID, CartonNumber)`，复制与二次扫描检查 SHA256。不要用文件名代替身份校验。
- 发票批次按七阶段执行，分组键为货代、模板版本、仓库；跨天扫描的输出 DateID 仍是当天。国家由元数据仓库对应中央地址库决定，批次按日期、货代、国家隔离；禁止混国合并。
- KYD 输出必须保留官方 `.xls` 的二进制结构和浮动图，使用 `kyd_xls_io.py`；不得改成 Excel 另存或通用工作簿重建。
- MC 输出 `.xlsx`，保留模板 B2 渠道；本机缓存注入中央地址库，Excel COM 计算公式。官方模板原件不应被改写。
- 仓库地址维护中央 `各物流地址库.xlsx`，不靠修改官方模板原件维护地址。
- 当前发货追踪页面走装箱明细 → FBA/SKU 汇总 → JSON 物流覆盖层；SQLAlchemy 模型与服务尚未接入主界面。
- SKU 数量只在同一 FBA 内按箱累计。确认货代来自有效发票批次快照；文件名仅作为候选。
- 查询物流保留人工登记的 Tracking；`forwarder_api.ini` 的 Token 不进入代码、日志、文档或安装包。
- 耗时操作使用 `TaskWorker`；UI 通过 Signal 更新，Excel COM 工作线程设置 `use_com=True`。

## 开发与验证

- 优先使用 `.venv/Scripts/python.exe`，现有本机环境为 Python 3.11.4。
- 启动：`& .\.venv\Scripts\python.exe main.py`；测试：`& .\.venv\Scripts\python.exe -m pytest -q`。
- 部分测试依赖 I 盘真实模板或文件，且缺文件时直接 return；测试通过数不能替代真实上传验收。
- 2026-10-20 基线为 190 passed / 1 failed；失败在 Excel COM 激活，HRESULT `0x80070005`。不要通过禁用校验或吞异常来“修复”环境失败。
- 在样本副本或重定向的测试目录复现问题。启动程序可恢复并写入批次状态；真实扫描也可能清理临时文件或初始化配置。
- `complete_batch()` 会删除同一天同货代同国家其他已完成批次的输出文件，并清理当前快速合并目录；其他范围及国家无法确定的旧结果不自动删除，排查或试运行前先理解该行为。
- 根据改动运行相关回归，报告实际结果及未验证项；合并、追踪或模板规则变化时同步维护文档。

## Git 与发布

- 开工先检查 `git status`、当前分支和已有修改，保留用户工作；接手代码基线为 `dev@24ea17f`。
- 新建维护分支时默认使用 `codex/` 前缀，不把当前本地 `main` 当作最新业务代码。
- 本次任务是否提交、推送或发布，按用户任务范围执行；不要改写已有历史或丢弃无关修改。
- `dist/`、`release/`、`build/`、`.venv/`、`temp/`、`logs/` 被忽略；业务文件位于仓库之外的 OneDrive。
- 发版同步检查 `app/version.py`、`InvoiceMergeSystem.spec` 的程序名和用户文档；打包不能替代桌面与货代导入验证。
