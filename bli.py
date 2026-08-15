"""
BLI 分析模块 — ForteBio CSV 解析 / 传感器图生成 / 1:1 Langmuir KD 拟合

纯计算，无 Flask 依赖（同 calculators.py 定位）。绘图走 matplotlib Agg + fonts.py 中文。

数据格式：ForteBio 预处理 CSV——
  - 行 1 列头：`t1E1c1` 形式的传感器列（每传感器 2 列：时间 + 响应）
  - 行 2-3 元数据：`Sample Loc:` / `Sample ID:` / `Sample Conc:`（顺序 == 数据列顺序，勿按板位重排）
  - 行 5+ 数值行
解析来自 REF/generate_BLI_figure.py（宽版 A-P 孔位）与 REF/fit_KD.py 的合并统一。

绘图样式常量 COLORS / PLOT_STYLE 供酶活等其他模块复用（参考 BLI 风格）。
KD 拟合：5 种方法（standard / split / joint / steady / mixed）+ 死曲线过滤 + NS 非特异扣除。

分析版本契约：Web 分析 UI 保存实验时，results 里带 BLI_ANALYSIS_VERSION；
experiment_raw 落 data_type="bli_curves" 原始曲线快照（只写一次）。
"""

import csv
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import curve_fit, least_squares
from scipy.signal import savgol_filter

# BLI 分析版本（随 v0.0.8 引入）：写入 results["BLI_ANALYSIS_VERSION"]，
# 供未来 recompute 对照——同版本 + 同 raw 快照 → 可复现同结果（规则 #8）。
BLI_ANALYSIS_VERSION = "0.0.8"

# ═══════════════════════════════════════════════════════════
#  绘图样式（BLI 风格）—— 酶活等其他模块引用同一套
# ═══════════════════════════════════════════════════════════

COLORS = ["#9bbf8a", "#82afda", "#f79059", "#e7dbd3", "#c2bdde",
          "#8dcec8", "#add3e2", "#3480b8", "#ffbe7a", "#fa8878", "#c82423"]

PLOT_STYLE = {
    "font.size": 12,
    "axes.titlesize": 14,
    "axes.labelsize": 13,
    "legend.fontsize": 10,
    "lines.linewidth": 2.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 1.0,
    "xtick.major.width": 1.0,
    "ytick.major.width": 1.0,
}


# ═══════════════════════════════════════════════════════════
#  数据模型 + 解析
# ═══════════════════════════════════════════════════════════

@dataclass
class Curve:
    """单条传感器结合曲线。"""
    label: str          # 传感器标签，如 "E1"
    sample_id: str      # Sample ID（同一样品多条曲线）
    conc_nM: float      # 样品浓度 (nM)
    time: np.ndarray    # 时间 (s)
    response: np.ndarray  # 响应 (nm)，NaN 为缺失


def parse_fortebio_csv(path: str) -> List[Curve]:
    """解析 ForteBio 预处理 CSV → Curve 列表。

    metadata 顺序 == 数据列顺序（ForteBio 预处理保证），不做板位重排——
    一旦按源板位排序会破坏元数据与传感器列的 1:1 对应（generate_BLI_figure 要点）。
    """
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) < 6:
        raise ValueError(f"CSV 行数不足（{len(rows)} 行，至少需 6 行：1 XML + 4 头 + 1 数据）")

    # 元数据（行 2-3）：每传感器一组的 Sample Loc / Sample ID / Sample Conc
    row2, row3 = rows[2], rows[3]
    wells_meta: List[Tuple[str, str, str]] = []
    i = 0
    while i < len(row2):
        loc_field = row2[i].strip()
        id_field = row2[i + 1].strip() if i + 1 < len(row2) else ""
        conc_field = row3[i].strip() if i < len(row3) else ""
        m_loc = re.match(r"Sample Loc:\s*(.+)", loc_field)
        m_id = re.match(r"Sample ID:\s*(.+)", id_field)
        m_conc = re.match(r"Sample Conc:\s*([\d.]+)", conc_field)
        if m_loc and m_id:
            wells_meta.append((m_loc.group(1), m_id.group(1),
                               m_conc.group(1) if m_conc else "?"))
        i += 2

    # 列头 → 传感器（A-P 宽版，覆盖 384 孔板；fit_KD 原为 A-H 窄版）
    col_headers = [h.strip() for h in rows[1] if h.strip()]
    sensor_labels: List[str] = []
    seen = set()
    for h in col_headers:
        m = re.match(r"t\d+([A-P]\d+)c\d+", h)
        if m and m.group(1) not in seen:
            sensor_labels.append(m.group(1))
            seen.add(m.group(1))

    col = 0
    sensor_map = []  # [label, time_col, resp_col] + (sid, conc)
    for label in sensor_labels:
        sensor_map.append([label, col, col + 1])
        col += 2
    for i, (loc, sid, conc) in enumerate(wells_meta):
        if i < len(sensor_map):
            sensor_map[i].extend([sid, conc])
    if len(wells_meta) != len(sensor_map):
        print(f"[bli] 警告: {len(wells_meta)} 条元数据 != {len(sensor_map)} 个传感器列，部分传感器可能未标定")

    # 数值行（空值 → NaN）
    n_cols = len(sensor_map) * 2
    data_rows = []
    for row in rows[5:]:
        nums = [float(v.strip()) if v.strip() else float("nan") for v in row]
        if len(nums) >= n_cols:
            data_rows.append(nums)
    if not data_rows:
        raise ValueError("CSV 无有效数值数据")
    cols = list(zip(*data_rows))

    curves: List[Curve] = []
    for entry in sensor_map:
        if len(entry) != 5:
            continue
        label, xc, yc, sid, conc = entry
        if sid == "?":
            continue
        try:
            conc_val = float(conc)
        except (TypeError, ValueError):
            conc_val = 0.0
        curves.append(Curve(
            label=label, sample_id=sid, conc_nM=conc_val,
            time=np.asarray(cols[xc], dtype=float),
            response=np.asarray(cols[yc], dtype=float),
        ))
    return curves


def group_by_sample(curves: List[Curve]) -> Dict[str, List[Curve]]:
    """按 Sample ID 分组，组内浓度降序（最高浓度在前，用作相界参考）。"""
    groups: Dict[str, List[Curve]] = {}
    for c in curves:
        groups.setdefault(c.sample_id, []).append(c)
    for sid in groups:
        groups[sid].sort(key=lambda c: c.conc_nM, reverse=True)
    return groups


# ═══════════════════════════════════════════════════════════
#  传感器图生成
# ═══════════════════════════════════════════════════════════

def fit_1to1_per_curve(t, y, t_assoc, t_dissoc) -> dict:
    """单曲线逐相 1:1 拟合：结合相 Req(1-e^{-kobs·t})，解离相 R0·e^{-koff·t}。

    返回 kobs / koff / Req / R0 / 两相 R²；拟合失败时回退合理初值。
    """
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    result: Dict[str, float] = {}

    mask_a = (t >= t_assoc) & (t <= t_dissoc)
    t_a = t[mask_a] - t_assoc
    y_a = y[mask_a] - y[mask_a][0]
    try:
        popt_a, _ = curve_fit(
            lambda ta, Req, kobs: Req * (1 - np.exp(-kobs * ta)),
            t_a, y_a,
            p0=[np.max(y_a), 0.01],
            bounds=([0, 1e-5], [20, 0.5]),
            maxfev=10000,
        )
        result["Req"], result["kobs"] = popt_a[0], popt_a[1]
        y_pred = popt_a[0] * (1 - np.exp(-popt_a[1] * t_a))
        result["assoc_r2"] = _r2_score(y_a, y_pred)
    except Exception:
        result["Req"], result["kobs"] = np.max(y_a), 0.01
        result["assoc_r2"] = 0.0

    mask_d = t >= t_dissoc
    t_d = t[mask_d] - t_dissoc
    y_d = y[mask_d]
    try:
        popt_d, _ = curve_fit(
            lambda td, R0, koff: R0 * np.exp(-koff * td),
            t_d, y_d,
            p0=[max(y_d[0], 0.001), 1e-3],
            bounds=([0, 1e-7], [10, 0.1]),
            maxfev=10000,
        )
        result["R0"], result["koff"] = popt_d[0], popt_d[1]
        y_pred = popt_d[0] * np.exp(-popt_d[1] * t_d)
        result["dissoc_r2"] = _r2_score(y_d, y_pred)
    except Exception:
        result["R0"], result["koff"] = y_d[0], 1e-3
        result["dissoc_r2"] = 0.0
    return result


def _generate_fitted_curve(t, t_assoc, t_dissoc, fit_result) -> np.ndarray:
    """由单曲线拟合参数生成整条仿真曲线（传感器图虚线叠加用）。"""
    t = np.asarray(t, float)
    y_fit = np.zeros_like(t)
    Req, kobs, koff = fit_result["Req"], fit_result["kobs"], fit_result["koff"]
    mask_a = (t >= t_assoc) & (t <= t_dissoc)
    mask_d = t > t_dissoc
    y_fit[mask_a] = Req * (1 - np.exp(-kobs * (t[mask_a] - t_assoc)))
    r_d = Req * (1 - np.exp(-kobs * (t_dissoc - t_assoc)))  # 解离起始响应
    y_fit[mask_d] = r_d * np.exp(-koff * (t[mask_d] - t_dissoc))
    return y_fit


def generate_sensorgram_png(curves: List[Curve], *,
                            smooth_window: int = 31, baseline_n: int = 0,
                            fit: bool = False, t_assoc: Optional[float] = None,
                            t_dissoc: Optional[float] = None,
                            separate: bool = False, dpi: int = 300,
                            mask: Tuple[str, ...] = (), view: Tuple[str, ...] = (),
                            ) -> bytes | Dict[str, bytes]:
    """生成传感器图 PNG。默认全部 sample 并排一个图；separate=True 返回 {sample_id: PNG bytes}。

    smooth_window: Savitzky-Golay 窗长（自动补奇数，0 关闭）
    baseline_n:   前 N 点均值归零（ForteBio 已对齐，默认关）
    fit:          叠加逐曲线 1:1 拟合虚线（t_assoc/t_dissoc 缺省自动检测）
    """
    from fonts import setup_matplotlib_cjk
    setup_matplotlib_cjk()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if smooth_window and smooth_window % 2 == 0:
        smooth_window += 1

    groups = group_by_sample(curves)
    mask_ids = {s.strip().lower() for s in mask if s.strip()}
    view_ids = {s.strip().lower() for s in view if s.strip()}
    if mask_ids:
        groups = {k: v for k, v in groups.items() if k.lower() not in mask_ids}
    if view_ids:
        groups = {k: v for k, v in groups.items() if k.lower() in view_ids}
    if not groups:
        raise ValueError("过滤后无样本组可绘制")

    def plot_smooth(ax, x, y, **kw):
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        nan = ~np.isnan(y)
        xc, yc = x[nan], y[nan]
        if baseline_n > 0 and len(yc) > baseline_n:
            yc = yc - np.mean(yc[:baseline_n])
        if smooth_window > 3 and len(yc) > smooth_window:
            ax.plot(xc, savgol_filter(yc, smooth_window, polyorder=3), **kw)
        else:
            ax.plot(xc, yc, **kw)

    def make_plot(ax, s_curves, sid):
        for i, c in enumerate(s_curves):
            color = COLORS[i % len(COLORS)]
            plot_smooth(ax, c.time, c.response, color=color, linewidth=2.5,
                        alpha=0.92, label=f"{c.conc_nM:g} nM")
        if fit:
            ta, td = t_assoc, t_dissoc
            if ta is None or td is None:
                a, d = _detect_phases(s_curves)
                ta = ta if ta is not None else a
                td = td if td is not None else d
            for i, c in enumerate(s_curves):
                color = COLORS[i % len(COLORS)]
                fr = fit_1to1_per_curve(c.time, c.response, ta, td)
                y_fit = _generate_fitted_curve(c.time, ta, td, fr)
                ax.plot(c.time, y_fit, color=color, linestyle="--", linewidth=2.0, alpha=0.75)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Response (nm)")
        ax.set_title(sid, fontweight="bold", loc="center")
        ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", title="Concentration",
                  frameon=True, fancybox=True, edgecolor="#cccccc")
        ax.grid(True, alpha=0.15, linestyle="-")

    def render(fig):
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    with plt.rc_context(PLOT_STYLE):
        if separate:
            out = {}
            for sid, s_curves in groups.items():
                fig, ax = plt.subplots(figsize=(9, 6))
                make_plot(ax, s_curves, sid)
                out[sid] = render(fig)
            return out

        n = len(groups)
        fig, axes = plt.subplots(1, n, figsize=(8 * n, 7))
        if n == 1:
            axes = [axes]
        for ax, (sid, s_curves) in zip(axes, groups.items()):
            make_plot(ax, s_curves, sid)
        fig.tight_layout()
        return render(fig)


# ═══════════════════════════════════════════════════════════
#  KD 拟合内核（1:1 Langmuir，5 种方法）
#  ═══════════════════════════════════════════════════════════

def _r2_score(y_true, y_pred) -> float:
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 1 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0


def _p(verbose: bool, *args) -> None:
    if verbose:
        print(*args)


def _simulate_1to1(t, kon, koff, rmax, conc, t_assoc, t_dissoc) -> np.ndarray:
    """整条 1:1 Langmuir 仿真曲线（全局拟合的预测函数）。"""
    t = np.asarray(t, float)
    kobs = kon * conc + koff
    kd_val = koff / kon if kon > 0 else 1e12
    req = rmax * conc / (kd_val + conc)
    r_d = req * (1.0 - np.exp(-kobs * (t_dissoc - t_assoc)))
    y = np.zeros_like(t)
    mask_a = (t >= t_assoc) & (t <= t_dissoc)
    mask_d = t > t_dissoc
    y[mask_a] = req * (1.0 - np.exp(-kobs * (t[mask_a] - t_assoc)))
    y[mask_d] = r_d * np.exp(-koff * (t[mask_d] - t_dissoc))
    return y


def fit_standard(t_list, y_list, conc_list, t_assoc, t_dissoc, verbose=False):
    """kobs vs [L] 线性回归（文献标准法）：逐曲线解离→koff(中位)，逐曲线结合→kobs，KD=koff/slope。"""
    koff_vals = []
    for t, y, conc in zip(t_list, y_list, conc_list):
        mask_d = t >= t_dissoc
        t_d = t[mask_d] - t_dissoc
        y_d = y[mask_d]
        if len(y_d) < 5:
            continue
        try:
            popt, _ = curve_fit(lambda td, R0, koff: R0 * np.exp(-koff * td),
                                t_d, y_d, p0=[max(y_d[0], 0.001), 1e-3],
                                bounds=([0, 1e-7], [10, 0.1]), maxfev=10000)
            koff_vals.append(popt[1])
        except Exception as e:
            _p(verbose, f"  {conc:7.1f} nM dissoc 拟合失败: {e}")
    if not koff_vals:
        return None
    koff_med = float(np.median(koff_vals))

    kobs_list, conc_for_kobs = [], []
    for t, y, conc in zip(t_list, y_list, conc_list):
        mask_a = (t >= t_assoc) & (t <= t_dissoc)
        t_a = t[mask_a] - t_assoc
        y_a = y[mask_a] - y[mask_a][0]
        if len(y_a) < 5:
            continue
        try:
            popt, _ = curve_fit(lambda ta, Req, kobs: Req * (1 - np.exp(-kobs * ta)),
                                t_a, y_a, p0=[y_a[-1], 0.01],
                                bounds=([0, 1e-5], [10, 0.5]), maxfev=10000)
            kobs_list.append(popt[1])
            conc_for_kobs.append(conc)
        except Exception:
            pass
    if len(kobs_list) < 2:
        return None

    conc_arr = np.array(conc_for_kobs)
    kobs_arr = np.array(kobs_list)
    slope, intercept = np.polyfit(conc_arr, kobs_arr, 1)
    kd = koff_med / slope if slope > 0 else float("inf")
    return {"kon": slope, "koff": koff_med, "kd": kd,
            "r2": _r2_score(kobs_arr, slope * conc_arr + intercept)}


def fit_split(t_list, y_list, conc_list, t_assoc, t_dissoc, verbose=False):
    """全局解离→koff；固定 koff 全局结合→kon/Rmax。"""
    def diss_residuals(koff_arr):
        koff = float(koff_arr[0])
        chunks = []
        for t, y, _ in zip(t_list, y_list, conc_list):
            mask_d = t >= t_dissoc
            td = t[mask_d] - t_dissoc
            yd = y[mask_d]
            if len(td) < 5:
                continue
            chunks.append(yd - yd[0] * np.exp(-koff * td))
        return np.concatenate(chunks) if chunks else np.zeros(1)

    fit_d = least_squares(diss_residuals, x0=np.array([1e-3]),
                          bounds=([1e-7], [0.1]), loss="soft_l1", max_nfev=10000)
    if not fit_d.success:
        _p(verbose, "  ⚠ 解离相全局拟合可能未收敛")
    koff = float(fit_d.x[0])

    max_sig = max(float(np.max(y[(t >= t_assoc) & (t <= t_dissoc)]))
                  for t, y, _ in zip(t_list, y_list, conc_list))

    def assoc_residuals(par):
        kon, rmax = float(par[0]), float(par[1])
        chunks = []
        for t, y, conc in zip(t_list, y_list, conc_list):
            mask_a = (t >= t_assoc) & (t <= t_dissoc)
            ta = t[mask_a] - t_assoc
            ya = y[mask_a] - y[mask_a][0]
            if len(ta) < 5:
                continue
            kobs = kon * conc + koff
            frac = (kon * conc) / kobs if kobs > 1e-15 else 0.0
            chunks.append(ya - rmax * frac * (1.0 - np.exp(-kobs * ta)))
        return np.concatenate(chunks) if chunks else np.zeros(1)

    fit_a = least_squares(assoc_residuals, x0=np.array([1e-4, max_sig]),
                          bounds=([1e-8, 0.01], [1.0, 20.0]),
                          loss="soft_l1", max_nfev=30000)
    if not fit_a.success:
        _p(verbose, "  ⚠ 结合相全局拟合可能未收敛")
    kon, rmax = float(fit_a.x[0]), float(fit_a.x[1])
    kd = koff / kon if kon > 0 else float("inf")
    return {"kon": kon, "koff": koff, "kd": kd, "rmax": rmax}


def fit_joint(t_list, y_list, conc_list, t_assoc, t_dissoc, verbose=False):
    """关联+解离全曲线全局拟合：共享 kon/koff/Rmax。"""
    max_sig = max(float(np.max(y[(t >= t_assoc) & (t <= t_dissoc)]))
                  for t, y, _ in zip(t_list, y_list, conc_list))

    def joint_residuals(par):
        kon, koff, rmax = float(par[0]), float(par[1]), float(par[2])
        chunks = []
        for t, y, conc in zip(t_list, y_list, conc_list):
            chunks.append(y - _simulate_1to1(t, kon, koff, rmax, conc, t_assoc, t_dissoc))
        return np.concatenate(chunks) if chunks else np.zeros(1)

    fit = least_squares(joint_residuals, x0=np.array([1e-4, 1e-3, max_sig]),
                        bounds=([1e-8, 1e-7, 0.01], [1.0, 0.1, 20.0]),
                        loss="soft_l1", max_nfev=30000)
    if not fit.success:
        _p(verbose, "  ⚠ 联合全局拟合可能未收敛")
    kon, koff, rmax = float(fit.x[0]), float(fit.x[1]), float(fit.x[2])
    kd = koff / kon if kon > 0 else float("inf")
    return {"kon": kon, "koff": koff, "kd": kd, "rmax": rmax}


def fit_steady(t_list, y_list, conc_list, t_assoc, t_dissoc, verbose=False):
    """稳态等温线：解离前 2 s 均值 Req vs [L]，拟合 R=Rmax·C/(KD+C)。"""
    req_vals, req_concs = [], []
    for t, y, conc in zip(t_list, y_list, conc_list):
        mask_end = (t >= t_dissoc - 2) & (t <= t_dissoc)
        if np.sum(mask_end) < 2:
            mask_end = (t >= t_dissoc - 0.5) & (t <= t_dissoc)
        req_vals.append(np.mean(y[mask_end]))
        req_concs.append(conc)
    if len(req_concs) < 2:
        return None
    try:
        popt, _ = curve_fit(lambda c, Rmax, KD: Rmax * c / (KD + c),
                            np.array(req_concs), np.array(req_vals),
                            p0=[np.max(req_vals), np.median(req_concs)],
                            bounds=([0, 1e-9], [20, 1e6]), maxfev=20000)
        rmax, kd = popt[0], popt[1]
        pred = rmax * np.array(req_concs) / (kd + np.array(req_concs))
        return {"rmax": rmax, "kd": kd, "r2": _r2_score(np.array(req_vals), pred)}
    except Exception:
        return None


def fit_mixed(t_list, y_list, conc_list, t_assoc, t_dissoc, verbose=False):
    """特异(1:1) + 非特异线性模型。稳态：Req=Rmax·C/(KD+C)+ns·C；动力学：NS 同 koff 衰减。"""
    req_vals, req_concs = [], []
    for t, y, conc in zip(t_list, y_list, conc_list):
        mask_end = (t >= t_dissoc - 2) & (t <= t_dissoc)
        if np.sum(mask_end) < 2:
            mask_end = (t >= t_dissoc - 0.5) & (t <= t_dissoc)
        req_vals.append(np.mean(y[mask_end]))
        req_concs.append(conc)

    def mixed_isotherm_3p(c, Rmax, KD, ns_slope):
        return Rmax * c / (KD + c) + ns_slope * c

    kd_ss, ns_slope = None, None
    if len(req_concs) >= 3:
        try:
            max_req = np.max(req_vals)
            popt_ss, _ = curve_fit(mixed_isotherm_3p, np.array(req_concs), np.array(req_vals),
                                   p0=[max_req, np.median(req_concs), 0.0],
                                   bounds=([0, 1e-9, 0], [max(max_req * 2, 0.5), 1e6, 0.002]),
                                   maxfev=20000)
            _, kd_ss, ns_slope = popt_ss
        except Exception as e:
            _p(verbose, f"  steady-state mixed 拟合失败: {e}")

    max_sig = max(float(np.max(y[(t >= t_assoc) & (t <= t_dissoc)]))
                  for t, y, _ in zip(t_list, y_list, conc_list))

    def simulate_mixed_v2(t, kon, koff, rmax, ns_scale, conc):
        y_spec = _simulate_1to1(t, kon, koff, rmax, conc, t_assoc, t_dissoc)
        y_ns = np.zeros_like(t)
        ns_amp = ns_scale * conc
        mask_a = t >= t_assoc
        y_ns[mask_a] = ns_amp
        mask_d = t > t_dissoc
        dt_d = t[mask_d] - t_dissoc
        y_ns[mask_d] = ns_amp * np.exp(-koff * dt_d)
        return y_spec + y_ns

    def mixed_residuals_v2(par):
        kon, koff, rmax, ns_scale = [float(x) for x in par]
        chunks = []
        for t, y, conc in zip(t_list, y_list, conc_list):
            chunks.append(y - simulate_mixed_v2(t, kon, koff, rmax, ns_scale, conc))
        return np.concatenate(chunks) if chunks else np.zeros(1)

    kd_m, ns_scale_kin = None, None
    try:
        fit_m = least_squares(mixed_residuals_v2, x0=np.array([1e-4, 1e-3, max_sig, 0.0]),
                              bounds=([1e-8, 1e-7, 0.01, 0], [1.0, 0.1, max_sig * 2, 0.002]),
                              loss="soft_l1", max_nfev=30000)
        kon_m, koff_m, _, ns_scale_kin = fit_m.x
        kd_m = koff_m / kon_m if kon_m > 0 else None
    except Exception as e:
        _p(verbose, f"  kinetic mixed 拟合失败: {e}")

    return {"kd_steady_mixed": kd_ss, "ns_slope_steady": ns_slope,
            "kd_kinetic_mixed": kd_m, "ns_scale_kinetic": ns_scale_kin}


def filter_dead_curves(t_list, y_list, conc_list, t_dissoc, cutoff=None):
    """按解离前 Req 过滤死曲线。cutoff 缺省 = 3× 最低 1/3 曲线的 Req 噪声。"""
    req_vals = []
    for t, y in zip(t_list, y_list):
        mask = (t >= t_dissoc - 1) & (t <= t_dissoc)
        req_vals.append(np.mean(y[mask]) if np.sum(mask) > 0 else 0)
    if cutoff is None:
        n_floor = max(2, len(req_vals) // 3)
        floor_idxs = np.argsort(req_vals)[:n_floor]
        noise = np.std([req_vals[i] for i in floor_idxs])
        if noise < 1e-6:
            noise = 0.001
        cutoff = 3 * noise
    keep = [(t, y, c) for t, y, c, req in zip(t_list, y_list, conc_list, req_vals) if req >= cutoff]
    if not keep:
        return [], [], []
    return ([k[0] for k in keep], [k[1] for k in keep], [k[2] for k in keep])


def _detect_phases(curves: List[Curve]) -> Tuple[float, float]:
    """自动检测结合/解离相界（最高浓度曲线）。REF 脚本靠 CLI 显式传相界，
    这里做启发式兜底：t_dissoc 用平滑后「最后一个局部极大」——原始 argmax 对
    饱和平台噪声敏感（平台期响应平，噪声峰会被误判为解离起点）。
    """
    ref = max(curves, key=lambda c: c.conc_nM)
    m = ~np.isnan(ref.response)
    t_ref = np.asarray(ref.time, float)[m]
    y_ref = np.asarray(ref.response, float)[m]
    n_b = max(3, min(50, len(y_ref) // 4))
    if len(y_ref) > 40:
        y_s = savgol_filter(y_ref, 31, polyorder=3)
    else:
        y_s = y_ref
    # 结合起点：平滑曲线首超 基线+5σ（基线取前 n_b 点）
    base = np.median(y_s[:n_b])
    noise = np.std(y_s[:n_b]) or 1e-3
    rising = np.flatnonzero(y_s > base + 5 * noise)
    t_assoc = float(t_ref[rising[0]]) if rising.size else float(t_ref[0])
    # 解离起点：最后一个局部极大（衰减段单调下降，无局部极大 → 落在平台肩部）
    local_max = [i for i in range(1, len(y_s) - 1)
                 if y_s[i] >= y_s[i - 1] and y_s[i] > y_s[i + 1]]
    idx_d = local_max[-1] if local_max else int(np.argmax(y_s))
    t_dissoc = max(float(t_ref[idx_d]), t_assoc + 1.0)
    return t_assoc, t_dissoc


def fit_kd(curves: List[Curve], *, t_assoc: Optional[float] = None,
           t_dissoc: Optional[float] = None, n_concs: int = 8,
           req_cutoff: Optional[float] = None, no_cutoff: bool = False,
           ns_sensor: Optional[str] = None, ns_subtract: str = "proportional",
           verbose: bool = False) -> dict:
    """对一个 Sample ID 的曲线组做 5 方法 KD 拟合。

    相界缺省自动检测（_detect_phases 启发式）；强一致数据建议显式传 t_assoc/t_dissoc
    （REF 脚本就是靠 CLI 参数传）。ns_sensor: 非特异对照传感器 label（如 "F8"），
    按浓度比例从样品曲线中扣除。返回 {"phase", "standard", "split", "joint", "steady", "mixed"}。
    """
    entries = sorted(curves, key=lambda c: c.conc_nM, reverse=True)[:n_concs]
    if not entries:
        return {"error": "无曲线数据"}

    t_all = [np.asarray(c.time, float) for c in entries]
    y_all = [np.asarray(c.response, float) for c in entries]
    conc_all = [c.conc_nM for c in entries]

    # 相界：缺省时启发式检测
    if t_assoc is None or t_dissoc is None:
        a, d = _detect_phases(entries)
        t_assoc = t_assoc if t_assoc is not None else a
        t_dissoc = t_dissoc if t_dissoc is not None else d

    # NS 非特异扣除（按 sensor label 匹配，浓度比例缩放）
    if ns_sensor and ns_subtract != "none":
        ns = next((c for c in entries if c.label == ns_sensor), None)
        if ns is not None:
            ns_t = np.asarray(ns.time, float)
            ns_y = np.asarray(ns.response, float)
            max_conc = max(conc_all)
            for i in range(len(y_all)):
                frac = conc_all[i] / max_conc if max_conc > 0 else 1.0
                y_all[i] = y_all[i] - np.interp(t_all[i], ns_t, ns_y) * frac

    # 死曲线过滤
    if not no_cutoff:
        t_all, y_all, conc_all = filter_dead_curves(t_all, y_all, conc_all, t_dissoc, req_cutoff)
    if len(t_all) < 2:
        return {"phase": {"t_assoc": t_assoc, "t_dissoc": t_dissoc}, "error": "有效曲线不足 2 条"}

    results = {
        "standard": fit_standard(t_all, y_all, conc_all, t_assoc, t_dissoc, verbose),
        "split": fit_split(t_all, y_all, conc_all, t_assoc, t_dissoc, verbose),
        "joint": fit_joint(t_all, y_all, conc_all, t_assoc, t_dissoc, verbose),
        "steady": fit_steady(t_all, y_all, conc_all, t_assoc, t_dissoc, verbose),
        "mixed": fit_mixed(t_all, y_all, conc_all, t_assoc, t_dissoc, verbose),
    }
    results["phase"] = {"t_assoc": t_assoc, "t_dissoc": t_dissoc}
    return results


# ═══════════════════════════════════════════════════════════
#  CLI（保留直接跑 CSV 的能力）
# ═══════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="ForteBio CSV → 传感器图 / KD 拟合")
    parser.add_argument("csv", help="ForteBio 预处理 CSV 路径")
    parser.add_argument("-o", "--out", default=None, help="输出 PNG 路径（默认 csv 同名）")
    parser.add_argument("-s", "--smooth-window", type=int, default=31, help="SG 平滑窗（奇数，0 关闭）")
    parser.add_argument("--fit", action="store_true", help="叠加 1:1 拟合虚线")
    parser.add_argument("--kd", action="store_true", help="输出各 sample 的 5 方法 KD")
    parser.add_argument("--sample", default=None, help="只处理指定 Sample ID")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    curves = parse_fortebio_csv(args.csv)
    if args.sample:
        curves = [c for c in curves if c.sample_id == args.sample]
    if not curves:
        print("无曲线数据")
        return

    if args.kd:
        for sid, s_curves in group_by_sample(curves).items():
            r = fit_kd(s_curves, verbose=args.verbose)
            print(f"\n{sid}:")
            for method, res in r.items():
                if method == "phase":
                    print(f"  phase assoc→dissoc: {res['t_assoc']:.1f}→{res['t_dissoc']:.1f} s")
                elif res:
                    kd = res.get("kd")
                    if kd is not None:
                        print(f"  {method:8s} KD = {kd:8.1f} nM  kon={res.get('kon', float('nan')):.3e} koff={res.get('koff', float('nan')):.3e}")
                    else:
                        print(f"  {method:8s} (稳态/混合) kd={res.get('kd_steady_mixed') or res.get('kd_kinetic_mixed') or '—'}")
    else:
        png = generate_sensorgram_png(curves, smooth_window=args.smooth_window,
                                      fit=args.fit, separate=bool(args.sample))
        if isinstance(png, dict):
            for sid, data in png.items():
                path = f"{args.sample}_{sid}.png"
                with open(path, "wb") as f:
                    f.write(data)
                print(f"Saved {path}")
        else:
            out = args.out or args.csv.rsplit(".", 1)[0] + ".png"
            with open(out, "wb") as f:
                f.write(png)
            print(f"Saved {out}")


if __name__ == "__main__":
    main()
