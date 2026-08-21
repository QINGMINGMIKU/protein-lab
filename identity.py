"""实验分析身份 — calc_type 是规范键，exp_type 只做展示族。

不改 schema：calc_type 写在 params JSON 里；读路径推断补齐历史记录。
"""
from __future__ import annotations

CALC_TYPES = (
    "concentration",
    "dilution",
    "bli_fit",
    "akta",
    "enzyme",
    "weblogo",
    "sds_page",
    "other",
)

# 规范身份 → 落库 exp_type（历史中文族名保持不变，避免迁移）
CALC_TO_EXP_TYPE = {
    "concentration": "浓度测定",
    "dilution": "BLI",
    "bli_fit": "BLI",
    "akta": "AKTA",
    "enzyme": "酶活测定",
    "weblogo": "Weblogo",
    "sds_page": "SDS-PAGE",
    "other": "其他",
}

# 手工建档 / 只有族名时的默认身份。BLI 默认拟合（稀释必须带 calc_type=dilution）。
EXP_TYPE_DEFAULT_CALC = {
    "浓度测定": "concentration",
    "酶活测定": "enzyme",
    "AKTA": "akta",
    "BLI": "bli_fit",
    "Weblogo": "weblogo",
    "SDS-PAGE": "sds_page",
    "其他": "other",
}

_ALIASES = {
    "bli": "bli_fit",
    "bli_analysis": "bli_fit",
    "bli_dilution": "dilution",
    "conc": "concentration",
    "logo": "weblogo",
}


def _as_dict(val) -> dict:
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val.strip():
        import json
        try:
            cur = val
            for _ in range(3):
                if not isinstance(cur, str):
                    break
                cur = json.loads(cur)
            return cur if isinstance(cur, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def normalize_calc_type(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = _ALIASES.get(s, s)
    return s if s in CALC_TYPES else None


def infer_from_exp_type(exp_type: str) -> str:
    t = (exp_type or "").strip()
    if t in EXP_TYPE_DEFAULT_CALC:
        return EXP_TYPE_DEFAULT_CALC[t]
    if "AKTA" in t:
        return "akta"
    if t.startswith("BLI") or t == "BLI":
        return "bli_fit"
    if "Weblogo" in t or "weblogo" in t.lower():
        return "weblogo"
    if "浓度" in t:
        return "concentration"
    if "酶活" in t:
        return "enzyme"
    if "SDS" in t:
        return "sds_page"
    return "other"


def infer_calc_type(exp: dict | None) -> str:
    """从一条实验记录推断规范身份。params.calc_type 优先。"""
    exp = exp or {}
    params = _as_dict(exp.get("params"))
    results = _as_dict(exp.get("results"))
    explicit = normalize_calc_type(params.get("calc_type"))
    if explicit:
        return explicit
    exp_type = exp.get("exp_type") or ""
    if params.get("proteins") and (params.get("a280") is not None or any(
            isinstance(p, dict) and p.get("conc_uM") is not None for p in (params.get("proteins") or []))):
        if "dilution" not in str(params.get("calc_type") or ""):
            # 浓度卡常见形态；稀释也带 proteins，但 dilution 会走 explicit
            if results.get("steps") or params.get("factor") or params.get("steps"):
                return "dilution"
    if results.get("samples") and ("BLI" in exp_type or not exp_type):
        return "bli_fit"
    if results.get("peaks") or params.get("channel"):
        return "akta"
    if params.get("wells") or results.get("wells"):
        return "enzyme"
    if params.get("sequences") or params.get("protein_ids") and "logo" in str(params).lower():
        pass
    return infer_from_exp_type(exp_type)


def slug_for(calc_type: str) -> str:
    ct = normalize_calc_type(calc_type) or infer_from_exp_type(calc_type)
    return ct


def exp_type_for(calc_type: str) -> str:
    ct = normalize_calc_type(calc_type) or "other"
    return CALC_TO_EXP_TYPE[ct]


def stamp_params(params, exp_type: str = "", calc_type: str = "") -> dict:
    """写入前补 calc_type。已有合法值不覆盖。"""
    params = dict(_as_dict(params))
    existing = normalize_calc_type(params.get("calc_type"))
    if existing:
        params["calc_type"] = existing
        return params
    ct = normalize_calc_type(calc_type) or infer_calc_type(
        {"params": params, "exp_type": exp_type, "results": {}})
    params["calc_type"] = ct
    return params


def annotate(exp: dict) -> dict:
    """读路径附 calc_type，不写库。"""
    if not exp:
        return exp
    exp = dict(exp)
    exp["calc_type"] = infer_calc_type(exp)
    return exp
