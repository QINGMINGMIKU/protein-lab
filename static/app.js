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

// ═════════════════════════════════════════════════════
//  浓度单位换算 kernel（隐藏能力：6 单位互转）
//  与 calculators.py 的 CONC_UNITS / convert_concentration 逐行镜像，改动时两边同步。
//  canonical 基准：molar→µM，mass→ng/µL；跨 kind（摩尔↔质量）需 mw (Da)。
// ═════════════════════════════════════════════════════
const CONC_UNITS = {
  M:     { kind: "molar", factor: 1e6 },
  uM:    { kind: "molar", factor: 1 },
  nM:    { kind: "molar", factor: 1e-3 },
  "mg/mL": { kind: "mass", factor: 1000 },
  "ug/mL": { kind: "mass", factor: 1 },
  "ng/uL": { kind: "mass", factor: 1 },
};

function convertConc(value, from, to, mw) {
  const f = CONC_UNITS[from], t = CONC_UNITS[to];
  if (!f || !t) throw new Error(`未知单位: ${from} / ${to}`);
  let base = value * f.factor;
  if (f.kind !== t.kind) {
    if (!mw || mw <= 0) throw new Error("跨摩尔/质量换算需要分子量 mw (Da)");
    base = f.kind === "molar" ? base * mw / 1000 : base * 1000 / mw;
  }
  return base / t.factor;
}

// 展示格式化：极小/极大值走科学计数，其余 toPrecision(4) 去尾零
function formatConc(value, unit) {
  if (value == null || !isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 0.01 || abs >= 1e5)) return value.toExponential(2);
  return (+value.toPrecision(4)).toString();
}

// 某单位的互补 kind 默认单位（主列展示所选单位，副列展示另一个 kind）
function complementaryUnit(unit) {
  return CONC_UNITS[unit]?.kind === "molar" ? "mg/mL" : "uM";
}

// ── 实验自动命名 ─────────────────────────────
// 系统变量: {date}_{exp_type}_{seq:02d}，seq 为当天同类型实验序号；支持用户自定义覆盖。
// 本地日期 YYYY-MM-DD（toISOString 是 UTC，UTC+8 凌晨 8 点前会记成"昨天"）
function todayLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

async function getAutoName(expType, date) {
  try {
    const q = new URLSearchParams({ exp_type: expType });
    if (date) q.set("date", date);
    const r = await API.get(`/api/experiments/next-name?${q.toString()}`);
    return r.name || "";
  } catch (_) { return ""; }
}

// 下载 base64 data URL 图片
function downloadDataUrl(dataUrl, filename) {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// 下载出图区域的全部图片（单图/分图/总图通用）：多图按 alt 逐张命名保存
async function downloadAreaImages(areaId, type) {
  const imgs = [...document.querySelectorAll(`#${areaId} img`)];
  if (!imgs.length) { toast("请先出图", true); return; }
  const auto = (await getAutoName(type)) || type;
  const safe = s => (s || "plot").replace(/[\\/:*?"<>|]/g, "_").trim() || "plot";
  imgs.forEach((img, i) => {
    const alt = safe(img.alt);
    const fname = imgs.length > 1 ? `${auto}_${alt}_${i + 1}.png` : `${auto}_${alt}.png`;
    downloadDataUrl(img.src, fname);
  });
}
async function downloadBliPlot() { await downloadAreaImages("bliPlotArea", "BLI"); }
async function downloadAktaPlot() { await downloadAreaImages("aktaPlotArea", "AKTA"); }

// ── Safe HTML escaping ──────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/\\/g, "&#92;");
}
function escAttr(s) { return esc(s); }

// ── Toast ────────────────────────────────────────────
function toast(msg, error, undoAction) {
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.textContent = msg;
  if (undoAction) {
    const link = document.createElement("span");
    link.className = "undo-link";
    link.textContent = "撤销";
    link.onclick = () => { undoAction(); el.remove(); };
    el.appendChild(link);
  }
  document.body.appendChild(el);
  setTimeout(() => el.remove(), undoAction ? 8000 : 2500);
}

// ── Tag system ──────────────────────────────────────
let activeTagFilter = [];

function renderTagChips(tagStr) {
  if (!tagStr) return "";
  return tagStr.split(",").map(t => {
    const s = t.trim();
    return s ? `<span class="tag-chip">${esc(s)}</span>` : "";
  }).join(" ");
}

async function loadTagFilter() {
  const bar = document.getElementById("tagFilterBar");
  if (!bar) return;
  try {
    const tags = await API.get("/api/proteins/tags");
    bar.innerHTML = tags.map(t => {
      const active = activeTagFilter.includes(t) ? " active" : "";
      return `<span class="tag-chip filter${active}" onclick="toggleTagFilter('${esc(t.replace(/'/g, "\\'"))}')">${esc(t)}</span>`;
    }).join(" ") || "";
  } catch (_) { bar.innerHTML = ""; }
}

function toggleTagFilter(tag) {
  const idx = activeTagFilter.indexOf(tag);
  if (idx >= 0) activeTagFilter.splice(idx, 1);
  else activeTagFilter.push(tag);
  loadTagFilter();
  loadProteins().catch(() => {});
}

// ── Tag input helper ─────────────────────────────────
function handleTagKey(event, containerId) {
  if (event.key !== "Enter") return;
  event.preventDefault();
  const container = document.getElementById(containerId);
  const input = container.querySelector("input");
  const val = input.value.trim();
  if (!val) return;
  const chip = document.createElement("span");
  chip.className = "tag-chip";
  chip.innerHTML = `${esc(val)} <span class="chip-x" onclick="this.parentElement.remove()">✕</span>`;
  container.insertBefore(chip, input);
  input.value = "";
  syncTagHidden(containerId);
}

function getTagChips(containerId) {
  const container = document.getElementById(containerId);
  const chips = container.querySelectorAll(".tag-chip");
  return Array.from(chips).map(c => c.textContent.replace("✕", "").trim()).filter(Boolean).join(", ");
}

function syncTagHidden(containerId) {
  const hiddenId = {
    "addTagInput": "addTagHidden",
    "batchTagAddInput": "batchTagAddHidden",
    "batchTagRemoveInput": "batchTagRemoveHidden",
  }[containerId];
  if (hiddenId) document.getElementById(hiddenId).value = getTagChips(containerId);
}

// 关闭弹窗时清理 chip
const _origCloseAddModal = closeAddModal;
closeAddModal = function() {
  const inp = document.querySelector("#addTagInput");
  if (inp) {
    inp.querySelectorAll(".tag-chip").forEach(c => c.remove());
    inp.querySelector("input").value = "";
    document.getElementById("addTagHidden").value = "";
  }
  document.getElementById("addForm").reset();
  document.getElementById("addModal").classList.add("hidden");
};

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

// 表头排序状态：key ∈ {mw, ext_ox}，dir 1=升序 -1=降序
let proteinSort = { key: null, dir: 1 };

function sortProteinTable(key) {
  if (proteinSort.key === key) proteinSort.dir *= -1;
  else { proteinSort.key = key; proteinSort.dir = 1; }
  loadProteins().catch(() => {});
  updateSortIndicators();
}

function updateSortIndicators() {
  const marks = { mw: "sortMwInd", ext_ox: "sortExtInd" };
  for (const [key, id] of Object.entries(marks)) {
    const el = document.getElementById(id);
    if (el) el.textContent = proteinSort.key === key ? (proteinSort.dir === 1 ? "▲" : "▼") : "";
  }
}

async function loadProteins() {
  const tbody = document.querySelector("#proteinTable tbody");
  if (!tbody) return;
  try {
    const q = document.getElementById("searchBox")?.value || "";
    let url = `/api/proteins?q=${encodeURIComponent(q)}`;
    if (activeTagFilter.length) url += `&tag=${encodeURIComponent(activeTagFilter.join(","))}`;
    const proteins = await API.get(url);
    // 客户端排序（MW / 消光系数）
    if (proteinSort.key) {
      const dir = proteinSort.dir, key = proteinSort.key;
      proteins.sort((a, b) => {
        const av = a[key], bv = b[key];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        return (av - bv) * dir;
      });
    }
    tbody.innerHTML = proteins.map(p => `
      <tr>
        <td><input type="checkbox" class="protein-check" value="${p.id}" onchange="updateBulkBar()"></td>
        <td><span class="clickable" data-action="show-detail" data-id="${p.id}">${esc(p.name)}</span></td>
        <td>${p.mw ? p.mw.toLocaleString() : "-"}</td>
        <td>${p.ext_ox || "-"}</td>
        <td>${p.abs_0_1pct ?? "-"}</td>
        <td>${renderTagChips(p.tag)}</td>
        <td><span class="seq-preview" onclick="this.classList.toggle('expanded')" title="点击展开/收起">${esc(p.sequence)}</span></td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-protein" data-id="${p.id}" data-name="${escAttr(p.name)}">删除</button></td>
      </tr>
    `).join("");
    loadTagFilter();
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
      <div style="margin-top:12px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <strong style="font-size:13px">标签</strong>
          <button class="btn btn-sm btn-outline" onclick="editProteinTags(${p.id})" id="editTagsBtn">✏️ 编辑</button>
        </div>
        <div id="proteinTagsDisplay">${renderTagChips(p.tag)}</div>
        <div id="proteinTagsEdit" class="hidden" style="margin-top:4px">
          <div class="tag-input" id="detailTagInput">
            <input type="text" placeholder="输入后回车" onkeydown="handleTagKey(event, 'detailTagInput')">
          </div>
          <div style="display:flex;gap:6px;margin-top:4px">
            <button class="btn btn-sm btn-primary" onclick="saveProteinTags(${p.id})">保存</button>
            <button class="btn btn-sm btn-outline" onclick="cancelEditTags()">取消</button>
          </div>
        </div>
      </div>
    `;
    document.getElementById("detailPanel").classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
}

function editProteinTags(pid) {
  document.getElementById("proteinTagsDisplay").classList.add("hidden");
  document.getElementById("editTagsBtn").classList.add("hidden");
  document.getElementById("proteinTagsEdit").classList.remove("hidden");
  document.getElementById("detailTagInput").querySelector("input").focus();
}

function cancelEditTags() {
  document.getElementById("proteinTagsDisplay").classList.remove("hidden");
  document.getElementById("editTagsBtn").classList.remove("hidden");
  document.getElementById("proteinTagsEdit").classList.add("hidden");
  document.getElementById("detailTagInput").querySelectorAll(".tag-chip").forEach(c => c.remove());
  document.getElementById("detailTagInput").querySelector("input").value = "";
}

async function saveProteinTags(pid) {
  const tag = getTagChips("detailTagInput");
  try {
    await API.put(`/api/proteins/${pid}`, { tag });
    toast("标签已更新");
    // 刷新显示
    cancelEditTags();
    showDetail(pid);
    loadProteins().catch(() => {});
    loadProteinSelects();
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
  if (tab.dataset.tab === "weblogo") { loadWeblogoProteins(); restoreWeblogo(); }
  if (tab.dataset.tab === "enzyme") loadEnzymeProteinList();
  refreshAutoNamePlaceholders();
});

// 自动命名占位提示：输入框显示系统默认名（留空即用它）
async function refreshAutoNamePlaceholders() {
  const targets = {
    concExpName: "浓度测定",
    bliExpName: "BLI",        // BLI 浓度梯度 tab
    bliAnaExpName: "BLI",     // BLI 分析 tab（v0.0.8）
    aktaExpName: "AKTA",      // AKTA 峰图 tab（v0.0.9）
    weblogoExpName: "Weblogo",
  };
  for (const [id, type] of Object.entries(targets)) {
    const el = document.getElementById(id);
    if (!el) continue;
    const auto = await getAutoName(type);
    el.placeholder = auto ? `实验名称（默认 ${auto}）` : "实验名称（可选）";
  }
}

// ═════════════════════════════════════════════════════
//  Tab 1: Protein concentration multi-table
// ═════════════════════════════════════════════════════

let selectedProteins = {};  // { id: { name, mw, ext_ox, abs_0_1pct, ... } }
let concUnit = localStorage.getItem("concUnit") || "uM";  // 浓度结果显示单位（6 单位之一）
let dilUnit = localStorage.getItem("dilUnit") || "uM";    // BLI 稀释步骤浓度显示单位
let allProteins = [];
let copyCache = null;       // cached experiment data for copy tab
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

// 更新浓度表两列结果表头：主列 = 所选单位，副列 = 互补 kind 默认单位
function updateConcHeaders() {
  const ths = document.querySelectorAll("#concTable thead th");
  if (ths.length < 9) return;
  ths[6].textContent = `浓度 (${concUnit})`;
  ths[7].textContent = `浓度 (${complementaryUnit(concUnit)})`;
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
  const title = customName || await getAutoName("浓度测定")
    || ids.map(id => selectedProteins[id].name).join(", ") + " 浓度测定";
  const oxidized = getCurrentOxidized();

  try {
    await API.post("/api/experiments/from-calculation", {
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
        <strong>${esc(p.name)}</strong> (母液 ${r.stock_conc_uM} μM, ${r.dilution_factor}× 稀释, ${r.n_steps} 步)
        <table style="margin-top:6px"><thead><tr><th>#</th><th>浓度 (${dilUnit})</th><th>总体积 (μL)</th><th>取上步 (μL)</th><th>缓冲液 (μL)</th></tr></thead>
        <tbody>${r.steps.map(s => `
          <tr><td>${s.step}</td><td>${fmtConc(s.conc_uM)}</td><td>${s.total_vol_uL}</td><td>${s.stock_vol_uL}</td><td>${s.buffer_vol_uL}</td></tr>
        `).join("")}</tbody></table>
        <p style="margin-top:6px;font-size:13px;color:#666">第一步总需求 ≈ ${r.steps[0].total_vol_uL} μL（含递推稀释裕量）</p>
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
      id: Number(id), name: p.name, mw: p.mw,
      stock_uM: p.stock_uM, start_uM: p.start_uM,
      factor: p.factor, steps: p.steps,
      vol: p.vol, dead: p.dead,
    });
  }
  const customName = document.getElementById("bliExpName").value.trim();
  const title = customName || await getAutoName("BLI")
    || Object.values(bliProteins).map(p => p.name).join(", ") + " BLI 稀释";

  try {
    await API.post("/api/experiments/from-calculation", {
      title: title,
      exp_type: "BLI",
      protein_ids: ids.map(Number),
      date: todayLocal(),
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
//  Tab 5: 从实验复制 (卡片式 UI)
// ═════════════════════════════════════════════════════

let copyAllExps = [];
let copyTypeFilter = "all";

const COPY_TYPE_META = {
  "浓度测定": { icon: "🧪", css: "conc", label: "浓度" },
  "BLI 浓度梯度": { icon: "📊", css: "dilution", label: "BLI" },
  "BLI 分析": { icon: "🧫", css: "bli", label: "BLI 分析" },
  "酶活测定": { icon: "⚡", css: "enzyme", label: "酶活" },
  "Weblogo": { icon: "🧬", css: "weblogo", label: "Logo" },
  "AKTA": { icon: "📈", css: "akta", label: "AKTA" },
};

function copyExpTypeInfo(e) {
  const params = typeof e.params === "string" ? safeJson(e.params) : e.params || {};
  const calcType = params.calc_type || "";
  if (calcType === "concentration") return COPY_TYPE_META["浓度测定"];
  if (calcType === "dilution") return COPY_TYPE_META["BLI 浓度梯度"];
  if (calcType === "enzyme") return COPY_TYPE_META["酶活测定"];
  if (calcType === "weblogo") return COPY_TYPE_META["Weblogo"];
  if (calcType === "akta") return COPY_TYPE_META["AKTA"];
  if (calcType === "bli_fit") return COPY_TYPE_META["BLI 分析"];
  // fallback: 旧存档（v0.0.8 无 calc_type）——BLI 分析靠 exp_type=="BLI" + results.samples 判别，
  // 与 BLI 浓度梯度（calc_type=dilution，恒有 calc_type）区分开
  if (isBliExp(e)) return COPY_TYPE_META["BLI 分析"];
  // fallback: match exp_type
  for (const [key, meta] of Object.entries(COPY_TYPE_META)) {
    if ((e.exp_type || "").includes(key.replace("测定", "").replace("浓度梯度", "")))
      return meta;
  }
  return { icon: "📋", css: "other", label: "其他" };
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

async function loadCopyExpList() {
  if (copyAllExps.length) { renderCopyExpList(); return; }
  try {
    copyAllExps = await API.get("/api/experiments?limit=100");
    renderCopyExpList();
    renderCopyTypeTags();
  } catch (err) { document.getElementById("copyExpList").innerHTML = '<p style="color:#888;text-align:center;padding:40px">加载失败</p>'; }
}

function renderCopyTypeTags() {
  const counts = { all: copyAllExps.length };
  for (const e of copyAllExps) {
    const t = copyExpTypeInfo(e);
    counts[t.css] = (counts[t.css] || 0) + 1;
  }
  const tags = [
    { key: "all", label: "全部", icon: "📋" },
    { key: "conc", label: "浓度", icon: "🧪" },
    { key: "dilution", label: "BLI", icon: "📊" },
    { key: "bli", label: "BLI 分析", icon: "🧫" },
    { key: "enzyme", label: "酶活", icon: "⚡" },
    { key: "weblogo", label: "Logo", icon: "🧬" },
    { key: "akta", label: "AKTA", icon: "📈" },
    { key: "other", label: "其他", icon: "📋" },
  ].filter(t => counts[t.key]);
  document.getElementById("copyTypeTags").innerHTML = tags.map(t =>
    `<span class="copy-type-tag ${t.key}${copyTypeFilter === t.key ? ' active' : ''}"
          onclick="copyTypeFilter='${t.key}';renderCopyTypeTags();renderCopyExpList()">
      ${t.icon} ${t.label} <span style="opacity:.6">${counts[t.key]}</span>
    </span>`
  ).join("");
}

function filterCopyExps() { renderCopyExpList(); }

function renderCopyExpList() {
  const container = document.getElementById("copyExpList");
  const q = (document.getElementById("copySearchInput")?.value || "").trim().toLowerCase();
  let exps = copyAllExps;
  if (copyTypeFilter !== "all") {
    exps = exps.filter(e => copyExpTypeInfo(e).css === copyTypeFilter);
  }
  if (q) {
    exps = exps.filter(e => (e.title || "").toLowerCase().includes(q) || (e.protein_names || "").toLowerCase().includes(q));
  }
  if (!exps.length) {
    container.innerHTML = '<p style="color:#888;font-size:13px;text-align:center;padding:40px">无匹配实验</p>';
    return;
  }
  container.innerHTML = exps.map(e => {
    const ti = copyExpTypeInfo(e);
    const params = typeof e.params === "string" ? safeJson(e.params) : e.params || {};
    const proteins = params.proteins || [];
    const wells = params.wells || params.well_info || {};
    let detail = "";
    if (params.calc_type === "enzyme") {
      detail = `${Object.keys(wells).length} 孔 | ${params.meta?.sample || ""}`;
    } else if (isAktaExp(e)) {
      detail = `通道 ${params.channel || "?"} | ${params.source || "已存档"}`;
    } else if (isBliExp(e)) {
      const results = typeof e.results === "string" ? safeJson(e.results) : e.results || {};
      const nSamples = results.samples ? Object.keys(results.samples).length : 0;
      detail = `${nSamples} 样本 | ${params.source || "已存档"}`;
    } else if (proteins.length) {
      detail = `${proteins.length} 蛋白 | ${proteins.map(p => p.name).join(", ")}`;
    } else {
      detail = e.protein_names || "无蛋白数据";
    }
    return `<div class="copy-card" onclick="selectCopyExp(${e.id})" id="copy-card-${e.id}">
      <div class="copy-type-badge ${ti.css}">${ti.icon}</div>
      <div class="copy-card-body">
        <div class="copy-card-title">${esc(e.title)}</div>
        <div class="copy-card-sub">${e.date || ""} · ${ti.label} · ${esc(detail)}</div>
      </div>
    </div>`;
  }).join("");
}

async function selectCopyExp(eid) {
  document.querySelectorAll(".copy-card").forEach(c => c.classList.remove("active"));
  document.getElementById("copy-card-" + eid)?.classList.add("active");
  try {
    const e = await API.get(`/api/experiments/${eid}`);
    copyCache = e;
    const ti = copyExpTypeInfo(e);
    const params = typeof e.params === "string" ? safeJson(e.params) : e.params || {};
    const calcType = params.calc_type || "";
    let detailHtml = "";
    const proteins = params.proteins || [];
    const wells = params.wells || params.well_info || {};

    if (calcType === "concentration" && proteins.length) {
      detailHtml = `<b>${proteins.length} 个蛋白</b><br>` +
        proteins.map(p => `· ${esc(p.name)}: A₂₈₀=${p.a280 ?? "?"}, ${p.conc_uM ?? "?"} μM`).join("<br>");
    } else if (calcType === "dilution" && proteins.length) {
      detailHtml = `<b>${proteins.length} 个蛋白</b><br>` +
        proteins.map(p => `· ${esc(p.name)}: ${p.stock_uM}→${p.start_uM} μM, ${p.factor}×${p.steps}步`).join("<br>");
    } else if (calcType === "enzyme") {
      const withData = Object.entries(wells).filter(([_, w]) => w.fit || w.times);
      detailHtml = `<b>${Object.keys(wells).length} 孔</b> (${withData.length} 有数据)<br>` +
        `${params.meta?.sample || ""} | ${params.meta?.wavelength || "?"} nm`;
      const negWells = Object.entries(wells).filter(([_, w]) => w.ref === "neg" || w.ref === "blank");
      if (negWells.length) detailHtml += `<br>阴性/空白: ${negWells.map(([id]) => id).join(", ")}`;
    } else if (calcType === "weblogo") {
      detailHtml = `<b>${proteins.length} 条序列</b> | ${params.positions || "?"} 位点`;
    } else if (isAktaExp(e)) {
      detailHtml = `<b>通道 ${esc(params.channel || "?")}</b>` +
        (params.source ? ` | 源文件 ${esc(params.source)}` : "") +
        (params.xmin || params.xmax ? ` | 体积 ${params.xmin ?? 0}–${params.xmax ?? "∞"} mL` : "");
    } else if (isBliExp(e)) {
      const results = typeof e.results === "string" ? safeJson(e.results) : e.results || {};
      const nSamples = results.samples ? Object.keys(results.samples).length : 0;
      detailHtml = `<b>${nSamples} 样本</b>` +
        (params.source ? ` | 源文件 ${esc(params.source)}` : "") +
        (params.smooth_window ? ` | 平滑 ${params.smooth_window}` : "");
    } else {
      detailHtml = `${e.protein_names || "无蛋白"} | ${e.notes || "无额外信息"}`;
    }

    const targetLabel = calcType === "enzyme" ? "酶活计算" : calcType === "dilution" ? "BLI 浓度梯度" : calcType === "weblogo" ? "Weblogo" : isAktaExp(e) ? "AKTA 峰图" : isBliExp(e) ? "BLI 分析" : "蛋白浓度";

    document.getElementById("copyPreviewTitle").textContent = e.title;
    document.getElementById("copyPreviewMeta").innerHTML = `<span class="copy-type-tag ${ti.css}">${ti.icon} ${ti.label}</span> ${e.date || ""} → <b>${targetLabel}</b>`;
    document.getElementById("copyPreviewDetail").innerHTML = detailHtml;
    document.getElementById("copyPreview").classList.remove("hidden");
  } catch (err) { toast(err.message, true); }
}

// helper: safe JSON parse
function safeJson(s) {
  try { return JSON.parse(s); } catch (_) { return {}; }
}

async function applyCopyAndSwitch() {
  if (!copyCache) { toast("请先选择实验", true); return; }
  const params = typeof copyCache.params === "string" ? JSON.parse(copyCache.params) : copyCache.params || {};
  const calcType = params.calc_type || "";

  if (calcType === "enzyme") {
    // 复制到酶活 Tab — 重建 enzymeData + enzymeWellInfo
    const wells = params.wells || params.well_info || {};
    const emeta = params.meta || {};
    enzymeData = { meta: emeta, wells: {} };
    enzymeWellInfo = {};
    enzymeSelection.clear();
    for (const [id, w] of Object.entries(wells)) {
      enzymeWellInfo[id] = {
        name: w.name,
        ref: w.ref,
        group: w.group || "",
        protein_id: w.protein_id,
        conc_ng_ml: w.conc_ng_ml,
        conc_uM: w.conc_uM,
        fit: w.fit,
      };
      if (w.times && w.od) {
        enzymeData.wells[id] = { times: w.times, od: w.od };
      }
    }
    // 时间范围筛选：复制数据重建（与上传路径一致，面板默认全选）
    enzymeTimePoints = [...new Set(emeta.temps || Object.values(enzymeData.wells)[0]?.times || [])].sort((a, b) => a - b);
    enzymeTimeLo = 0;
    enzymeTimeHi = enzymeTimePoints.length - 1;
    enzymeLastImage = null;
    enzymeLastPlotType = null;
    renderEnzymeTimePanel();
    document.getElementById("enzymeMeta").textContent =
      `${emeta.sample || ""} | ${emeta.wavelength || "?"} nm | ${Object.keys(wells).length} wells (复制)`;
    renderPlate();
    if (Object.values(enzymeWellInfo).some(i => i.fit)) {
      renderEnzymeTable(Object.keys(wells));
    }
    document.querySelector(".tab-btn[data-tab='enzyme']").click();
    toast(`已加载 ${Object.keys(wells).length} 个孔位数据`);
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
    toast(`已加载 ${proteins.length} 个蛋白`);
    return;
  }

  if (isBliExp(copyCache)) {
    // 复制到 BLI 分析 Tab — 从实验原始快照重建会话（曲线数据在 experiment_raw，规则 #8 可复现）
    const rid = (copyCache._raw_ids || [])[0];
    if (!rid) { toast("该实验无原始快照可复制", true); return; }
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
        `${copyCache.title || "已存档"} | ${data.n_sensors} 传感器 | ${bliSamples.length} 样本（快照）`;
      document.getElementById("bliAnalyzed").classList.remove("hidden");
      document.getElementById("bliKdWrap").classList.add("hidden");
      document.getElementById("bliPlotArea").innerHTML = "";
      refreshBliPlaceholder();
      document.querySelector(".tab-btn[data-tab='bli']").click();
      bliPlot();
      toast(`已载入 ${bliSamples.length} 个样本（来自快照）`);
    } catch (err) { toast(err.message, true); }
    return;
  }

  if (isAktaExp(copyCache)) {
    // 复制到 AKTA Tab — 从实验原始快照重建会话（曲线数据在 experiment_raw）
    const rid = (copyCache._raw_ids || [])[0];
    if (!rid) { toast("该实验无原始快照可复制", true); return; }
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
        `1 文件（快照） | 1 成功 | ${run.channels.length} 通道`;
      document.getElementById("aktaEventsInfo").textContent = "";
      document.getElementById("aktaAnalyzed").classList.remove("hidden");
      document.getElementById("aktaPeakTableWrap").classList.add("hidden");
      document.getElementById("aktaPlotArea").innerHTML = "";
      refreshAktaPlaceholder();
      document.querySelector(".tab-btn[data-tab='akta']").click();
      aktaPlot();
      toast(`已载入 ${run.channels.length} 个通道（来自快照）`);
    } catch (err) { toast(err.message, true); }
    return;
  }

  // 默认: 浓度实验 → Tab 1
  if (!copyCache.protein_ids) { toast("无蛋白数据可复制", true); return; }
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
    tbody.innerHTML = exps.map(e => {
      // 关联蛋白只显示第一个，hover 显示完整列表
      const pnames = (e.protein_names || "").split(",").map(s => s.trim()).filter(Boolean);
      const pcell = pnames.length
        ? `<span title="${esc(e.protein_names)}">${esc(pnames[0])}${pnames.length > 1 ? " 等" : ""}</span>`
        : "-";
      return `
      <tr>
        <td><input type="checkbox" class="exp-check" value="${e.id}" onchange="updateExpBulkBar()"></td>
        <td class="exp-date">${e.date || "-"}</td>
        <td><a href="/experiments/${e.id}" style="color:#4361ee;font-weight:500;text-decoration:none">${esc(e.title)}</a></td>
        <td class="exp-type"><span class="badge">${esc(e.exp_type)}</span></td>
        <td>${pcell}</td>
        <td>${esc((e.notes || "").substring(0, 40))}</td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-exp" data-id="${e.id}">删除</button></td>
        <td><a class="btn btn-sm btn-outline" href="/api/experiments/${e.id}/export" title="导出此实验">📥</a></td>
      </tr>
    `;
    }).join("");
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
    document.getElementById("expDate").value = prefill.date || todayLocal();
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
//  Tab 5: Enzyme Activity
// ═════════════════════════════════════════════════════

let enzymeData = null;         // {meta, wells: {A1: {times, od}, ...}}
const ENZYME_ANALYSIS_VERSION = "enzyme-1.0";  // raw 快照分析版本（与 BLI/AKTA 一致约定）
let enzymeSelection = new Set();
let enzymeWellInfo = {};       // {A1: {name, conc_ng_ml, conc_uM, mw}}
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
  try {
    const r = await fetch("/api/enzyme/parse", { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) { toast(data.error, true); return; }
    enzymeData = data;
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
    document.getElementById("enzymeMeta").textContent =
      `${data.meta.sample || file.name} | ${data.meta.wavelength || "?"} nm | ${Object.keys(data.wells).length} wells`;
    document.getElementById("enzymeTable").classList.add("hidden");
    document.getElementById("enzymePlotArea").innerHTML = "";
    toast("解析完成");
  } catch (err) { toast(err.message, true); }
}

function renderPlate() {
  document.querySelectorAll(".plate-well").forEach(el => {
    el.classList.remove("has-data", "selected");
    el.textContent = "";
  });
  if (!enzymeData) return;
  for (const [id, wd] of Object.entries(enzymeData.wells)) {
    const el = document.getElementById("well-" + id);
    if (!el) continue;
    el.classList.add("has-data");
    const info = enzymeWellInfo[id] || {};
    el.classList.remove("ref-blank", "ref-neg", "ref-pos");
    if (info.ref) el.classList.add("ref-" + info.ref);
    const symbol = info.ref === "blank" ? "○" : info.ref === "neg" ? "⊖" : info.ref === "pos" ? "⊕" : "●";
    el.textContent = info.name ? info.name.slice(0, 4) : symbol;
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
  if (eLo) eLo.textContent = "起始 " + enzymeTimePoints[enzymeTimeLo] + " s";
  if (eHi) eHi.textContent = "终止 " + enzymeTimePoints[enzymeTimeHi] + " s";
  updateEnzymeTimeBadge();
}

function updateEnzymeTimeBadge() {
  const el = document.getElementById("enzymeTimeCount");
  if (!el || !enzymeTimePoints.length) return;
  const n = enzymeTimeHi - enzymeTimeLo + 1;
  el.textContent = `已选 ${n}/${enzymeTimePoints.length} 个时间点（${enzymeTimePoints[enzymeTimeLo]}s — ${enzymeTimePoints[enzymeTimeHi]}s）`;
  el.style.color = n < 2 ? "#e74c3c" : "#888";  // <2 点无法拟合斜率，标红提醒
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

function updateWellForm() {
  const detail = document.getElementById("wellDetail");
  const form = document.getElementById("wellForm");
  const fit = document.getElementById("wellFit");
  if (enzymeSelection.size === 0) {
    detail.textContent = "选择孔位查看详情"; detail.classList.remove("hidden");
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
  document.getElementById("wellName").placeholder = `${enzymeSelection.size} 个孔选中`;
  document.getElementById("wellGroup").placeholder =
    enzymeSelection.size > 1 ? `同时设置 ${enzymeSelection.size} 个孔的组` : "同组孔取平均作图";

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
  ids.forEach((id) => {
    if (!enzymeWellInfo[id]) enzymeWellInfo[id] = {};
    if (name) {
      if (!multi) {
        enzymeWellInfo[id].name = name;
      } else {
        const ri = renameIds.indexOf(id);
        if (ri >= 0) enzymeWellInfo[id].name = `${name}_${ri + 1}`;
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

// 批量自动命名是否改这个孔：空名、同名、或已是 {name}_N 模式 → 命名；名字不同 → 跳过不覆盖
function enzymeShouldAutoRename(id, name) {
  const cur = (enzymeWellInfo[id]?.name || "").trim();
  if (!cur || cur === name) return true;
  return new RegExp("^" + _escRegex(name) + "_\\d+$").test(cur);
}

function _escRegex(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function enzymeBatchConc() {
  if (enzymeSelection.size < 2) { toast("请选中多个孔", true); return; }
  const start = parseFloat(prompt("起始浓度:"));
  if (isNaN(start)) return;
  const factor = parseFloat(prompt("每孔递增倍数（如 2 表示 2× 递增）:", "2")) || 2;
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
  toast(`已设置 ${ids.length} 孔，起始 ${start}，${factor}× 递增`);
}

async function enzymeCalcSelected() {
  if (!enzymeSelection.size) { toast("请先选中孔位", true); return; }
  await enzymeCalc(Array.from(enzymeSelection));
}

async function enzymeCalcAll(silent = false) {
  if (!enzymeData) { toast("请先上传数据", true); return; }
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
    const msg = bg ? `计算完成 (已扣除背景 ${bg.count} 个孔, 均值 ΔOD/min=${bg.avg.toFixed(6)})` : "计算完成";
    if (!silent) toast(msg);
  } catch (err) { toast(err.message, true); }
}

function renderEnzymeTable(wellIds) {
  const table = document.getElementById("enzymeTable");
  const tbody = table.querySelector("tbody");
  table.classList.remove("hidden");
  tbody.innerHTML = wellIds.map(id => {
    const info = enzymeWellInfo[id] || {};
    const f = info.fit || {};
    const refLabel = info.ref === "blank" ? "空白" : info.ref === "neg" ? "阴性" : info.ref === "pos" ? "阳性" : "样品";
    return `<tr>
      <td>${id}</td><td>${esc(info.name || "")}</td>
      <td style="color:#888">${esc(info.group || "")}</td>
      <td>${refLabel}</td>
      <td>${info.conc_ng_ml ?? "-"}</td><td>${info.conc_uM ?? "-"}</td>
      <td>${f.blank_corrected ? (f.slope_corrected?.toFixed(5) + ' <span style=color:#888;font-size:11px>(校正)</span>') : (f.slope?.toFixed(5) || "-")}</td>
      <td style="color:${f.r2 != null && f.r2 < 0.95 ? '#e74c3c' : '#333'}">${f.r2 ?? "-"}</td>
      <td>${info.activity ?? "-"}</td>
    </tr>`;
  }).join("");
}

async function enzymePlot(type) {
  if (!enzymeData) { toast("请先上传数据", true); return; }
  const ids = enzymeSelection.size ? Array.from(enzymeSelection) : Object.keys(enzymeData.wells);
  const alignStart = document.getElementById("enzymeAlignStart")?.checked || false;
  const alignEnd = document.getElementById("enzymeAlignEnd")?.checked || false;
  const showBlank = document.getElementById("enzymeShowBlank")?.checked || false;
  const subBlank = document.getElementById("enzymeSubBlank")?.checked || false;
  const errorBar = document.getElementById("enzymeErrorBar")?.value || "sd";
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
      `<img src="${r.image}" style="max-width:100%;border-radius:8px" alt="plot">
       <div style="margin-top:8px">
         <button class="btn btn-sm btn-outline" onclick="downloadEnzymePlot()">📥 下载 PNG</button>
       </div>`;
  } catch (err) { toast(err.message, true); }
}

async function downloadEnzymePlot() {
  if (!enzymeLastImage) { toast("请先生成曲线图", true); return; }
  const auto = await getAutoName("酶活测定") || "酶活测定";
  const name = enzymeLastPlotType === "michaelis" ? "MM曲线" : "动力学曲线";
  downloadDataUrl(enzymeLastImage, `${auto}_${name}.png`);
}

async function enzymeSaveExp() {
  if (!enzymeData) { toast("请先上传数据", true); return; }
  const autoName = await getAutoName("酶活测定");
  const title = prompt("实验名称:", autoName || enzymeData.meta.sample || "酶活测定");
  if (!title) return;

  const proteinIds = new Set();
  const wells = {};
  const rawWells = {};  // raw 快照：每孔**全量**时间序列（不受时间轴过滤影响），保证可复算
  for (const [id, wd] of Object.entries(enzymeData.wells)) {
    const info = enzymeWellInfo[id] || {};
    if (info.protein_id) proteinIds.add(info.protein_id);
    const { times, od } = enzymeFilteredData(wd);  // 存档只保留激活的时间点
    wells[id] = {
      name: info.name,
      ref: info.ref,
      group: info.group || "",
      protein_id: info.protein_id,
      conc_ng_ml: info.conc_ng_ml,
      conc_uM: info.conc_uM,
      fit: info.fit || null,
      times,
      od,
      od_range: od.length ? [od[0].toFixed(4), od[od.length - 1].toFixed(4)] : null,
    };
    rawWells[id] = {
      name: info.name,
      ref: info.ref,
      times: wd.times,   // 全量
      od: wd.od,         // 全量
    };
  }

  try {
    await API.post("/api/experiments/from-calculation", {
      title, exp_type: "酶活测定",
      protein_ids: Array.from(proteinIds),
      date: todayLocal(),
      calc_type: "enzyme",
      calc_params: {
        meta: enzymeData.meta,
        wells,
        well_count: Object.keys(enzymeData.wells).length,
        time_axis: enzymeTimePoints.length
          ? [enzymeTimePoints[enzymeTimeLo], enzymeTimePoints[enzymeTimeHi]] : null,
      },
      calc_result: {},
      raw_snapshots: [{
        data_type: "enzyme_traces",
        payload: {
          analysis_version: ENZYME_ANALYSIS_VERSION,
          meta: enzymeData.meta,
          wells: rawWells,
          time_axis: enzymeTimePoints.length
            ? [enzymeTimePoints[enzymeTimeLo], enzymeTimePoints[enzymeTimeHi]] : null,
        },
      }],
    });
    toast("已保存为实验记录");
  } catch (err) { toast(err.message, true); }
}

// 导出作图友好 Excel（宽格式：每孔独立时间/OD 两列 + 动力学汇总），文件名用自动命名
async function enzymeExportExcel() {
  if (!enzymeData) { toast("请先上传数据", true); return; }
  const autoName = await getAutoName("酶活测定") || "酶活测定";
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
      throw new Error(j.error || `导出失败 (${r.status})`);
    }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${autoName}.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    toast("已导出作图 Excel");
  } catch (err) { toast(err.message, true); }
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
        <strong>${esc(p.name)}</strong><span style="color:#888;font-size:11px">${p.mw?.toLocaleString()} Da</span>
      </div>`).join("")
    : '<div class="search-item" style="color:#888">无匹配</div>';
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
    toast(`已关联 ${enzymeSelection.size} 个孔到蛋白: ${p.name}`);
  } catch (err) { toast(err.message, true); }
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
  const roleLabels = { "": "样品", blank: "空白", neg: "阴性", pos: "阳性" };
  const label = roleLabels[refType || ""];
  const roleNames = Object.values(roleLabels);
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

// ═════════════════════════════════════════════════════
//  Tab 4: Weblogo
// ═════════════════════════════════════════════════════

let weblogoAllProteins = [];
let weblogoLastImage = null;
let weblogoLastProteins = [];
let weblogoLastParams = {};  // 生成参数（区间/多聚体/配色），随实验保存

async function loadWeblogoProteins() {
  if (weblogoAllProteins.length) { renderWeblogoProteinList(); return; }
  try {
    weblogoAllProteins = await API.get("/api/proteins");
    renderWeblogoProteinList();
  } catch (_) {}
}

function renderWeblogoProteinList(filter) {
  const container = document.getElementById("weblogoProteinList");
  if (!container) return;
  let list = weblogoAllProteins;
  if (filter) {
    const q = filter.toLowerCase();
    list = list.filter(p => p.name.toLowerCase().includes(q));
  }
  if (weblogoTagFilter.length) {
    list = list.filter(p => {
      const proteinTags = (p.tag || "").split(",").map(t => t.trim());
      return weblogoTagFilter.every(ft => proteinTags.includes(ft));
    });
  }
  container.innerHTML = list.map(p =>
    `<label class="checkbox-label" style="display:flex!important;flex-direction:row!important;align-items:center!important;gap:4px!important;margin-bottom:2px!important;cursor:pointer;padding:2px 4px">
      <input type="checkbox" class="weblogo-protein-check" value="${p.id}"> ${esc(p.name)}
    </label>`
  ).join("") || '<span style="color:#888">无匹配蛋白</span>';
}

async function loadWeblogoTagFilter() {
  const bar = document.getElementById("weblogoTagFilter");
  if (!bar) return;
  try {
    const tags = await API.get("/api/proteins/tags");
    bar.innerHTML = tags.map(t => {
      const active = weblogoTagFilter.includes(t) ? " active" : "";
      return `<span class="tag-chip filter${active}" onclick="toggleWeblogoTag('${esc(t.replace(/'/g, "\\'"))}')">${esc(t)}</span>`;
    }).join(" ") || "";
  } catch (_) {}
}

function toggleWeblogoTag(tag) {
  const idx = weblogoTagFilter.indexOf(tag);
  if (idx >= 0) weblogoTagFilter.splice(idx, 1);
  else weblogoTagFilter.push(tag);
  filterWeblogoProteins();
}

function filterWeblogoProteins() {
  const q = document.getElementById("weblogoSearch").value;
  loadWeblogoTagFilter();
  renderWeblogoProteinList(q);
}

function toggleAllWeblogoProteins(el) {
  document.querySelectorAll(".weblogo-protein-check").forEach(cb => cb.checked = el.checked);
}

// 渲染 weblogo 结果区（生成 / 恢复共用）
function showWeblogoResult(r, count) {
  document.getElementById("weblogoImage").src = r.image;
  const notes = [];
  const p = weblogoLastParams || {};
  if (p.multimer > 1) notes.push(`${p.multimer} 聚体裁剪`);
  if (p.start || p.end) notes.push(`位点 ${r.range ? r.range[0] + "–" + r.range[1] : ""}`);
  document.getElementById("weblogoInfo").textContent =
    `${count} 条序列, ${r.positions} 个位置` + (notes.length ? " (" + notes.join(", ") + ")" : "");
  document.getElementById("weblogoResult").classList.remove("hidden");
  document.getElementById("weblogoSaveBtn").style.display = "";
  document.getElementById("weblogoExpName").style.display = "";
  getAutoName("Weblogo").then(auto => {
    document.getElementById("weblogoExpName").placeholder =
      auto ? `实验名称（默认 ${auto}）` : "实验名称（可选）";
  });
}

async function generateWeblogo() {
  const checked = document.querySelectorAll(".weblogo-protein-check:checked");
  if (checked.length < 2) { toast("至少选择 2 个蛋白", true); return; }

  const ids = Array.from(checked).map(cb => parseInt(cb.value));
  const selected = weblogoAllProteins.filter(p => ids.includes(p.id));
  const sequences = selected.map(p => p.sequence);

  // 检查序列是否等长
  const n = sequences[0].length;
  if (sequences.some(s => s.length !== n)) {
    toast("所选蛋白序列长度不一致，无法对齐", true); return;
  }

  const color = document.getElementById("weblogoColor").value;
  const start = parseInt(document.getElementById("weblogoStart").value) || null;
  const end = parseInt(document.getElementById("weblogoEnd").value) || null;
  const multimer = parseInt(document.getElementById("weblogoMultimer").value) || 1;
  weblogoLastParams = { color_scheme: color, start, end, multimer };
  weblogoLastProteins = selected.map(p => ({ id: p.id, name: p.name }));

  // 记住请求（localStorage）：切页后回来自动恢复，命中服务端缓存秒回
  localStorage.setItem("weblogoLastRequest", JSON.stringify({
    sequences, color_scheme: color, start, end, multimer, proteins: weblogoLastProteins,
  }));

  const genBtn = document.getElementById("weblogoGenBtn");
  const origText = genBtn.textContent;
  genBtn.disabled = true;
  genBtn.textContent = "⏳ 生成中…";
  try {
    const r = await API.post("/api/weblogo", { sequences, color_scheme: color, start, end, multimer });
    weblogoLastImage = r.image;
    showWeblogoResult(r, selected.length);
    toast("Weblogo 已生成");
  } catch (err) { toast(err.message, true); }
  finally { genBtn.disabled = false; genBtn.textContent = origText; }
}

// 切页回来自动恢复上次 weblogo 结果（服务端已缓存，通常秒回，不被中断丢失）
async function restoreWeblogo() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem("weblogoLastRequest") || "null"); } catch (_) { return; }
  if (!saved || !saved.sequences || saved.sequences.length < 2) return;
  weblogoLastParams = { color_scheme: saved.color_scheme, start: saved.start, end: saved.end, multimer: saved.multimer };
  weblogoLastProteins = saved.proteins || [];
  try {
    const r = await API.post("/api/weblogo", {
      sequences: saved.sequences, color_scheme: saved.color_scheme,
      start: saved.start, end: saved.end, multimer: saved.multimer,
    });
    weblogoLastImage = r.image;
    showWeblogoResult(r, weblogoLastProteins.length || saved.sequences.length);
    toast("已恢复上次的 Weblogo 结果");
  } catch (_) { /* 首次生成被中断/渲染失败：忽略，用户重新生成即可 */ }
}

async function downloadWeblogo() {
  if (!weblogoLastImage) return;
  const auto = await getAutoName("Weblogo") || "Weblogo";
  downloadDataUrl(weblogoLastImage, `${auto}.png`);
}

async function saveWeblogoExp() {
  if (!weblogoLastProteins.length) return;
  const customName = document.getElementById("weblogoExpName").value.trim();
  const title = customName || await getAutoName("Weblogo")
    || weblogoLastProteins.map(p => p.name).join(", ") + " Weblogo";
  try {
    await API.post("/api/experiments/from-calculation", {
      title, exp_type: "Weblogo",
      protein_ids: weblogoLastProteins.map(p => p.id),
      date: todayLocal(),
      calc_type: "weblogo",
      calc_params: {
        proteins: weblogoLastProteins,
        image: weblogoLastImage,
        ...weblogoLastParams,
      },
      calc_result: {},
    });
    toast("已保存为实验记录");
  } catch (err) { toast(err.message, true); }
}

// ═════════════════════════════════════════════════════
//  Bulk actions & Undo
// ═════════════════════════════════════════════════════

// ── Proteins bulk ─────────────────────────────────────
function toggleSelectAllProteins(el) {
  document.querySelectorAll(".protein-check").forEach(cb => cb.checked = el.checked);
  updateBulkBar();
}

function updateBulkBar() {
  const checked = document.querySelectorAll(".protein-check:checked");
  const bar = document.getElementById("bulkBar");
  const count = document.getElementById("bulkCount");
  if (!bar || !count) return;
  if (checked.length) {
    bar.classList.remove("hidden");
    count.textContent = `已选 ${checked.length} 项`;
  } else {
    bar.classList.add("hidden");
  }
  // 同步全选框
  const all = document.querySelectorAll(".protein-check");
  const selAll = document.getElementById("selectAllProteins");
  if (selAll) selAll.checked = all.length > 0 && checked.length === all.length;
}

function clearSelection() {
  document.querySelectorAll(".protein-check").forEach(cb => cb.checked = false);
  document.getElementById("selectAllProteins").checked = false;
  updateBulkBar();
}

async function batchDeleteProteins() {
  const checked = document.querySelectorAll(".protein-check:checked");
  if (!checked.length) return;
  if (!confirm(`确定删除选中的 ${checked.length} 个蛋白？`)) return;
  const ids = Array.from(checked).map(cb => parseInt(cb.value));
  try {
    const r = await API.post("/api/proteins/batch-delete", { ids });
    toast(`已删除 ${r.deleted} 个蛋白`, false, () => undoRestore());
    clearSelection();
    loadProteins().catch(() => {});
    loadProteinSelects();
    closeDetail();
  } catch (err) { toast(err.message, true); }
}

async function deleteAllProteins() {
  if (!confirm("⚠️ 确定删除全部蛋白？此操作可以撤销。")) return;
  if (prompt("输入「全部删除」确认:") !== "全部删除") { toast("已取消", true); return; }
  try {
    const r = await API.post("/api/proteins/delete-all", {});
    toast(`已删除全部 ${r.deleted} 个蛋白`, false, () => undoRestore());
    document.getElementById("selectAllProteins").checked = false;
    loadProteins().catch(() => {});
    loadProteinSelects();
    closeDetail();
  } catch (err) { toast(err.message, true); }
}

// ── 批量改标签 ─────────────────────────────────────────
function batchEditTags() {
  const checked = document.querySelectorAll(".protein-check:checked");
  if (!checked.length) { toast("请先选中蛋白", true); return; }
  document.getElementById("batchTagCount").textContent = checked.length;
  document.getElementById("batchTagModal").classList.remove("hidden");
  document.getElementById("batchTagAddInput").querySelector("input").focus();
}

function closeBatchTagModal() {
  document.getElementById("batchTagModal").classList.add("hidden");
  ["batchTagAddInput", "batchTagRemoveInput"].forEach(id => {
    const c = document.getElementById(id);
    c.querySelectorAll(".tag-chip").forEach(ch => ch.remove());
    c.querySelector("input").value = "";
  });
  document.getElementById("batchTagAddHidden").value = "";
  document.getElementById("batchTagRemoveHidden").value = "";
}

async function applyBatchTags() {
  const checked = document.querySelectorAll(".protein-check:checked");
  if (!checked.length) { closeBatchTagModal(); return; }
  const add = document.getElementById("batchTagAddHidden").value;
  const remove = document.getElementById("batchTagRemoveHidden").value;
  if (!add && !remove) { toast("请添加或移除至少一个标签", true); return; }
  const ids = Array.from(checked).map(cb => parseInt(cb.value));
  try {
    const r = await API.post("/api/proteins/batch-tags", { ids, add, remove });
    toast(`已更新 ${r.updated} 个蛋白的标签`);
    closeBatchTagModal();
    loadProteins().catch(() => {});
    loadProteinSelects();
    loadTagFilter();
  } catch (err) { toast(err.message, true); }
}

// ── Experiments bulk ──────────────────────────────────
function toggleSelectAllExps(el) {
  document.querySelectorAll(".exp-check").forEach(cb => cb.checked = el.checked);
  updateExpBulkBar();
}

function updateExpBulkBar() {
  const checked = document.querySelectorAll(".exp-check:checked");
  const bar = document.getElementById("expBulkBar");
  const count = document.getElementById("expBulkCount");
  if (!bar || !count) return;
  if (checked.length) {
    bar.classList.remove("hidden");
    count.textContent = `已选 ${checked.length} 项`;
  } else {
    bar.classList.add("hidden");
  }
  const all = document.querySelectorAll(".exp-check");
  const selAll = document.getElementById("selectAllExps");
  if (selAll) selAll.checked = all.length > 0 && checked.length === all.length;
}

function clearExpSelection() {
  document.querySelectorAll(".exp-check").forEach(cb => cb.checked = false);
  document.getElementById("selectAllExps").checked = false;
  updateExpBulkBar();
}

async function batchDeleteExperiments() {
  const checked = document.querySelectorAll(".exp-check:checked");
  if (!checked.length) return;
  if (!confirm(`确定删除选中的 ${checked.length} 条实验？`)) return;
  const ids = Array.from(checked).map(cb => parseInt(cb.value));
  try {
    const r = await API.post("/api/experiments/batch-delete", { ids });
    toast(`已删除 ${r.deleted} 条实验`, false, () => undoRestore());
    clearExpSelection();
    loadExperiments().catch(() => {});
  } catch (err) { toast(err.message, true); }
}

async function deleteAllExperiments() {
  if (!confirm("⚠️ 确定删除全部实验？此操作可以撤销。")) return;
  if (prompt("输入「全部删除」确认:") !== "全部删除") { toast("已取消", true); return; }
  try {
    const r = await API.post("/api/experiments/delete-all", {});
    toast(`已删除全部 ${r.deleted} 条实验`, false, () => undoRestore());
    document.getElementById("selectAllExps").checked = false;
    loadExperiments().catch(() => {});
  } catch (err) { toast(err.message, true); }
}

// ── Undo ──────────────────────────────────────────────
async function undoRestore() {
  try {
    const r = await API.post("/api/undo", {});
    if (r.ok) {
      toast(`已撤销: ${r.restored} 已恢复`);
      loadProteins().catch(() => {});
      loadExperiments().catch(() => {});
      loadProteinSelects();
    } else {
      toast(r.error || "无法撤销", true);
    }
  } catch (err) { toast("撤销失败: " + err.message, true); }
}

// ═════════════════════════════════════════════════════
//  Tab: BLI 原始数据拟合（v0.0.8）
// ═════════════════════════════════════════════════════

let bliSession = null;       // /api/bli/analyze 返回的 session_id
let bliSamples = [];         // [{sample, n_curves, concs, labels}]
let bliSelectedSample = "";  // KD 拟合选中的样本
let bliLastPlot = null;      // 最近一次传感器图 dataURL（切页回来可刷新）
let bliActiveCurves = new Set();  // 勾选「进入数据」的曲线 label（出图/拟合/导出/存档共用）
let bliKdResult = null;      // 最近一次单样本 5 方法 KD 拟合结果（点样本行重拟合更新）

async function uploadBliFile() {
  const file = document.getElementById("bliFile").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const r = await fetch("/api/bli/analyze", { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) { toast(data.error, true); return; }
    bliSession = data.session_id;
    bliSamples = data.samples || [];
    bliSelectedSample = bliSamples[0]?.sample || "";
    bliLastPlot = null;
    bliKdResult = null;
    bliActiveCurves = new Set(bliSamples.flatMap(s => s.labels || []));  // 默认全选进入数据
    renderBliSamples();
    renderBliCurves();
    document.getElementById("bliMeta").textContent =
      `${file.name} | ${data.n_sensors} 传感器 | ${bliSamples.length} 样本`;
    document.getElementById("bliAnalyzed").classList.remove("hidden");
    document.getElementById("bliKdWrap").classList.add("hidden");
    document.getElementById("bliPlotArea").innerHTML = "";
    refreshBliPlaceholder();
    toast("解析完成");
  } catch (err) { toast(err.message, true); }
}

function renderBliSamples() {
  const tbody = document.getElementById("bliSampleList");
  tbody.innerHTML = bliSamples.map(s => `
    <tr>
      <td><strong>${esc(s.sample)}</strong></td>
      <td>${s.n_curves}</td>
      <td style="font-size:12px;color:#666">${(s.concs || []).map(c => formatConc(c, "nM")).join(" / ")}</td>
      <td><button class="btn btn-sm btn-outline bli-pick" data-sample="${escAttr(s.sample)}">${bliSelectedSample === s.sample ? "✓ 选中" : "拟合"}</button></td>
    </tr>`).join("");
}

// ══ 曲线勾选（进入数据）：每条曲线一行复选框，勾选 = 出图/拟合/导出/存档都纳入 ══

// 摊平为曲线行：{label, sample, conc}
function bliAllCurveRows() {
  const rows = [];
  for (const s of bliSamples) {
    (s.labels || []).forEach((lbl, i) => rows.push({ label: lbl, sample: s.sample, conc: s.concs?.[i] ?? 0 }));
  }
  return rows;
}

function renderBliCurves() {
  const tbody = document.getElementById("bliCurveList");
  if (!tbody) return;
  tbody.innerHTML = bliAllCurveRows().map(r => `
    <tr>
      <td><input type="checkbox" class="bli-curve-cb" data-label="${escAttr(r.label)}" ${bliActiveCurves.has(r.label) ? "checked" : ""}></td>
      <td style="font-size:12px">${esc(r.label)}</td>
      <td style="font-size:12px;color:#666">${esc(r.sample)}</td>
      <td style="font-size:12px;color:#666">${formatConc(r.conc, "nM")} nM</td>
    </tr>`).join("");
  updateBliCurveMaster();
}

// 总复选框三态：全选 / 半选（indeterminate）/ 全不选；同步「已选 X/Y」
function updateBliCurveMaster() {
  const all = bliAllCurveRows();
  const master = document.getElementById("bliCurveSelectAll");
  const stats = document.getElementById("bliCurveStats");
  if (!master || !all.length) return;
  const nOn = all.filter(r => bliActiveCurves.has(r.label)).length;
  master.checked = nOn === all.length;
  master.indeterminate = nOn > 0 && nOn < all.length;
  if (stats) stats.textContent = `已选 ${nOn}/${all.length}`;
}

function bliToggleAllCurves() {
  const all = bliAllCurveRows();
  bliActiveCurves = document.getElementById("bliCurveSelectAll").checked
    ? new Set(all.map(r => r.label)) : new Set();
  renderBliCurves();
}

// 曲线勾选 + 总复选框事件委托（document 级，calc 页外缺省元素不报错）
document.addEventListener("change", function (e) {
  const cb = e.target.closest(".bli-curve-cb");
  if (cb) {
    const lbl = cb.dataset.label;
    if (cb.checked) bliActiveCurves.add(lbl); else bliActiveCurves.delete(lbl);
    updateBliCurveMaster();
    return;
  }
  if (e.target.closest("#bliCurveSelectAll")) bliToggleAllCurves();
});

// 样本按钮事件委托：用 data-sample 传参（onclick 内联字符串对含引号样本名不安全）。
// ⚠ 必须在元素存在时绑定——app.js 被所有页面共享，calc 页外该元素为 null。
// 用可选链 + 顶层防错：只在 calculator 页面注册一次。
document.addEventListener("click", function (e) {
  const btn = e.target.closest(".bli-pick");
  if (!btn) return;
  bliSelectSample(btn.dataset.sample);
});

function bliSelectSample(sid) {
  bliSelectedSample = sid;
  renderBliSamples();
  bliFitSelected();
}

// 回填存档时的分析参数到 UI 控件（规则 #8：复制后按同参数复现分析）。
// t_assoc/t_dissoc 为 null（自动检测）→ 置空走占位符「自动」；ns_subtract 无控件，不在此列。
function bliBackfillParams(p) {
  if (!p) return;
  const setVal = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.value = (v == null || v === "") ? "" : v;
  };
  setVal("bliSmooth", p.smooth_window);
  setVal("bliNConcs", p.n_concs);
  setVal("bliTAssoc", p.t_assoc);
  setVal("bliTDissoc", p.t_dissoc);
  setVal("bliNsSensor", p.ns_sensor);
  const fitEl = document.getElementById("bliFit");
  if (fitEl) fitEl.checked = !!p.fit_overlay;
  const ncEl = document.getElementById("bliNoCutoff");
  if (ncEl) ncEl.checked = !!p.no_cutoff;
  const trimEl = document.getElementById("bliTrimStart");
  if (trimEl) trimEl.checked = p.trim_start !== false;
  // 曲线勾选子集：存档的 active_curves 记录当时进入数据的曲线，复制后默认也排除未勾选的
  if (Array.isArray(p.active_curves)) {
    bliActiveCurves = new Set(p.active_curves.map(String).filter(Boolean));
  }
}

function bliParams() {
  return {
    session_id: bliSession,
    smooth_window: parseInt(document.getElementById("bliSmooth").value || "0", 10),
    fit: document.getElementById("bliFit").checked,
    t_assoc: document.getElementById("bliTAssoc").value,
    t_dissoc: document.getElementById("bliTDissoc").value,
    n_concs: parseInt(document.getElementById("bliNConcs").value || "8", 10),
    ns_sensor: document.getElementById("bliNsSensor").value.trim(),
    no_cutoff: document.getElementById("bliNoCutoff").checked,
    active_curves: [...bliActiveCurves],
    trim_start: document.getElementById("bliTrimStart").checked,
  };
}

async function bliPlot() {
  if (!bliSession) { toast("请先上传数据", true); return; }
  const mode = (document.getElementById("bliPlotMode") || {}).value || "overlay";
  try {
    const r = await API.post("/api/bli/plot", { ...bliParams(), separate: mode === "separate" });
    const area = document.getElementById("bliPlotArea");
    if (mode === "separate" && r.images) {
      area.innerHTML = Object.entries(r.images).map(([sid, img]) =>
        `<div style="background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,.06);margin-bottom:10px">
          <div style="font-weight:600;margin-bottom:6px">${esc(sid)}</div>
          <img src="${img}" style="max-width:100%" alt="${esc(sid)}">
        </div>`).join("");
      bliLastPlot = null;
    } else {
      area.innerHTML =
        `<div style="background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
          <img src="${r.image}" style="max-width:100%" alt="传感器图">
        </div>`;
      bliLastPlot = r.image;
    }
  } catch (err) { toast(err.message, true); }
}

async function bliFitSelected() {
  if (!bliSession || !bliSelectedSample) { toast("请先选择样本", true); return; }
  try {
    const r = await API.post("/api/bli/fit", { ...bliParams(), sample: bliSelectedSample });
    bliKdResult = r;
    document.getElementById("bliKdWrap").classList.remove("hidden");
    document.getElementById("bliKdTables").innerHTML = renderBliKd(bliSelectedSample, r);
  } catch (err) { toast(err.message, true); }
}

// 单样本 KD 结果渲染（点样本行重拟合 → 更新这张卡片；拟合失败显示错误卡）
function renderBliKd(sample, res) {
  if (!res || res.error) {
    return `<div class="calc-card" style="padding:12px;margin-bottom:10px">
      <div style="font-weight:600;margin-bottom:4px">${esc(sample)}</div>
      <div style="color:#c00;font-size:13px">拟合失败：${esc(res.error || "未知错误")}</div>
    </div>`;
  }
  const phase = res.phase || {};
  const methods = ["standard", "split", "joint", "steady", "mixed"];
  const rows = methods.map(m => {
    const v = res[m];
    if (!v) return `<tr><td>${m}</td><td colspan="4" style="color:#888">拟合失败</td></tr>`;
    const kd = v.kd != null && isFinite(v.kd) ? `${formatConc(v.kd, "nM")} nM` : "—";
    const kon = v.kon != null && isFinite(v.kon) ? (+v.kon).toExponential(2) : "—";
    const koff = v.koff != null && isFinite(v.koff) ? (+v.koff).toExponential(2) : "—";
    const extra = v.kd_steady_mixed != null ? `KD(稳态) ${formatConc(v.kd_steady_mixed, "nM")}` :
                 (v.kd_kinetic_mixed != null ? `KD(动力学) ${formatConc(v.kd_kinetic_mixed, "nM")}` : "");
    return `<tr><td><strong>${m}</strong></td><td>${kd}</td><td>${kon}</td><td>${koff}</td><td>${extra}</td></tr>`;
  }).join("");
  return `<div class="calc-card" style="padding:12px;margin-bottom:10px">
    <div style="font-size:13px;color:#555;margin-bottom:6px">
      样本 <strong>${esc(sample)}</strong> · 相界 assoc ${phase.t_assoc?.toFixed(1)} s → dissoc ${phase.t_dissoc?.toFixed(1)} s
    </div>
    <table class="calc-table">
      <thead><tr><th>方法</th><th>KD</th><th>kon (1/M·s)</th><th>koff (1/s)</th><th>备注</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

async function bliSaveExp() {
  if (!bliSession) { toast("请先上传数据", true); return; }
  const autoName = await getAutoName("BLI");
  const title = prompt("实验名称:", autoName || "BLI 分析");
  if (!title) return;
  try {
    await API.post("/api/bli/save", {
      ...bliParams(),
      title,
      date: todayLocal(),
      source: document.getElementById("bliFile").files[0]?.name || "",
    });
    toast("已保存为实验记录（含原始曲线快照）");
  } catch (err) { toast(err.message, true); }
}

async function bliExport() {
  if (!bliSession) { toast("请先上传数据", true); return; }
  try {
    const r = await fetch("/api/bli/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bliParams()),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw new Error(j.error || `导出失败 (${r.status})`);
    }
    const blob = await r.blob();
    const fname = prompt("导出文件名:", "BLI_KD汇总.xlsx");
    if (!fname) return;
    const fn = /\.xlsx$/i.test(fname) ? fname : fname + ".xlsx";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fn;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    toast("已导出 BLI 分析 Excel");
  } catch (err) { toast(err.message, true); }
}

// 兼容入口：BLI/AKTA 上传后刷新各自输入框占位（统一走 refreshAutoNamePlaceholders）
function refreshBliPlaceholder() { refreshAutoNamePlaceholders(); }
function refreshAktaPlaceholder() { refreshAutoNamePlaceholders(); }

// ═════════════════════════════════════════════════════
//  Tab: AKTA 峰图整理（v0.0.9）
// ═════════════════════════════════════════════════════

// 多 run 批量：一次上传多个 zip，每个 run 独立 session/channel/目标峰
let aktaRuns = [];             // [{name, session_id, channels, uv_channels, events, meta, channel, target_peak}]
let aktaCurrentRun = 0;        // 当前选中的 run 下标（峰表/单张图用它）

async function uploadAktaFile() {
  const files = Array.from(document.getElementById("aktaFile").files || []);
  if (!files.length) return;
  const form = new FormData();
  files.forEach(f => form.append("file", f));
  try {
    const r = await fetch("/api/akta/analyze", { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) { toast(data.error, true); return; }
    aktaRuns = (data.runs || []).map(run => {
      if (run.error) return { ...run, channels: [], uv_channels: [], events: {}, meta: {} };
      const uv = run.uv_channels && run.uv_channels[0];
      return {
        ...run,
        channel: uv || run.channels[0]?.name || "",
        target_peak: 0,   // 阴影跟随主峰（第 1 个）
        checked: true,    // 默认参与出图（可勾选剔除）
      };
    });
    aktaCurrentRun = 0;
    const okRuns = aktaRuns.filter(r => !r.error);
    const errRuns = aktaRuns.filter(r => r.error);
    const totalCh = okRuns.reduce((n, r) => n + r.channels.length, 0);
    document.getElementById("aktaMeta").textContent =
      `${files.length} 文件 | ${okRuns.length} 成功${errRuns.length ? ` / ${errRuns.length} 失败` : ""} | ${totalCh} 通道`;
    renderAktaRuns();
    document.getElementById("aktaEventsInfo").textContent =
      errRuns.map(r => `${r.name}: ${r.error}`).join("；");
    document.getElementById("aktaAnalyzed").classList.remove("hidden");
    document.getElementById("aktaPeakTableWrap").classList.add("hidden");
    document.getElementById("aktaPlotArea").innerHTML = "";
    refreshAktaPlaceholder();
    if (okRuns.length) { toast(`解析完成：${okRuns.length} 个文件`); }
    else { toast("全部文件解析失败", true); }
  } catch (err) { toast(err.message, true); }
}

function renderAktaRuns() {
  const box = document.getElementById("aktaRunList");
  if (!box) return;
  box.innerHTML = aktaRuns.map((run, ri) => {
    if (run.error) {
      return `<div style="border:1px solid #f0c0c0;border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:13px;background:#fff7f7">
        <strong style="color:#c0392b">${esc(run.name)}</strong>
        <span style="color:#888;margin-left:8px">${esc(run.error)}</span>
      </div>`;
    }
    const chOpts = run.channels.map(ch =>
      `<option value="${escAttr(ch.name)}" ${ch.name === run.channel ? "selected" : ""}>${esc(ch.name)} (${esc(ch.data_type)}${ch.unit ? " " + esc(ch.unit) : ""}, ${ch.n_points}pts)</option>`).join("");
    const evInfo = Object.entries(run.events || {}).map(([k, v]) => `${k}:${v}`).join(" ");
    const checked = run.checked === false ? "" : "checked";
    return `<div style="border:1px solid ${aktaCurrentRun === ri ? "#4361ee" : "#e0e0e0"};border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:13px;background:${aktaCurrentRun === ri ? "#f0f5ff" : "#fff"}" data-run="${ri}">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <div style="display:inline-flex;align-items:center;gap:6px">
          <input type="checkbox" class="akta-run-check" data-run="${ri}" ${checked} onclick="event.stopPropagation()">
          <strong style="cursor:pointer" class="akta-run-select">${esc(run.name)}</strong>
        </div>
        <span style="color:#888;font-size:12px">${evInfo || "无事件"}</span>
      </div>
      <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;align-items:center">
        <select class="akta-run-channel" data-run="${ri}" style="flex:1;min-width:160px;padding:5px 8px;border:1px solid #d0d0d0;border-radius:4px;font-size:12px">${chOpts}</select>
      </div>
    </div>`;
  }).join("");
}

// 文件/通道列表的事件委托（document 级，缺省页面不报错）
document.addEventListener("click", function (e) {
  const sel = e.target.closest(".akta-run-select");
  if (sel) {
    const ri = parseInt(sel.closest("[data-run]").dataset.run, 10);
    aktaCurrentRun = ri;
    renderAktaRuns();
    aktaPlot();
    return;
  }
  const pick = e.target.closest(".akta-pick");
  if (pick) {
    aktaSelectChannel(pick.dataset.channel);
    return;
  }
});
document.addEventListener("change", function (e) {
  const ck = e.target.closest(".akta-run-check");
  if (ck) {
    const ri = parseInt(ck.dataset.run, 10);
    if (aktaRuns[ri]) aktaRuns[ri].checked = ck.checked;
    return;
  }
  const sel = e.target.closest(".akta-run-channel");
  if (!sel) return;
  const ri = parseInt(sel.dataset.run, 10);
  if (aktaRuns[ri]) aktaRuns[ri].channel = sel.value;
});

function aktaSelectChannel(name) {
  const run = aktaRuns[aktaCurrentRun];
  if (run) run.channel = name;
  renderAktaRuns();
  aktaPlot();
}

// 回填存档时的峰检测参数到 UI 控件（规则 #8）。save 只落 xmin/xmax/min_height/smooth_window，
// 显示类开关（frac 阴影/峰阴影/归一化等）不在 params 内，保持当前 UI 值。
function aktaBackfillParams(p) {
  if (!p) return;
  const setVal = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.value = (v == null || v === "") ? "" : v;
  };
  setVal("aktaXmin", p.xmin);
  setVal("aktaXmax", p.xmax);       // null → "" → 占位符「自动」
  setVal("aktaMinHeight", p.min_height);
  setVal("aktaSmooth", p.smooth_window);
}

function aktaParams(run) {
  run = run || aktaRuns[aktaCurrentRun];
  return {
    session_id: run.session_id,
    channel: run.channel,
    xmin: parseFloat(document.getElementById("aktaXmin").value || "0"),
    xmax: document.getElementById("aktaXmax").value,
    min_height: parseFloat(document.getElementById("aktaMinHeight").value || "5"),
    smooth_window: parseInt(document.getElementById("aktaSmooth").value || "11", 10),
    show_events: document.getElementById("aktaShowEvents").checked,
    highlight_frac: document.getElementById("aktaHighlightFrac").checked,
    peak_fill: document.getElementById("aktaPeakFill").checked,
    peak_labels: document.getElementById("aktaPeakLabels").checked,
    normalize: document.getElementById("aktaNormalize").checked,
    target_peak_idx: run.target_peak || 0,
  };
}

async function aktaPlot() {
  const run = aktaRuns[aktaCurrentRun];
  if (!run || run.error || !run.channel) { toast("请先选择文件/通道", true); return; }
  try {
    const r = await API.post("/api/akta/plot", aktaParams(run));
    document.getElementById("aktaPlotArea").innerHTML =
      `<div style="background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="font-weight:600;margin-bottom:6px;font-size:14px">${esc(run.name)} — ${esc(run.channel)}</div>
        <img src="${r.image}" style="max-width:100%" alt="AKTA 峰图">
      </div>`;
    renderAktaPeaks(r.peaks || [], run);
  } catch (err) { toast(err.message, true); }
}

// 出图入口：分图模式 = 每文件一张；总图模式 = 所有曲线叠一张
// 只出勾选（akta-run-check）的文件
async function aktaBatchPlot() {
  const okRuns = aktaRuns.filter(r => !r.error && r.channel && r.checked !== false);
  if (!okRuns.length) { toast("没有勾选可出图的文件", true); return; }
  const mode = document.getElementById("aktaPlotMode").value;
  const area = document.getElementById("aktaPlotArea");
  const normOn = document.getElementById("aktaNormalize").checked;

  if (mode === "overlay") {
    if (okRuns.length < 2) { toast("总图至少需要 2 个文件", true); return; }
    area.innerHTML = `<p style="color:#888;font-size:13px">正在生成总图（${okRuns.length} 个文件）...</p>`;
    try {
      const r = await API.post("/api/akta/overlay", {
        runs: okRuns.map(run => ({
          session_id: run.session_id,
          channel: run.channel,
          target_peak_idx: run.target_peak || 0,
        })),
        xmin: parseFloat(document.getElementById("aktaXmin").value || "0"),
        xmax: document.getElementById("aktaXmax").value,
        min_height: parseFloat(document.getElementById("aktaMinHeight").value || "5"),
        smooth_window: parseInt(document.getElementById("aktaSmooth").value || "11", 10),
        normalize: normOn,
        show_events: document.getElementById("aktaShowEvents").checked,
        highlight_frac: document.getElementById("aktaHighlightFrac").checked,
      });
      area.innerHTML = `<div style="background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="font-weight:600;margin-bottom:6px;font-size:14px">总图（${okRuns.length} 个文件${normOn ? " · 归一化" : ""}）</div>
        <img src="${r.image}" style="max-width:100%" alt="AKTA 总图">
      </div>`;
    } catch (err) { toast(err.message, true); }
    return;
  }

  // 分图模式
  area.innerHTML = `<p style="color:#888;font-size:13px">正在批量生成 ${okRuns.length} 张图...</p>`;
  let html = "";
  for (const run of okRuns) {
    try {
      const r = await API.post("/api/akta/plot", aktaParams(run));
      html += `<div style="background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 4px rgba(0,0,0,.06);margin-bottom:12px">
        <div style="font-weight:600;margin-bottom:6px;font-size:14px">${esc(run.name)} — ${esc(run.channel)}</div>
        <img src="${r.image}" style="max-width:100%" alt="${esc(run.name)}">
      </div>`;
    } catch (err) {
      html += `<div style="border:1px solid #f0c0c0;border-radius:8px;padding:8px;margin-bottom:8px;color:#c0392b;font-size:13px">${esc(run.name)}: ${esc(err.message)}</div>`;
    }
  }
  area.innerHTML = html;
}

function renderAktaPeaks(peaks, run) {
  const wrap = document.getElementById("aktaPeakTableWrap");
  const tbody = document.querySelector("#aktaPeakTable tbody");
  if (!wrap || !tbody) return;
  if (!peaks.length) {
    wrap.classList.remove("hidden");
    tbody.innerHTML = `<tr><td colspan="7" style="color:#888;text-align:center">未检测到峰（可调低最小峰高或缩小范围）</td></tr>`;
    return;
  }
  wrap.classList.remove("hidden");
  const cur = run.target_peak || 0;
  tbody.innerHTML = peaks.map((p, i) => `
    <tr style="${i === cur ? "background:#f0f5ff" : ""}">
      <td>${i + 1}</td>
      <td>${p.apex_vol}</td>
      <td>${p.height}</td>
      <td>${p.area}</td>
      <td>${p.start_vol}</td>
      <td>${p.end_vol}</td>
      <td>${p.half_width}</td>
      <td><button class="btn btn-sm btn-outline akta-peak-target" data-run-idx="${aktaCurrentRun}" data-peak="${i}">${i === cur ? "✓ 目标" : "目标"}</button></td>
    </tr>`).join("");
}

// 峰表点「目标」→ 切换阴影跟随的峰并重出图（document 级委托）
document.addEventListener("click", function (e) {
  const btn = e.target.closest(".akta-peak-target");
  if (!btn) return;
  const ri = parseInt(btn.dataset.runIdx, 10);
  const pi = parseInt(btn.dataset.peak, 10);
  if (aktaRuns[ri]) { aktaRuns[ri].target_peak = pi; aktaCurrentRun = ri; }
  renderAktaRuns();
  aktaPlot();
});

async function aktaExport() {
  const run = aktaRuns[aktaCurrentRun];
  if (!run || run.error || !run.channel) { toast("请先选择文件/通道", true); return; }
  // 作图数据覆盖全部勾选的 run（每个样品两列），峰表/曲线 sheet 仍用当前 run
  const okRuns = aktaRuns.filter(r => !r.error && r.channel && r.checked !== false);
  try {
    const r = await fetch("/api/akta/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...aktaParams(run),
        runs: okRuns.map(x => ({
          session_id: x.session_id,
          channel: x.channel,
          name: (x.name || x.channel || "sample").replace(/\.zip$/i, ""),
        })),
      }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw new Error(j.error || `导出失败 (${r.status})`);
    }
    const blob = await r.blob();
    // 文件名默认用 zip 包名（去 .zip），允许用户自定义
    const zipBase = (run.name || "").replace(/\.zip$/i, "") || run.channel;
    let fname = prompt("导出文件名:", `${zipBase}_峰表.xlsx`);
    if (!fname) return;
    if (!/\.xlsx$/i.test(fname)) fname += ".xlsx";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    toast(`已导出峰表 Excel（${okRuns.length} 个样品作图数据）`);
  } catch (err) { toast(err.message, true); }
}


async function aktaSaveExp() {
  const run = aktaRuns[aktaCurrentRun];
  if (!run || run.error || !run.channel) { toast("请先选择文件/通道", true); return; }
  const autoName = await getAutoName("AKTA");
  // 默认名优先用 zip 包名（去 .zip 扩展名），其次系统自动命名
  const zipBase = (run.name || "").replace(/\.zip$/i, "");
  const title = prompt("实验名称:", zipBase || autoName || "AKTA 峰图");
  if (!title) return;
  try {
    await API.post("/api/akta/save", {
      ...aktaParams(run),
      title,
      date: todayLocal(),
      source: run.name || "",
    });
    toast("已保存为实验记录（含原始曲线快照）");
  } catch (err) { toast(err.message, true); }
}

function refreshAktaPlaceholder() { refreshAutoNamePlaceholders(); }

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
    // 浓度单位下拉框（持久化到 localStorage）
    const unitSel = document.getElementById("concUnitSel");
    if (unitSel) unitSel.value = concUnit;
    updateConcHeaders();
    // 保存状态：离开页面前
    window.addEventListener("beforeunload", saveCalcState);
  }
  if (document.querySelector("#bliTable") || document.querySelector("#bliProteinSearch")) {
    const dilSel = document.getElementById("dilUnitSel");
    if (dilSel) dilSel.value = dilUnit;
  }
}
init();
