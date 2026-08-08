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

import models
from calculators import calc_ext_coeff, calc_conc, calc_dilution_series, sanitize_seq

app = Flask(__name__)


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


# ═══════════════════════════════════════════════════════════
#  Proteins API
# ═══════════════════════════════════════════════════════════

@app.route("/api/proteins", methods=["GET"])
def api_protein_list():
    search = request.args.get("q", "")
    proteins = models.protein_list(search)
    return jsonify(proteins)


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
    models.protein_delete(pid)
    return jsonify({"ok": True})


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
    models.exp_delete(eid)
    return jsonify({"ok": True})


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

def open_browser():
    import time
    time.sleep(0.5)  # 等 Flask 完全就绪
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    print("Protein Lab 启动中...")
    print("   浏览器即将打开 -> http://127.0.0.1:5000")
    print("   关闭此窗口即可停止服务")
    Timer(0.5, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
