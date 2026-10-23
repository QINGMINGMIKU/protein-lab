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
  setEvidence("bliMeta", "processing", t("workbench.status_processing"));
  try {
    const r = await fetch("/api/bli/analyze", { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) {
      setEvidence("bliMeta", "fail", t("workbench.status_fail"));
      toast(backendError(data, r.status), true); return;
    }
    bliSession = data.session_id;
    bliSamples = data.samples || [];
    bliSelectedSample = bliSamples[0]?.sample || "";
    bliLastPlot = null;
    bliKdResult = null;
    bliActiveCurves = new Set(bliSamples.flatMap(s => s.labels || []));  // 默认全选进入数据
    renderBliSamples();
    renderBliCurves();
    const phase = bliSamples.length ? "done" : "empty";
    setEvidence("bliMeta", phase,
      `${file.name} | ${t("workbench.sensors_n", { n: data.n_sensors })} | ${t("copy.samples_n", { n: bliSamples.length })}`);
    document.getElementById("bliAnalyzed").classList.remove("hidden");
    document.getElementById("bliKdWrap").classList.add("hidden");
    document.getElementById("bliPlotArea").innerHTML = "";
    refreshBliPlaceholder();
    toast(t("toast.parsed"));
  } catch (err) {
    setEvidence("bliMeta", "fail", t("workbench.status_fail"));
    toast(err, true);
  }
}

function renderBliSamples() {
  const tbody = document.getElementById("bliSampleList");
  tbody.innerHTML = bliSamples.map(s => `
    <tr>
      <td><strong>${esc(s.sample)}</strong></td>
      <td>${s.n_curves}</td>
      <td style="font-size:12px;color:var(--graphite)">${(s.concs || []).map(c => formatConc(c, "nM")).join(" / ")}</td>
      <td><button class="btn btn-sm btn-outline bli-pick" data-sample="${escAttr(s.sample)}">${bliSelectedSample === s.sample ? t("workbench.selected_mark") : t("workbench.fit")}</button></td>
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
      <td style="font-size:12px;color:var(--graphite)">${esc(r.sample)}</td>
      <td style="font-size:12px;color:var(--graphite)">${formatConc(r.conc, "nM")} nM</td>
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
  if (stats) stats.textContent = nOn + "/" + all.length;
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
  if (!bliSession) { toast(t("toast.upload_first"), true); return; }
  const mode = (document.getElementById("bliPlotMode") || {}).value || "overlay";
  try {
    const r = await API.post("/api/bli/plot", { ...bliParams(), separate: mode === "separate" });
    const area = document.getElementById("bliPlotArea");
    if (mode === "separate" && r.images) {
      area.innerHTML = Object.entries(r.images).map(([sid, img]) =>
        `<div class="calc-card" style="padding:12px;margin-bottom:10px">
          <div style="font-weight:600;margin-bottom:6px">${esc(sid)}</div>
          <img src="${img}" style="max-width:100%" alt="${esc(sid)}">
        </div>`).join("");
      bliLastPlot = null;
    } else {
      area.innerHTML =
        `<div class="calc-card" style="padding:12px">
          <img src="${r.image}" style="max-width:100%" alt="${esc(t("workbench.sensorgram"))}">
        </div>`;
      bliLastPlot = r.image;
    }
  } catch (err) { toast(err, true); }
}

async function bliFitSelected() {
  if (!bliSession || !bliSelectedSample) { toast(t("toast.pick_sample"), true); return; }
  try {
    const r = await API.post("/api/bli/fit", { ...bliParams(), sample: bliSelectedSample });
    bliKdResult = r;
    document.getElementById("bliKdWrap").classList.remove("hidden");
    document.getElementById("bliKdTables").innerHTML = renderBliKd(bliSelectedSample, r);
  } catch (err) { toast(err, true); }
}

// 单样本 KD 结果渲染（点样本行重拟合 → 更新这张卡片；拟合失败显示错误卡）
function renderBliKd(sample, res) {
  if (!res || res.error) {
    return `<div class="calc-card" style="padding:12px;margin-bottom:10px">
      <div style="font-weight:600;margin-bottom:4px">${esc(sample)}</div>
      <div style="color:var(--danger);font-size:13px">${t("toast.fit_failed")}: ${esc(res.error || t("error.generic"))}</div>
    </div>`;
  }
  const phase = res.phase || {};
  const methods = ["standard", "split", "joint", "steady", "mixed"];
  const rows = methods.map(m => {
    const v = res[m];
    if (!v) return `<tr><td>${m}</td><td colspan="4" style="color:var(--graphite)">${t("workbench.fit_failed_row")}</td></tr>`;
    const kd = v.kd != null && isFinite(v.kd) ? `${formatConc(v.kd, "nM")} nM` : "—";
    const kon = v.kon != null && isFinite(v.kon) ? (+v.kon).toExponential(2) : "—";
    const koff = v.koff != null && isFinite(v.koff) ? (+v.koff).toExponential(2) : "—";
    const extra = v.kd_steady_mixed != null ? t("workbench.kd_steady", { v: formatConc(v.kd_steady_mixed, "nM") }) :
                 (v.kd_kinetic_mixed != null ? t("workbench.kd_kinetic", { v: formatConc(v.kd_kinetic_mixed, "nM") }) : "");
    return `<tr><td><strong>${m}</strong></td><td>${kd}</td><td>${kon}</td><td>${koff}</td><td>${extra}</td></tr>`;
  }).join("");
  return `<div class="calc-card" style="padding:12px;margin-bottom:10px">
    <div style="font-size:13px;color:var(--graphite);margin-bottom:6px">
      ${t("workbench.sample_phase", { sample: esc(sample), ta: phase.t_assoc?.toFixed(1) ?? "—", td: phase.t_dissoc?.toFixed(1) ?? "—" })}
    </div>
    <div class="table-scroll"><table class="calc-table">
      <thead><tr><th>${t("workbench.method")}</th><th>KD</th><th>${t("workbench.kon")}</th><th>${t("workbench.koff")}</th><th>${t("workbench.notes_col")}</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </div>`;
}

async function bliSaveExp() {
  if (!bliSession) { toast(t("toast.upload_first"), true); return; }
  const mount = await promptExpMount("BLI");
  if (mount === null) { toast(t("toast.save_cancelled")); return; }
  let title = "";
  if (!mount.exp_id) {
    const autoName = await getAutoName("BLI", null, "bli_fit");
    title = await askText(t("ui.exp_name_prompt"), autoName || "BLI");
    if (!title) return;
  }
  try {
    await API.post("/api/bli/save", {
      ...bliParams(),
      title,
      date: todayLocal(),
      source: document.getElementById("bliFile").files[0]?.name || "",
      ...mount,
    });
    toast(mount.exp_id ? t("toast.remounted_curves", { id: mount.exp_id })
      : t("toast.saved_record"));
  } catch (err) { toast(err, true); }
}

async function bliExport() {
  if (!bliSession) { toast(t("toast.upload_first"), true); return; }
  try {
    const r = await fetch("/api/bli/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bliParams()),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw backendError(j, r.status, t("toast.export_failed", { status: r.status }));
    }
    const blob = await r.blob();
    const fname = await askText(t("ui.export_name"), "BLI_KD.xlsx");
    if (!fname) return;
    const fn = /\.xlsx$/i.test(fname) ? fname : fname + ".xlsx";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fn;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    toast(t("toast.exported_bli"));
  } catch (err) { toast(err, true); }
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
  setEvidence("aktaMeta", "processing", t("workbench.status_processing"));
  try {
    const r = await fetch("/api/akta/analyze", { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) {
      setEvidence("aktaMeta", "fail", t("workbench.status_fail"));
      toast(backendError(data, r.status), true); return;
    }
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
    const phase = okRuns.length ? "done" : "fail";
    setEvidence("aktaMeta", phase,
      `${t("workbench.files_ok", { n: files.length, ok: okRuns.length })}${errRuns.length ? t("workbench.files_fail", { n: errRuns.length }) : ""} | ${t("workbench.channels_n", { n: totalCh })}`);
    renderAktaRuns();
    document.getElementById("aktaEventsInfo").textContent =
      errRuns.map(r => `${r.name}: ${r.error}`).join("；");
    document.getElementById("aktaAnalyzed").classList.remove("hidden");
    document.getElementById("aktaPeakTableWrap").classList.add("hidden");
    document.getElementById("aktaPlotArea").innerHTML = "";
    refreshAktaPlaceholder();
    if (okRuns.length) { toast(t("toast.parsed_n_files", { n: okRuns.length })); }
    else { toast(t("toast.parse_all_failed"), true); }
  } catch (err) {
    setEvidence("aktaMeta", "fail", t("workbench.status_fail"));
    toast(err, true);
  }
}

function renderAktaRuns() {
  const box = document.getElementById("aktaRunList");
  if (!box) return;
  box.innerHTML = aktaRuns.map((run, ri) => {
    if (run.error) {
      return `<div class="calc-card" style="padding:8px 10px;margin-bottom:8px;font-size:13px;border-color:var(--danger);background:var(--danger-bg)">
        <strong style="color:var(--danger)">${esc(run.name)}</strong>
        <span style="color:var(--graphite);margin-left:8px">${esc(run.error)}</span>
      </div>`;
    }
    const chOpts = run.channels.map(ch =>
      `<option value="${escAttr(ch.name)}" ${ch.name === run.channel ? "selected" : ""}>${esc(ch.name)} (${esc(ch.data_type)}${ch.unit ? " " + esc(ch.unit) : ""}, ${ch.n_points}pts)</option>`).join("");
    const evInfo = Object.entries(run.events || {}).map(([k, v]) => `${k}:${v}`).join(" ");
    const checked = run.checked === false ? "" : "checked";
    return `<div class="calc-card" style="padding:8px 10px;margin-bottom:8px;font-size:13px;${aktaCurrentRun === ri ? "outline:2px solid var(--cyan);outline-offset:2px;" : ""}" data-run="${ri}">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <div style="display:inline-flex;align-items:center;gap:6px">
          <input type="checkbox" class="akta-run-check" data-run="${ri}" ${checked} onclick="event.stopPropagation()">
          <strong style="cursor:pointer" class="akta-run-select">${esc(run.name)}</strong>
        </div>
        <span style="color:var(--graphite);font-size:12px">${evInfo || t("workbench.no_events")}</span>
      </div>
      <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;align-items:center">
        <select class="akta-run-channel" data-run="${ri}" style="flex:1;min-width:160px;padding:5px 8px;border:1px solid var(--rule);font-size:12px">${chOpts}</select>
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
  if (!run || run.error || !run.channel) { toast(t("toast.pick_file_channel"), true); return; }
  try {
    const r = await API.post("/api/akta/plot", aktaParams(run));
    document.getElementById("aktaPlotArea").innerHTML =
      `<div class="calc-card" style="padding:12px">
        <div style="font-weight:600;margin-bottom:6px;font-size:14px">${esc(run.name)} — ${esc(run.channel)}</div>
        <img src="${r.image}" style="max-width:100%" alt="${esc(run.name)}">
      </div>`;
    renderAktaPeaks(r.peaks || [], run);
  } catch (err) { toast(err, true); }
}

// 出图入口：分图模式 = 每文件一张；总图模式 = 所有曲线叠一张
// 只出勾选（akta-run-check）的文件
async function aktaBatchPlot() {
  const okRuns = aktaRuns.filter(r => !r.error && r.channel && r.checked !== false);
  if (!okRuns.length) { toast(t("toast.no_checked_files"), true); return; }
  const mode = document.getElementById("aktaPlotMode").value;
  const area = document.getElementById("aktaPlotArea");
  const normOn = document.getElementById("aktaNormalize").checked;

  if (mode === "overlay") {
    if (okRuns.length < 2) { toast(t("toast.overlay_need_two"), true); return; }
    area.innerHTML = `<p style="color:var(--graphite);font-size:13px">${t("workbench.plotting_overlay", { n: okRuns.length })}</p>`;
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
      area.innerHTML = `<div class="calc-card" style="padding:12px">
        <div style="font-weight:600;margin-bottom:6px;font-size:14px">${normOn ? t("workbench.overlay_title_norm", { n: okRuns.length }) : t("workbench.overlay_title", { n: okRuns.length })}</div>
        <img src="${r.image}" style="max-width:100%" alt="${esc(t("workbench.overlay_title", { n: okRuns.length }))}">
      </div>`;
    } catch (err) { toast(err, true); }
    return;
  }

  // 分图模式
  area.innerHTML = `<p style="color:var(--graphite);font-size:13px">${t("workbench.plotting_n", { n: okRuns.length })}</p>`;
  let html = "";
  for (const run of okRuns) {
    try {
      const r = await API.post("/api/akta/plot", aktaParams(run));
      html += `<div class="calc-card" style="padding:12px;margin-bottom:12px">
        <div style="font-weight:600;margin-bottom:6px;font-size:14px">${esc(run.name)} — ${esc(run.channel)}</div>
        <img src="${r.image}" style="max-width:100%" alt="${esc(run.name)}">
      </div>`;
    } catch (err) {
      html += `<div class="calc-card" style="padding:8px;margin-bottom:8px;color:var(--danger);font-size:13px">${esc(run.name)}: ${esc(err.message)}</div>`;
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
    tbody.innerHTML = `<tr><td colspan="7" style="color:var(--graphite);text-align:center">${t("toast.no_peaks")}</td></tr>`;
    return;
  }
  wrap.classList.remove("hidden");
  const cur = run.target_peak || 0;
  tbody.innerHTML = peaks.map((p, i) => `
    <tr style="${i === cur ? "background:var(--accent-bg)" : ""}">
      <td>${i + 1}</td>
      <td>${p.apex_vol}</td>
      <td>${p.height}</td>
      <td>${p.area}</td>
      <td>${p.start_vol}</td>
      <td>${p.end_vol}</td>
      <td>${p.half_width}</td>
      <td><button class="btn btn-sm btn-outline akta-peak-target" data-run-idx="${aktaCurrentRun}" data-peak="${i}">${i === cur ? t("workbench.is_target") : t("workbench.target")}</button></td>
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
  if (!run || run.error || !run.channel) { toast(t("toast.pick_file_channel"), true); return; }
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
      throw backendError(j, r.status, t("toast.export_failed", { status: r.status }));
    }
    const blob = await r.blob();
    // 文件名默认用 zip 包名（去 .zip），允许用户自定义
    const zipBase = (run.name || "").replace(/\.zip$/i, "") || run.channel;
    let fname = await askText(t("ui.export_name"), `${zipBase}_peaks.xlsx`);
    if (!fname) return;
    if (!/\.xlsx$/i.test(fname)) fname += ".xlsx";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    toast(t("toast.exported_peaks", { n: okRuns.length }));
  } catch (err) { toast(err, true); }
}


async function aktaSaveExp() {
  const run = aktaRuns[aktaCurrentRun];
  if (!run || run.error || !run.channel) { toast(t("toast.pick_file_channel"), true); return; }
  const mount = await promptExpMount("AKTA");
  if (mount === null) { toast(t("toast.save_cancelled")); return; }
  let title = "";
  if (!mount.exp_id) {
    const autoName = await getAutoName("AKTA", null, "akta");
    // 默认名优先用 zip 包名（去 .zip 扩展名），其次系统自动命名
    const zipBase = (run.name || "").replace(/\.zip$/i, "");
    title = await askText(t("ui.exp_name_prompt"), zipBase || autoName || "AKTA");
    if (!title) return;
  }
  try {
    await API.post("/api/akta/save", {
      ...aktaParams(run),
      title,
      date: todayLocal(),
      source: run.name || "",
      ...mount,
    });
    toast(mount.exp_id ? t("toast.remounted_curves", { id: mount.exp_id })
      : t("toast.saved_record"));
  } catch (err) { toast(err, true); }
}

function refreshAktaPlaceholder() { refreshAutoNamePlaceholders(); }

