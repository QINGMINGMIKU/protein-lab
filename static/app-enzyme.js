// ═════════════════════════════════════════════════════
//  Tab 5: Enzyme Activity
// ═════════════════════════════════════════════════════

let enzymeData = null;         // {meta, wells: {A1: {times, od}, ...}}
// raw 快照分析版本（与 BLI/AKTA 一致约定）。v1="enzyme-1.0"：payload 无 params 槽、params.wells 内嵌 times/od；
// v2="enzyme-2.0"：payload 带 calc_type/params/source_file，逐点数据只在 raw（契约规则 A）。
const ENZYME_ANALYSIS_VERSION = "enzyme-2.0";
let enzymeSelection = new Set();
let enzymeWellInfo = {};       // {A1: {name, conc_ng_ml, conc_uM, mw, group, ref, protein_id, fit}}
let enzymeSourceFile = "";     // 上传的源文件名（落 raw payload.source_file 供溯源/对照识别；手工新建留空）
// 角色自动名识别（批量改名/参考按钮覆盖判定）：角色名是自动生成的、不算自定义名，
// 批量改名可覆盖（enzymeShouldAutoRename 放行）；自定义名仍跳过不覆盖。
// 中英兜底：英文界面（默认 en）下 "Sample"/"Blank" 等角色名也能被识别。
const ENZYME_ROLE_NAMES = ["样品", "空白", "阴性", "阳性", "Sample", "Blank", "Negative", "Positive"];
// 分组配色板：与 bli.py COLORS 一一对应（板上组色 = 出图图例色，认知闭环）。改配色动 bli.py，这边同步。
const PLOT_COLORS = ["#9bbf8a", "#82afda", "#f79059", "#e7dbd3", "#c2bdde",
                     "#8dcec8", "#add3e2", "#3480b8", "#ffbe7a", "#fa8878", "#c82423"];
// 深底用白字、浅底用碳黑字（相对亮度阈值 0.6）
function wellTextColor(hex) {
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.6 ? "#fff" : "var(--carbon)";
}
// 组 → {color, members}：组名按码位升序分配色板（与服务端 aggregate_groups 的 sorted() 顺序一致，
// 保证板色 = 图例色）；members 按板序（先行后列）排列，用于复孔序号回退显示。
const wellPlateSort = (a, b) => (a.charCodeAt(0) - b.charCodeAt(0)) || (parseInt(a.slice(1), 10) - parseInt(b.slice(1), 10));
function enzymeGroupMap() {
  const map = {};
  for (const [id, info] of Object.entries(enzymeWellInfo)) {
    const g = (info.group || "").trim();
    if (!g || info.ref) continue;   // 角色孔不参与分组配色
    (map[g] = map[g] || []).push(id);
  }
  const labels = Object.keys(map).sort();
  const out = {};
  labels.forEach((g, i) => {
    out[g] = { color: PLOT_COLORS[i % PLOT_COLORS.length], members: map[g].sort(wellPlateSort) };
  });
  return out;
}
// 孔内短标签：角色符号 > 组内复孔号（名字 _N 后缀，否则板序） > 名字前 4 字符 > 样品点
function enzymeWellLabel(id, info, groups) {
  if (info.ref) return { blank: "○", neg: "⊖", pos: "⊕" }[info.ref] || "○";
  const g = (info.group || "").trim();
  const name = info.name || "";
  const suf = /_(\d+)$/.exec(name);
  if (g && groups[g]) {
    if (suf) return suf[1];
    const idx = groups[g].members.indexOf(id);
    return idx >= 0 ? String(idx + 1) : "·";
  }
  return name ? name.slice(0, 4) : "●";
}
// 悬停提示：孔号+名字 / 组 / 角色 / 浓度 / 拟合（ΔOD、R²）
function enzymeWellTip(id, info) {
  const lines = [id + (info.name ? " · " + info.name : "")];
  const g = (info.group || "").trim();
  if (g) lines.push(`${t("workbench.well_group")}: ${g}`);
  if (info.ref) lines.push(`${t("workbench.ref")}: ${{ blank: t("workbench.blank"), neg: t("workbench.neg"), pos: t("workbench.pos") }[info.ref] || info.ref}`);
  else if (ENZYME_ROLE_NAMES.includes((info.name || "").trim()) || info.name) lines.push(`${t("workbench.ref")}: ${t("workbench.sample_well")}`);
  const conc = info.conc_ng_ml != null ? `${info.conc_ng_ml} ng/mL`
    : info.conc_uM != null ? `${info.conc_uM} μM` : null;
  if (conc) lines.push(`${t("workbench.concentration")}: ${conc}`);
  const f = info.fit;
  if (f && (f.slope != null || f.slope_corrected != null)) {
    const sl = f.slope_corrected != null ? f.slope_corrected : f.slope;
    lines.push(`ΔOD/min: ${(+sl).toExponential(1)} | R²: ${f.r2 != null ? (+f.r2).toFixed(3) : "-"}`);
  }
  return lines.join("\n");
}
let enzymeLastImage = null;    // 最近一次曲线图 base64（供下载）
let enzymeLastPlotType = null; // kinetics | michaelis
let enzymeTimePoints = [];     // 时间点列表（秒，升序，全孔共享网格）
let enzymeTimeLo = 0;          // 时间区间起点下标（含）
let enzymeTimeHi = 0;          // 时间区间终点下标（含）
let enzymeTimeDragging = null; // 正在拖动的长轴把手: 'lo' | 'hi'
let enzymeRefilterTimer = null;

async function uploadEnzymeFile() {
  const file = document.getElementById("enzymeFile").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  setEvidence("enzymeMeta", "processing", t("workbench.status_processing"));
  try {
    const r = await fetch("/api/enzyme/parse", { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) {
      setEvidence("enzymeMeta", "fail", t("workbench.status_fail"));
      toast(backendError(data, r.status), true); return;
    }
    enzymeData = data;
    enzymeSourceFile = file.name;   // 源文件名落 raw payload.source_file（溯源 / 对照识别）
    enzymeSelection.clear();
    enzymeWellInfo = {};
    // 时间范围筛选：全孔共享 meta.temps 网格，缺省全区间
    enzymeTimePoints = [...new Set(data.meta.temps || Object.values(data.wells)[0]?.times || [])].sort((a, b) => a - b);
    enzymeTimeLo = 0;
    enzymeTimeHi = enzymeTimePoints.length - 1;
    enzymeLastImage = null;
    enzymeLastPlotType = null;
    renderEnzymeTimePanel();
    renderPlate();
    const nWells = Object.keys(data.wells).length;
    setEvidence("enzymeMeta", nWells ? "done" : "empty",
      `${data.meta.sample || file.name} | ${data.meta.wavelength || "?"} nm | ${t("detail.wells_n", { n: nWells })}`);
    document.getElementById("enzymeTable").classList.add("hidden");
    document.getElementById("enzymePlotArea").innerHTML = "";
    toast(t("toast.parsed"));
  } catch (err) {
    setEvidence("enzymeMeta", "fail", t("workbench.status_fail"));
    toast(err, true);
  }
}

function renderPlate() {
  document.querySelectorAll(".plate-well").forEach(el => {
    el.classList.remove("has-data", "selected", "ref-blank", "ref-neg", "ref-pos");
    el.textContent = "";
    el.removeAttribute("title");
    el.removeAttribute("style");
  });
  if (!enzymeData) return;
  const groups = enzymeGroupMap();
  for (const [id, wd] of Object.entries(enzymeData.wells)) {
    const el = document.getElementById("well-" + id);
    if (!el) continue;
    const info = enzymeWellInfo[id] || {};
    el.classList.add("has-data");
    if (info.ref) el.classList.add("ref-" + info.ref);
    else {
      const g = (info.group || "").trim();
      const color = g && groups[g] ? groups[g].color : null;
      if (color) { el.style.background = color; el.style.color = wellTextColor(color); }
    }
    el.textContent = enzymeWellLabel(id, info, groups);
    el.title = enzymeWellTip(id, info);
  }
  updatePlateSelection();
}

function updatePlateSelection() {
  document.querySelectorAll(".plate-well").forEach(el => {
    const id = el.id.replace("well-", "");
    el.classList.toggle("selected", enzymeSelection.has(id));
  });
  updateWellForm();
}

// ── 时间范围筛选：拖动长轴把手选连续时间区间，对拟合/绘图/存档/导出统一生效 ──
function renderEnzymeTimePanel() {
  const panel = document.getElementById("enzymeTimePanel");
  if (!panel) return;
  if (!enzymeTimePoints.length) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  renderEnzymeTimeAxis();
}

function enzymeTimeFrac(i) {
  const n = enzymeTimePoints.length;
  return n < 2 ? 0 : i / (n - 1);
}

function renderEnzymeTimeAxis() {
  const axis = document.getElementById("enzymeTimeAxis");
  if (!axis || !enzymeTimePoints.length) return;
  // 时间点刻度（1px 竖线，hover 显示秒数）
  axis.querySelectorAll(".eta-tick").forEach(t => t.remove());
  enzymeTimePoints.forEach((t, i) => {
    const tick = document.createElement("div");
    tick.className = "eta-tick";
    tick.style.left = enzymeTimeFrac(i) * 100 + "%";
    tick.title = t + "s";
    axis.appendChild(tick);
  });
  // 区间高亮 + 双把手位置
  const loPct = enzymeTimeFrac(enzymeTimeLo) * 100;
  const hiPct = enzymeTimeFrac(enzymeTimeHi) * 100;
  const range = axis.querySelector(".eta-range");
  const hLo = axis.querySelector(".eta-handle-lo");
  const hHi = axis.querySelector(".eta-handle-hi");
  range.style.left = loPct + "%";
  range.style.width = Math.max(0, hiPct - loPct) + "%";
  hLo.style.left = loPct + "%";
  hHi.style.left = hiPct + "%";
  // 端点读数
  const eLo = document.getElementById("enzymeTimeLoLabel");
  const eHi = document.getElementById("enzymeTimeHiLabel");
  if (eLo) eLo.textContent = t("workbench.time_lo", { t: enzymeTimePoints[enzymeTimeLo] });
  if (eHi) eHi.textContent = t("workbench.time_hi", { t: enzymeTimePoints[enzymeTimeHi] });
  updateEnzymeTimeBadge();
}

function updateEnzymeTimeBadge() {
  const el = document.getElementById("enzymeTimeCount");
  if (!el || !enzymeTimePoints.length) return;
  const n = enzymeTimeHi - enzymeTimeLo + 1;
  el.textContent = t("workbench.time_selected", {
    n, total: enzymeTimePoints.length,
    lo: enzymeTimePoints[enzymeTimeLo], hi: enzymeTimePoints[enzymeTimeHi],
  });
  el.style.color = n < 2 ? "var(--danger)" : "var(--graphite)";  // <2 点无法拟合斜率，标红提醒
}

function enzymeTimeIndexFromEvent(e) {
  const axis = document.getElementById("enzymeTimeAxis");
  const rect = axis.getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  return Math.round(frac * (enzymeTimePoints.length - 1));
}

function enzymeTimeAxisDown(e) {
  if (!enzymeTimePoints.length) return;
  const idx = enzymeTimeIndexFromEvent(e);
  if (enzymeTimeLo === enzymeTimeHi) {
    // 区间坍缩成单点时：点左拖 lo、点右拖 hi，才能向两侧展开
    enzymeTimeDragging = idx <= enzymeTimeLo ? "lo" : "hi";
  } else {
    const dLo = Math.abs(idx - enzymeTimeLo), dHi = Math.abs(idx - enzymeTimeHi);
    enzymeTimeDragging = dLo <= dHi ? "lo" : "hi";
  }
  enzymeTimeAxisMoveTo(idx);
  document.getElementById("enzymeTimeAxis").setPointerCapture(e.pointerId);
}

function enzymeTimeAxisMove(e) {
  if (enzymeTimeDragging === null || !enzymeTimePoints.length) return;
  enzymeTimeAxisMoveTo(enzymeTimeIndexFromEvent(e));
}

function enzymeTimeAxisUp() {
  enzymeTimeDragging = null;
}

function enzymeTimeAxisMoveTo(idx) {
  if (enzymeTimeDragging === "lo") {
    enzymeTimeLo = Math.min(idx, enzymeTimeHi);   // lo 拖不过 hi
  } else {
    enzymeTimeHi = Math.max(idx, enzymeTimeLo);   // hi 拖不过 lo
  }
  renderEnzymeTimeAxis();
  clearTimeout(enzymeRefilterTimer);
  enzymeRefilterTimer = setTimeout(enzymeRefilter, 250);  // 防抖，连续拖动只触发一次
}

function enzymeTimeAll() {
  if (!enzymeTimePoints.length) return;
  enzymeTimeLo = 0;
  enzymeTimeHi = enzymeTimePoints.length - 1;
  renderEnzymeTimeAxis();
  clearTimeout(enzymeRefilterTimer);
  enzymeRefilterTimer = setTimeout(enzymeRefilter, 250);
}

// 筛选生效：已有拟合则静默重算，有图则重绘
async function enzymeRefilter() {
  if (!enzymeData) return;
  const hadFit = Object.keys(enzymeWellInfo).some(id => enzymeWellInfo[id].fit);
  if (hadFit) await enzymeCalcAll(true);
  if (enzymeLastPlotType) await enzymePlot(enzymeLastPlotType);
}

// 按激活区间过滤某孔数据（按时间值匹配，兼容个别孔缺测点导致的索引错位）
function enzymeFilteredData(wd) {
  if (!enzymeTimePoints.length) return { times: wd.times, od: wd.od };
  const lo = enzymeTimePoints[enzymeTimeLo], hi = enzymeTimePoints[enzymeTimeHi];
  const times = [], od = [];
  for (let i = 0; i < wd.times.length; i++) {
    const t = wd.times[i];
    if (t >= lo && t <= hi) { times.push(t); od.push(wd.od[i]); }
  }
  return { times, od };
}

function enzymeClickWell(e, id) {
  if (!enzymeData) return;
  if (e.ctrlKey || e.metaKey) {
    // Ctrl+点击: 追加/移除，不影响其他选中
    enzymeSelection.has(id) ? enzymeSelection.delete(id) : enzymeSelection.add(id);
  } else if (enzymeSelection.has(id) && enzymeSelection.size === 1) {
    // 单击已选中的唯一孔 → 取消选择
    enzymeSelection.delete(id);
  } else {
    // 单击未选中的孔 → 清空并选中
    enzymeSelection.clear();
    enzymeSelection.add(id);
  }
  updatePlateSelection();
}

// 刷新「组」下拉可选项：从所有孔已设的组名去重填充 datalist（供新建/改名时选已有组）
function refreshWellGroupOptions() {
  const d = document.getElementById("wellGroupOptions");
  if (!d) return;
  const groups = [...new Set(Object.values(enzymeWellInfo)
    .map(i => (i.group || "").trim()).filter(Boolean))];
  d.innerHTML = groups.map(g => `<option value="${g.replace(/"/g, "&quot;")}"></option>`).join("");
}

// 未选孔时的右栏全板摘要：命名/分组/角色/拟合一屏看全，省去逐孔点选
function renderPlateSummary(el) {
  if (!enzymeData) { el.textContent = t("workbench.pick_well"); return; }
  const wells = Object.entries(enzymeData.wells);
  const named = wells.filter(([id]) => (enzymeWellInfo[id]?.name || "").trim()).length;
  const groups = enzymeGroupMap();
  const roleCount = { blank: 0, neg: 0, pos: 0 };
  let fitted = 0, lowR2 = 0;
  for (const [id] of wells) {
    const info = enzymeWellInfo[id] || {};
    if (info.ref && roleCount[info.ref] != null) roleCount[info.ref]++;
    const f = info.fit;
    if (f && (f.slope != null || f.slope_corrected != null)) {
      fitted++;
      if (f.r2 != null && +f.r2 < 0.95) lowR2++;
    }
  }
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  let html = `<div class="ps-line">${t("workbench.sum_named", { n: named, total: wells.length })}</div>`;
  const gNames = Object.keys(groups).sort();
  if (gNames.length) {
    html += `<div class="ps-line">${t("workbench.sum_groups", { n: gNames.length })}</div><div class="ps-groups">` +
      gNames.map(g => `<span class="ps-chip"><i class="ps-dot" style="background:${groups[g].color}"></i>${esc(g)} ×${groups[g].members.length}</span>`).join("") +
      `</div>`;
  }
  if (roleCount.blank || roleCount.neg || roleCount.pos) {
    html += `<div class="ps-line">${t("workbench.sum_roles", { b: roleCount.blank, g: roleCount.neg, p: roleCount.pos })}</div>`;
  }
  if (fitted) {
    html += `<div class="ps-line">${t("workbench.sum_fitted", { n: fitted, low: lowR2 })}` +
      (lowR2 ? `<span class="ps-warn"> · ${t("workbench.sum_lowr2_hint", { low: lowR2 })}</span>` : "") + `</div>`;
  }
  el.innerHTML = html;
}

function updateWellForm() {
  const detail = document.getElementById("wellDetail");
  const form = document.getElementById("wellForm");
  const fit = document.getElementById("wellFit");
  if (enzymeSelection.size === 0) {
    detail.classList.remove("hidden");
    renderPlateSummary(detail);
    form.classList.add("hidden"); fit.classList.add("hidden");
    return;
  }
  detail.classList.add("hidden");
  form.classList.remove("hidden");
  const ids = Array.from(enzymeSelection);
  const info = enzymeWellInfo[ids[0]] || {};
  document.getElementById("wellName").value = info.name || "";
  document.getElementById("wellGroup").value = info.group || "";
  refreshWellGroupOptions();
  const unit = document.getElementById("wellConcUnit").value;
  document.getElementById("wellConc").value =
    unit === "ng_ml" ? (info.conc_ng_ml ?? "") : (info.conc_uM ?? "");
  document.getElementById("wellMW").value = info.mw || "";
  if (info.protein_id) {
    document.getElementById("wellProtein").value = info.protein_id;
    const p = enzymeProteinList.find(x => x.id === info.protein_id);
    document.getElementById("enzymeProteinSearch").value = p ? p.name : "";
  } else {
    document.getElementById("wellProtein").value = "";
    document.getElementById("enzymeProteinSearch").value = "";
  }
  document.getElementById("wellName").placeholder = t("toast.pick_wells_n", { n: enzymeSelection.size });
  document.getElementById("wellGroup").placeholder =
    enzymeSelection.size > 1 ? t("workbench.well_group_n", { n: enzymeSelection.size }) : t("workbench.well_group_ph");

  // 参考孔按钮状态
  const ref = info.ref;
  ["None", "Blank", "Neg", "Pos"].forEach(r => {
    const btn = document.getElementById("ref" + r);
    if (btn) btn.classList.toggle("active", (r === "None" && !ref) || (r !== "None" && ref === r.toLowerCase()));
  });

  // 拟合结果
  if (enzymeSelection.size === 1 && enzymeWellInfo[ids[0]]?.fit) {
    fit.classList.remove("hidden");
    const f = enzymeWellInfo[ids[0]].fit;
    fit.innerHTML = `ΔOD/min: <b>${f.slope?.toFixed(5) || "-"}</b> | R²: <b>${f.r2 ?? "-"}</b>`;
  } else {
    fit.classList.add("hidden");
  }
}

function enzymeUpdateWells() {
  const name = document.getElementById("wellName").value.trim();
  const group = document.getElementById("wellGroup").value.trim();
  const conc = parseFloat(document.getElementById("wellConc").value);
  const unit = document.getElementById("wellConcUnit").value;
  const mw = parseFloat(document.getElementById("wellMW").value) || null;

  const ids = Array.from(enzymeSelection);
  // 批量命名：同名孔按孔位顺序自动加 _1/_2/_3；已存在不同名字的孔跳过不覆盖（enzymeShouldAutoRename）
  const multi = ids.length > 1 && !!name;
  if (multi) {
    ids.sort((a, b) => (a.charCodeAt(0) - b.charCodeAt(0)) || (parseInt(a.slice(1), 10) - parseInt(b.slice(1), 10)));
  }
  const renameIds = multi ? ids.filter(id => enzymeShouldAutoRename(id, name)) : ids;
  // 已占用后缀号：全板中「不在本次重命名集合」的孔已持有 {name}_N（或裸 {name}）→ 序号让给它们，
  // 避免第二批/多批同名命名从头编号导致重名孔（如已有 TIM_1..4，新批又从 TIM_1 起）
  const usedNums = multi ? enzymeTakenSuffixes(renameIds, name) : new Set();
  let nextNum = 1;
  const takeNum = () => { while (usedNums.has(nextNum)) nextNum++; usedNums.add(nextNum); return nextNum++; };
  ids.forEach((id) => {
    if (!enzymeWellInfo[id]) enzymeWellInfo[id] = {};
    if (name) {
      if (!multi) {
        enzymeWellInfo[id].name = name;
      } else {
        const ri = renameIds.indexOf(id);
        if (ri >= 0) enzymeWellInfo[id].name = `${name}_${takeNum()}`;
      }
    }
    enzymeWellInfo[id].group = group;  // 空=清除组（与 name 的「非空才写」不同）
    enzymeWellInfo[id].mw = mw;
    if (!isNaN(conc)) {
      if (unit === "ng_ml") {
        enzymeWellInfo[id].conc_ng_ml = conc;
        enzymeWellInfo[id].conc_uM = mw ? +(conc / mw).toFixed(4) : null;
      } else {
        enzymeWellInfo[id].conc_uM = conc;
        enzymeWellInfo[id].conc_ng_ml = mw ? +(conc * mw).toFixed(1) : null;
      }
    }
  });
  refreshWellGroupOptions();
  renderPlate();
}

// 批量自动命名是否改这个孔：空名、同名、参考角色自动名（样品/空白/阴性/阳性）、或已是 {name}_N
// 模式 → 命名；其他自定义名 → 跳过不覆盖
function enzymeShouldAutoRename(id, name) {
  const cur = (enzymeWellInfo[id]?.name || "").trim();
  if (!cur || cur === name || ENZYME_ROLE_NAMES.includes(cur)) return true;
  return new RegExp("^" + _escRegex(name) + "_\\d+$").test(cur);
}

// 全板已被占用的 {name}_N 后缀号：除本次重命名集合外，孔名匹配 {name}_N 的占用 N、裸 {name} 占用 1。
// 批量命名按最小空闲号续编，保证不与其他孔重名。
function enzymeTakenSuffixes(renameIds, name) {
  const re = new RegExp("^" + _escRegex(name) + "_(\\d+)$");
  const used = new Set();
  for (const [wid, w] of Object.entries(enzymeWellInfo)) {
    if (renameIds.includes(wid)) continue;   // 本次会重命名，旧号释放
    const cur = (w?.name || "").trim();
    if (cur === name) { used.add(1); continue; }
    const m = re.exec(cur);
    if (m) used.add(parseInt(m[1], 10));
  }
  return used;
}

function _escRegex(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function enzymeBatchConc() {
  if (enzymeSelection.size < 2) { toast(t("toast.select_multi_wells"), true); return; }
  const startRaw = await askText(t("ui.start_conc"), "");
  const start = parseFloat(startRaw);
  if (isNaN(start)) return;
  const factor = parseFloat(await askText(t("ui.step_factor"), "2")) || 2;
  const unit = document.getElementById("wellConcUnit").value;
  const mw = parseFloat(document.getElementById("wellMW").value) || null;
  const ids = Array.from(enzymeSelection).sort();
  ids.forEach((id, i) => {
    const c = +(start * Math.pow(factor, i)).toFixed(4);
    if (!enzymeWellInfo[id]) enzymeWellInfo[id] = {};
    enzymeWellInfo[id].mw = mw;
    if (unit === "ng_ml") {
      enzymeWellInfo[id].conc_ng_ml = c;
      enzymeWellInfo[id].conc_uM = mw ? +(c / mw).toFixed(4) : null;
    } else {
      enzymeWellInfo[id].conc_uM = c;
      enzymeWellInfo[id].conc_ng_ml = mw ? +(c * mw).toFixed(1) : null;
    }
  });
  renderPlate();
  updateWellForm();
  toast(t("toast.batch_conc_set", { n: ids.length, start, factor }));
}

async function enzymeCalcSelected() {
  if (!enzymeSelection.size) { toast(t("toast.select_wells"), true); return; }
  await enzymeCalc(Array.from(enzymeSelection));
}

async function enzymeCalcAll(silent = false) {
  if (!enzymeData) { toast(t("toast.upload_first"), true); return; }
  await enzymeCalc(Object.keys(enzymeData.wells), silent);
}

async function enzymeCalc(wellIds, silent = false) {
  const payload = { wells: {} };
  for (const id of wellIds) {
    const wd = enzymeData.wells[id];
    if (!wd) continue;
    const { times, od } = enzymeFilteredData(wd);  // 只算激活的时间点
    payload.wells[id] = { times, od, ref: enzymeWellInfo[id]?.ref };
  }
  // 速率级背景扣除需要全板的阴性/空白孔作参考（即使当前未选中）——后端据此算 slope_corrected。
  // 背景优先级：阴性(neg) > 空白(blank)，两者并存只扣阴性（空白是基线，不混入背景）
  for (const [id, wd] of Object.entries(enzymeData.wells)) {
    const info = enzymeWellInfo[id] || {};
    if ((info.ref === "blank" || info.ref === "neg") && !payload.wells[id]) {
      const { times, od } = enzymeFilteredData(wd);
      payload.wells[id] = { times, od, ref: info.ref };
    }
  }
  try {
    const r = await API.post("/api/enzyme/fit", payload);
    // 后端已算好 slope_corrected / blank_corrected，这里只写回 + 显示
    for (const [id, fit] of Object.entries(r.wells)) {
      if (!enzymeWellInfo[id]) enzymeWellInfo[id] = {};
      enzymeWellInfo[id].fit = fit;
    }
    renderEnzymeTable(wellIds);
    updateWellForm();
    const bg = r.bg;
    const msg = bg ? t("workbench.calc_bg", { n: bg.count, avg: bg.avg.toFixed(6) }) : t("toast.calc_done");
    if (!silent) toast(msg);
  } catch (err) { toast(err, true); }
}

function renderEnzymeTable(wellIds) {
  const table = document.getElementById("enzymeTable");
  const tbody = table.querySelector("tbody");
  table.classList.remove("hidden");
  tbody.innerHTML = wellIds.map(id => {
    const info = enzymeWellInfo[id] || {};
    const f = info.fit || {};
    const refLabel = info.ref === "blank" ? t("workbench.blank") : info.ref === "neg" ? t("workbench.neg") : info.ref === "pos" ? t("workbench.pos") : t("workbench.sample_well");
    return `<tr>
      <td>${id}</td><td>${esc(info.name || "")}</td>
      <td style="color:var(--graphite)">${esc(info.group || "")}</td>
      <td>${refLabel}</td>
      <td>${info.conc_ng_ml ?? "-"}</td><td>${info.conc_uM ?? "-"}</td>
      <td>${f.blank_corrected ? (f.slope_corrected?.toFixed(5) + ' <span style=color:var(--graphite);font-size:11px>(' + t("workbench.corrected") + ')</span>') : (f.slope?.toFixed(5) || "-")}</td>
      <td style="color:${f.r2 != null && f.r2 < 0.95 ? 'var(--danger)' : 'var(--carbon)'}">${f.r2 ?? "-"}</td>
      <td>${info.activity ?? "-"}</td>
    </tr>`;
  }).join("");
}

async function enzymePlot(type) {
  if (!enzymeData) { toast(t("toast.upload_first"), true); return; }
  const ids = enzymeSelection.size ? Array.from(enzymeSelection) : Object.keys(enzymeData.wells);
  const alignStart = document.getElementById("enzymeAlignStart")?.checked || false;
  const alignEnd = document.getElementById("enzymeAlignEnd")?.checked || false;
  const showBlank = document.getElementById("enzymeShowBlank")?.checked || false;
  const subBlank = document.getElementById("enzymeSubBlank")?.checked || false;
  const errorBar = document.getElementById("enzymeErrorBar")?.value || "none";
  const groupEnabled = document.getElementById("enzymeGroup")?.checked ?? true;  // 按组分平均开关
  const payload = { type, align_start: alignStart, align_end: alignEnd, show_blank: showBlank, sub_blank: subBlank, error_bar: errorBar, wells: {} };
  for (const id of ids) {
    const wd = enzymeData.wells[id];
    if (!wd) continue;
    const info = enzymeWellInfo[id] || {};
    const { times, od } = enzymeFilteredData(wd);  // 只画激活的时间点
    payload.wells[id] = {
      times, od,
      ref: info.ref,  // 后端据此识别阴性/空白（扣除 + 默认隐藏）
      name: info.name || id,
      group: groupEnabled ? (info.group || "") : "",  // 关「按组分平均」→ 不传组，后端逐孔画
      conc_ng_ml: info.conc_ng_ml,
      substrate_uM: info.conc_uM,
      rate: info.fit?.slope,
      fit: info.fit,
    };
  }
  // 「扣除阴性」需要全板的阴性/空白孔作为参考，即使当前未选中
  // （后端减算用全部 wells_data，绘制仍受 show_blank 控制）
  if (subBlank) {
    for (const [id, wd] of Object.entries(enzymeData.wells)) {
      const info = enzymeWellInfo[id] || {};
      if ((info.ref === "blank" || info.ref === "neg") && !payload.wells[id]) {
        const { times, od } = enzymeFilteredData(wd);
        payload.wells[id] = { times, od, ref: info.ref, name: info.name || id, fit: info.fit };
      }
    }
  }
  try {
    const r = await API.post("/api/enzyme/plot", payload);
    enzymeLastImage = r.image;
    enzymeLastPlotType = type;
    document.getElementById("enzymePlotArea").innerHTML =
      `<img src="${r.image}" style="max-width:100%" alt="plot">
       <div style="margin-top:8px">
         <button class="btn btn-sm btn-outline" onclick="downloadEnzymePlot()">${t("workbench.download_png")}</button>
       </div>`;
  } catch (err) { toast(err, true); }
}

async function downloadEnzymePlot() {
  if (!enzymeLastImage) { toast(t("toast.plot_curve_first"), true); return; }
  const auto = await getAutoName("酶活测定", null, "enzyme") || "enzyme";
  const name = enzymeLastPlotType === "michaelis" ? t("workbench.mm") : t("workbench.kinetics");
  downloadDataUrl(enzymeLastImage, `${auto}_${name}.png`);
}

// 手动处理参数快照（对称 bliParams / aktaParams）：**只收手动项，不含逐点数据**。
// 契约规则 A：times/od 只落 experiment_raw，params 不内嵌；规则 B：这份快照原样嵌进
// raw payload.params，是「载入计算工具」回填 UI 的唯一读取源（raw 只写一次 → 天然不可变）。
function enzymeParams() {
  return {
    calc_type: "enzyme",
    meta: enzymeData?.meta || {},
    source_file: enzymeSourceFile || "",
    // 时间窗口：秒值对（保持现存语义，便于人读；复制时服务端换算成网格下标）
    time_axis: enzymeTimePoints.length
      ? [enzymeTimePoints[enzymeTimeLo], enzymeTimePoints[enzymeTimeHi]] : null,
    sub_blank: document.getElementById("enzymeSubBlank")?.checked ?? true,
    show_blank: document.getElementById("enzymeShowBlank")?.checked ?? false,
    align_start: document.getElementById("enzymeAlignStart")?.checked ?? true,
    align_end: document.getElementById("enzymeAlignEnd")?.checked ?? false,
    error_bar: document.getElementById("enzymeErrorBar")?.value || "none",
    group: document.getElementById("enzymeGroup")?.checked ?? true,
  };
}

// 回填存档时的分析参数到 UI 控件（对称 bliBackfillParams / aktaBackfillParams）。
// 默认 true 的开关用 `!== false`——缺字段时保持 UI 默认 true，不被静默改写为 false；
// 默认 false 的用 `!!`。error_bar 仅在存档里确实有该字段时才写回（保留下拉框默认 none）。
// 缺字段的开关静默跳过：v1 历史快照从未采集过开关值，无从考证，只能走当前 UI 默认。
function enzymeBackfillParams(p) {
  if (!p) return;
  // 默认 true 的开关：缺字段 → 保持 true（`undefined !== false`），仅显式 false 才关。
  const setDef = (id, v) => { const el = document.getElementById(id); if (el) el.checked = v !== false; };
  // 默认 false 的开关：缺字段 → false，真值才开。
  const setOpt = (id, v) => { const el = document.getElementById(id); if (el) el.checked = !!v; };
  setDef("enzymeSubBlank", p.sub_blank);
  setDef("enzymeAlignStart", p.align_start);
  setDef("enzymeGroup", p.group);
  setOpt("enzymeShowBlank", p.show_blank);
  setOpt("enzymeAlignEnd", p.align_end);
  const eb = document.getElementById("enzymeErrorBar");
  if (eb && p.error_bar) eb.value = p.error_bar;
  if (typeof p.source_file === "string" && p.source_file) enzymeSourceFile = p.source_file;
}

async function enzymeSaveExp() {
  if (!enzymeData) { toast(t("toast.upload_first"), true); return; }
  const mount = await promptExpMount("酶活测定");
  if (mount === null) { toast(t("toast.save_cancelled")); return; }
  let title = "";
  if (!mount.exp_id) {
    const autoName = await getAutoName("酶活测定", null, "enzyme");
    title = await askText(t("ui.exp_name_prompt"), autoName || enzymeData.meta.sample || t("exp_type.酶活测定"));
    if (!title) return;
  }

  const proteinIds = new Set();
  const wells = {};
  const rawWells = {};  // raw 快照：每孔**全量**时间序列（不受时间轴过滤影响），保证可复算
  for (const [id, wd] of Object.entries(enzymeData.wells)) {
    const info = enzymeWellInfo[id] || {};
    if (info.protein_id) proteinIds.add(info.protein_id);
    // 契约规则 A：params.wells 只留元数据 + 拟合 + 极小派生摘要（od_range，详情页要显示）。
    // times/od 只落 raw——此前存的是 enzymeFilteredData 的截断数据，复制→再存档会逐代丢点。
    wells[id] = {
      name: info.name,
      ref: info.ref,
      group: info.group || "",
      protein_id: info.protein_id,
      mw: info.mw ?? null,          // 此前丢失 → 复制后 ng/mL ↔ μM 无法互算
      conc_ng_ml: info.conc_ng_ml,
      conc_uM: info.conc_uM,
      fit: info.fit || null,
      od_range: (() => {
        const { od } = enzymeFilteredData(wd);
        return od.length ? [od[0].toFixed(4), od[od.length - 1].toFixed(4)] : null;
      })(),
    };
    rawWells[id] = {
      name: info.name,
      ref: info.ref,
      times: wd.times,   // 全量
      od: wd.od,         // 全量
    };
  }
  const enzParams = enzymeParams();

  let goal = {};
  if (!mount.exp_id) {
    goal = await promptGoalAttach();
    if (goal === null) { toast(t("toast.save_cancelled")); return; }
  }

  try {
    const saved = await API.post("/api/experiments/from-calculation", {
      title, exp_type: "酶活测定",
      protein_ids: Array.from(proteinIds),
      date: todayLocal(),
      calc_type: "enzyme",
      calc_params: { ...enzParams, wells, well_count: Object.keys(enzymeData.wells).length },
      calc_result: {},
      // raw payload 统一契约形状：analysis_version / calc_type / params（冻结副本，回填源）/ source_file / 模块数据。
      // params 与 calc_params 的手动部分同源——raw 只写一次，故快照里的手动参数天然不可变。
      raw_snapshots: [{
        data_type: "enzyme_traces",
        payload: {
          analysis_version: ENZYME_ANALYSIS_VERSION,
          calc_type: "enzyme",
          params: enzParams,
          source_file: enzymeSourceFile || "",
          meta: enzymeData.meta,
          wells: rawWells,
        },
      }],
      ...mount,
      ...goal,
    });
    toast(mount.exp_id ? t("toast.remounted", { id: mount.exp_id })
      : (saved.goal_node_id ? t("toast.saved_linked") : t("toast.saved_record")));
  } catch (err) { toast(err, true); }
}

// 导出作图友好 Excel（宽格式：每孔独立时间/OD 两列 + 动力学汇总），文件名用自动命名
async function enzymeExportExcel() {
  if (!enzymeData) { toast(t("toast.upload_first"), true); return; }
  const autoName = await getAutoName("酶活测定", null, "enzyme") || "enzyme";
  const wells = {};
  for (const [id, wd] of Object.entries(enzymeData.wells)) {
    const info = enzymeWellInfo[id] || {};
    const { times, od } = enzymeFilteredData(wd);  // 导出只包含激活的时间点
    wells[id] = {
      name: info.name, ref: info.ref,
      group: info.group || "",
      conc_ng_ml: info.conc_ng_ml, conc_uM: info.conc_uM,
      fit: info.fit || null,
      times, od,
    };
  }
  try {
    const r = await fetch("/api/enzyme/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta: enzymeData.meta, wells }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw backendError(j, r.status, t("toast.export_failed", { status: r.status }));
    }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${autoName}.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    toast(t("toast.exported_plot"));
  } catch (err) { toast(err, true); }
}

let enzymeProteinList = [];
async function loadEnzymeProteinList() {
  if (enzymeProteinList.length) return;
  try {
    enzymeProteinList = await API.get("/api/proteins");
  } catch (_) {}
}

async function enzymeSearchProtein() {
  if (!enzymeProteinList.length) await loadEnzymeProteinList();
  const q = document.getElementById("enzymeProteinSearch").value.trim().toLowerCase();
  const dropdown = document.getElementById("enzymeProteinResults");
  if (!q) { dropdown.classList.add("hidden"); return; }
  const matches = enzymeProteinList.filter(p =>
    p.name.toLowerCase().includes(q) || (p.tag || "").toLowerCase().includes(q)
  );
  dropdown.innerHTML = matches.length
    ? matches.map(p => `<div class="search-item" onclick="enzymeSelectProtein(${p.id},'${esc(p.name)}')">
        <strong>${esc(p.name)}</strong><span style="color:var(--graphite);font-size:11px">${p.mw?.toLocaleString()} Da</span>
      </div>`).join("")
    : `<div class="search-item" style="color:var(--graphite)">${t("workbench.no_match")}</div>`;
  dropdown.classList.remove("hidden");
}

function enzymeSelectProtein(pid, name) {
  document.getElementById("wellProtein").value = pid;
  document.getElementById("enzymeProteinSearch").value = name;
  document.getElementById("enzymeProteinResults").classList.add("hidden");
  enzymeLinkProtein(pid);
}

async function enzymeLinkProtein(pid) {
  pid = pid || document.getElementById("wellProtein").value;
  if (!pid) {
    for (const id of enzymeSelection) {
      if (enzymeWellInfo[id]) { enzymeWellInfo[id].protein_id = null; enzymeWellInfo[id].mw = null; }
    }
    renderPlate();
    return;
  }
  try {
    const p = await API.get(`/api/proteins/${pid}`);
    for (const id of enzymeSelection) {
      if (!enzymeWellInfo[id]) enzymeWellInfo[id] = {};
      enzymeWellInfo[id].protein_id = p.id;
      enzymeWellInfo[id].mw = p.mw;
      if (!enzymeWellInfo[id].name) enzymeWellInfo[id].name = p.name;
    }
    document.getElementById("wellName").value = p.name;
    document.getElementById("wellMW").value = p.mw;
    renderPlate();
    toast(t("toast.linked_wells", { n: enzymeSelection.size, name: p.name }));
  } catch (err) { toast(err, true); }
}

// 关闭搜索下拉
document.addEventListener("click", function (e) {
  if (!e.target.closest("#enzymeProteinSearch") && !e.target.closest("#enzymeProteinResults")) {
    const d = document.getElementById("enzymeProteinResults");
    if (d) d.classList.add("hidden");
  }
});

function enzymeSetRef(refType) {
  // 参考角色写进命名，不落空：●样品→"样品"、○空白→"空白"、⊖阴性→"阴性"、⊕阳性→"阳性"
  const roleLabels = {
    "": t("workbench.sample_well"),
    blank: t("workbench.blank"),
    neg: t("workbench.neg"),
    pos: t("workbench.pos"),
  };
  const label = roleLabels[refType || ""];
  const roleNames = ENZYME_ROLE_NAMES.concat(Object.values(roleLabels));
  for (const id of enzymeSelection) {
    if (!enzymeWellInfo[id]) enzymeWellInfo[id] = {};
    enzymeWellInfo[id].ref = refType;
    // 空命名或当前是角色名 → 跟随按钮；自定义命名不覆盖
    const cur = enzymeWellInfo[id].name || "";
    if (!cur || roleNames.includes(cur)) enzymeWellInfo[id].name = label;
  }
  updateWellForm();
  renderPlate();
}

function enzymeSelectAll() {
  if (!enzymeData) return;
  enzymeSelection = new Set(Object.keys(enzymeData.wells));
  updatePlateSelection();
}
function enzymeClearAll() { enzymeSelection.clear(); updatePlateSelection(); }
function enzymeInvertSelect() {
  if (!enzymeData) return;
  const all = new Set(Object.keys(enzymeData.wells));
  enzymeSelection = new Set([...all].filter(x => !enzymeSelection.has(x)));
  updatePlateSelection();
}

