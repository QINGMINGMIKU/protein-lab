"""test_akta.py — akta.py 模块（AKTA Unicorn zip 原生解析 / 峰检测 / 峰图）+ API 回归测试（assert 脚本）

跑法（必须用 venv python）：
    .venv/Scripts/python.exe test_akta.py

覆盖：
1. parse_akta_zip —— 两个真实样例 zip（REF/*.zip）的通道/事件解析（不依赖 pycorn，标准库原生）
2. find_uv_channels / find_fraction_events
3. detect_peaks —— 峰检测与真值位置同数量级（1YPI 主峰 ≈23.96 mL，PD1 主峰 ≈0.86 mL）
4. generate_akta_png —— PNG 头校验
5. /api/akta/analyze、/api/akta/plot、/api/akta/export、/api/akta/save（raw 落库 + version，隔离临时库）
6. raw 不可变 + 会话守卫

数据安全：数据库用临时目录，不触碰生产库（见 CLAUDE.md 测试规范）。
"""
import os, sys, base64, importlib, tempfile, shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TMP = tempfile.mkdtemp(prefix="protein_lab_akta_test_")
# 样例 zip 优先用 fixtures/（git 跟踪、CI 可用）；本地无 fixtures 时回退 REF/（被 gitignore 的工作区参考）
ROOT = os.path.dirname(os.path.abspath(__file__))


def _resolve_zip(name: str) -> str:
    for base in ("fixtures", "REF"):
        p = os.path.join(ROOT, base, name)
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, "fixtures", name)


ZIP_1YPI = _resolve_zip("1YPI_32 002.zip")
ZIP_PD1 = _resolve_zip("2026_0528_PD1_263_s75-10-300 75kd-6.5kd 003.zip")
assert os.path.exists(ZIP_1YPI), f"缺少样例 zip: {ZIP_1YPI}"
assert os.path.exists(ZIP_PD1), f"缺少样例 zip: {ZIP_PD1}"

import numpy as np
from akta import (parse_akta_zip, find_uv_channels, find_fraction_events,
                  detect_peaks, generate_akta_png, AKTA_ANALYSIS_VERSION)

# ── 1. 解析：1YPI（22 通道 + Fraction 31）──
r1 = parse_akta_zip(ZIP_1YPI)
ch1 = r1["channels"]
assert len(ch1) >= 20, f"1YPI 通道数 {len(ch1)} 异常"
assert "UV" in ch1, "1YPI 应有 UV 通道"
uv1 = ch1["UV"]
assert uv1.data_type == "UV" and uv1.unit == "mAU"
assert uv1.n_points() > 20000, f"1YPI UV 点数 {uv1.n_points()} 异常（应全分辨率）"
assert float(uv1.vols[0]) < 0.01 and 30 < float(uv1.vols[-1]) < 40, "UV 体积范围异常"
frac1 = find_fraction_events(r1["events"])
assert len(frac1) == 31, f"1YPI Fraction 事件数 {len(frac1)} != 31"
assert any("3.C.6" in txt for _, txt in frac1), "Fraction 应含板位标签"
print(f"1YPI parse OK: {len(ch1)} channels, {len(frac1)} fractions")

# ── 2. 解析：PD1_263（UV 1_280/2_260/3_230 + Fraction 13）──
r2 = parse_akta_zip(ZIP_PD1)
ch2 = r2["channels"]
uv_list = find_uv_channels(ch2)
assert uv_list == ["UV 1_280", "UV 2_260", "UV 3_230"], uv_list
uv280 = ch2["UV 1_280"]
assert uv280.n_points() > 5000 and float(np.max(uv280.amps)) > 50, "PD1 UV 280 应有强峰"
frac2 = find_fraction_events(r2["events"])
assert len(frac2) == 13, f"PD1 Fraction 事件数 {len(frac2)} != 13"
print(f"PD1 parse OK: {len(ch2)} channels, UV={uv_list}, {len(frac2)} fractions")

# ── 3. 峰检测：主峰位置与真值同数量级 ──
peaks1 = detect_peaks(uv1, min_height=5, smooth_window=11)
assert peaks1, "1YPI 应检出峰"
best1 = max(peaks1, key=lambda p: p.height)
assert 20 < best1.apex_vol < 27, f"1YPI 主峰 {best1.apex_vol} 偏离 23.96 mL 过远"
assert best1.height > 5, f"1YPI 主峰高 {best1.height} 异常"
peaks2 = detect_peaks(uv280, min_height=5, smooth_window=11)
assert peaks2, "PD1 应检出峰"
best2 = max(peaks2, key=lambda p: p.height)
assert 0.3 < best2.apex_vol < 1.5, f"PD1 主峰 {best2.apex_vol} 偏离 0.86 mL 过远"
assert best2.height > 50, f"PD1 主峰高 {best2.height} 异常"
# 半高宽/面积为正
assert all(p.half_width > 0 and p.area > 0 for p in peaks1[:3])
print(f"peak detection OK: 1YPI 主峰 {best1.apex_vol:.2f} mL, PD1 主峰 {best2.apex_vol:.2f} mL")

# ── 4. 峰图 PNG ──
png = generate_akta_png(uv280, peaks2, events=frac2, show_events=True)
assert png[:8] == b"\x89PNG\r\n\x1a\n", "PNG 头校验失败"
print(f"akta PNG OK: {len(png)}B")

# ── 5. API（隔离临时库）──
import models
importlib.reload(models)  # ⚠ 会把 DB_PATH 重置为真实路径（测试规范要求）
models.DB_PATH = os.path.join(TMP, "test.db")
models.init_db()
from app import app
client = app.test_client()

# 5a. analyze
with open(ZIP_1YPI, "rb") as f:
    resp = client.post("/api/akta/analyze",
                       data={"file": (f, "1YPI_32 002.zip")},
                       content_type="multipart/form-data")
assert resp.status_code == 200, resp.status_code
ana = resp.get_json()
assert ana["session_id"] and ana["uv_channels"] == ["UV"], ana
assert any(ch["name"] == "UV" for ch in ana["channels"])
assert ana["events"].get("Fraction") == 31, ana["events"]
sid = ana["session_id"]
print("akta analyze OK:", len(ana["channels"]), "channels, events:", ana["events"])

# 5b. plot：返回 image + peaks
resp = client.post("/api/akta/plot", json={
    "session_id": sid, "channel": "UV", "min_height": 5, "smooth_window": 11,
    "show_events": True})
assert resp.status_code == 200, resp.status_code
plot = resp.get_json()
assert plot["image"].startswith("data:image/png;base64,"), plot["image"][:40]
base64.b64decode(plot["image"].split(",", 1)[1])
assert plot["peaks"], "UV 通道应检出峰"
print("akta plot OK:", len(plot["peaks"]), "peaks")

# 5c. export：返回 xlsx
resp = client.post("/api/akta/export", json={
    "session_id": sid, "channel": "UV", "min_height": 5, "smooth_window": 11})
assert resp.status_code == 200, resp.status_code
xlsx = resp.data
assert xlsx[:2] == b"PK", "xlsx 应为 zip 容器"
print(f"akta export OK: {len(xlsx)}B xlsx")

# 5d. save：results 带 AKTA_ANALYSIS_VERSION；raw→experiment_raw data_type=akta_traces
resp = client.post("/api/akta/save", json={
    "session_id": sid, "title": "AKTA API 测试", "channel": "UV",
    "min_height": 5, "smooth_window": 11, "source": "1YPI_32 002.zip"})
assert resp.status_code == 201, (resp.status_code, resp.get_json())
saved = resp.get_json()
assert saved["exp_type"] == "AKTA"
assert saved["results"]["AKTA_ANALYSIS_VERSION"] == AKTA_ANALYSIS_VERSION
assert saved["results"]["n_peaks"] >= 1
assert saved["params"]["channel"] == "UV"
raws = models.exp_raw_list(saved["id"])
assert len(raws) == 1 and raws[0]["data_type"] == "akta_traces", raws
raw1 = models.exp_raw_get(raws[0]["id"])
assert raw1["payload"]["analysis_version"] == AKTA_ANALYSIS_VERSION
assert raw1["payload"]["channel"]["name"] == "UV"
assert len(raw1["payload"]["channel"]["vols"]) == uv1.n_points(), "raw 通道全量落库"
# raw 只写一次：同一实验重复 save 后旧 raw 内容不变（新分析=新行，旧行不动）
resp2 = client.post("/api/akta/save", json={
    "session_id": sid, "title": "AKTA API 测试2", "channel": "UV",
    "min_height": 5, "smooth_window": 11})
saved2 = resp2.get_json()
raws2 = models.exp_raw_list(saved2["id"])
assert len(raws2) == 1
raw1_after = models.exp_raw_get(raws[0]["id"])
assert raw1_after["payload"]["channel"] == raw1["payload"]["channel"], "raw 不可变"
print(f"akta save OK: exp#{saved['id']} raw#{raws[0]['id']} version={AKTA_ANALYSIS_VERSION}")

# 5e. 会话守卫：无效 session → 400
resp = client.post("/api/akta/plot", json={"session_id": "nope", "channel": "UV"})
assert resp.status_code == 400
resp = client.post("/api/akta/save", json={"session_id": "nope", "channel": "UV"})
assert resp.status_code == 400
print("akta session guard OK")

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED")
