"""test_akta.py — akta.py 模块（AKTA Unicorn zip 原生解析 / 峰检测 / 峰图）+ API 回归测试（assert 脚本）

跑法（必须用 venv python）：
    .venv/Scripts/python.exe test_akta.py

覆盖：
1. parse_akta_zip —— 两个真实样例 zip（REF/*.zip）的通道/事件解析（不依赖 pycorn，标准库原生）
2. find_uv_channels / find_fraction_events
3. detect_peaks —— 峰检测与真值位置同数量级（1YPI 主峰 ≈23.96 mL，PD1 主峰 ≈0.86 mL）
4. generate_akta_png —— PNG 头校验 + peak_labels/peak_fill/normalize 组合出图
5. _smooth —— savgol 边界守卫（偶窗 == len 不崩；短序列原样返回）
6. /api/akta/analyze、/api/akta/plot、/api/akta/export、/api/akta/save（raw 落库 + version，隔离临时库）
7. raw 不可变 + 会话守卫

数据安全：数据库用临时目录，不触碰生产库（见 CLAUDE.md 测试规范）。
"""
import os, sys, base64, importlib, tempfile, shutil, io

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
                  detect_peaks, generate_akta_png, _smooth, AKTA_ANALYSIS_VERSION)

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

# 4a. peak_labels / peak_fill / normalize 组合出图（回归：P2-4/5/6 改动路径）
for kw in ({"peak_labels": True},
           {"peak_fill": False},
           {"peak_labels": True, "peak_fill": False},
           {"peak_labels": True, "normalize": True}):
    png_k = generate_akta_png(uv280, peaks2, **kw)
    assert png_k[:8] == b"\x89PNG\r\n\x1a\n", f"PNG 头失败 kw={kw}"
print("akta PNG variants OK: peak_labels / peak_fill / normalize 组合")

# 4b. _smooth savgol 边界守卫（回归 P1-1：len(y)==偶窗 时 +1 后越界，savgol 抛 ValueError）
y_even = np.arange(4, dtype=float)
assert np.array_equal(_smooth(y_even, 4), y_even), "偶窗 == len 应原样返回（+1 后超长）"
assert np.array_equal(_smooth(y_even, 5), y_even), "窗 > len 应原样返回"
assert np.array_equal(_smooth(np.array([], dtype=float), 11), np.array([], dtype=float)), "空序列原样返回"
out = _smooth(np.arange(10, dtype=float), 4)      # 偶窗 < len → +1 成 5 正常平滑
assert out.shape == (10,) and np.isfinite(out).all()
out_odd = _smooth(np.arange(10, dtype=float), 5)  # 奇窗 < len 常规路径
assert out_odd.shape == (10,) and np.isfinite(out_odd).all()
out_eq = _smooth(np.arange(5, dtype=float), 5)    # 奇窗 == len（5 <= 5 合法）
assert out_eq.shape == (5,) and np.isfinite(out_eq).all()
print("akta _smooth boundary OK: 偶窗==len 不崩 / 短序列原样返回 / 常规路径同长")

# ── 5. API（隔离临时库）──
import models
importlib.reload(models)  # ⚠ 会把 DB_PATH 重置为真实路径（测试规范要求）
models.DB_PATH = os.path.join(TMP, "test.db")
models.init_db()
from app import app
client = app.test_client()

# 5a. analyze（多文件批量）
with open(ZIP_1YPI, "rb") as f:
    resp = client.post("/api/akta/analyze",
                       data={"file": (f, "1YPI_32 002.zip")},
                       content_type="multipart/form-data")
assert resp.status_code == 200, resp.status_code
ana = resp.get_json()
runs = ana["runs"]
assert len(runs) == 1, runs
r0 = runs[0]
assert r0["session_id"] and r0["uv_channels"] == ["UV"], r0
assert any(ch["name"] == "UV" for ch in r0["channels"])
assert r0["events"].get("Fraction") == 31, r0["events"]
sid = r0["session_id"]
print("akta analyze OK:", len(r0["channels"]), "channels, events:", r0["events"])

# 5a2. 批量：一次上传两个 zip → 两个 run
with open(ZIP_1YPI, "rb") as f1, open(ZIP_PD1, "rb") as f2:
    resp = client.post("/api/akta/analyze", data={
        "file": [(f1, "1YPI_32 002.zip"), (f2, "PD1.zip")]},
        content_type="multipart/form-data")
assert resp.status_code == 200, resp.status_code
runs2 = resp.get_json()["runs"]
assert len(runs2) == 2, runs2
assert runs2[0]["uv_channels"] == ["UV"] and runs2[1]["uv_channels"] == ["UV 1_280", "UV 2_260", "UV 3_230"]
print("akta batch analyze OK:", [r["name"] for r in runs2])

# 5b. plot：返回 image + peaks（默认无 frac 竖线、有目标峰阴影）
resp = client.post("/api/akta/plot", json={
    "session_id": sid, "channel": "UV", "min_height": 5, "smooth_window": 11,
    "show_events": False, "highlight_frac": True, "target_peak_idx": 0})
assert resp.status_code == 200, resp.status_code
plot = resp.get_json()
assert plot["image"].startswith("data:image/png;base64,"), plot["image"][:40]
base64.b64decode(plot["image"].split(",", 1)[1])
assert plot["peaks"], "UV 通道应检出峰"
print("akta plot OK:", len(plot["peaks"]), "peaks")

# 5b1. normalize=True 归一化图 + 总图 overlay
resp = client.post("/api/akta/plot", json={
    "session_id": sid, "channel": "UV", "min_height": 5, "smooth_window": 11,
    "normalize": True})
assert resp.status_code == 200, resp.status_code
assert resp.get_json()["image"].startswith("data:image/png;base64,")
print("akta plot normalize OK")

# 总图：同一 zip 的 UV + Cond 两通道叠加（API 层面 <2 文件时用两通道验证路径）
resp = client.post("/api/akta/overlay", json={
    "runs": [{"session_id": sid, "channel": "UV"},
             {"session_id": sid, "channel": "Cond"}],
    "min_height": 5, "smooth_window": 11, "normalize": True})
assert resp.status_code == 200, (resp.status_code, resp.get_json())
ov = resp.get_json()
assert ov["image"].startswith("data:image/png;base64,"), ov["image"][:40]
print("akta overlay OK:", len(ov["image"]) // 100, "xx base64")

# 总图 + frac 阴影：highlight_frac=True 时每个文件的目标峰阴影三元组传入绘图
resp = client.post("/api/akta/overlay", json={
    "runs": [{"session_id": sid, "channel": "UV", "target_peak_idx": 0},
             {"session_id": sid, "channel": "Cond", "target_peak_idx": 0}],
    "min_height": 5, "smooth_window": 11, "highlight_frac": True})
assert resp.status_code == 200, (resp.status_code, resp.get_json())
ov_sh = resp.get_json()
assert ov_sh["image"].startswith("data:image/png;base64,")
img = base64.b64decode(ov_sh["image"].split(",", 1)[1])
# 像素级：总图应有曲线色的连续阴影矩形（蓝色 #2166ac 系，alpha 0.15 叠白 ≈ (213,222,249)）
from PIL import Image
import numpy as np
a = np.asarray(Image.open(io.BytesIO(img)).convert("RGB"))
blue_shadow = np.sum((abs(a[:, :, 0].astype(int) - 213) < 30) &
                     (abs(a[:, :, 1].astype(int) - 222) < 30) &
                     (abs(a[:, :, 2].astype(int) - 249) < 30))
assert blue_shadow > 500, f"总图 frac 阴影缺失（蓝色像素 {blue_shadow}）"
print(f"akta overlay frac-shadow OK: {blue_shadow} 阴影像素")

# 总图：单通道 → 400（至少 2 个文件/通道）
resp = client.post("/api/akta/overlay", json={
    "runs": [{"session_id": sid, "channel": "UV"}]})
assert resp.status_code == 400
print("akta overlay guard OK")

# 5b2. fraction_ranges / target_fraction_span / span_bounds 纯函数
from akta import fraction_ranges, target_fraction_span, span_bounds
fr = fraction_ranges(r1["events"]["Fraction"], 36.4)
assert len(fr) == 31, f"frac 区间数 {len(fr)} != 31"
assert fr[0][0] < fr[1][0] and fr[-1][1] == 36.4, "区间应有序且末管延伸到 xmax"
# 主峰 23.96 mL 落在某 frac 内；其前后各一管构成阴影三元组
span = target_fraction_span(fr, 23.96, xmin=0, xmax=36.4)
assert span["self"] and span["prev"] and span["next"], span
assert span["self"][0] < span["self"][1] and span["self_label"], span
assert span["prev"][1] <= span["self"][0] and span["next"][0] >= span["self"][1], "前后 frac 应紧邻自身"
# 连续矩形 = [prev.start, next.end]（1 个矩形覆盖 3 管）
bounds = span_bounds(span)
assert bounds == (span["prev"][0], span["next"][1]), bounds
# 无事件 / 顶点不在 frac 内 → 安全返回 None
assert target_fraction_span([], 5)["self"] is None
assert target_fraction_span(fr, -1)["self"] is None
assert span_bounds(target_fraction_span([], 5)) is None
print("fraction shadow bounds OK:", bounds, "（连续矩形覆盖 3 管）")

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

# 5d3. 数据重挂：带 exp_id → 200，覆盖 results + 追加 raw（只写不更），实验身份不变
_mresp = client.post("/api/akta/save", json={
    "session_id": sid, "exp_id": saved["id"], "title": "忽略", "channel": "UV",
    "min_height": 5, "smooth_window": 11})
assert _mresp.status_code == 200, (_mresp.status_code, _mresp.get_json())
_mount = _mresp.get_json()
assert _mount["id"] == saved["id"] and _mount["title"] == "AKTA API 测试", \
    f"重挂不改实验身份/标题: {_mount['title']}"
assert _mount["results"].get("AKTA_ANALYSIS_VERSION") == AKTA_ANALYSIS_VERSION
_rawn_m = models.exp_raw_list(saved["id"])
assert len(_rawn_m) == 2, f"重挂应追加 raw 新行: {_rawn_m}"
assert models.exp_raw_get(raws[0]["id"])["payload"]["channel"] == raw1["payload"]["channel"], \
    "重挂后旧 raw 不可变"
print(f"akta save 重挂 OK: exp#{saved['id']} raw 1→2")

# 5d2. 自动命名：title 留空时用 zip 包名（去 .zip 扩展名，含日期/描述部分保留）
resp = client.post("/api/akta/save", json={
    "session_id": sid, "channel": "UV", "min_height": 5, "smooth_window": 11,
    "source": "1YPI_32 002.zip"})
assert resp.status_code == 201, resp.status_code
saved_auto = resp.get_json()
assert saved_auto["title"] == "1YPI_32 002", saved_auto["title"]
print("akta auto-title OK:", saved_auto["title"])
# 带 title 时优先 title
resp = client.post("/api/akta/save", json={
    "session_id": sid, "title": "手动标题", "channel": "UV",
    "min_height": 5, "smooth_window": 11, "source": "PD1.zip"})
saved_t = resp.get_json()
assert saved_t["title"] == "手动标题", saved_t["title"]
# 无 title 也无 source → 系统自动命名 {date}_akta_{seq}
resp = client.post("/api/akta/save", json={
    "session_id": sid, "channel": "UV", "min_height": 5, "smooth_window": 11})
saved_none = resp.get_json()
assert "_akta_" in saved_none["title"], saved_none["title"]
print("akta auto-title fallback OK:", saved_none["title"])

# 5e. 会话守卫：无效 session → 400
resp = client.post("/api/akta/plot", json={"session_id": "nope", "channel": "UV"})
assert resp.status_code == 400
resp = client.post("/api/akta/save", json={"session_id": "nope", "channel": "UV"})
assert resp.status_code == 400
print("akta session guard OK")

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED")
