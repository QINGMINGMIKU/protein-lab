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
        <td><input type="checkbox" class="protein-check" value="${p.id}" onchange="syncRecordCheck(this, 'protein-check'); updateBulkBar()"></td>
        <td><span class="clickable" data-action="show-detail" data-id="${p.id}">${esc(p.name)}</span></td>
        <td>${p.mw ? p.mw.toLocaleString() : "-"}</td>
        <td>${p.ext_ox || "-"}</td>
        <td>${p.abs_0_1pct ?? "-"}</td>
        <td>${renderTagChips(p.tag)}</td>
        <td><span class="seq-preview" onclick="this.classList.toggle('expanded')" title="${esc(t("proteins.seq_toggle"))}">${esc(p.sequence)}</span></td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-protein" data-id="${p.id}" data-name="${escAttr(p.name)}">${t("common.delete")}</button></td>
      </tr>
    `).join("");
    const list = document.getElementById("proteinList");
    if (list) {
      list.innerHTML = proteins.map(p => `
        <article class="record-card">
          <div class="record-card-head">
            <label class="record-select"><input type="checkbox" class="protein-check" value="${p.id}" onchange="syncRecordCheck(this, 'protein-check'); updateBulkBar()"></label>
            <h3 data-action="show-detail" data-id="${p.id}">${esc(p.name)}</h3>
          </div>
          <dl>
            <dt>MW</dt><dd>${p.mw ? p.mw.toLocaleString() : "-"}</dd>
            <dt>ε_ox</dt><dd>${p.ext_ox || "-"}</dd>
            <dt>${t("proteins.col_tags")}</dt><dd>${renderTagChips(p.tag) || "-"}</dd>
          </dl>
        </article>`).join("");
    }
    loadTagFilter();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:20px">${t("error.load_failed")}: ${esc(err.message)}</td></tr>`;
  }
}

async function refreshAllProteins() {
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("proteins.refresh"),
        message: t("proteins.confirm_refresh"),
        impact: t("proteins.confirm_refresh_impact"),
        danger: true,
      })
    : confirm(t("proteins.confirm_refresh"));
  if (!ok) return;
  try {
    const r = await API.post("/api/proteins/refresh-all", {});
    toast(t("proteins.refreshed", { n: r.refreshed }));
    loadProteins();
    loadProteinSelects();
  } catch (err) { toast(err, true); }
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
    toast(t("proteins.loaded_file", { name: file.name }));
  };
  reader.readAsText(file);
}

async function addProtein(e) {
  e.preventDefault();
  const form = document.getElementById("addForm");
  const data = Object.fromEntries(new FormData(form));
  try {
    await API.post("/api/proteins", data);
    toast(t("proteins.added"));
    closeAddModal();
    loadProteins();
    loadProteinSelects();
  } catch (err) { toast(err, true); }
}

async function deleteProtein(id, name) {
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("common.delete"),
        message: t("proteins.confirm_delete", { name }),
        impact: t("proteins.confirm_delete_impact"),
        danger: true,
      })
    : confirm(t("proteins.confirm_delete", { name }));
  if (!ok) return;
  try {
    await API.del(`/api/proteins/${id}`);
    toast(t("proteins.deleted"));
    loadProteins();
    loadProteinSelects();
    closeDetail();
  } catch (err) { toast(err, true); }
}

async function importFasta(e) {
  e.preventDefault();
  const form = document.getElementById("importForm");
  const data = Object.fromEntries(new FormData(form));
  try {
    const result = await API.post("/api/proteins/import", {
      fasta: data.fasta, tag: data.tag, notes: data.notes,
    });
    toast(t("proteins.imported", { n: result.imported.length }) +
      (result.skipped.length ? t("proteins.skipped", { n: result.skipped.length }) : ""));
    closeImportModal();
    loadProteins();
    loadProteinSelects();
  } catch (err) { toast(err, true); }
}

async function showDetail(id) {
  try {
    const p = await API.get(`/api/proteins/${id}`);
    currentDetailProtein = p;
    document.getElementById("detailName").textContent = p.name;
    document.getElementById("detailCreateExpBtn").onclick = () => createExpFromProtein();
    const delBtn = document.getElementById("detailDeleteBtn");
    if (delBtn) delBtn.onclick = () => deleteProtein(p.id, p.name);
    document.getElementById("detailContent").innerHTML = `
      <dl class="info-grid">
        <dt>${t("proteins.mw")}</dt><dd>${p.mw ? p.mw.toLocaleString() + " Da" : "-"}</dd>
        <dt>${t("proteins.wyc")}</dt><dd>${p.nW} / ${p.nY} / ${p.nC}</dd>
        <dt>${t("proteins.ext_red")}</dt><dd>${p.ext_red || "-"} M⁻¹·cm⁻¹</dd>
        <dt>${t("proteins.ext_ox")}</dt><dd>${p.ext_ox || "-"} M⁻¹·cm⁻¹</dd>
        <dt>Abs[0.1%]</dt><dd>${p.abs_0_1pct ?? "-"}</dd>
        <dt>${t("proteins.col_tags")}</dt><dd>${esc(p.tag || "-")}</dd>
        <dt>${t("proteins.notes")}</dt><dd>${esc(p.notes || "-")}</dd>
      </dl>
      <div class="sequence-full">${esc(p.sequence)}</div>
      <div style="margin-top:12px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <strong style="font-size:13px">${t("proteins.col_tags")}</strong>
          <button class="btn btn-sm btn-outline" onclick="editProteinTags(${p.id})" id="editTagsBtn">${t("common.edit")}</button>
        </div>
        <div id="proteinTagsDisplay">${renderTagChips(p.tag)}</div>
        <div id="proteinTagsEdit" class="hidden" style="margin-top:4px">
          <div class="tag-input" id="detailTagInput">
            <input type="text" placeholder="${esc(t("proteins.tag_ph"))}" onkeydown="handleTagKey(event, 'detailTagInput')">
          </div>
          <div style="display:flex;gap:6px;margin-top:4px">
            <button class="btn btn-sm btn-primary" onclick="saveProteinTags(${p.id})">${t("common.save")}</button>
            <button class="btn btn-sm btn-outline" onclick="cancelEditTags()">${t("common.cancel")}</button>
          </div>
        </div>
      </div>
    `;
    const panel = document.getElementById("detailPanel");
    panel.classList.remove("hidden");
    if (window.BigoUI) BigoUI.openDrawer(panel);
  } catch (err) { toast(err, true); }
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
    toast(t("toast.tags_updated"));
    // 刷新显示
    cancelEditTags();
    showDetail(pid);
    loadProteins().catch(() => {});
    loadProteinSelects();
  } catch (err) { toast(err, true); }
}

function closeDetail() {
  const panel = document.getElementById("detailPanel");
  if (window.BigoUI) BigoUI.closeDrawer(panel);
  else panel.classList.add("hidden");
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
      if (sel) sel.innerHTML = `<option value="">${id === "dilProtein" ? t("ui.pick_protein_opt") : t("ui.pick_protein_req")}</option>${options}`;
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


