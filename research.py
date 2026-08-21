"""
研究脉络 service 层（v0.1.0）— 证据链：目标→(拆解)子目标/实验→(得出)结论→(引出)新目标。

业务规则集中在这（Workbench 定位：AI 可读的证据链，不做项目管理）：
  - 三节点类型 goal/experiment/conclusion；单亲树、可自由重挂；多根目标
  - 白名单边：goal→{goal,experiment}、experiment→conclusion、conclusion→goal
    ——跨边不合法，除非勾「自由挂载」(free_attach) 逃生舱打破（不做跨分支共享，
      真 DAG 留后续）
  - 根必须是目标（goal）；experiment 块 = 实验引用（exp_id）或计划占位（exp_id 空）
  - 删节点级联删整棵子树（前端需确认）；删实验断链保留节点（FK SET NULL）

SQL 全在 models.py；这里只做校验 / 建树 / 序列化（纯逻辑，可独立单测）。
"""
import models

RESEARCH_NODE_TYPES = models.RESEARCH_NODE_TYPES
NODE_TYPE_LABELS = {"goal": "目标", "experiment": "实验", "conclusion": "结论"}

# 白名单边：父类型 → 允许的子类型集合。加子块勾「自由挂载」可打破任一边。
WHITELIST = {
    "goal": {"goal", "experiment"},
    "experiment": {"conclusion"},
    "conclusion": {"goal"},
}


def _as_bool(v) -> bool:
    """宽松布尔强转：True/"true"/"1"/"yes"/"on" → True，其余 → False。

    评审修复（P3-3）：API 边界可能收到字符串 "false"——`bool("false")` 是 True
    会误触白名单逃生舱，这里按真实语义解析。
    """
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def _coerce_id(v, field: str):
    """parent_id/exp_id 强转 int；None/''→None；非法→ValueError（调用方转 err）。

    评审修复（P3-3）：字符串 "5" 直接存库会成 TEXT，build_trees 按 int 键拼树时
    对不上（by_id.get("5") miss）→ 节点显示成孤立根。这里统一收口强转。
    """
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{field} 应为整数，收到 {v!r}")


def _normalize_tag(tag) -> str:
    """标签规范化：逐项 trim 去空，逗号连接（立场词匹配依赖无空格存储）。"""
    if not tag:
        return ""
    return ",".join(t.strip() for t in str(tag).split(",") if t.strip())


def _parent_label(t: str | None) -> str:
    return NODE_TYPE_LABELS.get(t or "", t or "根")


def _check_new_edge(parent: dict | None, node_type: str, free_attach: bool) -> str:
    """校验 (parent, node_type) 边是否合法，返回错误串（空串=合法）。

    parent=None 表示挂为根：根必须是目标（goal）。free_attach 逃生舱直接放行。
    """
    if free_attach:
        return ""
    if parent is None:
        if node_type != "goal":
            return f"根节点必须是目标（goal），「{NODE_TYPE_LABELS.get(node_type, node_type)}」要挂在已有节点下"
        return ""
    allowed = WHITELIST.get(parent["node_type"], set())
    if node_type not in allowed:
        return (f"白名单不允许「{_parent_label(parent['node_type'])}」直接挂"
                f"「{NODE_TYPE_LABELS.get(node_type, node_type)}」"
                f"（可勾「自由挂载」逃生舱打破）")
    return ""


def _sort_tail(sibs: list[dict], exclude_id: int = None) -> int:
    """取兄弟列表下一个 sort_order（排除 exclude_id 后取 max+1）。"""
    orders = [s.get("sort_order", 0) for s in sibs if s.get("id") != exclude_id]
    return (max(orders) + 1) if orders else 0


def create_node(node_type: str, title: str, detail: str = "",
                parent_id: int = None, exp_id: int = None, tag: str = "",
                free_attach: bool = False) -> tuple[int | None, str]:
    """新建研究节点。返回 (node_id, "") 或 (None, error)。"""
    try:
        parent_id = _coerce_id(parent_id, "parent_id")
        exp_id = _coerce_id(exp_id, "exp_id")
    except ValueError as e:
        return None, str(e)
    if node_type not in RESEARCH_NODE_TYPES:
        return None, f"未知节点类型: {node_type}"
    if not title or not title.strip():
        return None, "标题不能为空"
    # exp_id=0 也进校验（P3-4：0 会被 `if exp_id and` 当 falsy 绕过，静默存库当计划占位）
    if exp_id is not None and not models.exp_get(exp_id):
        return None, f"关联实验 {exp_id} 不存在"
    parent = models.research_node_get(parent_id) if parent_id is not None else None
    if parent_id is not None and parent is None:
        return None, f"父节点 {parent_id} 不存在"
    err = _check_new_edge(parent, node_type, _as_bool(free_attach))
    if err:
        return None, err
    sibs = (models.research_node_children(parent_id) if parent
            else models.research_nodes_root())
    nid = models.research_node_create(
        node_type=node_type, title=title.strip(), detail=detail,
        parent_id=parent_id, exp_id=exp_id, tag=_normalize_tag(tag),
        free_attach=_as_bool(free_attach), sort_order=_sort_tail(sibs))
    return nid, ""


def update_node(node_id: int, node_type: str, title: str, detail: str = "",
                parent_id: int = None, exp_id: int = None, tag: str = "",
                free_attach: bool = False) -> tuple[bool, str]:
    """全量更新研究节点（前端提交完整对象）。重挂（父变化）时重校验白名单并重排。"""
    try:
        parent_id = _coerce_id(parent_id, "parent_id")
        exp_id = _coerce_id(exp_id, "exp_id")
    except ValueError as e:
        return False, str(e)
    node = models.research_node_get(node_id)
    if not node:
        return False, "节点不存在"
    if node_type not in RESEARCH_NODE_TYPES:
        return False, f"未知节点类型: {node_type}"
    if not title or not title.strip():
        return False, "标题不能为空"
    # exp_id=0 也进校验（P3-4，同 create_node）
    if exp_id is not None and not models.exp_get(exp_id):
        return False, f"关联实验 {exp_id} 不存在"
    parent = models.research_node_get(parent_id) if parent_id is not None else None
    if parent_id is not None and parent is None:
        return False, f"父节点 {parent_id} 不存在"
    err = _check_new_edge(parent, node_type, _as_bool(free_attach))
    if err:
        return False, err
    # 防环（P2-2）：新父不能是自身或其任何后代——沿新父链上溯，遇 node_id 即环。
    # 白名单可能被 free_attach 逃生舱打破，防环是其上的硬兜底；否则树成环后
    # _collect_subtree / research_node_delete_subtree 死循环、/api/research/nodes 序列化 500
    # （get_chain/_depth_in_subtree 已有 seen，这里补齐）。
    if parent_id != node.get("parent_id") and parent_id is not None:
        cur, seen = parent_id, set()
        while cur is not None and cur not in seen:
            if cur == node_id:
                return False, "不能把节点挂到自身或其子树下（会成环）"
            seen.add(cur)
            p = models.research_node_get(cur)
            cur = p["parent_id"] if p else None
    if parent_id != node.get("parent_id"):
        sibs = (models.research_node_children(parent_id) if parent
                else models.research_nodes_root())
        sort_order = _sort_tail(sibs, exclude_id=node_id)
    else:
        sort_order = node.get("sort_order", 0)
    models.research_node_update(
        node_id, node_type=node_type, title=title.strip(), detail=detail,
        parent_id=parent_id, exp_id=exp_id, tag=_normalize_tag(tag),
        free_attach=_as_bool(free_attach), sort_order=sort_order)
    return True, ""


def delete_node_subtree(node_id: int) -> tuple[int, str]:
    """删除节点及其整棵子树（删子树由前端弹确认）。返回 (删除节点数, "")。"""
    if not models.research_node_get(node_id):
        return 0, "节点不存在"
    return models.research_node_delete_subtree(node_id), ""


def move_node(node_id: int, direction: str) -> tuple[bool, str]:
    """同级内上移/下移一位（direction: 'up'/'down'）。

    交换后对全部兄弟重排 normalize 成 0..n-1--顺带修复历史 sort_order 撞号
    （直接 models.research_node_create 建的节点 sort_order 全是 0，
    撞号时同级显示序退化为按 id 排）。
    """
    if direction not in ("up", "down"):
        return False, "direction 应为 'up' 或 'down'"
    node = models.research_node_get(node_id)
    if not node:
        return False, "节点不存在"
    sibs = (models.research_node_children(node["parent_id"])
            if node["parent_id"] is not None else models.research_nodes_root())
    ids = [s["id"] for s in sibs]
    if node_id not in ids:
        return False, "节点不在同级列表中"
    i = ids.index(node_id)
    j = i - 1 if direction == "up" else i + 1
    if j < 0 or j >= len(ids):
        return False, "已在同级" + ("首位" if direction == "up" else "末位") + "，无法移动"
    ids[i], ids[j] = ids[j], ids[i]
    for k, sid in enumerate(ids):
        models.research_node_update(sid, sort_order=k)
    return True, ""


def _node_public(n: dict) -> dict:
    """节点公开形态：free_attach 归一为 bool，附中文类型标签（供前端/JSON 消费）。"""
    return {**n, "free_attach": bool(n.get("free_attach")),
            "node_type_label": NODE_TYPE_LABELS.get(n.get("node_type"), n.get("node_type"))}


def build_trees() -> list[dict]:
    """森林序列化：全部根目标，每棵递归嵌套 children（按 sort_order 排序）。"""
    nodes = [_node_public(n) for n in models.research_nodes_all()]
    by_id = {n["id"]: n for n in nodes}
    roots = []
    for n in nodes:
        n["children"] = []
    for n in nodes:
        p = by_id.get(n["parent_id"])
        (p["children"] if p is not None else roots).append(n)
    for n in nodes:
        n["children"].sort(key=lambda c: (c.get("sort_order", 0), c.get("id", 0)))
    roots.sort(key=lambda r: (r.get("sort_order", 0), r.get("id", 0)))
    return roots


def _attach_subtree(node: dict) -> dict:
    """给节点挂上递归 children（原地改造并返回）。

    递归传下来的 `_node_public(c)` 是浅拷贝，没有 children 键——先 setdefault 再挂。
    """
    children = [models.research_node_get(c["id"])
                for c in models.research_node_children(node["id"])]
    children = [c for c in children if c]
    node.setdefault("children", [])
    for c in children:
        node["children"].append(_attach_subtree(_node_public(c)))
    node["children"].sort(key=lambda c: (c.get("sort_order", 0), c.get("id", 0)))
    return node


def get_node_with_subtree(node_id: int) -> dict | None:
    """节点 + 递归子树 + 实验摘要（供详情/链视图/MCP）。"""
    node = models.research_node_get(node_id)
    if not node:
        return None
    node = _node_public(node)
    node["children"] = []
    _attach_subtree(node)
    if node.get("exp_id"):
        e = models.exp_get(node["exp_id"])
        if e:
            node["experiment"] = {"id": e["id"], "title": e["title"],
                                  "exp_type": e["exp_type"], "date": e.get("date", "")}
    return node


def get_chain(node_id: int) -> list[dict] | None:
    """根→节点的 breadcrumb（链视图「串联」可视化）。防环兜底。"""
    node = models.research_node_get(node_id)
    if not node:
        return None
    chain = []
    seen = set()
    cur = node
    while cur and cur["id"] not in seen:
        seen.add(cur["id"])
        chain.append({"id": cur["id"], "node_type": cur["node_type"],
                      "node_type_label": NODE_TYPE_LABELS.get(cur["node_type"], cur["node_type"]),
                      "title": cur["title"]})
        pid = cur["parent_id"]
        if pid is None:
            break
        cur = models.research_node_get(pid)
    chain.reverse()
    return chain


# ── v0.1.2 研究上下文聚合（MCP get_research_context）──────────────────
# 立场词（epistemic status）复用 research_nodes.tag CSV 字段，这里只做词→key 映射。

STANCE_KEYWORDS = {"支持": "support", "反驳": "rebut", "部分": "partial", "不确定": "uncertain"}
STANCE_LABELS = {key: label for label, key in STANCE_KEYWORDS.items()}


def res_stance_key(tag: str) -> str:
    """立场词 → key。镜像 static/app.js resStanceKey：按 tag 序取第一个命中词（逐项 trim），
    无命中返回 ''。

    评审修复（P2-1）：旧实现按关键词序遍历且不 trim——(a) `数据, 支持`（逗号后空格）
    拆出 `["数据"," 支持"]` 匹配不到 → MCP 报空立场而 UI 显示「支持」；(b) 多立场词
    `不确定, 支持` 旧实现优先取「支持」（关键词序），前端按 tag 序取「不确定」。
    这里与前端逐字对齐。
    """
    for t in (tag or "").split(","):
        t = t.strip()
        if t in STANCE_KEYWORDS:
            return STANCE_KEYWORDS[t]
    return ""


def _collect_subtree(root_id: int) -> list[dict]:
    """扁平收集根节点及其全部后代（BFS 栈，seen 防环兜底，仿 research_node_delete_subtree）。"""
    out = []
    stack = [root_id]
    seen = set()
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        n = models.research_node_get(nid)
        if not n:
            continue
        out.append(n)
        stack.extend(c["id"] for c in models.research_node_children(nid))
    return out


def _depth_in_subtree(root_id: int, target_id: int) -> int:
    """target 相对 root 的层级（root 自身 = 0）。沿 parent 链数到 root，防环兜底。"""
    depth, cur = 0, target_id
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        if cur == root_id:
            return depth
        n = models.research_node_get(cur)
        if not n or n["parent_id"] is None:
            break
        cur, depth = n["parent_id"], depth + 1
    return depth


def get_research_context(goal_id: int) -> dict | None:
    """研究目标上下文聚合（v0.1.2，MCP get_research_context）。

    给 AI 一次拿到「一个研究目标」的证据链：goal 本体 + 父目标链 + 子树实验
    key results（完整 params/results + raw 快照元数据）+ 结论 epistemic status
    （立场 + 来源实验是否归档）+ 开放目标（子树内无结论的目标）。

    定位（Workbench）：给数据 + 轻量事实信号，判断留给 AI——不代做结论。
    返回 None = 目标不存在；节点存在但非 goal → raise ValueError（MCP 层转 -32602）。
    """
    root = models.research_node_get(goal_id)
    if not root:
        return None
    if root["node_type"] != "goal":
        raise ValueError(
            f"get_research_context: goal_id {goal_id} 不是目标节点"
            f"（{NODE_TYPE_LABELS.get(root['node_type'], root['node_type'])}），"
            f"研究上下文按目标聚合")

    nodes = _collect_subtree(goal_id)
    by_id = {n["id"]: n for n in nodes}

    # ── 子树实验：归档给完整 exp 块（params/results + raw 快照元数据），计划占位只给标志 ──
    experiments = []
    for n in nodes:
        if n["node_type"] != "experiment":
            continue
        entry = {"node_id": n["id"], "title": n["title"], "detail": n["detail"],
                 "tag": n["tag"], "exp_id": n["exp_id"], "planned": n["exp_id"] is None}
        if n["exp_id"]:
            e = models.exp_get(n["exp_id"])
            if e:
                entry["exp"] = {
                    "id": e["id"], "title": e["title"], "exp_type": e["exp_type"],
                    "date": e.get("date", ""), "protein_names": e.get("protein_names", ""),
                    "params": e.get("params"), "results": e.get("results"),
                    "notes": e.get("notes", ""),
                    "_raw": models.exp_raw_list(e["id"], with_version=True),
                }
                entry["exp"]["_raw_count"] = len(entry["exp"]["_raw"])
                try:
                    import compare as _compare
                    import identity as _identity
                    entry["exp"]["calc_type"] = _identity.infer_calc_type(e)
                    entry["exp"]["key_results"] = _compare.key_results(e)
                except Exception:
                    pass
        experiments.append(entry)

    # ── 结论 epistemic status：立场（tag 首个命中词）+ 来源实验（父节点）──
    conclusions = []
    for n in nodes:
        if n["node_type"] != "conclusion":
            continue
        stance_key = res_stance_key(n["tag"])
        parent = by_id.get(n["parent_id"]) if n["parent_id"] is not None else None
        source_exp_id = (parent["exp_id"] if parent and parent["node_type"] == "experiment"
                         else None)
        source_exp = models.exp_get(source_exp_id) if source_exp_id else None
        conclusions.append({
            "node_id": n["id"], "title": n["title"], "detail": n["detail"], "tag": n["tag"],
            "stance": {"key": stance_key, "label": STANCE_LABELS.get(stance_key, "")},
            "source_exp_id": source_exp_id,
            "source_archived": source_exp_id is not None,
            "source_exp_title": source_exp["title"] if source_exp else "",
            "parent_title": parent["title"] if parent else "",
        })

    # ── goal 节点：有无结论 / 归档·计划实验计数（开放目标 = 子树内无结论）──
    # 子树统计用本地 children_map DFS，避免对每个 goal 重复 _collect_subtree
    # （P4-5：旧实现对每个 goal 一轮全子树 DB 查询，O(G×N) 次连接且根查两遍）。
    children_map: dict[int | None, list[int]] = {}
    for n in nodes:
        children_map.setdefault(n["parent_id"], []).append(n["id"])

    def _subtree_ids(root_id: int) -> set[int]:
        seen, stack = set(), [root_id]
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            stack.extend(children_map.get(nid, []))
        return seen

    goal_nodes = []
    for n in nodes:
        if n["node_type"] != "goal":
            continue
        sub = [by_id[i] for i in _subtree_ids(n["id"])]
        goal_nodes.append({
            "id": n["id"], "title": n["title"], "detail": n["detail"], "tag": n["tag"],
            "node_type_label": NODE_TYPE_LABELS["goal"],
            "has_conclusion": any(x["node_type"] == "conclusion" for x in sub),
            "archived_experiments": sum(1 for x in sub
                                        if x["node_type"] == "experiment" and x["exp_id"]),
            "planned_experiments": sum(1 for x in sub
                                       if x["node_type"] == "experiment" and not x["exp_id"]),
        })
    open_goals = [
        {"id": gn["id"], "title": gn["title"], "tag": gn["tag"],
         "depth": _depth_in_subtree(goal_id, gn["id"])}
        for gn in goal_nodes if not gn["has_conclusion"]
    ]

    archived = sum(1 for x in experiments if not x["planned"])
    return {
        "goal": _node_public(root),
        "parent_chain": get_chain(goal_id),
        "subtree": {
            "goal_nodes": goal_nodes,
            "experiments": experiments,
            "conclusions": conclusions,
        },
        "open_goals": open_goals,
        "stats": {
            "goals": len(goal_nodes),
            "experiments": len(experiments),
            "planned": len(experiments) - archived,
            "archived": archived,
            "conclusions": len(conclusions),
            "open_goals": len(open_goals),
        },
    }
