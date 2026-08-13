"""test_bli.py — bli.py 模块 + 酶活绘图端点的回归测试（assert 脚本）

跑法（必须用 venv python）：
    .venv/Scripts/python.exe test_bli.py

覆盖：
1. parse_fortebio_csv / group_by_sample —— 合成 ForteBio CSV 的解析与分组
2. generate_sensorgram_png —— PNG 头校验 + fit 叠加 + separate 模式
3. fit_kd —— 自动相界检测 + 显式相界下 5 方法 KD 与仿真真值同数量级
4. 酶活纯函数（calculators.sub_blank / align_wells / snap_ylim）
5. /api/enzyme/plot（kinetics + michaelis）→ 200 + base64 PNG（隔离临时库）
6. /calculator 仍 200

数据安全：数据库用临时目录，不触碰生产库（见 CLAUDE.md 测试规范）。
"""
import os, sys, csv, base64, importlib, tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from bli import _simulate_1to1, parse_fortebio_csv, group_by_sample, \
    generate_sensorgram_png, fit_kd

TMP = tempfile.mkdtemp(prefix="protein_lab_test_")

# ── 1. 合成 fixture：真值 kon=1e-4 / koff=0.01 → KD = 100 nM ──
rng = np.random.default_rng(42)
KON, KOFF, RMAX = 1e-4, 0.01, 1.0
T_ASSOC, T_DISSOC = 100.0, 400.0
t = np.arange(0.0, 700.0, 2.0)

samples = [
    ("A1", "WT", 200.0), ("A2", "WT", 100.0), ("A3", "WT", 50.0),
    ("A4", "WT", 25.0), ("A5", "WT", 12.5),
    ("B1", "MUT", 200.0), ("B2", "MUT", 50.0),
]
rows = [[None]]  # 行 0: XML（解析器不读）
rows.append([f"t1{l}c{i}" for l, _, _ in samples for i in (1, 2)])
row2, row3 = [], []
for l, sid, c in samples:
    row2 += [f"Sample Loc: {l}", f"Sample ID: {sid}"]
    row3 += [f"Sample Conc: {c:g}", ""]
rows.append(row2)
rows.append(row3)
rows.append([])  # 行 4 空行
ncols = len(samples)
resp_cols = []
for l, sid, c in samples:
    y = _simulate_1to1(t, KON, KOFF, RMAX, c, T_ASSOC, T_DISSOC)
    resp_cols.append(y + rng.normal(0, 0.008, size=len(t)))
for i in range(len(t)):
    row = []
    for j in range(ncols):
        row += [f"{t[i]:.1f}", f"{resp_cols[j][i]:.6f}"]
    rows.append(row)

csv_path = os.path.join(TMP, "fixture.csv")
with open(csv_path, "w", encoding="utf-8", newline="") as f:
    csv.writer(f).writerows(rows)

# ── 2. parse / group ──
curves = parse_fortebio_csv(csv_path)
assert len(curves) == len(samples), f"解析传感器数 {len(curves)} != {len(samples)}"
groups = group_by_sample(curves)
assert set(groups) == {"WT", "MUT"}, set(groups)
assert [c.conc_nM for c in groups["WT"]] == [200, 100, 50, 25, 12.5], "组内须浓度降序"
print("parse/group OK:", {k: len(v) for k, v in groups.items()})

# ── 3. 传感器图 PNG ──
png = generate_sensorgram_png(curves, smooth_window=31)
assert png[:8] == b"\x89PNG\r\n\x1a\n", "PNG 头校验失败"
png_fit = generate_sensorgram_png(curves, fit=True)
assert png_fit[:8] == b"\x89PNG\r\n\x1a\n"
sep = generate_sensorgram_png(curves, separate=True)
assert set(sep) == {"WT", "MUT"}
print(f"sensorgram PNG OK: {len(png)}B, fit={len(png_fit)}B, separate={ {k: len(v) for k, v in sep.items()} }")

# ── 4. KD 拟合（真值 KD=100 nM）──
# 4a. 自动相界检测 sanity：解离起点应落在结合平台区域
res_auto = fit_kd(groups["WT"], verbose=True)
ta_auto, td_auto = res_auto["phase"]["t_assoc"], res_auto["phase"]["t_dissoc"]
print(f"auto phase: assoc={ta_auto:.1f} dissoc={td_auto:.1f}")
assert 90 <= ta_auto <= 120, f"auto t_assoc {ta_auto} 异常"
assert 250 <= td_auto <= 450, f"auto t_dissoc {td_auto} 异常"

# 4b. 显式相界（协议真值）→ 5 方法 KD 与真值同数量级
res = fit_kd(groups["WT"], t_assoc=100, t_dissoc=400, verbose=True)
print("explicit phase: 100→400")
for m, v in res.items():
    if m != "phase" and v:
        print(f"  {m}: {v}")
kd_std = res["standard"]["kd"]
assert 10 < kd_std < 1000, f"standard KD {kd_std} 偏离真值过远"
kd_joint = res["joint"]["kd"]
assert 10 < kd_joint < 1000, f"joint KD {kd_joint} 偏离真值过远"
print(f"KD OK: standard={kd_std:.1f} nM, joint={kd_joint:.1f} nM (truth 100)")

# ── 5. 酶活纯函数（calculators：sub_blank / align_wells / snap_ylim）──
from calculators import sub_blank, align_wells, snap_ylim, correct_slopes

def _close(a, b, tol=1e-9):
    return abs(a - b) < tol

# 5a. sub_blank：逐时间点扣背景均值，背景自身归零；neg+blank 并存只扣阴性（空白不入背景）
wells = {
    "A1": {"times": [0, 1, 2], "od": [0.10, 0.12, 0.14], "ref": ""},
    "B1": {"times": [0, 1, 2], "od": [0.08, 0.08, 0.08], "ref": "neg"},
    "B2": {"times": [0, 1, 2], "od": [0.10, 0.10, 0.10], "ref": "blank"},
}
subbed, mean_neg = sub_blank(wells, enabled=True)
assert set(mean_neg) == {0, 1, 2} and all(_close(v, 0.08) for v in mean_neg.values()), mean_neg
assert all(_close(a, b) for a, b in zip(subbed["A1"]["od"], [0.02, 0.04, 0.06])), subbed["A1"]["od"]
assert _close(subbed["B1"]["od"][0], 0.0), "阴性自身应被扣到 ≈0"
# 空白不入背景：扣的是 neg 均值，故 B2 = 0.10 - 0.08 = 0.02（不被「多扣」）
assert all(_close(a, b) for a, b in zip(subbed["B2"]["od"], [0.02, 0.02, 0.02])), subbed["B2"]["od"]
# 仅空白：回退用空白作背景（兼容老用法）
w_bo = {"A1": {"times": [0, 1], "od": [0.20, 0.22], "ref": ""},
        "B2": {"times": [0, 1], "od": [0.05, 0.05], "ref": "blank"}}
sbo, mno = sub_blank(w_bo, enabled=True)
assert all(_close(v, 0.05) for v in mno.values()), mno
assert all(_close(a, b) for a, b in zip(sbo["A1"]["od"], [0.15, 0.17])), sbo["A1"]["od"]
# 未启用：原样返回、mean_neg=None；无背景孔：也原样
w_off, mn_off = sub_blank(wells, enabled=False)
assert mn_off is None and w_off is wells
w_none, mn_none = sub_blank({"A1": {"times": [0], "od": [0.1], "ref": ""}}, enabled=True)
assert mn_none is None and w_none["A1"]["od"] == [0.1]
print("sub_blank OK")

# 5b. align_wells：均值只统计样品/阳性，位移只作用于样品/阳性
w3 = {
    "A1": {"times": [0, 1], "od": [0.10, 0.20], "ref": ""},
    "A2": {"times": [0, 1], "od": [0.30, 0.40], "ref": "pos"},
    "B1": {"times": [0, 1], "od": [0.05, 0.06], "ref": "neg"},
}
aligned, af, al = align_wells(w3, align_start=True, align_end=False)
assert _close(af, 0.20), af  # (0.10 + 0.30) / 2
assert all(_close(a, b) for a, b in zip(aligned["A1"]["od"], [0.20, 0.30])), aligned["A1"]["od"]
assert all(_close(a, b) for a, b in zip(aligned["A2"]["od"], [0.20, 0.30])), aligned["A2"]["od"]
assert aligned["B1"]["od"] == [0.05, 0.06], "阴性不参与对齐"
# 无对齐开关：原样返回
w_n, _, _ = align_wells(w3, align_start=False, align_end=False)
assert w_n["A1"]["od"] == [0.10, 0.20]
print("align_wells OK", af)

# 5c. snap_ylim：外扩 6% + 数量级取整；空值返回 None
assert snap_ylim([]) is None
lo, hi = snap_ylim([0.0, 1.0, 2.0])
assert _close(lo, -0.2) and _close(hi, 2.2), (lo, hi)  # span=2 → step=0.1 → [-0.2, 2.2]
print("snap_ylim OK", (lo, hi))

# 5d. correct_slopes：仅阴性斜率均值作背景；空白是基线不入背景、不被校正
fits = {
    "A1": {"slope": 0.010, "intercept": 0.1, "r2": 0.99, "n": 20},   # 样品
    "B1": {"slope": 0.002, "intercept": 0.08, "r2": 0.90, "n": 20},  # 阴性（背景）
    "D1": {"slope": 0.001, "intercept": 0.05, "r2": 0.95, "n": 20},  # 空白（基线）
    "C1": {"slope": None, "intercept": None, "r2": None, "n": 1},    # 数据点不足
}
refs = {"A1": "", "B1": "neg", "D1": "blank", "C1": ""}
out = correct_slopes(fits, refs)
assert out["A1"]["blank_corrected"] is True
assert _close(out["A1"]["slope_corrected"], 0.008), out["A1"]   # 0.010 - 0.002（只扣阴性）
assert out["B1"]["blank_corrected"] is True
assert _close(out["B1"]["slope_corrected"], 0.000), out["B1"]   # 阴性自身也扣
# 空白不入背景、不被速率校正——避免被多扣成负值
assert "slope_corrected" not in out["D1"] and "blank_corrected" not in out["D1"], out["D1"]
assert "slope_corrected" not in out["C1"] and "blank_corrected" not in out["C1"], out["C1"]
# 无背景：blank_corrected=False，不产生 slope_corrected
out2 = correct_slopes({"A1": {"slope": 0.010}}, {"A1": ""})
assert out2["A1"]["blank_corrected"] is False and "slope_corrected" not in out2["A1"]
# 仅空白作背景：样品扣空白均值，空白自身不被校正
out3 = correct_slopes({"A1": {"slope": 0.010}, "D1": {"slope": 0.001}}, {"A1": "", "D1": "blank"})
assert _close(out3["A1"]["slope_corrected"], 0.009), out3
assert "slope_corrected" not in out3["D1"]
print("correct_slopes OK")

# ── 6. 酶活绘图端点（隔离临时库）──
import models
importlib.reload(models)  # ⚠ 会把 DB_PATH 重置为真实路径（测试规范要求）
models.DB_PATH = os.path.join(TMP, "test.db")
models.init_db()
from app import app
client = app.test_client()

tt = list(np.arange(0, 10, 0.5))
payload_kinetics = {
    "type": "kinetics", "align_start": True, "align_end": False, "show_blank": False,
    "wells": {
        "A1": {"times": tt, "od": [0.1 + 0.002 * x for x in range(len(tt))],
               "name": "WT", "conc_ng_ml": 200, "ref": "pos",
               "fit": {"slope": 0.002, "intercept": 0.1}},
        "A2": {"times": tt, "od": [0.08 + 0.001 * x for x in range(len(tt))],
               "name": "MUT", "conc_ng_ml": 100, "ref": "",
               "fit": {"slope": 0.001, "intercept": 0.08}},
    },
}
resp = client.post("/api/enzyme/plot", json=payload_kinetics)
assert resp.status_code == 200, resp.status_code
img = resp.get_json()["image"]
assert img.startswith("data:image/png;base64,"), img[:40]
base64.b64decode(img.split(",", 1)[1])
print("enzyme kinetics plot OK")

# 5b. sub_blank（扣除阴性信号）：含平坦阴性孔 + show_blank 时阴性必须能画出来且正常渲染
payload_sub = {
    "type": "kinetics", "sub_blank": True, "show_blank": True,
    "wells": {
        "A1": {"times": tt, "od": [0.1 + 0.002 * x for x in range(len(tt))],
               "name": "WT", "conc_ng_ml": 200, "ref": "",
               "fit": {"slope": 0.002, "intercept": 0.1}},
        "B1": {"times": tt, "od": [0.08] * len(tt),
               "name": "Neg", "ref": "neg",
               "fit": {"slope": 0.0, "intercept": 0.08}},
    },
}
resp = client.post("/api/enzyme/plot", json=payload_sub)
assert resp.status_code == 200, resp.status_code
assert resp.get_json()["image"].startswith("data:image/png;base64,")
print("enzyme kinetics sub_blank (neg included) OK")

payload_mm = {"type": "michaelis", "wells": {
    "A1": {"substrate_uM": 10, "rate": 0.001, "name": "WT"},
    "A2": {"substrate_uM": 20, "rate": 0.002, "name": "MUT"},
}}
resp = client.post("/api/enzyme/plot", json=payload_mm)
assert resp.status_code == 200, resp.status_code
assert resp.get_json()["image"].startswith("data:image/png;base64,")
print("enzyme michaelis plot OK")

# 6b. /api/enzyme/fit 返回速率级校正（slope_corrected 已收归后端；空白不被校正）
resp = client.post("/api/enzyme/fit", json={"wells": {
    "A1": {"times": tt, "od": [0.1 + 0.002 * x for x in range(len(tt))], "ref": ""},
    "B1": {"times": tt, "od": [0.08 + 0.0005 * x for x in range(len(tt))], "ref": "neg"},
    "C1": {"times": tt, "od": [0.07] * len(tt), "ref": "blank"},
}})
assert resp.status_code == 200, resp.status_code
fit_res = resp.get_json()
assert fit_res["A1"]["blank_corrected"] is True, fit_res
assert "slope_corrected" in fit_res["A1"] and fit_res["B1"]["slope_corrected"] is not None
assert "slope_corrected" not in fit_res["C1"], "空白不做速率校正"
print("enzyme fit slope_corrected OK")

assert client.get("/calculator").status_code == 200
print("/calculator OK")

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED")
