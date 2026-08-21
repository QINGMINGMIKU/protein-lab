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
print(f"3. i18n keys complete ({len(EN)} keys, {len(used)} used in templates) OK")

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
for tab in ("conc", "dilution", "bli", "akta", "weblogo", "enzyme", "copy"):
    assert f'data-tab="{tab}"' in calc, f"missing tool {tab}"
    assert f'id="tab-{tab}"' in calc
assert 'data-i18n="workbench.group.prepare"' in calc
assert 'data-i18n="workbench.group.analyze"' in calc
assert 'data-i18n="workbench.group.sequence"' in calc
assert 'data-i18n="workbench.group.reuse"' in calc
assert 'class="advanced"' in calc or "<details" in calc

exps = client.get("/experiments").get_data(as_text=True)
for _id in ("expTable", "expList", "expTypeFilter", "exportBtn", "expModal"):
    assert f'id="{_id}"' in exps, f"archive missing #{_id}"
for t in models.EXP_TYPES:
    assert f'<option value="{t}">' in exps, f"exp_type option missing {t}"

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
assert 'id="copySearchInput"' in calc
appjs = (STATIC / "app.js").read_text(encoding="utf-8")
for banned in ("全部标签", "全部蛋白", "新建实验", "计划占位（未归档）"):
    assert banned not in appjs, f"hardcoded UI string still in app.js: {banned}"
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
# i18n.js embeds the same keys as i18n.json
for key in EN:
    assert f'"{key}"' in js, f"i18n.js missing key {key}"
print("9. Layout / i18n / dialog wiring OK")

# ── 10. Design tokens / responsive invariants ─────────
css = (STATIC / "style.css").read_text(encoding="utf-8")
for token in (
    "--lab-canvas: #F3F0EA",
    "--instrument: #FBF8F1",
    "--carbon: #141414",
    "--graphite: #4E4A44",
    "--cyan: #C8791E",
    "--cyan-deep: #A96316",
    "--hit: 44px",
    "--max: 1920px",
):
    assert token in css, f"missing token {token}"
assert "html, body { max-width: 100%; overflow-x: hidden; }" in css
assert "@media (max-width: 1023px) { .grid-guides { display: none; } }" in css
assert "@media (max-width: 767px)" in css
assert ".record-list { display: block" in css
assert "prefers-reduced-motion" in css
assert "outline: 2px solid var(--cyan)" in css
assert "border-radius" in css and "box-shadow" in css, "warm-paper cards need radius + shadow"
assert "JetBrainsMonoVariable.woff2" in css, "JetBrains Mono should be registered"
assert "IBM Plex" not in css, "IBM Plex Mono must be fully removed"
assert '"JetBrains Mono"' in css, "JetBrains Mono should be the default UI font"
assert "font-variant-numeric: tabular-nums" in css, "tabular numbers for data columns"
assert "a { color: var(--cyan)" in css, "links should use the amber accent, not browser blue"
assert "a:visited { color: var(--cyan)" in css, "visited links must not revert to browser purple"
for tok in ("--success", "--danger", "--warning", "--info", "--rule-soft", "--accent-bg"):
    assert tok in css, f"missing semantic token {tok}"
assert ".res-tag-chip.support" in css, "stance semantic classes missing"
assert "border-radius: 0" in css, "buttons must stay square (BDA decision)"
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
