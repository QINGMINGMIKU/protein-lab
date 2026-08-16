"""test_research.py — 研究脉络（v0.1.0）service 层 + API + MCP 读契约回归（assert 脚本）

跑法（必须用 venv python）：
    .venv/Scripts/python.exe test_research.py

覆盖：
1. 白名单边：goal→{goal,experiment}、experiment→conclusion、conclusion→goal 放行
2. 白名单拦截：goal→conclusion / experiment→experiment / conclusion→experiment 等拒绝
3. 根必须是目标（goal）：experiment/conclusion 挂根拒绝
4. 逃生舱 free_attach：打破白名单放行
5. exp_id 校验：引用不存在实验拒绝
6. 级联删除子树：删根连带删除全部后代，返回删除数
7. build_trees 森林序列化（嵌套结构 + 排序）
8. 删实验断链：exp_id FK SET NULL，节点保留
9. 同级排序：sort_order 自动追加
10. 更新重挂：白名单拦截 + free_attach 放行 + 换父重排
11. API：/api/research/nodes 增查改删 + 白名单 400
12. MCP 读工具零写库（list_research_trees / get_research_node）
13. /research 页面渲染（流程图容器 #researchFlow）

数据安全：数据库用临时目录，不触碰生产库（见 CLAUDE.md 测试规范）。
"""
import os, sys, json, importlib, tempfile, contextlib, io, sqlite3

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import models
importlib.reload(models)  # ⚠ 会把 DB_PATH 重置为真实路径（测试规范要求）
TMP = tempfile.mkdtemp(prefix="protein_lab_research_")
models.DB_PATH = os.path.join(TMP, "test.db")
models.init_db()
import research
import mcp_server


def dump_db():
    conn = sqlite3.connect(models.DB_PATH)
    conn.row_factory = sqlite3.Row
    out = {}
    for (tname,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        rows = conn.execute(f'SELECT * FROM "{tname}"').fetchall()
        out[tname] = [dict(r) for r in rows]
    conn.close()
    return out


# ── 1. 白名单边放行 ──
g = models.research_node_create(node_type="goal", title="根目标", sort_order=0)
ok, err = research.create_node("goal", "子目标", parent_id=g)
assert ok and not err, f"goal→goal 应放行: {err}"
sub_g = ok
ok, err = research.create_node("experiment", "实验1", parent_id=g)
assert ok and not err, f"goal→experiment 应放行: {err}"
exp1 = ok
ok, err = research.create_node("conclusion", "结论1", parent_id=exp1)
assert ok and not err, f"experiment→conclusion 应放行: {err}"
conc1 = ok
ok, err = research.create_node("goal", "新目标", parent_id=conc1)
assert ok and not err, f"conclusion→goal 应放行: {err}"
print("1. 白名单放行边 OK")

# ── 2. 白名单拦截 ──
for bad_type in ("conclusion",):
    ok, err = research.create_node(bad_type, "bad", parent_id=g)
    assert ok is None and "白名单" in err, f"goal→{bad_type} 应被拦截: {err}"
for bad_type in ("experiment", "goal"):
    ok, err = research.create_node(bad_type, "bad", parent_id=exp1)
    assert ok is None and "白名单" in err, f"experiment→{bad_type} 应被拦截: {err}"
for bad_type in ("experiment", "conclusion"):
    ok, err = research.create_node(bad_type, "bad", parent_id=conc1)
    assert ok is None and "白名单" in err, f"conclusion→{bad_type} 应被拦截: {err}"
print("2. 白名单拦截 OK")

# ── 3. 根必须是目标 ──
for bad_type in ("experiment", "conclusion"):
    ok, err = research.create_node(bad_type, "bad-root")
    assert ok is None and "根节点必须" in err, f"{bad_type} 挂根应拒绝: {err}"
print("3. 根必须为目标 OK")

# ── 4. 逃生舱 free_attach ──
ok, err = research.create_node("conclusion", "非常规结论", parent_id=g, free_attach=True)
assert ok and not err, f"free_attach 应打破白名单: {err}"
ok, err = research.create_node("experiment", "非常规实验", parent_id=exp1, free_attach=True)
assert ok and not err, f"free_attach 应打破白名单(experiment): {err}"
assert models.research_node_get(ok)["free_attach"] == 1, "free_attach 应落库为 1"
print("4. 逃生舱 free_attach OK")

# ── 5. exp_id 校验 ──
ok, err = research.create_node("experiment", "坏引用", parent_id=g, exp_id=99999)
assert ok is None and "关联实验" in err, f"引用不存在实验应拒绝: {err}"
print("5. exp_id 校验 OK")

# ── 6. 级联删除子树 ──
# 树：goalA → [goalB → [experiment → [conclusion]]]（目标删根应连带删 4 个后代）
ga = research.create_node("goal", "A")[0]
gb = research.create_node("goal", "B", parent_id=ga)[0]
ge = research.create_node("experiment", "E", parent_id=gb)[0]
gc = research.create_node("conclusion", "C", parent_id=ge)[0]
count, err = research.delete_node_subtree(ga)
assert not err and count == 4, f"删子树应返回 4: {count} {err}"
assert all(models.research_node_get(x) is None for x in (ga, gb, ge, gc)), "子树应全部删除"
print("6. 级联删除子树 OK")

# ── 7. build_trees 森林序列化 ──
trees = research.build_trees()
roots = [t["id"] for t in trees]
assert g in roots, f"根目标应出现在森林: {roots}"
root = next(t for t in trees if t["id"] == g)
assert any(c["id"] == sub_g for c in root["children"]), "子目标应嵌套在根下"
assert any(c["id"] == exp1 for c in root["children"]), "实验应嵌套在根下"
e1_node = next(c for c in root["children"] if c["id"] == exp1)
assert any(c["id"] == conc1 for c in e1_node["children"]), "结论应嵌套在实验下"
assert root["free_attach"] is False and "node_type_label" in root, "公开形态应带 label/布尔 free_attach"
print("7. build_trees 森林序列化 OK")

# ── 8. 删实验断链（FK SET NULL，节点保留）──
eid = models.exp_create(title="断链实验", exp_type="BLI", params={}, results={})
link = research.create_node("experiment", "引用实验", parent_id=g, exp_id=eid)[0]
assert models.research_node_get(link)["exp_id"] == eid, "应建立实验引用"
models.exp_delete(eid)
assert models.exp_get(eid) is None
assert models.research_node_get(link)["exp_id"] is None, "删实验后 exp_id 应置 NULL（节点保留）"
print("8. 删实验断链（FK SET NULL）OK")

# ── 9. 同级排序：sort_order 自动追加 ──
s1 = research.create_node("goal", "sib1", parent_id=g)[0]
s2 = research.create_node("goal", "sib2", parent_id=g)[0]
s3 = research.create_node("goal", "sib3", parent_id=g)[0]
order = [n["id"] for n in models.research_node_children(g)]
rel = [x for x in order if x in (s1, s2, s3)]
assert rel == [s1, s2, s3], f"同级应按 sort_order 升序: {order}"
print("9. 同级排序 OK")

# ── 10. 更新重挂：白名单拦截 + free_attach 放行 + 换父重排 ──
# 把 conclusion 重挂到另一个 experiment 下（合法）
ok, err = research.update_node(conc1, "conclusion", "结论1改", parent_id=exp1)
assert ok and not err, f"conclusion 重挂 experiment 应放行: {err}"
# 把 experiment 重挂到 conclusion 下（白名单拦截）
ok, err = research.update_node(exp1, "experiment", "实验1改", parent_id=conc1)
assert ok is False and "白名单" in err, f"experiment 挂 conclusion 应拦截: {err}"
# 加逃生舱后放行
ok, err = research.update_node(exp1, "experiment", "实验1改", parent_id=conc1, free_attach=True)
assert ok and not err, f"free_attach 重挂应放行: {err}"
assert models.research_node_get(exp1)["parent_id"] == conc1, "应已重挂到 conclusion 下"
# 重挂回 g（goal）→ 应排在 g 子节点末尾
ok, err = research.update_node(exp1, "experiment", "实验1改", parent_id=g)
assert ok and not err, f"重挂回 goal 应放行: {err}"
g_children = [n["id"] for n in models.research_node_children(g)]
assert g_children[-1] == exp1, f"重挂应追加到目标子节点末尾: {g_children}"
print("10. 更新重挂 OK")

# ── 11. API 增查改删 ──
from app import app
client = app.test_client()
r = client.post("/api/research/nodes", json={
    "node_type": "goal", "title": "API目标", "tag": "api"})
assert r.status_code == 201, f"创建应 201: {r.status_code} {r.get_json()}"
api_gid = r.get_json()["id"]
r = client.post("/api/research/nodes", json={
    "node_type": "conclusion", "title": "坏挂", "parent_id": api_gid})
assert r.status_code == 400, f"白名单违规应 400: {r.status_code}"
r = client.get(f"/api/research/nodes/{api_gid}")
assert r.status_code == 200 and r.get_json()["chain"] == [{"id": api_gid,
    "node_type": "goal", "node_type_label": "目标", "title": "API目标"}], "GET 应带链视图"
r = client.get("/api/research/nodes")
assert r.status_code == 200 and any(t["id"] == api_gid for t in r.get_json()), "列表应含新根"
# 递归子树路径（回归：_attach_subtree 曾因递归传浅拷贝缺 children 键 KeyError）
r = client.get(f"/api/research/nodes/{g}")
rj = r.get_json()
assert r.status_code == 200 and rj.get("children") is not None, "GET 有子节点应带 children"
assert len(rj["children"]) == len(models.research_node_children(g)), "children 数应等于直接子节点数"
r = client.put(f"/api/research/nodes/{api_gid}", json={
    "node_type": "goal", "title": "API目标改", "parent_id": None, "tag": "api"})
assert r.status_code == 200 and r.get_json()["title"] == "API目标改", "PUT 应更新"
r = client.delete(f"/api/research/nodes/{api_gid}")
assert r.status_code == 200 and r.get_json()["ok"], "DELETE 应成功"
r = client.get(f"/api/research/nodes/{api_gid}")
assert r.status_code == 404, "删除后应 404"
print("11. API 增查改删 OK")

# ── 12. MCP 读工具零写库 ──
assert {"list_research_trees", "get_research_node"} <= mcp_server.READ_TOOLS, "研究读工具应在 READ_TOOLS"
before = dump_db()
for tool, args in [
    ("list_research_trees", {}),
    ("get_research_node", {"node_id": g}),
    ("get_research_node", {"node_id": 99999}),
]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mcp_server.handle_tools_call(None, {"name": tool, "arguments": args})
    out = buf.getvalue().strip()
    assert out, f"{tool} 应有响应"
    # 错误响应也是非空——解析首行断言非 error（回归：get_research_node 曾因
    # _attach_subtree KeyError 静默走 send_error，仍能通过旧"非空"断言）
    if tool == "get_research_node" and args.get("node_id") == g:
        assert '"error"' not in out, f"get_research_node 应成功返回: {out[:200]}"
        text = json.loads(json.loads(out.split(chr(10))[0])["result"]["content"][0]["text"])
        assert text.get("children"), "有子节点应带递归子树"
    assert dump_db() == before, f"读工具 {tool} 不应写库"
print("12. MCP 读工具零写库 OK")

# ── 13. /research 页面渲染（横向流程图容器）──
r = client.get("/research")
html = r.get_data(as_text=True)
assert r.status_code == 200 and 'id="researchFlow"' in html, "/research 应渲染流程图容器"
assert 'class="res-flow-container"' in html, "流程图容器应有 res-flow-container 样式"
print("13. /research 页面渲染 OK")

print("\n全部研究脉络测试通过 ✓")
