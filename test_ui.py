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

PAGES = ("/", "/research", "/proteins", "/calculator", "/experiments")

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
    "fonts/IBMPlexMono-Regular.woff2",
    "fonts/IBMPlexMono-Medium.woff2",
    "fonts/NotoSansSC-Regular.otf",
    "fonts/LICENSE-Inter.txt",
    "fonts/LICENSE-IBMPlexMono.txt",
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
assert 'data-exp-types' in exps and 'data-exp-types' in detail

bli = services.create_experiment(
    title="UI BLI loadable", exp_type="BLI",
    params={"calc_type": "bli_fit"},
    results={"samples": {}},
    raw_snapshots=[("bli_curves", {"analysis_version": "0.0.8", "curves": []})],
)
bli_html = client.get(f"/experiments/{bli['id']}").get_data(as_text=True)
assert "Load into workbench" in bli_html
assert f'href="/calculator?load_exp={bli["id"]}"' in bli_html
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
ui = (STATIC / "ui-shell.js").read_text(encoding="utf-8")
assert "getClientRects" in ui
assert "bigoDialogCancel" in ui
assert "cancel.click()" in ui
assert 'select[data-exp-types]' in js
# i18n.js embeds the same keys as i18n.json
for key in EN:
    assert f'"{key}"' in js, f"i18n.js missing key {key}"
print("9. Layout / i18n / dialog wiring OK")

print("\nAll UI tests passed.")
