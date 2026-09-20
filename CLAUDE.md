# CLAUDE.md — Protein Lab

本文件为 `protein_lab/` 独立工作区的项目说明。该目录是**独立的 git 仓库**（远程 `QINGMINGMIKU/protein-lab`），与上级 `WeeklyReport/` 研究周报工作区（BME 湿实验 / LaTeX / 简历）**无关**——不要引入那里的上下文或记忆。

## 项目概述

本地蛋白质实验管理系统。Flask 后端 + 纯 SQLite（无 ORM），数据完全本地、离线可用。

**产品定位：Scientific Workbench（不是 Research OS）**——帮助科学家更快从实验数据得到科学结论，而非管理研发活动。中心对象是「数据/分析/证据」，不是「项目/样品/实验管理」。减少认知成本、不增加管理成本（不做 LIMS/ELN/Inventory/Workflow 状态机/全量审计）。**AI 是一等用户**：数据/分析/上下文都要让 AI 不经 UI、通过 MCP 直接拿到且足够结构化可解读。

- **蛋白库**：手动添加 / FASTA 批量导入 / 搜索 / 标签筛选与批量改标签 / 点击表头按 MW、消光系数排序
- **计算工具**（6 个 tab）：
  - 蛋白浓度 — Beer-Lambert（ProtParam 消光系数）
  - BLI 浓度梯度 — 递推稀释 + 统一体积 + 整百取整
  - BLI 分析（v0.0.8）— 上传 ForteBio CSV：传感器图（SG 平滑/拟合虚线/每样本出图）+ 5 方法 KD 拟合 + 保存为实验（原始曲线落 experiment_raw 快照）
  - AKTA 峰图（v0.0.9）— 上传 AKTA Unicorn zip 原生解析（无 pycorn 依赖）：通道列表 + Fraction 事件 → 峰检测/标注/峰表 Excel 导出 → 保存为实验（原始曲线落快照）
  - Weblogo — 勾选蛋白生成序列 logo；长序列自动分块换行（每块 50 位，编号连续）；可选位点区间（start/end，1-based 闭区间）与多聚体裁剪（multimer=N 裁剪为单亚基）；结果按请求参数服务端缓存 + 并发去重，切页回来看别的数据再回来自动恢复（不丢生成结果）
  - 酶活计算 — TECAN xlsx 解析 + 96 孔板 UI + 动力学拟合 + Michaelis-Menten + 阴性扣除；存档时**原始曲线只落 `experiment_raw`**、手动参数（时间窗/六个作图开关/每孔 mw/源文件名）落 `params`
- **实验归档**（`/experiments`）：一键保存 / Excel 导出 / 详情页（含**原始数据快照表**：experiment_raw 类型/时间/分析版本）/ 批量删除 + 撤销（内存 undo 栈，最多 20 条）。**同时是唯一的实验浏览 + 载入面**（原计算器「从实验复制」tab 已删——浏览实验是档案页的职责，塞在工具页里是概念错位）：客户端搜索（标题 / 关联蛋白，覆盖**最近 100 条**，到顶显式提示）+ 类型过滤；**可载入行的标题直接深链 `/calculator?load_exp=<id>`** 载入对应计算工具（酶活/BLI/AKTA 从**原始快照**重建数据、浓度/稀释读 `params`，均回填存档参数，`/api/*/restore`，见「架构要点」三段式契约），不可载入的（纯记录 / weblogo）回落详情页。**能否载入由 `identity.is_loadable` 单点判定**（详情页 CTA 与列表 API 的 `loadable` 共用同一函数，两处不可能漂移；判定刻意保守：只看 `params.calc_type` 原值、不从 `exp_type` 兜底、raw 只认 `CALC_RAW_TYPES` 白名单）
- **MCP 服务器**：`mcp_server.py`，19 个工具，读写契约（写工具 `save_experiment` + `save_observation` + `save_conclusion` + `attach_goal`）+ 结构化错误码（缺参/类型错/语义不满足 → -32602，未知工具 → -32601，内部错误 → -32000）；实验读取工具（get_experiment/get_experiment_raw）递归剔除 sequence 明文（IP 保护兜底）。`get_system_prompt` 返回 `system_prompt.py` 中的 AI 数据处理工作流指导（数据质量评估 / 计算走工具 / 实验 vs 观察归档边界 / 研究脉络挂载 / 序列脱敏），供外部智能体开始处理实验数据前调用

## 环境

- Python 3.9+，依赖见 `requirements.txt`：`flask` `openpyxl` `biopython` `logomaker`
- **依赖隐患**：`app.py`/`calculators.py` 直接 `import numpy`，weblogo 与酶活绘图还会惰性 `import pandas`/`matplotlib`/`logomaker`——这些都不在 `requirements.txt` 里，靠 logomaker 传递安装。全新建环境只装 requirements.txt 能跑，但别以为它们被显式声明。
- **必须用 venv python**：`.venv/Scripts/python.exe`（Windows）/ `.venv/bin/python`（macOS）。系统 python 缺依赖（biopython、logomaker），跑测试/脚本都要用 venv。
- 前端：Jinja2 + 原生 JS + 手写 CSS，无构建步骤。
- 启动：双击 `启动.bat` / `启动.command`，或 `.venv/Scripts/python app.py`。启动时自动备份数据库到 `backups/`（例行桶保留 10 份，`pre-*` 安全网与手工备份不受轮转影响）。

## 目录结构

```
protein_lab/
├── app.py              Flask 主应用（含 --mcp / --import-db 入口分发）
├── calculators.py      计算核心纯函数（MW / ε / 浓度 / 稀释 / 酶活拟合）
├── bli.py              BLI 内核（ForteBio 解析 / 传感器图 / 五方法 KD 拟合，v0.0.6+）
├── akta.py             AKTA 内核（Unicorn zip 原生解析 / 峰检测 / 峰图 / 峰表，v0.0.9）
├── services.py         统一实验写入入口（自动命名/校验/未来 audit·lineage 插桩点）
├── models.py           SQLite 模型：CRUD + JSON 往返 + schema 迁移框架 + experiment_raw
├── mcp_server.py       MCP stdio 服务器（读写契约：写工具 save_experiment + save_observation + save_conclusion + attach_goal）
├── system_prompt.py    AI 数据处理工作流指导（get_system_prompt 工具的返回内容）
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
├── tools/              仅开发用的一次性脚本（不入包 / 不入 CI），如 backfill_enzyme_raw.py、strip_params_pointdata.py
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
- **实验存储三段式契约（2026-09-16 固化，三模块统一）**：实验数据分三层落库，**不要混**：

  | 层 | 表 | 存什么 | 可变性 |
  |---|---|---|---|
  | 原始数据 | `experiment_raw.payload` | 仪器直接产出（BLI 曲线 / AKTA 通道 / 酶活孔时间序列）+ 存档时的手动参数快照 | **只插不更**（`exp_save_raw` 重复调用=新行；删实验不删 raw，FK `ON DELETE SET NULL`） |
  | 手动处理参数 | `experiments.params` | 人填 + 人选的：浓度 / MW / 分组 / 时间窗 / 作图开关 / 源文件名 | 可变（`resave_experiment` 重挂覆盖） |
  | 派生结果 | `experiments.results` | 拟合 / 峰表 / KD 表等分析产物摘要 | 可变 |

  **`payload` 统一形状**（新增分析型模块必须照此）：
  ```
  {analysis_version, calc_type, params, source_file, <模块自有原始数据键>}
  ```
  `params` = 写库时手动参数的**冻结副本**，是「载入计算工具」回填 UI 的**唯一读取源**（raw 只写一次 → 快照里的手动参数天然不可变）。`source_file` = 源文件名（溯源 / 对照识别）。

  **三条规则**：
  - **A. 逐点数据只在 raw**——`params` 不内嵌 `times/od`（酶活 v2 起；`od_range` 这类极小派生摘要可留，详情页要显示）。违反后果：载入路径读到的是**按时间窗截断后**的 params → 载入再存档**逐代丢点**（酶活实测 exp #41 源 90 点只存 16 点、#33 源 180 点只存 94 点）。
  - **B. `payload.params` 是回填源**——raw payload 必须嵌 `params` 槽；历史 v1 快照无此槽时，`/api/*/restore` 用 payload 里残存的参数合成最小集（酶活用 `time_axis`）。
  - **C. raw 只插不更**——重新分析 = 追加新行；`latestRawId(exp, data_type)` / `_enzyme_raw_wells()` 取**最后一条**（= 当前状态），历史行保留可复现。

  **载入回放三端对称**：BLI `bli_curves` / AKTA `akta_traces` / 酶活 `enzyme_traces` —— 前端 `latestRawId(exp, data_type)` **按类型**取最新快照（重挂可能往同一实验追加别的类型的 raw）→ `GET /api/experiments/<eid>/raw/<rid>` → `POST /api/<模块>/restore` → 重建曲线 + `*BackfillParams()` 回填开关。**浓度 / 稀释 / Weblogo 不适用**（「输入即数据」：params 本身就是全部输入，无独立原始数据）。归档导出要作图数据时同样读 raw（`_enzyme_raw_wells(e)`，取不到回退 `params.wells`）。

  **版本契约**：`analysis_version` 是溯源标签**不是闸门**——restore 遇版本不符**不阻断**，返回 `version_warning` 并原样回放（旧快照仍可用）。`ENZYME_ANALYSIS_VERSION`（`calculators.py`）在 `static/app.js` 有同名镜像常量，改动两边同步（同 `convertConc` 约定）。

  **单位铁律**：`wells[*].times` **规范单位是秒**（`fit_kinetics` 内 `k×60` → ΔOD/min；绘图 `/60` → 分钟轴；导出 `/60` 写 "时间 (min)" 列）。历史 exp #47 是 MCP 手写、`times` 误用**分钟**（`meta.time_unit="min"`），属已知脏数据。**经实测更正（2026-09-16）**：当年 MCP 是**用秒算对了 fit** 的，只把 `times` 存成了分钟——所以**存档 `fit` 本身正确**（用 raw 秒值重拟合，4 孔比值全为 **1.000**、R² 逐位相同），错的只是「从 `params.wells` 重新拟合/出图」这条路径（60× 的值 + 0.49 min 的轴）。此前本文档称「其 fit 偏 60×」是**错的**。该路径已由 `tools/strip_params_pointdata.py` 消掉（`params.wells` 不再有逐点），重拟合/出图现在只可能读 raw（秒）。
  **历史 raw 的契约豁免**：raw#1(akta)/#2(bli)/#3/#4(enzyme) 早于槽位要求，缺 `calc_type`/`source_file`——**raw 只插不更（规则 C），不回填**；读端必须容忍缺失（现状已容忍：`/api/enzyme/restore` 等处用 `get`/`setdefault`）。即「三模块统一」只对新写入的快照成立。
- **MCP 读写契约（v0.0.7 起，v0.1.3+ 扩写面）**：写工具集 `save_experiment`（归档）/ `save_observation`（观察旁注）/ `save_conclusion`（结论，走 research.create_node）/ `attach_goal`（一实验多目标，走 services.attach_goal，幂等：已挂返 already_attached）；读工具零写库由 `test_models.py` 逐工具断言强制（库内容逐字节不变），**无运行时拦截**——新增读工具必须在测试 `read_cases` 注册。
- **研究脉络模块（v0.1.0）**：`research.py` service 层——证据链 **目标→(拆解)子目标/实验→(得出)结论→(引出)新目标**。数据在 `research_nodes` 表（迁移 v3+v4+v5：node_type/parent_id/title/detail/exp_id/tag/sort_order/supporting_exp_ids，`models.research_node_*` CRUD；parent FK 级联删、exp_id FK `ON DELETE SET NULL` 断链保留；`supporting_exp_ids` 是 JSON 文本列，读端 `_node_row` 反序列化；**v5 删 free_attach 列**）。**挂载类型不设约束**（2026-09-18 取消白名单，`research.WHITELIST` 与 `free_attach` 已删——真实形态是「筛选战役(experiment) → N 个候选结果(experiment)」的同类型嵌套，旧白名单把它判成非法），表层**不做 CHECK**；**结构校验是唯一硬约束**：父节点须存在、单亲树、**防环**（`update_node` 沿新父链上溯，取消白名单后它是唯一的硬兜底——成环会让 `_collect_subtree`/删子树死循环、序列化 500）、**根必须是 goal**（`_check_root_type`，多根）；`create_node` 失败返 `(None, err)`、`update_node` 失败返 `(False, err)`（注意两者返回形态不同）。`/research` 是**默认首页**（`/` 也指向它，顶层导航第一项）；前端两态：**根目标列表**（默认）→ 点根目标进**单根横向流程图**（左→右流式、同级纵向并联，`researchFlowLayout` DFS 访问序布局 + SVG 肘形连接线按父类型着色，app.js `RES_FLOW`/`RES_FLOW_EDGE` 常量）；API `/api/research/nodes` 增查改删 + 递归子树 + 链（根→节点 breadcrumb）。**MCP 新增 `list_research_trees` / `get_research_node` / `get_research_context`（读工具，注册 read_cases；`get_research_context`（v0.1.2+v0.1.3）= 研究目标上下文聚合：goal 本体 + 父目标链 + 子树实验 key results + 结论 stance + **支持实验全证据 `supporting_experiments`（多实验→一结论，`_exp_block` 与子树实验同块）+ `observations` 观察/关键细节聚合（parent 上下文）** + 开放目标，数据给全、判断留给 AI）**——吸收原 v0.1.1 的 experiment_links（实验块 exp_id 即血缘）。回归 `test_research.py`（20 节：合法边/任意类型挂载/**生产真实形状钉子**（筛选战役→N 候选结果）/根须 goal/级联删/JSON 往返/断链/排序/API/MCP 零写/上下文聚合/页面渲染/observation/防环/**v5 删列**）。
- **实验 `params`/`results` 可能是双重编码的 JSON 字符串**（历史数据遗留）——读这两个字段要 `while isinstance(val, str): json.loads` 防御性解包（见 `page_experiment_detail`、`_export_excel`）。
- **undo 栈是内存态**（app.py `_undo_stack`，上限 20 条），**重启即失**——这是已知限制（不做持久化回收站/软删除：那要又一次 schema 迁移 + 列表与详情页 UI，与 Workbench「不增加管理成本」定位不符）。**批量删除压一条 `experiments_bulk` 条目**（item 内 `items` 列表），故 `delete-all` 删 9999 条也只占 1 个栈位：此前逐条 `_push_undo` 会因 20 上限**静默挤掉早期条目**，撤销只能回来后 20 条且毫无提示。`/api/undo` 的 `experiments_bulk` 分支逐条重建 + `exp_raw_relink` 重挂旧快照，部分失败时只把**失败的那些**压回栈顶（重试不重复建已恢复的）。单条删除仍走单条路径（前端只对批量/全删给撤销入口）。
- **字体解析（v0.0.4）**：weblogo 与酶活绘图走 `fonts.py` 候选链——打包 Noto Sans SC（`resource_path("fonts/NotoSansSC-Regular.otf")`）→ 旧 dev 回退 `../fonts/simhei.ttf` → Windows 系统字体 → macOS 系统字体，返回第一个存在者。已不依赖上级工作区。
- **测试文件**：`test_bli.py` 是仓库第一个测试（assert 脚本，`.venv/Scripts/python.exe test_bli.py` 直接跑）——bli.py 解析/绘图/KD 回归 + 酶活绘图端点 + 隔离临时库。新增测试照此模式。
- **路径与打包（v0.0.4）**：`paths.py` 统一路径解析——`app_base_dir()` 决定 DB/backups 位置（frozen→EXE 同目录，dev→源码目录），`resource_path()` 读 templates/static/fonts（frozen→`_MEIPASS`）。`models.DB_PATH` 与 Flask `template_folder`/`static_folder` 都走它。中文字体改走 `fonts.py`（打包 Noto Sans SC，OFL 协议，仓库 `fonts/` 内），不再依赖上级工作区。
- **CLI 入口**：同一二进制支持 `--mcp`（stdio MCP，须在 print 前短路避免污染 stdout）与 `--import-db <旧库>`（空库时一次复制迁移）。
- **Web 服务器（v0.0.4）**：main 块用 **waitress**（生产 WSGI，纯 Python 跨平台）`serve()` 替代 Flask 开发服务器——启动无 "development server" 警告、请求日志被 CRITICAL 级别压制，控制台只显示产品 banner。waitress 是 main 块惰性 import，已列入 spec `hiddenimports`。
- **端口（v0.0.4）**：默认 5000，被占用自动顺延找空闲（5000-5049）；`--port <n>` 显式指定（占用则报错退出）。banner / `open_browser` / `serve()` 都用解析出的实际端口。
- **打包配置**：`protein_lab.spec`（**onedir**，console=True，`exclude_binaries` + `COLLECT`）+ `.github/workflows/build.yml`（tag 推送时 Windows/macOS 双平台构建 onedir 目录、zip 后附到 Release）。onedir（非 onefile）免启动解压、杀毒误报低——体积换体验的取舍。注意 `mcp_server`、`fonts`、`paths`、`pandas`、`logomaker`、`matplotlib` 是惰性 import，需在 spec `hiddenimports` 显式声明。

## 数据安全（最高优先级）

- **严禁在生产数据库上测试**：任何涉及删改数据的测试必须用独立临时库或先备份。
- `app.py` 启动时自动将 `protein_lab.db` 备份到 `backups/`，例行桶保留最近 10 份。**备份走 SQLite 在线备份 API**（`models.backup_db_to`）——事务一致，WAL 状态与并发读都不影响；此前「`wal_checkpoint(TRUNCATE)` + `copy2`」的做法在服务运行时遇并发读会 checkpoint busy，**备份静默不含最新写入**。库为 WAL 模式（`models.init_db()` 设一次，持久化在库文件头）；并发安全由 `models.get_db(timeout=30)` 兜底（waitress 4 线程 + MCP 进程互等而非 5s 撞锁）。
- **备份按前缀分桶，各桶由各自的生产者轮转**（2026-09-16 修）：例行桶靠**严格正则** `^protein_lab_\d{8}_\d{6}\.db$` 匹配（`app.py` 的 `ROUTINE_BACKUP_RE`），只删自己生成的文件——`protein_lab_manual_*`（手工复制）与一切 `pre-*` 安全网**永不**被例行轮转碰到。此前按 `.db` 后缀清理，而 `protein_lab_manual_*` 排序在 `protein_lab_2*` 之上（'m' > '2'），占满名额后把 `pre-enzyme-backfill_*` 挤到第 11 位**下次启动即删**。新增备份类型时**必须**在正则上隔离，别共用后缀。
- **迁移前自动备份**：`_migrate()` 在首个未应用迁移前快照 `pre-migration_*.db`（保留 5 份，同样走在线备份 API）——app.py 启动备份晚于 import 时迁移，备份到手已是迁移后库，迁移前快照为破坏性迁移留回滚点。
- 恢复方法：关闭服务 → 从 `backups/` 选一份复制回上级目录改名为 `protein_lab.db` → **删掉同目录残留的 `protein_lab.db-wal` / `protein_lab.db-shm`**（异常退出可能遗留，会让 SQLite 把旧 WAL 重放到刚恢复的库上）→ 重启。

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
- **回归套件**：`test_models.py`（27 节：JSON 往返 / exp_type 单一来源 / 迁移幂等 / raw 只插不更 / read_only 拒写 / MCP 读零写库 / 迁移前备份 / 研究脉络 / **§21 酶活存档契约 v2** / **§25 备份分桶轮转** / **§26 批量删除撤销** / **§27 可载入判定 loadable**）+ `test_bli.py`（BLI 解析/绘图/KD + 酶活绘图 + **BLI 分析 API**）+ `test_akta.py`（**AKTA 原生解析/峰检测/峰图 + API**，fixtures/ 真实样例 zip）+ `test_enzyme.py`（**酶活存档契约 + `/api/enzyme/restore` + 归档导出读 raw + `tools/strip_params_pointdata` 的 fail-closed 防线**）+ `test_research.py` + `test_ui.py`（含**合约源码级断言**：enzymeParams 不得写 times/od、复制兜底须显式提示、**i18n.js 与 i18n.json 逐键同步**、app.js 的 `t()` 字面量键必须存在、**copy tab 不得复活 / 载入引擎与 is*Exp 不得被删**）+ `test_identity.py`。CI 构建前自动跑（`MPLBACKEND=Agg`，见 `.github/workflows/build.yml` 的 Run tests 步——**新增测试文件必须加进该行**）。

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
  - **酶活模块增强**：时间点筛选 UI；阴性信号级扣除，图内阴性归零；拟合后速率级校正 `slope_corrected`；拟合虚线锚定曲线首点并优先采用扣阴性后斜率；扣除与对齐解耦；纵轴取整；载入历史实验重建时间面板；参考列样品兜底。
  - **BLI 模块**：`bli.py` 统一 ForteBio 解析、传感器图与五方法 KD 拟合内核，`test_bli.py` 为仓库首个回归测试；酶活绘图套用 BLI 样式。
- v0.0.6 ✓ 已发布 (2026-08-13) — 仓库卫生：README 定位重写 + 撤技术报告 + 推送 GitHub
- 架构升级 ✓ (2026-08-13) — 统一写入入口 services / 计算纯函数化（扣减/对齐/取整） / JSON 反序列化收归 models / 速率校正后端单写 / 校正语义修正（背景只扣阴性） / exp_type 单一来源
- v0.0.7 ✓ 已发布 (2026-08-13) — **数据存储地基**：schema 迁移框架（`PRAGMA user_version`）/ `experiment_raw` 不可变快照 / 迁移前自动备份 / MCP 读写契约 / CI 测试步（test_models 14 节 + test_bli）
- v0.0.8 ✓ 已完成 (2026-08-15) — **BLI 原始数据拟合 UI**：`/api/bli/analyze|plot|fit|save` 四端点 + 计算工具「BLI 分析」tab（上传 ForteBio CSV → 样本摘要/参数面板 → 传感器图/每样本图 → 5 方法 KD 表 → 保存实验）。results 带 `BLI_ANALYSIS_VERSION`，raw→`experiment_raw` `data_type=bli_curves`（只写一次）；会话 `_bli_sessions` 内存缓存（TTL 2h/上限 10）；详情页新增原始数据快照表（`exp_raw_list(with_version=True)` 轻量提取版本号）。
- v0.0.9 ✓ 已完成 (2026-08-15) — **AKTA 峰图整理**：`akta.py` 纯函数模块——**标准库原生解析 Unicorn zip（无 pycorn 依赖）**：嵌套 zip `rindex(EOCD)+22` 截断 + float32 偏移 47 起解码（pycorn 逻辑，REF 真实样例 zip 验证）；峰检测（SG 平滑 + 5% 分位基线 + scipy find_peaks height/prominence/distance）；峰图（标注 + Fraction 事件竖线）；峰表 Excel 导出。`/api/akta/analyze|plot|export|save` + 计算工具「AKTA 峰图」tab；results 带 `AKTA_ANALYSIS_VERSION`，raw→`experiment_raw` `data_type=akta_traces`；`test_akta.py` 用 REF 两个真实 zip 回归。
- v0.0.10 ✓ 已发布 (2026-08-16) — **酶活孔分组 + 作图 Excel 宽格式**：`aggregate_groups` 纯函数——同组孔逐时间点取平均（均值曲线 + 误差棒 SD/SEM，图例带 `(n=成员数)`，组内仅 1 孔退化为单孔）；孔位详情面板「组」输入框（datalist 可选已有组，多选孔批量应用）；批量命名同名孔按孔位从左到右、上到下自动加 `_1/_2/_3`；空/错位孔返回 null fit（防 stale R² 标红）；作图 Excel 改宽格式（每孔独立「时间/OD」两列，撞名回落孔位，归档多实验用标题前缀），BLI/AKTA 作图导出复用共享写器 `_write_wide_ws_pairs`。**评审修复**：undo 先 peek 校验成功才 pop（失败保留可重试）/ renderBliKd 返回值落 DOM（KD 表此前不渲染）/ `exp_update` 列表参数序列化 / BLI 空窗口守卫（4 处 IndexError/ValueError）。experiments 列表蛋白列只显示首个 + hover 完整列表、日期/类型列 nowrap。
- v0.1.0 ✓ 已完成 (2026-08-17) — **研究脉络**（research narrative，2026-08-16 拍板重计划）：顶层导航第一项大 Tab（/research 默认首页）——目标→实验→结论→新目标证据链；挂载类型不设约束（原「白名单 + 自由挂载逃生舱」**2026-09-18 已整体取消**，见下条；单亲树可重挂）；实验块 = 引用（exp_id）/计划占位；根目标列表 → 单根横向流程图（左→右流式、同级纵向并联）+ 链视图（breadcrumb）+ 实验引用卡 + 搜索/标签/蛋白筛选；结论块按 tag 立场着色（支持=绿/反驳=红/部分=橙/不确定=灰——epistemic status 可视化）；MCP `list_research_trees` / `get_research_node`。**吸收原 v0.1.1 的 experiment_links**（exp_id 即血缘）。明确不做：状态机/全量审计/画布拖拽/项目批次管理。
- v0.1.1 ✓ 已完成 (2026-08-17) — **从实验自然产生研究脉络（入口生死线）**：保存实验（Web 归档 / MCP `save_experiment`）时多一步「属于哪个研究目标？」——○已有目标（下拉，研究树 goal 节点）○新建目标 ○暂不关联；`services.create_experiment` 自动挂 Goal→Experiment 节点（exp_id 关联），「暂不关联」零摩擦不建节点。**原则：研究脉络是实验的自然副产物，不是要维护的管理模块**（呼应「四个蛋白不需要 LIMS」）。同 exp_id 可挂多 goal（`attach_goal` / 详情页「+ 关联到其他目标」）；新建目标 = 根 goal，父级定位后期重挂。Web UI：保存弹窗最简三态（select+input，默认暂不关联）；从-计算存档 3 处共用 `promptGoalAttach` helper；MCP `save_experiment` 加 `goal_id` / `new_goal` 同步支持。失败回滚（节点关联失败 → 删实验，不留孤儿）。原轻量谱系 `used_sample_from` 顺延。
- v0.1.2 ✓ 已完成 (2026-08-18) — MCP 研究上下文 **`get_research_context(goal_id)`**（2026-08-17 评价拍板，取代原 get_variant_context 优先级）：goal 本体 + 父目标链 + 子树实验（归档 metadata/key results，完整 params/results + raw 快照元数据）+ 结论（epistemic status + 来源实验是否归档）+ 开放目标（子树内无结论的目标）；注册两处 read_cases + 序列脱敏（整包 `_strip_sequences`）。使能 AI 回答「现在在研究什么 / 哪些结论缺实验支持 / 哪些实验互相矛盾 / 目标验证到什么程度」。`get_variant_context` 变体化顺延。
- v0.1.3 ✓ 已完成 (2026-08-21) — **证据结构升级（数据/服务/MCP 层，零 UI）**：研究脉络补上真实科研两处结构——**observation 观察/关键细节节点**（叶子旁注，任何节点下可挂研究过程事实/参数，分类 tag：操作要点/文献事实/负结果/参数，不进必选链）+ **结论多实验支持 `supporting_exp_ids`**（多实验→一结论旁路引用：树父实验仍主证据，其余走一等引用；方向恒定实验→结论，结构上不可能成环——比真 DAG 便宜且无环）。迁移 v4（`research_nodes` 加 `supporting_exp_ids` JSON 列，ADD COLUMN 非破坏）。`get_research_context` 聚合扩展：conclusions 带 `supporting_experiments`（`_exp_block` 全证据：params/results/raw 快照）+ 新增 `observations` 聚合 + stats.observations；API 端点透传 supporting_exp_ids。前端零 UI 不动（observation 渲染走泛化兜底，UI 在 v0.1.4）。**明确不做**：通用边表/任意方向边/DAG 图编辑。**2026-09-18 挂载自由化把这处放宽推到底**（白名单整体取消——observation 只是当时的局部放宽）。
- v0.1.4 — 研究脉络 UI：observation 创建/编辑/渲染 + 结论编辑多选支持实验（**在朋友 UI PR 落地后做**，避免做一套被重写）
- ✓ 已完成 (2026-09-16) — **酶活原始数据契约补齐（三段式契约固化，不占版本号）**：修复「载入计算工具」对酶活**有损**（只读 `params.wells` 里被时间窗截断的曲线，raw 从不读 → 载入再存档逐代丢点，实测 #41 源 90 点只存 16 点）。改动：① 固化**三段式契约**（原始数据 raw / 手动参数 params / 派生 results + `payload` 统一形状 + A/B/C 三规则，见「架构要点」，BLI/AKTA 已合规、本次补齐酶活并写死）；② `enzymeParams()` 单点构造手动参数——**六个作图开关 + `mw` + `source_file` 首次落库**（此前全丢），`params.wells` 移除 `times/od` 保留 `od_range`；③ 新增 `/api/enzyme/restore`（v1 旧快照兼容合成 params + 秒值对→网格下标换算，版本不符只警告不阻断）；④ 载入分支改读 raw 全量 + `enzymeBackfillParams()` 回填开关；⑤ `latestRawId(exp, data_type)` 按类型取快照（`_raws` 带 data_type，修「混类型重挂取错快照」）；⑥ 归档导出作图数据改读 raw（`_enzyme_raw_wells`，缺 raw 回退 params 不降级）；⑦ `test_enzyme.py` 新增 + `test_models.py` §21 改写 + `test_ui.py` 合约断言 + CI。**已知脏数据**：历史 #47 由 MCP 手写，`times` 单位误为分钟（应秒），其 fit 偏 60×、出图 x 轴偏 60×；历史 5 条酶活实验的六个开关从未采集，回填后只能走 UI 默认值。
- ✓ 已完成 (2026-09-17) — **实验归档入口收口（删「从实验复制」tab，不占版本号）**：计算器 7 tab → 6 tab，删掉唯一的非工具 tab（浏览实验本就是档案页职责）。① **判定单点化**：`identity.is_loadable(exp, raw_types)` + `identity.CALC_RAW_TYPES` 白名单成为「能否载入计算工具」的唯一源，详情路由（模板 `loadable`）与列表 API（`_attach_loadable` → 每行 `loadable`）共用，**两处不可能漂移**（`test_models.py §27c` 逐实验钉死同真同假）；判定刻意保守——只看 `params.calc_type` 原值（不 normalize、不从 `exp_type` 兜底）、不认 `results`、raw 只认白名单（`experiment_raw.data_type` 是开放集，库里有 `test_trace`）。② **N+1 规避**：`models.exp_raw_type_map(exp_ids, data_types)` 一条 `SELECT DISTINCT`（按 400 分块）代替逐行查 raw；只挂路由不挂 `exp_list`（delete-all / 导出不该为此多花查询）。③ **档案页成为唯一浏览+载入面**：toolbar 补关键词搜索（标题/关联蛋白，覆盖**最近 100 条**——原 tab 搜 100 条，沿用默认 50 会静默缩水一半，到顶显式提示 `archive.search_capped`）；`loadExperiments` 拆成 `loadExperiments` / `expMatchesQuery` / `filterExpList` / `renderExpList`，重绘前后用 `recordCheckedIds` 保勾选，并**顺手修既有 bug**（`updateExpBulkBar()` 在 `loadExperiments()` 里从未被调用，切类型下拉后批量条残留过期计数）。④ **标题点击 = 直载计算工具**（`loadable ? /calculator?load_exp=<id> : /experiments/<id>`，纯 href 零 JS——档案页没有计算器 DOM，`applyCopyAndSwitch` 会去点 `.tab-btn` 而 null 崩），**详情页降为次要入口**（可载入行加第 9 列详情图标，表头 8→9、`colspan` 同步）；`/calculator` 页头补反向链接回档案页。⑤ `isAktaExp`/`isBliExp` 定义在被删区间内、但保留的 `applyCopyAndSwitch`（1561/1594）仍在调——**先挖出再删**，否则 ReferenceError 打断载入（`test_ui.py` 源码级断言钉住）。i18n 删 19 键（原估 17，漏数 `copy.filter.*` 的 8 个）/ 增 2 键，四份手工同步。
- ✓ 已完成 (2026-09-18) — **研究脉络挂载自由化（取消白名单 + 删 `free_attach`，不占版本号）**：① **白名单整体取消**（`research.WHITELIST` 删除，任何类型可挂任何父节点）——直接来由是生产实际形态「筛选战役(experiment) → N 个候选结果(experiment)」被旧白名单判成非法（node 43→44，只能勾「自由挂载」才建成）；34 节点里 2 个带标记、其中 1 个（id=4 `goal→experiment`）本就合法 = **废标记**，说明设定已在空转。② **结构校验升格为唯一硬约束**：父节点须存在、单亲树、防环（`update_node` 沿新父链上溯）、**根仍须 goal**（`_check_new_edge` 收窄改名 `_check_root_type`）——无类型约束的单亲树仍不是 DAG，不触碰「明确不做：通用 DAG」。③ **`free_attach` 走迁移 v5 `DROP COLUMN`**（`_migrate_v5_post` 照抄 v1 删 `protein_id` 的既有模式：列在不在→幂等；SQLite ≥3.35 才删，否则跳过留无害残留）：**删列本身即「移除数据中原有标记」**，还白拿迁移框架的原子性 + `pre-migration_*.db` 快照 + 版本可追溯——**不写单独脚本**；结构列一列不动，已实测迁移前后 34 行 × 9 结构列 + 拓扑指纹逐行一致。④ 前端删 3 处渲染（`lf-free` 徽章 / `free-attach` 虚线 / `res-free` 徽章）+ 1 处 checkbox + 2 处 PUT 载荷 + i18n 2 键（四份）+ CSS 4 处；`researchFirstAllowed`（白名单前端镜像）删除，**新增子节点默认继承父节点类型**（筛选战役下加候选结果即同类型嵌套），加根默认 goal。⑤ 顺带根除 MCP 潜伏 bug `bool("false") is True`（删参即根除）。⑥ 测试：`test_research.py` 4 节反转 + **新增生产真实形状钉子**（goal→experiment→experiment×N）+ §20 v5 删列断言；`test_models.py`/`test_ui.py` 零改动。**未使用观察**：`supporting_exp_ids` 现网 34 行全为 `[]`——v0.1.3 的多实验旁路引用实际未被使用，值得单独复盘（不属本次）。
- v0.1.5 — Comparison：WT vs variant 多实验横切对比 + 判断辅助（Workbench 差异化核心）+ `used_sample_from` 采样来源标注
- v0.2.0 — AI 解读层（基于研究上下文判断 candidate 优先级 + **候选结论生成→人类确认**；定位 Research Context 的 AI 消费，**不叫 AI 科学家**）
- **明确不做（defer，2026-08-17 拍板，2026-08-21 窄修订）**：通用 DAG / Evidence Graph——「一实验支持多目标」由多节点引用同一 exp_id 覆盖、「一结论来自多实验」由 v0.1.3 `supporting_exp_ids` 旁路引用覆盖（方向恒定、结构上无环，不付 DAG 的图编辑/环路/排序代价）；仍不做：任意两点任意方向的通用边表。对外命名统一为 **Research Context / Research Trace**，不是 Autonomous Scientist。
- 飞书 bot（支线）— 实验室飞书消息通道 → AI（tool-use）→ protein_lab MCP；**序列脱敏硬约束**；MVP 用现有 13 工具（查蛋白/算浓度/归档），价值在 v0.1.2 `get_research_context` 后显现
- Prism / 出版数据打通（支线，暂缓）— 把 BLI/AKTA 等分析结果导出 `.pzfx`（GraphPad Prism 项目文件，本质 XML/zip），人工在 Prism 里排版出版级图；**明确不做**：无人值守直出版本（用户拍板暂不推进，仅备查）。matplotlib 定位=分析过程即时可视化 + 存档快照，非最终论文图终点。待办先决：数据流打通方案评估（哪个模块导出、如何映射 Prism 数据表）

**设计原则（Workbench 定位）**：
- 减少认知成本、不增加管理成本：拖入数据 → 自动分析 → 给结论，不做项目/批次/审批流。
- **AI 是一等用户**：数据/分析/上下文机器可读，MCP 可拿一切；外部 AI（Claude API/代理）不碰序列明文。
- **序列脱敏（IP 保护）**：序列明文绝不出本地计算边界——所有「序列→数值」（MW/ε/浓度/组成）本地 calculators 算完只给派生物；MCP 返回默认剔除 `sequence` 字段（`_sanitize` 收口），`get_protein` 用 SHA-256 指纹前 12 位替代明文；飞书回复模板禁止输出序列。Weblogo 是唯一明文展示场景（浏览器本地）。
- **明确不做**：LIMS/ELN/Inventory/Workflow 状态机、全量审计、PDB/胶图资产库、决策替代（比较/筛选/看板由工具辅助、不代做判断）。
