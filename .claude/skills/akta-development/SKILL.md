---
name: akta-development
description: 维护和扩展 protein_lab 的 AKTA 分析模块（akta.py + /api/akta/* + 计算工具「AKTA 峰图」tab）。当涉及 AKTA 峰检测/峰图、Unicorn zip 解析、AKTA 实验存档/复制恢复、详情页 AKTA 表格渲染、峰表导出、下载峰图时使用。包含格式逆向要点、数据契约与已踩坑。
---

# AKTA 分析模块开发指南

protein_lab 的 AKTA 工具（v0.0.9+）从「上传 Unicorn zip → 峰图 + 峰表 → 存档」跑通到「从实验复制恢复 + 参数回填 + 多样品导出」。沉淀了格式逆向、数据契约与多入口一致性的经验。改这个模块前先读本指南 + [akta.py](../../../akta.py) 实际代码。

> 姊妹模块 [bli-development](../bli-development/SKILL.md)（BLI 分析）走同一套契约与模式，两端点/会话/判别字段/复制恢复/回填/下载镜像对称。改一侧要评估另一侧。

## 架构地图

```
akta.py       纯函数内核：Unicorn zip 原生解析 / Channel / Peak / detect_peaks / 峰图 PNG（无 Flask 依赖）
app.py        四端点 + 内存会话：analyze → plot → export → save（另加 restore 供复制）
services.py   统一实验写入入口（calc_type 判别字段在此保证）
models.py     experiment_raw 不可变快照（只写一次，删实验不删 raw）
calculator.html + static/app.js   「AKTA 峰图」tab：上传 → 文件/通道列表 → 峰检测参数 → 峰图 → 峰表
templates/experiment_detail.html   详情页 AKTA 峰检测结果卡片 + 原始快照表
test_akta.py  fixtures/ 两个真实 zip 回归
```

- **会话模式**：`_akta_sessions` 内存态（TTL 2h / 上限 10 / Lock 保护），与 BLI `_bli_sessions` 同款。上传只解析一次，前端拿摘要，曲线数据留服务端按需出图。
- **纯函数内核**：`parse_akta_zip` / `detect_peaks` / 绘图都无 Flask 依赖，可独立复用、独立测试。

## Unicorn zip 逆向要点（勿改，除非格式理解更深）

- 外层 zip 的 `Chrom.N_MM_True` 是**嵌套 zip**，非标准结构（EOCD 不在文件尾、带尾部填充）：需 `raw.rindex(_ZIP_MAGIC_END)+22` 截断才能被 zipfile 读取。
- 嵌套 zip 内 `CoordinateData.Volumes/Amplitudes` 是 .NET 序列化 float32 数组：**数据从偏移 47 起、每 4 字节一个 float32、跳过尾部 48 字节**。
- 通道元数据在 `Chrom.1.Xml` 的 `<Curves><Curve>`（Name/CurveDataType/AmplitudeUnit/CurvePoints→BinaryCurvePointsFileName）；事件（Fraction/Injection/Run Log）在 `<EventCurves>`。
- 验证一律走 `test_akta.py` 的 fixtures 真实样例 zip，不要靠猜。

## 数据契约（改动前必须对齐的横切字段）

1. **`calc_type:"akta"` 必须写入 params**——它是详情页渲染、从实验复制、导出的统一判别字段。写入端漏了它，读端所有分支静默失效（详见陷阱 #1）。
2. **results 恒带 `AKTA_ANALYSIS_VERSION`**（规则 #3：分析结果必须记录版本）。
3. **raw → `experiment_raw` `data_type=akta_traces`，只写一次**（规则 #2/#5）。payload 形状：`{analysis_version, params, channel: ch.to_dict(full=True), events, meta}`——注意**只存当前选中通道**的完整 vols/amps，多通道会话存档会丢其他通道（已知取舍，暂够用）。
4. **复制 = 从快照 restore，不重新解析 zip**（规则 #8 可复现）：`GET /api/experiments/<eid>` 附 `_raw_ids` → `GET .../raw/<rid>` 拉 payload → `POST /api/akta/restore` 重建会话。restore 返回形状与 analyze 单 run 一致（`{session_id, runs:[{name, session_id, channels, uv_channels, events, meta}]}`），前端可直接塞进 `aktaRuns`。
5. **复制回填参数**（规则 #8 复现同参数）：复制分支调 `aktaBackfillParams(raw.payload.params)` 把存档的 xmin/xmax/min_height/smooth_window 写回 UI 控件（`aktaXmin`/`aktaXmax`/`aktaMinHeight`/`aktaSmooth`）。**save 只落峰检测参数**，显示类开关（frac 阴影/峰阴影/归一化等）不在 params 内，回填不覆盖。

## 导出 Excel（3 sheet，v0.0.9+）

- **Sheet1 峰表**：当前 run 的峰（峰号/峰位/峰高/面积/起止/半高宽），保留现状。
- **Sheet2 曲线-{channel}**：当前 run 单通道 Volume + Signal，保留现状。
- **Sheet3 作图数据**：**每个勾选 run = 两列** `{样品名} 体积 (mL)` + `{样品名} 信号 ({unit})`，跨 run 并列——直接可选列作图 / 导入 Prism 对比多条色谱。列对各自从第 2 行写起，不强制行对齐（各样品体积轴本就不同，按 X 值作图）。
- 前端 `aktaExport()` 发送 `{...aktaParams(run), runs: [勾选 run 的 {session_id, channel, name}]}`；服务端 `runs` 缺失时回退单 run（兼容旧调用）。`name` 前端去 `.zip`。

## 已知陷阱（每条都是踩过的坑）

1. **calc_type 缺失** → 详情页显示原始 JSON 兜底、复制分支识别不了。修复在统一写入入口补字段，不要在读端兜底。
2. **多入口揭示序列不一致** → `aktaRunList` 在 `#aktaAnalyzed`（默认 `hidden`）内。上传路径和复制路径都必须完整执行「设置 `aktaMeta` → 清 `aktaEventsInfo` → 揭示 `#aktaAnalyzed` → 隐藏 `#aktaPeakTableWrap` → 清 `#aktaPlotArea` → `refreshAktaPlaceholder()`」。改一侧必须同步另一侧（现两处重复，若再长建议抽 `revealAktaAnalyzed()`）。BLI 同款 `#bliAnalyzed`/`bliKdWrap`。
3. **前端字段名以服务端为准**：analyze 端点多文件字段是 `file`（`request.files.getlist("file")`），不是 `zip`。改端点签名要同步 app.js 的 POST。
4. **x 轴标题去下划线**：通道名如 `UV 1_280` 含下划线，横轴统一 `Volume (mL)`，不带通道名。
5. **峰阴影用曲线补色**（`_complement_color` = 255−各通道），不用固定色；背景网格 `ax.grid(True, alpha=0.15)` 是代码自带。
6. **样式常量共享**：`COLORS`/`PLOT_STYLE` 从 bli.py 抽出（11 色面板），AKTA/BLI/酶活三处复用——改配色动 bli.py，别在各模块自建一套。

## 绘图/UI 迭代规范

- 用户给的配色、样式指令是**规范级**的：直接按规范改代码，**不要反复出图确认**（用户明确「没必要看图，只需要代码里面看一下横轴标题规范」）。
- **出图下载**：BLI/AKTA 动作栏有常驻「📥 下载 PNG」按钮 → `downloadAreaImages(areaId, type)` 扫描出图区全部 `<img>`，把 `img.src`（data URL）逐张下载，按 `img.alt` 命名 `{自动名}_{alt}.png`（多图加序号）。新分析模块出图区记得补下载按钮。
- 中文绘图走 `fonts.py` 候选链（打包 Noto Sans SC → dev 回退 simhei → 系统字体）。

## 开发/验证流程

```bash
# 语法 + 回归（必须用 venv python，系统 python 缺 biopython/logomaker）
node --check static/app.js
.venv/Scripts/python.exe test_akta.py      # fixtures 真实 zip 解析/峰检测/峰图 + API
.venv/Scripts/python.exe test_models.py    # 数据契约回归
```

- **端到端验证走 test_client**（`from app import app`，不起真实服务器）。测试库隔离顺序：
  `import models` → `importlib.reload(models)` → `models.DB_PATH=<临时路径>` → `models.init_db()` → `from app import app`。**严禁在生产库上测**。
- 复制链路完整测试序列：analyze（拿 run.session_id）→ save（校验 params.calc_type==akta、`_raw_ids` 出现）→ GET raw（payload.channel 有 vols/amps）→ restore（uv_channels/events 齐全）。fixtures 在 `fixtures/*.zip`。
- 导出验证：POST /api/akta/export（带 runs 列表）→ openpyxl 读回确认 sheet 名/列数/header，作图数据列数 = 样品数×2。
