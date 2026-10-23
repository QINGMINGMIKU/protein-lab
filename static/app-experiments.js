// ═════════════════════════════════════════════════════
//  Experiments Page
// ═════════════════════════════════════════════════════

// ── 实验档案列表：拉取 → 客户端关键词过滤 → 桌面表 / 移动卡双渲染 ─
// 原「从实验复制」tab 已删，这里成为**唯一**的实验浏览 + 载入面：
// 可载入的行（_loadable，见 identity.is_loadable）标题直接深链到计算器，
// 不可载入的（纯记录 / weblogo）回落详情页。
let expAllExps = [];
// limit=100：原 copy tab 搜的就是最近 100 条，档案页默认 50 会让搜索覆盖面静默缩水一半。
// 两条副作用都接受了：① models.exp_list 的 calc_type 分支会放大到 max(limit*20, 500)
// 再 Python 过滤切片，limit=100 → 取 2000 行；② 一次重绘 100 行（无虚拟滚动，与原 tab 的
// 100 张卡片同量级）。真到顶了在表尾显式提示（archive.search_capped），不静默少给。
const EXP_LIST_LIMIT = 100;

async function loadExperiments() {
  const tbody = document.querySelector("#expTable tbody");
  if (!tbody) return;
  updateExportLink();
  try {
    const type = document.getElementById("expTypeFilter")?.value || "";
    const qs = type ? `calc_type=${encodeURIComponent(type)}&` : "";
    expAllExps = await API.get(`/api/experiments?${qs}limit=${EXP_LIST_LIMIT}`);
    renderExpList();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:20px">${t("error.load_failed")}: ${esc(err.message)}</td></tr>`;
  }
}

// 关键词匹配：标题或关联蛋白名子串（小写化）。原样移植自被删的 copy tab，语义不变。
// 已知边界：protein_names 来自人工关联表而非存档 params，所以「忘了关联蛋白」的实验搜不到。
function expMatchesQuery(e, q) {
  return `${e.title || ""} ${e.protein_names || ""}`.toLowerCase().includes(q);
}

function filterExpList() { renderExpList(); }

function renderExpList() {
  const tbody = document.querySelector("#expTable tbody");
  if (!tbody) return;
  const q = (document.getElementById("expSearchInput")?.value || "").trim().toLowerCase();
  // 重绘会重建每一行的复选框 → 先记下当前勾选，渲染后回填。
  // 否则「勾两行 → 搜索把某行滤掉 → 清空搜索」勾选就静默丢了。
  const checked = new Set(recordCheckedIds("exp-check"));
  const exps = q ? expAllExps.filter(e => expMatchesQuery(e, q)) : expAllExps;

  if (!exps.length) {
    const empty = `<p style="color:var(--graphite);font-size:13px;text-align:center;padding:40px">${t("ui.no_matching_exp")}</p>`;
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:20px;color:var(--graphite)">${t("ui.no_matching_exp")}</td></tr>`;
    const list0 = document.getElementById("expList");
    if (list0) list0.innerHTML = empty;
    updateExpBulkBar();
    return;
  }

  const firstPage = exps.length;   // 供上限提示判断
  tbody.innerHTML = exps.map(e => {
    // 关联蛋白只显示第一个，hover 显示完整列表
    const pnames = (e.protein_names || "").split(",").map(s => s.trim()).filter(Boolean);
    const pcell = pnames.length
      ? `<span title="${esc(e.protein_names)}">${esc(pnames[0])}${pnames.length > 1 ? t("archive.and_more", { n: pnames.length - 1 }) : ""}</span>`
      : "-";
    const typeLabel = (window.BigoI18n && BigoI18n.calcTypeLabel && e.calc_type)
      ? BigoI18n.calcTypeLabel(e.calc_type)
      : ((window.BigoI18n && BigoI18n.expTypeLabel) ? BigoI18n.expTypeLabel(e.exp_type) : e.exp_type);
    // 可载入 → 直接进计算器（深链，由 calculator 页的 loadExpIntoCalc 消费）；
    // 不可载入 → 详情页。纯 href 切换、零 JS：档案页没有计算器 DOM，
    // applyCopyAndSwitch 会去点 .tab-btn 而 null 崩，所以必须站内导航。
    const href = e.loadable ? `/calculator?load_exp=${e.id}` : `/experiments/${e.id}`;
    const titleAttr = e.loadable ? ` title="${esc(t("detail.load_tool"))}"` : "";
    // 详情图标只在可载入行出现（其余行的标题已经指向详情），列本身保留占位以对齐
    const detailCell = e.loadable
      ? `<a class="btn btn-sm btn-icon" href="/experiments/${e.id}" title="${esc(t("common.details"))}" aria-label="${esc(t("common.details"))}">
           <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8Z" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>
         </a>`
      : "";
    return `
      <tr>
        <td><input type="checkbox" class="exp-check" value="${e.id}"${checked.has(String(e.id)) ? " checked" : ""} onchange="syncRecordCheck(this, 'exp-check'); updateExpBulkBar()"></td>
        <td class="exp-date">${e.date || "-"}</td>
        <td><a href="${href}"${titleAttr}>${esc(e.title)}</a></td>
        <td class="exp-type"><span class="badge">${esc(typeLabel)}</span></td>
        <td>${pcell}</td>
        <td>${esc((e.notes || "").substring(0, 40))}</td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-exp" data-id="${e.id}" data-name="${escAttr(e.title)}">${t("common.delete")}</button></td>
        <td><a class="btn btn-sm btn-outline" href="/api/experiments/${e.id}/export" title="${esc(t("archive.export_one"))}">${t("common.export")}</a></td>
        <td>${detailCell}</td>
      </tr>
    `;
  }).join("");

  // 搜索只覆盖最近 EXP_LIST_LIMIT 条——到顶了就明说，别让人以为「搜不到 = 不存在」
  if (firstPage >= EXP_LIST_LIMIT) {
    tbody.innerHTML += `<tr><td colspan="9" style="text-align:center;padding:10px;color:var(--graphite);font-size:12px">${t("archive.search_capped")}</td></tr>`;
  }

  const list = document.getElementById("expList");
  if (list) {
    list.innerHTML = exps.map(e => {
      const pnames = (e.protein_names || "").split(",").map(s => s.trim()).filter(Boolean);
      const typeLabel = (window.BigoI18n && BigoI18n.calcTypeLabel && e.calc_type)
        ? BigoI18n.calcTypeLabel(e.calc_type)
        : ((window.BigoI18n && BigoI18n.expTypeLabel) ? BigoI18n.expTypeLabel(e.exp_type) : e.exp_type);
      const href = e.loadable ? `/calculator?load_exp=${e.id}` : `/experiments/${e.id}`;
      return `<article class="record-card">
        <div class="record-card-head">
          <label class="record-select"><input type="checkbox" class="exp-check" value="${e.id}"${checked.has(String(e.id)) ? " checked" : ""} onchange="syncRecordCheck(this, 'exp-check'); updateExpBulkBar()"></label>
          <h3><a href="${href}"${e.loadable ? ` title="${esc(t("detail.load_tool"))}"` : ""}>${esc(e.title)}</a></h3>
        </div>
        <dl>
          <dt>${t("archive.col_date")}</dt><dd>${esc(e.date || "-")}</dd>
          <dt>${t("archive.col_type")}</dt><dd>${esc(typeLabel)}</dd>
          <dt>${t("archive.col_protein")}</dt><dd>${esc(pnames[0] || "-")}${pnames.length > 1 ? t("archive.and_more", { n: pnames.length - 1 }) : ""}</dd>
        </dl>
      </article>`;
    }).join("");
  }
  // 重绘后刷新批量条：此前 loadExperiments() 从不调它，切换类型下拉后批量条会残留过期计数
  updateExpBulkBar();
}

function showExpAddModal(prefill = null) {
  document.getElementById("expModalTitle").textContent = t("archive.new");
  document.getElementById("expModal").classList.remove("hidden");
  loadGoalOptions();  // v0.1.1：拉研究目标下拉
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
  const ng = document.getElementById("expNewGoal"); if (ng) ng.value = "";
}

async function loadGoalOptions() {
  // 保存弹窗下拉：拉已有 goal 节点轻量列表
  try {
    const list = await API.get("/api/research/goals");
    const sel = document.getElementById("expGoalSel");
    if (!sel) return;
    sel.innerHTML = '<option value="">' + t("archive.no_goal") + '</option>'
      + list.map(g => `<option value="${g.id}">${esc(g.title)}${g.tag ? "  · " + esc(g.tag) : ""}</option>`).join("");
  } catch (_) { /* 拉不到不阻塞保存 */ }
}

// 公共：从「属于哪个研究目标」控件收集 {goal_id|new_goal|...}（保存弹窗专用）
function readGoalAttachFromForm(prefix = "exp") {
  const sel = document.getElementById(prefix + "GoalSel");
  const inp = document.getElementById(prefix + "NewGoal");
  const selVal = sel ? sel.value.trim() : "";
  const inpVal = inp ? inp.value.trim() : "";
  if (selVal) return { goal_id: parseInt(selVal, 10) };
  if (inpVal) return { new_goal: { title: inpVal, tag: "" } };
  return {};
}

// 公共：从-计算存档 3 处复用：弹「属于哪个研究目标？」（默认暂不关联 = 0）
// 返回 {goal_id|new_goal|...}；用户取消 = 取消整个存档动作（不保存）
async function promptGoalAttach() {
  let goals = [];
  try { goals = await API.get("/api/research/goals"); } catch (_) { return {}; }
  const options = [{ id: 0, label: t("ui.pick_goal_none") }].concat(
    goals.map(g => ({ id: g.id, label: g.title + (g.tag ? "  · " + g.tag : "") }))
  );
  if (window.BigoUI && BigoUI.pick) {
    const picked = await BigoUI.pick({
      title: t("ui.pick_goal"),
      options,
      allowCustom: true,
      customLabel: t("ui.pick_goal_new"),
    });
    if (picked === null) return null;
    if (picked.custom) return { new_goal: { title: picked.custom, tag: "" } };
    const item = picked.item;
    if (!item || !item.id) return {};
    return { goal_id: item.id };
  }
  return {};
}

async function promptExpMount(expType) {
  let list = [];
  try { list = await API.get(`/api/experiments?type=${encodeURIComponent(expType)}&limit=50`); }
  catch (_) { return {}; }
  const options = [{ id: 0, label: t("ui.pick_mount_new") }].concat(
    list.map(e => ({
      id: e.id,
      label: `[${e.id}] ${e.title || t("ui.exp_fallback", { id: e.id })}${e.date ? "  ·  " + e.date : ""}`,
    }))
  );
  if (window.BigoUI && BigoUI.pick) {
    const picked = await BigoUI.pick({
      title: t("ui.pick_mount"),
      message: t("exp_type." + expType),
      impact: list.length ? t("ui.pick_mount_hint") : t("ui.no_mount_targets"),
      options,
    });
    if (picked === null) return null;
    const item = picked.item;
    if (!item || !item.id) return {};
    return { exp_id: item.id };
  }
  return {};
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
      toast(t("toast.invalid_json", { k }), true);
      return;
    }
  }
  try {
    const saved = await API.post("/api/experiments", {
      title: data.title, exp_type: data.exp_type,
      protein_ids: proteinIds, date: data.date,
      params: data.params, results: data.results, notes: data.notes,
      ...readGoalAttachFromForm("exp"),
    });
    toast(saved.goal_node_id ? t("toast.saved_exp_linked") : t("toast.saved_exp"));
    closeExpModal();
    loadExperiments();
  } catch (err) { toast(err, true); }
}

async function showExpDetail(id) {
  try {
    const e = await API.get(`/api/experiments/${id}`);
    const titleEl = document.getElementById("expDetailTitle");
    titleEl.innerHTML = `<span id="expDetailTitleText">${esc(e.title)}</span> <button class="btn btn-sm btn-outline" onclick="editExpTitle(${e.id})" style="margin-left:8px">${t("common.edit")}</button>`;
    const paramsStr = JSON.stringify(e.params || {}, null, 2);
    const resultsStr = JSON.stringify(e.results || {}, null, 2);
    const typeLabel = (window.BigoI18n && BigoI18n.expTypeLabel) ? BigoI18n.expTypeLabel(e.exp_type) : e.exp_type;
    document.getElementById("expDetailContent").innerHTML = `
      <dl class="info-grid">
        <dt>${t("detail.type")}</dt><dd>${esc(typeLabel)}</dd>
        <dt>${t("detail.date")}</dt><dd>${e.date || "-"}</dd>
        <dt>${t("detail.proteins")}</dt><dd>${esc(e.protein_names || t("detail.no_protein"))}</dd>
        <dt>${t("detail.notes")}</dt><dd id="expDetailNotes">${esc(e.notes || "-")}</dd>
        <dt>${t("detail.research")}</dt>
        <dd>
          <div id="detailResearchList" style="display:inline">${t("detail.loading")}</div>
          <button class="btn btn-sm btn-outline" onclick="attachGoalPrompt(${e.id})" style="margin-left:8px">${t("detail.attach_goal")}</button>
        </dd>
      </dl>
      <div style="margin-top:12px"><strong>${t("detail.params")}</strong></div>
      <pre style="background:var(--instrument);padding:10px;border:1px solid var(--rule);font-size:12px;max-height:150px;overflow:auto">${esc(paramsStr)}</pre>
      <div style="margin-top:8px"><strong>${t("detail.results")}</strong></div>
      <pre style="background:var(--instrument);padding:10px;border:1px solid var(--rule);font-size:12px;max-height:200px;overflow:auto">${esc(resultsStr)}</pre>
    `;
    document.getElementById("expDetailPanel").classList.remove("hidden");
    loadResearchList(e.id);
  } catch (err) { toast(err, true); }
}

async function loadResearchList(expId) {
  const el = document.getElementById("detailResearchList");
  if (!el) return;
  try {
    const trees = await API.get("/api/research/nodes");
    const links = [];
    for (const root of trees) collectLinks(root, root, expId, links);
    if (!links.length) { el.textContent = t("ui.unlinked"); return; }
    el.innerHTML = links.map(l => `<a href="/research?root=${l.goalId}" target="_blank">${esc(l.goalTitle)}</a>`).join(" · ");
  } catch (_) { el.textContent = t("error.load_failed"); }
}

// 沿父链回溯到最近 goal：matchedExperiment 是命中的 experiment 节点，逐层上溯 parent_id
// 找最近祖先 node_type==='goal'。build_trees 返回的节点不带 parent_id（嵌套 children 隐式），
// 所以引入 rootAsGoal 路径：在递归路径上缓存"走到当前节点时最近 goal 祖先"，
// 命中 experiment 节点时直接用这个祖先。
function collectLinks(node, nearestGoalSoFar, expId, out) {
  const here = node.node_type === "goal" ? node : nearestGoalSoFar;
  if (node.node_type === "experiment" && node.exp_id === expId && here) {
    out.push({ goalId: here.id, goalTitle: here.title });
  }
  for (const c of (node.children || [])) collectLinks(c, here, expId, out);
}

async function attachGoalPrompt(expId) {
  let goals = [];
  try { goals = await API.get("/api/research/goals"); } catch (_) { toast(t("toast.goals_failed"), true); return; }
  const options = goals.map(g => ({ id: g.id, label: g.title + (g.tag ? "  · " + g.tag : "") }));
  if (!options.length && window.BigoUI && BigoUI.prompt) {
    const custom = await BigoUI.prompt({ title: t("detail.attach_goal"), label: t("ui.pick_goal_new") });
    if (!custom) return;
    try {
      await API.post(`/api/experiments/${expId}/attach-goal`, { new_goal: { title: custom, tag: "" } });
      toast(t("toast.attached"));
      loadResearchList(expId);
    } catch (err) { toast(err, true); }
    return;
  }
  const picked = window.BigoUI && BigoUI.pick
    ? await BigoUI.pick({
        title: t("detail.attach_goal"),
        options,
        allowCustom: true,
        customLabel: t("ui.pick_goal_new"),
      })
    : null;
  if (!picked) return;
  let body;
  if (picked.custom) body = { new_goal: { title: picked.custom, tag: "" } };
  else if (picked.item && picked.item.id) body = { goal_id: picked.item.id };
  else return;
  try {
    await API.post(`/api/experiments/${expId}/attach-goal`, body);
    toast(t("toast.attached"));
    loadResearchList(expId);
  } catch (err) { toast(err, true); }
}

async function editExpTitle(id) {
  const titleEl = document.getElementById("expDetailTitleText");
  const current = titleEl.textContent;
  const input = document.createElement("input");
  input.type = "text"; input.value = current;
  input.style.cssText = "font-size:18px;font-weight:600;padding:4px 8px;border:1px solid var(--rule);width:300px";
  titleEl.replaceWith(input);
  input.focus();
  input.onblur = input.onkeydown = async function (ev) {
    if (ev && ev.type === "keydown" && ev.key !== "Enter") return;
    const newTitle = input.value.trim() || current;
    try {
      await API.put(`/api/experiments/${id}`, { title: newTitle });
      toast(t("toast.updated"));
    } catch (err) { toast(err, true); }
    showExpDetail(id);
  };
}

// Update export link with current filter
function updateExportLink() {
  const type = document.getElementById("expTypeFilter")?.value || "";
  const link = document.getElementById("exportBtn");
  if (link) link.href = "/api/experiments/export" + (type ? "?calc_type=" + encodeURIComponent(type) : "");
}

function closeExpDetail() {
  document.getElementById("expDetailPanel").classList.add("hidden");
}

async function deleteExp(id, name) {
  const label = name || ("#" + id);
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("common.delete"),
        message: t("archive.confirm_delete_named", { name: label }),
        impact: t("archive.confirm_delete_impact"),
        danger: true,
      })
    : confirm(t("archive.confirm_delete_named", { name: label }));
  if (!ok) return;
  try {
    await API.del(`/api/experiments/${id}`);
    toast(t("toast.deleted"));
    loadExperiments();
  } catch (err) { toast(err, true); }
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

