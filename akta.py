"""
akta.py — AKTA Unicorn 导出 zip 解析 / 峰检测 / 峰图 / 峰表导出

纯计算，无 Flask 依赖（同 calculators.py / bli.py 定位）。用标准库
(zipfile + xml.etree + struct) 原生解析 Unicorn 导出包，不依赖 pycorn——
本环境装不上（pip 网络不通），格式按 pycorn 源码逻辑 + 真实样例 zip 验证实现。

数据格式（Unicorn 7.x 导出 .zip）：
  - 外层 zip：`Chrom.1.Xml`（通道元数据 + 事件）+ `Chrom.1_NN_True`（每条通道的曲线，嵌套 zip）
  - 嵌套 zip：非标准结构（EOCD 不在文件尾、带尾部填充），需 `rindex(EOCD)+22` 截断才能被 zipfile 读取
  - 嵌套 zip 内 `CoordinateData.Volumes` / `CoordinateData.Amplitudes`：.NET 序列化 float32 数组，
    数据从偏移 47 起、每 4 字节一个 float32（pycorn unpacker 逻辑）
  - 通道元数据：`<Curves><Curve><Name>/<AmplitudeUnit>/<CurveDataType>/<CurvePoints>` 等
  - 事件（Fraction / Injection / Logbook）：`<EventCurves><EventCurve><Events><Event Volume/Text>`

分析版本契约：保存实验时 results 带 AKTA_ANALYSIS_VERSION；experiment_raw 落
data_type="akta_traces" 原始曲线快照（只写一次）。
"""

import io
import struct
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# AKTA 分析版本（随 v0.0.9 引入）：写入 results["AKTA_ANALYSIS_VERSION"]，
# 供未来 recompute 对照——同版本 + 同 raw 快照 → 可复现同结果（规则 #8）。
AKTA_ANALYSIS_VERSION = "0.0.9"

# 嵌套 zip 的魔数（pycorn 手动 zip 检测用）
_ZIP_MAGIC_START = b"\x50\x4B\x03\x04\x2D\x00\x00\x00\x08"
_ZIP_MAGIC_END = b"\x50\x4B\x05\x06\x00\x00\x00\x00"
_DATA_OFFSET = 47          # float32 数据起始偏移
_DATA_TAIL = 48            # 尾部跳过字节


# ═══════════════════════════════════════════════════════════
#  数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class Channel:
    """单条 AKTA 通道（如 UV 1_280）。vols/amps 等长，vol 单调递增。"""
    name: str
    data_type: str = "Other"
    unit: str = ""
    vols: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    amps: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))

    def n_points(self) -> int:
        return len(self.vols)

    def to_dict(self, full: bool = False) -> dict:
        d = {"name": self.name, "data_type": self.data_type, "unit": self.unit,
             "n_points": self.n_points()}
        if full:
            d["vols"] = [float(x) for x in self.vols]
            d["amps"] = [float(x) for x in self.amps]
        return d


@dataclass
class Peak:
    """色谱峰。面积 = ∫(amp - baseline) dv，用梯形积分。"""
    apex_vol: float
    apex_amp: float
    start_vol: float
    end_vol: float
    height: float          # 峰高 = apex_amp - baseline
    area: float            # mAU·mL（baseline 上方积分）
    half_width: float      # 半高宽 (mL)

    def to_dict(self) -> dict:
        return {"apex_vol": round(self.apex_vol, 3), "apex_amp": round(self.apex_amp, 3),
                "start_vol": round(self.start_vol, 3), "end_vol": round(self.end_vol, 3),
                "height": round(self.height, 3), "area": round(self.area, 4),
                "half_width": round(self.half_width, 3)}


# ═══════════════════════════════════════════════════════════
#  zip 解析
# ═══════════════════════════════════════════════════════════

def _fix_nested_zip(raw: bytes) -> io.BytesIO:
    """嵌套 zip 修复：EOCD 不在文件尾（尾部有填充），截到 EOCD+22 让 zipfile 能读。"""
    f_end = raw.rindex(_ZIP_MAGIC_END) + 22
    return io.BytesIO(raw[:f_end])


def _unpack_curve(inp: bytes) -> List[float]:
    """.NET 序列化 float32 数组：偏移 47 起，每 4 字节一个 float32，跳过尾部 48 字节。"""
    read_size = len(inp) - _DATA_TAIL
    vals = []
    for i in range(_DATA_OFFSET, read_size, 4):
        vals.append(struct.unpack("<f", inp[i:i + 4])[0])
    return vals


def parse_akta_zip(path: str) -> dict:
    """解析 AKTA Unicorn 导出 zip → {"channels": {name: Channel}, "events": {name: [(vol, text)]}, "meta": {...}}。

    只挑有体积+幅度双数据、且能被标准库解码的通道；无法解码的（如无 Volume 数据的
    编辑副本）跳过并记入 meta["skipped"]。
    """
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        raw_by_name = {n: zf.read(n) for n in names}

    # 内层嵌套 zip（Chrom.N_MM_True）→ 解码出 vols/amps
    curve_files = {}
    for n, raw in raw_by_name.items():
        if "Chrom" in n and "Xml" not in n and raw[:9] == _ZIP_MAGIC_START:
            try:
                inner = zipfile.ZipFile(_fix_nested_zip(raw))
                curve_files[n] = {i: inner.read(i) for i in inner.namelist()}
            except Exception:
                pass  # 非标准/损坏的曲线块跳过

    # 通道元数据来自 Chrom.1.Xml
    xml_raw = raw_by_name.get("Chrom.1.Xml", b"")
    if not xml_raw:
        raise ValueError("zip 中未找到 Chrom.1.Xml（不是有效的 AKTA Unicorn 导出？）")

    import xml.etree.ElementTree as ET
    tree = ET.fromstring(xml_raw)

    channels: Dict[str, Channel] = {}
    skipped = []
    curves_el = tree.find("Curves")
    if curves_el is not None:
        for c in curves_el:
            name_el = c.find("Name")
            if name_el is None or not name_el.text:
                continue
            name = name_el.text
            d_type = c.attrib.get("CurveDataType", "Other")
            unit_el = c.find("AmplitudeUnit")
            unit = unit_el.text if unit_el is not None and unit_el.text else ""
            try:
                fname = c.find("CurvePoints")[0][1].text
            except (IndexError, TypeError, AttributeError):
                skipped.append(name)
                continue
            inner = curve_files.get(fname, {})
            vols_raw = inner.get("CoordinateData.Volumes", b"")
            amps_raw = inner.get("CoordinateData.Amplitudes", b"")
            if not vols_raw or not amps_raw:
                skipped.append(name)
                continue
            vols = np.asarray(_unpack_curve(vols_raw), dtype=float)
            amps = np.asarray(_unpack_curve(amps_raw), dtype=float)
            n = min(len(vols), len(amps))
            if n == 0:
                skipped.append(name)
                continue
            channels[name] = Channel(name=name, data_type=d_type, unit=unit,
                                     vols=vols[:n], amps=amps[:n])

    # 事件（Fraction / Injection / Logbook）
    events: Dict[str, List[Tuple[float, str]]] = {}
    events_el = tree.find("EventCurves")
    if events_el is not None:
        for e in events_el:
            name_el = e.find("Name")
            if name_el is None or not name_el.text:
                continue
            e_name = "Fraction" if name_el.text == "Fraction" else name_el.text
            evs = e.find("Events")
            if evs is None:
                continue
            e_data = []
            for ev in evs:
                vol_el = ev.find("EventVolume")
                txt_el = ev.find("EventText")
                if vol_el is None or vol_el.text is None:
                    continue
                try:
                    e_data.append((float(vol_el.text), (txt_el.text or "").strip()))
                except (TypeError, ValueError):
                    continue
            if e_data:
                events[e_name] = e_data

    # meta：版本 + 运行名（ChromatogramName）
    root_attrib = tree.attrib
    chrom_name_el = tree.find("ChromatogramName")
    meta = {
        "format_version": root_attrib.get("FormatVersion", ""),
        "unicorn_version": root_attrib.get("UNICORNVersion", ""),
        "run_name": chrom_name_el.text if chrom_name_el is not None and chrom_name_el.text else "",
        "skipped": skipped,
    }
    return {"channels": channels, "events": events, "meta": meta}


def find_uv_channels(channels: Dict[str, Channel]) -> List[str]:
    """UV 通道名（按 CurveDataType == 'UV'；按波长后缀 280/260/230 等排序，280 优先）。"""
    uv = [n for n, ch in channels.items() if ch.data_type == "UV"]
    # 波长后缀排序：_280 优先，其次 260/230，无后缀靠后
    def key(n: str):
        for i, wl in enumerate(("280", "260", "230")):
            if n.endswith(f"_{wl}"):
                return i
        return 10
    return sorted(uv, key=key)


def find_fraction_events(events: Dict[str, List[Tuple[float, str]]]) -> List[Tuple[float, str]]:
    return events.get("Fraction", [])


# ═══════════════════════════════════════════════════════════
#  峰检测
# ═══════════════════════════════════════════════════════════

def detect_peaks(channel: Channel, *, xmin: float = 0.0, xmax: Optional[float] = None,
                 min_height: float = 5.0, smooth_window: int = 11,
                 min_prominence: Optional[float] = None,
                 min_distance_ml: float = 0.5) -> List[Peak]:
    """在指定体积区间内检测色谱峰。

    - 先 SG 平滑（自动补奇数），基线取区间内 5% 分位数（近似平坦基线）
    - 峰定位用 scipy.signal.find_peaks：height 过滤绝对幅度，prominence 过滤
      噪声毛刺（对弱信号 UV 数据关键），distance 合并分裂峰（按 mL 折算点数）
    - 峰边界：自顶点向两侧走回基线交叉点；半高宽 = 半高处的体积跨度
    - 面积：顶点区间内 (amp - baseline) 的梯形积分
    """
    from scipy.signal import find_peaks

    vols = np.asarray(channel.vols, dtype=float)
    amps = np.asarray(channel.amps, dtype=float)
    if xmax is None:
        xmax = float(vols[-1]) if len(vols) else 0.0
    mask = (vols >= xmin) & (vols <= xmax)
    v, a = vols[mask], amps[mask]
    if len(v) < 5:
        return []

    y = _smooth(a, smooth_window)
    baseline = float(np.percentile(y, 5))
    if not np.isfinite(baseline):
        baseline = 0.0
    y_b = y - baseline  # 扣基线后的信号

    # distance：按体积间隔折算点数（避免相邻采样点噪声分裂同一峰）
    step = float(np.median(np.diff(v))) if len(v) > 1 else 1.0
    distance = max(1, int(round(min_distance_ml / step))) if step > 0 else 1
    prominence = min_prominence if min_prominence is not None else max(min_height * 0.5, 0.5)

    peaks_idx, _ = find_peaks(y_b, height=min_height, prominence=prominence, distance=distance)
    if len(peaks_idx) == 0:
        return []

    out = []
    for i in peaks_idx:
        apex_vol = float(v[i])
        apex_amp = float(a[i])
        height = float(y_b[i])
        # 峰边界：向两侧找信号回到基线（≤ baseline + 5% 峰高）的最远位置
        j_l = i
        while j_l > 0 and y_b[j_l] > 0.05 * height:
            j_l -= 1
        j_r = i
        while j_r < len(y_b) - 1 and y_b[j_r] > 0.05 * height:
            j_r += 1
        start_vol = float(v[j_l])
        end_vol = float(v[j_r])
        # 面积：梯形积分（np.trapezoid 为 numpy≥2.0 名，旧版为 np.trapz）
        seg = y_b[j_l:j_r + 1]
        x_seg = v[j_l:j_r + 1]
        if len(seg) > 1:
            trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz", None)
            area = float(trapz(seg, x_seg))
        else:
            area = 0.0
        # 半高宽
        half = 0.5 * height
        k_l = i
        while k_l > j_l and y_b[k_l] > half:
            k_l -= 1
        k_r = i
        while k_r < j_r and y_b[k_r] > half:
            k_r += 1
        half_width = float(v[k_r] - v[k_l])
        out.append(Peak(apex_vol=apex_vol, apex_amp=apex_amp,
                        start_vol=start_vol, end_vol=end_vol,
                        height=height, area=area, half_width=half_width))
    return out


def _smooth(y: np.ndarray, window: int) -> np.ndarray:
    """Savitzky-Golay 平滑（scipy C 实现；窗口自动补奇数，短序列原样返回）。

    早期版本是纯 numpy 逐点 lstsq（O(n) 次最小二乘），3 万点要 ~0.5s——
    同文件 detect_peaks 已在用 scipy，此处无规避依赖的必要，改为 scipy.savgol_filter
    提速 ~19 倍（BLI 侧 [bli.py] 同样用它）。
    """
    from scipy.signal import savgol_filter
    y = np.asarray(y, dtype=float)
    if window < 3 or len(y) < window:
        return y
    if window % 2 == 0:
        window += 1
    return savgol_filter(y, window, polyorder=min(3, window - 1))


# ═══════════════════════════════════════════════════════════
#  Fraction 区间解析（阴影高亮用）
# ═══════════════════════════════════════════════════════════

def fraction_ranges(events: Optional[List[Tuple[float, str]]], xmax: float = float("inf")
                    ) -> List[Tuple[float, float, str]]:
    """把 Fraction 事件 (vol, label) 转成收集区间列表 [(start, end, label), ...]。

    每个事件 = 一管的开始体积；区间 = [start, 下一事件 start)。最后一管延伸到 xmax。
    事件缺失 / 空列表 → 返回 []。
    """
    if not events:
        return []
    evs = sorted(events, key=lambda e: e[0])
    out = []
    for i, (vol, label) in enumerate(evs):
        end = evs[i + 1][0] if i + 1 < len(evs) else xmax
        out.append((float(vol), float(end), str(label).strip()))
    return out


def find_fraction_index(fractions: List[Tuple[float, float, str]], vol: float) -> Optional[int]:
    """返回包含体积 vol 的 frac 下标（区间 [start, end) 左闭右开）；无则 None。"""
    for i, (s, e, _) in enumerate(fractions):
        if s <= vol < e:
            return i
    return None


def target_fraction_span(fractions: List[Tuple[float, float, str]], apex_vol: float,
                         xmin: float = 0.0, xmax: Optional[float] = None
                         ) -> dict:
    """目标峰（顶点体积 apex_vol）自身 frac + 前后各 1 个 frac 的区间，用于矩形背景阴影。

    返回 {"self": (s,e), "prev": (s,e)|None, "next": (s,e)|None, "self_label": str}。
    区间已 clamp 到 [xmin, xmax]。无 fractions / 顶点不在任何 frac 内 → {"self": None, ...}。
    """
    if not fractions:
        return {"self": None, "prev": None, "next": None, "self_label": ""}
    idx = find_fraction_index(fractions, apex_vol)
    if idx is None:
        return {"self": None, "prev": None, "next": None, "self_label": ""}
    hi = xmax if xmax is not None else float("inf")

    def clamp(rng):
        s, e = rng
        return (max(s, xmin), min(e, hi))

    self_rng = clamp(fractions[idx][:2])
    prev_rng = clamp(fractions[idx - 1][:2]) if idx - 1 >= 0 else None
    next_rng = clamp(fractions[idx + 1][:2]) if idx + 1 < len(fractions) else None
    return {"self": self_rng, "prev": prev_rng, "next": next_rng,
            "self_label": fractions[idx][2]}


def span_bounds(span: dict) -> Optional[Tuple[float, float]]:
    """阴影连续矩形的起止：合并 self + 前后 frac 的总跨度 [prev.start, next.end]。
    缺 prev/next 时回退 self 边界；无有效区间返回 None。"""
    if not span or not span.get("self"):
        return None
    s0, s1 = span["self"]
    if span.get("prev"):
        s0 = min(s0, span["prev"][0])
    if span.get("next"):
        s1 = max(s1, span["next"][1])
    return (s0, s1) if s0 < s1 else None


# ═══════════════════════════════════════════════════════════
#  绘图
# ═══════════════════════════════════════════════════════════

def _normalize_amps(amps, vols, xmin, xmax, normalize):
    """可选 min-max 归一化到 [0,1]（对齐 REF 脚本 --no-normalize 默认行为）。
    normalize=False → 原样返回。"""
    if not normalize:
        return amps
    mask = (vols >= xmin) & (vols <= xmax)
    seg = amps[mask]
    if len(seg) == 0:
        return amps
    lo, hi = float(np.min(seg)), float(np.max(seg))
    if hi - lo < 1e-12:
        return np.zeros_like(amps)
    return (amps - lo) / (hi - lo)


def _complement_color(color: str) -> str:
    """RGB 补色（255 - 各通道），供峰阴影与曲线形成对比。"""
    c = color.lstrip("#")
    if len(c) != 6:
        return color
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (255 - r, 255 - g, 255 - b)


def generate_akta_png(channel: Channel, peaks: List[Peak], *,
                      events: Optional[List[Tuple[float, str]]] = None,
                      xmin: float = 0.0, xmax: Optional[float] = None,
                      show_events: bool = False,      # frac 竖线（默认不显示，可切换）
                      highlight_frac: bool = True,    # 目标峰 frac 矩形阴影（默认开）
                      target_peak_idx: int = 0,       # 阴影跟随哪个峰（默认主峰/第一个）
                      peak_fill: bool = True,         # 每个检测峰峰下面积填充（默认开）
                      peak_labels: bool = False,      # 峰顶竖虚线 + P1 xx mL 标注（默认关）
                      smooth_window: int = 11,
                      normalize: bool = False,        # min-max 归一化到 [0,1]（区间内）
                      sample_name: str = "",          # 图例 smooth 条目名 + 图标题（默认 = 压缩包名）
                      dpi: int = 200) -> bytes:
    """生成峰图 PNG：UV 轨迹（平滑叠加）+ 基线 + 峰标注。

    - highlight_frac=True：目标峰自身 frac + 前后各 1 个 frac 画矩形背景阴影
      （中间深、两边浅；目标峰 = peaks[target_peak_idx]）
    - peak_fill=True：每个检测峰峰下面积背景填充
    - peak_labels=True：每个峰画峰顶竖虚线 + 「Px 峰位/高度」标注
    - show_events=True：画 Fraction 事件竖线（默认关闭）
    - normalize=True：区间内 min-max 归一化到 [0,1]（对齐 REF 脚本默认归一化行为）
    - sample_name：图例只保留 smooth 一条（raw 灰线为背景不占图例），
      条目名与图标题都用它；缺省回退通道名。
    """
    from fonts import setup_matplotlib_cjk
    setup_matplotlib_cjk()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from bli import COLORS, PLOT_STYLE

    name = (sample_name or "").strip() or channel.name or ""

    vols = np.asarray(channel.vols, dtype=float)
    amps = _normalize_amps(np.asarray(channel.amps, dtype=float), vols, xmin,
                           xmax if xmax is not None else float(vols[-1]) if len(vols) else 0,
                           normalize)
    if xmax is None:
        xmax = float(vols[-1]) if len(vols) else 0.0

    with plt.rc_context(PLOT_STYLE):
        fig, ax = plt.subplots(figsize=(10, 6))
        # 原始灰线：背景参考，不带 label（不进图例）
        ax.plot(vols, amps, color="#b0b0b0", linewidth=1.2, alpha=0.7)
        mask = (vols >= xmin) & (vols <= xmax)
        v, a = vols[mask], amps[mask]
        if len(v) > 3:
            ax.plot(v, _smooth(a, smooth_window), color=COLORS[0], linewidth=2.2,
                    label=name)

        # 目标峰 frac 矩形背景阴影（先画，避免盖住曲线）：
        # 一个连续矩形覆盖 self+前后各 1 个 frac 的总跨度，顶部标自身 frac 标签
        if highlight_frac and events:
            target_peak = peaks[target_peak_idx] if 0 <= target_peak_idx < len(peaks) else None
            span = target_fraction_span(fraction_ranges(events, xmax),
                                        target_peak.apex_vol if target_peak else xmin,
                                        xmin, xmax) if target_peak else {"self": None}
            bounds = span_bounds(span)
            if bounds:
                s0, s1 = bounds
                ax.axvspan(s0, s1, color="#4361ee", alpha=0.14, zorder=0)
                ax.text((s0 + s1) / 2, ax.get_ylim()[1] * 0.985,
                        f"frac {span['self_label']}", fontsize=9,
                        color="#4361ee", ha="center", va="top", fontweight="bold")

        # 基线
        if len(v) > 3:
            base = float(np.percentile(_smooth(a, smooth_window), 5))
            ax.axhline(base, color="#999999", linestyle=":", linewidth=1.2)
            ax.text(xmin + (xmax - xmin) * 0.01, base, f"baseline {base:.2f}",
                    fontsize=9, color="#777777", va="bottom")

        # Fraction 事件竖线（默认关，用户可开）
        if show_events and events:
            for vol, txt in events:
                if xmin <= vol <= xmax:
                    ax.axvline(vol, color="#5aae61", linestyle="--", linewidth=1.0, alpha=0.6)
                    ax.text(vol, ax.get_ylim()[1] * 0.97, txt, rotation=90,
                            fontsize=7, color="#3c763d", va="top", ha="right")

        # 峰标注：峰下面积填充（peak_fill，默认开）+ 峰顶竖虚线/标注（peak_labels，默认关）
        for idx, p in enumerate(peaks, 1):
            if peak_labels:
                ax.axvline(p.apex_vol, color=COLORS[1 % len(COLORS)], linestyle="--",
                           linewidth=1.0, alpha=0.7)
                ax.annotate(f"P{idx} {p.apex_vol:.2f} mL\n{p.height:.1f} mAU",
                            xy=(p.apex_vol, p.apex_amp), xytext=(8, 8),
                            textcoords="offset points", fontsize=9, color="#b2182b")
            if peak_fill:
                ax.fill_between(v, base, _smooth(a, smooth_window),
                                where=[(p.start_vol <= x <= p.end_vol) for x in v],
                                color=_complement_color(COLORS[0]), alpha=0.12)

        ax.set_xlim(xmin, xmax)
        ax.set_xlabel("Volume (mL)")
        ax.set_ylabel(f"Signal ({channel.unit})" if channel.unit else "Signal")
        # 图内不设标题（对齐 REF 原脚本无标题风格；身份由图例 + 前端卡片承担）
        ax.legend(loc="upper right", fontsize=9)
        ax.grid(True, alpha=0.15)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()


def generate_akta_overlay_png(channels: List[Channel], *,
                              events: Optional[List[Tuple[float, str]]] = None,
                              xmin: float = 0.0, xmax: Optional[float] = None,
                              show_events: bool = False,
                              smooth_window: int = 11,
                              normalize: bool = False,
                              labels: Optional[List[str]] = None,
                              frac_spans: Optional[List[dict]] = None,  # 每文件目标峰阴影三元组
                              title: str = "",
                              dpi: int = 200) -> bytes:
    """总图：把多个通道（通常来自不同 zip 的同名 UV 通道）的平滑曲线叠在一张图上。

    - 每个通道一条线，label 取 labels[i]（缺省用通道名），图例多条目
    - normalize=True：各通道各自区间内 min-max 归一化到 [0,1] 再叠加（可跨文件对比）
    - frac_spans：每文件一个 {"self": (s,e), "prev": (s,e)|None, "next": (s,e)|None}，
      用该文件曲线的颜色画矩形阴影（自身深、前后浅），方便在总图上直接看到每个
      目标峰收集在哪几管
    - 峰不单独标注（重叠后无法区分）；可选 frac 竖线（show_events）
    """
    from fonts import setup_matplotlib_cjk
    setup_matplotlib_cjk()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from bli import COLORS, PLOT_STYLE

    if not channels:
        raise ValueError("无通道可叠加")
    if xmax is None:
        xmax = max(float(np.max(c.vols)) if len(c.vols) else 0 for c in channels)

    with plt.rc_context(PLOT_STYLE):
        fig, ax = plt.subplots(figsize=(11, 6.5))

        # 目标峰 frac 阴影：先画（zorder=0），每文件一个连续矩形（self+前后 frac 总跨度），
        # 颜色跟随该文件曲线
        if frac_spans:
            for i, span in enumerate(frac_spans):
                bounds = span_bounds(span)
                if not bounds:
                    continue
                s0, s1 = bounds
                base = COLORS[i % len(COLORS)]
                ax.axvspan(s0, s1, color=base, alpha=0.15, zorder=0)

        for i, ch in enumerate(channels):
            vols = np.asarray(ch.vols, dtype=float)
            amps = _normalize_amps(np.asarray(ch.amps, dtype=float), vols, xmin, xmax, normalize)
            mask = (vols >= xmin) & (vols <= xmax)
            v, a = vols[mask], amps[mask]
            if len(v) < 2:
                continue
            lbl = (labels[i] if labels and i < len(labels) else "") or ch.name
            ax.plot(v, _smooth(a, smooth_window), color=COLORS[i % len(COLORS)],
                    linewidth=2.2, alpha=0.92, label=lbl)

        if show_events and events:
            for vol, txt in events:
                if xmin <= vol <= xmax:
                    ax.axvline(vol, color="#5aae61", linestyle="--", linewidth=1.0, alpha=0.6)

        ax.set_xlim(xmin, xmax)
        ax.set_xlabel("Volume (mL)")
        ax.set_ylabel("Signal (normalized)" if normalize else "Signal (mAU)")
        # 图内不设标题（对齐 REF 原脚本 overlay 无标题风格；身份由图例 + 前端卡片承担）
        ax.legend(loc="upper right", fontsize=9)
        ax.grid(True, alpha=0.15)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()


# ═══════════════════════════════════════════════════════════
#  导出
# ═══════════════════════════════════════════════════════════

def peaks_to_rows(peaks: List[Peak]) -> List[dict]:
    return [p.to_dict() for p in peaks]
