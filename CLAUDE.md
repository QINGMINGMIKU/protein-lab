# CLAUDE.md — Protein Lab

本文件为 `protein_lab/` 独立工作区的项目说明。该目录是**独立的 git 仓库**（远程 `QINGMINGMIKU/protein-lab`），与上级 `WeeklyReport/` 研究周报工作区（BME 湿实验 / LaTeX / 简历）**无关**——不要引入那里的上下文或记忆。

## 项目概述

本地蛋白质实验管理系统。Flask 后端 + 纯 SQLite（无 ORM），数据完全本地、离线可用。

- **蛋白库**：手动添加 / FASTA 批量导入 / 搜索 / 标签筛选与批量改标签 / 点击表头按 MW、消光系数排序
- **计算工具**（5 个 tab）：
  - 蛋白浓度 — Beer-Lambert（ProtParam 消光系数）
  - BLI 浓度梯度 — 递推稀释 + 统一体积 + 整百取整
  - Weblogo — 勾选蛋白生成序列 logo；长序列自动分块换行（每块 50 位，编号连续）；可选位点区间（start/end，1-based 闭区间）与多聚体裁剪（multimer=N 裁剪为单亚基）；结果按请求参数服务端缓存 + 并发去重，切页回来看别的数据再回来自动恢复（不丢生成结果）
  - 酶活计算 — TECAN xlsx 解析 + 96 孔板 UI + 动力学拟合 + Michaelis-Menten + 阴性扣除
  - 从实验复制 — 历史实验卡片回填
- **实验归档**：一键保存 / Excel 导出 / 详情页 / 批量删除 + 撤销（内存 undo 栈，最多 20 条）
- **MCP 服务器**：`mcp_server.py`，7 个工具

## 环境

- Python 3.9+，依赖见 `requirements.txt`：`flask` `openpyxl` `biopython` `logomaker`
- **依赖隐患**：`app.py`/`calculators.py` 直接 `import numpy`，weblogo 与酶活绘图还会惰性 `import pandas`/`matplotlib`/`logomaker`——这些都不在 `requirements.txt` 里，靠 logomaker 传递安装。全新建环境只装 requirements.txt 能跑，但别以为它们被显式声明。
- **必须用 venv python**：`.venv/Scripts/python.exe`（Windows）/ `.venv/bin/python`（macOS）。系统 python 缺依赖（biopython、logomaker），跑测试/脚本都要用 venv。
- 前端：Jinja2 + 原生 JS + 手写 CSS，无构建步骤。
- 启动：双击 `启动.bat` / `启动.command`，或 `.venv/Scripts/python app.py`。启动时自动备份数据库到 `backups/`（保留 10 份）。

## 目录结构

```
protein_lab/
├── app.py              Flask 主应用（含 --mcp / --import-db 入口分发）
├── calculators.py      计算核心（MW / ε / 浓度 / 稀释 / 酶活拟合）
├── models.py           SQLite 数据模型（DB 路径走 paths.app_base_dir()）
├── mcp_server.py       MCP stdio 服务器
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
├── .github/workflows/  CI 双平台构建
├── backups/            数据库自动备份
└── protein_lab.db     自动生成，首次运行创建
```

## 架构要点

- **分层**：`app.py` 是单体 Flask（页面路由渲染 Jinja2 + `/api/*` JSON 接口 + 内存 undo 栈）；纯计算在 `calculators.py`（无 Flask 依赖，可独立复用）；SQL 全在 `models.py`；`mcp_server.py` 直接 `import models` + `calculators`，**与 Web 共用同一个 `protein_lab.db`**。
- **`models.init_db()` 在 import 时执行**（models.py 末尾）——只要 `import models` 就触碰真实库。测试规范里的 reload 顺序就是为绕过这个副作用而设计。
- **浓度单位 kernel（v0.0.5）**：`calculators.CONC_UNITS` + `convert_concentration(value, from, to, mw)`（canonical 基准 molar→µM、mass→ng/µL，跨 kind 需 mw：`µM × MW/1000 = ng/µL`）——**前端 `static/app.js` 有逐行镜像 `convertConc`/`formatConc`**，改动必须两边同步。计算器工具里浓度只做**显示层换算**（下拉框切单位），存档/详情页/导出仍固定 µM/mg/mL；`calc_conc()` 返回 6 单位。
- **BLI 分析模块 `bli.py`（v0.0.6 地基）**：ForteBio CSV 解析（`parse_fortebio_csv`，元数据顺序==列顺序不可重排）→ `group_by_sample`（组内浓度降序）→ 传感器图 `generate_sensorgram_png`（SG 平滑/拟合虚线叠加/separate 模式，返回 PNG bytes）+ KD 内核 `fit_kd`（1:1 Langmuir **5 方法**：standard/split/joint/steady/mixed，+ 死曲线过滤 + NS 非特异扣除）。**绘图样式常量 `COLORS`/`PLOT_STYLE` 从这里抽出**，酶活 `/api/enzyme/plot` 已复用（函数内惰性 `from bli import ...` 避免模块顶部拖 scipy）。相界缺省走 `_detect_phases` 启发式（平滑后最后局部极大），强一致数据建议显式传 `t_assoc`/`t_dissoc`。回归测试在 `test_bli.py`（合成 fixture + 隔离临时库）。
- **实验 `params`/`results` 可能是双重编码的 JSON 字符串**（历史数据遗留）——读这两个字段要 `while isinstance(val, str): json.loads` 防御性解包（见 `page_experiment_detail`、`_export_excel`）。
- **undo 栈是内存态**（app.py `_undo_stack`，上限 20 条），重启即失。
- **字体解析（v0.0.4）**：weblogo 与酶活绘图走 `fonts.py` 候选链——打包 Noto Sans SC（`resource_path("fonts/NotoSansSC-Regular.otf")`）→ 旧 dev 回退 `../fonts/simhei.ttf` → Windows 系统字体 → macOS 系统字体，返回第一个存在者。已不依赖上级工作区。
- **测试文件**：`test_bli.py` 是仓库第一个测试（assert 脚本，`.venv/Scripts/python.exe test_bli.py` 直接跑）——bli.py 解析/绘图/KD 回归 + 酶活绘图端点 + 隔离临时库。新增测试照此模式。
- **路径与打包（v0.0.4）**：`paths.py` 统一路径解析——`app_base_dir()` 决定 DB/backups 位置（frozen→EXE 同目录，dev→源码目录），`resource_path()` 读 templates/static/fonts（frozen→`_MEIPASS`）。`models.DB_PATH` 与 Flask `template_folder`/`static_folder` 都走它。中文字体改走 `fonts.py`（打包 Noto Sans SC，OFL 协议，仓库 `fonts/` 内），不再依赖上级工作区。
- **CLI 入口**：同一二进制支持 `--mcp`（stdio MCP，须在 print 前短路避免污染 stdout）与 `--import-db <旧库>`（空库时一次复制迁移）。
- **Web 服务器（v0.0.4）**：main 块用 **waitress**（生产 WSGI，纯 Python 跨平台）`serve()` 替代 Flask 开发服务器——启动无 "development server" 警告、请求日志被 CRITICAL 级别压制，控制台只显示产品 banner。waitress 是 main 块惰性 import，已列入 spec `hiddenimports`。
- **端口（v0.0.4）**：默认 5000，被占用自动顺延找空闲（5000-5049）；`--port <n>` 显式指定（占用则报错退出）。banner / `open_browser` / `serve()` 都用解析出的实际端口。
- **打包配置**：`protein_lab.spec`（**onedir**，console=True，`exclude_binaries` + `COLLECT`）+ `.github/workflows/build.yml`（tag 推送时 Windows/macOS 双平台构建 onedir 目录、zip 后附到 Release）。onedir（非 onefile）免启动解压、杀毒误报低——体积换体验的取舍。注意 `mcp_server`、`fonts`、`paths`、`pandas`、`logomaker`、`matplotlib` 是惰性 import，需在 spec `hiddenimports` 显式声明。

## 数据安全（最高优先级）

- **严禁在生产数据库上测试**：任何涉及删改数据的测试必须用独立临时库或先备份。
- `app.py` 启动时自动将 `protein_lab.db` 复制到 `backups/`，保留最近 10 份。
- 恢复方法：关闭服务 → 从 `backups/` 选一份复制回上级目录改名为 `protein_lab.db` → 重启。

## 测试规范

- 测试用 `from app import app; app.test_client()`，不起真实服务器。
- 数据库隔离（**顺序很关键，不能乱**）：
  1. `import models`
  2. `importlib.reload(models)` — ⚠️ 会把 `models.DB_PATH` 重置为真实路径
  3. `models.DB_PATH = <临时路径或 ':memory:'>`
  4. `models.init_db()`
  5. `from app import app`
- 若必须用正式库，测试前先手动备份 `protein_lab.db`。
- 跑测试一律用 `.venv/Scripts/python.exe`（系统 python 缺依赖）。

## 发布纪律

- **不要擅自 push 或发布 release**，等用户明确说"发布"再做。
- 本地 commit 随意，不影响远程。

## Claude Code 运行注意

- **Bash 工作目录不可靠**（会重置到上级目录）：执行涉及文件的操作前先 `cd /c/WorkSpace/WeeklyReport/protein_lab && ...`，或使用绝对路径，否则相对路径（如 `rm -f`）会静默失效。
- 内置 `/code-review` 在本环境（deepseek 代理）下会卡死——卡住时改用手动内联评审。
- 记忆走本工作区自己的 `.claude/` 内存（project key 与 WeeklyReport 不同），不会串数据。

## MCP

- MCP 服务器依赖 biopython，`.mcp.json` 的 command 必须指向 venv python（本目录自带 `.mcp.json`，仅含 protein-lab，不含上级的 zotero）。
- 独立工作区打开时读本目录的 `.mcp.json`，上级配置不会生效。

## 版本路线

- v0.0.1 ✓ 已发布 — 基础蛋白库 / 浓度+BLI / 实验归档 / MCP
- v0.0.2 ✓ 已发布 (2026-08-09) — Weblogo / 撤销 / ProtParam / 酶活计算 / 启动自动备份
- v0.0.3 ✓ 已发布 (2026-08-10) — 批量改标签 / 表头排序 / Weblogo 换行+区间+多聚体
- v0.0.4 ✓ 已发布 (2026-08-11) — PyInstaller **onedir** 打包（免解压、秒开、误报低）+ GitHub Actions CI 双平台构建（tag 推送出 Win zip + macOS zip 附到 Release）+ macOS 兼容（打包 Noto Sans SC、`paths.py` 统一路径）+ `--mcp` / `--import-db` + 酶活模块增强（**实验自动命名** `{date}_{type}_{seq:02d}` / 曲线图 PNG 下载 / **作图友好 Excel** 孔位-时间-OD 长格式 + 动力学汇总）+ 发布前打磨（Weblogo 服务端缓存+切页自动恢复 / Excel 导出**实验信息独占行**布局 / 详情页兜底修复 / 信息卡表格排版）
- v0.0.5 — **浓度单位管理**（隐藏换算 kernel + 浓度计算处单位切换）：`calculators.CONC_UNITS` + `convert_concentration`（6 单位 M/uM/nM/mg/mL/ug/mL/ng/uL 互转，跨摩尔/质量需 mw，前端 JS 逐行镜像 `convertConc`/`formatConc`）；蛋白浓度 + BLI 浓度梯度 tab 各加**浓度单位下拉框**（仅显示层换算，存档仍 µM/mg/mL，默认 uM 与现状一致）；MCP 新增 `convert_concentration` 工具。后续可做：存档/详情页单位显示、enzyme 输入扩 6 单位
- v0.0.6 — BLI 原始数据拟合 + 多步稀释管理（**模块地基已铺好**：`bli.py` 统一 ForteBio 解析 + 传感器图 + 五方法 KD 内核 + `test_bli.py` 回归；UI 上传/参数面板/存档待接）
- v0.0.7 — AKTA 峰图整理
- v0.1.0（暂缓）— 连续实验管理（浓度→稀释→BLI/酶活串联工作流）
- v0.2.0（规划）— **蛋白研发工作台**（骨架=蛋白档案，记忆=知识沉淀，血肉=小工具）。**明确不做：PDB/胶图资产库**——企业/客户交付平台向（可追溯、可演示），小作坊实验室自己跑数据自己看，价值低；轻量版=蛋白页列出关联实验（含 SDS-PAGE 类型）即可：
  - **蛋白档案页**（`/proteins/<id>`）：变体系族归类（`1YPI_WT` / `1YPI_32|ppl=1.111` 按命名/标签归组）、关联实验时间线、指标趋势（历次浓度/BLI/酶活叠看走势）、协议记忆入口
  - **实验知识沉淀**：蛋白成功方案自动记录，开始实验时自动提示（如 PD1 禁冻、60 mM imidazole、16-18°C 低温诱导）
  - **妙妙小工具**：多曲线叠画对比（酶活 time-OD 勾选多孔/多实验 + 标 ΔOD/min 线性区）；图片标注峰/转折点（MM 标 Vmax/Km、AKTA 峰检测标注）；归档后变量重命名（孔位/样本显示名写回，导出/对比用新名）

**设计原则**：减少 dirtywork（机械操作），不做决策替代（比较/筛选/看板）。
