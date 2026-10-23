"""Excel 导出 — 实验归档与作图数据宽格式。

从 app.py 抽出（2026-10-22 维护轮）：这组函数是纯搬运/排版逻辑，被
实验归档导出、酶活/ BLI / AKTA 作图导出共用；放在独立模块便于单测与定位。
"""
import json
from io import BytesIO

from flask import send_file
from openpyxl import Workbook
from openpyxl.styles import Font

import models


def _enzyme_wide_columns(wells, prefix="") -> tuple[list, list]:
    """把每孔时间序列转成宽格式：每孔独立两列（时间 + OD），跨孔并列。
    返回 (headers, col_data)：headers 每孔一对 `{标签} 时间 (min)` / `{标签} OD`；
    标签优先样品名、缺省用孔位，撞名时退回孔位，prefix 用于多实验合并区分来源。
    col_data 为 [(times, ods), ...]，写入时每孔占两列、行按各自时间索引对齐（不足留空）。"""
    headers = []
    col_data = []
    if not isinstance(wells, dict):
        return headers, col_data
    seen = set()
    for wid, w in sorted(wells.items()):
        if not isinstance(w, dict):
            continue
        times = w.get("times") or []
        ods = w.get("od") or []
        if not times or not ods:
            continue
        lbl = (w.get("name") or "").strip() or wid
        full = f"{prefix}{lbl}"
        if full in seen:
            full = f"{prefix}{wid}"
        seen.add(full)
        headers += [f"{full} 时间 (min)", f"{full} OD"]
        col_data.append((times, ods))
    return headers, col_data


def _enzyme_raw_wells(e) -> dict:
    """取该实验**最新**原始快照里的全量孔位曲线（含 times/od），供归档导出宽格式。

    存档契约（见 CLAUDE.md「存档契约」）：逐点数据只在 experiment_raw，
    `experiments.params.wells` 只留元数据 + fit + od_range。归档导出要作图数据，
    必须读 raw。raw 只插不更 → 取最后一条即当前状态；`backfilled` 之前的旧快照
    形状可能无 wells 或仍是截断数据，此时回退 `params.wells`（历史实验保持现状）。
    读不到返回 {}（调用方回退）。"""
    try:
        raws = models.exp_raw_list(e.get("id")) or []
    except Exception:
        return {}
    for r in reversed(raws):
        if (r.get("data_type") or "") != "enzyme_traces":
            continue
        try:
            row = models.exp_raw_get(r["id"]) or {}
            payload = row.get("payload") or {}
        except Exception:
            continue
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                continue
        w = payload.get("wells") if isinstance(payload, dict) else None
        if isinstance(w, dict) and w:
            return w
    return {}


def _write_wide_ws(ws, headers, col_data):
    """把宽格式列对写入 worksheet：第 1 行表头加粗 + 固定列宽，数据每孔两列
    （时间 (min) + OD），各列对从第 2 行起按各自时间索引对齐（点数不同不足处留空）。"""
    from openpyxl.utils import get_column_letter
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        ws.cell(row=1, column=c).font = Font(bold=True)
        ws.column_dimensions[get_column_letter(c)].width = 15
    for ci, (times, ods) in enumerate(col_data):
        base = ci * 2 + 1
        for r, (t, od) in enumerate(zip(times, ods), 2):
            ws.cell(row=r, column=base).value = round(t / 60, 3)
            ws.cell(row=r, column=base + 1).value = round(od, 4) if od is not None else ""


def _write_wide_ws_pairs(ws, headers, col_data, fmt=None):
    """通用宽格式列对写入：第 1 行表头加粗 + 固定列宽 15，每单位两列从第 2 行起
    按各自索引对齐写入（点数不同不足处留空）。col_data 为 [(xs, ys), ...]；
    fmt: (x, y) -> (v1, v2) 数值转换，缺省原样 float。
    BLI/AKTA 作图数据用此写入器；酶活专用变换（时间 /60、OD 取 4 位）见 _write_wide_ws。"""
    from openpyxl.utils import get_column_letter
    if fmt is None:
        fmt = lambda x, y: (float(x), float(y))
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        ws.cell(row=1, column=c).font = Font(bold=True)
        ws.column_dimensions[get_column_letter(c)].width = 15
    for ci, (xs, ys) in enumerate(col_data):
        base = ci * 2 + 1
        for r, (x, y) in enumerate(zip(xs, ys), 2):
            v1, v2 = fmt(x, y)
            ws.cell(row=r, column=base).value = v1
            ws.cell(row=r, column=base + 1).value = v2


def export_excel(exps, download_name="实验记录.xlsx"):
    """共享导出逻辑 — exps 是已查询的实验列表。
    每个实验一个区块：实验名称/日期/类型 各占一行（不再作为表头列），下面接该类型的数据表头 + 数据行。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "实验记录"

    # 根据实验类型选择数据表头（实验名称/日期/类型 单独成行，不进表头）
    def _get_calc_type(e):
        p = e.get("params") or {}
        return p.get("calc_type", "") if isinstance(p, dict) else ""
    all_enzyme = exps and all(_get_calc_type(e) == "enzyme" for e in exps)
    enzyme_wide_groups = []  # (headers, col_data) 宽格式（每孔两列），全酶活导出时附加为作图 Sheet

    CONC_HEADERS = ["蛋白", "MW (Da)", "ε", "Abs 0.1%", "A280", "浓度 (μM)", "浓度 (mg/mL)",
                    "目标浓度 (μM)", "目标体积 (μL)", "取母液 (μL)", "加缓冲液 (μL)"]
    DIL_HEADERS = ["蛋白", "母液 (μM)", "稀释倍数", "每孔体积 (μL)", "步骤",
                   "浓度 (μM)", "总体积 (μL)", "取上步 (μL)", "加缓冲液 (μL)"]
    ENZ_HEADERS = ["孔位/命名", "参考类型", "浓度 (ng/mL)", "浓度 (μM)",
                   "ΔOD/min", "R²", "样本", "波长"]

    def _write_block(headers, rows):
        """写一块数据：表头行（加粗）+ 数据行。"""
        if not rows:
            return
        ws.append(headers)
        for c in range(1, len(headers) + 1):
            ws.cell(row=ws.max_row, column=c).font = Font(bold=True)
        for r in rows:
            ws.append(r)

    first_exp = True
    for e in exps:
        params = e.get("params") or {}
        results = e.get("results") or {}
        calc_type = params.get("calc_type", "")
        proteins = params.get("proteins", [])

        # 实验信息：每项独立一行（块与块之间空一行分隔）
        if not first_exp:
            ws.append([])
        first_exp = False
        meta = [("实验名称", e.get("title", "")), ("日期", e.get("date", "")),
                ("类型", e.get("exp_type", ""))]
        if e.get("notes"):
            meta.append(("备注", e["notes"]))
        for label, val in meta:
            ws.append([label, val])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

        if calc_type == "concentration" and proteins:
            rows = []
            for i, prot in enumerate(proteins):
                if not isinstance(prot, dict):
                    continue
                mw_val = prot.get("mw", "")
                eps_val = prot.get("epsilon", "")
                abs_val = prot.get("abs_0_1pct", "")
                # 新格式：全在 params.proteins 里；旧格式：浓度在 results 数组里
                conc_uM = prot.get("conc_uM", "")
                conc_mg = prot.get("conc_mg_mL", "")
                if (not conc_uM) and isinstance(results, list) and i < len(results):
                    r = results[i]
                    if isinstance(r, dict):
                        conc_uM = r.get("conc_uM", conc_uM)
                        conc_mg = r.get("conc_mg_mL", conc_mg)
                rows.append([
                    prot.get("name", ""),
                    f"{mw_val:.1f}" if isinstance(mw_val, (int, float)) and mw_val else mw_val,
                    f"{eps_val:.0f}" if isinstance(eps_val, (int, float)) and eps_val else eps_val,
                    f"{abs_val:.4f}" if isinstance(abs_val, (int, float)) and abs_val else abs_val,
                    prot.get("a280", ""), conc_uM, conc_mg,
                    prot.get("target_conc", ""), prot.get("target_vol", ""),
                    prot.get("take_vol", ""), prot.get("buffer_vol", ""),
                ])
            _write_block(CONC_HEADERS, rows)

        elif calc_type == "dilution":
            # BLI 稀释实验：每蛋白每步一行
            dil_proteins = params.get("proteins", [])
            rows = []
            for prot in dil_proteins:
                if not isinstance(prot, dict):
                    continue
                pid = str(prot.get("id", ""))
                prot_result = results.get(pid, {}) if isinstance(results, dict) else {}
                prot_steps = prot_result.get("steps", []) if isinstance(prot_result, dict) else []
                if not prot_steps:
                    # 旧格式兼容：results.steps 直接是列表
                    prot_steps = results.get("steps", results) if isinstance(results, dict) else (results if isinstance(results, list) else [])
                for st in prot_steps:
                    if not isinstance(st, dict):
                        continue
                    rows.append([
                        prot.get("name", ""), prot.get("stock_uM", ""), prot.get("factor", ""),
                        prot.get("vol", ""), st.get("step", ""), st.get("conc_uM", ""),
                        st.get("total_vol_uL", ""), st.get("stock_vol_uL", ""),
                        st.get("buffer_vol_uL", ""),
                    ])
            if rows:
                _write_block(DIL_HEADERS, rows)
            else:
                ws.append(["关联蛋白", e.get("protein_names", "")])

        elif calc_type == "enzyme":
            # 酶活实验：每孔一行
            wells = params.get("wells") or params.get("well_info") or {}
            emeta = params.get("meta", {})
            if wells:
                rows = []
                for wid, w in sorted(wells.items()):
                    if not isinstance(w, dict):
                        continue
                    fit = w.get("fit") or {}
                    ref_label = {"blank": "空白", "neg": "阴性", "pos": "阳性"}.get(w.get("ref", ""), "")
                    rows.append([
                        f"{wid} {w.get('name', '')}", ref_label,
                        w.get("conc_ng_ml", ""), w.get("conc_uM", ""),
                        fit.get("slope", ""), fit.get("r2", ""),
                        emeta.get("sample", ""), emeta.get("wavelength", ""),
                    ])
                _write_block(ENZ_HEADERS, rows)
                # 汇总 Sheet 的原始数据收进宽格式（每孔时间+OD 两列），多实验用标题前缀区分。
                # 逐点数据只在 experiment_raw（契约规则 A）→ 优先读 raw 全量。
                # raw 缺失时回退 params.wells：params 已按契约去逐点后这里只会得到**空列**，
                # 不会给出"被截断却看似完整"的错数据——失败方向是显式的，不是静默的。
                h2, cd2 = _enzyme_wide_columns(
                    _enzyme_raw_wells(e) or wells, prefix=f"{e['title']} ")
                if h2:
                    enzyme_wide_groups.append((h2, cd2))
            else:
                ws.append(["关联蛋白", e.get("protein_names", "")])

        elif proteins and not calc_type:
            # 旧格式：proteins 存在但没标记 calc_type，走旧逻辑
            rows = []
            for i, prot in enumerate(proteins):
                if not isinstance(prot, dict):
                    continue
                name = prot.get("name", "")
                a280 = prot.get("a280", "")
                conc_uM = ""
                conc_mg = ""
                if isinstance(results, list) and i < len(results):
                    r = results[i]
                    conc_uM = r.get("conc_uM", "")
                    conc_mg = r.get("conc_mg_mL", "")
                rows.append([name, "", "", "", a280, conc_uM, conc_mg, "", "", "", ""])
            _write_block(CONC_HEADERS, rows)

        else:
            ws.append(["关联蛋白", e.get("protein_names", "")])

    # 自适应列宽：按内容最大宽度设置（CJK 按 2 个宽度计，上限 40）
    for col in range(1, ws.max_column + 1):
        max_len = 0
        for cell in ws[col]:
            v = cell.value
            if v is None:
                continue
            n = sum(2 if ord(ch) > 127 else 1 for ch in str(v))
            max_len = max(max_len, n)
        ws.column_dimensions[cell.column_letter].width = min(max_len + 2, 40)

    # 酶活导出：附加「作图数据」宽格式 Sheet（每孔独立时间+OD 两列，方便 Origin/Prism 等外部作图）
    if all_enzyme and enzyme_wide_groups:
        ws2 = wb.create_sheet("作图数据")
        headers2, all_cols = [], []
        for h2, cd2 in enzyme_wide_groups:
            headers2 += h2
            all_cols += cd2
        _write_wide_ws(ws2, headers2, all_cols)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=download_name)
