// ═════════════════════════════════════════════════════
//  研究脉络（v0.1.0）— 证据链：目标 → 实验 → 结论 → 新目标
//  挂载类型不设约束（2026-09-18 取消白名单）：任何类型可挂任何父节点，
//  真实形态就是「筛选战役 → N 个候选结果」的同类型嵌套。
//  服务端只留结构校验：根必须是目标 + 防环。
// ═════════════════════════════════════════════════════
const researchState = {
  trees: [], experiments: [], expMap: {},
  selectedId: null,
  collapsed: new Set(),   // lineflow 折叠态：▾ 按钮切换子层显隐
  view: "list", activeRootId: null,
};

function researchNodeMatch(node, q, tag, prot) {
  if (tag) {
    const tags = (node.tag || "").split(",").map(s => s.trim()).filter(Boolean);
    if (!tags.includes(tag)) return false;
  }
  if (prot) {
    const exp = node.exp_id ? researchState.expMap[node.exp_id] : null;
    const names = (exp && exp.protein_names || "").split(",").map(s => s.trim()).filter(Boolean);
    if (!names.includes(prot)) return false;
  }
  if (q) {
    const exp = node.exp_id ? researchState.expMap[node.exp_id] : null;
    const expTitle = (exp && exp.title) || (node.experiment && node.experiment.title) || "";
    const hay = `${node.title || ""} ${node.tag || ""} ${expTitle}`.toLowerCase();
    if (!hay.includes(q.toLowerCase())) return false;
  }
  return true;
}

function researchFilterMatch(node, q, tag, prot) {
  if (researchNodeMatch(node, q, tag, prot)) return true;
  return (node.children || []).some(c => researchFilterMatch(c, q, tag, prot));
}

function researchFindNode(id) {
  const stack = [...researchState.trees];
  while (stack.length) {
    const n = stack.pop();
    if (n.id === id) return n;
    if (n.children) stack.push(...n.children);
  }
  return null;
}

// 同级兄弟列表：根节点 -> 树列表；子节点 -> 父的 children（排序用）
function researchSiblings(node) {
  if (!node || node.parent_id == null) return researchState.trees;
  const p = researchFindNode(node.parent_id);
  return (p && p.children) || [];
}

// 同级上移/下移：PUT /move 交换 + 重排 sort_order，成功后整树重载
async function researchMove(id, dir) {
  try {
    await API.put(`/api/research/nodes/${id}/move`, { direction: dir });
    await researchLoad();
    if (researchState.selectedId === id) {
      const n = researchFindNode(id);
      if (n) renderResearchDetail(n);
    }
    toast(t("toast.moved"));
  } catch (err) { toast(err, true); }
}

// lineflow 卡片角标 ▾ 切换：折叠/展开子层
function researchToggle(id) {
  if (researchState.collapsed.has(id)) researchState.collapsed.delete(id);
  else researchState.collapsed.add(id);
  researchRender();
}

// lineflow 配色由 CSS 变量统一管理（--lf-line-goal/experiment/conclusion/observation），
// 旧横向流程图常量 RES_FLOW / RES_FLOW_EDGE 在 v0.1.2 lineflow 替换中已删，保留此处说明。

function researchRender(force) {
  const q = (document.getElementById("researchQuery").value || "").trim();
  const tag = document.getElementById("researchTagFilter").value || "";
  const prot = document.getElementById("researchProteinFilter").value || "";
  if (force) { researchLoad().catch(() => {}); return; }
  const flowEl = document.getElementById("researchFlow");
  const scLeft = flowEl.scrollLeft;   // 横向流程图滚动位置：重画 innerHTML 前保存
  const backEl = document.getElementById("researchFlowBack");
  const emptyEl = document.getElementById("researchEmpty");
  if (!researchState.trees.length) {
    flowEl.classList.add("hidden");
    backEl.classList.add("hidden");
    emptyEl.classList.remove("hidden");
    return;
  }
  flowEl.classList.remove("hidden");
  emptyEl.classList.add("hidden");
  if (researchState.view === "list") {
    backEl.classList.add("hidden");
    renderResearchRootList(flowEl, q, tag, prot);
  } else {
    const root = researchFindNode(researchState.activeRootId);
    if (!root) { // 根目标被删（级联删）→ 回落列表
      researchState.view = "list";
      researchState.activeRootId = null;
      backEl.classList.add("hidden");
      renderResearchRootList(flowEl, q, tag, prot);
    } else {
      backEl.classList.remove("hidden");
      document.getElementById("researchFlowBackTitle").textContent = root.title;
      renderResearchFlow(flowEl, [root], q, tag, prot);
    }
  }
  // 选中节点已被删（子树删除）时收起详情
  if (researchState.selectedId != null && !researchFindNode(researchState.selectedId)) {
    researchState.selectedId = null;
    document.getElementById("researchDetail").classList.add("hidden");
    document.getElementById("researchChain").classList.add("hidden");
  }
  flowEl.scrollLeft = scLeft;   // 重画后恢复横向滚动位置
  // 重绘会还原旧 scrollLeft，选中态可能又被裁切/被面板盖住——每次重绘后都补一次露出
  if (researchState.selectedId != null) researchRevealSelected();
}

function renderResearchFlow(flowEl, trees, q, tag, prot) {
  const filtering = !!(q || tag || prot);
  const html = trees.map(tnode => renderEvidenceNode(tnode, q, tag, prot, filtering)).join("");
  flowEl.innerHTML = html
    ? `<ul class="flow-tree">${html}</ul>`
    : `<div class="empty-hint">${t("research.empty_filter")}</div>`;
  flowEl.style.width = "";
  flowEl.style.height = "";
}

function renderEvidenceNode(node, q, tag, prot, filtering) {
  if (filtering && !researchFilterMatch(node, q, tag, prot)) return "";
  const dim = (q || tag || prot) && !researchNodeMatch(node, q, tag, prot) ? " dim" : "";
  const sel = researchState.selectedId === node.id ? " selected" : "";
  const kids = node.children || [];
  const collapsed = researchState.collapsed.has(node.id);
  const childHtml = kids.length && !collapsed
    ? `<ul class="flow-tree">${kids.map(c => renderEvidenceNode(c, q, tag, prot, filtering)).join("")}</ul>`
    : "";
  const stance = node.node_type === "conclusion" ? lineflowStanceChip(node.tag) : "";
  const tags = (node.tag || "").split(",").map(s => s.trim()).filter(Boolean)
    .filter(tg => !["支持", "反驳", "部分", "不确定"].includes(tg))
    .map(tg => `<span class="lf-tag">${esc(tg)}</span>`).join("");
  const collapseBtn = kids.length
    ? `<button class="lf-collapse${collapsed ? "" : " open"}" onclick="event.stopPropagation();researchToggle(${node.id})" title="${collapsed ? t("research.expand") : t("research.collapse")}"><span class="lf-tri" aria-hidden="true"></span></button>`
    : "";
  return `<li class="flow-col${kids.length ? " has-children" : ""}${kids.length && collapsed ? " collapsed" : ""}">
    <div class="evidence-node evidence-node--${node.node_type}${dim}${sel}" onclick="researchSelect(${node.id})">
      <span class="evidence-title">${esc(node.title)}</span>
      <span class="evidence-type">${t("node." + node.node_type)}</span>
      ${stance}${tags}${collapseBtn}
    </div>
    ${childHtml}
  </li>`;
}

function lineflowStanceChip(tag) {
  const key = resStanceKey(tag);
  if (key === "other") return "";
  const labels = {
    support: t("stance.支持"),
    rebut: t("stance.反驳"),
    partial: t("stance.部分"),
    uncertain: t("stance.不确定"),
  };
  return `<span class="stance-chip ${key}">${esc(labels[key])}</span>`;
}

// ── 根目标列表（/research 默认首页：列全部根目标，点进单根流程图）──
function researchRootStats(root) {
  let nodes = 0, exps = 0;
  const walk = n => {
    nodes++;
    if (n.exp_id) exps++;
    (n.children || []).forEach(walk);
  };
  walk(root);
  return { nodes, exps };
}

function researchRootCard(root) {
  const { nodes, exps } = researchRootStats(root);
  const tags = (root.tag || "").split(",").map(s => s.trim()).filter(Boolean);
  const idx = researchState.trees.findIndex(tr => tr.id === root.id);
  return `<div class="res-root-card" onclick="researchOpenRoot(${root.id})">
    <div class="res-root-top">
      <span class="res-root-count">${t("research.nodes_exps", { nodes, exps })}</span>
      <span class="res-root-actions">
        <button class="btn btn-sm" ${idx <= 0 ? "disabled" : ""}
                onclick="event.stopPropagation();researchMove(${root.id}, 'up')" title="${t("research.move_up")}">↑</button>
        <button class="btn btn-sm" ${idx < 0 || idx >= researchState.trees.length - 1 ? "disabled" : ""}
                onclick="event.stopPropagation();researchMove(${root.id}, 'down')" title="${t("research.move_down")}">↓</button>
        <button class="btn btn-sm" onclick="event.stopPropagation();researchEdit(${root.id})">${t("common.edit")}</button>
        <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();researchDelete(${root.id})">${t("common.delete")}</button>
      </span>
    </div>
    <div class="res-root-title">${esc(root.title)}</div>
    ${tags.length ? `<div class="res-flow-tags">${tags.map(tg => esc(tg)).join(" · ")}</div>` : ""}
  </div>`;
}

function renderResearchRootList(flowEl, q, tag, prot) {
  const matched = researchState.trees.filter(r => researchFilterMatch(r, q, tag, prot));
  flowEl.innerHTML = matched.length
    ? `<div class="res-root-list">${matched.map(researchRootCard).join("")}</div>`
    : `<div class="empty-hint">${t("research.empty_roots")}</div>`;
  flowEl.style.width = "";
  flowEl.style.height = "";
}

function researchOpenRoot(id) {
  researchState.view = "flow";
  researchState.activeRootId = id;
  researchState.selectedId = null;
  document.getElementById("researchDetail").classList.add("hidden");
  document.getElementById("researchChain").classList.add("hidden");
  researchRender();
  document.getElementById("researchFlow").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function researchBackToList() {
  researchState.view = "list";
  researchState.activeRootId = null;
  researchState.selectedId = null;
  document.getElementById("researchDetail").classList.add("hidden");
  document.getElementById("researchChain").classList.add("hidden");
  researchRender();
}

// 结论 stance 配色由 CSS .res-tag-chip.support/rebut/partial/uncertain 接管（语义 token）。
function resStanceKey(tag) {
  const m = { 支持: "support", 反驳: "rebut", 部分: "partial", 不确定: "uncertain" };
  for (const t of String(tag || "").split(",").map(s => s.trim())) {
    if (m[t]) return m[t];
  }
  return "other";
}
function resTagChip(tag) {
  const key = resStanceKey(tag);
  const label = key !== "other" ? t("stance." + tag) : tag;
  return `<span class="res-tag-chip ${key}">${esc(label)}</span>`;
}

async function researchSelect(id) {
  let node;
  try { node = await API.get(`/api/research/nodes/${id}`); }
  catch (err) { toast(err, true); return; }
  researchState.selectedId = id;
  researchRender();
  renderResearchChain(node.chain || []);
  renderResearchDetail(node);
  const detailEl = document.getElementById("researchDetail");
  detailEl.classList.remove("hidden");
  if (window.BigoUI) BigoUI.openDrawer(detailEl);
  else detailEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  // reveal 必须在面板打开之后：桌面态 .res-detail-side 是 fixed 悬浮层盖在导图右缘上方
  researchRevealSelected();
}

// 选中节点完整露出：宽节点右缘贴 .res-flow-container（overflow-x:auto）裁切边、
// 或被桌面态悬浮详情面板（fixed, right:24px, 高可达视口底部）盖住时，2px outline
// + 1px offset 画在盒子外会切掉「选择框不完整」。把内容横向左移，直到节点（含外扩框）
// 进入有效可视区（容器视口 ∩ 面板左缘）并留 6px 呼吸位；左缘溢出同理右移。
function researchRevealSelected() {
  const flow = document.getElementById("researchFlow");
  const el = flow && flow.querySelector(".evidence-node.selected");
  if (!el) return;
  const apply = () => {
    const r = el.getBoundingClientRect();
    const c = flow.getBoundingClientRect();
    const PAD = 6;  // > outline 外扩 3px
    let bound = c.right;
    const panel = document.getElementById("researchDetail");
    if (panel && !panel.classList.contains("hidden")
        && window.matchMedia("(min-width: 1024px)").matches) {
      // 桌面态面板 fixed right:24 宽 400：左界确定性计算（不量 rect，避开重排/动画时机）
      const pl = window.innerWidth - 24 - panel.offsetWidth;
      if (pl > c.left + 40) bound = Math.min(bound, pl - PAD);
    }
    let dx = 0;
    if (r.right > bound - PAD) dx = r.right - bound + PAD;
    else if (r.left < c.left + PAD) dx = r.left - c.left - PAD;
    if (dx) flow.scrollBy({ left: dx, behavior: "smooth" });
  };
  requestAnimationFrame(apply);
}

function renderResearchChain(chain) {
  const el = document.getElementById("researchChain");
  el.classList.remove("hidden");
  el.innerHTML = chain.map((c, i) =>
    `${i ? '<span class="res-chain-sep">→</span>' : ""}<span class="res-chain-link" onclick="researchSelect(${c.id})">${esc(c.title)}</span>`
  ).join("");
}

function renderResearchDetail(node) {
  document.getElementById("researchDetailTitle").textContent = node.title;
  const kids = node.children || [];
  const tags = (node.tag || "").split(",").map(s => s.trim()).filter(Boolean);
  let expCard = "";
  if (node.experiment) {
    const e = node.experiment;
    const typeLabel = (window.BigoI18n && BigoI18n.expTypeLabel) ? BigoI18n.expTypeLabel(e.exp_type) : e.exp_type;
    expCard = `<div class="res-exp-card">
      <div class="res-exp-card-head">${t("research.linked_exp")}</div>
      <a class="res-exp-card-title" href="/experiments/${e.id}">${esc(e.title)}</a>
      <div class="res-exp-card-meta">${esc(typeLabel)} · ${esc(e.date || "")} · #${e.id}</div>
    </div>`;
  } else if (node.node_type === "experiment") {
    expCard = `<div class="res-exp-card res-exp-placeholder">${t("research.planned")}</div>`;
  }
  const kidChips = kids.length
    ? `<div class="res-kids"><span class="res-kids-label">${t("research.children")}</span>` +
      kids.map(k => `<span class="res-chain-link" onclick="researchSelect(${k.id})">${esc(k.title)}</span>`).join(" · ") + "</div>"
    : "";
  const currentStance = resStanceKey(node.tag);
  const currentStanceValue = currentStance === "support" ? "支持"
    : currentStance === "rebut" ? "反驳"
    : currentStance === "partial" ? "部分"
    : currentStance === "uncertain" ? "不确定" : "";
  const stanceCtrl = node.node_type === "conclusion"
    ? `<div class="res-stance-ctrl">
        <span class="res-stance-label">${t("research.stance")}</span>
        <select id="detailStanceSel" data-prev="${esc(currentStanceValue)}" onchange="researchChangeStance(${node.id}, this.value)">
          <option value=""${currentStanceValue === "" ? " selected" : ""}>${t("research.stance_clear")}</option>
          <option value="支持"${currentStanceValue === "支持" ? " selected" : ""}>${t("stance.支持")}</option>
          <option value="反驳"${currentStanceValue === "反驳" ? " selected" : ""}>${t("stance.反驳")}</option>
          <option value="部分"${currentStanceValue === "部分" ? " selected" : ""}>${t("stance.部分")}</option>
          <option value="不确定"${currentStanceValue === "不确定" ? " selected" : ""}>${t("stance.不确定")}</option>
        </select>
       </div>`
    : "";
  const cachedNode = researchFindNode(node.id) || node;
  const sibs = researchSiblings(cachedNode);
  const sIdx = sibs.findIndex(s => s.id === node.id);
  const moveCtrl = `
      <button class="btn btn-sm" ${sIdx <= 0 ? "disabled" : ""}
              onclick="researchMove(${node.id}, 'up')" title="${t("research.move_up")}">↑</button>
      <button class="btn btn-sm" ${sIdx < 0 || sIdx >= sibs.length - 1 ? "disabled" : ""}
              onclick="researchMove(${node.id}, 'down')" title="${t("research.move_down")}">↓</button>`;
  document.getElementById("researchDetailContent").innerHTML = `
    <div class="res-detail-meta">
      <span class="res-badge res-badge-${node.node_type}">${t("node." + node.node_type)}</span>
      ${tags.map(tg => node.node_type === "conclusion" ? resTagChip(tg) : `<span class="res-tag-chip">${esc(tg)}</span>`).join("")}
      <span class="res-detail-id">#${node.id}</span>
    </div>
    ${stanceCtrl}
    ${expCard}
    ${node.detail ? `<div class="res-detail-txt">${esc(node.detail)}</div>` : ""}
    ${kidChips}
    <div class="res-detail-actions">
      ${moveCtrl}
      <button class="btn btn-primary" onclick="researchAddChild(${node.id})">${t("research.add_child")}</button>
      <button class="btn" onclick="researchEdit(${node.id})">${t("common.edit")}</button>
      <button class="btn btn-danger" onclick="researchDelete(${node.id})">${t("research.delete_tree")}</button>
    </div>`;
}

// stance 控件保存：复用 tag 字段（零 schema 变更）
// 选 stance → 移除 tag 里旧的 stance 词 + 加入新；选「清除」→ 移除所有 stance 词；不动 PD1/BLI 等普通 tag
async function researchChangeStance(nodeId, stanceValue) {
  const sel = document.getElementById("detailStanceSel");
  const prevValue = sel ? sel.getAttribute("data-prev") || "" : "";
  // 复用 researchState 缓存的节点（避免额外 GET）；cache miss 时再 GET
  let curNode = researchFindNode(nodeId);
  if (!curNode) {
    try { curNode = await API.get(`/api/research/nodes/${nodeId}`); }
    catch (err) { toast(err, true); if (sel) sel.value = prevValue; return; }
  }
  const STANCE_KEYWORDS = ["支持", "反驳", "部分", "不确定"];
  const parts = String(curNode.tag || "").split(",").map(s => s.trim()).filter(Boolean);
  const kept = parts.filter(p => !STANCE_KEYWORDS.includes(p));
  if (stanceValue) kept.push(stanceValue);
  const newTag = kept.join(",");
  try {
    // update_node 是全量更新（title 必填 + 根须 goal + 防环），挂立场时必须带上 node_type /
    // title / parent_id 等 leaf 字段，否则 title="" 被 400 挡。设计：tag 是 leaf 字段，但 API
    // 没开 PATCH 端点，前端必须传齐其他字段。
    await API.put(`/api/research/nodes/${nodeId}`, {
      tag: newTag,
      node_type: curNode.node_type,
      title: curNode.title,
      detail: curNode.detail || "",
      parent_id: curNode.parent_id,
      exp_id: curNode.exp_id,
    });
    if (sel) sel.setAttribute("data-prev", stanceValue);
    await researchLoad();
    // 重新选中刷新详情面板（detail panel 不会自动重建——研究脉络 load 后 selectedId 保留即可）
    const refreshed = researchFindNode(nodeId);
    if (refreshed) renderResearchDetail(refreshed);
    toast(t("toast.stance_updated"));
  } catch (err) {
    toast(err, true);
    if (sel) sel.value = prevValue;  // 失败时回滚 UI
  }
}

function researchOpenModal(mode, node, parent) {
  const nid = document.getElementById("researchNodeId");
  const pid = document.getElementById("researchParentId");
  const typeSel = document.getElementById("researchNodeType");
  const titleInp = document.getElementById("researchTitle");
  const detailInp = document.getElementById("researchDetailTxt");
  const tagInp = document.getElementById("researchTag");
  const expSel = document.getElementById("researchExpSel");
  const expSearch = document.getElementById("researchExpSearch");
  // 每次都重建实验下拉（实验可能新归档）；未加载过则先拉取
  if (researchState.experiments.length) {
    researchExpFill();
  } else {
    researchLoad().then(researchExpFill);
  }
  expSearch.value = "";
  researchExpFilter();
  if (mode === "edit" && node) {
    document.getElementById("researchModalTitle").textContent = t("common.edit");
    nid.value = node.id;
    pid.value = node.parent_id || "";
    typeSel.value = node.node_type;
    titleInp.value = node.title;
    detailInp.value = node.detail || "";
    tagInp.value = node.tag || "";
    expSel.value = node.exp_id || "";
  } else {
    document.getElementById("researchModalTitle").textContent = mode === "root" ? t("research.add_root") : t("research.add_child");
    nid.value = "";
    pid.value = parent ? parent.id : "";
    // 默认继承父节点类型（筛选战役下加候选结果就是同类型嵌套）；加根默认 goal
    typeSel.value = parent ? parent.node_type : "goal";
    titleInp.value = "";
    detailInp.value = "";
    tagInp.value = "";
    expSel.value = "";
    expSearch.value = "";
  }
  document.getElementById("researchModal").classList.remove("hidden");
  titleInp.focus();
}

function researchAddRoot() { researchOpenModal("root", null, null); }
function researchAddChild(parentId) {
  const parent = researchFindNode(parentId) || { id: parentId, node_type: "goal" };
  researchOpenModal("child", null, parent);
}
function researchEdit(id) { researchOpenModal("edit", researchFindNode(id) || null, null); }
function researchCloseModal() { document.getElementById("researchModal").classList.add("hidden"); }
function researchCloseDetail() {
  const el = document.getElementById("researchDetail");
  if (window.BigoUI) BigoUI.closeDrawer(el);
  else el.classList.add("hidden");
  document.getElementById("researchChain").classList.add("hidden");
  researchState.selectedId = null;
  researchRender();
}

async function researchSave(e) {
  e.preventDefault();
  const id = document.getElementById("researchNodeId").value;
  const rawPid = document.getElementById("researchParentId").value;
  const rawExp = document.getElementById("researchExpSel").value;
  const payload = {
    node_type: document.getElementById("researchNodeType").value,
    title: document.getElementById("researchTitle").value.trim(),
    detail: document.getElementById("researchDetailTxt").value,
    parent_id: rawPid ? Number(rawPid) : null,
    exp_id: rawExp ? Number(rawExp) : null,
    tag: document.getElementById("researchTag").value.trim(),
  };
  try {
    if (id) await API.put(`/api/research/nodes/${id}`, payload);
    else await API.post("/api/research/nodes", payload);
    researchCloseModal();
    toast(id ? t("toast.updated") : t("toast.saved"));
    await researchLoad();
  } catch (err) { toast(err, true); }
}

async function researchDelete(id) {
  const node = researchFindNode(id);
  const label = node ? node.title : `#${id}`;
  const ok = window.BigoUI
    ? await BigoUI.confirm({
        title: t("research.delete_tree"),
        message: t("research.confirm_delete", { label }),
        impact: t("research.confirm_delete_impact"),
        danger: true,
      })
    : confirm(t("research.confirm_delete", { label }));
  if (!ok) return;
  try {
    await API.del(`/api/research/nodes/${id}`);
    if (researchState.selectedId === id) researchCloseDetail();
    toast(t("toast.deleted"));
    await researchLoad();
  } catch (err) { toast(err, true); }
}

function researchExpFill() {
  const sel = document.getElementById("researchExpSel");
  sel.innerHTML = '<option value="">' + t("research.exp_placeholder") + '</option>' +
    researchState.experiments.map(e => {
      const typeLabel = (window.BigoI18n && BigoI18n.expTypeLabel) ? BigoI18n.expTypeLabel(e.exp_type) : e.exp_type;
      return `<option value="${e.id}">${esc(e.date || "")} ${esc(e.title)} — ${esc(typeLabel)}</option>`;
    }).join("");
}
function researchExpFilter() {
  const q = (document.getElementById("researchExpSearch").value || "").toLowerCase();
  [...document.getElementById("researchExpSel").options].forEach(o => {
    o.hidden = q !== "" && !o.text.toLowerCase().includes(q);
  });
}
function researchFillTagFilter() {
  const sel = document.getElementById("researchTagFilter");
  const seen = new Set();
  const stack = [...researchState.trees];
  while (stack.length) {
    const n = stack.pop();
    (n.tag || "").split(",").map(s => s.trim()).filter(Boolean).forEach(t => seen.add(t));
    if (n.children) stack.push(...n.children);
  }
  const cur = sel.value;
  sel.innerHTML = '<option value="">' + t("research.all_tags") + '</option>' +
    [...seen].sort().map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  sel.value = [...sel.options].some(o => o.value === cur) ? cur : "";
}
function researchFillProteinFilter() {
  const sel = document.getElementById("researchProteinFilter");
  const seen = new Set();
  researchState.experiments.forEach(e =>
    (e.protein_names || "").split(",").map(s => s.trim()).filter(Boolean).forEach(p => seen.add(p)));
  const cur = sel.value;
  sel.innerHTML = '<option value="">' + t("research.all_proteins") + '</option>' +
    [...seen].sort().map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
  sel.value = [...sel.options].some(o => o.value === cur) ? cur : "";
}
async function researchLoad() {
  const [trees, exps] = await Promise.all([
    API.get("/api/research/nodes"),
    API.get("/api/experiments?limit=500"),
  ]);
  researchState.trees = trees;
  researchState.experiments = exps;
  researchState.expMap = {};
  exps.forEach(e => { researchState.expMap[e.id] = e; });
  researchFillTagFilter();
  researchFillProteinFilter();
  researchRender();
}
async function researchInit() {
  try {
    await researchLoad();
    // 深链支持：/research?root=<goalId>（实验详情页研究脉络链接）→ 定位到对应目标树
    const rid = parseInt(new URLSearchParams(location.search).get("root"), 10);
    if (rid && researchFindNode(rid)) researchOpenRoot(rid);
  } catch (_) {}
}

function compareSelectedIds() {
  return [...document.querySelectorAll(".compare-check:checked")].map(el => parseInt(el.value, 10)).filter(Boolean);
}

async function loadCompareCandidates() {
  const box = document.getElementById("compareList");
  if (!box) return;
  const type = document.getElementById("compareTypeFilter")?.value || "";
  const qs = type ? `calc_type=${encodeURIComponent(type)}&limit=200` : "limit=200";
  try {
    const exps = await API.get(`/api/experiments?${qs}`);
    if (!exps.length) {
      box.innerHTML = `<p class="empty-hint">${t("common.empty")}</p>`;
      return;
    }
    box.innerHTML = exps.map(e => {
      const typeLabel = (window.BigoI18n && e.calc_type)
        ? BigoI18n.calcTypeLabel(e.calc_type) : (e.exp_type || "");
      return `<label class="checkbox-label">
        <input type="checkbox" class="compare-check" value="${e.id}">
        <span><strong>${esc(e.title)}</strong>
        <span style="color:var(--graphite);font-size:12px"> · ${esc(e.date || "")} · ${esc(typeLabel)}</span></span>
      </label>`;
    }).join("");
  } catch (err) {
    box.innerHTML = `<p class="empty-hint">${t("error.load_failed")}</p>`;
    toast(err, true);
  }
}

async function runCompare() {
  const ids = compareSelectedIds();
  const meta = document.getElementById("compareMeta");
  const table = document.getElementById("compareTable");
  if (!table) return;
  if (ids.length < 2) {
    setEvidence("compareMeta", "empty", t("compare.empty"));
    return;
  }
  setEvidence("compareMeta", "processing", t("workbench.status_processing"));
  try {
    const r = await fetch("/api/experiments/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) {
      const msg = data.error === "calc_type_mismatch" ? t("compare.mismatch")
        : data.error === "need_two" ? t("compare.need_two")
        : data.error === "not_found" ? t("compare.missing")
        : t("error.generic");
      setEvidence("compareMeta", "fail", msg);
      toast(backendError(data, r.status), true);
      return;
    }
    const typeLabel = window.BigoI18n ? BigoI18n.calcTypeLabel(data.calc_type) : data.calc_type;
    setEvidence("compareMeta", data.rows.length ? "done" : "empty",
      data.rows.length ? typeLabel : t("compare.no_metrics"));
    const head = table.querySelector("thead");
    const body = table.querySelector("tbody");
    const colH = (data.columns || []).map(c => `<th>${esc(c.title)}<div style="font-weight:400;color:var(--graphite)">${esc(c.date || "")}</div></th>`).join("");
    head.innerHTML = `<tr><th>${t("compare.pick")}</th>${colH}</tr>`;
    body.innerHTML = (data.rows || []).map(row => {
      const cells = (row.values || []).map(v => {
        if (v == null) return "<td>—</td>";
        const n = Number(v);
        const txt = Number.isFinite(n) ? (+n.toPrecision(4)).toString() : String(v);
        return `<td>${esc(txt)}${row.unit ? ` <span style="color:var(--graphite)">${esc(row.unit)}</span>` : ""}</td>`;
      }).join("");
      return `<tr class="${row.highlight ? "compare-hot" : ""}"><td>${esc(row.label)}</td>${cells}</tr>`;
    }).join("") || `<tr><td colspan="${1 + (data.columns || []).length}">${t("compare.no_metrics")}</td></tr>`;
  } catch (err) {
    setEvidence("compareMeta", "fail", t("workbench.status_fail"));
    toast(err, true);
  }
}

