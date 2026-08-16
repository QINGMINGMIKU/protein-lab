"""实验写入服务 — HTTP 与 MCP 共用的统一 create 入口。

设计意图：所有「创建实验」最终都走 create_experiment，未来在这里挂：
- 审计（audit_log）
- 谱系血缘（experiment_links / copied_from）
- 原始数据分离（experiment_raw + analysis_version）
"""
from datetime import datetime

import models


def auto_exp_name(exp_type: str, date: str = "") -> str:
    """自动命名: {date}_{exp_type}_{seq:02d}，seq 为当天同类型已有标题的最大后缀 + 1"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    seq = models.exp_next_seq(exp_type, date)
    return f"{date}_{exp_type}_{seq:02d}"


def coerce_int_list(values) -> list[int]:
    """把 id 列表规整为 int：跳过空值与不能转 int 的项（不抛错，
    避免 API 把 Python 原始错误文本 `invalid literal for int()...` 泄漏给前端）。"""
    out = []
    for v in values or []:
        if not v:
            continue
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _protein_snapshot_entry(p: dict) -> dict:
    """蛋白库数值快照（不含序列明文）——存档时记录「当时绑定的蛋白参数」。"""
    return {
        "id": p["id"],
        "name": p["name"],
        "mw": p.get("mw"),
        "epsilon_ox": p.get("ext_ox"),
        "epsilon_red": p.get("ext_red"),
        "abs_0_1pct": p.get("abs_0_1pct"),
    }


def _enrich_protein_snapshot(params, results, protein_ids):
    """为所有写入路径的实验补上「当时绑定的蛋白 + 浓度参数」快照（规则：任何存档都要自洽可渲染）。

    - params 已带 proteins（Web 计算工具存档）→ 原样不动；
    - 紧凑浓度形态（a280 + mw/epsilon，无 calc_type/proteins，如 MCP 存档）→
      规范成标准 {calc_type:"concentration", proteins:[{name,mw,epsilon,abs_0_1pct,a280,conc_uM,conc_mg_mL}]}，
      让详情页浓度卡片可直接渲染（浓度值取 results.mean_uM/mean_mg_ml）；
    - 其余类型（酶活/AKTA/weblogo/BLI 等）→ 附加库内蛋白数值快照，保证记录当时绑定参数。
    """
    if not isinstance(params, dict):
        params = {}
    if params.get("proteins"):
        return params  # 已有蛋白快照
    entries = [_protein_snapshot_entry(models.protein_get(pid))
               for pid in (protein_ids or [])]
    entries = [e for e in entries if e]
    if not entries:
        return params
    results = results if isinstance(results, dict) else {}
    # 紧凑浓度形态 → 标准浓度卡片形态
    if params.get("a280") is not None and (
            params.get("mw_da") or params.get("epsilon_red") or params.get("epsilon_ox")):
        oxidized = bool(params.get("oxidized", True))
        eps = params.get("epsilon_ox" if oxidized else "epsilon_red") or entries[0].get(
            "epsilon_ox" if oxidized else "epsilon_red") or 0
        mw = params.get("mw_da") or entries[0].get("mw") or 0
        abs01 = (10 * eps / mw) if mw else 0
        entry = {
            "id": entries[0]["id"],
            "name": entries[0]["name"],
            "mw": mw,
            "epsilon": eps,
            "abs_0_1pct": entries[0].get("abs_0_1pct") or abs01,
            "a280": params.get("a280"),
            "conc_uM": results.get("mean_uM"),
            "conc_mg_mL": results.get("mean_mg_ml"),
        }
        return {**params, "calc_type": params.get("calc_type") or "concentration",
                "proteins": [entry]}
    # 通用绑定快照
    return {**params, "proteins": entries}


def create_experiment(title: str, exp_type: str, protein_ids: list[int] = None,
                      date: str = "", params: dict = None, results: dict = None,
                      notes: str = "", auto_name: bool = True,
                      raw_snapshots: list[tuple[str, object]] = None) -> dict:
    """统一创建实验：校验 + 自动命名 + 蛋白快照 + 落库（可选原子携带 raw 快照），返回完整实验 dict。

    auto_name=False 时标题留空不自动命名（MCP 已要求 title 必填，走默认 True 也无副作用）。
    raw_snapshots: [(data_type, payload), ...] —— 与实验在同事务内原子落库（experiment_raw），
    避免先建实验再单独 save raw 的部分写入（孤儿实验）。BLI/AKTA 等需要快照的写入入口走这里。"""
    exp_type = (exp_type or "").strip()
    if not exp_type:
        raise ValueError("实验类型不能为空")
    title = (title or "").strip()
    if auto_name and not title:
        title = auto_exp_name(exp_type, date)
    if isinstance(protein_ids, list):
        protein_ids = coerce_int_list(protein_ids)
    params = _enrich_protein_snapshot(params, results, protein_ids)
    if raw_snapshots:
        eid = models.exp_create_with_raw(
            title=title, exp_type=exp_type, protein_ids=protein_ids,
            date=date, params=params, results=results, notes=notes,
            raw_snapshots=raw_snapshots,
        )
    else:
        eid = models.exp_create(
            title=title, exp_type=exp_type, protein_ids=protein_ids,
            date=date, params=params, results=results, notes=notes,
        )
    return models.exp_get(eid)
