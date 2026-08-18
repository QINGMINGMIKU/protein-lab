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
12. MCP 读工具零写库（list_research_trees / get_research_node / get_research_context）
13. /research 页面渲染（流程图容器 #researchFlow）
14. 立场 tag 操控：写入/替换/清除/跨节点类型（v0.1.2 增量，零 schema 变更）
15. 研究上下文聚合 get_research_context（v0.1.2）：结构/计划占位/开放目标/stance 映射/边界/序列脱敏

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
assert {"list_research_trees", "get_research_node", "get_research_context"} <= mcp_server.READ_TOOLS, \
    "研究读工具应在 READ_TOOLS"
before = dump_db()
for tool, args in [
    ("list_research_trees", {}),
    ("get_research_node", {"node_id": g}),
    ("get_research_node", {"node_id": 99999}),
    ("get_research_context", {"goal_id": g}),
    ("get_research_context", {"goal_id": 99999}),
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
    if tool == "get_research_context" and args.get("goal_id") == g:
        assert '"error"' not in out, f"get_research_context 应成功返回: {out[:200]}"
        text = json.loads(json.loads(out.split(chr(10))[0])["result"]["content"][0]["text"])
        assert text.get("subtree") is not None, "上下文应带 subtree 聚合块"
    assert dump_db() == before, f"读工具 {tool} 不应写库"
print("12. MCP 读工具零写库 OK")

# ── 13. /research 页面渲染（横向流程图容器）──
r = client.get("/research")
html = r.get_data(as_text=True)
assert r.status_code == 200 and 'id="researchFlow"' in html, "/research 应渲染流程图容器"
assert 'id="researchFlowBack"' in html, "应有单根流程图返回栏（根目标列表→流程图）"
assert 'class="res-flow-container"' in html, "流程图容器应有 res-flow-container 样式"
print("13. /research 页面渲染 OK")

# ── 14. 立场 tag 操控（v0.1.2 增量：复用 tag 字段，零 schema 变更）──
# 设计：立场词 ["支持","反驳","部分","不确定"] 混入 tag CSV 字符串；
# 前端 applyStanceToTag 负责「移除旧立场词 + 追加新立场词」。
# 本节直接验证数据层 / API 层数据契约正确（service 层走白名单，连带 parent_id 等
# 必须透传；本节只验 tag 字段读写，绕过 service 走 models 直写）。
STANCE_KEYWORDS = ["支持", "反驳", "部分", "不确定"]

# 14a. 单立场写入：conclusion 节点 tag="支持" → 字段可读出
assert models.research_node_update(conc1, tag="支持")
got = models.research_node_get(conc1)
assert got["tag"] == "支持", f"14a 立场写入后 tag 应等于『支持』: {got['tag']!r}"
print("14a. 单立场写入 OK")

# 14b. 替换：原 tag="支持" + 附加 "PD1"，改 stance 为 "反驳"
# 数据层只负责写入；去重（旧 stance→新 stance）由前端 applyStanceToTag 负责。
models.research_node_update(conc1, tag="PD1,支持")
models.research_node_update(conc1, tag="PD1,反驳")
got = models.research_node_get(conc1)
assert "反驳" in got["tag"], f"14b 新 stance 应写入: {got['tag']!r}"
print("14b. 立场替换（去重由前端）OK")

# 14c. 清除：等价于 tag 里移除所有 stance 词
models.research_node_update(conc1, tag="PD1,BLI")
got = models.research_node_get(conc1)
for kw in STANCE_KEYWORDS:
    assert kw not in got["tag"], f"14c 清除后不应残留 stance 词『{kw}』: {got['tag']!r}"
assert "PD1" in got["tag"] and "BLI" in got["tag"], f"14c 非 stance tag 应保留: {got['tag']!r}"
print("14c. 立场清除（保留非 stance tag）OK")

# 14d. 跨节点类型：experiment 节点也能写 stance 词（数据契约无类型约束；
# UI 仅在 conclusion 节点详情面板显示控件，但不阻塞其他类型 tag 写入）
models.research_node_update(exp1, tag="TIM,支持")
got = models.research_node_get(exp1)
assert "支持" in got["tag"], f"14d experiment 节点 stance 应可读: {got['tag']!r}"
print("14d. 跨节点类型 stance 写入 OK（UI 仅在 conclusion 显示控件）")

# 14e. API 端点 PUT tag 透传：与数据层行为一致（必须带 parent_id 走白名单）
# （前端 researchChangeStance 失败回滚逻辑不在本节；本节验证 API 契约）
conc1_meta = models.research_node_get(conc1)
r = client.put(f"/api/research/nodes/{conc1}", json={
    "tag": "PD1,部分", "title": conc1_meta["title"], "node_type": "conclusion",
    "parent_id": conc1_meta["parent_id"]})
assert r.status_code == 200, f"14e PUT tag 应成功: {r.status_code} {r.get_data(as_text=True)[:200]}"
got = models.research_node_get(conc1)
assert got["tag"] == "PD1,部分", f"14e API PUT 后 tag 应等于『PD1,部分』: {got['tag']!r}"
print("14e. API PUT tag 透传 OK")

# ── 15. 研究上下文聚合 get_research_context（v0.1.2）──
# 数据契约：goal 本体 + 父目标链 + 子树实验 key results + 结论 stance + 开放目标。
# 测试状态：g 子树含 exp1(无 exp_id)/conc1(tag=PD1,部分,父=exp1)/sub_g(无结论)。
def _ctx(gid):
    """直接调 service 层（不走 MCP），返回上下文 dict。"""
    return research.get_research_context(gid)

# 15a. 结构：goal 本体 / 父链 / 归档实验块（含 exp 明细 + raw 快照元数据）/ 结论 stance
arch_eid = models.exp_create(title="浓度测定归档", exp_type="浓度测定",
                             params={"a280": 0.5}, results={"mean_uM": 12.3})
models.exp_save_raw(arch_eid, "test_trace", {"analysis_version": "v-test"})
arch_link = research.create_node("experiment", "归档实验", parent_id=g, exp_id=arch_eid)[0]
ctx_g = _ctx(g)
assert ctx_g["goal"]["id"] == g and ctx_g["goal"]["node_type_label"] == "目标", \
    f"goal 本体应为首节点: {ctx_g['goal']}"
assert ctx_g["parent_chain"][0]["id"] == g and ctx_g["parent_chain"][-1]["id"] == g, \
    f"根目标的父链应为自身: {ctx_g['parent_chain']}"
exp_entry = next(x for x in ctx_g["subtree"]["experiments"] if x["node_id"] == arch_link)
assert not exp_entry["planned"] and exp_entry["exp"]["id"] == arch_eid, \
    f"归档实验应带 exp 块: {exp_entry}"
assert exp_entry["exp"]["results"] == {"mean_uM": 12.3} and exp_entry["exp"]["params"] == {"a280": 0.5}, \
    "key results = 完整 params/results"
assert exp_entry["exp"]["_raw_count"] == 1 and \
    exp_entry["exp"]["_raw"][0]["analysis_version"] == "v-test", \
    f"应带 raw 快照元数据: {exp_entry['exp']['_raw']}"
conc_entry = next(x for x in ctx_g["subtree"]["conclusions"] if x["node_id"] == conc1)
assert conc_entry["stance"] == {"key": "partial", "label": "部分"}, \
    f"结论 stance 应映射 partial: {conc_entry['stance']}"
assert conc_entry["source_exp_id"] is None and not conc_entry["source_archived"], \
    "来源实验未归档 → source_archived=False（AI 据此判缺实验支持）"
print("15a. 上下文结构（goal/父链/实验块/stance）OK")

# 15b. 计划占位：exp_id 空 → planned 标志，无 exp 块
plan_node = research.create_node("experiment", "计划实验", parent_id=g)[0]
plan_entry = next(x for x in _ctx(g)["subtree"]["experiments"] if x["node_id"] == plan_node)
assert plan_entry["planned"] is True and plan_entry["exp_id"] is None and "exp" not in plan_entry, \
    f"计划占位应只带 planned 标志: {plan_entry}"
print("15b. 计划占位 OK")

# 15c. 开放目标：子树内无结论的目标；已下结论的目标不算
fresh_g = research.create_node("goal", "新开放目标")[0]
assert any(x["id"] == fresh_g for x in _ctx(fresh_g)["open_goals"]), "无结论的目标应标记开放"
assert all(x["id"] != g for x in ctx_g["open_goals"]), "已下结论的目标不应开放"
sub_entry = next(x for x in ctx_g["subtree"]["goal_nodes"] if x["id"] == sub_g)
assert sub_entry["has_conclusion"] is False, "子目标无结论 → has_conclusion=False"
print("15c. 开放目标 OK")

# 15d. stance 映射：结论 tag 命中立场词 → key/label（跨类型结论也可写，14d 已证）
sup_conc = research.create_node("conclusion", "支持结论", parent_id=exp1)[0]
models.research_node_update(sup_conc, tag="PD1,支持")
sup_entry = next(x for x in _ctx(g)["subtree"]["conclusions"] if x["node_id"] == sup_conc)
assert sup_entry["stance"] == {"key": "support", "label": "支持"}, \
    f"支持 应映射 support: {sup_entry['stance']}"
assert sup_entry["parent_title"] == "实验1改", f"来源父实验标题应带出: {sup_entry['parent_title']}"
print("15d. stance 映射（支持/部分）OK")

# 15e/15f. 边界：非 goal 报错（MCP 层转 -32602），不存在返回 None
try:
    _ctx(exp1)
    assert False, "非目标节点应 raise ValueError"
except ValueError as err:
    assert "不是目标节点" in str(err), f"报错应说明按目标聚合: {err}"
assert _ctx(99999) is None, "不存在的目标应返回 None"
print("15e/15f. 非 goal / 不存在边界 OK")

# 15g. 序列脱敏：内嵌实验 params 的 sequence 明文不得出 MCP
sec_eid = models.exp_create(title="脱敏实验", exp_type="BLI",
                            params={"sequence": "MKRWASFILLER", "a280": 0.3},
                            results={"mean_uM": 1.2})
research.create_node("experiment", "脱敏挂载", parent_id=g, exp_id=sec_eid)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    mcp_server.handle_tools_call(None, {"name": "get_research_context",
                                        "arguments": {"goal_id": g}})
out = buf.getvalue().strip()
assert '"error"' not in out, f"get_research_context 应成功返回: {out[:200]}"
text = json.loads(json.loads(out.split(chr(10))[0])["result"]["content"][0]["text"])
assert "sequence" not in json.dumps(text, ensure_ascii=False), \
    "get_research_context 不得泄漏序列明文"
assert text["stats"]["archived"] >= 2, f"stats 应累计归档实验: {text['stats']}"
print("15g. MCP 序列脱敏 OK")

print("\n全部研究脉络测试通过 ✓")
