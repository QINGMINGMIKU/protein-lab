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

# 分析型 raw 白名单——这些 data_type 才可能重建计算工具的画面。
# experiment_raw.data_type 是**开放集**（库里就有 test_trace 之类的非分析快照），
# 所以判定必须走白名单，不能只看「有没有 raw」。
CALC_RAW_TYPES = ("enzyme_traces", "bli_curves", "akta_traces")


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


def is_loadable(exp: dict | None, raw_types=()) -> bool:
    """该实验能否「载入计算工具」（详情页 CTA 与列表 API 共用的唯一判定源）。

    `raw_types` = 该实验已落库的 experiment_raw.data_type 集合，由调用方批量查好传入
    （见 `models.exp_raw_type_map`），避免逐条查 raw。

    **三处刻意保守**（逐字还原原 experiment_detail.html 模板的内联判定，别"顺手"放宽）：
      1) 只看 `params.calc_type` **键**的值——不 normalize、不从 exp_type 兜底推断。
         真实库里就有反例：#38「重新纯化与浓度标定」/#39「AKTA 峰位分析」是 MCP 手写的
         记录，params 里有 `proteins` 却**没有 `calc_type` 键**（infer_calc_type 会给它们
         贴 concentration / akta 标签）。一旦改成走推断，这两条就会显示「可载入」，
         点进去只能得到残缺的 tab（#39 连 `akta_traces` 快照都没有）——即"改了既有可见行为"。
      2) 不认 results——原模板也不认（weblogo 即便有 sequences 也不可载入）；
      3) raw 只看 `CALC_RAW_TYPES` 白名单（`experiment_raw.data_type` 是开放集，
         库里存在 `test_trace` 这类非分析快照，"有 raw" 不等于"能重建画面"）。
    """
    exp = exp or {}
    params = _as_dict(exp.get("params"))
    calc_type = params.get("calc_type", "")
    has_calc_raw = any(rt in CALC_RAW_TYPES for rt in (raw_types or ()))
    has_calc_params = (
        (calc_type in ("concentration", "dilution") and bool(params.get("proteins")))
        or (calc_type == "enzyme" and bool(params.get("wells")))
    )
    return bool(has_calc_raw or has_calc_params)
