"""test_ui.py — Bigo.bio BDA Workbench UI shell, i18n, static assets (assert script)

Run with venv python against a temp database (never the user protein_lab.db).
"""
import os, sys, json, re, importlib, tempfile, pathlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"

import models
importlib.reload(models)
TMP = tempfile.mkdtemp(prefix="protein_lab_ui_")
models.DB_PATH = os.path.join(TMP, "test.db")
models.init_db()
import services

from app import app, inject_static_version
client = app.test_client()

PAGES = ("/", "/research", "/proteins", "/calculator", "/experiments", "/compare")

I18N = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
EN, ZH = I18N["en"], I18N["zh-CN"]

# ── 1. Pages 200 ──────────────────────────────────────
for url in PAGES:
    r = client.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}"
print("1. All pages 200 OK")

# ── 2. App shell markers ──────────────────────────────
home = client.get("/").get_data(as_text=True)
assert 'class="brand"' in home and "Bigo.bio" in home, "brand Bigo.bio missing"
assert 'data-i18n="nav.research"' in home, "Research Trace nav missing"
assert 'data-i18n="nav.proteins"' in home, "Protein Library nav missing"
assert 'data-i18n="nav.workbench"' in home, "BDA Workbench nav missing"
assert 'data-i18n="nav.archive"' in home, "Evidence Archive nav missing"
assert 'data-i18n="nav.compare"' in home, "Compare nav missing"
assert 'id="langSwitch"' in home or 'data-locale-btn' in home, "language switch missing"
assert 'id="siteMenu"' in home and 'id="menuToggle"' in home, "mobile menu missing"
assert 'class="grid-guides"' in home, "desktop grid guides missing"
assert 'static/i18n.js' in home, "i18n.js not injected"
assert '<html lang="en"' in home, "default html lang should be en"
print("2. App shell markers OK")

# ── 3. i18n key completeness ──────────────────────────
assert set(EN) == set(ZH), f"en/zh-CN key mismatch: {sorted(set(EN)^set(ZH))[:10]}"
assert EN["nav.research"] == "Research Trace"
assert ZH["nav.research"] == "研究脉络"
js = (STATIC / "i18n.js").read_text(encoding="utf-8")
appjs_src = (STATIC / "app.js").read_text(encoding="utf-8")
assert "window.BigoI18n" in js or "global.BigoI18n" in js
assert "function" in js and "setLocale" in js and 'localStorage' in js
for key in ("t(", "apply(", "setLocale(", "locale"):
    assert key.replace("(", "") in js, f"BigoI18n API missing {key}"
# templates: every data-i18n* key exists
used = set()
for path in TEMPLATES.glob("*.html"):
    text = path.read_text(encoding="utf-8")
    used.update(k for k in re.findall(r'data-i18n(?:-placeholder|-title|-aria|-option)?="([^"]+)"', text) if "{{" not in k)
missing = sorted(k for k in used if k not in EN)
assert not missing, f"templates reference unknown i18n keys: {missing[:12]}"
# i18n.js 是**手工同步**的第二份字典（CLAUDE.md 明示）。json 里加了键却忘了同步 js，
# UI 会直接显示裸 key 而不报错——这里逐键逐值比对文本，把这个漂移钉死。
js_drift = []
for _loc, _d in (("en", EN), ("zh-CN", ZH)):
    for _k, _v in _d.items():
        if f'{json.dumps(_k, ensure_ascii=False)}: {json.dumps(_v, ensure_ascii=False)}' not in js:
            js_drift.append(f"{_loc}:{_k}")
assert not js_drift, \
    f"i18n.js 与 i18n.json 不同步（{len(js_drift)} 项）: {js_drift[:10]}"
# app.js 里 t("...") 的**整键字面量**必须都在字典里；拼接键（t("exp_type." + x)）不以 , ) 收尾，天然排除
_appjs_keys = set(re.findall(r'\bt\(\s*"([a-z][a-zA-Z0-9_.]*)"\s*[,)]', appjs_src))
_unknown = sorted(k for k in _appjs_keys if k not in EN)
assert not _unknown, f"app.js 引用了字典里没有的 i18n key: {_unknown[:12]}"
print(f"3. i18n keys complete ({len(EN)} keys, {len(used)} used in templates, "
      f"{len(_appjs_keys)} literal in app.js, js/json in sync) OK")

# ── 4. Experiment type display mapping ────────────────
for stored in models.EXP_TYPES:
    assert f"exp_type.{stored}" in EN, f"missing exp_type mapping for {stored!r}"
    assert f"exp_type.{stored}" in ZH
print("4. Experiment type label mapping OK")

# ── 5. Static assets exist ────────────────────────────
for rel in (
    "i18n.js", "i18n.json", "ui-shell.js", "app.js", "style.css",
    "fonts/InterVariable.woff2",
    "fonts/JetBrainsMonoVariable.woff2",
    "fonts/NotoSansSC-Regular.otf",
    "fonts/LICENSE-Inter.txt",
    "fonts/LICENSE-JetBrainsMono.txt",
    "fonts/LICENSE-NotoSansSC.txt",
):
    p = STATIC / rel
    assert p.is_file() and p.stat().st_size > 0, f"missing static asset {rel}"
print("5. Static assets exist OK")

# ── 6. Critical DOM IDs ───────────────────────────────
research = client.get("/research").get_data(as_text=True)
assert 'id="researchFlow"' in research
assert 'id="researchFlowBack"' in research
assert 'class="res-layout"' in research and "res-detail-side" in research
assert 'id="researchQuery"' in research

proteins = client.get("/proteins").get_data(as_text=True)
for _id in ("proteinTable", "proteinList", "searchBox", "detailPanel", "addModal", "importModal", "batchTagModal", "bulkBar"):
    assert f'id="{_id}"' in proteins, f"proteins missing #{_id}"

calc = client.get("/calculator").get_data(as_text=True)
for tab in ("conc", "dilution", "bli", "akta", "weblogo", "enzyme"):
    assert f'data-tab="{tab}"' in calc, f"missing tool {tab}"
    assert f'id="tab-{tab}"' in calc
# 「从实验复制」tab 已删（浏览+载入收口到实验档案页），Reuse 组只剩空壳也一并删掉
assert 'data-tab="copy"' not in calc, "copy tab 应已删除"
assert 'id="tab-copy"' not in calc, "tab-copy 面板应已删除"
assert 'data-i18n="workbench.group.reuse"' not in calc, "Reuse 空壳组应已删除"
assert 'data-i18n="workbench.group.prepare"' in calc
assert 'data-i18n="workbench.group.analyze"' in calc
assert 'data-i18n="workbench.group.sequence"' in calc
assert 'class="advanced"' in calc or "<details" in calc

exps = client.get("/experiments").get_data(as_text=True)
for _id in ("expTable", "expList", "expTypeFilter", "exportBtn", "expModal", "expSearchInput"):
    assert f'id="{_id}"' in exps, f"archive missing #{_id}"
for t in models.EXP_TYPES:
    assert f'<option value="{t}">' in exps, f"exp_type option missing {t}"
# 档案页第 9 列（详情入口）——表头数与错误行 colspan 必须跟着走，否则列错位
# 用 <th[ >] 而非 <th，否则会把 <thead> 也算进来
_nth = len(re.findall(r"<th[ >]", exps))
assert _nth == 9, f"expTable 应有 9 列表头，实际 {_nth}"

eid = services.create_experiment(title="UI detail", exp_type="其他", params={"k": "v"}, results={})["id"]
detail = client.get(f"/experiments/{eid}").get_data(as_text=True)
assert "Load into workbench" not in detail, "non-loadable experiment must not show workbench CTA"
assert "载入计算工具" not in detail
assert f'href="/calculator?load_exp={eid}"' not in detail
assert 'data-calc-types' in exps
assert 'data-exp-types' in detail

bli = services.create_experiment(
    title="UI BLI loadable", exp_type="BLI",
    params={"calc_type": "bli_fit"},
    results={"samples": {}},
    raw_snapshots=[("bli_curves", {"analysis_version": "0.0.8", "curves": []})],
)
bli_html = client.get(f"/experiments/{bli['id']}").get_data(as_text=True)
assert "Load into workbench" in bli_html
assert f'href="/calculator?load_exp={bli["id"]}"' in bli_html
compare = client.get("/compare").get_data(as_text=True)
assert 'id="compareTable"' in compare
assert 'data-calc-types' in compare
print("6. Critical DOM IDs OK")

# ── 7. Fonts.py + PyInstaller paths ───────────────────
import fonts as fonts_mod
cjk = fonts_mod.find_cjk_font()
assert cjk and "NotoSansSC-Regular.otf" in cjk.replace("\\", "/"), f"CJK font path {cjk}"
assert "static/fonts" in cjk.replace("\\", "/"), f"web-accessible font path expected, got {cjk}"
spec = (ROOT / "protein_lab.spec").read_text(encoding="utf-8")
assert '("static", "static")' in spec or '("static"' in spec
print("7. PyInstaller / fonts path OK")

# ── 8. inject_static_version includes i18n.js ─────────
# context processor is registered; inspect source
src = (ROOT / "app.py").read_text(encoding="utf-8")
assert "i18n.js" in src, "inject_static_version should include i18n.js"
print("8. static version includes i18n.js OK")

# ── 9. Layout / i18n wiring / dialog cancel ───────────
assert 'id="weblogoSearch"' in calc, "Weblogo search input missing"
assert "stack-on-narrow" in calc
assert 'id="copySearchInput"' not in calc, "copy tab 的搜索框应随 tab 一起删除"
assert 'id="expSearchInput"' in exps, "档案页应接管搜索（原 copy tab 的唯一搜索入口）"
appjs = (STATIC / "app.js").read_text(encoding="utf-8")
for banned in ("全部标签", "全部蛋白", "新建实验", "计划占位（未归档）"):
    assert banned not in appjs, f"hardcoded UI string still in app.js: {banned}"
# 载入链路：档案页标题深链到计算器，由 applyCopyAndSwitch（载入引擎）消费
assert "load_exp=" in appjs, "档案页标题应深链 /calculator?load_exp=<id>"
assert "function applyCopyAndSwitch(" in appjs, "载入引擎不该被删"
assert "function isAktaExp(" in appjs and "function isBliExp(" in appjs, \
    "is*Exp 定义在被删区间内，必须挖出来（applyCopyAndSwitch 仍在调）"
assert "function latestRawId(" in appjs and "function safeJson(" in appjs
# 档案页列表重构后的三个函数必须都在（搜索过滤是纯客户端）
for fn in ("function expMatchesQuery(", "function filterExpList(", "function renderExpList("):
    assert fn in appjs, f"档案页缺少 {fn}"
assert "let expAllExps = []" in appjs and "EXP_LIST_LIMIT" in appjs
assert 'colspan="9"' in appjs, "错误行/空态行的 colspan 应同步为 9（表格加了第 9 列）"
assert "archive.search_capped" in appjs, "搜索上限（仅最近 100 条）应有可见提示"
assert "recordCheckedIds" in appjs
assert "syncRecordCheck" in appjs
assert "archive.confirm_delete_named" in appjs
assert "setEvidence" in appjs
assert "iconClose" in appjs
assert "backendError" in appjs
ui = (STATIC / "ui-shell.js").read_text(encoding="utf-8")
assert "getClientRects" in ui
assert "bigoDialogCancel" in ui
assert "cancel.click()" in ui
assert 'select[data-exp-types]' in js
assert 'select[data-calc-types]' in js
spec = (ROOT / "protein_lab.spec").read_text(encoding="utf-8")
assert '("static", "static")' in spec
assert '("fonts", "fonts")' not in spec
detail_src = (TEMPLATES / "experiment_detail.html").read_text(encoding="utf-8")
assert "detail.wells_unit" in detail_src
assert " 孔" not in detail_src
assert "setEvidence" in appjs and "workbench.status_processing" in appjs
# 酶活存档契约 v2 前端面（原始数据只落 raw / 手动参数落 params / 复制从快照回放）
assert "function enzymeParams(" in appjs, "enzymeParams 缺失（手动参数单点构造）"
assert "function enzymeBackfillParams(" in appjs, "enzymeBackfillParams 缺失（复制回填开关）"
assert '"enzyme-2.0"' in appjs, "ENZYME_ANALYSIS_VERSION 未升到 2.0"
assert "/api/enzyme/restore" in appjs, "复制分支应走 /api/enzyme/restore"
assert 'latestRawId(copyCache, "enzyme_traces")' in appjs, "酶活复制应按类型取最新快照"
enzyme_params_src = appjs.split("function enzymeParams(")[1].split("\nfunction ")[0]
for banned in ("times:", "od:"):
    assert banned not in enzyme_params_src, \
        f"enzymeParams 不得写 {banned[:-1]}（逐点数据只在 experiment_raw）"
# 默认 true 的开关用 `!== false`——缺字段时不把 UI 从默认改写
assert "v !== false" in appjs.split("function enzymeBackfillParams(")[1].split("\nfunction ")[0], \
    "enzymeBackfillParams 应对默认 true 字段用 !== false"
# 复制兜底必须**显式**：params.wells 去逐点后（契约规则 A），无 raw 时静默产出空曲线会让人
# 以为「这实验本来就没数据」。两条路径都要有提示，且 raw 出错时不重复叠 toast。
_copy_src = appjs.split('latestRawId(copyCache, "enzyme_traces")')[1].split("enzymeData = {")[0]
assert "toast(t(\"toast.enzyme_no_raw\"), true)" in _copy_src, \
    "无原始快照时必须显式报错（不得静默给空曲线）"
assert 'toast(t("toast.enzyme_from_params"))' in _copy_src, \
    "回退 params 逐点时须提示曲线可能已被时间窗截断"
assert "rawFailed" in _copy_src, "raw 取数失败时应标记，避免错误 toast 之后再叠一条"
# 自由格式 kv 渲染必须被 table-scroll 保护，嵌套表不能撑破「实验参数/结果」卡片
kv_macro = detail_src.split("{% macro kv_table")[1].split("{% endmacro")[0]
assert 'class="table-scroll"' in kv_macro, "kv_table must be wrapped in a scroll container"
# i18n.js embeds the same keys as i18n.json
for key in EN:
    assert f'"{key}"' in js, f"i18n.js missing key {key}"
print("9. Layout / i18n / dialog wiring OK")

# ── 10. Design tokens / responsive invariants ─────────
css = (STATIC / "style.css").read_text(encoding="utf-8")
for token in (
    "--lab-canvas: #FFFFFF",
    "--paper: #F3F0EA",
    "--instrument: #FFFFFF",
    "--carbon: #141414",
    "--graphite: #4E4A44",
    "--cyan: #C8791E",
    "--cyan-deep: #A96316",
    "--on-accent: #FBF8F1",
    "--hit: 44px",
    "--ctrl: 36px",
    "--max: 1920px",
):
    assert token in css, f"missing token {token}"
assert "html, body { max-width: 100%; overflow-x: hidden; }" in css
assert ".grid-guides { display: none; }" in css, "column guides must not paint over cards"
assert "@media (max-width: 767px)" in css
assert ".record-list { display: block" in css
assert "prefers-reduced-motion" in css
assert "outline: 2px solid var(--cyan)" in css
assert "border-radius" in css and "box-shadow" in css, "warm-paper cards need radius + shadow"
assert "JetBrainsMonoVariable.woff2" in css, "JetBrains Mono should be registered"
assert "IBM Plex" not in css, "IBM Plex Mono must be fully removed"
assert '--font-sans: "Inter"' in css, "Inter should be the UI sans stack (BDA body)"
assert "font-family: var(--font-sans)" in css, "body should use Inter, not mono"
assert '"JetBrains Mono"' in css, "JetBrains Mono remains for data/labels"
assert "font-variant-numeric: tabular-nums" in css, "tabular numbers for data columns"
assert ".page-kicker" in css, "BDA-style orange uppercase page eyebrow"
assert "a { color: var(--cyan)" in css, "links should use the amber accent, not browser blue"
assert "a:visited { color: var(--cyan)" in css, "visited links must not revert to browser purple"
for tok in ("--success", "--danger", "--warning", "--info", "--rule-soft", "--accent-bg"):
    assert tok in css, f"missing semantic token {tok}"
assert ".res-tag-chip.support" in css, "stance semantic classes missing"
assert "border-radius: 0" in css, "buttons must stay square (BDA decision)"
assert "@keyframes modalIn" in css, "modal entrance animation missing"
assert "@keyframes dropIn" in css, "dropdown entrance animation missing"
assert "@keyframes toastIn" in css, "toast animation missing"
assert "@media (prefers-reduced-motion: no-preference)" in css, "animations must be motion-safe gated"
assert "::-webkit-scrollbar" in css, "custom scrollbar missing"
assert "::selection" in css, "selection highlight missing"
assert ".kv-nested th, .kv-nested td" in css and "word-break: break-all" in css, "kv-nested cells must wrap long content"
assert "id=\"bliMeta\"" in calc and "id=\"aktaMeta\"" in calc and "id=\"enzymeMeta\"" in calc
assert 'id="plateGrid"' in calc
assert re.search(r'class="table-scroll"\s*>\s*<div id="plateGrid"', calc), "enzyme plate must scroll locally"
print("10. Design tokens / responsive CSS OK")

# ── 11. Hardcoded colors fully removed (Warm Paper tokenization) ──
banned = ("#888", "#666", "#555", "#999", "#333", "#e74c3c", "#c0392b", "#c00",
          "#f0f5ff", "#f8f9fb", "#f0c0c0", "#fff7f7", "#e8f5e9", "#ffebee",
          "#fff3e0", "#f5f5f5", "#2e7d32", "#c62828", "#e65100", "#757575")
for label, text in (("app.js", appjs), ("style.css", css)):
    for c in banned:
        assert c not in text, f"{label} still contains hardcoded {c}"
for path in TEMPLATES.glob("*.html"):
    text = path.read_text(encoding="utf-8")
    for c in banned:
        assert c not in text, f"{path.name} still contains hardcoded {c}"
assert "RES_STANCE_CHIP" not in appjs, "JS stance inline colors must be removed"
assert "IBM Plex" not in appjs and "IBMPlexMono" not in appjs
print("11. No hardcoded colors / IBM Plex leftovers OK")

print("\nAll UI tests passed.")
