# 发票报关修改 Implementation Plan

> 执行方式：当前会话直接实现，按用户授权审核后继续；保留未提交改动，不安装、不提交、不发布。

**Goal:** 三家货代发票按国家规则扫描、人工选择并另存整批修订。
**Architecture:** 新增 app/customs 独立包和页面；原文件只增加导航/图标/成功路径通知。
**Tech Stack:** Python 3.11 / PySide6 / openpyxl只读 / xlrd / olefile / BIFF与ZIP局部写入。
**Spec:** ../specs/2026-10-22-customs-modify-design.md

## Global Constraints

- 输出根“报关修改后目录”，原件不变、原文件名不变、整批保留、日志外置。
- 只有预览选中的四字段可改变，未知模板和不完整规则不得执行。
- 不改变旧发票合并能力，不执行真实业务批次，不修改官方模板。

## Review Focus

- 文件扫描之后新增/改动/删除，确认须失败。
- 同名文件位于不同子目录，不得覆盖。
- RK 数值海关编码和空白/MULBLANK 文本替换，不破坏其他记录。
- 多候选无选择，复制原内容；不能偷偷取最高分。
- 含图片和校验的真实二进制模板副本，保存后结构和非目标内容须一致。

## Tasks

- [x] 1. 规则及匹配。新增 app/customs/models.py、rules.py；测试 tests/test_customs_rules.py 先失败。接口 load_rules(Path)->RuleSet、match_rules(str,RuleSet,region,threshold)->候选列表。覆盖国别、四项缺失、公式、精确优先、去重与冲突。
- [x] 2. 模板读写。新增 app/customs/workbooks.py、xls_patch.py、sst_index.py。先写 tests/test_customs_workbooks.py。接口 read_invoice(Path,carrier)->Invoice、write_invoice(source,dest,invoice,changes)。测试三模板定位、公式拒绝、ZIP其他项和OLE其他流不变及多行四字段回读。
- [x] 3. 批次服务。新增 app/customs/service.py。先写 tests/test_customs_service.py。接口 scan_batch(root,rules_path,carrier,region,threshold)->ScanResult、apply_revision(scan,selections,output_root)->Path。覆盖清单/哈希变更、完整复制、失败不发布及路径包含/联接拒绝。
- [x] 4. 页面与接线。新增 app/pages/customs_page.py（含本机偏好）；原主窗口增加导航与通知连接，发票页成功分支增加 Signal。先写 tests/test_customs_ui.py；确认控件变化失效、后台忙碌禁用、候选和选择联动。同步维护文档。
- [x] 5. 回归及审阅。运行新增用例和完整 pytest；临时副本核对真实模板；请求打开本机未提交差异供用户查看。记录未验证的真实货代上传。

## Execution ledger

Ruling: 在当前 dev 工作区实现且不提交 — 用户希望直接查看修改，工作区原先干净，.git只读 — 代价是新增功能与当前工作区共存，全部保留为可审阅差异。
Ruling: 按本轮“审核后可写代码”持续执行，先落盘已确认需求和防错细节，不再重复业务确认 — 用户已有多轮逐项确认并明确授权下一步 — 若后续出现必须改变业务范围的问题再询问。

2026-10-22 实施：规则9项、工作簿14项、服务8项、界面10项，共41个新增测试。每阶段先观察缺失功能或边界红灯再实施；专项最终通过。完整回归在沙箱内初次244 passed/1 failed（既有Excel COM 0x80070005）；同一MC用例在沙箱外通过。最终完整回归输出258 passed/2 warnings，32.68秒；警告来自openpyxl只读扫描的既有校验扩展提示，新XML写入保留该扩展。

独立审查提出EXTSST跨桶未更新及XLS错误值检查问题，已修复并补充红灯/绿灯用例。SST按微软结构完整定位并重建EXTSST，官方HP 8669及KYD 2972条位置经独立交叉解码一致。另验证原字段为空、XML缺失cell、数值RK编码、源元数据误选、CompObj另存、非法本机偏好、主导航及成功路径传递。

已在1050×760内容区域用本机中文字体渲染页面，最小尺寸719×630。旧代码语法树变化只在MainWindow.build_ui、InvoicePage._on_content_merge_finished及新增MainWindow.closeEvent，图标函数未变；业务服务无修改。尚无真实后台上传、安装包、生产批次执行或Git提交/发布。

规则表兼容修复（2026-10-22）：按用户实际布局新增英文材质/HS CODE别名，采用用户确认的英文材质；修改后全空按未启用处理并显示计数，部分填写仍拦截，别名冲突拒绝。5个复现用例先失败后通过，完整回归263 passed/2 warnings，36.27秒，退出码0。用户原表只读加载147条，跳过3704行；只读扫描其MC批次13份/85行，命中5行，无候选冲突，原表/发票未写入。已打开修复后窗口并观察到同一预览结果，未点击确认修改。

快越达实票验证（2026-10-22）：截图为手选迈创后扫描KYD.xls触发格式拒绝。已用用户实际上传样本验证专用BIFF读写、所有非目标值/样式、浮动图记录及其他OLE流不变。新增AUTO模式，基于魔数/工作表/表头识别，切换批次路径清除上批货代、混合目录拦截、预览固定实际货代及明确提示手选错误。7个新增用例及真实19份/115行/20处命中批次在临时目录完整发布回读通过；真实原件不变。完整回归270 passed/2 warnings，41.85秒，退出码0。未发布业务输出或安装包，修改后的真实货代导入仍待验收。
