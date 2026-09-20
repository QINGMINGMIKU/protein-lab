"""test_identity.py — calc_type 身份 + 横切对比（临时库，不碰 protein_lab.db）

Run: MPLBACKEND=Agg .venv/bin/python test_identity.py
"""
import os, sys, json, importlib, tempfile, io, contextlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import models
importlib.reload(models)
TMP = tempfile.mkdtemp(prefix="protein_lab_id_")
models.DB_PATH = os.path.join(TMP, "test.db")
models.init_db()
import identity
import compare
import services

# ── 1. infer: explicit calc_type wins ──
assert identity.infer_calc_type({"params": {"calc_type": "dilution"}, "exp_type": "BLI"}) == "dilution"
assert identity.infer_calc_type({"params": {"calc_type": "bli_fit"}, "exp_type": "BLI"}) == "bli_fit"
print("1. explicit calc_type OK")

# ── 2. infer: BLI family split (dilution vs fit vs bare) ──
assert identity.infer_calc_type({"exp_type": "BLI", "params": {}, "results": {}}) == "bli_fit"
assert identity.infer_calc_type({
    "exp_type": "BLI", "params": {},
    "results": {"samples": {"WT": {"standard": {"kd": 1}}}},
}) == "bli_fit"
print("2. BLI heuristics OK")

# ── 3. infer: stored families ──
assert identity.infer_calc_type({"exp_type": "浓度测定", "params": {}}) == "concentration"
assert identity.infer_calc_type({"exp_type": "酶活测定", "params": {}}) == "enzyme"
assert identity.infer_calc_type({"exp_type": "AKTA", "params": {}}) == "akta"
assert identity.infer_calc_type({"exp_type": "Weblogo", "params": {}}) == "weblogo"
assert identity.infer_calc_type({"exp_type": "SDS-PAGE", "params": {}}) == "sds_page"
assert identity.infer_calc_type({"exp_type": "其他", "params": {}}) == "other"
print("3. family defaults OK")

# ── 4. slug + stored family mapping ──
assert identity.slug_for("concentration") == "concentration"
assert identity.exp_type_for("dilution") == "BLI"
assert identity.exp_type_for("bli_fit") == "BLI"
assert identity.exp_type_for("weblogo") == "Weblogo"
assert "Weblogo" in models.EXP_TYPES
print("4. slug / EXP_TYPES OK")

# ── 5. stamp on create ──
e_conc = services.create_experiment(
    title="id-conc", exp_type="浓度测定",
    params={"a280": 0.5}, results={"mean_uM": 12.3},
)
assert e_conc["params"]["calc_type"] == "concentration"
e_bli = services.create_experiment(title="id-bli", exp_type="BLI", params={}, results={})
assert e_bli["params"]["calc_type"] == "bli_fit"
e_logo = services.create_experiment(title="id-logo", exp_type="Weblogo", params={}, results={})
assert e_logo["params"]["calc_type"] == "weblogo"
print("5. stamp on create OK")

# ── 6. auto-name uses slug, dilution ≠ bli_fit sequences ──
n1 = services.auto_exp_name("BLI", date="2099-01-01", calc_type="dilution")
n2 = services.auto_exp_name("BLI", date="2099-01-01", calc_type="bli_fit")
assert n1 == "2099-01-01_dilution_01", n1
assert n2 == "2099-01-01_bli_fit_01", n2
services.create_experiment(title=n1, exp_type="BLI", date="2099-01-01",
                           params={"calc_type": "dilution"})
n1b = services.auto_exp_name("BLI", date="2099-01-01", calc_type="dilution")
assert n1b == "2099-01-01_dilution_02", n1b
n2b = services.auto_exp_name("BLI", date="2099-01-01", calc_type="bli_fit")
assert n2b == "2099-01-01_bli_fit_01", n2b
print("6. auto-name slug OK")

# ── 7. list filter by calc_type separates BLI twins ──
dil = services.create_experiment(
    title="twin-dil", exp_type="BLI", date="2099-02-01",
    params={"calc_type": "dilution"}, results={"steps": []},
)
fit = services.create_experiment(
    title="twin-fit", exp_type="BLI", date="2099-02-01",
    params={"calc_type": "bli_fit"},
    results={"samples": {"WT": {"standard": {"kd": 10.0, "r2": 0.99}}}},
)
dils = models.exp_list(calc_type="dilution", limit=200)
fits = models.exp_list(calc_type="bli_fit", limit=200)
assert any(x["id"] == dil["id"] for x in dils)
assert not any(x["id"] == fit["id"] for x in dils)
assert any(x["id"] == fit["id"] for x in fits)
assert not any(x["id"] == dil["id"] for x in fits)
assert all(x.get("calc_type") == "dilution" for x in dils)
print("7. calc_type list filter OK")

# ── 8. key_results ──
kr = compare.key_results(models.exp_get(fit["id"]))
assert kr["calc_type"] == "bli_fit"
assert "WT" in kr["metrics"]
assert abs(kr["metrics"]["WT"]["kd_nM"] - 10.0) < 1e-9
e_enz = services.create_experiment(
    title="id-enz", exp_type="酶活测定",
    params={"calc_type": "enzyme", "wells": {
        "A1": {"name": "WT", "fit": {"slope": 0.002, "slope_corrected": 0.0015, "r2": 0.99}},
    }},
    results={},
)
kr_e = compare.key_results(models.exp_get(e_enz["id"]))
assert kr_e["metrics"]["WT"]["slope"] == 0.0015
print("8. key_results OK")

# ── 9. compare same type + highlight ──
fit2 = services.create_experiment(
    title="twin-fit-2", exp_type="BLI", date="2099-02-02",
    params={"calc_type": "bli_fit"},
    results={"samples": {"WT": {"standard": {"kd": 50.0, "r2": 0.98}}}},
)
cmp = compare.compare_experiments([fit["id"], fit2["id"]])
assert cmp["ok"] is True
assert cmp["calc_type"] == "bli_fit"
kd_row = next(r for r in cmp["rows"] if r["key"] == "WT.kd_nM")
assert kd_row["values"] == [10.0, 50.0]
assert kd_row["highlight"] is True
print("9. compare highlight OK")

# ── 10. compare rejects mixed types ──
bad = compare.compare_experiments([dil["id"], fit["id"]])
assert bad["ok"] is False
assert bad["error"] == "calc_type_mismatch"
print("10. compare mismatch OK")

# ── 11. Flask /compare + API ──
from app import app
client = app.test_client()
r = client.get("/compare")
assert r.status_code == 200, r.status_code
html = r.get_data(as_text=True)
assert 'id="compareTable"' in html
assert 'data-i18n="nav.compare"' in client.get("/").get_data(as_text=True)
api = client.post("/api/experiments/compare", json={"ids": [fit["id"], fit2["id"]]})
assert api.status_code == 200, api.get_data(as_text=True)
body = api.get_json()
assert body["ok"] and body["calc_type"] == "bli_fit"
mix = client.post("/api/experiments/compare", json={"ids": [dil["id"], fit["id"]]})
assert mix.status_code == 400
listed = client.get("/api/experiments?calc_type=dilution").get_json()
assert any(x["id"] == dil["id"] for x in listed)
print("11. compare page + API OK")

# ── 12. MCP compare_experiments is a read tool ──
import mcp_server
assert "compare_experiments" in mcp_server.READ_TOOLS
assert "compare_experiments" not in mcp_server.WRITE_TOOLS
before = open(models.DB_PATH, "rb").read()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    mcp_server.handle_tools_call(None, {
        "name": "compare_experiments",
        "arguments": {"exp_ids": [fit["id"], fit2["id"]]},
    })
assert open(models.DB_PATH, "rb").read() == before
mcp_body = json.loads(buf.getvalue().strip())
text = json.loads(mcp_body["result"]["content"][0]["text"])
assert text["ok"] is True
print("12. MCP compare_experiments read-only OK")

# ── 13. is_loadable：可载入判定的唯一源（详情页 CTA 与档案列表共用）──
# 逐字还原原 experiment_detail.html 内联判定的语义；下面每条边界都是刻意保守，
# 放宽任何一条都会让「载入计算工具」出现在载不动的实验上。
_IL = identity.is_loadable

# 13a. 分析型 raw 白名单 → True（BLI/AKTA/酶活三端）
assert _IL({"params": {}}, ["bli_curves"]) is True
assert _IL({"params": {}}, ["akta_traces"]) is True
assert _IL({"params": {}}, ["enzyme_traces"]) is True
# 白名单外（data_type 是开放集，库里就有 test_trace 这类非分析快照）→ False
assert _IL({"params": {}}, ["test_trace"]) is False
assert _IL({"params": {}}, ["bli_curves", "test_trace"]) is True

# 13b. 酶活靠 wells；空容器不算
assert _IL({"params": {"calc_type": "enzyme", "wells": {"A1": {"name": "WT"}}}}) is True
assert _IL({"params": {"calc_type": "enzyme", "wells": {}}}) is False
# 13c. 浓度/稀释靠 proteins；空列表不算
assert _IL({"params": {"calc_type": "concentration", "proteins": [{"name": "WT"}]}}) is True
assert _IL({"params": {"calc_type": "concentration", "proteins": []}}) is False
assert _IL({"params": {"calc_type": "dilution", "proteins": [{"name": "WT"}]}}) is True
# 三端各自认自己的槽位，不串台
assert _IL({"params": {"calc_type": "concentration", "wells": {"A1": {}}}}) is False
assert _IL({"params": {"calc_type": "enzyme", "proteins": [{"name": "WT"}]}}) is False

# 13d. 纯记录 / weblogo → False（原模板也不认 weblogo，即便有 sequences）
assert _IL({"exp_type": "其他", "params": {"k": "v"}, "results": {}}) is False
assert _IL({"params": {"calc_type": "weblogo", "sequences": ["ACDE"]}}) is False

# 13e. **核心保守点**：不给 exp_type 兜底推断。
# 这条实验会被 infer_calc_type 判成 bli_fit，但 params 里什么都没有 → 必须 False。
assert identity.infer_calc_type(
    {"exp_type": "BLI", "params": {}, "results": {"samples": {}}}) == "bli_fit"
assert _IL({"exp_type": "BLI", "params": {}, "results": {"samples": {"WT": {}}}}) is False

# 13f. 不认别名（证明没走 normalize_calc_type）
assert identity.normalize_calc_type("conc") == "concentration"
assert _IL({"params": {"calc_type": "conc", "proteins": [{"name": "WT"}]}}) is False
assert _IL({"params": {"calc_type": "bli", "wells": {"A1": {}}}}) is False

# 13g. 历史双重编码：params 是 JSON 字符串也要正确解包
assert _IL({"params": '{"calc_type": "enzyme", "wells": {"A1": {}}}'}) is True
assert _IL({"params": '{"calc_type": "enzyme", "wells": {}}'}) is False
assert _IL({"params": "not json", "wells": {"A1": {}}}) is False

# 13h. 空/None 输入不炸
assert _IL(None) is False
assert _IL({}) is False
print("13. is_loadable 判定边界 OK")

print("\nAll identity/compare tests passed.")
