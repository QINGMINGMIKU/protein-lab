// ═════════════════════════════════════════════════════
//  Protein Lab — Frontend
// ═════════════════════════════════════════════════════

const API = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`请求失败 (${r.status})`);
    return r.json();
  },
  async post(url, data) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || `请求失败 (${r.status})`);
    return j;
  },
  async put(url, data) {
    const r = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || `请求失败 (${r.status})`);
    return j;
  },
  async del(url) {
    const r = await fetch(url, { method: "DELETE" });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw new Error(j.error || `删除失败 (${r.status})`);
    }
  },
};

// ── Safe HTML escaping ──────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/\\/g, "&#92;");
}
function escAttr(s) { return esc(s); }

// ── Toast ────────────────────────────────────────────
function toast(msg, error) {
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2500);
}

// ── Delegated click handler ──────────────────────────
document.addEventListener("click", function (e) {
  const target = e.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const id = target.dataset.id ? parseInt(target.dataset.id) : null;
  const name = target.dataset.name || "";
  switch (action) {
    case "show-detail":    showDetail(id); break;
    case "delete-protein": deleteProtein(id, name); break;
    case "show-exp":       showExpDetail(id); break;
    case "delete-exp":     deleteExp(id); break;
  }
});

// ═════════════════════════════════════════════════════
//  Proteins Page
// ═════════════════════════════════════════════════════

let currentDetailProtein = null;  // track which protein is shown in detail

async function loadProteins() {
  const tbody = document.querySelector("#proteinTable tbody");
  if (!tbody) return;
  try {
    const q = document.getElementById("searchBox")?.value || "";
    const proteins = await API.get(`/api/proteins?q=${encodeURIComponent(q)}`);
    tbody.innerHTML = proteins.map(p => `
      <tr>
        <td><span class="clickable" data-action="show-detail" data-id="${p.id}">${esc(p.name)}</span></td>
        <td>${p.mw ? p.mw.toLocaleString() : "-"}</td>
        <td>${p.ext_ox || "-"}</td>
        <td>${p.abs_0_1pct ?? "-"}</td>
        <td>${esc(p.tag || "")}</td>
        <td><span class="seq-preview" onclick="this.classList.toggle('expanded')" title="点击展开/收起">${esc(p.sequence)}</span></td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-protein" data-id="${p.id}" data-name="${escAttr(p.name)}">删除</button></td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="color:#c0392b;text-align:center;padding:20px">加载失败: ${esc(err.message)}</td></tr>`;
  }
}

async function refreshAllProteins() {
  if (!confirm("将用当前算法重新计算所有蛋白的 MW 和消光系数，确定？")) return;
  try {
    const r = await API.post("/api/proteins/refresh-all", {});
    toast(`已刷新 ${r.refreshed} 条蛋白`);
    loadProteins();
    loadProteinSelects();
  } catch (err) { toast(err.message, true); }
}

function showAddModal() { document.getElementById("addModal").classList.remove("hidden"); }
function closeAddModal() { document.getElementById("addModal").classList.add("hidden"); document.getElementById("addForm").reset(); }
function showImportModal() { document.getElementById("importModal").classList.remove("hidden"); }
function closeImportModal() {
  document.getElementById("importModal").classList.add("hidden");
  document.getElementById("importForm").reset();
  document.querySelector("#importForm textarea[name=fasta]").removeAttribute("required");
}

function loadFastaFile() {
  const file = document.getElementById("fastaFile").files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function () {
    const textarea = document.querySelector("#importForm textarea[name=fasta]");
    textarea.value = reader.result;
    textarea.removeAttribute("required");
    toast(`已加载: ${file.name}`);
  };
  reader.readAsText(file);
}

async function addProtein(e) {
  e.preventDefault();
  const form = document.getElementById("addForm");
  const data = Object.fromEntries(new FormData(form));
  try {
    await API.post("/api/proteins", data);
    toast("蛋白已添加");
    closeAddModal();
    loadProteins();
    loadProteinSelects();
  } catch (err) { toast(err.message, true); }
}

async function deleteProtein(id, name) {
  if (!confirm(`确定删除 "${name}"？`)) return;
  try {
    await API.del(`/api/proteins/${id}`);
    toast("已删除");
    loadProteins();
    loadProteinSelects();
    closeDetail();
  } catch (err) { toast(err.message, true); }
}

async function importFasta(e) {
  e.preventDefault();
  const form = document.getElementById("importForm");
  const data = Object.fromEntries(new FormData(form));
  try {
    const result = await API.post("/api/proteins/import", {
      fasta: data.fasta, tag: data.tag, notes: data.notes,
    });
    toast(`导入了 ${result.imported.length} 条` +
      (result.skipped.length ? `，跳过 ${result.skipped.length} 条重复` : ""));
    closeImportModal();
    loadProteins();
    loadProteinSelects();
  } catch (err) { toast(err.message, true); }
}

async function showDetail(id) {
  try {
    const p = await API.get(`/api/proteins/${id}`);
    currentDetailProtein = p;
    document.getElementById("detailName").textContent = p.name;
    document.getElementById("detailCreateExpBtn").onclick = () => createExpFromProtein();
    document.getElementById("detailContent").innerHTML = `
      <dl class="info-grid">
        <dt>分子量</dt><dd>${p.mw ? p.mw.toLocaleString() + " Da" : "-"}</dd>
        <dt>Trp / Tyr / Cys</dt><dd>${p.nW} / ${p.nY} / ${p.nC}</dd>
        <dt>ε (还原态)</dt><dd>${p.ext_red || "-"} M⁻¹·cm⁻¹</dd>
        <dt>ε (氧化态)</dt><dd>${p.ext_ox || "-"} M⁻¹·cm⁻¹</dd>
        <dt>Abs[0.1%]</dt><dd>${p.abs_0_1pct ?? "-"}</dd>
        <dt>标签</dt><dd>${esc(p.tag || "-")}</dd>
        <dt>备注</dt><dd>${esc(p.notes || "-")}</dd>
      </dl>
      <div class="sequence-full">${esc(p.sequence)}</div>
    `;
    document.getElementById("detailPanel").classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
}

function closeDetail() {
  document.getElementById("detailPanel").classList.add("hidden");
  currentDetailProtein = null;
}

function createExpFromProtein() {
  if (!currentDetailProtein) return;
  // 跳转到实验页并预选该蛋白
  sessionStorage.setItem("prefill_exp_protein", JSON.stringify([currentDetailProtein.id]));
  sessionStorage.setItem("prefill_exp_protein_names", currentDetailProtein.name);
  window.location.href = "/experiments";
}

async function loadProteinSelects() {
  try {
    const proteins = await API.get("/api/proteins");
    const options = proteins.map(p =>
      `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    ["concProtein", "dilProtein"].forEach(id => {
      const sel = document.getElementById(id);
      if (sel) sel.innerHTML = `<option value="">${id === "dilProtein" ? "-- 可选 --" : "-- 选择蛋白 --"}</option>${options}`;
    });
    // 实验页多选 checkbox
    const container = document.getElementById("proteinCheckboxes");
    if (container) {
      container.innerHTML = proteins.map(p =>
        `<label class="checkbox-label"><input type="checkbox" name="protein_ids" value="${p.id}"> ${esc(p.name)}</label>`
      ).join("");
    }
  } catch (_) { /* 非关键 */ }
}


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

document.addEventListener("click", function (e) {
  const tab = e.target.closest(".tab-btn");
  if (!tab) return;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
  tab.classList.add("active");
  document.getElementById("tab-" + tab.dataset.tab).classList.remove("hidden");
  if (tab.dataset.tab === "copy") loadCopyExpList();
  if (tab.dataset.tab === "dilution") loadBliImportExps();
});

// ═════════════════════════════════════════════════════
//  Tab 1: Protein concentration multi-table
// ═════════════════════════════════════════════════════

let selectedProteins = {};  // { id: { name, mw, ext_ox, abs_0_1pct, ... } }
let allProteins = [];
let copyCache = null;       // cached experiment data for copy tab

async function searchProteins() {
  const q = document.getElementById("proteinSearch").value.trim();
  const dropdown = document.getElementById("searchResults");
  if (!q) { dropdown.classList.add("hidden"); return; }

  if (!allProteins.length) {
    allProteins = await API.get("/api/proteins");
  }
  const matches = allProteins.filter(p =>
    p.name.toLowerCase().includes(q.toLowerCase())
    || (p.tag || "").toLowerCase().includes(q.toLowerCase())
  );

  if (!matches.length) {
    dropdown.innerHTML = '<div class="search-item" style="color:#888">无匹配结果</div>';
  } else {
    dropdown.innerHTML = matches.map(p => `
      <div class="search-item" onclick="addProteinToTable(${p.id})">
        <strong>${esc(p.name)}</strong>
        <span style="color:#888;font-size:12px">${p.mw ? p.mw.toLocaleString() + ' Da' : ''} | ε=${p.ext_ox || 0}</span>
        ${selectedProteins[p.id] ? '<span style="color:#27ae60">✓ 已选</span>' : ''}
      </div>
    `).join("");
  }
  dropdown.classList.remove("hidden");
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
    container.innerHTML = '<span style="color:#888;font-size:13px">搜索并添加蛋白...</span>';
    return;
  }
  container.innerHTML = ids.map(id => {
    const p = selectedProteins[id];
    return `<span class="chip">${esc(p.name)} <button class="chip-x" onclick="removeProteinFromTable(${id})">✕</button></span>`;
  }).join("");
}

function renderTable() {
  const tbody = document.querySelector("#concTable tbody");
  const ids = Object.keys(selectedProteins);
  if (!ids.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="13">请在上方搜索并添加蛋白</td></tr>';
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
        <td><button class="btn btn-sm btn-danger" onclick="removeProteinFromTable(${id})">✕</button></td>
      </tr>
    `;
  }).join("");
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

  row.querySelector(".conc-uM").textContent = conc_uM;
  row.querySelector(".conc-mg").textContent = conc_mg;

  // 目标浓度稀释
  const targetConc = parseFloat(row.querySelector(".target-conc").value);
  const targetVol = parseFloat(row.querySelector(".target-vol").value);

  if (!isNaN(targetConc) && !isNaN(targetVol) && targetConc > 0 && targetVol > 0) {
    p._targetConc = targetConc; p._targetVol = targetVol;
    if (targetConc > conc_uM) {
      row.querySelector(".vol-take").innerHTML = '<span style="color:#e74c3c">目标>当前</span>';
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
  if (!anyError) toast("全部计算完成");
}

async function saveConcTable() {
  const ids = Object.keys(selectedProteins);
  if (!ids.length) { toast("请先添加蛋白", true); return; }
  const customName = document.getElementById("concExpName").value.trim();
  const title = customName || ids.map(id => selectedProteins[id].name).join(", ") + " 浓度测定";
  const oxidized = getCurrentOxidized();

  try {
    await API.post("/api/experiments/from-calculation", {
      title: title,
      exp_type: "浓度测定",
      protein_ids: ids.map(Number),
      date: new Date().toISOString().slice(0, 10),
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
    });
    toast("已保存为实验记录");
  } catch (err) { toast(err.message, true); }
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
    sel.innerHTML = '<option value="">-- 从浓度实验导入 --</option>' +
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
    if (!proteins.length) { toast("该实验无蛋白数据", true); return; }

    let added = 0;
    for (const prot of proteins) {
      if (!prot || !prot.id) continue;
      const pid = String(prot.id);
      if (bliProteins[pid]) continue;  // 已有

      const conc_uM = prot.conc_uM;
      if (conc_uM == null || isNaN(conc_uM)) continue;

      bliProteins[pid] = {
        name: prot.name || "",
        stock_uM: conc_uM,
        start_uM: Math.min(conc_uM, 10),
        factor: 2,
        steps: 8,
        vol: 200,
        dead: 0,
      };
      added++;
    }
    if (!added) { toast("所有蛋白已存在或浓度无效", true); return; }
    renderBliTable();
    toast(`已导入 ${added} 个蛋白`);
  } catch (err) { toast(err.message, true); }
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
    dropdown.innerHTML = '<div class="search-item" style="color:#888">无匹配结果</div>';
  } else {
    dropdown.innerHTML = matches.map(p => `
      <div class="search-item" onclick="addBliProtein(${p.id})">
        <strong>${esc(p.name)}</strong>
        ${bliProteins[p.id] ? '<span style="color:#27ae60">✓ 已添加</span>' : ''}
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
  bliProteins[id] = { name: p.name, stock_uM: 50, start_uM: 10, factor: 2, steps: 8, vol: 200, dead: 5 };
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
    tbody.innerHTML = '<tr class="empty-row"><td colspan="8">请从浓度表导入蛋白，或在上方搜索添加</td></tr>';
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
        <td><button class="btn btn-sm btn-danger" onclick="removeBliProtein(${id})">✕</button></td>
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
    return { error: "参数不完整" };
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
  if (!rows.length) { toast("请先添加蛋白", true); return; }
  const results = {};
  for (const row of rows) {
    const r = await calcBliOneRow(row);
    if (r) results[row.dataset.bliProteinId] = r;
  }
  renderBliResults(results);
  toast("BLI 计算完成");
}

// ── Render BLI results ───────────────────────────────
function renderBliResults(results) {
  const container = document.getElementById("bliResults");
  const ids = Object.keys(results);
  if (!ids.length) { container.innerHTML = ""; return; }

  let html = "";
  for (const id of ids) {
    const r = results[id];
    const p = bliProteins[id];
    if (r.error) {
      html += `<div class="result-box" style="margin-bottom:12px"><strong>${esc(p.name)}</strong>: ${esc(r.error)}</div>`;
      continue;
    }
    const totalStock = r.steps.reduce((s, st) => s + st.stock_vol_uL, 0);
    const totalBuffer = r.steps.reduce((s, st) => s + st.buffer_vol_uL, 0);
    html += `
      <div class="result-box" style="margin-bottom:14px">
        <strong>${esc(p.name)}</strong> (母液 ${r.stock_conc_uM} μM, ${r.dilution_factor}× 稀释, ${r.n_steps} 步)
        <table style="margin-top:6px"><thead><tr><th>#</th><th>浓度 (μM)</th><th>总体积 (μL)</th><th>取上步 (μL)</th><th>缓冲液 (μL)</th></tr></thead>
        <tbody>${r.steps.map(s => `
          <tr><td>${s.step}</td><td>${s.conc_uM}</td><td>${s.total_vol_uL}</td><td>${s.stock_vol_uL}</td><td>${s.buffer_vol_uL}</td></tr>
        `).join("")}</tbody></table>
        <p style="margin-top:6px;font-size:13px;color:#666">第一步总需求 ≈ ${r.steps[0].total_vol_uL} μL（含递推稀释裕量）</p>
      </div>`;
  }
  container.innerHTML = html;
}

// ── Save BLI table as experiment ─────────────────────
async function saveBliTable() {
  const ids = Object.keys(bliProteins);
  if (!ids.length) { toast("请先添加蛋白并计算", true); return; }
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
      id: Number(id), name: p.name,
      stock_uM: p.stock_uM, start_uM: p.start_uM,
      factor: p.factor, steps: p.steps,
      vol: p.vol, dead: p.dead,
    });
  }
  const customName = document.getElementById("bliExpName").value.trim();
  const title = customName || Object.values(bliProteins).map(p => p.name).join(", ") + " BLI 稀释";

  try {
    await API.post("/api/experiments/from-calculation", {
      title: title,
      exp_type: "BLI",
      protein_ids: ids.map(Number),
      date: new Date().toISOString().slice(0, 10),
      calc_type: "dilution",
      calc_params: { proteins },
      calc_result: dilutionResults,
    });
    renderBliResults(dilutionResults);
    toast("已保存为实验记录");
  } catch (err) { toast(err.message, true); }
}

// ═════════════════════════════════════════════════════
//  Tab 3: Copy from experiment
// ═════════════════════════════════════════════════════

async function loadCopyExpList() {
  const sel = document.getElementById("copyExpSelect");
  if (sel.options.length > 1) return;  // already loaded
  const exps = await API.get("/api/experiments?limit=50");
  sel.innerHTML = '<option value="">-- 选择实验 --</option>' +
    exps.map(e => `<option value="${e.id}">${esc(e.title)} (${e.date || ""})</option>`).join("");
}

async function loadExpForCopy() {
  const expId = document.getElementById("copyExpSelect").value;
  if (!expId) return;
  const e = await API.get(`/api/experiments/${expId}`);
  copyCache = e;
  document.getElementById("copySummary").textContent =
    `实验: ${e.title} | 类型: ${e.exp_type} | 蛋白: ${e.protein_names || "无"} | 日期: ${e.date}`;
  document.getElementById("copyPreview").classList.remove("hidden");
}

async function applyCopyAndSwitch() {
  if (!copyCache || !copyCache.protein_ids) { toast("无蛋白数据可复制", true); return; }
  if (!allProteins.length) {
    allProteins = await API.get("/api/proteins");
  }
  copyCache.protein_ids.forEach(id => addProteinToTable(id));
  // 预填 A280
  const params = typeof copyCache.params === "string" ? JSON.parse(copyCache.params) : copyCache.params;
  if (params && params.proteins) {
    params.proteins.forEach(pp => {
      if (selectedProteins[pp.id] && pp.a280) {
        selectedProteins[pp.id]._a280 = pp.a280;
      }
    });
    renderTable();
  }
  document.querySelector(".tab-btn[data-tab='conc']").click();
  toast("已加载蛋白列表，可修改 A280 后重新计算");
}

// ═════════════════════════════════════════════════════
//  Experiments Page
// ═════════════════════════════════════════════════════

async function loadExperiments() {
  const tbody = document.querySelector("#expTable tbody");
  if (!tbody) return;
  updateExportLink();
  try {
    const type = document.getElementById("expTypeFilter")?.value || "";
    const exps = await API.get(`/api/experiments?type=${encodeURIComponent(type)}`);
    tbody.innerHTML = exps.map(e => `
      <tr>
        <td>${e.date || "-"}</td>
        <td><span class="clickable" data-action="show-exp" data-id="${e.id}">${esc(e.title)}</span></td>
        <td><span class="badge">${esc(e.exp_type)}</span></td>
        <td>${esc(e.protein_names || "-")}</td>
        <td>${esc((e.notes || "").substring(0, 40))}</td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-exp" data-id="${e.id}">删除</button></td>
        <td><a class="btn btn-sm btn-outline" href="/api/experiments/${e.id}/export" title="导出此实验">📥</a></td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:#c0392b;text-align:center;padding:20px">加载失败: ${esc(err.message)}</td></tr>`;
  }
}

function showExpAddModal(prefill = null) {
  document.getElementById("expModalTitle").textContent = prefill?.title || "新建实验";
  document.getElementById("expModal").classList.remove("hidden");
  if (prefill) {
    document.getElementById("expTitle").value = prefill.title || "";
    document.getElementById("expType").value = prefill.exp_type || "";
    document.getElementById("expDate").value = prefill.date || new Date().toISOString().slice(0, 10);
    document.getElementById("expParams").value = prefill.params || "";
    document.getElementById("expResults").value = prefill.results || "";
    document.getElementById("expNotes").value = prefill.notes || "";
    // 预选蛋白
    if (prefill.protein_ids) {
      document.querySelectorAll("#proteinCheckboxes input[type=checkbox]").forEach(cb => {
        cb.checked = prefill.protein_ids.includes(parseInt(cb.value));
      });
    }
  }
}

function closeExpModal() {
  document.getElementById("expModal").classList.add("hidden");
  document.getElementById("expForm").reset();
  document.querySelectorAll("#proteinCheckboxes input[type=checkbox]").forEach(cb => cb.checked = false);
}

async function saveExperiment(e) {
  e.preventDefault();
  const form = document.getElementById("expForm");
  const data = Object.fromEntries(new FormData(form));
  // 收集选中的蛋白
  const checked = document.querySelectorAll("#proteinCheckboxes input[type=checkbox]:checked");
  const proteinIds = Array.from(checked).map(cb => parseInt(cb.value));

  for (const k of ["params", "results"]) {
    try {
      data[k] = (data[k] && data[k].trim()) ? JSON.parse(data[k]) : {};
    } catch (_) {
      toast(`${k} 不是有效的 JSON`, true);
      return;
    }
  }
  try {
    await API.post("/api/experiments", {
      title: data.title, exp_type: data.exp_type,
      protein_ids: proteinIds, date: data.date,
      params: data.params, results: data.results, notes: data.notes,
    });
    toast("实验已保存");
    closeExpModal();
    loadExperiments();
  } catch (err) { toast(err.message, true); }
}

async function showExpDetail(id) {
  try {
    const e = await API.get(`/api/experiments/${id}`);
    const titleEl = document.getElementById("expDetailTitle");
    titleEl.innerHTML = `<span id="expDetailTitleText">${esc(e.title)}</span> <button class="btn btn-sm btn-outline" onclick="editExpTitle(${e.id})" style="margin-left:8px">✏️ 编辑</button>`;
    const paramsStr = JSON.stringify(e.params || {}, null, 2);
    const resultsStr = JSON.stringify(e.results || {}, null, 2);
    document.getElementById("expDetailContent").innerHTML = `
      <dl class="info-grid">
        <dt>类型</dt><dd>${esc(e.exp_type)}</dd>
        <dt>日期</dt><dd>${e.date || "-"}</dd>
        <dt>关联蛋白</dt><dd>${esc(e.protein_names || "无")}</dd>
        <dt>备注</dt><dd id="expDetailNotes">${esc(e.notes || "-")}</dd>
      </dl>
      <div style="margin-top:12px"><strong>实验参数</strong></div>
      <pre style="background:#f8f9fb;padding:10px;border-radius:6px;font-size:12px;max-height:150px;overflow:auto">${esc(paramsStr)}</pre>
      <div style="margin-top:8px"><strong>实验结果</strong></div>
      <pre style="background:#f8f9fb;padding:10px;border-radius:6px;font-size:12px;max-height:200px;overflow:auto">${esc(resultsStr)}</pre>
    `;
    document.getElementById("expDetailPanel").classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
}

async function editExpTitle(id) {
  const titleEl = document.getElementById("expDetailTitleText");
  const current = titleEl.textContent;
  const input = document.createElement("input");
  input.type = "text"; input.value = current;
  input.style.cssText = "font-size:18px;font-weight:600;padding:4px 8px;border:1px solid #d0d0d0;border-radius:4px;width:300px";
  titleEl.replaceWith(input);
  input.focus();
  input.onblur = input.onkeydown = async function (ev) {
    if (ev && ev.type === "keydown" && ev.key !== "Enter") return;
    const newTitle = input.value.trim() || current;
    try {
      await API.put(`/api/experiments/${id}`, { title: newTitle });
      toast("已更新");
    } catch (err) { toast(err.message, true); }
    showExpDetail(id);
  };
}

// Update export link with current filter
function updateExportLink() {
  const type = document.getElementById("expTypeFilter")?.value || "";
  const link = document.getElementById("exportBtn");
  if (link) link.href = "/api/experiments/export" + (type ? "?type=" + encodeURIComponent(type) : "");
}

function closeExpDetail() {
  document.getElementById("expDetailPanel").classList.add("hidden");
}

async function deleteExp(id) {
  if (!confirm("确定删除该实验记录？")) return;
  try {
    await API.del(`/api/experiments/${id}`);
    toast("已删除");
    loadExperiments();
  } catch (err) { toast(err.message, true); }
}

// ── Pre-fill from protein page ──────────────────────
function checkPrefill() {
  const prefill = sessionStorage.getItem("prefill_exp_protein");
  if (prefill) {
    const ids = JSON.parse(prefill);
    sessionStorage.removeItem("prefill_exp_protein");
    sessionStorage.removeItem("prefill_exp_protein_names");
    // 延迟等 checkbox 渲染完
    setTimeout(() => {
      showExpAddModal();
      ids.forEach(id => {
        const cb = document.querySelector(`#proteinCheckboxes input[value="${id}"]`);
        if (cb) cb.checked = true;
      });
    }, 300);
  }
}

// ═════════════════════════════════════════════════════
//  Init
// ═════════════════════════════════════════════════════
function init() {
  if (document.querySelector("#proteinTable")) {
    loadProteins().catch(() => {});
    loadProteinSelects();
  }
  if (document.querySelector("#expTable")) {
    loadExperiments().catch(() => {});
    loadProteinSelects();
    checkPrefill();
  }
  if (document.querySelector("#concTable") || document.querySelector("#proteinSearch")) {
    loadProteinSelects();
    restoreCalcState();
    // 保存状态：离开页面前
    window.addEventListener("beforeunload", saveCalcState);
  }
}
init();
