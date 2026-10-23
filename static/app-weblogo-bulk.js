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
  ).join("") || `<span style="color:var(--graphite)">${t("workbench.no_match_protein")}</span>`;
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
  if (p.multimer > 1) notes.push(t("workbench.multimer_cropped", { n: p.multimer }));
  if (p.start || p.end) notes.push(t("workbench.pos_span", { lo: r.range ? r.range[0] : "", hi: r.range ? r.range[1] : "" }));
  document.getElementById("weblogoInfo").textContent =
    t("workbench.seq_pos", { n: count, pos: r.positions }) + (notes.length ? " (" + notes.join(", ") + ")" : "");
  document.getElementById("weblogoResult").classList.remove("hidden");
  document.getElementById("weblogoSaveBtn").style.display = "";
  document.getElementById("weblogoExpName").style.display = "";
  getAutoName("Weblogo", null, "weblogo").then(auto => {
    document.getElementById("weblogoExpName").placeholder =
      auto ? t("ui.exp_name_default", { name: auto }) : t("ui.exp_name_optional");
  });
}

async function generateWeblogo() {
  const checked = document.querySelectorAll(".weblogo-protein-check:checked");
  if (checked.length < 2) { toast(t("toast.weblogo_min_proteins"), true); return; }

  const ids = Array.from(checked).map(cb => parseInt(cb.value));
  const selected = weblogoAllProteins.filter(p => ids.includes(p.id));
  const sequences = selected.map(p => p.sequence);

  // 检查序列是否等长
  const n = sequences[0].length;
  if (sequences.some(s => s.length !== n)) {
    toast(t("toast.weblogo_len_mismatch"), true); return;
  }

  const color = document.getElementById("weblogoColor").value;
  const start = parseInt(document.getElementById("weblogoStart").value) || null;
  const end = parseInt(document.getElementById("weblogoEnd").value) || null;
  const multimer = parseInt(document.getElementById("weblogoMultimer").value) || 1;
  weblogoLastParams = { color_scheme: color, start, end, multimer };
  weblogoLastProteins = selected.map(p => ({ id: p.id, name: p.name }));

  // 记住请求（sessionStorage）：仅当次会话内切页回来恢复，命中服务端缓存秒回；
  // 浏览器关闭/重开后不恢复——避免跨会话自动重新生成，白耗性能
  sessionStorage.setItem("weblogoLastRequest", JSON.stringify({
    sequences, color_scheme: color, start, end, multimer, proteins: weblogoLastProteins,
  }));

  const genBtn = document.getElementById("weblogoGenBtn");
  const origText = genBtn.textContent;
  genBtn.disabled = true;
  genBtn.textContent = t("workbench.generating");
  try {
    const r = await API.post("/api/weblogo", { sequences, color_scheme: color, start, end, multimer });
    weblogoLastImage = r.image;
    showWeblogoResult(r, selected.length);
    toast(t("toast.weblogo_done"));
  } catch (err) { toast(err, true); }
  finally { genBtn.disabled = false; genBtn.textContent = origText; }
}

// 切页回来自动恢复上次 weblogo 结果（服务端已缓存，通常秒回，不被中断丢失）
async function restoreWeblogo() {
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem("weblogoLastRequest") || "null"); } catch (_) { return; }
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
    toast(t("toast.weblogo_restored"));
  } catch (_) { /* 首次生成被中断/渲染失败：忽略，用户重新生成即可 */ }
}

async function downloadWeblogo() {
  if (!weblogoLastImage) return;
  const auto = await getAutoName("Weblogo", null, "weblogo") || "weblogo";
  downloadDataUrl(weblogoLastImage, `${auto}.png`);
}

async function saveWeblogoExp() {
  if (!weblogoLastProteins.length) return;
  const customName = document.getElementById("weblogoExpName").value.trim();
  const title = customName || await getAutoName("Weblogo", null, "weblogo")
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
    toast(t("toast.saved_record"));
  } catch (err) { toast(err, true); }
}

// ═════════════════════════════════════════════════════
//  Bulk actions & Undo
// ═════════════════════════════════════════════════════

// ── Proteins bulk ─────────────────────────────────────
function recordCheckedIds(cls) {
  const ids = [];
  const seen = new Set();
  document.querySelectorAll("." + cls + ":checked").forEach(cb => {
    if (seen.has(cb.value)) return;
    seen.add(cb.value);
    ids.push(parseInt(cb.value, 10));
  });
  return ids;
}
function recordAllCount(cls) {
  return new Set([...document.querySelectorAll("." + cls)].map(cb => cb.value)).size;
}
function syncRecordCheck(el, cls) {
  document.querySelectorAll("." + cls).forEach(cb => {
    if (cb.value === el.value) cb.checked = el.checked;
  });
}

function toggleSelectAllProteins(el) {
  document.querySelectorAll(".protein-check").forEach(cb => cb.checked = el.checked);
  updateBulkBar();
}

function updateBulkBar() {
  const ids = recordCheckedIds("protein-check");
  const bar = document.getElementById("bulkBar");
  const count = document.getElementById("bulkCount");
  if (!bar || !count) return;
  if (ids.length) {
    bar.classList.remove("hidden");
    count.textContent = t("workbench.selected_n", { n: ids.length });
  } else {
    bar.classList.add("hidden");
  }
  const selAll = document.getElementById("selectAllProteins");
  const allN = recordAllCount("protein-check");
  if (selAll) selAll.checked = allN > 0 && ids.length === allN;
}

function clearSelection() {
  document.querySelectorAll(".protein-check").forEach(cb => cb.checked = false);
  document.getElementById("selectAllProteins").checked = false;
  updateBulkBar();
}

async function batchDeleteProteins() {
  const ids = recordCheckedIds("protein-check");
  if (!ids.length) return;
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("proteins.delete_selected"),
        message: t("proteins.confirm_batch_delete", { n: ids.length }),
        impact: t("proteins.confirm_delete_impact"),
        danger: true,
      })
    : confirm(t("proteins.confirm_batch_delete", { n: ids.length }));
  if (!ok) return;
  try {
    const r = await API.post("/api/proteins/batch-delete", { ids });
    toast(t("toast.deleted_n_proteins", { n: r.deleted }), false, () => undoRestore());
    clearSelection();
    loadProteins().catch(() => {});
    loadProteinSelects();
    closeDetail();
  } catch (err) { toast(err, true); }
}

async function deleteAllProteins() {
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("proteins.delete_all"),
        message: t("proteins.confirm_delete_all"),
        impact: t("proteins.confirm_delete_all_impact"),
        danger: true,
      })
    : confirm(t("proteins.confirm_delete_all"));
  if (!ok) return;
  const phrase = t("proteins.confirm_phrase");
  const typed = window.BigoUI
    ? await BigoUI.prompt({ title: t("proteins.type_confirm", { phrase }), value: "" })
    : prompt(t("proteins.type_confirm", { phrase }));
  if (typed !== phrase) { toast(t("proteins.cancelled"), true); return; }
  try {
    const r = await API.post("/api/proteins/delete-all", {});
    toast(t("toast.deleted_all_proteins", { n: r.deleted }), false, () => undoRestore());
    document.getElementById("selectAllProteins").checked = false;
    loadProteins().catch(() => {});
    loadProteinSelects();
    closeDetail();
  } catch (err) { toast(err, true); }
}

// ── 批量改标签 ─────────────────────────────────────────
function batchEditTags() {
  const ids = recordCheckedIds("protein-check");
  if (!ids.length) { toast(t("toast.select_proteins"), true); return; }
  document.getElementById("batchTagCount").textContent = ids.length;
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
  const ids = recordCheckedIds("protein-check");
  if (!ids.length) { closeBatchTagModal(); return; }
  const add = document.getElementById("batchTagAddHidden").value;
  const remove = document.getElementById("batchTagRemoveHidden").value;
  if (!add && !remove) { toast(t("toast.need_tag_change"), true); return; }
  try {
    const r = await API.post("/api/proteins/batch-tags", { ids, add, remove });
    toast(t("toast.updated_n_tags", { n: r.updated }));
    closeBatchTagModal();
    loadProteins().catch(() => {});
    loadProteinSelects();
    loadTagFilter();
  } catch (err) { toast(err, true); }
}

// ── Experiments bulk ──────────────────────────────────
function toggleSelectAllExps(el) {
  document.querySelectorAll(".exp-check").forEach(cb => cb.checked = el.checked);
  updateExpBulkBar();
}

function updateExpBulkBar() {
  const ids = recordCheckedIds("exp-check");
  const bar = document.getElementById("expBulkBar");
  const count = document.getElementById("expBulkCount");
  if (!bar || !count) return;
  if (ids.length) {
    bar.classList.remove("hidden");
    count.textContent = t("workbench.selected_n", { n: ids.length });
  } else {
    bar.classList.add("hidden");
  }
  const selAll = document.getElementById("selectAllExps");
  const allN = recordAllCount("exp-check");
  if (selAll) selAll.checked = allN > 0 && ids.length === allN;
}

function clearExpSelection() {
  document.querySelectorAll(".exp-check").forEach(cb => cb.checked = false);
  document.getElementById("selectAllExps").checked = false;
  updateExpBulkBar();
}

async function batchDeleteExperiments() {
  const ids = recordCheckedIds("exp-check");
  if (!ids.length) return;
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("archive.delete_selected"),
        message: t("archive.confirm_batch", { n: ids.length }),
        impact: t("archive.confirm_delete_impact"),
        danger: true,
      })
    : confirm(t("archive.confirm_batch", { n: ids.length }));
  if (!ok) return;
  try {
    const r = await API.post("/api/experiments/batch-delete", { ids });
    toast(t("toast.deleted_n_exps", { n: r.deleted }), false, () => undoRestore());
    clearExpSelection();
    loadExperiments().catch(() => {});
  } catch (err) { toast(err, true); }
}

async function deleteAllExperiments() {
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("archive.delete_all"),
        message: t("archive.confirm_all"),
        impact: t("archive.confirm_all_impact"),
        danger: true,
      })
    : confirm(t("archive.confirm_all"));
  if (!ok) return;
  const phrase = t("proteins.confirm_phrase");
  const typed = window.BigoUI
    ? await BigoUI.prompt({ title: t("proteins.type_confirm", { phrase }), value: "" })
    : prompt(t("proteins.type_confirm", { phrase }));
  if (typed !== phrase) { toast(t("proteins.cancelled"), true); return; }
  try {
    const r = await API.post("/api/experiments/delete-all", {});
    toast(t("toast.deleted_all_exps", { n: r.deleted }), false, () => undoRestore());
    document.getElementById("selectAllExps").checked = false;
    loadExperiments().catch(() => {});
  } catch (err) { toast(err, true); }
}

// ── Undo ──────────────────────────────────────────────
async function undoRestore() {
  try {
    const r = await API.post("/api/undo", {});
    if (r.ok) {
      // 批量撤销（batch-delete / delete-all 压的是一条 bulk 条目）：返回条数而非标题
      let msg = r.bulk ? t("toast.undone_n", { n: r.restored }) : t("toast.undone", { n: r.restored });
      if (r.failed) msg += ` · ${t("toast.undo_partial", { n: r.failed })}`;
      toast(msg, !!r.failed);
      loadProteins().catch(() => {});
      loadExperiments().catch(() => {});
      loadProteinSelects();
    } else {
      toast(r.error || t("toast.cannot_undo"), true);
    }
  } catch (err) { toast(t("toast.undo_failed", { msg: err.message }), true); }
}

