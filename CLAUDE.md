# CLAUDE.md — Protein Lab

本文件为 `protein_lab/` 独立工作区的项目说明。该目录是**独立的 git 仓库**（远程 `QINGMINGMIKU/protein-lab`），与上级 `WeeklyReport/` 研究周报工作区（BME 湿实验 / LaTeX / 简历）**无关**——不要引入那里的上下文或记忆。

## 项目概述

本地蛋白质实验管理系统。Flask 后端 + 纯 SQLite（无 ORM），数据完全本地、离线可用。

**产品定位：Scientific Workbench（不是 Research OS）**——帮助科学家更快从实验数据得到科学结论，而非管理研发活动。中心对象是「数据/分析/证据」，不是「项目/样品/实验管理」。减少认知成本、不增加管理成本（不做 LIMS/ELN/Inventory/Workflow 状态机/全量审计）。**AI 是一等用户**：数据/分析/上下文都要让 AI 不经 UI、通过 MCP 直接拿到且足够结构化可解读。

- **蛋白库**：手动添加 / FASTA 批量导入 / 搜索 / 标签筛选与批量改标签 / 点击表头按 MW、消光系数排序
- **计算工具**（7 个 tab）：
  - 蛋白浓度 — Beer-Lambert（ProtParam 消光系数）
  - BLI 浓度梯度 — 递推稀释 + 统一体积 + 整百取整
  - BLI 分析（v0.0.8）— 上传 ForteBio CSV：传感器图（SG 平滑/拟合虚线/每样本出图）+ 5 方法 KD 拟合 + 保存为实验（原始曲线落 experiment_raw 快照）
  - AKTA 峰图（v0.0.9）— 上传 AKTA Unicorn zip 原生解析（无 pycorn 依赖）：通道列表 + Fraction 事件 → 峰检测/标注/峰表 Excel 导出 → 保存为实验（原始曲线落快照）
  - Weblogo — 勾选蛋白生成序列 logo；长序列自动分块换行（每块 50 位，编号连续）；可选位点区间（start/end，1-based 闭区间）与多聚体裁剪（multimer=N 裁剪为单亚基）；结果按请求参数服务端缓存 + 并发去重，切页回来看别的数据再回来自动恢复（不丢生成结果）
  - 酶活计算 — TECAN xlsx 解析 + 96 孔板 UI + 动力学拟合 + Michaelis-Menten + 阴性扣除
  - 从实验复制 — 历史实验卡片回填
- **实验归档**：一键保存 / Excel 导出 / 详情页（含**原始数据快照表**：experiment_raw 类型/时间/分析版本）/ 批量删除 + 撤销（内存 undo 栈，最多 20 条）
- **MCP 服务器**：`mcp_server.py`，13 个工具，读写契约（唯一写工具 `save_experiment`）+ 结构化错误码（缺参/类型错/语义不满足 → -32602，未知工具 → -32601，内部错误 → -32000）；实验读取工具（get_experiment/get_experiment_raw）递归剔除 sequence 明文（IP 保护兜底）

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
├── calculators.py      计算核心纯函数（MW / ε / 浓度 / 稀释 / 酶活拟合）
├── bli.py              BLI 内核（ForteBio 解析 / 传感器图 / 五方法 KD 拟合，v0.0.6+）
├── akta.py             AKTA 内核（Unicorn zip 原生解析 / 峰检测 / 峰图 / 峰表，v0.0.9）
├── services.py         统一实验写入入口（自动命名/校验/未来 audit·lineage 插桩点）
├── models.py           SQLite 模型：CRUD + JSON 往返 + schema 迁移框架 + experiment_raw
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
├── .github/workflows/  CI 双平台构建 + 测试步
├── backups/            数据库自动备份
└── protein_lab.db     自动生成，首次运行创建
```

## 架构要点

- **分层**：`app.py` 是单体 Flask（页面路由渲染 Jinja2 + `/api/*` JSON 接口 + 内存 undo 栈）；纯计算在 `calculators.py`（无 Flask 依赖，可独立复用）；SQL 全在 `models.py`；`mcp_server.py` 直接 `import models` + `calculators`，**与 Web 共用同一个 `protein_lab.db`**。
- **`models.init_db()` 在 import 时执行**（models.py 末尾）——只要 `import models` 就触碰真实库。测试规范里的 reload 顺序就是为绕过这个副作用而设计。
- **浓度单位 kernel（v0.0.5）**：`calculators.CONC_UNITS` + `convert_concentration(value, from, to, mw)`（canonical 基准 molar→µM、mass→ng/µL，跨 kind 需 mw：`µM × MW/1000 = ng/µL`）——**前端 `static/app.js` 有逐行镜像 `convertConc`/`formatConc`**，改动必须两边同步。计算器工具里浓度只做**显示层换算**（下拉框切单位），存档/详情页/导出仍固定 µM/mg/mL；`calc_conc()` 返回 6 单位。
- **BLI 分析模块 `bli.py`（v0.0.6 地基 + v0.0.8 UI）**：ForteBio CSV 解析（`parse_fortebio_csv`，元数据顺序==列顺序不可重排）→ `group_by_sample`（组内浓度降序）→ 传感器图 `generate_sensorgram_png`（SG 平滑/拟合虚线叠加/separate 模式，返回 PNG bytes）+ KD 内核 `fit_kd`（1:1 Langmuir **5 方法**：standard/split/joint/steady/mixed，+ 死曲线过滤 + NS 非特异扣除）。**绘图样式常量 `COLORS`/`PLOT_STYLE` 从这里抽出**，酶活 `/api/enzyme/plot` 与 AKTA 峰图已复用（函数内惰性 `from bli import ...` 避免模块顶部拖 scipy）。相界缺省走 `_detect_phases` 启发式（平滑后最后局部极大），强一致数据建议显式传 `t_assoc`/`t_dissoc`。`BLI_ANALYSIS_VERSION` 常量随分析版本更新。Web 分析 UI（v0.0.8）：`/api/bli/analyze`（上传→会话缓存）→ `/plot`（传感器图）→ `/fit`（单样本 5 方法）→ `/save`（results 带 version + raw 落库 `bli_curves`）；会话 `_bli_sessions` 内存态（TTL 2h / 上限 10，Lock 保护）。回归测试在 `test_bli.py`（合成 fixture + 隔离临时库）。
- **AKTA 分析模块 `akta.py`（v0.0.9）**：**标准库原生解析 Unicorn zip，无 pycorn 依赖**——外层 zip 的 `Chrom.N_MM_True` 是**嵌套 zip**（非标准结构：EOCD 不在文件尾、带尾部填充），需 `raw.rindex(_ZIP_MAGIC_END)+22` 截断才能被 zipfile 读取；嵌套 zip 内 `CoordinateData.Volumes/Amplitudes` 是 .NET 序列化 float32 数组，**数据从偏移 47 起、每 4 字节一个 float32、跳过尾部 48 字节**（pycorn `unpacker` 逻辑，格式经 REF 真实样例 zip 验证）。通道元数据在 `Chrom.1.Xml` 的 `<Curves><Curve>`（Name/CurveDataType/AmplitudeUnit/CurvePoints→BinaryCurvePointsFileName），事件（Fraction/Injection/Run Log）在 `<EventCurves>`。峰检测 `detect_peaks`：SG 平滑（`_smooth` 纯 numpy 实现）→ 基线取区间 5% 分位数 → scipy `find_peaks`（height + prominence + distance 合并分裂峰）→ 边界走回基线、梯形面积、半高宽。Web API（v0.0.8 同款会话模式）：`/api/akta/analyze|plot|export|save`，save 时 results 带 `AKTA_ANALYSIS_VERSION` + raw 落库 `akta_traces`。回归测试 `test_akta.py`（REF 两个真实 zip）。
- **统一写入入口（架构升级 2026-08）**：`services.create_experiment` 收敛手动/from-calculation/MCP 三条写入路径（自动命名 + 空类型校验 + `coerce_int_list` 静默过滤坏 id）。未来 audit/lineage 的插桩点。`models.EXP_TYPES` 是 exp_type 单一来源，模板下拉/MCP 描述/测试全走常量。
- **数据存储地基（v0.0.7）**：schema 迁移框架——`models.SCHEMA_VERSION` + 有序 `MIGRATIONS`，`_migrate()` 逐条 `BEGIN`→迁移→`PRAGMA user_version=N`→`COMMIT` 原子（**不能 executescript，会隐式提交**）；v1=现有 3 表（老库 no-op）、v2=`experiment_raw`。`experiment_raw`：**只写一次从不 UPDATE**（`exp_save_raw` 重复调用=新行），删实验不删 raw（FK `ON DELETE SET NULL`，规则 #2/#5/#8）。`get_db(read_only=True)` 开 `PRAGMA query_only` 拒写（MCP 只读契约基础设施）。
- **MCP 读写契约（v0.0.7）**：唯一写工具 `save_experiment`；读工具零写库由 `test_models.py` 逐工具断言强制（库内容逐字节不变），**无运行时拦截**——新增读工具必须在测试 `read_cases` 注册。
- **研究脉络模块（v0.1.0）**：`research.py` service 层——证据链 **目标→(拆解)子目标/实验→(得出)结论→(引出)新目标**。数据在 `research_nodes` 表（迁移 v3：node_type/parent_id/title/detail/exp_id/tag/sort_order，`models.research_node_*` CRUD；parent FK 级联删、exp_id FK `ON DELETE SET NULL` 断链保留）。**白名单边在 service 层**（`research.WHITELIST`：goal→{goal,experiment}、experiment→conclusion、conclusion→goal），表层**不做 CHECK** 留 `free_attach` 逃生舱打破；根必须是 goal、多根；`create_node` 失败返 `(None, err)`、`update_node` 失败返 `(False, err)`（注意两者返回形态不同）。`/research` 是**默认首页**（`/` 也指向它，顶层导航第一项）；前端两态：**根目标列表**（默认）→ 点根目标进**单根横向流程图**（左→右流式、同级纵向并联，`researchFlowLayout` DFS 访问序布局 + SVG 肘形连接线按父类型着色，app.js `RES_FLOW`/`RES_FLOW_EDGE` 常量）；API `/api/research/nodes` 增查改删 + 递归子树 + 链（根→节点 breadcrumb）。**MCP 新增 `list_research_trees` / `get_research_node`（读工具，注册 read_cases）**——吸收原 v0.1.1 的 experiment_links（实验块 exp_id 即血缘）。回归 `test_research.py`（白名单/逃生舱/级联删/JSON 往返/断链/排序/API/MCP 零写/页面渲染）。
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
- **迁移前自动备份**：`_migrate()` 在首个未应用迁移前快照 `pre-migration_*.db`（保留 5 份）——app.py 启动备份晚于 import 时迁移，备份到手已是迁移后库，迁移前快照为破坏性迁移留回滚点。
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
- **回归套件**：`test_models.py`（14 节：JSON 往返 / exp_type 单一来源 / 迁移幂等 / raw 只插不更 / read_only 拒写 / MCP 读零写库 / 迁移前备份）+ `test_bli.py`（BLI 解析/绘图/KD + 酶活绘图 + **BLI 分析 API**）+ `test_akta.py`（**AKTA 原生解析/峰检测/峰图 + API**，fixtures/ 真实样例 zip）。CI 构建前自动跑（`MPLBACKEND=Agg`）。

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
- v0.0.4 ✓ 已发布 (2026-08-11) — PyInstaller **onedir** 打包（免解压、秒开、误报低）+ GitHub Actions CI 双平台构建（tag 推送出 Win zip + macOS zip 附到 Release）+ macOS 兼容（打包 Noto Sans SC、`paths.py` 统一路径）+ `--mcp` / `--import-db` + 酶活模块增强（**实验自动命名** `{date}_{type}_{seq:02d}` / 曲线图 PNG 下载 / **作图友好 Excel**（每孔独立时间/OD 列对宽格式）+ 动力学汇总）+ 发布前打磨（Weblogo 服务端缓存+切页自动恢复 / Excel 导出**实验信息独占行**布局 / 详情页兜底修复 / 信息卡表格排版）
- v0.0.5 ✓ 已发布 (2026-08-12) — 浓度单位管理 + 酶活模块增强 + BLI 模块。
  - **浓度单位管理**：`calculators.CONC_UNITS` 与 `convert_concentration` 实现六单位互转，跨摩尔/质量换算需分子量，前端 JS 逐行镜像。蛋白浓度与 BLI 浓度梯度处增加单位下拉框，仅显示层换算，存档仍固定 µM/mg/mL。MCP 新增 `convert_concentration` 工具。
  - **酶活模块增强**：时间点筛选 UI；阴性信号级扣除，图内阴性归零；拟合后速率级校正 `slope_corrected`；拟合虚线锚定曲线首点并优先采用扣阴性后斜率；扣除与对齐解耦；纵轴取整；从实验复制重建时间面板；参考列样品兜底。
  - **BLI 模块**：`bli.py` 统一 ForteBio 解析、传感器图与五方法 KD 拟合内核，`test_bli.py` 为仓库首个回归测试；酶活绘图套用 BLI 样式。
- v0.0.6 ✓ 已发布 (2026-08-13) — 仓库卫生：README 定位重写 + 撤技术报告 + 推送 GitHub
- 架构升级 ✓ (2026-08-13) — 统一写入入口 services / 计算纯函数化（扣减/对齐/取整） / JSON 反序列化收归 models / 速率校正后端单写 / 校正语义修正（背景只扣阴性） / exp_type 单一来源
- v0.0.7 ✓ 已发布 (2026-08-13) — **数据存储地基**：schema 迁移框架（`PRAGMA user_version`）/ `experiment_raw` 不可变快照 / 迁移前自动备份 / MCP 读写契约 / CI 测试步（test_models 14 节 + test_bli）
- v0.0.8 ✓ 已完成 (2026-08-15) — **BLI 原始数据拟合 UI**：`/api/bli/analyze|plot|fit|save` 四端点 + 计算工具「BLI 分析」tab（上传 ForteBio CSV → 样本摘要/参数面板 → 传感器图/每样本图 → 5 方法 KD 表 → 保存实验）。results 带 `BLI_ANALYSIS_VERSION`，raw→`experiment_raw` `data_type=bli_curves`（只写一次）；会话 `_bli_sessions` 内存缓存（TTL 2h/上限 10）；详情页新增原始数据快照表（`exp_raw_list(with_version=True)` 轻量提取版本号）。
- v0.0.9 ✓ 已完成 (2026-08-15) — **AKTA 峰图整理**：`akta.py` 纯函数模块——**标准库原生解析 Unicorn zip（无 pycorn 依赖）**：嵌套 zip `rindex(EOCD)+22` 截断 + float32 偏移 47 起解码（pycorn 逻辑，REF 真实样例 zip 验证）；峰检测（SG 平滑 + 5% 分位基线 + scipy find_peaks height/prominence/distance）；峰图（标注 + Fraction 事件竖线）；峰表 Excel 导出。`/api/akta/analyze|plot|export|save` + 计算工具「AKTA 峰图」tab；results 带 `AKTA_ANALYSIS_VERSION`，raw→`experiment_raw` `data_type=akta_traces`；`test_akta.py` 用 REF 两个真实 zip 回归。
- v0.0.10 ✓ 已发布 (2026-08-16) — **酶活孔分组 + 作图 Excel 宽格式**：`aggregate_groups` 纯函数——同组孔逐时间点取平均（均值曲线 + 误差棒 SD/SEM，图例带 `(n=成员数)`，组内仅 1 孔退化为单孔）；孔位详情面板「组」输入框（datalist 可选已有组，多选孔批量应用）；批量命名同名孔按孔位从左到右、上到下自动加 `_1/_2/_3`；空/错位孔返回 null fit（防 stale R² 标红）；作图 Excel 改宽格式（每孔独立「时间/OD」两列，撞名回落孔位，归档多实验用标题前缀），BLI/AKTA 作图导出复用共享写器 `_write_wide_ws_pairs`。**评审修复**：undo 先 peek 校验成功才 pop（失败保留可重试）/ renderBliKd 返回值落 DOM（KD 表此前不渲染）/ `exp_update` 列表参数序列化 / BLI 空窗口守卫（4 处 IndexError/ValueError）。experiments 列表蛋白列只显示首个 + hover 完整列表、日期/类型列 nowrap。
- v0.1.0 ✓ 已完成 (2026-08-17) — **研究脉络**（research narrative，2026-08-16 拍板重计划）：顶层导航第一项大 Tab（/research 默认首页）——目标→实验→结论→新目标证据链；白名单 + 自由挂载逃生舱（单亲树可重挂）；实验块 = 引用（exp_id）/计划占位；根目标列表 → 单根横向流程图（左→右流式、同级纵向并联）+ 链视图（breadcrumb）+ 实验引用卡 + 搜索/标签/蛋白筛选；结论块按 tag 立场着色（支持=绿/反驳=红/部分=橙/不确定=灰——epistemic status 可视化）；MCP `list_research_trees` / `get_research_node`。**吸收原 v0.1.1 的 experiment_links**（exp_id 即血缘）。明确不做：状态机/全量审计/画布拖拽/项目批次管理。
- v0.1.1 — **从实验自然产生研究脉络（入口生死线，2026-08-17 评价拍板）**：保存实验（Web 归档 / MCP `save_experiment`）时多一步「属于哪个研究目标？」——○已有目标（下拉，研究树 goal 节点）○新建目标 ○暂不关联；`services.create_experiment` 自动挂 Goal→Experiment 节点（exp_id 关联），「暂不关联」零摩擦不建节点。**原则：研究脉络是实验的自然副产物，不是要维护的管理模块**（呼应「四个蛋白不需要 LIMS」）。原轻量谱系 `used_sample_from` 顺延。
- v0.1.2 — MCP 研究上下文 **`get_research_context(goal_id)`**（2026-08-17 评价拍板，取代原 get_variant_context 优先级）：goal 本体 + 父目标链 + 子树实验（归档 metadata/key results）+ 结论（epistemic status + 来源实验）+ 开放目标；注册 read_cases + 序列脱敏。使能 AI 回答「现在在研究什么 / 哪些结论缺实验支持 / 哪些实验互相矛盾 / 目标验证到什么程度」。`get_variant_context` 变体化顺延。
- v0.1.3 — Comparison：WT vs variant 多实验横切对比 + 判断辅助（Workbench 差异化核心）+ `used_sample_from` 采样来源标注
- v0.2.0 — AI 解读层（基于研究上下文判断 candidate 优先级 + **候选结论生成→人类确认**；定位 Research Context 的 AI 消费，**不叫 AI 科学家**）
- **明确不做（defer，2026-08-17 评价拍板）**：DAG / Evidence Graph——单亲树 + `free_attach` 逃生舱 + 多节点引用同一 exp_id 已覆盖「一实验支持多目标 / 一结论来自多实验」的现实场景；真 DAG 的图编辑/环路/排序代价现在付不起。对外命名统一为 **Research Context / Research Trace**，不是 Autonomous Scientist。
- 飞书 bot（支线）— 实验室飞书消息通道 → AI（tool-use）→ protein_lab MCP；**序列脱敏硬约束**；MVP 用现有 13 工具（查蛋白/算浓度/归档），价值在 v0.1.2 `get_research_context` 后显现
- Prism / 出版数据打通（支线，暂缓）— 把 BLI/AKTA 等分析结果导出 `.pzfx`（GraphPad Prism 项目文件，本质 XML/zip），人工在 Prism 里排版出版级图；**明确不做**：无人值守直出版本（用户拍板暂不推进，仅备查）。matplotlib 定位=分析过程即时可视化 + 存档快照，非最终论文图终点。待办先决：数据流打通方案评估（哪个模块导出、如何映射 Prism 数据表）

**设计原则（Workbench 定位）**：
- 减少认知成本、不增加管理成本：拖入数据 → 自动分析 → 给结论，不做项目/批次/审批流。
- **AI 是一等用户**：数据/分析/上下文机器可读，MCP 可拿一切；外部 AI（Claude API/代理）不碰序列明文。
- **序列脱敏（IP 保护）**：序列明文绝不出本地计算边界——所有「序列→数值」（MW/ε/浓度/组成）本地 calculators 算完只给派生物；MCP 返回默认剔除 `sequence` 字段（`_sanitize` 收口），`get_protein` 用 SHA-256 指纹前 12 位替代明文；飞书回复模板禁止输出序列。Weblogo 是唯一明文展示场景（浏览器本地）。
- **明确不做**：LIMS/ELN/Inventory/Workflow 状态机、全量审计、PDB/胶图资产库、决策替代（比较/筛选/看板由工具辅助、不代做判断）。
