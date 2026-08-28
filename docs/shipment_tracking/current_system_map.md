# 发货追踪中心 — 现有系统接入点地图

Task 0.1 扫描结果。本文件只描述现状与推荐接入点，不包含 Shipment 业务实现。

扫描范围：`D:\InvoiceMergeSystem`（当前产品版本 v1.1.3）。  
扫描日期：2026-08-28。

---

## 0. 结论先行（验收问题）

> 一票发票成功生成以后，从哪个函数可以拿到：店铺 / FBA / SKU / 数量 / 箱数 / 重量 / 货代 / 渠道？

**没有单一函数一次返回全部字段。** 发票成功后，已确认数据分散在三层：

| 字段 | 已确认对象 | 位置 |
|---|---|---|
| 店铺 `store_code` | `InvoiceRecord` / snapshot | `batch.snapshot["Files"][].store_code`，来自源发票 `_SystemMeta.StoreCode` |
| 发货日期 `DateID` | `BatchRecord` / MergePlan | `batch.date_id`，形如 `20260821` |
| FBA `fba_batch` | `InvoiceRecord` | `_SystemMeta.FBABatch`；**按箱**，同一合并文件里可能有多个 FBA |
| 目的仓 `warehouse_code` | MergePlan group | `_SystemMeta.WarehouseCode` |
| 货代 `carrier_code` | MergePlan group / 适配器 | `_SystemMeta.CarrierCode`（`KYD` / `MC`） |
| 箱号列表 | MergePlan group | `group["carton_numbers"]` |
| 箱数 | MergePlan group | `len(group["carton_numbers"])` |
| 渠道 | 源发票 / 合并结果 Excel | KYD：源表 `B4`；MC：模板 `B2`（合并不覆盖）。**不在 JSON 里** |
| SKU / 品名 / 数量 | 源发票明细行 | KYD 工作表「快越达发票」第 30 行起；MC「迈创发票」第 18 行起。**扫描阶段不入库** |
| 重量 | 询价明细有 `WeightKG`；发票 `_SystemMeta` **没有重量** | 发票侧重量在明细单元格，合并时读过但未写入 Batch JSON |
| 负责人 `owner` | `RegisteredSource` | `发票系统\公共配置\invoice_sources.ini` 的 `Owner` |
| 源文件 | snapshot / manifest | `path` / `copied_path` |

推荐读取入口（服务层，非 GUI）：

1. `run_result_check()` 通过后，读 `batch.directory / "merge_plan.json"` + `batch.snapshot`
2. 渠道、SKU、数量、重量：复用适配器已有读法（`KydAdapter._source_rows` / MC 源表明细），**不要再解析发货规划、不要 OCR**

发货规划本身 **不在本仓库解析**。`PlanID` / `FBABatch` / `CartonNumber` 由上游生成，写在源发票 `_SystemMeta` 里，本系统只校验与合并。

---

## 1. 程序启动入口

| 项 | 路径 |
|---|---|
| 开发入口 | `D:\InvoiceMergeSystem\main.py` → `main()` |
| 打包入口 | `InvoiceMergeSystem.spec` → `发票合并系统_V1.1.3.exe` |
| GUI 框架 | PySide6；`QApplication` + `APP_STYLE` |
| 日志 | `app/app_logging.py`；目录 `LOCAL_ROOT/logs`（开发为 `D:\InvoiceMergeSystem\logs`，frozen 为 exe 同级） |
| 后台线程 | `app/workers.py` `TaskWorker(QThread)`；Excel COM 任务 `use_com=True` |

启动链：`main.py` → `setup_logging()` → `MainWindow()` → `go_to("home")`。

---

## 2. GUI 主窗口与页面注册

文件：`app/main_window.py`

模式：左侧 `nav_items` + `QStackedWidget` + `self.pages[route]`。

当前路由：

| route | 页面类 | 文件 |
|---|---|---|
| `home` | `HomePage` | `app/pages/home_page.py` |
| `inquiry` | `InquiryPage` | `app/pages/inquiry_page.py` |
| `invoice` | `InvoicePage` | `app/pages/invoice_page.py` |
| `batch_edit` | `BatchEditPage` | `app/pages/batch_edit_page.py` |
| `sensitive` | `SensitivePage` | `app/pages/sensitive_page.py` |
| `maintain` | `MaintainPage` | `app/pages/maintain_page.py` |

首页卡片 `ModuleCard.clicked` → `navigate_requested` → `MainWindow.go_to`。

发货追踪导航应 **追加** route，不要改现有六个模块的行为。

---

## 3. 询价中心入口

| 项 | 说明 |
|---|---|
| GUI | `InquiryPage` |
| 服务 | `app/services/inquiry_service.py` |
| 配置 | `app/inquiry_config.py` |
| 扫描根 | `发票系统\询价路径\{DateID}` |
| 结果 | `发票系统\询价结果` + 中央 `询价表模板.xlsx` |

询价已确认字段（按仓汇总，不是按 SKU）：`WarehouseCode`、`WeightKG`、箱数，以及明细里的 `StoreCode` / `PlanID` / `SourceID` / `FBABatch` / `CartonNumber`。

询价与发票扫描 **解耦**：`test_scan_does_not_depend_on_inquiry`。Shipment 建档应跟 **发票成功**，不要跟询价汇总绑定。

---

## 4. 发票生成入口（发票中心）

GUI：`InvoicePage`。步骤条在 `app/services/batch_service.py`：

```text
① 原始扫描 FIRST_SCAN_PASSED     invoice_scan_service.scan_original_invoices
② 快速合并 QUICK_MERGED          invoice_fast_merge_service.run_quick_merge
③ 二次扫描 SECOND_SCAN_PASSED    invoice_second_scan_service.run_second_scan
④ MergePlan MERGE_PLAN_READY     merge_plan_service.build_merge_plan
⑤ 内容合并 CONTENT_MERGED        invoice_content_merge_service.run_content_merge
⑥ 结果检查 CHECK_PASSED          invoice_result_check_service.run_result_check
⑦ 完成 COMPLETED                 batch_service.complete_batch
```

准备合并（②③④）由 `invoice_prepare_service.run_prepare_merge` 串起来。  
内容合并走 Excel COM（迈创）或 BIFF（快越达），GUI 用 `TaskWorker(use_com=True)`。

输出：

- KYD：`发票系统\合并结果\{DateID}\{BatchID}\KYD_{仓}_{N}箱.xls`
- MC：`...\MC_{仓}_{N}箱.xlsx`

「发票成功」在业务上有两档：

- **文件已生成**：`run_content_merge` 返回 `passed=True`（`STATUS_CONTENT_MERGED`）
- **文件已校验**：`run_result_check` 返回 `passed=True`（`STATUS_CHECK_PASSED`）← 更适合当「已确认发票」
- **批次锁定**：`complete_batch`（`STATUS_COMPLETED`）；用户可能停在检查通过、尚未点完成

---

## 5. 「发货规划解析」对象 — 本仓库没有独立解析器

没有 `shipping_plan_parser` 一类模块。

上游（发票系统外的抓取/VBA）已经把规划写进每张源发票的隐藏表 `_SystemMeta`（`veryHidden`）。本系统 `read_system_meta()`（`invoice_scan_service.py`）只读这些键：

```text
MetaSchemaVersion, CarrierCode, CarrierName, TemplateVersion,
InvoiceType, ChannelCell, DateID, GeneratedAt,
StoreCode, PlanID, SourceID, WarehouseCode, FBABatch, CartonNumber
```

领域对象：

- `InvoiceRecord`：一箱一张源发票的已确认元数据
- `ScanResult`：一次原始扫描
- `BatchRecord.snapshot["Files"]`：上述记录的 JSON 快照
- `merge_plan.json` `Groups[]`：按 **货代 + 模板版本 + 目的仓** 分组后的合并计划（一票最终发票）

`PlanID` 只作同源校验（同一 SourceID 必须相同），MergePlan **不按 PlanID 分组**。

---

## 6. 货代配置来源

两处，职责不同：

**A. 已启用物流商名单**  
`发票系统\公共配置\current_config.ini`  
节名 `[Carrier.KYD]`、`[Carrier.MC]` …  
`load_known_carriers()` 用来拒绝未知 `CarrierCode`。

**B. 发票合并适配器注册表**  
`app/services/invoice_adapters/__init__.py`

```text
("KYD", "1.0") → KydAdapter
("MC", "1.0")  → McAdapter
```

`get_adapter(carrier_code, template_version)` 是现有「按代码取实现」模式，与计划中的 `ForwarderAdapter` registry 同构，但 **当前适配器只做发票模板合并，不做物流轨迹 API**。

V1 追踪层应新建独立 registry，不要把轨迹 API 写进现有 `KydAdapter` / `McAdapter`。

---

## 7. 渠道配置来源

**没有**独立的渠道 INI/数据库。

渠道名写在发票 Excel 里：

- 快越达：源「快越达发票」`B4`；官方模板「服务」表是渠道目录；合并时写入复制件 `B4`
- 迈创：官方模板 `B2` 渠道名，合并 **不覆盖**，避免线上「找不到服务」

`_SystemMeta.ChannelCell` 只标明渠道单元格位置，扫描不把渠道文本存进 `InvoiceRecord`。

批量改渠道：`BatchEditPage` → `batch_modify_service`，改的是 **合并结果文件**，不是配置中心。

---

## 8. 当前数据库 / 持久化方式

**没有 SQLAlchemy，没有 SQLite/PostgreSQL。**

| 数据 | 形式 | 根目录 |
|---|---|---|
| Batch 状态 / snapshot | JSON | `发票系统\批次记录\{DateID}\{BatchID}\` |
| 快速合并清单 | `quick_merge_manifest.json` | 同上 |
| MergePlan | `merge_plan.json` | 同上 |
| 结果检查 | `result_check.json` | 同上 |
| 询价/发票/地址/模板 | Excel / INI | `发票系统\` 与 `【发货单】\发货单各源抓取\` |
| 应用日志 | `logs\app.log` | 程序本地目录 |

JSON 读写：`app/json_io.py`（原子 replace）。

Shipment V1 引入 SQLite 是 **新持久化**，不要把 Batch JSON 迁进数据库，也不要把 SQLite 放在 OneDrive 业务根上（多机锁文件风险）。建议：`LOCAL_ROOT/data/shipment_tracking.sqlite`（与 logs 一样跟 exe）。

---

## 9. 发票成功后的代码位置

按调用栈（服务层，GUI 只触发）：

```text
InvoicePage.start_content_merge
  → TaskWorker
  → invoice_content_merge_service.run_content_merge
       adapter.merge_group(...)
       adapter.validate_output(...)
       写入 合并结果\...
       save_status(CONTENT_MERGED)
  → InvoicePage._on_content_merge_finished

InvoicePage.start_result_check
  → invoice_result_check_service.run_result_check
       再 validate_output
       可选敏感词警告
       save_status(CHECK_PASSED)
  → InvoicePage._on_result_check_finished

InvoicePage.start_complete_batch
  → batch_service.complete_batch
       save_status(COMPLETED)
```

`run_content_merge` 任一组失败会删掉本批已写出的官方文件并返回失败（发票主事务）。  
Shipment 建档必须 **后置**：发票已成功落盘后再调用；失败只提示、可重试，不回滚发票。

---

## 10. 最适合调用 `CreateShipment()` 的位置

**推荐（V1）：** `run_result_check` 在 `save_status(..., STATUS_CHECK_PASSED)` **之后**，同一服务流程末尾调用新的集成函数（例如未来的 `create_shipments_from_batch(batch)`），而不是写在 `InvoicePage` 里。

理由：

- 输出文件已存在且 `validate_output` 已通过
- 仍可从 `merge_plan.json` + `snapshot` 取已确认元数据
- 不依赖用户是否点「完成 Batch」
- GUI 不直接碰数据库 / Shipment 内部

**不要**放在：

- `run_content_merge` 内部与写文件同一 try：以免建档失败策略和「整批删输出」缠在一起
- `KydAdapter.merge_group` / `McAdapter.merge_group`：会绑定货代实现
- 询价生成成功：还没有最终发票与渠道定稿（迈创渠道以模板为准，且用户可能批量改 B4）

**重试：** `CHECK_PASSED` / `COMPLETED` 后允许再调一次；幂等靠 source fingerprint（Task 3.2）。

**粒度警告（须在 Task 3 / 11 拍板）：**

MergePlan 一组 = **一个最终发票文件** = 一仓 + 一货代 + 多箱，**FBA 可能多个**。  
`ShipmentCreateCommand` 目前是 **单个** `fba_shipment_id`。

建议后续 Task 二选一（本 Task 不实现）：

- A. 一票 Shipment = 一个 MergePlan group（发票文件），`fba_shipment_id` 存主 FBA 或拼接，箱上保留各 FBA
- B. 一票 Shipment = 同一 `(store, date, fba_batch, carrier, warehouse)`（更接近亚马逊货件）

默认更接近业务的是 **B**；默认更接近现有合并产物的是 **A**。接入时必须显式选择，禁止 silently 按文件建档又按 FBA 去重。

---

## 11. 当前程序目录结构（相关部分）

```text
D:\InvoiceMergeSystem\
  main.py
  InvoiceMergeSystem.spec
  app\
    main_window.py
    invoice_config.py          # 中央业务路径
    inquiry_config.py
    json_io.py
    workers.py
    excel_com.py
    pages\                     # 全部 GUI 页
    services\                  # 询价/批次/扫描/合并/敏感词
      invoice_adapters\        # KYD/MC 发票模板适配器（非轨迹 API）
      kyd_xls_io.py            # 快越达 BIFF，禁止 Excel 另存
      address_library.py
    widgets\
  tests\
  docs\
  release\
```

风格：页面在 `app/pages/`，业务在 `app/services/`，适配器用 registry。**没有** `app/database/`、`models/`、`repositories/`。

---

## 12. 推荐新增目录（沿用现有风格，不重构旧模块）

新增独立包，不把轨迹代码塞进现有 KYD/MC 发票适配器：

```text
app/shipment_tracking/
  domain/           # enums, commands, 纯数据
  repositories/
  services/
  forwarders/       # ForwarderAdapter；与 invoice_adapters 分开
  scheduler/

app/database/       # SQLAlchemy 引擎/会话；仅 Shipment 使用
  models/
  migrations/

app/pages/          # GUI 仍放这里，便于 MainWindow 注册
  shipment_dashboard_page.py
  shipment_list_page.py
  shipment_detail_page.py
  shipment_exception_page.py
  shipment_eta_page.py
  shipment_forwarder_settings_page.py

tests/shipment_tracking/
```

集成薄层（发票成功后调用，仍属服务层）：

```text
app/services/shipment_integration.py
  # 从 BatchRecord + merge_plan 构造 ShipmentCreateCommand
  # 禁止 GUI import repository
```

`MainWindow.nav_items` 增加 `shipment`（或子页用页内 Tab）。首页加一张卡片即可。

---

## 13. 现有约束（后续 Task 不得破坏）

- 快越达合并：复制官方 `.xls`，BIFF 填写，不经 Excel 另存；图块 `kyd_et_cell_image_data.bin`
- 迈创：复制官方 `.xlsx`，COM 粘贴 + Calculate；不覆盖 B2 渠道
- 地址：中央 `各物流地址库.xlsx`，维护页打开；不改官方模板内嵌地址库
- 配置路径写死 OneDrive `I:\...\发票系统`（`invoice_config.py`）
- 单活动 Batch、内容哈希、MergePlan 哈希

---

## 14. 本 Task 未做事项

- 未改业务代码
- 未建表、未引入 SQLAlchemy
- 未加 GUI
- 未实现 `CreateShipment`
- `docs/specs/shipment-tracking-center-v1.md` 仓库中尚不存在（计划引用了该 Spec）
