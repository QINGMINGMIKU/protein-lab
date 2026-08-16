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
    if node_type not in RESEARCH_NODE_TYPES:
        return None, f"未知节点类型: {node_type}"
    if not title or not title.strip():
        return None, "标题不能为空"
    if exp_id and not models.exp_get(exp_id):
        return None, f"关联实验 {exp_id} 不存在"
    parent = models.research_node_get(parent_id) if parent_id is not None else None
    if parent_id is not None and parent is None:
        return None, f"父节点 {parent_id} 不存在"
    err = _check_new_edge(parent, node_type, bool(free_attach))
    if err:
        return None, err
    sibs = (models.research_node_children(parent_id) if parent
            else models.research_nodes_root())
    nid = models.research_node_create(
        node_type=node_type, title=title.strip(), detail=detail,
        parent_id=parent_id, exp_id=exp_id, tag=tag,
        free_attach=bool(free_attach), sort_order=_sort_tail(sibs))
    return nid, ""


def update_node(node_id: int, node_type: str, title: str, detail: str = "",
                parent_id: int = None, exp_id: int = None, tag: str = "",
                free_attach: bool = False) -> tuple[bool, str]:
    """全量更新研究节点（前端提交完整对象）。重挂（父变化）时重校验白名单并重排。"""
    node = models.research_node_get(node_id)
    if not node:
        return False, "节点不存在"
    if node_type not in RESEARCH_NODE_TYPES:
        return False, f"未知节点类型: {node_type}"
    if not title or not title.strip():
        return False, "标题不能为空"
    if exp_id and not models.exp_get(exp_id):
        return False, f"关联实验 {exp_id} 不存在"
    parent = models.research_node_get(parent_id) if parent_id is not None else None
    if parent_id is not None and parent is None:
        return False, f"父节点 {parent_id} 不存在"
    err = _check_new_edge(parent, node_type, bool(free_attach))
    if err:
        return False, err
    if parent_id != node.get("parent_id"):
        sibs = (models.research_node_children(parent_id) if parent
                else models.research_nodes_root())
        sort_order = _sort_tail(sibs, exclude_id=node_id)
    else:
        sort_order = node.get("sort_order", 0)
    models.research_node_update(
        node_id, node_type=node_type, title=title.strip(), detail=detail,
        parent_id=parent_id, exp_id=exp_id, tag=tag,
        free_attach=bool(free_attach), sort_order=sort_order)
    return True, ""


def delete_node_subtree(node_id: int) -> tuple[int, str]:
    """删除节点及其整棵子树（删子树由前端弹确认）。返回 (删除节点数, "")。"""
    if not models.research_node_get(node_id):
        return 0, "节点不存在"
    return models.research_node_delete_subtree(node_id), ""


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
