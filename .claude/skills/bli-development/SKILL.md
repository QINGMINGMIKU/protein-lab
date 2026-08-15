---
name: bli-development
description: 维护和扩展 protein_lab 的 BLI 分析模块（bli.py + /api/bli/* + 计算工具「BLI 分析」tab）。当涉及 ForteBio CSV 解析、传感器图、KD 拟合、BLI 实验存档/复制恢复/参数回填、详情页 BLI 表格渲染、下载传感器图时使用。包含数据契约与已踩坑。
---

# BLI 分析模块开发指南

protein_lab 的 BLI 工具（v0.0.6 内核 + v0.0.8 UI）从「上传 ForteBio CSV → 传感器图 + KD 表」跑通到「存档 + 从实验复制恢复 + 参数回填 + 下载」。走与 AKTA 同款的数据契约与多入口模式。改这个模块前先读本指南 + [bli.py](../../../bli.py) 实际代码。

> 姊妹模块 [akta-development](../akta-development/SKILL.md)（AKTA 峰图）走同一套契约与模式，两端点/会话/判别字段/复制恢复/回填/下载镜像对称。改一侧要评估另一侧。

## 架构地图

```
bli.py       纯函数内核：parse_fortebio_csv / group_by_sample / generate_sensorgram_png / fit_kd
             （+ COLORS/PLOT_STYLE 样式常量本尊 + BLI_ANALYSIS_VERSION，无 Flask 依赖）
app.py       六端点 + 内存会话：analyze → plot → fit → save（另加 restore 供复制、export 导出 Excel）
services.py  统一实验写入入口（calc_type 判别字段在此保证）
models.py    experiment_raw 不可变快照（只写一次，删实验不删 raw）
calculator.html + static/app.js   「BLI 分析」tab：上传 → 样本摘要/参数面板 → 传感器图 → 5 方法 KD 表
templates/experiment_detail.html   详情页 BLI 拟合卡片 + 原始快照表
test_bli.py  合成 fixture + 隔离临时库回归
```

- **会话模式**：`_bli_sessions` 内存态（TTL 2h / 上限 10 / Lock 保护，超量丢最旧），存的是**曲线 dict 列表**（`_bli_curve_to_dict` 序列化）。上传只解析一次，前端拿摘要，曲线数据留服务端按需出图/拟合。
- **纯函数内核**：解析/分组/绘图/拟合全无 Flask 依赖，可独立复用、独立测试。

## 内核要点

- **ForteBio 元数据顺序 == 列顺序，不可重排**——`parse_fortebio_csv` 依赖表头顺序解析浓度/样品/时间/响应。
- **`group_by_sample`**：按 sample 分组，组内浓度降序。
- **`generate_sensorgram_png`**：SG 平滑（`smooth_window`）→ 拟合虚线叠加 → `separate=True` 每 sample 一图。返回 PNG bytes（多图时返回 dict）。
- **`fit_kd`**：1:1 Langmuir **5 方法**（standard/split/joint/steady/mixed）+ 死曲线过滤 + NS 非特异扣除（`ns_sensor`/`ns_subtract`）。
- **相界缺省**走 `_detect_phases`（**对齐 REF 脚本 generate_BLI_figure.py / fit_KD.py**）：t_dissoc = **平滑后最高浓度曲线 argmax**（REF 用原始 argmax，这里平滑防抖）；t_assoc = 平滑曲线首超 **基线+5σ** 处（REF 默认数据起点，这里检测真实结合起点，让 trim_start 默认截基线有意义）。**强一致数据仍建议显式传 `t_assoc`/`t_dissoc`**。
- **曲线级过滤**：`_bli_filter_curves(curves, active_curves)` 按曲线 label 过滤（None=全保留，[]=一条不剩），在 API 层统一应用——plot/fit/save/export 四端点都收 `active_curves`。`_bli_trim_curves(curves, t_assoc)` 截去结合起点前基线。
- **trim_start（默认开）**：四端点收 `trim_start`（默认 True）→ 若未显式传 ta/td 先在**原始曲线**上 `_detect_phases` 解析绝对相界，再按 ta 截去之前的数据。出图/拟合/导出/存档都基于截后曲线；raw 快照仍存全量。

## 数据契约（改动前必须对齐的横切字段）

1. **`calc_type:"bli_fit"` 必须写入 params**——它是详情页渲染、从实验复制、导出的统一判别字段。**BLI 的坑比 AKTA 深**：浓度梯度实验也共享 `exp_type="BLI"`（但 calc_type="dilution"），判别顺序必须「先算 calc_type，dilution 显式排除」再落旧格式兜底（详见陷阱 #1）。
2. **results 恒带 `BLI_ANALYSIS_VERSION`**（规则 #3）+ `params` + `samples`（逐 sample 的 5 方法拟合结果 dict，失败为 `{"error": ...}`）。params 额外记 `active_curves`（进入数据的曲线 label，None=全选）与 `trim_start`（是否截去结合起点前基线）——供复制回填复现当时的曲线选择/截断。
3. **raw → `experiment_raw` `data_type=bli_curves`，只写一次**（规则 #2/#5）。payload 形状：
   ```python
   {"analysis_version": BLI_ANALYSIS_VERSION, "params": params,
    "curves": [{"label","sample_id","conc_nM","time","response"} ...]}
   ```
   save 端点里用 `_json_safe` 先清 NaN/Inf（float 曲线值），否则 `json.dumps` 产出非法 JSON。
4. **复制 = 从快照 restore，不重新解析 CSV**（规则 #8 可复现）：`POST /api/bli/restore`，body `{"payload": {"curves": [...]}}` → 重建会话。返回形状与 `/api/bli/analyze` 一致（`{session_id, samples, n_sensors}`），前端可直接复用上传路径状态。
5. **复制回填参数**（规则 #8 复现同参数）：复制分支调 `bliBackfillParams(raw.payload.params)` 把存档的 `smooth_window/n_concs/t_assoc/t_dissoc/ns_sensor/fit_overlay/no_cutoff/trim_start` 写回控件（`bliSmooth`/`bliNConcs`/`bliTAssoc`/`bliTDissoc`[null→""]/`bliNsSensor`/`bliFit`/`bliNoCutoff`/`bliTrimStart`），`active_curves` 子集重建 `bliActiveCurves` Set 并 `renderBliCurves()` 同步勾选——复制后未勾选的曲线默认也排除。**在 `bliParams()` 之前调用**。save 只落分析参数，显示类开关（separate/view/mask）不在 params 内，回填不覆盖。
6. **save 由后端重算**：前端展示过的图/表参数只是展示，save 端点按提交 params 重新 `fit_kd` 逐 sample 计算落库，保证「所见即所得」且可复现。

## 导出 Excel（2 sheet，对标 AKTA）

- **Sheet1「KD 汇总」**：每样品一行 × 5 方法 KD + 备注。取值约定与拟合面板一致——standard/split/joint/steady 取 `kd`；mixed 无单值 kd，**稳态优先**（`kd_steady_mixed`）否则动力学（`kd_kinetic_mixed`），备注标注；拟合失败写 "—"+ 备注。
- **Sheet2「作图数据」**：**每条传感器曲线 = 两列** `{label} 时间 (s)` + `{label} 响应 (nm)`，Prism 可直接画传感器图；label 撞名时拼 `sample_id` 去重。时间列各自从第 2 行写起，不强制行对齐。**trim_start 默认开 → 时间从 t_assoc 起、行数减少**。
- 前端 `bliExport()` 发送 `bliParams()`（session_id + 拟合参数 + active_curves/trim_start）；服务端按 active_curves 过滤 + trim 后 `fit_kd` 逐 sample 重算（同 save 契约）。`test_bli.py` 7f（trim 行数/首点）/7g（active_curves 子集列数、空勾选 400）/7h（trim 关全长）回归。

## 已知陷阱（每条都是踩过的坑）

1. **dilution 混入 BLI 判定** → 浓度梯度实验 `exp_type` 也是 "BLI"。`isBliExp(e)` 判别顺序：`calc_type==="bli_fit"` → `calc_type==="dilution"` 显式 return false → 旧格式（无 calc_type）才靠 `exp_type` 含 "BLI" **且 `results.samples` 存在**。缺任一步都会把浓度梯度误判成 BLI 分析。写入端漏 calc_type = 详情页/复制全静默失效（AKTA 陷阱 #1 同款）。
2. **多入口揭示序列不一致** → 上传路径和复制路径都必须完整执行「reveal `#bliAnalyzed` → hide `#bliKdWrap` → 清 `#bliPlotArea` → `refreshBliPlaceholder()`」→ switch tab → `bliPlot()`。改一侧必须同步另一侧。AKTA 同款 `#aktaAnalyzed`/`#aktaPeakTableWrap`。
3. **前端字段名以服务端为准**：analyze 的文件字段是 `file`（`request.files["file"]`），save 的判别参数是 `fit_overlay`（兼容前端老 `fit`）；后端做 `bool(body.get("fit_overlay") or body.get("fit"))`。改端点签名要同步 app.js 的 POST。
4. **相界不要依赖启发式**：`_detect_phases` 只对强一致数据可靠，明显 assoc/dissoc 相界应在参数面板显式输入，save 也会把 t_assoc/t_dissoc 落 params。
5. **样式常量本尊在 bli.py**：`COLORS`/`PLOT_STYLE`（11 色面板）在 bli.py 定义，AKTA/酶活惰性 `from bli import ...` 复用——改配色动 bli.py，别在各模块自建一套。
6. **空/坏会话兜底**：plot/fit/save 端点先 `_bli_get_session`，会话不存在（TTL 2h 过期/重启）返回「会话不存在或已过期，请重新上传」——前端复制恢复的 restore 分支天然规避这个（永远重新建会话）。

## 绘图/UI 迭代规范

- **批量操作流（对齐 AKTA）**：动作栏 = 出图模式下拉（总图/分图）+「🖼 出图」+「🧪 拟合选中样本」+「📊 导出 Excel」+「📥 下载 PNG」。**出图模式 select 替代双按钮**（`bliPlot()` 读 `#bliPlotMode` 传 `separate`，分图时渲染 `r.images` dict）；**拟合是单样本按钮**——`bliFitSelected()` POST /api/bli/fit 拟合当前 `bliSelectedSample`，结果存 `bliKdResult`，`renderBliKd()` 渲染一张卡片；样本行按钮切换选中样本并触发重拟合。**曲线勾选列表**（`#bliCurveList` 每曲线一复选框 + `#bliCurveSelectAll` 总复选三态 + `#bliCurveStats` 已选 X/Y）决定哪些曲线进入数据——`bliActiveCurves` Set 经 `bliParams().active_curves` 传给四端点，`renderBliCurves()`/`updateBliCurveMaster()`/`bliToggleAllCurves()` 维护状态（事件委托 `.bli-curve-cb`/`#bliCurveSelectAll`）。参数面板有 **`#bliTrimStart`**（默认勾选）→ `bliParams().trim_start`。
- 用户给的配色、样式指令是**规范级**的：直接按规范改代码，不要反复出图确认。
- **出图下载**：动作栏有常驻「📥 下载 PNG」按钮 → `downloadAreaImages("bliPlotArea","BLI")` 扫描出图区全部 `<img>`，按 `img.alt` 命名 `{自动名}_{alt}.png`（多图加序号）。新分析模块出图区记得补下载按钮。
- 中文绘图走 `fonts.py` 候选链（打包 Noto Sans SC → dev 回退 simhei → 系统字体）。

## 开发/验证流程

```bash
# 语法 + 回归（必须用 venv python，系统 python 缺 biopython/logomaker）
node --check static/app.js
.venv/Scripts/python.exe test_bli.py      # 解析/绘图/KD + BLI 分析 API + 酶活绘图
.venv/Scripts/python.exe test_models.py    # 数据契约回归
```

- **端到端验证走 test_client**（`from app import app`，不起真实服务器）。测试库隔离顺序：
  `import models` → `importlib.reload(models)` → `models.DB_PATH=<临时路径>` → `models.init_db()` → `from app import app`。**严禁在生产库上测**。
- 复制链路完整测试序列：analyze（拿 session_id + samples）→ save（校验 params.calc_type=="bli_fit"、results 带 BLI_ANALYSIS_VERSION、`_raw_ids` 出现）→ GET raw（payload.curves 有 label/conc_nM/time/response）→ restore（session_id + samples 与 analyze 一致）。
- 合成 fixture 用 `synthetic` 生成器（test_bli.py 内），不依赖真实 ForteBio 文件。
