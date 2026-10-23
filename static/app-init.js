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
  if (document.querySelector("#researchFlow")) {
    researchInit();
  }
  // 详情页「载入计算工具」深链：/calculator?load_exp=<id> → 恢复对应计算 tab 数据
  const loadExpId = parseInt(new URLSearchParams(location.search).get("load_exp"), 10);
  if (loadExpId && document.querySelector("#concTable")) {
    loadExpIntoCalc(loadExpId);
  } else if (document.querySelector(".tab-btn")) {
    const m = (location.hash || "").match(/tool=([a-z]+)/);
    if (m) activateTool(m[1], { hash: false });
    else {
      const active = document.querySelector(".tab-btn.active");
      if (active) activateTool(active.dataset.tab);
    }
  }
  window.addEventListener("hashchange", () => {
    if (document.querySelector(".tab-btn")) {
      const m = (location.hash || "").match(/tool=([a-z]+)/);
      if (m) activateTool(m[1], { hash: false });
    }
  });
  document.addEventListener("bigo:locale", () => {
    if (document.querySelector("#proteinTable")) loadProteins().catch(() => {});
    if (document.querySelector("#expTable")) loadExperiments().catch(() => {});
    if (document.querySelector("#researchFlow")) {
      researchFillTagFilter();
      researchFillProteinFilter();
      researchRender();
    }
    if (document.getElementById("compareTable")) loadCompareCandidates();
    if (document.querySelector("#concTable")) { refreshAutoNamePlaceholders(); updateConcHeaders(); }
    updateBulkBar();
    updateExpBulkBar();
  });
  const rl = document.getElementById("detailResearchList");
  if (rl && rl.dataset.expId) {
    loadResearchList(parseInt(rl.dataset.expId, 10));
  }
  if (document.getElementById("compareTable")) {
    loadCompareCandidates();
  }
}
init();

