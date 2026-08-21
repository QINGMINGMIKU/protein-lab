"""横切对比 — 同类实验的关键数对齐。判断留给人，这里只摊开数字。"""
from __future__ import annotations

from identity import infer_calc_type, _as_dict


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):  # NaN / Inf
        return None
    return n


def _bli_sample_metrics(sample: dict) -> dict:
    if not isinstance(sample, dict):
        return {}
    if "error" in sample and "standard" not in sample:
        return {}
    std = sample.get("standard") if isinstance(sample.get("standard"), dict) else sample
    kd = _num(std.get("kd") if isinstance(std, dict) else None)
    r2 = _num(std.get("r2") if isinstance(std, dict) else None)
    kon = _num(std.get("kon") if isinstance(std, dict) else None)
    koff = _num(std.get("koff") if isinstance(std, dict) else None)
    out = {}
    if kd is not None:
        out["kd_nM"] = kd
    if r2 is not None:
        out["r2"] = r2
    if kon is not None:
        out["kon"] = kon
    if koff is not None:
        out["koff"] = koff
    return out


def _conc_metrics(exp: dict) -> dict:
    params = _as_dict(exp.get("params"))
    results = _as_dict(exp.get("results"))
    metrics = {}
    proteins = params.get("proteins")
    if isinstance(proteins, list):
        for p in proteins:
            if not isinstance(p, dict):
                continue
            name = p.get("name") or str(p.get("id") or "protein")
            um = _num(p.get("conc_uM"))
            mg = _num(p.get("conc_mg_mL") or p.get("conc_mg_ml"))
            cell = {}
            if um is not None:
                cell["conc_uM"] = um
            if mg is not None:
                cell["conc_mg_mL"] = mg
            if cell:
                metrics[name] = cell
    if not metrics:
        um = _num(results.get("mean_uM"))
        mg = _num(results.get("mean_mg_ml") or results.get("mean_mg_mL"))
        if um is not None or mg is not None:
            cell = {}
            if um is not None:
                cell["conc_uM"] = um
            if mg is not None:
                cell["conc_mg_mL"] = mg
            metrics["mean"] = cell
    return metrics


def _enzyme_metrics(exp: dict) -> dict:
    params = _as_dict(exp.get("params"))
    wells = params.get("wells") or _as_dict(exp.get("results")).get("wells") or {}
    if not isinstance(wells, dict):
        return {}
    metrics = {}
    for wid, w in wells.items():
        if not isinstance(w, dict):
            continue
        name = (w.get("name") or "").strip() or wid
        fit = w.get("fit") if isinstance(w.get("fit"), dict) else {}
        slope = _num(fit.get("slope_corrected"))
        if slope is None:
            slope = _num(fit.get("slope"))
        r2 = _num(fit.get("r2"))
        cell = {}
        if slope is not None:
            cell["slope"] = slope
        if r2 is not None:
            cell["r2"] = r2
        if cell:
            metrics[name] = cell
    return metrics


def _akta_metrics(exp: dict) -> dict:
    results = _as_dict(exp.get("results"))
    peaks = results.get("peaks") or []
    n = results.get("n_peaks")
    cell = {}
    if n is not None:
        cell["n_peaks"] = _num(n)
    if isinstance(peaks, list) and peaks:
        def _h(p):
            return _num(p.get("height") or p.get("height_mAU")) or 0
        top = max((p for p in peaks if isinstance(p, dict)), key=_h, default=None)
        if top:
            apex = _num(top.get("apex") or top.get("apex_ml") or top.get("position"))
            height = _num(top.get("height") or top.get("height_mAU"))
            if apex is not None:
                cell["apex_mL"] = apex
            if height is not None:
                cell["height_mAU"] = height
    return {"run": cell} if cell else {}


def _dilution_metrics(exp: dict) -> dict:
    params = _as_dict(exp.get("params"))
    results = exp.get("results")
    metrics = {}
    proteins = params.get("proteins")
    if isinstance(proteins, list):
        for p in proteins:
            if not isinstance(p, dict):
                continue
            name = p.get("name") or str(p.get("id") or "protein")
            start = _num(p.get("start_uM") or p.get("start_conc_uM"))
            if start is not None:
                metrics[name] = {"start_uM": start}
    if isinstance(results, dict):
        for name, block in results.items():
            if not isinstance(block, dict):
                continue
            start = _num(block.get("start_uM") or block.get("start"))
            if start is not None:
                metrics.setdefault(name, {})["start_uM"] = start
    return metrics


def _weblogo_metrics(exp: dict) -> dict:
    params = _as_dict(exp.get("params"))
    results = _as_dict(exp.get("results"))
    n = params.get("n") or results.get("n") or (len(params.get("protein_ids") or []) or None)
    cell = {}
    nn = _num(n)
    if nn is not None:
        cell["n_seq"] = nn
    return {"logo": cell} if cell else {}


_EXTRACTORS = {
    "concentration": _conc_metrics,
    "dilution": _dilution_metrics,
    "bli_fit": lambda exp: {
        name: _bli_sample_metrics(block)
        for name, block in (_as_dict(exp.get("results")).get("samples") or {}).items()
        if isinstance(block, dict) and _bli_sample_metrics(block)
    },
    "akta": _akta_metrics,
    "enzyme": _enzyme_metrics,
    "weblogo": _weblogo_metrics,
}


def key_results(exp: dict) -> dict:
    ct = infer_calc_type(exp)
    fn = _EXTRACTORS.get(ct)
    metrics = fn(exp) if fn else {}
    return {"id": exp.get("id"), "title": exp.get("title", ""), "calc_type": ct, "metrics": metrics}


_UNITS = {
    "kd_nM": "nM",
    "r2": "",
    "kon": "1/M·s",
    "koff": "1/s",
    "conc_uM": "µM",
    "conc_mg_mL": "mg/mL",
    "slope": "ΔOD/min",
    "n_peaks": "",
    "apex_mL": "mL",
    "height_mAU": "mAU",
    "start_uM": "µM",
    "n_seq": "",
}

_HIGHLIGHT_RATIO = 2.0  # fold ≥ 2 标差异


def _ratio(a, b):
    if a is None or b is None:
        return None
    if a == 0 and b == 0:
        return 1.0
    if a == 0 or b == 0:
        return None
    return max(abs(b / a), abs(a / b))


def compare_experiments(exp_ids: list[int]) -> dict:
    """对齐 2+ 条实验的关键数。混类型返回 ok=False，不抛。"""
    import models
    ids = []
    for v in exp_ids or []:
        try:
            ids.append(int(v))
        except (TypeError, ValueError):
            continue
    if len(ids) < 2:
        return {"ok": False, "error": "need_two", "calc_type": None, "columns": [], "rows": []}
    exps = []
    for eid in ids:
        e = models.exp_get(eid)
        if not e:
            return {"ok": False, "error": "not_found", "missing_id": eid, "columns": [], "rows": []}
        exps.append(e)
    types = [infer_calc_type(e) for e in exps]
    if len(set(types)) != 1:
        return {"ok": False, "error": "calc_type_mismatch", "calc_types": types,
                "columns": [], "rows": []}
    ct = types[0]
    extracted = [key_results(e) for e in exps]
    columns = [{
        "id": e["id"],
        "title": e.get("title", ""),
        "date": e.get("date", ""),
        "protein_names": e.get("protein_names", ""),
        "calc_type": ct,
    } for e in exps]
    names = []
    seen = set()
    for kr in extracted:
        for name in kr["metrics"]:
            if name not in seen:
                seen.add(name)
                names.append(name)
    metric_keys = []
    mseen = set()
    for kr in extracted:
        for block in kr["metrics"].values():
            for mk in block:
                if mk not in mseen:
                    mseen.add(mk)
                    metric_keys.append(mk)
    rows = []
    for name in names:
        for mk in metric_keys:
            values = []
            for kr in extracted:
                block = kr["metrics"].get(name) or {}
                values.append(block.get(mk))
            if all(v is None for v in values):
                continue
            ratio = None
            if len(values) >= 2:
                ratio = _ratio(values[0], values[-1])
            highlight = bool(ratio is not None and ratio >= _HIGHLIGHT_RATIO)
            rows.append({
                "key": f"{name}.{mk}",
                "entity": name,
                "metric": mk,
                "label": f"{name} · {mk}",
                "unit": _UNITS.get(mk, ""),
                "values": values,
                "ratio": ratio,
                "highlight": highlight,
            })
    return {"ok": True, "error": None, "calc_type": ct, "columns": columns, "rows": rows}
