"""
Protein Lab — 本地蛋白质实验管理系统
Flask 主应用
"""
import sys
import os
import json
import webbrowser
from io import BytesIO
from threading import Timer
from flask import Flask, request, jsonify, render_template, send_file
from openpyxl import Workbook
from openpyxl.styles import Font

# 确保能找到同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import models
from calculators import calc_ext_coeff, calc_conc, calc_dilution_series, sanitize_seq, parse_tecan_xlsx, fit_kinetics

app = Flask(__name__)

# ── Undo 栈（内存中，最多 20 条）──────────────────────────
_undo_stack = []


def _push_undo(item_type: str, data: dict):
    _undo_stack.append({"type": item_type, "data": data})
    if len(_undo_stack) > 20:
        _undo_stack.pop(0)


def _pop_undo():
    return _undo_stack.pop() if _undo_stack else None


# ═══════════════════════════════════════════════════════════
#  页面路由
# ═══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("proteins.html")


@app.route("/proteins")
def page_proteins():
    return render_template("proteins.html")


@app.route("/calculator")
def page_calculator():
    return render_template("calculator.html")


@app.route("/experiments")
def page_experiments():
    return render_template("experiments.html")


@app.route("/experiments/<int:eid>")
def page_experiment_detail(eid):
    e = models.exp_get(eid)
    if not e:
        return "实验不存在", 404
    # 解析 JSON 字符串字段供模板使用（处理历史双编码问题）
    for field in ("params", "results"):
        val = e.get(field)
        while isinstance(val, str):
            try: val = json.loads(val)
            except: break
        if not isinstance(val, dict):
            val = {}
        e[field] = val
    return render_template("experiment_detail.html", exp=e)


@app.route("/weblogo")
def page_weblogo():
    return render_template("weblogo.html")


# ═══════════════════════════════════════════════════════════
#  Proteins API
# ═══════════════════════════════════════════════════════════

@app.route("/api/proteins", methods=["GET"])
def api_protein_list():
    search = request.args.get("q", "")
    tag_filter = request.args.get("tag", "")
    proteins = models.protein_list(search, tag_filter)
    return jsonify(proteins)


@app.route("/api/proteins/tags", methods=["GET"])
def api_protein_tags():
    return jsonify(models.protein_tags())


@app.route("/api/proteins/<int:pid>", methods=["GET"])
def api_protein_get(pid):
    p = models.protein_get(pid)
    if not p:
        return jsonify({"error": "蛋白不存在"}), 404
    return jsonify(p)


@app.route("/api/proteins", methods=["POST"])
def api_protein_create():
    data = request.get_json()
    name = data.get("name", "").strip()
    sequence = sanitize_seq(data.get("sequence", ""))
    if not name or not sequence:
        return jsonify({"error": "名称和序列不能为空"}), 400

    # 检查重复
    existing = models.protein_get_by_name(name)
    if existing:
        return jsonify({"error": f"蛋白 '{name}' 已存在"}), 409

    # 计算 MW / ε
    c = calc_ext_coeff(sequence)
    pid = models.protein_create(
        name=name, sequence=sequence,
        tag=data.get("tag", ""), notes=data.get("notes", ""),
        mw=c["mw"], nW=c["nW"], nY=c["nY"], nC=c["nC"],
        ext_red=c["ext_red"], ext_ox=c["ext_ox"], abs_0_1pct=c["abs_0_1pct"],
    )
    return jsonify(models.protein_get(pid)), 201


@app.route("/api/proteins/<int:pid>", methods=["PUT"])
def api_protein_update(pid):
    data = request.get_json()
    kwargs = {}
    for field in ["name", "sequence", "tag", "notes"]:
        if field in data:
            val = data[field]
            if isinstance(val, str):
                val = val.strip()
                if field == "sequence":
                    val = val.upper()
            kwargs[field] = val
    # 如果更新了序列，重新计算
    if "sequence" in kwargs:
        c = calc_ext_coeff(kwargs["sequence"])
        kwargs.update(mw=c["mw"], nW=c["nW"], nY=c["nY"], nC=c["nC"],
                      ext_red=c["ext_red"], ext_ox=c["ext_ox"],
                      abs_0_1pct=c["abs_0_1pct"])
    models.protein_update(pid, **kwargs)
    return jsonify(models.protein_get(pid))


@app.route("/api/proteins/<int:pid>", methods=["DELETE"])
def api_protein_delete(pid):
    p = models.protein_get(pid)
    if p:
        _push_undo("protein", dict(p))
    models.protein_delete(pid)
    return jsonify({"ok": True})


@app.route("/api/proteins/batch-delete", methods=["POST"])
def api_protein_batch_delete():
    ids = request.get_json().get("ids", [])
    deleted = 0
    for pid in ids:
        p = models.protein_get(int(pid))
        if p:
            _push_undo("protein", dict(p))
            models.protein_delete(int(pid))
            deleted += 1
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/proteins/batch-tags", methods=["POST"])
def api_protein_batch_tags():
    """批量修改标签：为多个蛋白添加/移除标签（不覆盖已有标签）"""
    data = request.get_json()
    ids = data.get("ids", [])
    add_set = {t.strip() for t in data.get("add", "").split(",") if t.strip()}
    remove_set = {t.strip() for t in data.get("remove", "").split(",") if t.strip()}
    if not add_set and not remove_set:
        return jsonify({"error": "请至少添加或移除一个标签"}), 400
    updated = 0
    for pid in ids:
        p = models.protein_get(int(pid))
        if not p:
            continue
        cur = {t.strip() for t in (p.get("tag") or "").split(",") if t.strip()}
        cur.difference_update(remove_set)
        cur.update(add_set)
        models.protein_update(int(pid), tag=", ".join(sorted(cur)))
        updated += 1
    return jsonify({"ok": True, "updated": updated})


@app.route("/api/proteins/delete-all", methods=["POST"])
def api_protein_delete_all():
    proteins = models.protein_list()
    for p in proteins:
        _push_undo("protein", dict(p))
    models.protein_delete_all()
    return jsonify({"ok": True, "deleted": len(proteins)})


@app.route("/api/proteins/refresh-all", methods=["POST"])
def api_protein_refresh_all():
    """一键重算所有蛋白的 MW 和消光系数"""
    proteins = models.protein_list()
    count = 0
    for p in proteins:
        c = calc_ext_coeff(p["sequence"])
        models.protein_update(p["id"],
            mw=c["mw"], nW=c["nW"], nY=c["nY"], nC=c["nC"],
            ext_red=c["ext_red"], ext_ox=c["ext_ox"], abs_0_1pct=c["abs_0_1pct"])
        count += 1
    return jsonify({"ok": True, "refreshed": count})


@app.route("/api/proteins/import", methods=["POST"])
def api_protein_import_fasta():
    """批量导入 FASTA 文本"""
    data = request.get_json()
    fasta_text = data.get("fasta", "")
    tag = data.get("tag", "")
    notes = data.get("notes", "")
    if not fasta_text.strip():
        return jsonify({"error": "FASTA 内容为空"}), 400

    imported = []
    skipped = []
    entries = parse_fasta(fasta_text)
    for header, seq in entries:
        if not seq:
            continue
        name = header.strip()
        existing = models.protein_get_by_name(name)
        if existing:
            skipped.append(name)
            continue
        c = calc_ext_coeff(seq)
        models.protein_create(
            name=name, sequence=seq, tag=tag, notes=notes,
            mw=c["mw"], nW=c["nW"], nY=c["nY"], nC=c["nC"],
            ext_red=c["ext_red"], ext_ox=c["ext_ox"], abs_0_1pct=c["abs_0_1pct"],
        )
        imported.append(name)

    return jsonify({"imported": imported, "skipped": skipped, "total": len(entries)})


def parse_fasta(text: str) -> list:
    """解析 FASTA 文本，返回 [(header, sequence), ...]"""
    entries = []
    current_header = ""
    current_seq = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_header:
                entries.append((current_header, "".join(current_seq)))
            current_header = line[1:]  # 去掉 >
            current_seq = []
        else:
            current_seq.append(line)
    if current_header:
        entries.append((current_header, "".join(current_seq)))
    return entries


# ═══════════════════════════════════════════════════════════
#  Calculation API
# ═══════════════════════════════════════════════════════════

@app.route("/api/calc/concentration", methods=["POST"])
def api_calc_concentration():
    data = request.get_json()
    protein_id = data.get("protein_id")
    a280 = data.get("a280")
    oxidized = data.get("oxidized", True)
    path_length = data.get("path_length_cm", 1.0)

    if not protein_id or a280 is None:
        # 允许直接传序列
        sequence = data.get("sequence")
        if not sequence:
            return jsonify({"error": "需要 protein_id 或 sequence"}), 400
        c = calc_ext_coeff(sequence)
        mw = c["mw"]
        epsilon = c["ext_ox"] if oxidized else c["ext_red"]
    else:
        p = models.protein_get(int(protein_id))
        if not p:
            return jsonify({"error": "蛋白不存在"}), 404
        epsilon = p["ext_ox"] if oxidized else p["ext_red"]
        mw = p["mw"]

    try:
        path_length = float(path_length)
        result = calc_conc(float(a280), epsilon, mw, path_length)
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@app.route("/api/calc/dilution", methods=["POST"])
def api_calc_dilution():
    data = request.get_json()
    try:
        stock_conc = float(data["stock_conc_uM"])
        start_conc = float(data["start_conc_uM"])
        dilution_factor = float(data.get("dilution_factor", 2))
        n_steps = int(data.get("n_steps", 8))
        vol_per_well = float(data["vol_per_well_uL"])
        dead_vol = float(data.get("dead_vol_uL", 5))
    except (KeyError, ValueError) as e:
        return jsonify({"error": f"参数无效: {e}"}), 400

    try:
        steps = calc_dilution_series(stock_conc, start_conc, dilution_factor,
                                     n_steps, vol_per_well, dead_vol)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "stock_conc_uM": stock_conc,
        "dilution_factor": dilution_factor,
        "n_steps": n_steps,
        "vol_per_well_uL": vol_per_well,
        "steps": [{
            "step": s.step,
            "conc_uM": s.conc_uM,
            "stock_vol_uL": s.stock_vol_uL,
            "buffer_vol_uL": s.buffer_vol_uL,
            "total_vol_uL": s.total_vol_uL,
        } for s in steps]
    })


# ═══════════════════════════════════════════════════════════
#  Experiments API
# ═══════════════════════════════════════════════════════════

@app.route("/api/experiments", methods=["GET"])
def api_exp_list():
    exp_type = request.args.get("type", "")
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    return jsonify(models.exp_list(exp_type, limit))


@app.route("/api/experiments/<int:eid>", methods=["GET"])
def api_exp_get(eid):
    e = models.exp_get(eid)
    if not e:
        return jsonify({"error": "实验不存在"}), 404
    return jsonify(e)


@app.route("/api/experiments", methods=["POST"])
def api_exp_create():
    data = request.get_json()
    title = data.get("title", "").strip()
    exp_type = data.get("exp_type", "").strip()
    if not title or not exp_type:
        return jsonify({"error": "实验标题和类型不能为空"}), 400

    protein_ids = data.get("protein_ids", [])
    if isinstance(protein_ids, list):
        protein_ids = [int(p) for p in protein_ids if p]

    eid = models.exp_create(
        title=title, exp_type=exp_type,
        protein_ids=protein_ids,
        date=data.get("date", ""),
        params=data.get("params", {}),
        results=data.get("results", {}),
        notes=data.get("notes", ""),
    )
    return jsonify(models.exp_get(eid)), 201


@app.route("/api/experiments/from-calculation", methods=["POST"])
def api_exp_from_calc():
    """从计算工具一键保存为实验"""
    data = request.get_json()
    title = data.get("title", "").strip()
    exp_type = data.get("exp_type", "").strip()
    if not title or not exp_type:
        return jsonify({"error": "实验标题和类型不能为空"}), 400

    protein_ids = data.get("protein_ids", [])
    if isinstance(protein_ids, list):
        protein_ids = [int(p) for p in protein_ids if p]

    # 将计算参数和结果打包进 params/results
    calc_params = data.get("calc_params", {})
    calc_result = data.get("calc_result", {})

    params = {"calc_type": data.get("calc_type", ""), **calc_params}
    results = calc_result

    eid = models.exp_create(
        title=title, exp_type=exp_type,
        protein_ids=protein_ids,
        date=data.get("date", ""),
        params=params, results=results,
        notes=data.get("notes", ""),
    )
    return jsonify(models.exp_get(eid)), 201


@app.route("/api/experiments/<int:eid>", methods=["PUT"])
def api_exp_update(eid):
    """编辑实验元数据（标题、类型、日期、备注）"""
    data = request.get_json()
    kwargs = {}
    for key in ["title", "exp_type", "date", "notes", "params", "results"]:
        if key in data:
            kwargs[key] = data[key]
    if kwargs:
        models.exp_update(eid, **kwargs)
    return jsonify(models.exp_get(eid))


@app.route("/api/experiments/<int:eid>/proteins", methods=["PUT"])
def api_exp_update_proteins(eid):
    """单独更新实验的蛋白关联"""
    data = request.get_json()
    protein_ids = data.get("protein_ids", [])
    if isinstance(protein_ids, list):
        protein_ids = [int(p) for p in protein_ids if p]
    models.exp_update(eid, protein_ids=protein_ids)
    return jsonify(models.exp_get(eid))


@app.route("/api/experiments/<int:eid>", methods=["DELETE"])
def api_exp_delete(eid):
    e = models.exp_get(eid)
    if e:
        _push_undo("experiment", dict(e))
    models.exp_delete(eid)
    return jsonify({"ok": True})


@app.route("/api/experiments/batch-delete", methods=["POST"])
def api_exp_batch_delete():
    ids = request.get_json().get("ids", [])
    deleted = 0
    for eid in ids:
        e = models.exp_get(int(eid))
        if e:
            _push_undo("experiment", dict(e))
            models.exp_delete(int(eid))
            deleted += 1
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/experiments/delete-all", methods=["POST"])
def api_exp_delete_all():
    exps = models.exp_list(limit=9999)
    for e in exps:
        _push_undo("experiment", dict(e))
    models.exp_delete_all()
    return jsonify({"ok": True, "deleted": len(exps)})


# ═══════════════════════════════════════════════════════════
#  Undo API
# ═══════════════════════════════════════════════════════════

@app.route("/api/undo/status", methods=["GET"])
def api_undo_status():
    return jsonify({"count": len(_undo_stack)})


@app.route("/api/undo", methods=["POST"])
def api_undo_restore():
    item = _pop_undo()
    if not item:
        return jsonify({"error": "无撤销项"}), 404
    data = item["data"]
    if item["type"] == "protein":
        existing = models.protein_get_by_name(data["name"])
        if existing:
            return jsonify({"error": f"蛋白 '{data['name']}' 已存在，无法撤销"}), 409
        models.protein_create(
            name=data["name"], sequence=data["sequence"],
            tag=data.get("tag", ""), notes=data.get("notes", ""),
            mw=data.get("mw", 0), nW=data.get("nW", 0),
            nY=data.get("nY", 0), nC=data.get("nC", 0),
            ext_red=data.get("ext_red", 0), ext_ox=data.get("ext_ox", 0),
            abs_0_1pct=data.get("abs_0_1pct", 0),
        )
        return jsonify({"ok": True, "restored": data["name"]})
    elif item["type"] == "experiment":
        protein_ids = data.get("protein_ids", [])
        models.exp_create(
            title=data["title"], exp_type=data["exp_type"],
            protein_ids=protein_ids,
            date=data.get("date", ""),
            params=data.get("params", {}),
            results=data.get("results", {}),
            notes=data.get("notes", ""),
        )
        return jsonify({"ok": True, "restored": data["title"]})
    return jsonify({"error": "未知类型"}), 400


@app.route("/api/experiments/<int:eid>/export", methods=["GET"])
def api_exp_export_single(eid):
    """导出单个实验为 Excel"""
    e = models.exp_get(eid)
    if not e:
        return jsonify({"error": "实验不存在"}), 404
    safe_name = e["title"].replace("/", "_").replace("\\", "_")[:60]
    return _export_excel([e], download_name=f"{safe_name}.xlsx")


@app.route("/api/experiments/export", methods=["GET"])
def api_exp_export():
    """导出全部（或按类型筛选）实验为 Excel"""
    exp_type = request.args.get("type", "")
    exps = models.exp_list(exp_type, limit=9999)
    return _export_excel(exps)


def _export_excel(exps, download_name="实验记录.xlsx"):
    """共享导出逻辑 — exps 是已查询的实验列表"""
    wb = Workbook()
    ws = wb.active
    ws.title = "实验记录"

    # 根据实验类型选择表头
    def _get_calc_type(e):
        p = e.get("params", {})
        if isinstance(p, str):
            try: p = json.loads(p)
            except: p = {}
        return p.get("calc_type", "") if isinstance(p, dict) else ""
    all_enzyme = exps and all(_get_calc_type(e) == "enzyme" for e in exps)
    if all_enzyme:
        headers = ["实验名称", "日期", "类型", "孔位/命名", "参考类型",
                   "浓度 (ng/mL)", "浓度 (μM)", "ΔOD/min", "R²", "样本", "波长"]
    else:
        headers = ["实验名称", "日期", "类型", "蛋白", "MW (Da)", "ε",
                   "Abs 0.1%", "A280", "浓度 (μM)", "浓度 (mg/mL)",
                   "目标浓度 (μM)", "目标体积 (μL)", "取母液 (μL)", "加缓冲液 (μL)"]
    ws.append(headers)
    for col in range(1, len(headers) + 1):
        ws.cell(row=1, column=col).font = Font(bold=True)

    row = 2
    for e in exps:
        params = e.get("params", "{}")
        results = e.get("results", "{}")
        if isinstance(params, str):
            params = json.loads(params)
        if isinstance(results, str):
            results = json.loads(results)

        calc_type = params.get("calc_type", "")
        proteins = params.get("proteins", [])

        if calc_type == "concentration" and proteins:
            for i, prot in enumerate(proteins):
                if isinstance(prot, dict):
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
                    ws.append([
                        e["title"] if i == 0 else "", e.get("date", "") if i == 0 else "",
                        e["exp_type"] if i == 0 else "", prot.get("name", ""),
                        f"{mw_val:.1f}" if isinstance(mw_val, (int, float)) and mw_val else mw_val,
                        f"{eps_val:.0f}" if isinstance(eps_val, (int, float)) and eps_val else eps_val,
                        f"{abs_val:.4f}" if isinstance(abs_val, (int, float)) and abs_val else abs_val,
                        prot.get("a280", ""), conc_uM, conc_mg,
                        prot.get("target_conc", ""), prot.get("target_vol", ""),
                        prot.get("take_vol", ""), prot.get("buffer_vol", ""),
                    ])
                row += 1

        elif calc_type == "dilution":
            # BLI 稀释实验：每蛋白的每步一行
            dil_proteins = params.get("proteins", [])
            if dil_proteins:
                first = True
                for prot in dil_proteins:
                    if not isinstance(prot, dict):
                        continue
                    pid = str(prot.get("id", ""))
                    prot_result = results.get(pid, {}) if isinstance(results, dict) else {}
                    prot_steps = prot_result.get("steps", []) if isinstance(prot_result, dict) else []
                    if not prot_steps:
                        # 旧格式兼容：results.steps 直接是列表
                        prot_steps = results.get("steps", results) if isinstance(results, dict) else (results if isinstance(results, list) else [])
                    prot_name = prot.get("name", "")
                    for i, st in enumerate(prot_steps):
                        if isinstance(st, dict):
                            ws.append([
                                e["title"] if first and i == 0 else "",
                                e.get("date", "") if first and i == 0 else "",
                                e["exp_type"] if first and i == 0 else "",
                                prot_name,
                                "", "", "", "",
                                st.get("conc_uM", ""),
                                f"stock={prot.get('stock_uM','')}",
                                f"factor={prot.get('factor','')}",
                                f"vol={prot.get('vol','')}",
                                st.get("stock_vol_uL", ""),
                                st.get("buffer_vol_uL", ""),
                            ])
                        row += 1
            else:
                ws.append([e["title"], e.get("date", ""), e["exp_type"],
                          e.get("protein_names", ""), "", "", "", "", "", "", "", "", "", ""])
                row += 1

        elif calc_type == "enzyme":
            # 酶活实验：每孔一行
            wells = params.get("wells") or params.get("well_info") or {}
            emeta = params.get("meta", {})
            if wells:
                first = True
                for wid, w in sorted(wells.items()):
                    if not isinstance(w, dict):
                        continue
                    fit = w.get("fit") or {}
                    ref_label = {"blank": "空白", "neg": "阴性", "pos": "阳性"}.get(w.get("ref", ""), "")
                    ws.append([
                        e["title"] if first else "", e.get("date", "") if first else "",
                        e["exp_type"] if first else "", f"{wid} {w.get('name', '')}",
                        ref_label,
                        w.get("conc_ng_ml", ""), w.get("conc_uM", ""),
                        fit.get("slope", ""), fit.get("r2", ""),
                        emeta.get("sample", ""), emeta.get("wavelength", ""),
                    ])
                    first = False
                    row += 1
            else:
                ws.append([e["title"], e.get("date", ""), e["exp_type"],
                          e.get("protein_names", ""), "", "", "", "",
                          "", "", "", ""])
                row += 1

        elif proteins and not calc_type:
            # 旧格式：proteins 存在但没标记 calc_type，走旧逻辑
            for i, prot in enumerate(proteins):
                if isinstance(prot, dict):
                    name = prot.get("name", "")
                    a280 = prot.get("a280", "")
                    conc_uM = ""
                    conc_mg = ""
                    if isinstance(results, list) and i < len(results):
                        r = results[i]
                        conc_uM = r.get("conc_uM", "")
                        conc_mg = r.get("conc_mg_mL", "")
                    ws.append([
                        e["title"] if i == 0 else "", e.get("date", "") if i == 0 else "",
                        e["exp_type"] if i == 0 else "", name, "", "", "", a280,
                        conc_uM, conc_mg, "", "", "", ""
                    ])
                row += 1
        else:
            ws.append([
                e["title"], e.get("date", ""), e["exp_type"],
                e.get("protein_names", ""), "", "", "", "", "", "", "", "", "", ""
            ])
            row += 1

    if all_enzyme:
        widths = [30, 12, 10, 20, 10, 14, 12, 12, 10, 22, 10]
    else:
        widths = [30, 12, 10, 20, 12, 10, 10, 10, 12, 12, 14, 14, 12, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=download_name)


# ═══════════════════════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
#  Weblogo API
# ═══════════════════════════════════════════════════════════

@app.route("/api/weblogo", methods=["POST"])
def api_weblogo():
    """用 logomaker 生成序列标识图，返回 base64 PNG"""
    import base64
    import pandas as pd
    import logomaker
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 中文字体（图内块标题）
    from matplotlib import font_manager
    font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "simhei.ttf")
    if os.path.exists(font_path):
        font_manager.fontManager.addfont(font_path)
        plt.rcParams["font.family"] = "SimHei"
    plt.rcParams["axes.unicode_minus"] = False

    data = request.get_json()
    sequences = data.get("sequences", [])
    color_scheme = data.get("color_scheme", "chemistry")

    if not sequences or len(sequences) < 2:
        return jsonify({"error": "至少需要 2 条对齐序列"}), 400

    n_pos = len(sequences[0])
    for s in sequences:
        if len(s) != n_pos:
            return jsonify({"error": "所有序列必须等长（已对齐）"}), 400

    # 构建频率矩阵
    chars = sorted(set("".join(sequences)))
    counts = {c: [0] * n_pos for c in chars}
    for seq in sequences:
        for i, c in enumerate(seq):
            if c in counts:
                counts[c][i] += 1

    counts_df = pd.DataFrame(counts)
    prob_df = counts_df.div(counts_df.sum(axis=1), axis=0)
    info_df = logomaker.transform_matrix(prob_df, from_type="probability", to_type="information")

    # 长序列分块换行：每个分块一行，编号连续
    MAX_BLOCK = 50
    if n_pos <= MAX_BLOCK:
        blocks = [n_pos]
    else:
        blocks = [MAX_BLOCK] * (n_pos // MAX_BLOCK)
        if n_pos % MAX_BLOCK:
            blocks.append(n_pos % MAX_BLOCK)
    n_rows = len(blocks)
    block_w = max(blocks)
    fig, axes = plt.subplots(n_rows, 1, figsize=(max(8, block_w * 0.4), 2.4 * n_rows),
                             squeeze=False)
    axes = axes.flatten()
    ymax = max(float(info_df.max().max()), 4.5)

    for i, blk in enumerate(blocks):
        start = sum(blocks[:i])
        sub = info_df.iloc[start:start + blk]
        logomaker.Logo(sub, ax=axes[i], color_scheme=color_scheme)
        axes[i].set_xlim(start - 0.5, start + blk - 0.5)
        axes[i].set_xticks(range(start, start + blk))
        axes[i].set_xticklabels([str(x + 1) for x in range(start, start + blk)], fontsize=8)
        axes[i].set_ylim(0, ymax)
        axes[i].set_ylabel("bits")
        if n_rows > 1:
            axes[i].set_title(f"位置 {start + 1}--{start + blk}", fontsize=10, color="#555", pad=8)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode()

    return jsonify({"image": f"data:image/png;base64,{img_b64}", "positions": n_pos})


# ═══════════════════════════════════════════════════════════
#  Enzyme Activity API
# ═══════════════════════════════════════════════════════════

@app.route("/api/enzyme/parse", methods=["POST"])
def api_enzyme_parse():
    """上传 TECAN xlsx，返回井数据"""
    if "file" not in request.files:
        return jsonify({"error": "请上传 xlsx 文件"}), 400
    f = request.files["file"]
    tmp = os.path.join(os.path.dirname(models.DB_PATH), "_upload.xlsx")
    f.save(tmp)
    try:
        data = parse_tecan_xlsx(tmp)
    except Exception as e:
        return jsonify({"error": f"解析失败: {e}"}), 400
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return jsonify(data)


@app.route("/api/enzyme/fit", methods=["POST"])
def api_enzyme_fit():
    """对指定孔做线性拟合，返回 ΔOD/min + R²"""
    body = request.get_json()
    wells_data = body.get("wells", {})
    results = {}
    for well_id, wd in wells_data.items():
        if wd.get("times") and wd.get("od"):
            results[well_id] = fit_kinetics(wd["times"], wd["od"])
    return jsonify(results)


@app.route("/api/enzyme/plot", methods=["POST"])
def api_enzyme_plot():
    """生成动力学曲线图，返回 base64 PNG"""
    import base64
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # 中文字体
    font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "simhei.ttf")
    if os.path.exists(font_path):
        font_manager.fontManager.addfont(font_path)
        plt.rcParams["font.family"] = "SimHei"
    plt.rcParams["axes.unicode_minus"] = False

    body = request.get_json()
    wells_data = body.get("wells", {})
    plot_type = body.get("type", "kinetics")  # kinetics | michaelis
    align_start = body.get("align_start", False)
    align_end = body.get("align_end", False)

    fig, ax = plt.subplots(figsize=(8, 4.5))

    if plot_type == "kinetics":
        # 对齐：计算全部孔的起始/终止均值
        all_first_od = []
        all_last_od = []
        if align_start or align_end:
            for wd in wells_data.values():
                if wd.get("od") and len(wd["od"]) > 0:
                    all_first_od.append(wd["od"][0])
                    all_last_od.append(wd["od"][-1])
        avg_first = sum(all_first_od) / len(all_first_od) if all_first_od else 0.0
        avg_last = sum(all_last_od) / len(all_last_od) if all_last_od else 0.0

        has_blank = any(wd.get("ref") in ("blank", "neg") for wd in wells_data.values())

        for well_id, wd in wells_data.items():
            if not wd.get("times") or not wd.get("od"):
                continue
            ref = wd.get("ref", "")
            # 默认隐藏阴性/空白
            if ref in ("blank", "neg") and not body.get("show_blank", False):
                continue

            label = wd.get("name", well_id)
            conc = wd.get("conc_ng_ml", "")
            lbl = f"{label}" + (f" ({conc} ng/mL)" if conc else "")
            times_min = [t / 60 for t in wd["times"]]
            od_vals = list(wd["od"])

            if align_start and od_vals:
                shift = avg_first - od_vals[0]
                od_vals = [v + shift for v in od_vals]
            if align_end and od_vals:
                shift = avg_last - od_vals[-1]
                od_vals = [v + shift for v in od_vals]

            # 阳性对照：加粗突出
            lw = 2 if ref == "pos" else 1
            alpha_val = 1.0 if ref == "pos" else 0.85
            line = ax.plot(times_min, od_vals, ".-", label=lbl, linewidth=lw, markersize=3, alpha=alpha_val)
            # 阳性拟合线也更粗
            fit = wd.get("fit")
            if fit and fit.get("slope") is not None:
                t_fit = np.linspace(times_min[0], times_min[-1], 100)
                intercept = fit.get("intercept", od_vals[0]) if fit.get("intercept") is not None else od_vals[0]
                od_fit = [intercept + fit["slope"] / 60 * t for t in t_fit]
                if align_start and fit.get("intercept") is not None:
                    shift_fit = avg_first - fit["intercept"]
                    od_fit = [v + shift_fit for v in od_fit]
                ax.plot(t_fit, od_fit, "--", linewidth=lw + 0.5, alpha=0.6, color=line[0].get_color())

        # 标注：中文/英文自适应
        use_cn = os.path.exists(font_path)
        notes = []
        if has_blank:
            notes.append("已扣除阴性/空白" if use_cn else "blank subtracted")
        if align_start:
            notes.append("已对齐起始值" if use_cn else "start aligned")
        if align_end:
            notes.append("已对齐终止值" if use_cn else "end aligned")
        title = "Kinetics"
        if notes:
            title += " (" + ", ".join(notes) + ")"
        ax.set_title(title, fontsize=12, color="#555")
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("OD")
        if wells_data:
            ax.legend(ncol=3, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 1.18), frameon=False)
    elif plot_type == "michaelis":
        points = []
        for well_id, wd in wells_data.items():
            s = wd.get("substrate_uM")
            v = wd.get("rate")
            if s is not None and v is not None:
                points.append((s, v, wd.get("name", well_id)))
        if points:
            points.sort()
            sx = [p[0] for p in points]
            sy = [p[1] for p in points]
            ax.scatter(sx, sy, c="#4361ee")
            for p in points:
                ax.annotate(p[2], (p[0], p[1]), fontsize=8,
                           textcoords="offset points", xytext=(0, 8))
            ax.set_xlabel("Substrate (μM)")
            ax.set_ylabel("Rate (ΔOD/min)")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return jsonify({"image": f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"})


def open_browser():
    import time
    time.sleep(0.5)  # 等 Flask 完全就绪
    webbrowser.open("http://127.0.0.1:5000")


def backup_database():
    """启动时自动备份数据库，保留最近 10 份"""
    db_path = models.DB_PATH
    if not os.path.exists(db_path):
        return
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"protein_lab_{stamp}.db")
    import shutil
    shutil.copy2(db_path, backup_path)

    # 清理旧备份，只保留最近 10 份
    existing = sorted(
        [f for f in os.listdir(backup_dir) if f.endswith(".db")],
        reverse=True,
    )
    for old in existing[10:]:
        os.remove(os.path.join(backup_dir, old))

    print(f"   数据库已备份 -> backups/ ({min(len(existing), 10)} 份)")


if __name__ == "__main__":
    print("Protein Lab 启动中...")
    print("   浏览器即将打开 -> http://127.0.0.1:5000")
    print("   关闭此窗口即可停止服务")
    backup_database()
    Timer(0.5, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
