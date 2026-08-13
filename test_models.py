"""test_models.py — models 层数据模型回归测试（assert 脚本）

跑法（必须用 venv python）：
    .venv/Scripts/python.exe test_models.py

覆盖：
1. JSON 往返：exp_create 写 dict → exp_get/exp_list 读回 dict（非字符串）
2. list 型 results 保留（旧浓度格式 results 是数组）
3. 双重编码历史字符串防御性解包
4. exp_update 对 dict 参数自动序列化
5. init_db 幂等（跑两遍无异常、不丢数据）

数据安全：用临时目录隔离库，不触碰生产 protein_lab.db（见 CLAUDE.md 测试规范）。
"""
import os, sys, json, importlib, tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import models
importlib.reload(models)  # ⚠ 会把 DB_PATH 重置为真实路径（测试规范要求）
TMP = tempfile.mkdtemp(prefix="protein_lab_test_")
models.DB_PATH = os.path.join(TMP, "test.db")
models.init_db()
import services


def _seed_protein(name="1YPI_WT", seq="MKRWAS"):
    return models.protein_create(name=name, sequence=seq)


# ── 1. JSON 往返：dict 写入 → dict 读回（不再返回字符串）──
pid = _seed_protein()
eid = models.exp_create(
    title="测试酶活", exp_type="酶活测定", protein_ids=[pid],
    params={"calc_type": "enzyme", "wells": {"A1": {"fit": {"slope": 0.1}}}},
    results={"analysis_version": "linear-dODmin-v1", "wells": {"A1": {"slope": 0.1}}},
    notes="往返测试",
)
e = models.exp_get(eid)
assert e is not None
assert isinstance(e["params"], dict), f"params 应为 dict，实际 {type(e['params'])}"
assert isinstance(e["results"], dict), f"results 应为 dict，实际 {type(e['results'])}"
assert e["params"]["calc_type"] == "enzyme"
assert e["results"]["wells"]["A1"]["slope"] == 0.1
assert e["protein_ids"] == [pid]
print("1. JSON 往返 dict OK")

# ── 2. exp_list 同样反序列化 ──
lst = models.exp_list()
assert lst and isinstance(lst[0]["params"], dict), "exp_list params 应为 dict"
assert isinstance(lst[0]["results"], dict), "exp_list results 应为 dict"
print("2. exp_list 反序列化 OK")

# ── 3. list 型 results 保留（旧浓度格式 results 是数组）──
eid2 = models.exp_create(
    title="旧浓度", exp_type="浓度测定", protein_ids=[pid],
    params={"calc_type": "concentration", "proteins": [{"id": pid, "name": "1YPI_WT"}]},
    results=[{"conc_uM": 5.0, "conc_mg_mL": 0.14}],
)
e2 = models.exp_get(eid2)
assert isinstance(e2["results"], list), f"旧浓度 results 应保留为 list，实际 {type(e2['results'])}"
assert e2["results"][0]["conc_uM"] == 5.0
print("3. list 型 results 保留 OK")

# ── 4. 双重编码历史字符串防御性解包 ──
conn = models.get_db()
inner = json.dumps({"calc_type": "enzyme"})
double = json.dumps(inner)  # 字符串里再编码一层
cur = conn.execute(
    "INSERT INTO experiments (title, exp_type, params, results) VALUES (?,?,?,?)",
    ("双重编码", "酶活测定", double, "{}"),
)
eid3 = cur.lastrowid
conn.commit()
conn.close()
e3 = models.exp_get(eid3)
assert isinstance(e3["params"], dict), f"双重编码应解包为 dict，实际 {type(e3['params'])}"
assert e3["params"]["calc_type"] == "enzyme"
print("4. 双重编码解包 OK")

# ── 5. exp_update 对 dict 参数自动序列化 ──
ok = models.exp_update(eid, params={"calc_type": "enzyme", "note": "改过了"})
assert ok is True
e4 = models.exp_get(eid)
assert isinstance(e4["params"], dict)
assert e4["params"]["note"] == "改过了"
print("5. exp_update 序列化 OK")

# ── 6. init_db 幂等（跑两遍无异常、数据不丢）──
before = models.exp_list()
models.init_db()
after = models.exp_list()
assert len(after) == len(before), "init_db 重跑不应丢数据"
assert all(isinstance(x["params"], dict) for x in after)
print("6. init_db 幂等 OK")

# ── 7. services.create_experiment：统一写入 + 自动命名 + 校验 ──
e7 = services.create_experiment(title="", exp_type="浓度测定", protein_ids=[pid],
                                params={"a": 1}, results={"b": 2})
assert e7["title"].endswith("_浓度测定_01") or "_浓度测定_" in e7["title"], f"自动命名异常: {e7['title']}"
assert e7["params"] == {"a": 1} and e7["results"] == {"b": 2}
# 非法 protein_ids 不抛错，静默过滤（避免 Python 原始错误文本泄漏）
assert services.coerce_int_list(["abc", pid, None, 0, ""]) == [pid], "非 int id 应被过滤"
e7b = services.create_experiment(title="坏ids", exp_type="BLI",
                                 protein_ids=["abc", pid, None, "1.5"])
assert e7b["protein_ids"] == [pid], f"坏 id 应被过滤: {e7b['protein_ids']}"
try:
    services.create_experiment(title="x", exp_type="", params={})
    raise AssertionError("空 exp_type 应抛 ValueError")
except ValueError:
    pass
print("7. services.create_experiment OK")

# ── 8. 三个写入入口都走 services（API 层冒烟）──
from app import app
client = app.test_client()
r = client.post("/api/experiments", json={
    "title": "", "exp_type": "BLI", "protein_ids": [pid],
    "params": {"calc_type": "dilution"}, "results": {"steps": []},
})
assert r.status_code == 201, r.status_code
assert isinstance(r.get_json()["params"], dict), "API 手动写入 params 应为 dict"
r = client.post("/api/experiments/from-calculation", json={
    "title": "", "exp_type": "酶活测定", "protein_ids": [pid],
    "calc_type": "enzyme", "calc_params": {"wells": {}}, "calc_result": {},
})
assert r.status_code == 201, r.status_code
body = r.get_json()
assert body["params"]["calc_type"] == "enzyme", "calc_type 应打进 params"
assert isinstance(body["results"], dict)
print("8. API 写入入口 OK")

# ── 9. exp_type 单一来源：模板下拉从 models.EXP_TYPES 渲染，无硬编码漂移 ──
exp_types = list(models.EXP_TYPES)
assert len(exp_types) >= 6 and "酶活测定" in exp_types, f"EXP_TYPES 缺类型: {exp_types}"
lst = models.exp_list()
assert lst, "应存在实验用于详情页渲染"
for url in ("/experiments", f"/experiments/{lst[0]['id']}"):
    r = client.get(url)
    assert r.status_code == 200, r.status_code
    html = r.get_data(as_text=True)
    for t in exp_types:
        assert f'<option value="{t}">' in html, f"{url} 缺少 exp_type 选项: {t}"
print("9. exp_type 单一来源渲染 OK")

# ── 10. 迁移框架：user_version 正确 + 幂等（重跑不改变任何数据）──
def _db_dump():
    """全表逐行快照，用于断言"库内容逐字节不变"（比行数严格：UPDATE 也能暴露）"""
    conn = models.get_db()
    dump = {}
    for t in ("proteins", "experiments", "experiment_proteins", "experiment_raw"):
        dump[t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
    conn.close()
    return dump

conn = models.get_db()
v = conn.execute("PRAGMA user_version").fetchone()[0]
conn.close()
assert v == models.SCHEMA_VERSION, f"user_version 应={models.SCHEMA_VERSION}，实际 {v}"
before = _db_dump()
models.init_db()  # 再迁移一遍
assert _db_dump() == before, "迁移重跑不应改变任何数据"
print("10. 迁移幂等 OK")

# ── 11. experiment_raw：只插不更 / 删实验不删 raw（FK SET NULL）──
eid_r = services.create_experiment(title="raw测试", exp_type="BLI", protein_ids=[],
                                   params={}, results={})["id"]
rid1 = models.exp_save_raw(eid_r, "bli_curves", {"curves": [[1, 2], [3, 4]]})
rid2 = models.exp_save_raw(eid_r, "bli_curves", {"curves": [[5, 6]]})
assert rid1 != rid2, "重复保存应生成新行（只插不更）"
r1 = models.exp_raw_get(rid1)
assert r1 is not None and r1["payload"] == {"curves": [[1, 2], [3, 4]]}, "旧行 payload 应原样保留"
lst_raw = models.exp_raw_list(eid_r)
assert [x["id"] for x in lst_raw] == [rid1, rid2], "应按 id 升序列出全部快照"
assert all("payload" not in x for x in lst_raw), "列表不应携带大字段"
models.exp_delete(eid_r)
assert models.exp_get(eid_r) is None, "实验应已物理删除（v0.0.7 阶段，软删在 v0.1.0）"
r1 = models.exp_raw_get(rid1)
r2 = models.exp_raw_get(rid2)
assert r1 and r2, "删实验后 raw 必须保留"
assert r1["experiment_id"] is None and r2["experiment_id"] is None, "FK 应置 NULL"
print("11. experiment_raw 只插不更 / 删实验留 raw OK")

# ── 12. get_db(read_only=True)：写操作被 SQLite 拒绝 ──
import sqlite3
ro = models.get_db(read_only=True)
try:
    ro.execute("INSERT INTO experiments (title, exp_type) VALUES ('x','BLI')")
    raise AssertionError("只读连接应拒绝写操作")
except sqlite3.OperationalError:
    pass
finally:
    ro.close()
print("12. get_db read_only 拒绝写 OK")

# ── 13. MCP 读写契约：读工具零写库（逐工具调用后库内容逐字节不变）──
import contextlib, io
import mcp_server
assert mcp_server.WRITE_TOOLS == {"save_experiment"}, f"写工具应仅 save_experiment: {mcp_server.WRITE_TOOLS}"
names = {t["name"] for t in mcp_server.TOOLS}
assert names == mcp_server.READ_TOOLS | mcp_server.WRITE_TOOLS, "每个工具必须归入读或写"
read_cases = [
    ("search_proteins", {"query": "1YPI"}),
    ("get_protein", {"name": "1YPI_WT"}),
    ("list_proteins", {}),
    ("calculate_concentration", {"sequence": "MKRWAS", "a280": 0.5}),
    ("convert_concentration", {"value": 1, "from_unit": "uM", "to_unit": "nM"}),
    ("calculate_dilution", {"stock_conc_uM": 100, "start_conc_uM": 10}),
    ("list_experiments", {}),
]
before = _db_dump()
for tool, args in read_cases:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mcp_server.handle_tools_call(None, {"name": tool, "arguments": args})
    assert buf.getvalue().strip(), f"{tool} 应有响应"
    assert _db_dump() == before, f"读工具 {tool} 不应写库"
print("13. MCP 读工具零写库 OK")

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED")
