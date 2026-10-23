// ═════════════════════════════════════════════════════
//  State persistence (survives page navigation)
// ═════════════════════════════════════════════════════

function saveCalcState() {
  if (!Object.keys(selectedProteins).length) {
    sessionStorage.removeItem("calc_state");
    return;
  }
  const slim = {};
  for (const [id, p] of Object.entries(selectedProteins)) {
    slim[id] = {
      _a280: p._a280, _path: p._path,
      _conc_uM: p._conc_uM, _conc_mg: p._conc_mg,
      _targetConc: p._targetConc, _targetVol: p._targetVol,
      _takeVol: p._takeVol, _bufferVol: p._bufferVol,
    };
  }
  sessionStorage.setItem("calc_state", JSON.stringify({
    ids: Object.keys(selectedProteins),
    data: slim,
    oxidized: getCurrentOxidized(),
    expName: document.getElementById("concExpName")?.value || "",
  }));
}

async function restoreCalcState() {
  const raw = sessionStorage.getItem("calc_state");
  if (!raw) return;
  try {
    const saved = JSON.parse(raw);
    if (!saved.ids || !saved.ids.length) return;
    if (!allProteins.length) allProteins = await API.get("/api/proteins");
    for (const id of saved.ids) {
      const p = allProteins.find(x => x.id == id);
      if (!p) continue;
      selectedProteins[id] = {
        name: p.name, mw: p.mw,
        ext_ox: p.ext_ox, ext_red: p.ext_red,
        abs_0_1pct: p.abs_0_1pct,
        ...(saved.data[id] || {}),
      };
    }
    // 恢复 Cys 状态
    if (saved.oxidized !== undefined) {
      const sel = document.getElementById("concOxidized");
      if (sel) sel.value = saved.oxidized ? "1" : "0";
    }
    // 恢复实验名称
    if (saved.expName) {
      const inp = document.getElementById("concExpName");
      if (inp) inp.value = saved.expName;
    }
    renderChips();
    renderTable();
    sessionStorage.removeItem("calc_state");
  } catch (_) { sessionStorage.removeItem("calc_state"); }
}

// ═════════════════════════════════════════════════════
//  Calculator Page — Tab switching
// ═════════════════════════════════════════════════════

const TOOL_IDS = ["conc", "dilution", "bli", "akta", "weblogo", "enzyme"];

function activateTool(tabId, opts) {
  if (!TOOL_IDS.includes(tabId)) return;
  const tab = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (!tab) return;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
  tab.classList.add("active");
  const panel = document.getElementById("tab-" + tabId);
  if (panel) panel.classList.remove("hidden");
  if (tabId === "dilution") loadBliImportExps();
  if (tabId === "weblogo") { loadWeblogoProteins(); restoreWeblogo(); }
  if (tabId === "enzyme") loadEnzymeProteinList();
  refreshAutoNamePlaceholders();
  if (!opts || opts.hash !== false) {
    const url = new URL(location.href);
    url.hash = "tool=" + tabId;
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
}

document.addEventListener("click", function (e) {
  const tab = e.target.closest(".tab-btn");
  if (!tab) return;
  activateTool(tab.dataset.tab);
});

// 自动命名占位提示：输入框显示系统默认名（留空即用它）
async function refreshAutoNamePlaceholders() {
  const targets = [
    ["concExpName", "浓度测定", "concentration"],
    ["bliExpName", "BLI", "dilution"],
    ["bliAnaExpName", "BLI", "bli_fit"],
    ["aktaExpName", "AKTA", "akta"],
    ["weblogoExpName", "Weblogo", "weblogo"],
  ];
  for (const [id, type, calc] of targets) {
    const el = document.getElementById(id);
    if (!el) continue;
    const auto = await getAutoName(type, null, calc);
    el.placeholder = auto ? t("ui.exp_name_default", { name: auto }) : t("ui.exp_name_optional");
  }
}

// ═════════════════════════════════════════════════════
//  Tab 1: Protein concentration multi-table
// ═════════════════════════════════════════════════════

let selectedProteins = {};  // { id: { name, mw, ext_ox, abs_0_1pct, ... } }
let concUnit = localStorage.getItem("concUnit") || "uM";  // 浓度结果显示单位（6 单位之一）
let dilUnit = localStorage.getItem("dilUnit") || "uM";    // BLI 稀释步骤浓度显示单位
let allProteins = [];
let copyCache = null;       // 待载入计算工具的实验（档案页/详情页深链写入）
let calcTagFilter = [];     // 计算工具标签筛选
let weblogoTagFilter = [];  // Weblogo 标签筛选

async function searchProteins() {
  const q = document.getElementById("proteinSearch").value.trim();
  const dropdown = document.getElementById("searchResults");
  if (!q) { dropdown.classList.add("hidden"); return; }

  if (!allProteins.length) {
    allProteins = await API.get("/api/proteins");
  }
  const matches = allProteins.filter(p => {
    const nameMatch = p.name.toLowerCase().includes(q.toLowerCase());
    const tagMatch = (p.tag || "").toLowerCase().includes(q.toLowerCase());
    if (!nameMatch && !tagMatch) return false;
    // 标签筛选
    if (calcTagFilter.length) {
      const proteinTags = (p.tag || "").split(",").map(t => t.trim());
      if (!calcTagFilter.every(ft => proteinTags.includes(ft))) return false;
    }
    return true;
  });

  if (!matches.length) {
    dropdown.innerHTML = '<div class="search-item" style="color:var(--graphite)">' + t("ui.no_match") + '</div>';
  } else {
    dropdown.innerHTML = matches.map(p => `
      <div class="search-item" onclick="addProteinToTable(${p.id})">
        <strong>${esc(p.name)}</strong>
        <span style="color:var(--graphite);font-size:12px">${p.mw ? p.mw.toLocaleString() + ' Da' : ''} | ε=${p.ext_ox || 0}</span>
        ${selectedProteins[p.id] ? `<span style="color:var(--cyan-deep)">✓ ${t("ui.selected_chip")}</span>` : ''}
      </div>
    `).join("");
  }
  dropdown.classList.remove("hidden");
  loadCalcTagFilter();
}

async function loadCalcTagFilter() {
  const bar = document.getElementById("calcTagFilter");
  if (!bar) return;
  try {
    const tags = await API.get("/api/proteins/tags");
    bar.innerHTML = tags.map(t => {
      const active = calcTagFilter.includes(t) ? " active" : "";
      return `<span class="tag-chip filter${active}" onclick="toggleCalcTag('${esc(t.replace(/'/g, "\\'"))}')">${esc(t)}</span>`;
    }).join(" ") || "";
  } catch (_) {}
}

function toggleCalcTag(tag) {
  const idx = calcTagFilter.indexOf(tag);
  if (idx >= 0) calcTagFilter.splice(idx, 1);
  else calcTagFilter.push(tag);
  searchProteins();
}

// Close dropdown on outside click
document.addEventListener("click", function (e) {
  if (!e.target.closest("#proteinSearch") && !e.target.closest("#searchResults")) {
    document.getElementById("searchResults").classList.add("hidden");
  }
});

function addProteinToTable(id) {
  if (selectedProteins[id]) return;  // already added
  const p = allProteins.find(x => x.id === id);
  if (!p) return;
  selectedProteins[id] = { name: p.name, mw: p.mw, ext_ox: p.ext_ox, ext_red: p.ext_red, abs_0_1pct: p.abs_0_1pct };
  document.getElementById("proteinSearch").value = "";
  document.getElementById("searchResults").classList.add("hidden");
  renderChips();
  renderTable();
}

function removeProteinFromTable(id) {
  delete selectedProteins[id];
  renderChips();
  renderTable();
  // 立即持久化，防止页面切换丢失
  if (!Object.keys(selectedProteins).length) {
    sessionStorage.removeItem("calc_state");
  }
}

function getCurrentOxidized() {
  const sel = document.getElementById("concOxidized");
  return sel ? sel.value === "1" : false;  // 默认还原态
}

function updateTableExtCoeff() {
  const oxidized = getCurrentOxidized();
  const rows = document.querySelectorAll("#concTable tbody tr[data-protein-id]");
  rows.forEach(row => {
    const id = row.dataset.proteinId;
    const p = selectedProteins[id];
    if (!p) return;
    const ext = oxidized ? (p.ext_ox || 0) : (p.ext_red || p.ext_ox || 0);
    const abs = oxidized ? (p.abs_0_1pct || 0) : (p.ext_red ? (p.ext_red / p.mw) : p.abs_0_1pct || 0);
    row.cells[2].textContent = ext || "-";
    row.cells[3].textContent = abs ? abs.toFixed(4) : "-";
    // 已输入 A280 的行自动用新 ε 重算浓度
    const a280Val = parseFloat(row.querySelector(".a280-input")?.value);
    if (!isNaN(a280Val) && a280Val >= 0) calcOneRow(row);
  });
}

function renderChips() {
  const container = document.getElementById("selectedChips");
  const ids = Object.keys(selectedProteins);
  if (!ids.length) {
    container.innerHTML = '<span style="color:var(--graphite);font-size:13px">' + t("ui.search_add_protein") + '</span>';
    return;
  }
  container.innerHTML = ids.map(id => {
    const p = selectedProteins[id];
    return `<span class="chip">${esc(p.name)} <button type="button" class="chip-x" onclick="removeProteinFromTable(${id})" aria-label="${esc(t("common.close"))}">${iconClose()}</button></span>`;
  }).join("");
}

function renderTable() {
  const tbody = document.querySelector("#concTable tbody");
  const ids = Object.keys(selectedProteins);
  if (!ids.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="13">' + t("workbench.empty_conc") + '</td></tr>';
    return;
  }
  tbody.innerHTML = ids.map(id => {
    const p = selectedProteins[id];
    return `
      <tr data-protein-id="${id}">
        <td>${esc(p.name)}</td>
        <td>${p.mw ? p.mw.toLocaleString() : "-"}</td>
        <td>${p.ext_ox || "-"}</td>
        <td>${p.abs_0_1pct ?? "-"}</td>
        <td><input type="number" class="cell-input a280-input" step="any" placeholder="0.5" value="${p._a280 || ''}"></td>
        <td><input type="number" class="cell-input path-input" step="any" placeholder="1.0" value="${p._path || '1.0'}" style="width:60px"></td>
        <td class="col-result conc-uM">-</td>
        <td class="col-result conc-mg">-</td>
        <td><input type="number" class="cell-input target-conc" step="any" placeholder="10" value="${p._targetConc || ''}"></td>
        <td><input type="number" class="cell-input target-vol" step="any" placeholder="200" value="${p._targetVol || ''}"></td>
        <td class="col-result vol-take">-</td>
        <td class="col-result vol-buffer">-</td>
        <td><button class="btn btn-sm btn-icon btn-danger" onclick="removeProteinFromTable(${id})" aria-label="${esc(t("common.delete"))}">${iconClose()}</button></td>
      </tr>
    `;
  }).join("");
}

// 更新浓度表两列结果表头：主列 = 所选单位，副列 = 互补 kind 默认单位
function updateConcHeaders() {
  const ths = document.querySelectorAll("#concTable thead th");
  if (ths.length < 9) return;
  ths[6].textContent = `${t("workbench.col_conc")} (${concUnit})`;
  ths[7].textContent = `${t("workbench.col_conc")} (${complementaryUnit(concUnit)})`;
}

// 浓度单位切换下拉框：更新全局单位 → 重算已有行
function changeConcUnit() {
  const sel = document.getElementById("concUnitSel");
  concUnit = sel ? sel.value : "uM";
  localStorage.setItem("concUnit", concUnit);
  updateConcHeaders();
  const rows = document.querySelectorAll("#concTable tbody tr[data-protein-id]");
  rows.forEach(row => {
    const a = parseFloat(row.querySelector(".a280-input")?.value);
    if (!isNaN(a) && a >= 0) calcOneRow(row);
  });
}

// ── 单行本地计算（Beer-Lambert + 稀释规划），不调 API ──
function calcOneRow(row) {
  const id = row.dataset.proteinId;
  const p = selectedProteins[id];
  if (!p) return false;

  const oxidized = getCurrentOxidized();
  const epsilon = oxidized ? p.ext_ox : p.ext_red || p.ext_ox;

  const a280 = parseFloat(row.querySelector(".a280-input").value);
  if (isNaN(a280) || a280 < 0) {
    row.querySelector(".conc-uM").textContent = "A280?";
    row.querySelector(".conc-mg").textContent = "A280?";
    return false;
  }

  const path = parseFloat(row.querySelector(".path-input").value) || 1.0;
  const molar_M = a280 / (epsilon * path);
  const conc_uM = +(molar_M * 1e6).toFixed(2);
  const conc_mg = +(molar_M * p.mw).toFixed(4);

  p._a280 = a280;
  p._path = path;
  p._conc_uM = conc_uM;
  p._conc_mg = conc_mg;

  // 结果按所选单位显示：主列 = concUnit，副列 = 互补 kind 的默认单位（µM↔mg/mL）
  // 缺 mw 无法跨 kind 时显示 "-"（同 kind 换算不抛，这里只兜底，不让整行计算中断）
  const secondaryUnit = complementaryUnit(concUnit);
  const fmtConc = (uM, unit) => {
    try { return formatConc(convertConc(uM, "uM", unit, p.mw), unit); }
    catch { return "-"; }
  };
  row.querySelector(".conc-uM").textContent = fmtConc(conc_uM, concUnit);
  row.querySelector(".conc-mg").textContent = fmtConc(conc_uM, secondaryUnit);

  // 目标浓度稀释
  const targetConc = parseFloat(row.querySelector(".target-conc").value);
  const targetVol = parseFloat(row.querySelector(".target-vol").value);

  if (!isNaN(targetConc) && !isNaN(targetVol) && targetConc > 0 && targetVol > 0) {
    p._targetConc = targetConc; p._targetVol = targetVol;
    if (targetConc > conc_uM) {
      row.querySelector(".vol-take").innerHTML = '<span style="color:var(--danger)">' + t("toast.target_gt_current") + '</span>';
      row.querySelector(".vol-buffer").textContent = "-";
      p._takeVol = null; p._bufferVol = null;
    } else {
      const takeVol = +((targetConc * targetVol) / conc_uM).toFixed(1);
      const bufferVol = +(targetVol - takeVol).toFixed(1);
      row.querySelector(".vol-take").textContent = takeVol;
      row.querySelector(".vol-buffer").textContent = bufferVol;
      p._takeVol = takeVol; p._bufferVol = bufferVol;
    }
  } else {
    row.querySelector(".vol-take").textContent = "-";
    row.querySelector(".vol-buffer").textContent = "-";
    p._takeVol = null; p._bufferVol = null;
  }
  return true;
}

async function calcAllRows() {
  const rows = document.querySelectorAll("#concTable tbody tr[data-protein-id]");
  let anyError = false;
  for (const row of rows) {
    if (!calcOneRow(row)) anyError = true;
  }
  if (!anyError) toast(t("toast.calc_done"));
}

async function saveConcTable() {
  const ids = Object.keys(selectedProteins);
  if (!ids.length) { toast(t("toast.add_protein_first"), true); return; }
  const customName = document.getElementById("concExpName").value.trim();
  const title = customName || await getAutoName("浓度测定", null, "concentration")
    || ids.map(id => selectedProteins[id].name).join(", ") + " 浓度测定";
  const oxidized = getCurrentOxidized();

  const goal = await promptGoalAttach();
  if (goal === null) { toast(t("toast.save_cancelled")); return; }

  try {
    const saved = await API.post("/api/experiments/from-calculation", {
      title: title,
      exp_type: "浓度测定",
      protein_ids: ids.map(Number),
      date: todayLocal(),
      calc_type: "concentration",
      calc_params: {
        oxidized,
        proteins: ids.map(id => ({
          id: Number(id),
          name: selectedProteins[id].name,
          mw: selectedProteins[id].mw,
          epsilon: oxidized ? selectedProteins[id].ext_ox : selectedProteins[id].ext_red,
          abs_0_1pct: selectedProteins[id].abs_0_1pct,
          a280: selectedProteins[id]._a280,
          path: selectedProteins[id]._path,
          conc_uM: selectedProteins[id]._conc_uM,
          conc_mg_mL: selectedProteins[id]._conc_mg,
          target_conc: selectedProteins[id]._targetConc,
          target_vol: selectedProteins[id]._targetVol,
          take_vol: selectedProteins[id]._takeVol,
          buffer_vol: selectedProteins[id]._bufferVol,
        })),
      },
      calc_result: [],
      ...goal,
    });
    toast(saved.goal_node_id ? t("toast.saved_linked") : t("toast.saved_record"));
  } catch (err) { toast(err, true); }
}

// ═════════════════════════════════════════════════════
//  Tab 2: BLI Dilution (multi-protein)
// ═════════════════════════════════════════════════════

let bliProteins = {};  // { id: { name, stock_uM, start_uM, factor, steps, vol, dead } }

// ── Load concentration experiments into BLI import dropdown ─
async function loadBliImportExps() {
  const sel = document.getElementById("bliImportExp");
  if (!sel || sel.options.length > 1) return;  // already loaded
  try {
    const exps = await API.get("/api/experiments?type=浓度测定&limit=50");
    sel.innerHTML = '<option value="">' + t("workbench.import_conc") + '</option>' +
      exps.map(e => `<option value="${e.id}">${esc(e.title)} (${e.date || ""})</option>`).join("");
  } catch (_) { /* non-critical */ }
}

function onBliImportExpChange() {
  const btn = document.getElementById("bliImportBtn");
  if (btn) btn.disabled = !document.getElementById("bliImportExp").value;
}

// ── Import proteins from a saved concentration experiment ──
async function importBliFromExp() {
  const expId = document.getElementById("bliImportExp").value;
  if (!expId) return;
  try {
    const e = await API.get(`/api/experiments/${expId}`);
    let params = e.params;
    if (typeof params === "string") params = JSON.parse(params);
    const proteins = (params && params.proteins) || [];
    if (!proteins.length) { toast(t("toast.no_protein_data"), true); return; }

    let added = 0;
    for (const prot of proteins) {
      if (!prot || !prot.id) continue;
      const pid = String(prot.id);
      if (bliProteins[pid]) continue;  // 已有

      const conc_uM = prot.conc_uM;
      if (conc_uM == null || isNaN(conc_uM)) continue;

      bliProteins[pid] = {
        name: prot.name || "",
        mw: prot.mw,
        stock_uM: conc_uM,
        start_uM: Math.min(conc_uM, 10),
        factor: 2,
        steps: 8,
        vol: 200,
        dead: 0,
      };
      added++;
    }
    if (!added) { toast(t("toast.proteins_exist_or_invalid"), true); return; }
    renderBliTable();
    toast(t("toast.imported_n", { n: added }));
  } catch (err) { toast(err, true); }
}

// ── Search proteins for BLI ─────────────────────────
async function searchBliProteins() {
  const q = document.getElementById("bliProteinSearch").value.trim();
  const dropdown = document.getElementById("bliSearchResults");
  if (!q) { dropdown.classList.add("hidden"); return; }
  if (!allProteins.length) allProteins = await API.get("/api/proteins");
  const matches = allProteins.filter(p =>
    p.name.toLowerCase().includes(q.toLowerCase())
  );
  if (!matches.length) {
    dropdown.innerHTML = '<div class="search-item" style="color:var(--graphite)">' + t("ui.no_match") + '</div>';
  } else {
    dropdown.innerHTML = matches.map(p => `
      <div class="search-item" onclick="addBliProtein(${p.id})">
        <strong>${esc(p.name)}</strong>
        ${bliProteins[p.id] ? `<span style="color:var(--cyan-deep)">✓ ${t("ui.added_chip")}</span>` : ''}
      </div>
    `).join("");
  }
  dropdown.classList.remove("hidden");
}

document.addEventListener("click", function (e) {
  if (!e.target.closest("#bliProteinSearch") && !e.target.closest("#bliSearchResults")) {
    const d = document.getElementById("bliSearchResults");
    if (d) d.classList.add("hidden");
  }
});

function addBliProtein(id) {
  if (bliProteins[id]) return;
  const p = allProteins.find(x => x.id === id);
  if (!p) return;
  bliProteins[id] = { name: p.name, mw: p.mw, stock_uM: 50, start_uM: 10, factor: 2, steps: 8, vol: 200, dead: 5 };
  document.getElementById("bliProteinSearch").value = "";
  document.getElementById("bliSearchResults").classList.add("hidden");
  renderBliTable();
}

function removeBliProtein(id) {
  delete bliProteins[id];
  renderBliTable();
  document.getElementById("bliResults").innerHTML = "";
}

// ── Render BLI table ────────────────────────────────
function renderBliTable() {
  const tbody = document.querySelector("#bliTable tbody");
  const ids = Object.keys(bliProteins);
  if (!ids.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="8">' + t("workbench.empty_dil") + '</td></tr>';
    return;
  }
  tbody.innerHTML = ids.map(id => {
    const b = bliProteins[id];
    return `
      <tr data-bli-protein-id="${id}">
        <td>${esc(b.name)}</td>
        <td><input type="number" class="cell-input bli-stock" step="any" value="${b.stock_uM}" style="width:90px"></td>
        <td><input type="number" class="cell-input bli-start" step="any" value="${b.start_uM}" style="width:80px"></td>
        <td><input type="number" class="cell-input bli-factor" step="any" value="${b.factor}" style="width:60px"></td>
        <td><input type="number" class="cell-input bli-nsteps" value="${b.steps}" min="2" max="24" style="width:55px"></td>
        <td><input type="number" class="cell-input bli-vol" step="any" value="${b.vol}" style="width:70px"></td>
        <td><input type="number" class="cell-input bli-dead" step="any" value="${b.dead}" style="width:65px"></td>
        <td><button class="btn btn-sm btn-icon btn-danger" onclick="removeBliProtein(${id})" aria-label="${esc(t("common.delete"))}">${iconClose()}</button></td>
      </tr>
    `;
  }).join("");
}

// ── Read BLI params from DOM ─────────────────────────
function readBliRow(row) {
  const get = (cls, parseFn) => {
    const el = row.querySelector("." + cls);
    return el ? parseFn(el.value) : null;
  };
  return {
    stock: get("bli-stock", parseFloat),
    start: get("bli-start", parseFloat),
    factor: get("bli-factor", parseFloat),
    nsteps: get("bli-nsteps", v => parseInt(v)),
    vol: get("bli-vol", parseFloat),
    dead: get("bli-dead", parseFloat),
  };
}

// ── Calculate BLI for one row ────────────────────────
async function calcBliOneRow(row) {
  const id = row.dataset.bliProteinId;
  const p = bliProteins[id];
  if (!p) return null;
  const v = readBliRow(row);
  // Save params
  p.stock_uM = v.stock; p.start_uM = v.start; p.factor = v.factor;
  p.steps = v.nsteps; p.vol = v.vol; p.dead = v.dead;

  if (isNaN(v.stock) || isNaN(v.start) || isNaN(v.factor) || isNaN(v.nsteps) || isNaN(v.vol)) {
    return { error: t("toast.params_incomplete") };
  }
  try {
    return await API.post("/api/calc/dilution", {
      stock_conc_uM: v.stock,
      start_conc_uM: v.start,
      dilution_factor: v.factor,
      n_steps: v.nsteps,
      vol_per_well_uL: v.vol,
      dead_vol_uL: Number.isFinite(v.dead) && v.dead >= 0 ? v.dead : 0,
    });
  } catch (err) {
    return { error: err.message };
  }
}

async function calcAllBliRows() {
  const rows = document.querySelectorAll("#bliTable tbody tr[data-bli-protein-id]");
  if (!rows.length) { toast(t("toast.add_protein_first"), true); return; }
  const results = {};
  for (const row of rows) {
    const r = await calcBliOneRow(row);
    if (r) results[row.dataset.bliProteinId] = r;
  }
  renderBliResults(results);
  toast(t("toast.bli_calc_done"));
}

// ── Render BLI results ───────────────────────────────
let _lastBliResults = null;  // 缓存最近结果，切换单位时直接重渲染（不再调 API）

function renderBliResults(results) {
  _lastBliResults = results;
  const container = document.getElementById("bliResults");
  const ids = Object.keys(results);
  if (!ids.length) { container.innerHTML = ""; return; }

  let html = "";
  for (const id of ids) {
    const r = results[id];
    const p = bliProteins[id];
    if (!p) continue;  // 蛋白已被移除但缓存里还有结果——跳过，避免下面 p.name 抛错
    if (r.error) {
      html += `<div class="result-box" style="margin-bottom:12px"><strong>${esc(p.name)}</strong>: ${esc(r.error)}</div>`;
      continue;
    }
    const totalStock = r.steps.reduce((s, st) => s + st.stock_vol_uL, 0);
    const totalBuffer = r.steps.reduce((s, st) => s + st.buffer_vol_uL, 0);
    // 步骤浓度列按所选单位显示（保存仍为 µM）；缺 mw 无法跨 kind 时显示 "-"（避免 µM 数值挂在 mg/mL 表头下）
    const mw = bliProteins[id]?.mw;
    const fmtConc = (uM) => {
      try { return formatConc(convertConc(uM, "uM", dilUnit, mw), dilUnit); }
      catch { return "-"; }
    };
    html += `
      <div class="result-box" style="margin-bottom:14px">
        <strong>${esc(p.name)}</strong> (${t("workbench.stock_c")} ${r.stock_conc_uM} μM, ${r.dilution_factor}×, ${r.n_steps} ${t("workbench.steps")})
        <div class="table-scroll"><table class="calc-table" style="margin-top:6px"><thead><tr><th>#</th><th>${t("workbench.col_conc")} (${dilUnit})</th><th>${t("workbench.total_vol")}</th><th>${t("workbench.from_prev")}</th><th>${t("workbench.col_buffer")}</th></tr></thead>
        <tbody>${r.steps.map(s => `
          <tr><td>${s.step}</td><td>${fmtConc(s.conc_uM)}</td><td>${s.total_vol_uL}</td><td>${s.stock_vol_uL}</td><td>${s.buffer_vol_uL}</td></tr>
        `).join("")}</tbody></table></div>
        <p style="margin-top:6px;font-size:13px;color:var(--graphite)">${t("detail.first_demand", { v: r.steps[0].total_vol_uL })}</p>
      </div>`;
  }
  container.innerHTML = html;
}

// BLI 稀释单位切换：更新全局单位 → 用缓存结果重渲染
function changeDilUnit() {
  const sel = document.getElementById("dilUnitSel");
  dilUnit = sel ? sel.value : "uM";
  localStorage.setItem("dilUnit", dilUnit);
  if (_lastBliResults) renderBliResults(_lastBliResults);
}

// ── Save BLI table as experiment ─────────────────────
async function saveBliTable() {
  const ids = Object.keys(bliProteins);
  if (!ids.length) { toast(t("toast.add_protein_and_calc"), true); return; }
  // 收集最新参数 + 结果
  const rows = document.querySelectorAll("#bliTable tbody tr[data-bli-protein-id]");
  const proteins = [];
  const dilutionResults = {};
  for (const row of rows) {
    const id = row.dataset.bliProteinId;
    const p = bliProteins[id];
    if (!p) continue;
    const v = readBliRow(row);
    // 重新计算以生成最新结果
    try {
      const r = await API.post("/api/calc/dilution", {
        stock_conc_uM: v.stock, start_conc_uM: v.start,
        dilution_factor: v.factor, n_steps: v.nsteps,
        vol_per_well_uL: v.vol, dead_vol_uL: Number.isFinite(v.dead) && v.dead >= 0 ? v.dead : 0,
      });
      dilutionResults[id] = r;
      p.stock_uM = v.stock; p.start_uM = v.start;
      p.factor = v.factor; p.steps = v.nsteps;
      p.vol = v.vol; p.dead = v.dead;
    } catch (err) {
      toast(`${p.name}: ${err.message}`, true);
      return;
    }
    proteins.push({
      id: Number(id), name: p.name, mw: p.mw,
      stock_uM: p.stock_uM, start_uM: p.start_uM,
      factor: p.factor, steps: p.steps,
      vol: p.vol, dead: p.dead,
    });
  }
  const customName = document.getElementById("bliExpName").value.trim();
  const title = customName || await getAutoName("BLI", null, "dilution")
    || Object.values(bliProteins).map(p => p.name).join(", ") + " BLI dilution";

  const goal = await promptGoalAttach();
  if (goal === null) { toast(t("toast.save_cancelled")); return; }

  try {
    const saved = await API.post("/api/experiments/from-calculation", {
      title: title,
      exp_type: "BLI",
      protein_ids: ids.map(Number),
      date: todayLocal(),
      calc_type: "dilution",
      calc_params: { proteins },
      calc_result: dilutionResults,
      ...goal,
    });
    renderBliResults(dilutionResults);
    toast(saved.goal_node_id ? t("toast.saved_linked") : t("toast.saved_record"));
  } catch (err) { toast(err, true); }
}


// helper: safe JSON parse
function safeJson(s) {
  try { return JSON.parse(s); } catch (_) { return {}; }
}

// 取实验**最新**一条原始快照 id（_raws 按 id 升序 = 创建序，最后一条=最近一次分析）。
// 多次重挂/重分析后应载入最新状态（旧快照保留可复现，但计算入口看当前）。
// dataType 给定时优先取该类型的最新一条——重挂可能往同一实验追加别的类型的 raw
// （如酶活实验被 BLI 分析重挂），直接取整体最后一条会拿到类型不符的 payload。
function latestRawId(exp, dataType) {
  const raws = (exp && exp._raws) || [];
  if (raws.length) {
    const pool = dataType ? raws.filter(r => (r.data_type || "") === dataType) : raws;
    return (pool.length ? pool : raws).slice(-1)[0].id;
  }
  const ids = (exp && exp._raw_ids) || [];   // 兼容无 _raws 的旧响应
  return ids[ids.length - 1];
}

// AKTA 判定：新存档靠 params.calc_type=="akta"，旧存档（v0.0.9 早期无 calc_type）靠 exp_type 兜底
function isAktaExp(e) {
  const params = typeof e.params === "string" ? safeJson(e.params) : e.params || {};
  return params.calc_type === "akta" || (e.exp_type || "").indexOf("AKTA") >= 0;
}

// BLI 分析判定：新存档靠 params.calc_type=="bli_fit"；旧存档（v0.0.8 无 calc_type）
// 靠 exp_type=="BLI" + results.samples 判别（排除 calc_type=dilution 的浓度梯度）
function isBliExp(e) {
  const params = typeof e.params === "string" ? safeJson(e.params) : e.params || {};
  if (params.calc_type === "bli_fit") return true;
  if (params.calc_type === "dilution") return false;
  if ((e.exp_type || "").indexOf("BLI") >= 0) {
    const results = typeof e.results === "string" ? safeJson(e.results) : e.results || {};
    return !!(results && results.samples);
  }
  return false;
}

async function applyCopyAndSwitch() {
  if (!copyCache) { toast(t("toast.pick_experiment"), true); return; }
  const params = typeof copyCache.params === "string" ? JSON.parse(copyCache.params) : copyCache.params || {};
  const calcType = params.calc_type || "";

  if (calcType === "enzyme") {
    // 复制到酶活 Tab — 曲线优先从**原始快照**重建（逐点数据只在 experiment_raw，契约规则 A），
    // 手动参数从快照 payload.params 回填（规则 B）。
    const pWells = params.wells || params.well_info || {};
    let emeta = params.meta || {};
    let srcWells = null, rParams = null, lo = null, hi = null, nPoints = 0;
    let rawFailed = false;
    const rid = latestRawId(copyCache, "enzyme_traces");
    if (rid) {
      try {
        const raw = await API.get(`/api/experiments/${copyCache.id}/raw/${rid}`);
        const data = await API.post("/api/enzyme/restore", { payload: raw.payload });
        if (Object.keys(data.wells || {}).length) {
          srcWells = data.wells;
          emeta = data.meta || emeta;
          rParams = data.params || {};
          lo = data.time_lo; hi = data.time_hi; nPoints = data.n_points;
          if (data.version_warning) toast(data.version_warning);
        }
      } catch (err) { rawFailed = true; toast(err, true); }
    }
    if (!srcWells) {
      // 兜底①：老库的 params.wells 可能仍内嵌逐点（未跑 tools/strip_params_pointdata.py）。
      // 那是**被当时时间窗截断后**的曲线，不是全量——必须说清楚，别让人以为拿到的是原始数据。
      srcWells = {};
      for (const [id, w] of Object.entries(pWells)) {
        if (w.times && w.od) srcWells[id] = { times: w.times, od: w.od };
      }
      if (Object.keys(srcWells).length) {
        toast(t("toast.enzyme_from_params"));
      } else if (!rawFailed) {
        // 兜底②：真的没有原始快照（或快照内无曲线）。**显式报错**，不静默给一张空图。
        toast(t("toast.enzyme_no_raw"), true);
      }
      // rawFailed 时上面的 err toast 已说明原因，不再叠一条
    }

    enzymeData = { meta: emeta, wells: {} };
    enzymeWellInfo = {};
    enzymeSelection.clear();
    for (const [id, w] of Object.entries(pWells)) {
      enzymeWellInfo[id] = {
        name: w.name,
        ref: w.ref,
        group: w.group || "",
        protein_id: w.protein_id,
        mw: w.mw ?? null,
        conc_ng_ml: w.conc_ng_ml,
        conc_uM: w.conc_uM,
        fit: w.fit,
      };
    }
    for (const [id, w] of Object.entries(srcWells)) {
      enzymeData.wells[id] = { times: w.times, od: w.od };
      if (!enzymeWellInfo[id]) enzymeWellInfo[id] = { name: w.name, ref: w.ref };
    }
    // 时间范围筛选：重建时间面板 + 回填存档的时间窗（秒值对 → 服务端已换算成网格下标）
    enzymeTimePoints = [...new Set(emeta.temps || Object.values(enzymeData.wells)[0]?.times || [])].sort((a, b) => a - b);
    const nT = enzymeTimePoints.length;
    enzymeTimeLo = nT && lo != null ? Math.max(0, Math.min(nT - 1, lo)) : 0;
    enzymeTimeHi = nT && hi != null ? Math.max(0, Math.min(nT - 1, hi)) : nT - 1;
    enzymeLastImage = null;
    enzymeLastPlotType = null;
    enzymeSourceFile = "";
    renderEnzymeTimePanel();
    if (rParams) enzymeBackfillParams(rParams);   // 六个开关 + source_file
    else if (params.source_file) enzymeSourceFile = params.source_file;
    document.getElementById("enzymeMeta").textContent =
      `${emeta.sample || ""} | ${emeta.wavelength || "?"} nm | ${t("copy.wells_n", { n: Object.keys(enzymeWellInfo).length })}` +
      (nPoints ? ` | ${t("copy.points_n", { n: nPoints })}` : "") +
      ` (${rParams ? t("copy.from_snapshot") : t("copy.copied")})`;
    renderPlate();
    if (Object.values(enzymeWellInfo).some(i => i.fit)) {
      renderEnzymeTable(Object.keys(enzymeWellInfo));
    }
    document.querySelector(".tab-btn[data-tab='enzyme']").click();
    toast(t("toast.loaded_wells", { n: Object.keys(enzymeData.wells).length }));
    return;
  }

  if (calcType === "dilution") {
    // 复制到 BLI Tab
    const proteins = params.proteins || [];
    for (const p of proteins) {
      const pid = String(p.id);
      if (!bliProteins[pid]) {
        bliProteins[pid] = {
          name: p.name,
          mw: p.mw || selectedProteins[pid]?.mw || allProteins.find(x => String(x.id) === pid)?.mw,
          stock_uM: p.stock_uM || 50,
          start_uM: p.start_uM || 10,
          factor: p.factor || 2,
          steps: p.steps || 8,
          vol: p.vol || 200,
          dead: p.dead || 0,
        };
      }
    }
    renderBliTable();
    document.querySelector(".tab-btn[data-tab='dilution']").click();
    toast(t("toast.loaded_proteins", { n: proteins.length }));
    return;
  }

  if (isBliExp(copyCache)) {
    // 复制到 BLI 分析 Tab — 从实验原始快照重建会话（曲线数据在 experiment_raw，规则 #8 可复现）
    const rid = latestRawId(copyCache, "bli_curves");
    if (!rid) { toast(t("toast.no_raw_snapshot"), true); return; }
    try {
      const raw = await API.get(`/api/experiments/${copyCache.id}/raw/${rid}`);
      const data = await API.post("/api/bli/restore", {
        payload: raw.payload,
        name: copyCache.title || params.source || "restored",
      });
      bliSession = data.session_id;
      bliSamples = data.samples || [];
      bliSelectedSample = bliSamples[0]?.sample || "";
      bliLastPlot = null;
      bliKdResult = null;
      bliActiveCurves = new Set(bliSamples.flatMap(s => s.labels || []));  // 默认全选，下面按存档子集回填
      bliBackfillParams(raw.payload.params);   // 回填存档参数（含 active_curves/trim_start），出图/拟合按同参数复现
      renderBliSamples();
      renderBliCurves();
      // 揭示分析结果区（与上传路径一致：bliSampleList 在 #bliAnalyzed 内，默认 hidden）
      document.getElementById("bliMeta").textContent =
        `${copyCache.title || t("toast.saved")} | ${t("workbench.sensors_n", { n: data.n_sensors })} | ${t("copy.samples_n", { n: bliSamples.length })}`;
      document.getElementById("bliAnalyzed").classList.remove("hidden");
      document.getElementById("bliKdWrap").classList.add("hidden");
      document.getElementById("bliPlotArea").innerHTML = "";
      refreshBliPlaceholder();
      document.querySelector(".tab-btn[data-tab='bli']").click();
      bliPlot();
      toast(t("toast.loaded_bli_samples", { n: bliSamples.length }));
    } catch (err) { toast(err, true); }
    return;
  }

  if (isAktaExp(copyCache)) {
    // 复制到 AKTA Tab — 从实验原始快照重建会话（曲线数据在 experiment_raw）
    const rid = latestRawId(copyCache, "akta_traces");
    if (!rid) { toast(t("toast.no_raw_snapshot"), true); return; }
    try {
      const raw = await API.get(`/api/experiments/${copyCache.id}/raw/${rid}`);
      const data = await API.post("/api/akta/restore", {
        payload: raw.payload,
        name: copyCache.title || params.source || params.channel || "restored",
      });
      const run = data.runs[0];
      aktaRuns = [{
        ...run,
        channel: run.uv_channels[0] || run.channels[0]?.name || "",
        target_peak: 0,
        checked: true,
      }];
      aktaCurrentRun = 0;
      aktaBackfillParams(raw.payload.params);   // 回填存档峰检测参数
      renderAktaRuns();
      // 揭示分析结果区（与上传路径一致：aktaRunList 在 #aktaAnalyzed 内，默认 hidden）
      document.getElementById("aktaMeta").textContent =
        `${t("workbench.files_ok", { n: 1, ok: 1 })} | ${t("workbench.channels_n", { n: run.channels.length })}`;
      document.getElementById("aktaEventsInfo").textContent = "";
      document.getElementById("aktaAnalyzed").classList.remove("hidden");
      document.getElementById("aktaPeakTableWrap").classList.add("hidden");
      document.getElementById("aktaPlotArea").innerHTML = "";
      refreshAktaPlaceholder();
      document.querySelector(".tab-btn[data-tab='akta']").click();
      aktaPlot();
      toast(t("toast.loaded_akta_channels", { n: run.channels.length }));
    } catch (err) { toast(err, true); }
    return;
  }

  // 默认: 浓度实验 → Tab 1
  if (!copyCache.protein_ids) { toast(t("toast.no_proteins_to_copy"), true); return; }
  if (!allProteins.length) {
    allProteins = await API.get("/api/proteins");
  }
  copyCache.protein_ids.forEach(id => addProteinToTable(id));
  if (params.proteins) {
    params.proteins.forEach(pp => {
      const sp = selectedProteins[pp.id];
      if (!sp) return;
      if (pp.a280 != null) sp._a280 = pp.a280;
      if (pp.path != null) sp._path = pp.path;
      if (pp.conc_uM != null) sp._conc_uM = pp.conc_uM;
      if (pp.conc_mg_mL != null) sp._conc_mg = pp.conc_mg_mL;
      if (pp.target_conc != null) sp._targetConc = pp.target_conc;
      if (pp.target_vol != null) sp._targetVol = pp.target_vol;
      if (pp.take_vol != null) sp._takeVol = pp.take_vol;
      if (pp.buffer_vol != null) sp._bufferVol = pp.buffer_vol;
    });
    renderTable();
  }
  document.querySelector(".tab-btn[data-tab='conc']").click();
  toast(t("toast.loaded_protein_list"));
}

// 详情页「载入计算工具」深链：/calculator?load_exp=<id> → 把该实验载入对应计算 tab
// （复用载入引擎 applyCopyAndSwitch：BLI/AKTA 读最新 raw 快照重建会话，酶活/浓度读 params 重建）
async function loadExpIntoCalc(expId) {
  try {
    const exp = await API.get(`/api/experiments/${expId}`);
    if (!exp || exp.error) { toast(t("toast.load_exp_failed"), true); return; }
    copyCache = exp;
    await applyCopyAndSwitch();
  } catch (err) { toast(err.backend ? err : backendError(null, 0, err.message || t("toast.load_exp_failed")), true); }
}

