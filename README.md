# Protein Lab — 本地优先的蛋白研究流程平台

本地运行的蛋白质实验管理系统：从蛋白建库、浓度计算、BLI 梯度、酶活分析到实验归档，一条链管理湿实验里真正会用到的数据。Flask + 纯 SQLite，无需网络，数据完全本地。

> **给实验室自己用的数据管理**——不追求通用，只覆盖你做实验那天真的需要的东西。

![Protein Lab 概览](docs/screenshot.png)

## 它解决什么问题

数据散落在各处是湿实验最常见的隐性成本：浓度算在 Excel、酶活画在临时脚本、结果记在笔记里，下次要用找不回。Protein Lab 把这条链收拢进一个本地应用，每个环节的结果都能一键存档、随时回溯。

| 核心场景 | 你得到 |
|---|---|
| **蛋白库存** | 蛋白库 + FASTA 批量导入 + 搜索 / 标签筛选 / 批量改标签；MW、消光系数自动计算（ProtParam，与 Expasy 一致）；表头排序 |
| **自动化分析** | TECAN Spark xlsx 一键解析 → 96 孔板 → 动力学拟合（ΔOD/min、R²）→ Michaelis-Menten → 阴性扣除 → 作图 Excel（每孔独立时间/OD 列对宽格式，Origin/Prism 直接可用） |
| **实验记录** | 一键归档 + 自动命名（`{日期}_{类型}_{序号}`）+ 详情页 + Excel 导出 + 撤销；从历史实验一键复制回填到工具 |
| **AI 集成** | MCP 服务器 10 个工具：读蛋白库 / 算浓度 / 稀释规划 / 单位换算 / 读研究脉络 / 存实验，Claude 等 AI 可直接操作你的数据 |

## 功能

- **研究脉络**（v0.1.0）— 顶层导航第一项（默认首页）：**目标 →(拆解)子目标/实验 →(得出)结论 →(引出)新目标** 证据链；白名单 + 自由挂载逃生舱；实验块 = 关联已归档实验（exp_id）或计划占位；**根目标列表**（默认，每根卡片带节点/实验数）→ 点入**单根横向流程图**（左→右流式、同级纵向并联、连接线按类型着色）+ 链视图（根到节点 breadcrumb）+ 实验引用卡 + 搜索/标签/蛋白筛选；MCP 可读
- **蛋白库** — 手动添加 / FASTA 批量导入 / 搜索匹配 / 标签筛选与编辑 / **批量改标签**（选中多条添加/移除标签）/ **点击表头按 MW、消光系数排序**
- **计算工具**（7 个标签页）：
  - 蛋白浓度 — Beer-Lambert 计算（Biopython ProtParam 消光系数，与 Expasy 一致）；**浓度单位切换**（M/uM/nM/mg/mL/ug/mL/ng/uL）
  - BLI 浓度梯度 — 递推稀释 + 统一体积 + 整百微升取整；**单位切换**
  - **BLI 分析**（v0.0.8）— 上传 ForteBio CSV：传感器图（SG 平滑 + 拟合虚线 + 每样本出图）+ **5 方法 KD 拟合** + 保存为实验（**原始曲线落 experiment_raw 快照** + results 带分析版本）
  - **AKTA 峰图**（v0.0.9）— 上传 AKTA Unicorn zip **原生解析**（无 pycorn 依赖）：通道列表 + Fraction 事件 → **峰检测/标注** + 峰表 Excel 导出 → 保存为实验（**原始曲线落快照**）
  - Weblogo — 勾选蛋白生成序列标识图；**长序列自动分块换行**（每块 50 位，编号连续）；可选**位点区间**和**多聚体裁剪**；**结果服务端缓存 + 切页自动恢复**
  - 酶活计算 — TECAN Spark xlsx 解析 + 96 孔板 UI + 动力学拟合（ΔOD/min、R²）+ Michaelis-Menten + **阴性扣除**（信号级归零 + 速率级校正）+ **时间点筛选** + 一键导出作图 Excel
  - 从实验复制 — 卡片式浏览历史实验，按类型过滤/搜索，一键加载到对应工具
- **BLI 模块**（v0.0.5）— ForteBio CSV 解析 + 传感器图（Savitzky-Golay 平滑 + 拟合虚线）+ **五方法 KD 拟合内核**（standard / split / joint / steady / mixed，含死曲线过滤与 NS 扣除）
- **BLI 原始数据拟合**（v0.0.8）— 上传 ForteBio CSV 一键分析：传感器图 / 5 方法 KD / **保存为实验（原始曲线落 experiment_raw 快照 + results 带分析版本）**
- **AKTA 峰图整理**（v0.0.9）— 上传 AKTA Unicorn zip 原生解析（**无 pycorn 依赖，标准库实现**）：通道列表（UV/Cond/压力…）+ Fraction 事件 → **峰检测/标注/峰表导出 Excel** → 保存为实验（原始曲线落快照）
- **实验自动命名** — `{日期}_{实验类型}_{序号}`，同一天同类型自动递增；导出文件也遵循命名
- **实验归档** — 一键保存 / Excel 导出 / 详情页 / 批量删除 + 撤销；启动自动备份数据库（保留最近 10 份）
- **MCP 服务器** — 8 个工具，供 Claude 等 AI 通过 MCP 协议调用
- **测试** — `test_models.py`（14 节：JSON 往返 / 迁移框架 / 原始数据不可变 / MCP 读写契约）+ `test_bli.py`（BLI 解析/绘图/KD 拟合 + 酶活绘图 + **BLI 分析 API**）+ `test_akta.py`（**AKTA 原生解析/峰检测/峰图 + API**，用真实样例 zip）；CI 每次构建前自动运行

## 数据完整性（v0.0.7）

湿实验数据丢了就再也补不回来。数据层围绕 8 条完整性规则设计：

| 能力 | 说明 |
|---|---|
| **版本化 schema 迁移** | `PRAGMA user_version` + 有序迁移列表，应用启动即自动升级；老库非破坏升级，数据原样不动 |
| **原始数据不可变** | `experiment_raw` 表**只写一次、从不覆盖**（新分析=新快照行）；删除实验不删原始数据（FK `ON DELETE SET NULL`） |
| **迁移前自动备份** | 每次 schema 升级前快照 `pre-migration_*.db`（保留 5 份）；启动例行备份保留 10 份 |
| **MCP 读写契约** | 唯一写工具 `save_experiment`，读工具零写库——由测试逐工具断言强制，不是口头约定 |
| **架构分层** | `models`（数据+序列化）→ `services`（统一写入入口）→ `calculators`（纯函数，可单测）→ `app`（编排渲染）；速率校正等计算**后端单写**，消灭前后端双写漂移 |

## 运行方式

### 方式一：源码 + venv（开发 / 无打包需求）

- Windows 双击 `启动.bat`，macOS 双击 `启动.command`，浏览器自动打开 <http://127.0.0.1:5000>。
- 首次运行自动创建 `.venv` 并安装依赖。关闭窗口即停止服务。
- 启动时自动备份数据库到 `backups/`（保留最近 10 份）。

### 方式二：打包版（v0.0.5，无需 Python）

- 从 GitHub Release 下载 `protein-lab-windows.zip` 或 `protein-lab-macos.zip`，解压后进入 `protein_lab/` 目录，双击 `protein_lab.exe`（Windows）/ 运行 `protein_lab`（macOS）即可。放在**可写目录**（如桌面/下载，不要放 `C:\Program Files`）。
- 打包采用 **onedir 目录形态**（非单文件）：**免启动解压、秒开、杀毒误报低**。
- 后端用生产 WSGI 服务器（waitress）：**启动无"开发服务器"警告、不刷访问日志**，控制台只显示产品 banner。
- 默认端口 **5000**，被占用时自动顺延（5001、5002…）不冲突；需固定端口用 `--port`：
  ```bash
  protein_lab.exe --port 8080
  ```
- 数据库 `protein_lab.db` 与 `backups/` 自动创建在**程序同目录**。首次运行是空库，想带现有数据，用 `--import-db`：
  ```bash
  protein_lab.exe --import-db <旧 protein_lab.db 路径>
  ```
- macOS 首次打开如提示"无法验证开发者"：右键 → 打开；或终端执行 `xattr -d com.apple.quarantine /路径/protein_lab/protein_lab`。

## 打包与发布

- 本地构建（Windows）：`.venv\Scripts\pip install -r requirements-build.txt` → `.venv\Scripts\pyinstaller protein_lab.spec --noconfirm` → 产物在 `dist/protein_lab/` 目录。
- CI 自动构建：**推送 `v*` tag** 时，GitHub Actions 在 `windows-latest` + `macos-latest` 分别构建 Windows / macOS 的 onedir 目录，压缩为 `protein-lab-windows.zip` / `protein-lab-macos.zip` 自动附加到该 tag 的 Release。无需自购 Mac。
- macOS 构建产物在 Mac 上运行，Mac 的 `.venv/bin/python` 同理（路径不同）。

## 配置 MCP（可选）

**方式 A（推荐，打包版）** — 直接用二进制 + `--mcp`：

```json
{
  "mcpServers": {
    "protein-lab": {
      "type": "stdio",
      "command": "C:/路径/protein_lab/protein_lab.exe",
      "args": ["--mcp"]
    }
  }
}
```
macOS 把 command 换成二进制路径（如 `/Applications/protein_lab/protein_lab`）。

**方式 B（源码 + venv）** — 注意用 venv 的 python（MCP 需要 biopython）：

```json
{
  "mcpServers": {
    "protein-lab": {
      "type": "stdio",
      "command": "/路径/protein_lab/.venv/Scripts/python.exe",
      "args": ["/路径/protein_lab/mcp_server.py"]
    }
  }
}
```
macOS 下 venv 路径为 `.venv/bin/python`。

## 目录结构

```
protein_lab/
├── app.py              Flask 主应用（含 --mcp / --import-db 入口分发）
├── calculators.py      计算核心纯函数（MW / ε / 浓度 / 稀释 / 酶活拟合）
├── bli.py              BLI 内核（ForteBio 解析 / 传感器图 / 五方法 KD 拟合）
├── akta.py             AKTA 内核（Unicorn zip 原生解析 / 峰检测 / 峰图 / 峰表，v0.0.9）
├── models.py           SQLite 模型：CRUD + JSON 往返 + schema 迁移框架 + experiment_raw
├── services.py         统一实验写入入口（自动命名 / 校验 / 未来 audit·lineage 插桩点）
├── mcp_server.py       MCP stdio 服务器（读写契约：唯一写工具 save_experiment）
├── paths.py            路径解析（PyInstaller 打包与 dev 双模式）
├── fonts.py            CJK 字体解析 + matplotlib 中文配置
├── protein_lab.spec    PyInstaller 打包配置
├── requirements.txt    运行时依赖
├── requirements-build.txt  打包依赖（pyinstaller）
├── 启动.bat            一键启动（Windows）
├── 启动.command        一键启动（macOS）
├── templates/          Jinja2 页面模板
├── static/             JS + CSS
├── fonts/              Noto Sans SC（OFL，打包进二进制）
├── fixtures/           AKTA 测试样例 zip（git 跟踪，CI 用）
├── .github/workflows/  CI 双平台构建 + 测试步
├── backups/            数据库自动备份（例行 10 份 + 迁移前 pre-migration 5 份）
└── protein_lab.db     自动生成，首次运行创建
```

## 版本历史

| 版本 | 内容 |
|---|---|
| v0.0.1 | 基础蛋白库 / 浓度 + BLI 梯度 / 实验归档 / MCP |
| v0.0.2 | Weblogo / 撤销 / ProtParam / 酶活计算 / 启动自动备份 |
| v0.0.3 | 批量改标签 / 表头排序 / Weblogo 换行 + 区间 + 多聚体 |
| v0.0.4 | PyInstaller **onedir** 打包 / GitHub Actions 双平台构建 / macOS 兼容 / waitress / `--mcp` / `--import-db` |
| v0.0.5 | 浓度单位管理 / 酶活增强（时间点筛选、阴性扣除、速率校正）/ BLI 模块（ForteBio 解析 + 五方法 KD） |
| **架构升级**（2026-08） | 统一写入入口 / 计算纯函数化 / 反序列化收归 models / 校正后端单写 / 实验类型单一来源 |
| **v0.0.7** | **数据存储地基**：schema 迁移框架 / experiment_raw 不可变快照 / 迁移前自动备份 / MCP 读写契约 / CI 测试步 |
| **v0.0.8** | **BLI 原始数据拟合 UI**：ForteBio CSV 上传分析（传感器图 / 5 方法 KD 拟合）/ 保存为实验（raw→experiment_raw `bli_curves`，results 带 `BLI_ANALYSIS_VERSION`）/ 详情页原始快照展示 |
| **v0.0.9** | **AKTA 峰图整理**：`akta.py` 标准库原生解析 Unicorn zip（无 pycorn 依赖）/ 峰检测标注 / 峰表 Excel 导出 / 保存为实验（raw→experiment_raw `akta_traces`，results 带 `AKTA_ANALYSIS_VERSION`）；**BLI 分析增强**（曲线勾选入样 / 单样本拟合 / 默认截去结合起点前基线 / 相界对齐 REF 脚本）；**AKTA 复制恢复 + 参数回填 + Sheet3 多样品作图导出 + 峰图 PNG 下载** |
| **v0.0.10**（当前） | **酶活孔分组 + 作图 Excel 宽格式**：同组孔逐时间点均值曲线 + 误差棒（SD/SEM，图例带 `(n=N)`）；「组」输入框带 datalist 可选已有组 + 多选批量应用；批量命名同名孔自动加 `_1/_2/_3`；作图 Excel 每孔独立时间/OD 两列（BLI/AKTA/酶活统一宽格式）；**评审修复**（undo peek 成功才 pop / renderBliKd 落 DOM / exp_update 列表序列化 / BLI 空窗口守卫） |
| **v0.1.0**（researcher 分支，未发布） | **研究脉络**：证据链 **目标 → 实验 → 结论 → 新目标**；`research_nodes` 表（迁移 v3）+ `research.py` service 层白名单 + 自由挂载逃生舱；实验块引用/计划占位；`/research` 默认首页 + 树/链视图 + 实验引用卡 + 搜索/标签/蛋白筛选；MCP `list_research_trees` / `get_research_node`；`test_research.py` |
