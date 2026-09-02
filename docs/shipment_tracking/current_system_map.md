# Shipment Tracking Current System Map

PHASE 0 / Task 0.1（2026-09-01）。  
PHASE 0 / Task 0.2（2026-09-01）：Channel / Tracking 绑定点专项调查（第 21–25 节）。  
PHASE 1 / 物流绑定（2026-09-01）：发货规划 FBA 只读匹配发票批次 `snapshot.json` 的确认货代（`CarrierCode`）；跳过 `INVALIDATED`；文件名物流商仅作候选。  

范围：`D:\InvoiceMergeSystem` 现有代码 + 真实目录 `I:\OneDrive\OneDrive - Lion\【采购仓储】\【装箱明细】` 抽样 + `发票系统\全部发票汇总` / `询价路径` 抽样。  
本文件只描述数据是什么、何时可信。不设计表、不实现 Parser、不接 API。

先前（2026-08-28）同路径文档描述的是**发票合并成功后**能读到的字段。本次专项调查确认：那条链**不能**作为 `FBA → SKU → Qty` 的事实源。

---

## 1. Shipping File Directory Model

根目录（已在磁盘存在，本仓库**没有任何常量指向它**）：

```text
I:\OneDrive\OneDrive - Lion\【采购仓储】\【装箱明细】
```

抽样：19 个店铺目录（`美3`、`美10`、`美15`、`欧1`、`英1`、`EM` 等）。

| 层 | 样例 | 业务含义 | 本仓库是否解析 |
|---|---|---|---|
| 店铺 | `美3` | `store_code` | 否 |
| 月份 | `2026.8` / `2026.08` / `2026.05` / `2026.5` | year + month | 否 |
| 日期 | `8.21美3` | `ship_date` + store | 否 |
| 批次 | 无子目录，或 `1`/`2` | `batch_no`（当天第几批） | 否 |
| 文件 | `0811-美3-快越达.xlsm` | 发货单/发货规划工作簿 | 否（扩展名也不在扫描白名单） |

同店月份文件夹名**混用**（全库实际出现）：`2026.01` 与 `2026.1`，`2026.05` 与 `2026.5`，`2026.8`，`2026.06`。另有不像月份的目录名（如 `2.6EM`、`6.26EM`），现有代码没有识别规则。

日期文件夹与文件名日期**可以不一致**：`美3\2026.8\8.21美3\0811-美3-快越达.xlsm`（夹名 8.21，文件名 0811）。现有代码不读这些路径，因此没有「以谁为准」的规则。

非批次子目录：常见 `标签`。数字名 `1`/`2` 才是当天多批。

本仓库扫描的是另一棵树：`发票系统\询价路径`、`invoice_sources.ini` 里的物流商发票目录。`ALLOWED_EXTENSIONS = {".xlsx"}`（`app/invoice_config.py`），**`.xlsm` 会被发票扫描直接跳过**。

---

## 2. Batch Identification

目录层 `batch_no`：**代码中不存在**。没有 `batch_no`、没有对 `1`/`2` 子目录的识别。

本仓库里的 `Batch` / `batch_id` 是**发票合并批次**（如 `20260821-B0001`），来自 `app/services/batch_service.py`，按 `DateID` 一天一个未完成发票 Batch。与装箱明细「当天第几批发货」不是同一概念。

真实目录证据：

- 单批：`美3\2026.8\8.21美3\` 下直接 `.xlsm`（旁有 `标签`，不是批次号）
- 多批：`美3\2026.6\6.11美3\1\` 与 `\2\` 各一份 `0611-美3-迈创合德.xlsm`

未来若建发货事实，必须单独定义 `Store + ShipDate + BatchNo`，**不要复用**发票 `batch_id`。

---

## 3. Shipping Plan Parser Entry

**本仓库没有发货单 / 发货规划 Parser。**

| 查找项 | 结果 |
|---|---|
| `ShippingPlanParser` / `CartonParser` | 不存在 |
| 打开 `.xlsm` | 不存在 |
| 识别「美国3号-发货规划」 | 不存在 |
| 最接近的 Excel 读取 | 见下表（都不是发货规划） |

实际打开 Excel 的模块：

| 文件 | 类/函数 | 打开什么 |
|---|---|---|
| `app/services/invoice_scan_service.py` | `read_system_meta()` | 源发票 `.xlsx` 隐藏表 `_SystemMeta` |
| `app/services/inquiry_service.py` | 扫描 `*_询价明细.xlsx` | 询价明细行（仓/箱/重，无 SKU） |
| `app/services/invoice_adapters/kyd_adapter.py` | `KydAdapter._source_rows()` | 工作表「快越达发票」第 30 行起 |
| `app/services/invoice_adapters/mc_adapter.py` | `McAdapter.merge_group` / `_count_data_rows_openpyxl` | 工作表「迈创发票」第 18 行起 |

发货规划工作表**存在于真实 `.xlsm`**，由店号命名，例如：

- `美国3号-发货规划`（与店铺 `美3` 对应）
- 同文件常残留 `美国8号-发货规划 1`（他店模板残留，不能当本店事实）

识别方式（文件内观察，非本仓库代码）：按 Sheet 名关键词 `发货规划` + 店号，**不是**本程序配置，也**没有**写死在 Python 里。

---

## 4. FBA Extraction

### 4.1 装箱明细（事实源，本仓库未读）

真实文件 `0611-美3-迈创合德.xlsm` → 表 `美国3号-发货规划`：

- 第 1 行、第 14 列起：仓库（`IND9`、`ABE8`、`PSP3`…）
- 第 2 行同列：`FBA批号`（如 `FBA19FY7J9B7`）
- 第 3 行：`内部编码ID`
- 第 12 行：`总数量(箱)`（该 FBA 箱数，抽样为 118）

一列 = 一个 FBA（不是一列 = 一个物理箱）。

### 4.2 本仓库已结构化保存的 FBA

来源：上游 VBA 写入源发票 `_SystemMeta.FBABatch`。

- 读取：`read_system_meta()` → `InvoiceRecord.fba_batch`
- 校验：`scan_original_invoices()` 要求同一 `FBABatch` 只能对应一个 `WarehouseCode`
- MergePlan **不按 FBA 分组**，按货代 + 模板版本 + 目的仓；一组里可以有多个 FBA

询价明细同样有列 `FBABatch`（`inquiry_service.REQUIRED_COLUMNS`），粒度为**箱**，无 SKU。

---

## 5. SKU Extraction

### 5.1 装箱明细（事实源，本仓库未读）

`美国3号-发货规划` 第 13 行为表头：

| 列 | 表头 |
|---|---|
| 1 | 产品英文品名 |
| 2 | 英文材质 |
| 3 | 中文材质 |
| 4 | 商品编码 HS CODE |
| 5 | 子ASIN |
| 6 | SKU |
| 7 | 图片地址 |
| 8 | 产品中文品名 |
| 9 | 是否发货 |
| 13 | 发货数量（该 SKU 各 FBA 合计） |
| 14 列起 | 各 FBA 列上的该 SKU 数量 |

抽样已发货行同时带齐：SKU、子ASIN、中英文品名。

### 5.2 本仓库

发票适配器 `product_fields` 只有 `ProductEN` / `ProductCN` / `MaterialEN` / `MaterialCN`。**没有 SKU、没有 ASIN 字段。**

`ShipmentItemInput.sku`（`app/shipment_tracking/domain/commands.py`）是尚未接入 GUI 的命令 DTO，没有任何 Parser 给它赋值。

---

## 6. Quantity Extraction

必须区分三种数量：

| 数量 | 在发货规划里 | 本仓库 |
|---|---|---|
| FBA 内该 SKU 补货数 | 第 13 行起、对应 FBA 列单元格 | **无** |
| SKU 全 FBA 合计 | 第 13 列「发货数量」 | **无** |
| 单箱申报数量 | 不在发货规划矩阵里 | 发票明细：KYD 第 7 列、MC `J` 列；且上游按 **MAIN_SKU** 只写主 SKU |

真实抽样（`6.11美3` 第 1 批）：

- `US3A16-Silver` 合计 40；五个 FBA 各 8
- 同一 FBA `FBA19FY7J9B7` 同时有 5 个 SKU（8 / 50 / 20 / 24 / 16）

因此 **FBA 多 SKU 在发货规划里成立**。发票链无法还原：同文件 `物流商配置` 申报模式 = `MAIN_SKU`；`发票字段映射` 写明品名取「**最大数量 SKU 所在行**」。这与「单份发票可能只体现某一个 FBA 下的一个产品」一致。

跨箱合计（同一 FBA、同一 SKU 分在多箱）：发货规划给出的已是 **FBA 列合计**，不必再从箱加总。物理箱清单在表「做发票」（原箱号、仓、重量、长宽高、箱内总件数），**没有按箱拆 SKU**。

---

## 7. Carton Data Structure

本仓库没有名为 `CartonData` 的类型。

最接近的已落地对象：

```text
InvoiceRecord  (invoice_scan_service.py)
  path, sha256
  carrier_code, carrier_name, template_version
  date_id, generated_at
  store_code, plan_id, source_id
  warehouse_code, fba_batch, carton_number
```

一箱一张源发票。**无** SKU、无重量、无尺寸、无渠道文本。

询价行另有 `WeightKG`（按箱，不按 SKU）。

发货规划表头（箱/FBA 级，列在第 1–12 行）：`Warehouse`、`FBA批号`、`内部编码ID`、长/宽/高 cm、重量 KG/LB、总数量(箱)。没有独立的 `CartonNumber` 列；箱号是上游生成发票时用「FBA批号 & U + 同 FBA 序号（6 位）」拼出来的（见 xlsm 表「发票字段映射」）。

未接线的 DTO（禁止当作已有 Parser 输出）：

```text
ShipmentCartonInput: carton_number, weight_kg, length_cm, width_cm, height_cm
ShipmentItemInput: sku, product_name, quantity, asin, cartons, weight_kg
```

---

## 8. Can Current Parser Produce Batch → FBA → SKU → Qty?

**不能。** 现有 Parser 碰不到装箱明细，也拿不到 SKU。

| 链 | 现有 Parser | 真实 `.xlsm` 能否支持（尚未接入） |
|---|---|---|
| Store + ShipDate + BatchNo | 无（发票 Batch 是另一概念） | 目录层可推出；代码未做 |
| FBA → SKU → Qty | 无 | **能**：发货规划矩阵 |
| FBA → Carton → SKU → Qty | 无 | **不能完整得到**：SKU 停在 FBA 列；「做发票」有物理箱无 SKU；发票只有 MAIN_SKU |

结论编号见第 20 节 Question A = **NO**（对现有 Parser）。  
底层 Excel 对 `FBA → SKU → Qty` 已够；缺的是 **新 Parser + 目录层 BatchNo**，不是「对已有 Carton 行做一次 groupby」那么简单（因为本仓库根本没有 Carton→SKU 行）。

---

## 9. Current Forwarder Data Flow

| 来源 | 是否被本程序解析/使用 | 角色 |
|---|---|---|
| 装箱明细文件名 `…-快越达.xlsm` / `…-迈创合德.xlsm` | 否 | Candidate |
| xlsm「物流商配置」`本次生成=生成`（抽样 KYD=生成，MC=不生成） | 否（VBA 用） | Candidate / 生成开关 |
| `发票系统\公共配置\invoice_sources.ini` `CarrierCode` | 是。`load_source_entries()`；GUI 下拉「物流商扫描源」 | 扫描范围 + Candidate 代码（KYD/MC） |
| `current_config.ini` `[Carrier.KYD]` | 是。`load_known_carriers()` 拒未知码 | 白名单 |
| 源发票 `_SystemMeta.CarrierCode` / `CarrierName` | 是。写入 `InvoiceRecord` | 扫描后结构化 |
| MergePlan `Groups[].carrier_code` | 是。内容合并选适配器 | 与 meta 一致的分组键 |
| 适配器注册表 `get_adapter("KYD"/"MC")` | 是。只合并发票模板 | 非轨迹 API |

GUI：`InvoicePage.source_combo` 一次只选一个已启用 Source，再 `scan_original_invoices`。没有单独的「确认货代」对话框。

---

## 10. Candidate Forwarder vs Confirmed Forwarder

```text
candidate_forwarder
  文件名（快越达 / 迈创合德）
  xlsm「物流商配置」本次生成
  invoice_sources.ini CarrierCode（扫描前人工选源）

confirmed_forwarder（本系统内）
  源发票 _SystemMeta.CarrierCode
  在「发票中心选择扫描源并扫描通过」之后确定
  内容合并 / 结果检查不再改货代
```

文件名 **不等于** `final_forwarder`：程序从不解析文件名里的「快越达」。若文件名与 `_SystemMeta` 冲突，以 meta 为准（meta 才被读取）。

最后一次与货代有关的人工动作：在发票中心选择 `KYD｜…` / `MC｜…` 扫描源。之后没有改货代的步骤（批量修改改的是渠道单元格，不改 `CarrierCode`）。

与 FBA：每张源发票同时有 `fba_batch` + `carrier_code`，**可以**按箱绑到 FBA。同一 MergePlan 组（同仓同货代）可含多个 FBA，货代相同。

---

## 11. Current Channel Data Flow

发货规划表**没有**渠道列。询价明细**没有**渠道列。`_SystemMeta.ChannelCell` 只存单元格地址（如 B4），扫描**不存渠道文本**。

| 节点 | 渠道文本在哪 | 本程序 |
|---|---|---|
| 发货单 xlsm | 无结构化渠道 | 不读 |
| 询价 | 无 | — |
| 源发票 KYD `快越达发票!B4` | 有 | 合并时 `KydAdapter._source_rows` 读取，写入结果 `B4` |
| 源发票 MC `迈创发票!B2` | 可能有旧名 | **合并不覆盖**官方模板 B2 |
| 合并结果 | KYD B4 / MC 模板 B2 | 可被「批量修改单元格值」改 |

没有 `Forwarder → Channel` 的生产配置模型。ORM `Forwarder` / `ForwarderChannel`（`app/database/models/shipment.py`）未被任何页面写入或读取。

---

## 12. Candidate Channel vs Confirmed Channel

```text
candidate_channel
  源发票上的渠道单元格（KYD B4，MC B2）
  来自上游做发票，不是发货规划

confirmed_channel（按货代分叉）
  KYD：内容合并写入合并结果 B4；若事后批量改 B4，以改后的合并结果为准
  MC：官方模板 B2（合并刻意保留）；源发票 B2 不可信
```

最可信节点：

- 未改渠道：KYD = 内容合并完成的合并文件 B4；MC = 合并文件模板 B2
- 改过渠道：`batch_modify_service` 执行成功之后的合并结果单元格

渠道绑定粒度是 **货代 + 目的仓的合并文件**，不是单个 FBA。同仓多 FBA 共用一个渠道。

---

## 13. Current Tracking Data

业务路径（询价 / 发票扫描 / 合并 / 批量改渠道）**没有** Tracking Number、运单号、提单号、货代单号、快递单号、参考号字段。

代码库检索命中仅：

- `app/database/models/shipment.py` `ShipmentTracking.tracking_number`
- `app/shipment_tracking/repositories/tracking_repository.py`
- 对应单测

上述对象**没有**从 Excel 填入，GUI 零引用（`app/pages` 无 `shipment_tracking`）。

判断：**情况 D — 当前生产数据流完全没有 Tracking**（揽收后才有单号是业务常识，但本仓库既无字段也无接口，不能当作已实现的情况 C）。

---

## 14. FBA ↔ Tracking Binding Capability

当前 **没有** `FBA ↔ Tracking`。

可作后续桥梁、但不是 Tracking 的现有字段：

| 桥梁 | 有无 | 说明 |
|---|---|---|
| FBA ↔ 货代订单号 | 无 | |
| FBA ↔ 参考号 | 无 | |
| FBA ↔ CartonNumber | 有 | `_SystemMeta` / 询价 / MergePlan `carton_numbers` |
| FBA ↔ PlanID / SourceID | 有 | 发票 meta、询价行 |
| FBA ↔ CarrierCode | 有 | 发票 meta |

---

## 15. Forwarder API Lookup Keys

**当前代码库无法确认。**

没有货代 OpenAPI 客户端、没有 KYD/MC 轨迹文档、没有按 FBA/Tracking/订单号查询的实现。`credential_reference`、`api_sync_logs` 只出现在未接线的 SQLAlchemy 模型中，不能推断真实 API 键。

---

## 16. Reliable Logistics Binding Point

| 字段 | 首次出现 | 最终确认节点 | 当前可靠性 | 是否可直接绑定 FBA |
|---|---|---|---|---|
| Forwarder | Candidate：文件名 / 物流商配置 / sources.ini。结构化：`_SystemMeta.CarrierCode` | 发票中心选扫描源并扫描通过 | 高（对已扫描发票） | 是（经箱级 meta） |
| Channel | Candidate：源发票渠道格 | KYD：合并结果 B4（含批量修改后）；MC：模板 B2 | 中（MC 源发票渠道不可信；改渠道后要以合并文件为准） | 间接（同仓同货代多 FBA 共用） |
| Tracking | 无 | **当前无可靠绑定节点** | 低 / 无 | 否 |

数据链 2 中的「？」= **发票中心选择物流商扫描源 + 源发票 `_SystemMeta`（货代）**，以及 **内容合并（及可选批量改渠道）后的合并结果文件（渠道）**。Tracking 的「？」在本系统内不存在。

---

## 17. Future GUI Field Availability

| GUI 字段 | 当前来源 | 是否已有 | 可信节点 |
|---|---|---|---|
| 店铺 | 装箱明细店目录；发票 `_SystemMeta.StoreCode`；sources.ini `StoreCode` | 发票侧已有；目录层未解析 | 发货事实应以装箱明细店目录 / 规划表 A1；发票 meta 可作核对 |
| FBA | 发货规划第 2 行；发票 `FBABatch` | 两边都有 | **补货内容以发货规划为准**；发票 FBA 只证明该箱属于该 FBA |
| 产品名称 | 发货规划 A/H 列；发票品名（MAIN_SKU） | 发票有但不完整 | 发货规划 SKU 行 |
| SKU | 发货规划第 6 列 | **暂时没有**（本仓库未读） | 发货规划 |
| 补货数量 | 发货规划 FBA 列 × SKU 行 | **暂时没有** | 发货规划（不要用发票申报数量加总） |
| 当前物流状态 | 无 | 暂时没有；未来 API | 无 |
| 发货日期 | 日期文件夹 `8.21美3`；发票 `DateID` | 发票 DateID 已有；文件夹未解析 | 目录 `ship_date` 与发票 DateID 可能不一致，需人工定规则 |
| Amazon ETA | 无 | 暂时没有；未来 API/计算 | 无 |
| 货代 | 见第 9–10 节 | 发票侧已有 Confirmed | 扫描通过后的 `CarrierCode` |
| 渠道 | 见第 11–12 节 | Excel 有，JSON 无 | 合并结果（KYD B4 / MC B2） |
| Tracking | 无 | 暂时没有；未来 API | 无 |

---

## 18. Existing Scanner Reuse Capability

| 能力 | 已有？ | 位置 |
|---|---|---|
| 递归扫描 | 有 | `collect_invoice_files` `directory.rglob("*")`；`collect_inquiry_files` `rglob("*_询价明细.xlsx")` |
| 月份识别 `2026.8` vs `2026.08` | **无** | 未来需要新增 |
| 日期识别 `8.21美3` | **无** | 未来需要新增 |
| 批次识别 `1`/`2`（排除 `标签`） | **无** | 未来需要新增 |
| `.xlsm` 筛选 | **无**（只允许 `.xlsx`） | `ALLOWED_EXTENSIONS`；未来需要新增 |
| Excel 锁文件 `~$` | 有 | `is_excel_junk_file()`；发票/询价收集均跳过 |
| 重复路径 | 有 | `seen` / `seen_paths` resolve 去重 |
| 文件修改时间 | **无**（扫描不用 mtime） | 未来需要新增 |
| Hash | 有 | `sha256_file()`（发票、询价） |

可复用的是「递归 + 锁文件 + sha256」工具函数，**不能**复用发票/询价的收集规则去扫装箱明细。

---

## 19. Missing Data

现有 Parser 相对于目标链缺少：

1. 装箱明细根路径与 `.xlsm` 扫描
2. `batch_no`（目录层）
3. 发货规划 Sheet 识别与 FBA 列表头解析
4. SKU / ASIN / 按 FBA 的补货数量
5. 物理箱 ↔ SKU 明细（源文件也没有完整矩阵）
6. 渠道的结构化 JSON 字段
7. Tracking / 货代订单号 / 参考号
8. 货代 API 查询键与实现
9. 物流状态、Amazon ETA

未接线、本阶段不当作可用能力：`app/database/models/shipment.py`、`app/shipment_tracking/*`（无 GUI、无发票回调）。

---

## 20. Final Conclusions

### Question A

```text
现有 Parser 是否能够可靠输出：

Batch → FBA → SKU → Qty
```

**NO**

证据：

- 仓库内没有任何模块打开【装箱明细】或 `.xlsm`。
- `batch_no` 未实现；发票 `batch_id` 不是发货批次。
- SKU 只存在于发货规划第 6 列，从未被 Python 读取。
- 发票/询价即使有 FBA，也按箱、且发票申报为 MAIN_SKU，不能还原 FBA 内全部 SKU 数量。

Excel 侧：`FBA → SKU → Qty` **可以**从「美国N号-发货规划」直接读出（抽样：一 FBA 五 SKU）。`Batch → …` 要靠目录。`FBA → Carton → SKU → Qty` 源文件也不完整。

### Question B

```text
Forwarder:
最佳绑定节点 = 发票中心选择物流商扫描源并扫描通过后的 _SystemMeta.CarrierCode
（文件名 / 物流商配置 = Candidate，程序未读）

Channel:
最佳绑定节点 = 内容合并完成后的合并结果渠道格
（KYD：B4，含事后批量修改；MC：官方模板 B2，不要用源发票 B2）

Tracking:
最佳绑定节点 = 当前无可靠绑定节点
```

---

## 附录：两条真实数据链（代码 vs 源文件）

### 数据链 1 — 发货事实（目标）

```text
【装箱明细】店铺目录          （未解析）
    ↓
月份目录 2026.8 / 2026.08     （未解析）
    ↓
日期目录 8.21美3              （未解析）
    ↓
批次 缺省=1 或子目录 1/2      （未解析）
    ↓
*.xlsm（排除 ~$）             （未扫描）
    ↓
Sheet「美国3号-发货规划」      （无 Parser）
    ↓
FBA 列头第2行
    ↓
SKU 行第6列 + 该 FBA 列数量
```

本仓库实际走的是另一条链，且不能替代上图：

```text
invoice_sources.ini
    ↓
collect_invoice_files (.xlsx)
    ↓
read_system_meta → InvoiceRecord（店/FBA/箱/货代，无 SKU）
    ↓
MergePlan（按仓+货代，不是按 FBA）
    ↓
KydAdapter._source_rows / Mc 源表明细（品名+申报数量，MAIN_SKU）
```

### 数据链 2 — 物流绑定

```text
FBA（发货规划或发票 meta）
    ↓
？ = 发票扫描源选择 + _SystemMeta.CarrierCode     → Forwarder Confirmed
    ↓
？ = 内容合并（及可选批量改渠道）合并结果文件         → Channel Confirmed
    ↓
Tracking = （本系统无此节点）
```

---

## Channel Binding Investigation

调查范围：全仓库关键词（Channel / 渠道 / shipping_channel / service_type / transport_mode / shipping_method / route 等）+ GUI 控件 + `_SystemMeta` + 真实 `.xlsm` / 源发票 / 询价文件。未改 Parser、未改 `_SystemMeta`、未接 API。

### 1. 发货单 `.xlsm` 里有没有 Channel

发货规划表（如 `美国3号-发货规划`）**没有渠道列**。

渠道出现在**同一份发货单里的发票模板 Sheet**，不是规划矩阵：

| 文件 | 位置 | 抽样值 | 本程序是否读取 |
|---|---|---|---|
| `0811-美3-快越达.xlsm` | `快越达发票!B4`（标签 `服务（渠道）*`） | `K18美西稳速达-卡派-包税` | **否**（不打开 `.xlsm`） |
| 同文件 | `迈创发票!B2`（标签 `服务*`） | `墨西哥空运带电/敏感` | **否** |
| `0611-美3-迈创合德.xlsm` | `迈创发票!B2` | 同上，模板默认服务名 | **否** |

`物流商配置` 只有货代代码/申报模式/`本次生成`，**没有渠道列**。  
`发票字段映射` **没有** Channel / ChannelCode / 服务 映射行；VBA 不会从发货规划写入渠道。渠道是发票模板上的自由文本（或人工改模板），不是规划事实。

文件名 `0811-美3-快越达.xlsm` 只有货代 Candidate，**没有渠道**。程序也不解析文件名。

### 2. GUI 是否人工选择渠道（美森 / 普船 / 空派 / 卡派 / 快船）

**没有**这类下拉。

| 控件 | 文件 | 选的是什么 |
|---|---|---|
| `InvoicePage.source_combo`（唯一生产 `QComboBox`） | `app/pages/invoice_page.py` | **物流商扫描源**（`KYD｜…` / `MC｜…`），不是渠道 |
| `BatchEditPage.value_edit`（`QLineEdit`） | `app/pages/batch_edit_page.py` | 自由文本「新的发货渠道」，无选项列表 |
| 询价中心 | `inquiry_page.py` | 无 ComboBox、无渠道列 |

链：

```text
发票中心 source_combo
    → currentData = SourceKey
    → scan_original_invoices(该扫描源)
    → 确认的是 CarrierCode，不是 Channel

批量修改 value_edit
    → preview_files / apply_modifications
    → 写入合并结果指定单元格（KYD 默认 B4）
    → 只改 Excel 文本，不写 JSON / 不写 _SystemMeta
```

测试和未接线 DTO 里出现过 `美森限时达`（`ShipmentCreateCommand.channel_code`），**无页面引用**。

### 3. Channel 是否进入 `_SystemMeta`

**不进入渠道文本。** 只强制存在地址指针：

```text
_SystemMeta.ChannelCell = "B4"   （KYD 抽样；必填）
```

`read_system_meta()` 把该地址读进临时 `dict`，但 `InvoiceRecord` **没有** `channel` / `channel_cell` 字段。  
`snapshot.json` / `quick_merge_manifest.json` / MergePlan **都不保存** ChannelCell 或渠道名。

不存在：`ChannelCode`、`ChannelName`、`ServiceCode`、`RouteCode`、`TransportType`、`ShippingMethod`。

生产路径上真正读写渠道**文本**的位置：

```text
来源：源发票「快越达发票」B4
  KydAdapter._source_rows → 第一个非空 B4
  merge_group → fill_kyd_template(..., channel=...)
  写入：合并结果「模板」B4（xls r4c2）

迈创：McAdapter.merge_group 不覆盖官方模板 B2
  validate_output 只检查合并结果 B2 非空
  源发票 B2 = Candidate，不可当作 Confirmed
```

### 4. Candidate vs Confirmed

```text
candidate_channel
  xlsm 发票模板 B4/B2（本程序未读）
  源发票 KYD B4 / MC B2（合并前 Excel 文本）
  不从文件名、目录名推断（程序无此解析）

confirmed_channel
  KYD：内容合并完成后的合并结果 B4
        若批量修改成功，以改后的合并结果 B4 为准
  MC：官方「迈创发票模板.xlsx」复制件的模板!B2
        （合并不用源发票服务名）
```

绑定粒度 = **货代 + 目的仓的一份合并文件**，同仓多个 FBA 共用一个渠道文本。没有 `ChannelCode`。

---

## Tracking Binding Investigation

全仓库检索：tracking / tracking_number / 运单号 / 物流单号 / 货代单号 / 提单号 / 海运单号 / 快递单号 / order_no / reference / waybill / BOL / BL / 客户单号 / 客户参考号 / 参考号。

### 生产路径（询价扫描 / 发票扫描 / 合并 / 批量改渠道 / 敏感词）

**没有任何 Tracking 字段被读取或保存。** `app/pages` 对 `shipment_tracking` **零引用**，无人工录入运单/提单的入口。

### Excel 上的空槽（有标签、无值、本程序不读）

真实抽样：

| 位置 | 标签 | 抽样值 | 发票字段映射 | 本程序 |
|---|---|---|---|---|
| xlsm / 源发票 `快越达发票!A2` | `客户订单号（运单号码）` | **空**（源发票 B2=`None`） | **无此映射** | 不读 B2 |
| xlsm `迈创发票!A1` | `客户订单号` | **空** | 无 | 不读 |
| KYD 明细表头第 29 行 B 列 | `PO Number*（Reference ID）` | Amazon 箱级参考列名 | 无 Tracking 映射 | 合并读的是品名/数量/图，不把该列当运单 |
| `做发票` | 箱/仓/重量/尺寸 | 无运单列 | — | 不读 `.xlsm` |

结论：货代侧「客户订单号 / 运单号码」在发票模板上是**预留格**，生成发货单和生成源发票时都**没有填写**。不能当作已存在的 Tracking。

### 未接线代码（不当作生产来源）

- `ShipmentTracking.tracking_number`（`app/database/models/shipment.py`）
- `TrackingRepository.add_tracking()`
- `ApiSyncLog`

仅单测写入内存 SQLite，无 GUI、无发票回调、无真实 API。

### 产生时间（按代码，不是按业务常识）

**E — 目前系统完全没有。**

不是 A（发货单已有值：标签空）。不是 B/C（确定货代、生成发票后仍空）。D（揽收后才有单号）是行业常识，但本仓库既无字段赋值也无接口，不能选 D。

---

## _SystemMeta Complete Field Review

权威清单：`invoice_scan_service.META_FIELDS`。`read_system_meta()` 读 `_SystemMeta` A/B 两列全部键值，但**缺任一必填键即失败**。真实源发票抽样 **extra_keys = []**（没有隐藏的 Tracking / ChannelName）。

| 键 | 抽样值 | 进入 InvoiceRecord？ | 用途 |
|---|---|---|---|
| MetaSchemaVersion | `1.0` | 否（只校验） | 必须为 1.0 |
| CarrierCode | `KYD` / `MC` | **是** `carrier_code` | Confirmed Forwarder |
| CarrierName | `快越达` | 是 `carrier_name` | 展示 |
| TemplateVersion | `1.0` | 是 | 选适配器 |
| InvoiceType | `STANDARD` | 否 | 只要求非空 |
| ChannelCell | `B4` | **否** | **单元格地址**，不是渠道名 |
| DateID | `20260821` | 是 `date_id` | 发票日 |
| GeneratedAt | 时间戳 | 是 | 同 SourceID 留最新 |
| StoreCode | `美8` | 是 | 店 |
| PlanID | `CD` | 是 | 计划 |
| SourceID | 8 位 hex | 是 | 一次生成 |
| WarehouseCode | `ABE8` | 是 | 目的仓 |
| FBABatch | `FBA19MGRJV7V` | 是 `fba_batch` | FBA |
| CartonNumber | `…U000001` | 是 | 箱号 |

**没有：** Channel / ChannelCode / ChannelName / TrackingNo / OrderNo / ReferenceNo / Waybill / BOL / 客户订单号。

合并结果（KYD `.xls` / MC `.xlsx`）**禁止**再带 `_SystemMeta` / `_MergeMeta`（`validate_output`）。因此合并后渠道只活在可见单元格里。

询价明细另有列 `DefaultCarrier`、`CarrierCode`（真实表头存在），`inquiry_service.REQUIRED_COLUMNS` **不包含它们，扫描也不读**。询价也**没有**渠道、运单、订单号列。

---

## FBA ↔ Logistics Identifier Mapping

| 关系 | 当前 | 最稳定路径（若要用） |
|---|---|---|
| FBA ↔ CarrierCode | **有** | `_SystemMeta.FBABatch` + `_SystemMeta.CarrierCode`（扫描通过后，箱级） |
| FBA ↔ Channel 文本 | **间接** | 箱 → 仓 + 货代 → 合并文件 → KYD B4 / MC B2；同仓多 FBA 共用 |
| FBA ↔ ChannelCode | **无** | 生产无渠道代码 |
| FBA ↔ Tracking Number | **无** | |
| FBA ↔ Forwarder Order / 客户订单号 | **无** | 模板有空标签，值为空，程序不读 |
| FBA ↔ Customer Reference / 货代参考号 | **无** | KYD「PO Number / Reference ID」是 Amazon 箱级列名，不是货代参考号 |
| FBA ↔ Bill of Lading / Waybill | **无** | |
| FBA ↔ CartonNumber | **有** | meta / 询价 / MergePlan `carton_numbers` |
| FBA ↔ PlanID / SourceID | **有** | 发票 meta、询价行 |

货代 API 查询键：**当前代码库无法确认**（无 OpenAPI / Postman / Provider 客户端；`credential_reference` 只在未接线模型里）。

---

## Logistics Binding Final Recommendation

只基于现有数据，不发明表。

```text
当前可绑定：

FBA
+ _SystemMeta.CarrierCode     （发票中心选扫描源并扫描通过）

Channel 文本（非 ChannelCode）
+ KYD：合并结果 B4（含批量修改后）
+ MC：合并结果模板 B2（官方模板名）

当前不可绑定：

TrackingNumber
ForwarderOrderNo
ReferenceNo（货代）
BL / Waybill
ChannelCode
```

已实现（只读，不写库、不改合并）：

```text
发货规划 FBA
  → BATCH_ROOT/**/snapshot.json  Files[].fba_batch + carrier_code
  → 跳过 status.json Status=INVALIDATED
  → 同店同 FBA 多个 CarrierCode → 冲突
  → 扫描未覆盖 → 未绑定
文件名「快越达」等 → 候选货代，不当确认
```

Channel / Tracking 仍待后续：

```text
FBA
+ ChannelText（从合并结果读，不要从 _SystemMeta.ChannelCell 当渠道名）
+ Tracking：未来 人工录入 或 货代API
    查询键待 API 文档，禁止假设等于 FBA
```

不要用文件名里的「快越达」当 Forwarder，不要用源发票 MC B2 当 Confirmed Channel，不要把空的「客户订单号（运单号码）」当成已有 Tracking。

