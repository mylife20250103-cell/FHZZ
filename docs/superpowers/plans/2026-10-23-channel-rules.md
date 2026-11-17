# 合并发票渠道规则 Implementation Plan

> **For agentic workers:** 在当前会话使用 superpowers:executing-plans 按任务实施；本次不派实现子代理，不执行 Git 写操作。

**Goal:** 在批量修改页按人工渠道规则为不同仓库生成服务建议，确认后保留原件另存整批。

**Architecture:** 独立 channel_rules 包负责官方服务目录、人工规则、模板读取和发布。页面用 TaskWorker 调用，旧手工修改服务保持原状。

**Tech Stack:** Python 3.11、PySide6、openpyxl、xlrd、olefile、现有局部 XML/BIFF 补丁。

**Spec:** docs/superpowers/specs/2026-10-23-channel-rules-design.md

## Global Constraints

只改相关模块；不安装依赖、不提交、不打包；保留现有未提交工作。真实模板和业务批次只读，所有验证输出在 D 盘 temp。
用户已批准实施，沿用当前 dev 工作目录以使用未提交的报关基础能力，不新建会遗漏这些能力的工作树。

## Review Focus

- 单账号超时、空目录及失效服务，不得用旧数据假装同步成功。
- 同仓库不同税费/派送规则及同名服务跨账号，冲突需人工确认。
- 改名文件、模板变更、公式目标与混国不得绕过识别。
- 预览后源文件、规则或目录变化必须阻止发布。
- 中途写入失败及同名文件不得影响源件；改动必须保留模板图片与其他内容。

## Task 1：目录与规则

Files: 新增 app/channel_rules/{models,catalog,rules}.py，tests/test_channel_rules.py。
Interfaces: Service、ChannelRule、Catalog；fetch_services(config)、refresh_catalog(configs, previous)、read_rules(path)、match_rules(rules, head, category, tax, delivery)。
- [x] 写并运行缺失功能测试，覆盖失败保留、空响应、重复代码冲突、六条件精确匹配及规则缺项。
- [x] 实现目录请求、版本缓存和规则 Excel 读取/模板/汇总导出。
- [x] 运行该组测试并核对结果。

## Task 2：模板与整批发布

Files: 新增 app/channel_rules/{invoices,service}.py，tests/test_channel_revision.py。
Interfaces: InvoiceHead、ChannelScan、ChannelEdit；scan_batch(root, rules_path, catalog, carrier, cell)、apply_revision(scan, edits, output_root, catalog_path)。
- [x] 写并运行测试：按内容识别、国家核对、逐仓建议、源件变化、中途失败、仅服务格变化。
- [x] 实现只读扫描、目标格检查、哈希锁定、副本写入、审计和原子目录发布。
- [x] 使用真实 MC/KYD/HP 模板的 D 盘副本验证，原件 SHA256 不变。

## Task 3：页面与最小接线

Files: 新增 app/pages/channel_batch_panel.py；修改 app/pages/batch_edit_page.py、app/main_window.py；新增 tests/test_channel_ui.py。
- [x] 测试条件变化使预览失效、每行条件/候选调整、批次路径通知及忙时关闭保护。
- [x] 实现目录同步、规则创建/选择、服务汇总导出、扫描预览、逐行修改和确认另存。
- [x] 原手工页保留，连接合并成功路径及窗口关闭保护。

## Task 4：回归与交接

- [x] 更新本功能用户说明和维护交接；不修改其他模块。
- [x] 完整 pytest、diff 检查及无关模块差异核对（全量存在独立复现的旧测试失败，详见下文；未声称全绿）。
- [x] 独立审查安全边界，处理必要问题后报告实际结果与未验收项目。

## 执行记录

- 公开目录文档已核实；网络访问在受限环境失败，授权的只读访问成功。
- Pre-flight: Task1 的 Catalog/ChannelRule 供 Task2 和 Task3 使用；Task2 的 ChannelScan 锁定数据及可编辑行供 Task3 使用；发布重新验证同一版本。
- Ruling: 新增独立副本发布模式，不改共享旧手工服务的回滚逻辑，避免影响敏感词模块；旧手工模式仍为原行为。
- Task 1: complete — 13项首批测试由缺失模块失败转为通过；目录按账号保留，不保存原始响应或Token；正式客户端禁止重定向携带身份头。
- Task 2: complete — 真实MC批次13份、KYD批次19份、HP官方模板填测试明细1份，分别只选一份写入目录中存在的服务，全部输出在D盘独立目录；源清单/哈希未变，未选字节一致，已选回读成功。这是结构测试映射，不是已批准业务规则或真实上传验收。
- Task 3: complete — 新规则模式与手工模式并存；选择物流商填可编辑B1/B2/B4，自动识别后显示实际格；逐行条件与服务可调整；修改前后及状态优先展示；主窗口只追加成功合并通知及退出保护。
- Task 4: complete — 新功能46项通过；含旧手工与报关界面的相关组62项通过。最终全量命令使用独立D盘basetemp及正常Excel COM权限，315 passed / 1 failed / 2 warnings，27.50秒，退出码1。
- 旧失败：tests/test_customs_service.py::test_uploaded_kyd_batch_can_publish_complete_revision_to_test_directory，第116行断言历史样本必须命中真实用户规则。当前表268条启用（US41），历史19份115行产品0命中；规则文件哈希已不同于前次交接，KYD单票样本哈希仍与前次一致。独立只运行该测试时 app.channel_rules 与 app.pages.channel_* 导入列表为空，仍在同一断言失败。本次未改用户规则、报关代码或该测试，不通过跳过或吞异常制造全绿。
- 两个warning为原有openpyxl只读提示Data Validation extension；新写入路径保持非目标ZIP内容。git diff --check无错误；app/services及app/shipment_tracking相对HEAD无差异。
- 独立只读审查提出异步批次通知顺序、审计/暂存源路径、国家别名与空国家冲突问题，均先复现测试再修复；复核未发现剩余Critical/Important。正式客户端最后逐货代只读查询成功：KYD312、MC197、HP431、LH105。
- 通过独立Qt页面渲染检查布局，未运行生产MainWindow启动恢复或实际上传。未安装依赖、未提交/推送/打包，既有报关未提交修改保留。
