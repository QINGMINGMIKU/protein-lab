"""实验写入服务 — HTTP 与 MCP 共用的统一 create 入口。

设计意图：所有「创建实验」最终都走 create_experiment，未来在这里挂：
- 审计（audit_log）
- 谱系血缘（experiment_links / copied_from）
- 原始数据分离（experiment_raw + analysis_version）
- v0.1.1：从实验自然产生研究脉络（保存时挂 Goal→Experiment 节点）
"""
from datetime import datetime

import models
import research


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
                      raw_snapshots: list[tuple[str, object]] = None,
                      goal_id: int | None = None,
                      new_goal: dict | None = None) -> dict:
    """统一创建实验：校验 + 自动命名 + 蛋白快照 + 落库（可选原子携带 raw 快照）+ 可选挂研究脉络节点。

    auto_name=False 时标题留空不自动命名（MCP 已要求 title 必填，走默认 True 也无副作用）。
    raw_snapshots: [(data_type, payload), ...] —— 与实验在同事务内原子落库（experiment_raw），
    避免先建实验再单独 save raw 的部分写入（孤儿实验）。BLI/AKTA 等需要快照的写入入口走这里。
    goal_id / new_goal（v0.1.1）：保存时挂研究脉络 = 已有 goal 节点 / 新建根 goal；
    二选一互斥，都给时 goal_id 优先。失败时主动删实验（补偿模式），
    避免孤儿实验。返回 dict 增 `goal_node_id` 字段（int | None）。"""
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
    # v0.1.1：从实验自然产生研究脉络（入口生死线）
    # 设计原则：节点关联是 best-effort——失败时 log warning 但**不删实验**、返回 goal_node_id=None。
    # 旧版（v0.1.1 初版）走补偿删实验，结果：(a) raw 留底成孤儿 (FK SET NULL)；
    # (b) 用户为「选目标」付选择成本，整实验丢失，破坏「零摩擦」原则。
    # 研究脉络是实验的副产物——实验优先落库，节点补建失败不致命。
    exp_dict = models.exp_get(eid)
    exp_dict["goal_node_id"] = None
    if goal_id is not None or new_goal:
        try:
            exp_dict["goal_node_id"] = _attach_goal_node(
                eid, title, goal_id=goal_id, new_goal=new_goal)
        except ValueError as err:
            # 业务级失败（goal 不存在 / 白名单拦截 / 标题为空等）—— 静默降级为不挂节点
            import logging
            logging.warning("create_experiment 挂研究脉络失败 (exp_id=%s): %s", eid, err)
    return exp_dict


def _attach_goal_node(exp_id: int, exp_title: str,
                      goal_id: int | None = None,
                      new_goal: dict | None = None) -> int:
    """为已存实验挂一个 experiment 节点到 goal 下，返回该节点 id。
    goal_id 路径：直接挂；new_goal 路径：先建根 goal 节点，再挂 experiment 节点。
    失败抛 ValueError（业务级：goal 不存在 / 白名单不允许 / 标题为空等）。

    new_goal 路径的两步创建若第二步失败，会主动 delete_subtree 回滚第一步建的根 goal，
    避免孤儿根 goal 节点。
    """
    if not goal_id and not new_goal:
        raise ValueError("需要 goal_id 或 new_goal 之一")
    if goal_id is not None:
        g = models.research_node_get(goal_id)
        if not g:
            raise ValueError(f"goal 节点 {goal_id} 不存在")
        if g.get("node_type") != "goal":
            raise ValueError(f"节点 {goal_id} 不是目标节点（{g.get('node_type')}），只能挂到目标下")
        parent_id = goal_id
    else:
        ng_title = (new_goal.get("title") or "").strip()
        if not ng_title:
            raise ValueError("新建目标标题不能为空")
        ng_tag = (new_goal.get("tag") or "").strip()
        nid, err = research.create_node(
            node_type="goal", title=ng_title, tag=ng_tag, free_attach=False)
        if not nid:
            raise ValueError(f"创建 goal 节点失败: {err}")
        parent_id = nid
    enid, err = research.create_node(
        node_type="experiment", title=exp_title, exp_id=exp_id,
        parent_id=parent_id, free_attach=False)
    if not enid:
        # new_goal 路径下回滚第一步建的根 goal（避免孤儿根 goal 节点）
        if not goal_id and parent_id:
            try:
                models.research_node_delete_subtree(parent_id)
            except Exception:
                import logging
                logging.exception("清理孤儿根 goal 失败 (node_id=%s)", parent_id)
        raise ValueError(f"挂 experiment 节点失败: {err}")
    return enid


def attach_goal(exp_id: int, goal_id: int) -> dict:
    """实验详情页「+ 关联到其他目标」：为已存实验追加一个 experiment 节点到指定 goal 下。

    返回 {"node_id": 新建 experiment 节点 id, "goal_id": goal_id, "experiment_id": exp_id}。
    失败返 None（前端统一按 falsy 处理）。
    """
    exp = models.exp_get(exp_id)
    if not exp:
        return None
    title = exp.get("title") or f"实验 #{exp_id}"
    try:
        enid = _attach_goal_node(exp_id, title, goal_id=goal_id, new_goal=None)
    except ValueError:
        return None
    if not enid:
        return None
    return {"node_id": enid, "goal_id": goal_id, "experiment_id": exp_id}
