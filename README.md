# 发票合并系统

面向多店铺 Amazon FBA 发货工作的 Windows 桌面程序，用于汇总物流询价、合并货代商业发票、查看发货和物流轨迹，以及批量修改渠道、检查敏感词。

当前代码版本为 **v1.1.19**。业务数据、模板和公共配置主要放在公司 OneDrive，程序代码由 Git 管理。

V1.1.19 加入发票中心国家分流及浅色桌面主题：统一侧栏图标、文字层级、按钮、表格及状态提示，保留现有业务操作。请使用 `发票合并系统_V1.1.19.exe`；旧 exe 不包含本次改动。

## 文档入口

- [项目理解与维护交接](docs/项目理解与维护交接.md)：程序目的、当前实现、数据流、维护边界、测试基线与 Git 状态。
- [操作说明书](docs/发票合并系统应用说明书.md)：日常使用与常见问题。
- [版本历史](docs/V1.1发版说明.md)：V1.1 至 V1.1.19 的主要变化。
- [维护入口](AGENTS.md)：后续维护时先读取的项目约定。
- [早期追踪调查](docs/shipment_tracking/current_system_map.md)：历史设计依据，部分结论已被后续实现替代。

## 主要功能

- **询价中心**：按国家站点、日期范围扫描询价明细，按仓库汇总重量和箱数，导出询价表。
- **发票中心**：选择货代和国家扫描源发票，核验仓库国家，在单一国家内按货代、模板版本、仓库合并，生成快越达 `.xls` 或迈创 `.xlsx` 上传文件。使用前请按[国家目录配置](docs/发票国家分流配置.md)整理源发票。
- **发货追踪**：读取装箱明细中的发货规划，显示 FBA、SKU、数量、货代、渠道和 Tracking，按需查询物流详情。
- **重点追踪**：保存店铺与品名条件，集中查看最近 60 天的重点产品运输情况。
- **批量修改与敏感词检查**：修改选中单元格、检查品名和材质，并提供命中定位和结果导出。
- **维护**：打开中央物流地址库。发票中心还可打开货代登录网页，由操作人员自行登录、上传和下单。

## 运行

需要 Windows、Python 和 Microsoft Excel。当前项目虚拟环境为 Python **3.11.4**。

在项目根目录使用已有环境启动：

```powershell
& .\.venv\Scripts\python.exe main.py
```

首次建立环境时：

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

还需要本机能访问代码中配置的 `I:\OneDrive\OneDrive - Lion` 业务目录，以及中央模板、地址库和公共配置。安装 Python 依赖不会自动创建这些业务文件。

## 验证与打包

运行现有测试：

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

测试集包含依赖真实模板、装箱明细及 Excel 自动化的用例；不属于完全独立于业务环境的测试集。`pytest.ini` 的临时目录也固定在 `D:/InvoiceMergeSystem/temp/pytest`。

2026-10-20 的 V1.1.19 发布回归：**217 passed，1 warning**（22.17 秒），包含 Excel COM 用例。接手时受限环境曾因 Excel COM 激活返回 `0x80070005` 失败，完整历史及环境差异见[交接记录](docs/项目理解与维护交接.md)。真实货代导入与 Windows 显示缩放仍需实际工作环境验收。

已有打包配置，可在具备 PyInstaller 的 Windows 环境中执行：

```powershell
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm InvoiceMergeSystem.spec
```

PyInstaller 未列入 `requirements.txt`；本机现有环境已安装。发布产物位于 `dist/发票合并系统_V1.1.19.exe`，含使用说明的压缩包位于 `release/发票合并系统_V1.1.19.zip`。

正式发版还需复制到公司 OneDrive 的版本目录：

```text
I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\发票合并系统_V<版本号>\
```

沿用历史发布位置，新建版本目录，复制已验证的 `release/发票合并系统_V<版本号>/` 内容，再逐文件比对 SHA256。V1.1.19 已于 2026-10-20 复制并验证全部 7 个文件。Git 推送、GitHub Release 和 OneDrive 文件发布是三个独立步骤；云端同步状态由 OneDrive 客户端负责。

## Git

仓库远程地址：[mylife20250103-cell/FHZZ](https://github.com/mylife20250103-cell/FHZZ)。2026-10-20 检查时，当前分支为 `dev`，代码基线为 `24ea17f`；本地 `main` 仍停留在较早版本。

代码仓库与 OneDrive 业务数据需要分别保留。`dist/`、`release/`、`build/`、`.venv/`、`temp/` 和 `logs/` 当前被 Git 忽略，提交代码不会把这些内容一起备份。
