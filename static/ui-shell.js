/* Bigo.bio BDA Workbench — mobile menu, drawers, dialogs */
(function (global) {
  function t(key, params) {
    return (global.BigoI18n && global.BigoI18n.t) ? global.BigoI18n.t(key, params) : key;
  }

  let menuOpen = false;
  let lastFocus = null;
  let activeDialog = null;

  function qs(id) { return document.getElementById(id); }

  function lockScroll(lock) {
    document.documentElement.classList.toggle("nav-open", lock);
    document.body.style.overflow = lock ? "hidden" : "";
  }

  function focusables(root) {
    return [...root.querySelectorAll("a, button, input, select, textarea, [tabindex]:not([tabindex='-1'])")]
      .filter(el => !el.disabled && el.getClientRects().length > 0);
  }

  function trapKey(e, root) {
    if (e.key === "Escape") {
      e.preventDefault();
      if (activeDialog) {
        const cancel = qs("bigoDialogCancel");
        if (cancel) cancel.click();
        else closeDialog(false);
      } else closeMenu();
      return;
    }
    if (e.key !== "Tab") return;
    const list = focusables(root);
    if (!list.length) return;
    const first = list[0], last = list[list.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  }

  function openMenu() {
    const menu = qs("siteMenu");
    const toggle = qs("menuToggle");
    if (!menu) return;
    menuOpen = true;
    lastFocus = document.activeElement;
    menu.classList.add("is-open");
    menu.setAttribute("aria-hidden", "false");
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    lockScroll(true);
    const first = focusables(menu)[0];
    if (first) first.focus();
  }

  function closeMenu() {
    const menu = qs("siteMenu");
    const toggle = qs("menuToggle");
    if (!menu) return;
    menuOpen = false;
    menu.classList.remove("is-open");
    menu.setAttribute("aria-hidden", "true");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    lockScroll(false);
    if (toggle) toggle.focus();
    else if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function toggleMenu() { menuOpen ? closeMenu() : openMenu(); }

  function openDrawer(el) {
    if (!el) return;
    el.classList.remove("hidden");
    el.classList.add("drawer-open");
    if (window.matchMedia("(max-width: 1023px)").matches) {
      lockScroll(true);
      el.setAttribute("role", "dialog");
      el.setAttribute("aria-modal", "true");
      const closeBtn = el.querySelector("[data-drawer-close]");
      if (closeBtn) closeBtn.focus();
    }
  }

  function closeDrawer(el) {
    if (!el) return;
    el.classList.add("hidden");
    el.classList.remove("drawer-open");
    el.removeAttribute("aria-modal");
    if (!document.querySelector(".drawer-open") && !menuOpen && !activeDialog) lockScroll(false);
  }

  function ensureDialogRoot() {
    let root = qs("bigoDialog");
    if (root) return root;
    root = document.createElement("div");
    root.id = "bigoDialog";
    root.className = "modal hidden";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.innerHTML = `
      <div class="modal-box" role="document">
        <div class="modal-header">
          <h3 id="bigoDialogTitle"></h3>
          <button type="button" class="btn btn-icon" id="bigoDialogX" data-i18n-aria="ui.dialog_close">
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
          </button>
        </div>
        <p id="bigoDialogBody" class="dialog-body"></p>
        <p id="bigoDialogImpact" class="dialog-impact"></p>
        <div id="bigoDialogExtra"></div>
        <div class="form-actions">
          <button type="button" class="btn btn-outline" id="bigoDialogCancel"></button>
          <button type="button" class="btn btn-primary" id="bigoDialogOk"></button>
        </div>
      </div>`;
    document.body.appendChild(root);
    root.addEventListener("click", (e) => {
      if (e.target === root) {
        const cancel = qs("bigoDialogCancel");
        if (cancel) cancel.click();
      }
    });
    return root;
  }

  function closeDialog(ok) {
    const root = qs("bigoDialog");
    if (!root || !activeDialog) return;
    const resolve = activeDialog.resolve;
    activeDialog = null;
    root.classList.add("hidden");
    lockScroll(menuOpen);
    resolve(ok);
  }

  function confirm(opts) {
    const o = opts || {};
    const root = ensureDialogRoot();
    qs("bigoDialogTitle").textContent = o.title || t("common.confirm");
    qs("bigoDialogBody").textContent = o.message || "";
    const impact = qs("bigoDialogImpact");
    impact.textContent = o.impact || "";
    impact.classList.toggle("hidden", !o.impact);
    qs("bigoDialogExtra").innerHTML = "";
    const okBtn = qs("bigoDialogOk");
    const cancelBtn = qs("bigoDialogCancel");
    okBtn.textContent = o.confirmLabel || t("common.confirm");
    cancelBtn.textContent = o.cancelLabel || t("common.cancel");
    okBtn.className = "btn " + (o.danger ? "btn-danger" : "btn-primary");
    root.classList.remove("hidden");
    lockScroll(true);
    okBtn.onclick = () => closeDialog(true);
    cancelBtn.onclick = () => closeDialog(false);
    qs("bigoDialogX").onclick = () => closeDialog(false);
    okBtn.focus();
    return new Promise((resolve) => { activeDialog = { resolve }; });
  }

  function prompt(opts) {
    const o = opts || {};
    const root = ensureDialogRoot();
    qs("bigoDialogTitle").textContent = o.title || t("common.confirm");
    qs("bigoDialogBody").textContent = o.message || "";
    const impact = qs("bigoDialogImpact");
    impact.textContent = o.impact || "";
    impact.classList.toggle("hidden", !o.impact);
    const extra = qs("bigoDialogExtra");
    extra.innerHTML = `<label class="dialog-field"><span>${o.label || ""}</span>
      <input type="text" id="bigoDialogInput" value="${(o.value || "").replace(/"/g, "&quot;")}"></label>`;
    const okBtn = qs("bigoDialogOk");
    const cancelBtn = qs("bigoDialogCancel");
    okBtn.textContent = o.confirmLabel || t("common.confirm");
    cancelBtn.textContent = o.cancelLabel || t("common.cancel");
    okBtn.className = "btn btn-primary";
    root.classList.remove("hidden");
    lockScroll(true);
    const input = qs("bigoDialogInput");
    okBtn.onclick = () => {
      const v = input.value;
      const resolve = activeDialog.resolve;
      activeDialog = null;
      root.classList.add("hidden");
      lockScroll(menuOpen);
      resolve(v);
    };
    cancelBtn.onclick = qs("bigoDialogX").onclick = () => {
      const resolve = activeDialog.resolve;
      activeDialog = null;
      root.classList.add("hidden");
      lockScroll(menuOpen);
      resolve(null);
    };
    input.focus();
    input.select();
    return new Promise((resolve) => { activeDialog = { resolve }; });
  }

  function pick(opts) {
    const o = opts || {};
    const root = ensureDialogRoot();
    qs("bigoDialogTitle").textContent = o.title || t("common.confirm");
    qs("bigoDialogBody").textContent = o.message || "";
    const impact = qs("bigoDialogImpact");
    impact.textContent = o.impact || "";
    impact.classList.toggle("hidden", !o.impact);
    const options = (o.options || []).map((it, i) =>
      `<option value="${i}">${String(it.label).replace(/</g, "&lt;")}</option>`).join("");
    qs("bigoDialogExtra").innerHTML = `
      <label class="dialog-field"><select id="bigoDialogSelect">${options}</select></label>
      ${o.allowCustom ? `<label class="dialog-field"><span>${o.customLabel || ""}</span>
        <input type="text" id="bigoDialogCustom" placeholder="${(o.customPlaceholder || "").replace(/"/g, "&quot;")}"></label>` : ""}`;
    const okBtn = qs("bigoDialogOk");
    const cancelBtn = qs("bigoDialogCancel");
    okBtn.textContent = o.confirmLabel || t("common.confirm");
    cancelBtn.textContent = o.cancelLabel || t("common.cancel");
    okBtn.className = "btn btn-primary";
    root.classList.remove("hidden");
    lockScroll(true);
    const finish = (val) => {
      const resolve = activeDialog.resolve;
      activeDialog = null;
      root.classList.add("hidden");
      lockScroll(menuOpen);
      resolve(val);
    };
    okBtn.onclick = () => {
      const custom = qs("bigoDialogCustom");
      if (custom && custom.value.trim()) { finish({ custom: custom.value.trim() }); return; }
      const sel = qs("bigoDialogSelect");
      const idx = parseInt(sel.value, 10);
      finish({ index: idx, item: (o.options || [])[idx] });
    };
    cancelBtn.onclick = qs("bigoDialogX").onclick = () => finish(null);
    qs("bigoDialogSelect").focus();
    return new Promise((resolve) => { activeDialog = { resolve }; });
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("#menuToggle")) { e.preventDefault(); toggleMenu(); }
    if (e.target.closest("[data-menu-close]")) { e.preventDefault(); closeMenu(); }
    if (e.target.closest("[data-locale-btn]")) {
      const loc = e.target.closest("[data-locale-btn]").getAttribute("data-locale-btn");
      if (global.BigoI18n) global.BigoI18n.setLocale(loc);
    }
    if (e.target.closest("[data-drawer-close]")) {
      const drawer = e.target.closest(".drawer, .res-detail-side, #detailPanel, #researchDetail");
      closeDrawer(drawer);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (activeDialog) trapKey(e, qs("bigoDialog"));
    else if (menuOpen) trapKey(e, qs("siteMenu"));
  });

  global.BigoUI = { openMenu, closeMenu, toggleMenu, openDrawer, closeDrawer, confirm, prompt, pick };
})(window);
