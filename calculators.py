"""
蛋白质计算核心：MW、消光系数（Biopython ProtParam）、浓度、BLI 稀释规划
"""
from dataclasses import dataclass
from typing import List

from Bio.SeqUtils.ProtParam import ProteinAnalysis


def sanitize_seq(sequence: str) -> str:
    """清洗序列：去换行/空格/终止符/非氨基酸字符"""
    import re
    seq = sequence.upper()
    seq = re.sub(r'\s+', '', seq)
    seq = seq.replace('*', '')
    seq = re.sub(r'[^ACDEFGHIKLMNPQRSTVWY]', '', seq)
    return seq


def calc_mw(sequence: str) -> float:
    """蛋白质分子量 (Da) — 使用 Biopython ProtParam"""
    return ProteinAnalysis(sanitize_seq(sequence)).molecular_weight()


def calc_ext_coeff(sequence: str) -> dict:
    """计算还原态和氧化态消光系数 — 使用 Biopython ProtParam (Pace et al. 1995)"""
    seq = sanitize_seq(sequence)
    pa = ProteinAnalysis(seq)
    ext_red, ext_ox = pa.molar_extinction_coefficient()  # → (reduced, oxidized)
    mw = pa.molecular_weight()
    nW = seq.count("W")
    nY = seq.count("Y")
    nC = seq.count("C")
    abs_0_1pct = ext_ox / mw if mw > 0 else 0
    return {
        "mw": round(mw, 1),
        "nW": nW, "nY": nY, "nC": nC,
        "ext_red": round(ext_red, 0),
        "ext_ox": round(ext_ox, 0),
        "abs_0_1pct": round(abs_0_1pct, 4),
    }


def calc_conc(a280: float, ext_coeff: float, mw: float,
              path_length: float = 1.0) -> dict:
    """Beer-Lambert: A = ε·c·l → c"""
    if ext_coeff <= 0:
        raise ValueError("消光系数为 0，无法用 A280 定量（序列不含 W/Y/C）")
    if path_length <= 0:
        raise ValueError(f"光程必须 > 0，当前值: {path_length} cm")
    if a280 < 0:
        raise ValueError(f"A280 不能为负数，当前值: {a280}")
    molar_M = a280 / (ext_coeff * path_length)
    return {
        "a280": a280,
        "path_length_cm": path_length,
        "epsilon": ext_coeff,
        "mw": mw,
        "molar_conc_uM": round(molar_M * 1e6, 2),
        "mass_conc_mg_mL": round(molar_M * mw, 4),
        "mass_conc_ug_mL": round(molar_M * mw * 1000, 2),
    }


@dataclass
class DilutionStep:
    step: int
    conc_uM: float
    stock_vol_uL: float
    buffer_vol_uL: float
    total_vol_uL: float


def calc_dilution_series(stock_conc_uM: float, start_conc_uM: float,
                         dilution_factor: float, n_steps: int,
                         vol_per_well_uL: float,
                         extra_dead_vol_uL: float = 0.0) -> List[DilutionStep]:
    """
    BLI 梯度稀释规划 — 连续递推稀释

    每个步骤需要足够体积来：(a) 取 vol_per_well_uL 到孔中 +
    (b) 留足下一步稀释所需的母液 + (c) 死体积裕量。

    从最后一步向前递推：第 i 步总体积 = 孔体积 + 第 i+1 步总体积/稀释倍数 + 死体积。
    递推后每步总体积向上取整到 5 μL 倍数，保证移液量尽量整洁。

    Parameters
    ----------
    stock_conc_uM : 母液浓度 (μM)
    start_conc_uM : 起始最高浓度 (μM), 必须 ≤ stock_conc_uM
    dilution_factor : 稀释倍数 (如 2 表示 2 倍稀释)
    n_steps : 梯度步数
    vol_per_well_uL : 每孔所需体积 (μL)
    extra_dead_vol_uL : 额外死体积 (μL), 用于保证移液准确

    Returns
    -------
    list of DilutionStep
    """
    if stock_conc_uM <= 0:
        raise ValueError(f"母液浓度必须 > 0，当前值: {stock_conc_uM} μM")
    if start_conc_uM <= 0:
        raise ValueError(f"起始浓度必须 > 0，当前值: {start_conc_uM} μM")
    if start_conc_uM > stock_conc_uM:
        raise ValueError(
            f"起始浓度 ({start_conc_uM} μM) 不能超过母液浓度 ({stock_conc_uM} μM)")
    if dilution_factor <= 1:
        raise ValueError(f"稀释倍数必须 > 1，当前值: {dilution_factor}")
    if n_steps < 1:
        raise ValueError(f"梯度步数必须 ≥ 1，当前值: {n_steps}")
    if vol_per_well_uL <= 0:
        raise ValueError(f"每孔体积必须 > 0，当前值: {vol_per_well_uL} μL")

    # 从后向前递推，计算第 0 步所需最大体积
    import math
    total_last = vol_per_well_uL + extra_dead_vol_uL
    total_cur = total_last
    for _ in range(n_steps - 1):
        total_cur = vol_per_well_uL + total_cur / dilution_factor + extra_dead_vol_uL
    # 向上取整到 100 μL，所有步骤统一体积
    uniform_total = math.ceil(total_cur / 100) * 100

    steps = []
    for i in range(n_steps):
        target_conc = start_conc_uM / (dilution_factor ** i)
        total_needed = uniform_total

        if i == 0:
            # 第一步: 直接从母液配制
            stock_vol = total_needed * target_conc / stock_conc_uM
            buffer_vol = total_needed - stock_vol
        else:
            # 后续步骤: 从上一步的剩余液中取 total_needed / factor
            stock_vol = total_needed / dilution_factor
            buffer_vol = total_needed - stock_vol

        steps.append(DilutionStep(
            step=i + 1,
            conc_uM=round(target_conc, 4),
            stock_vol_uL=round(stock_vol, 2),
            buffer_vol_uL=round(buffer_vol, 2),
            total_vol_uL=round(total_needed, 2),
        ))
    return steps
