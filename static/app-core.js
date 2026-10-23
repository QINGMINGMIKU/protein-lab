// ═════════════════════════════════════════════════════
//  Protein Lab — Frontend
// ═════════════════════════════════════════════════════

const API = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw backendError(null, r.status, `HTTP ${r.status}`);
    return r.json();
  },
  async post(url, data) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const j = await r.json();
    if (!r.ok) throw backendError(j, r.status);
    return j;
  },
  async put(url, data) {
    const r = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const j = await r.json();
    if (!r.ok) throw backendError(j, r.status);
    return j;
  },
  async del(url) {
    const r = await fetch(url, { method: "DELETE" });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw backendError(j, r.status);
    }
  },
};

function t(key, params) {
  return (window.BigoI18n && window.BigoI18n.t) ? window.BigoI18n.t(key, params) : key;
}
async function askText(title, value) {
  if (window.BigoUI && BigoUI.prompt) {
    return BigoUI.prompt({ title, value: value == null ? "" : String(value) });
  }
  return prompt(title, value == null ? "" : String(value));
}
function backendError(j, status, fallback) {
  const e = new Error((j && j.error) || fallback || `HTTP ${status}`);
  e.backend = true;
  return e;
}

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
  if (!f || !t) throw new Error(t("toast.unknown_unit", { from, to }));
  let base = value * f.factor;
  if (f.kind !== t.kind) {
    if (!mw || mw <= 0) throw new Error(t("toast.need_mw"));
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

async function getAutoName(expType, date, calcType) {
  try {
    const q = new URLSearchParams();
    if (expType) q.set("exp_type", expType);
    if (calcType) q.set("calc_type", calcType);
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
  if (!imgs.length) { toast(t("toast.plot_first"), true); return; }
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
function iconClose() {
  return `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}
function setEvidence(id, phase, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.dataset.phase = phase || "";
  el.classList.add("evidence-status");
  el.textContent = text || "";
}

function toast(msg, error, undoAction) {
  const el = document.createElement("div");
  let text = msg;
  let backend = false;
  if (msg instanceof Error) {
    error = true;
    text = msg.message;
    backend = !!msg.backend;
  }
  el.className = "toast" + (error ? " error" : "");
  if (backend) {
    const title = document.createElement("div");
    title.className = "toast-title";
    title.textContent = t("error.generic");
    el.appendChild(title);
    const details = document.createElement("details");
    const sum = document.createElement("summary");
    sum.textContent = t("error.details");
    const pre = document.createElement("pre");
    pre.textContent = String(text);
    details.appendChild(sum);
    details.appendChild(pre);
    el.appendChild(details);
  } else {
    el.appendChild(document.createTextNode(String(text)));
  }
  if (undoAction) {
    const link = document.createElement("span");
    link.className = "undo-link";
    link.textContent = t("common.undo");
    link.onclick = () => { undoAction(); el.remove(); };
    el.appendChild(link);
  }
  document.body.appendChild(el);
  setTimeout(() => el.remove(), (undoAction || error) ? 8000 : 2500);
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
  chip.innerHTML = `${esc(val)} <button type="button" class="chip-x" onclick="this.parentElement.remove()" aria-label="${esc(t("common.close"))}">${iconClose()}</button>`;
  container.insertBefore(chip, input);
  input.value = "";
  syncTagHidden(containerId);
}

function getTagChips(containerId) {
  const container = document.getElementById(containerId);
  const chips = container.querySelectorAll(".tag-chip");
  return Array.from(chips).map(c => {
    const clone = c.cloneNode(true);
    clone.querySelectorAll(".chip-x").forEach(x => x.remove());
    return clone.textContent.trim();
  }).filter(Boolean).join(", ");
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
    case "delete-exp":     deleteExp(id, name); break;
  }
});

