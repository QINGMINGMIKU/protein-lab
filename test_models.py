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
assert e7["title"].endswith("_concentration_01") or "_concentration_" in e7["title"], f"自动命名异常: {e7['title']}"
assert e7["params"]["a"] == 1 and e7["results"] == {"b": 2}, "params/results 应透传"
assert e7["params"].get("calc_type") == "concentration"
assert e7["params"].get("proteins") and e7["params"]["proteins"][0]["id"] == pid, "绑定蛋白应附数值快照"
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
assert len(exp_types) >= 6 and "酶活测定" in exp_types and "Weblogo" in exp_types, f"EXP_TYPES 缺类型: {exp_types}"
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
assert mcp_server.WRITE_TOOLS == {"save_experiment", "save_observation",
                                  "save_conclusion", "attach_goal"}, \
    f"写工具应为 save_experiment + save_observation + save_conclusion + attach_goal: {mcp_server.WRITE_TOOLS}"
names = {t["name"] for t in mcp_server.TOOLS}
assert names == mcp_server.READ_TOOLS | mcp_server.WRITE_TOOLS, "每个工具必须归入读或写"
# 13b 前置：种研究脉络节点 + 给 e7 挂一条含序列明文的原始快照（供脱敏断言），
# 供研究/实验读工具返回真实数据（同一快照做零写断言）
_rn_id = models.research_node_create(node_type="goal", title="稳定性优化", tag="稳定性", sort_order=0)
models.research_node_create(node_type="experiment", title="表达纯化",
                            parent_id=_rn_id, exp_id=e7["id"], sort_order=0)
_rn_raw = models.exp_save_raw(e7["id"], "test_trace", {
    "analysis_version": "v-test",
    "params": {"sequence": "MKRWASFILLER"},
    "curves": [[0, 1.0], [1, 2.0]],
})
read_cases = [
    ("search_proteins", {"query": "1YPI"}),
    ("get_protein", {"name": "1YPI_WT"}),
    ("list_proteins", {}),
    ("calculate_concentration", {"sequence": "MKRWAS", "a280": 0.5}),
    ("convert_concentration", {"value": 1, "from_unit": "uM", "to_unit": "nM"}),
    ("calculate_dilution", {"stock_conc_uM": 100, "start_conc_uM": 10}),
    ("list_experiments", {}),
    ("get_experiment", {"exp_id": e7["id"]}),
    ("get_experiment_raw", {"raw_id": _rn_raw}),
    ("list_protein_tags", {}),
    ("list_research_trees", {}),
    ("get_research_node", {"node_id": _rn_id}),
    ("get_research_context", {"goal_id": _rn_id}),
    ("compare_experiments", {"exp_ids": [e7["id"], e7["id"]]}),
    ("get_system_prompt", {}),
]
before = _db_dump()
for tool, args in read_cases:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mcp_server.handle_tools_call(None, {"name": tool, "arguments": args})
    assert buf.getvalue().strip(), f"{tool} 应有响应"
    assert _db_dump() == before, f"读工具 {tool} 不应写库"
print("13. MCP 读工具零写库 OK")

# 序列脱敏收口（IP 保护）：get_protein 不得返回 sequence 明文，只给指纹
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    mcp_server.handle_tools_call(None, {"name": "get_protein", "arguments": {"name": "1YPI_WT"}})
gp = json.loads(buf.getvalue().strip())
gp_text = json.loads(gp["result"]["content"][0]["text"])
assert "sequence" not in gp_text, "get_protein 不得返回序列明文"
assert gp_text.get("sequence_fp"), "get_protein 应返回序列指纹"
assert len(gp_text["sequence_fp"]) == 12, "指纹应为前 12 位"
print("13b. get_protein 序列脱敏（指纹替代明文）OK")

# ── 13c. 参数校验：缺必填/类型错 → -32602，未知工具 → -32601（结构化错误，不泄漏原始异常）──
def _call_mcp(tool, arguments):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mcp_server.handle_tools_call(None, {"name": tool, "arguments": arguments})
    return json.loads(buf.getvalue().strip())

_ge = _call_mcp("get_protein", {})
assert _ge["error"]["code"] == -32602 and "缺少" in _ge["error"]["message"] and "get_protein" in _ge["error"]["message"], \
    f"缺必填应返 -32602: {_ge}"
_ge = _call_mcp("get_experiment", {"exp_id": "abc"})
assert _ge["error"]["code"] == -32602, f"类型错应返 -32602: {_ge}"
_ge = _call_mcp("convert_concentration", {"value": 1, "from_unit": "uM", "to_unit": "ng/uL"})
assert _ge["error"]["code"] == -32602 and "mw" in _ge["error"]["message"], f"跨摩尔质量缺 mw 应返 -32602: {_ge}"
_ge = _call_mcp("nope_tool", {})
assert _ge["error"]["code"] == -32601, f"未知工具应返 -32601: {_ge}"
print("13c. MCP 参数校验错误码（-32602 / -32601）OK")

# ── 13d. 实验读取序列脱敏（IP 保护）：get_experiment / get_experiment_raw 剔除 sequence 明文 ──
_gexp = _call_mcp("get_experiment", {"exp_id": e7["id"]})
_gexp = json.loads(_gexp["result"]["content"][0]["text"])
assert "sequence" not in json.dumps(_gexp, ensure_ascii=False), "get_experiment 不得泄漏序列明文"
assert _gexp["_raw_count"] >= 1 and any(
    r["data_type"] == "test_trace" and r.get("analysis_version") == "v-test" for r in _gexp["_raw"]), \
    "get_experiment._raw 应带原始快照元数据（含分析版本）"
_graw = _call_mcp("get_experiment_raw", {"raw_id": _rn_raw})
_graw = json.loads(_graw["result"]["content"][0]["text"])
assert "sequence" not in json.dumps(_graw, ensure_ascii=False), "get_experiment_raw 不得泄漏序列明文"
assert _graw["payload"]["curves"] == [[0, 1.0], [1, 2.0]], "raw payload 曲线应完整保留"
print("13d. MCP 实验读取序列脱敏 + 快照读取 OK")

# ── 14. 迁移前自动备份：老库升级时留下迁移前快照（P1 修复回归）──
import shutil
sub = os.path.join(TMP, "mig_backup_test")
os.makedirs(sub, exist_ok=True)
bpath = os.path.join(sub, "seed.db")
c = sqlite3.connect(bpath)
c.execute("PRAGMA user_version = 0")
c.executescript("""
    CREATE TABLE proteins (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
        sequence TEXT NOT NULL, mw REAL, nW INTEGER DEFAULT 0, nY INTEGER DEFAULT 0,
        nC INTEGER DEFAULT 0, ext_red REAL, ext_ox REAL, abs_0_1pct REAL,
        tag TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')));
    CREATE TABLE experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        exp_type TEXT NOT NULL, date TEXT DEFAULT (date('now','localtime')),
        params TEXT DEFAULT '{}', results TEXT DEFAULT '{}', notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime')));
    CREATE TABLE experiment_proteins (experiment_id INTEGER NOT NULL, protein_id INTEGER NOT NULL,
        PRIMARY KEY (experiment_id, protein_id));
    INSERT INTO proteins (name, sequence) VALUES ('老库蛋白', 'MKRWAS');
""")
c.commit()
c.close()
saved = models.DB_PATH
models.DB_PATH = bpath
models.init_db()  # 触发迁移：应先生成 pre-migration 备份，再升级主库
bks = sorted([f for f in os.listdir(os.path.join(sub, "backups"))
              if f.startswith("pre-migration_") and f.endswith(".db")])
assert bks, "应生成 pre-migration 备份"
bkc = sqlite3.connect(os.path.join(sub, "backups", bks[-1]))
tabs = [r[0] for r in bkc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
assert "experiment_raw" not in tabs, "备份应是迁移前状态（无 experiment_raw）"
assert bkc.execute("SELECT COUNT(*) FROM proteins").fetchone()[0] == 1, "备份应含老库数据"
assert bkc.execute("PRAGMA user_version").fetchone()[0] == 0, "备份 user_version 应为 0"
bkc.close()
c = sqlite3.connect(bpath)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
assert "experiment_raw" in tabs, "主库应已迁移到含 experiment_raw"
assert c.execute("SELECT COUNT(*) FROM proteins").fetchone()[0] == 1, "迁移不应丢数据"
c.close()
models.DB_PATH = saved
print("14. 迁移前自动备份 OK")

# ── 15. 原子写入：exp_create_with_raw 单事务建实验 + 落 raw（BLI/AKTA save 收敛）──
a_id = services.create_experiment(
    title="原子BLI", exp_type="BLI", protein_ids=[pid],
    params={"smooth_window": 31}, results={"BLI_ANALYSIS_VERSION": "v1"},
    raw_snapshots=[("bli_curves", {"curves": [[1.5, 2.5], [3.5, 4.5]]})],
)["id"]
assert models.exp_get(a_id) is not None, "实验应创建成功"
araw = models.exp_raw_list(a_id)
assert len(araw) == 1 and araw[0]["data_type"] == "bli_curves", "raw 应与实验同事务落库"
a1 = models.exp_raw_get(araw[0]["id"])
assert a1["payload"] == {"curves": [[1.5, 2.5], [3.5, 4.5]]}, "raw payload 应原样"
# 多份 raw 也可
b_id = services.create_experiment(
    title="多raw", exp_type="AKTA", raw_snapshots=[
        ("akta_traces", {"ch": [1]}), ("akta_traces", {"ch": [2]})],
)["id"]
assert len(models.exp_raw_list(b_id)) == 2, "多 raw 快照应一次落库"
# 原子性：raw payload 含不可序列化对象时整个建实验失败，不留孤儿实验
try:
    services.create_experiment(title="坏raw", exp_type="BLI",
                               raw_snapshots=[("bli_curves", {"x": set()})])
    raise AssertionError("不可序列化 raw 应导致整事务回滚")
except (TypeError, ValueError):
    pass
assert all(e["title"] != "坏raw" for e in models.exp_list()), "原子失败不应留孤儿实验"
print("15. 原子写入（exp_create_with_raw）OK")

# ── 16. undo 恢复断链修复：删实验 → raw 孤儿 → exp_raw_relink 重挂回新 id ──
r_id = services.create_experiment(
    title="断链测试", exp_type="BLI",
    raw_snapshots=[("bli_curves", {"curves": [[1, 2]]})])["id"]
r_raw = models.exp_raw_list(r_id)[0]
models.exp_delete(r_id)
orphan = models.exp_raw_get(r_raw["id"])
assert orphan["experiment_id"] is None, "删实验后 raw 应成孤儿（FK SET NULL）"
new_id = models.exp_create(title="断链恢复", exp_type="BLI", params={}, results={})
models.exp_raw_relink([r_raw["id"]], new_id)
relinked = models.exp_raw_get(r_raw["id"])
assert relinked["experiment_id"] == new_id, "relink 后 raw 应挂回新实验"
assert relinked["payload"] == {"curves": [[1, 2]]}, "relink 不得改动 payload"
assert models.exp_raw_list(new_id)[0]["data_type"] == "bli_curves", "新实验应能读到快照"
print("16. exp_raw_relink 断链修复 OK")

# ── 17. exp_update 对 list 型 params/results 序列化（此前仅 dict 序列化，list 直接绑库报错）──
_e17 = models.exp_create(title="list参数", exp_type="BLI", params={}, results={})
assert models.exp_update(_e17, params=[{"x": 1}, {"x": 2}], results=[1, 2, 3])
_r17 = models.exp_get(_e17)
assert _r17["params"] == [{"x": 1}, {"x": 2}], _r17["params"]
assert _r17["results"] == [1, 2, 3], _r17["results"]
print("17. exp_update list 序列化 OK")

# ── 18. undo peek-before-pop：恢复冲突（同名蛋白已存在）时项保留原位，可重试 ──
from app import app as _undo_app
_uc = _undo_app.test_client()
_p18 = models.protein_create(name="UndoConflict", sequence="MK")
assert _uc.delete(f"/api/proteins/{_p18}").status_code == 200
_cnt18 = _uc.get("/api/undo/status").get_json()["count"]
models.protein_create(name="UndoConflict", sequence="MK")   # 造同名冲突
_conf = _uc.post("/api/undo")
assert _conf.status_code == 409, _conf.status_code
assert _uc.get("/api/undo/status").get_json()["count"] == _cnt18, "冲突后 undo 项应保留（peek-before-pop）"
cid = [p["id"] for p in models.protein_list() if p["name"] == "UndoConflict"][0]
models.protein_delete(cid)                                   # 移除冲突 → 可重试恢复
_ok = _uc.post("/api/undo")
assert _ok.status_code == 200 and _ok.get_json()["restored"] == "UndoConflict", _ok.get_json()
assert _uc.get("/api/undo/status").get_json()["count"] == _cnt18 - 1, "恢复成功应 pop 一项"
print("18. undo peek-before-pop OK")

# ── 19. 蛋白快照：任何写入路径都记录「当时绑定的蛋白 + 浓度参数」──
# 19a. MCP 紧凑浓度存档（a280+mw，无 calc_type/proteins）→ 服务端规范成标准形态，详情页可渲染
_legacy = services.create_experiment(
    title="MCP 紧凑浓度", exp_type="浓度测定", protein_ids=[pid], date="2026-08-16",
    params={"a280": 1.94, "path_length_cm": 1, "epsilon_red": 50880,
            "oxidized": False, "mw_da": 53309.8},
    results={"measurements_mg_ml": [2.03, 2.03, 2.03], "mean_mg_ml": 2.03, "mean_uM": 38.13})
_pj = _legacy["params"]
assert _pj.get("calc_type") == "concentration", "紧凑浓度存档应规范出 calc_type=concentration"
assert _pj.get("proteins") and _pj["proteins"][0]["name"] == models.protein_get(pid)["name"], "应规范出含绑定蛋白的 proteins 列表"
assert _pj["proteins"][0]["a280"] == 1.94 and _pj["proteins"][0]["conc_uM"] == 38.13, "proteins 应含 a280/浓度"
_html19a = client.get(f"/experiments/{_legacy['id']}").get_data(as_text=True)
assert 'data-i18n="detail.conc_title"' in _html19a and "38.13" in _html19a, "MCP 紧凑浓度详情页应渲染浓度卡片"
# 19b. 通用绑定快照：无 proteins 的存档（酶活等）也会附上库内蛋白数值快照
_enzyme19 = services.create_experiment(
    title="", exp_type="酶活测定", protein_ids=[pid], date="2026-08-16",
    params={"calc_type": "enzyme", "wells": {}}, results={})
_p19 = _enzyme19["params"].get("proteins")
assert _p19 and _p19[0].get("mw") is not None and "epsilon_ox" in _p19[0], "酶活存档应附蛋白数值快照"
# 19c. Web 存档已带 proteins（计算工具）→ 不被覆盖
_web19 = services.create_experiment(
    title="", exp_type="浓度测定", protein_ids=[pid], date="2026-08-16",
    params={"calc_type": "concentration",
            "proteins": [{"id": pid, "name": "X", "conc_uM": 9.9}]}, results={})
assert _web19["params"]["proteins"][0]["conc_uM"] == 9.9 and len(_web19["params"]["proteins"]) == 1, "已有 proteins 不应被覆盖"
print("19. 蛋白+浓度快照（MCP 紧凑浓度规范化 / 通用绑定 / 不覆盖已有）OK")

# ── 20. v0.1.1 从实验自然产生研究脉络：保存实验时挂 Goal→Experiment 节点 ──
# 20a. goal_id 路径：已有 goal → 实验自动挂
_gid = models.research_node_create(node_type="goal", title="TIM 变体活性优化", tag="稳定性,TIM")
_exp_a = services.create_experiment(
    title="", exp_type="酶活测定", date="2026-08-17",
    params={"calc_type": "enzyme"}, results={}, goal_id=_gid)
assert _exp_a.get("goal_node_id"), f"goal_id 路径应返回新 experiment 节点 id: {_exp_a}"
_gsub = models.research_node_get(_exp_a["goal_node_id"])
assert _gsub and _gsub["node_type"] == "experiment" and _gsub["exp_id"] == _exp_a["id"], \
    f"挂的 experiment 节点应引用新建实验: {_gsub}"
assert _gsub["parent_id"] == _gid, "experiment 节点应挂在传入的 goal 下"
# 20b. new_goal 路径：自动建根 goal + experiment 节点
_exp_b = services.create_experiment(
    title="", exp_type="浓度测定", date="2026-08-17",
    params={"calc_type": "concentration"}, results={},
    new_goal={"title": "PD1 结合 BLI", "tag": "BLI,PD1"})
assert _exp_b.get("goal_node_id"), f"new_goal 路径应返回新节点: {_exp_b}"
_root_goals = [n for n in models.research_nodes_root() if n["title"] == "PD1 结合 BLI"]
assert len(_root_goals) == 1, f"new_goal 应建一个根 goal 节点: {models.research_nodes_root()}"
_b_node = models.research_node_get(_exp_b["goal_node_id"])
assert _b_node["parent_id"] == _root_goals[0]["id"], "experiment 应挂在新建的 goal 下"
# 20c. 未关联路径：不传 goal 参数 → 零节点新建，实验照常创建
_before_root = len(models.research_nodes_root())
_exp_c = services.create_experiment(
    title="", exp_type="BLI", date="2026-08-17", params={}, results={})
assert _exp_c.get("goal_node_id") is None, "未关联应返回 None"
assert _exp_c["id"] > 0, "实验应照常创建"
assert len(models.research_nodes_root()) == _before_root, "未关联不应创建新节点"
# 20d. 失败 best-effort（H5 修订）：goal_id 不存在 → 静默降级为不挂节点，实验照常创建
# 原则：研究脉络是实验的副产物，节点关联失败不致命；旧版（v0.1.1 初版）补偿删实验
# 会留 raw 孤儿 + 破坏"零摩擦"原则。新版不抛、log warning、实验保留、goal_node_id=None。
_before_ids = {e["id"] for e in models.exp_list()}
import logging as _log
_log.getLogger().setLevel(_log.CRITICAL)  # 静音 WARNING
_exp_d = services.create_experiment(
    title="", exp_type="BLI", date="2026-08-17", params={}, results={},
    goal_id=99999)
_log.getLogger().setLevel(_log.WARNING)
_after_ids = {e["id"] for e in models.exp_list()}
assert _exp_d["goal_node_id"] is None, f"无效 goal_id 应静默降级，goal_node_id 应为 None: {_exp_d}"
assert len(_after_ids) == len(_before_ids) + 1, "实验应照常创建（best-effort 不删实验）"
# 20e. attach_goal：一实验多目标
_exp_e1 = services.create_experiment(
    title="", exp_type="BLI", date="2026-08-17", params={}, results={}, goal_id=_gid)
_extra_gid = models.research_node_create(node_type="goal", title="TIM 寡聚化", tag="TIM")
_att = services.attach_goal(_exp_e1["id"], _extra_gid)
assert _att and _att["node_id"] and _att["goal_id"] == _extra_gid, f"attach_goal 应成功: {_att}"
_subs = models.research_node_children(_gid)
_sub_ids_e1 = [s for s in _subs if s.get("exp_id") == _exp_e1["id"]]
_subs_extra = models.research_node_children(_extra_gid)
_sub_ids_extra = [s for s in _subs_extra if s.get("exp_id") == _exp_e1["id"]]
assert len(_sub_ids_e1) == 1 and len(_sub_ids_extra) == 1, "同一实验应同时挂在两个 goal 下"
# 20f. attach_goal 失败：实验不存在 / goal 不存在
assert services.attach_goal(99999, _gid) is None, "实验不存在应返 None"
assert services.attach_goal(_exp_e1["id"], 99999) is None, "goal 不存在应返 None"
print("20. 从实验自然产生研究脉络（goal_id / new_goal / 未关联 / 失败回滚 / attach_goal）OK")

# ── 21. 酶活存档契约 v2：原始数据只落 raw、手动参数落 params（保证数据可恢复） ──
# 契约（见 CLAUDE.md「存档契约」）：payload = {analysis_version, calc_type, params, source_file, <模块数据>}；
# 规则 A：params.wells **不含** times/od（逐点数据只在 raw）；规则 B：payload.params 是手动参数冻结副本。
_raw21 = {
    "analysis_version": "enzyme-2.0",
    "calc_type": "enzyme",
    "params": {"calc_type": "enzyme", "time_axis": [5, 15], "sub_blank": True,
               "show_blank": False, "error_bar": "none"},
    "source_file": "20260817_120000.xlsx",
    "meta": {"sample": "S1"},
    "wells": {
        "A1": {"name": "A1", "ref": "", "times": [0, 5, 10, 15, 20], "od": [0.1, 0.2, 0.3, 0.4, 0.5]},
        "A2": {"name": "A2", "ref": "neg", "times": [0, 5, 10, 15, 20], "od": [0.05, 0.05, 0.05, 0.05, 0.05]},
    },
}
# 存档的 params.wells（v2：只有元数据 + 拟合 + 极小摘要 od_range，无逐点数据）
_wells_f = {
    "A1": {"name": "A1", "ref": "", "group": "", "protein_id": None, "mw": 27000,
           "conc_ng_ml": 100.0, "conc_uM": 3.7, "fit": {"slope": 0.02, "r2": 0.99},
           "od_range": ["0.2000", "0.4000"]},
    "A2": {"name": "A2", "ref": "neg", "group": "", "protein_id": None, "mw": None,
           "conc_ng_ml": None, "conc_uM": None, "fit": None, "od_range": ["0.0500", "0.0500"]},
}
_exp21 = services.create_experiment(
    title="", exp_type="酶活测定", date="2026-08-17",
    params={"calc_type": "enzyme", "wells": _wells_f, "time_axis": [5, 15]},
    results={},
    raw_snapshots=[("enzyme_traces", _raw21)],
)
# 21a. raw 落库：1 条，data_type=enzyme_traces
_raws = models.exp_raw_list(_exp21["id"])
assert len(_raws) == 1 and _raws[0]["data_type"] == "enzyme_traces", f"raw 应落 1 条: {_raws}"
# 21b. raw payload 保留**全量**时间序列（5 个点，含范围外的 0/20）+ 契约槽齐全
_raw_payload = models.exp_raw_get(_raws[0]["id"])["payload"]
assert _raw_payload["wells"]["A1"]["times"] == [0, 5, 10, 15, 20], f"raw 应存全量: {_raw_payload['wells']['A1']['times']}"
assert _raw_payload["analysis_version"] == "enzyme-2.0", "raw 应带 analysis_version"
for _k in ("calc_type", "params", "source_file"):
    assert _k in _raw_payload, f"raw payload 应带契约槽 {_k}: {sorted(_raw_payload)}"
assert _raw_payload["calc_type"] == "enzyme", "payload.calc_type 应规范为 enzyme"
assert _raw_payload["params"]["time_axis"] == [5, 15], "payload.params 应是手动参数冻结副本"
# 21c. 契约规则 A：存档 params.wells **不含**逐点数据，但保留 od_range 与 mw
_e21b = models.exp_get(_exp21["id"])
_w21 = _e21b["params"]["wells"]["A1"]
assert "times" not in _w21 and "od" not in _w21, f"params.wells 不应内嵌逐点数据: {sorted(_w21)}"
assert _w21["od_range"] == ["0.2000", "0.4000"], "params.wells 应保留 od_range 摘要"
assert _w21["mw"] == 27000, "params.wells 应保留 mw（复制后 ng/mL ↔ μM 可互算）"
# 21d. 不可变：raw 永不更新（只插不更）
_old_payload = _raw_payload
models.exp_save_raw(_exp21["id"], "enzyme_traces", {"analysis_version": "v2", "wells": {}, "time_axis": None})
_raws2 = models.exp_raw_list(_exp21["id"])
assert len(_raws2) == 2, f"应新增 1 条，total=2: {len(_raws2)}"
_first = models.exp_raw_get(_raws[0]["id"])
assert _first["payload"] == _old_payload, "第一条 raw 不得被新 raw 覆盖"
# 21e. 原子性：raw payload 含不可序列化对象（set）→ 整实验回滚，不留孤儿
_before = {e["id"] for e in models.exp_list()}
try:
    services.create_experiment(
        title="坏raw", exp_type="酶活测定",
        params={"calc_type": "enzyme"}, results={},
        raw_snapshots=[("enzyme_traces", {"wells": {"A1": {"times": [1.0, 2.0], "od_set": {0.1, 0.2}}}})
])
    raise AssertionError("不可序列化 raw 应失败")
except (TypeError, ValueError):
    pass
assert {e["id"] for e in models.exp_list()} == _before, "raw 失败应回滚实验"
print("21. 酶活存档契约 v2（raw 全量 / params 无逐点 / 不可变 / 原子性）OK")

# ── 22. 详情页兜底渲染：自由格式中文键可读 + kv 表 + 研究脉络挂载点 ──
# 背景：MCP save_experiment 归档的自由格式实验（中文键、无 calc_type）走兜底分支；
# Flask 3 默认 app.json.ensure_ascii=True 会把中文渲染成 \uXXXX 转义（"渲染失败"观感）。
_e22 = services.create_experiment(
    title="自由格式中文键", exp_type="其他",
    params={"体系": "每孔 200 uL", "温度": 25},
    results={"结论": "正常"},
)
_r22 = client.get(f"/experiments/{_e22['id']}")
assert _r22.status_code == 200, _r22.status_code
_h22 = _r22.get_data(as_text=True)
assert "每孔 200 uL" in _h22, "中文参数值应以明文渲染（ensure_ascii=False）"
assert "\\u4f53\\u7cfb" not in _h22, "中文不得渲染成 \\uXXXX 转义"
assert "<th style=\"vertical-align:top\">体系</th>" in _h22, "自由格式参数应渲染键值表"
assert f'data-exp-id="{_e22["id"]}"' in _h22, "详情页研究脉络块应带 data-exp-id 供 init() 挂载"
# 22b. tojson 仍 HTML 安全（< > & 转义不受 ensure_ascii 开关影响）
_e22b = services.create_experiment(
    title="xss 探针", exp_type="其他",
    params={"k": "<script>alert(1)</script>"}, results={},
)
_h22b = client.get(f"/experiments/{_e22b['id']}").get_data(as_text=True)
assert "<script>alert(1)" not in _h22b, "参数值中的 HTML 不得原样输出"
# 22c. exp_type=AKTA 但 results 无 peaks（汇总型实验）不得整页空白——known 门要真有数据才算已渲染
_e22c = services.create_experiment(
    title="AKTA 汇总无峰表", exp_type="AKTA",
    params={"峰位": "主峰 23 mL", "结论": "表达量关联"},
    results={"结论": "wt 较高"},
)
_h22c = client.get(f"/experiments/{_e22c['id']}").get_data(as_text=True)
assert 'data-i18n="detail.params"' in _h22c, "AKTA 汇总实验无 peaks 时应落入 kv 区（known 门修复），当前整页空白"
assert "主峰 23 mL" in _h22c, "kv 区应展示参数值"
# 22d. 嵌套 dict 渲染成子表格，不是一行巨型 JSON
_e22d = services.create_experiment(
    title="嵌套参数", exp_type="其他",
    params={"蛋白": {"id": 1, "name": "1YPI_WT", "mw": 53309.8}}, results={},
)
_h22d = client.get(f"/experiments/{_e22d['id']}").get_data(as_text=True)
assert "kv-nested" in _h22d, "嵌套 dict 应渲染子表格"
assert "1YPI_WT" in _h22d, "嵌套子表应含值"
print("22. 详情页兜底渲染（中文可读 / kv 表 / data-exp-id / HTML 安全 / AKTA 无峰表 / 嵌套子表）OK")

# ── 23. 数据重挂（services.resave_experiment + 端点 exp_id 分支）──
# 背景：三个分析流（酶活/BLI/AKTA）存档可选「挂载到已有同类实验」（前端 promptExpMount）。
# 汇总/占位实验从原始数据重新分析后把结构化结果挂回去——覆盖 params/results + 追加 raw 快照，
# 实验身份/日期/研究树节点不变；protein 绑定缺失时保留（不能误清空）。
_g23 = models.research_node_create(node_type="goal", title="重挂目标", tag="")
_p23 = _seed_protein("重挂蛋白")
_e23 = services.create_experiment(
    title="酶活占位", exp_type="酶活测定", protein_ids=[_p23],
    params={"calc_type": "enzyme", "meta": {"sample": "old"}},
    results={"wells": {"A1": {"slope": 0.01}}},
    notes="原备注", goal_id=_g23,
)
assert _e23["goal_node_id"], "占位实验应已挂研究节点"
# 23a. resave 覆盖 params/results、追加 raw、身份/日期/notes/蛋白绑定/研究节点不变
_r23 = services.resave_experiment(
    _e23["id"],
    params={"calc_type": "enzyme", "meta": {"sample": "new"}},
    results={"wells": {"A1": {"slope": 0.5}}},
    raw_snapshots=[("enzyme_traces", {"analysis_version": "v9",
                                      "wells": {"A1": {"slope": 0.5}}})],
)
assert _r23["id"] == _e23["id"] and _r23["title"] == "酶活占位", "重挂不改实验身份/标题"
assert _r23["exp_type"] == "酶活测定" and _r23["date"] == _e23["date"], "重挂不改类型/日期"
assert _r23["params"]["meta"]["sample"] == "new", "重挂应覆盖 params"
assert _r23["results"]["wells"]["A1"]["slope"] == 0.5, "重挂应覆盖 results"
assert _r23["notes"] == "原备注", "notes 未传时保留"
assert _r23["protein_ids"] == [_p23], "protein_ids 未传时应保留原绑定（不能清空）"
_rawn23 = [n for n in models.research_nodes_all() if n.get("exp_id") == _e23["id"]]
assert len(_rawn23) == 1 and _rawn23[0]["id"] == _e23["goal_node_id"], \
    f"研究节点应仍关联同一实验: {_rawn23}"
_rawn23raw = models.exp_raw_list(_e23["id"])
assert len(_rawn23raw) == 1 and _rawn23raw[0]["data_type"] == "enzyme_traces", _rawn23raw
assert _rawn23raw[0]["id"] == _r23["_raw_ids"][0], "返回应附 _raw_ids"
# 23b. 追加 raw 只写不更：再重挂一次 → 2 行，首行 payload 不变
_r23b = services.resave_experiment(
    _e23["id"], params={"calc_type": "enzyme"}, results={},
    raw_snapshots=[("enzyme_traces", {"analysis_version": "v10"})])
_rawn23b = models.exp_raw_list(_e23["id"])
assert len(_rawn23b) == 2, f"追加 raw 应新行: {_rawn23b}"
assert models.exp_raw_get(_rawn23raw[0]["id"])["payload"]["analysis_version"] == "v9", "旧 raw 不可变"
assert _r23b["_raw_ids"] == [x["id"] for x in _rawn23b], "_raw_ids 应含全部快照"
# 23c. notes / protein_ids 显式传时更新（与缺失=保留区分）
_r23c = services.resave_experiment(_e23["id"], params={}, results={},
                                   notes="新备注", protein_ids=[])
assert _r23c["notes"] == "新备注", "notes 显式传时应更新"
assert _r23c["protein_ids"] == [], "protein_ids 显式传 [] 时应换绑"
# 23d. 不存在的实验 → ValueError
try:
    services.resave_experiment(99999, params={}, results={})
    raise AssertionError("resave 不存在的实验应抛 ValueError")
except ValueError as _e23err:
    assert "不存在" in str(_e23err)
# 23e. 端点级：from-calculation 带 exp_id → 200 重挂；不带 → 201 新建；非法 → 400
_api23 = services.create_experiment(
    title="端点占位", exp_type="酶活测定",
    params={"calc_type": "enzyme", "meta": {"sample": "占位"}}, results={})
_j23r = client.post("/api/experiments/from-calculation", json={
    "title": "忽略", "exp_type": "酶活测定", "calc_type": "enzyme",
    "calc_params": {"meta": {"sample": "重算"}},
    "calc_result": {"wells": {"A1": {"slope": 2.0}}},
    "exp_id": _api23["id"],
})
assert _j23r.status_code == 200, (_j23r.status_code, _j23r.get_json())
_j23 = _j23r.get_json()
assert _j23["id"] == _api23["id"] and _j23["title"] == "端点占位", "端点重挂保持身份与标题"
assert _j23["params"]["meta"]["sample"] == "重算", "端点重挂应覆盖 params"
_j23new = client.post("/api/experiments/from-calculation", json={
    "title": "新建实验", "exp_type": "酶活测定", "calc_type": "enzyme",
    "calc_params": {"meta": {"sample": "a"}}, "calc_result": {}})
assert _j23new.status_code == 201, (_j23new.status_code, _j23new.get_json())
_j23bad = client.post("/api/experiments/from-calculation", json={
    "title": "x", "exp_type": "酶活测定", "calc_type": "enzyme",
    "calc_params": {}, "calc_result": {}, "exp_id": "abc"})
assert _j23bad.status_code == 400, _j23bad.get_json()
print("23. 数据重挂（resave 覆盖/追加/保留/节点不变 + 端点 exp_id 分支）OK")

# ── 24. 详情页「载入计算工具」入口 ──
# 用户拍板：详情页删掉 raw 快照表状态，只留一个「已加载好对应数据的计算页面」入口。
# 有分析数据（raw 快照 / 可重建 params）→ 显示按钮，跳 /calculator?load_exp=<id>；
# 纯记录实验不显示；raw 快照表块已整体移除。
_e24b = services.create_experiment(
    title="BLI 载入", exp_type="BLI",
    params={"calc_type": "bli_fit", "source": "a.csv"},
    results={"samples": {"WT": {"kd": 100}}},
    raw_snapshots=[("bli_curves", {"analysis_version": "0.0.8", "curves": []})],
)
_h24b = client.get(f"/experiments/{_e24b['id']}").get_data(as_text=True)
assert f'href="/calculator?load_exp={_e24b["id"]}"' in _h24b, "BLI 实验应显示载入计算工具按钮"
assert "原始数据快照" not in _h24b, "raw 快照表应已从详情页移除"
_e24n = services.create_experiment(title="纯记录", exp_type="其他",
                                   params={"k": "v"}, results={})
_h24n = client.get(f"/experiments/{_e24n['id']}").get_data(as_text=True)
assert "载入计算工具" not in _h24n, "纯记录实验不应显示载入按钮"
_p24 = _seed_protein("载入浓度")
_e24c = services.create_experiment(
    title="浓度载入", exp_type="浓度测定", protein_ids=[_p24],
    params={"calc_type": "concentration",
            "proteins": [{"id": _p24, "name": "载入浓度", "a280": 0.5}]},
    results={})
_h24c = client.get(f"/experiments/{_e24c['id']}").get_data(as_text=True)
assert f'href="/calculator?load_exp={_e24c["id"]}"' in _h24c, "浓度实验应显示载入按钮"
print("24. 详情页载入计算工具入口（按钮显隐 / raw 表移除）OK")

# ── 25. 备份分桶轮转回归：例行桶只轮转自己的文件，安全网/手工备份一个不删 ──
# 背景：旧实现按 `.db` **后缀**清理备份目录。`protein_lab_manual_*` 排序在 `protein_lab_2*`
# 之上（'m' > '2'），10 个名额被 2 份手工 + 8 份例行占满，把 `pre-enzyme-backfill_*` 挤到
# 第 11 位 → **下次启动即被删除**，回填的安全网静默消失。现改为严格正则匹配例行文件名，
# 各桶由各自的生产者轮转：例行 10（本函数）/ pre-migration_ 5（models）/ pre-* 各归其主。
import app as _app_mod
_bk_sub = os.path.join(TMP, "bucket_test")
os.makedirs(_bk_sub, exist_ok=True)
_saved_db_path = models.DB_PATH
models.DB_PATH = os.path.join(_bk_sub, "protein_lab.db")
models.init_db()
_bk_dir = os.path.join(_bk_sub, "backups")
os.makedirs(_bk_dir, exist_ok=True)
for _f in os.listdir(_bk_dir):          # 清掉 init_db 自己产出的迁移前备份，基线干净
    os.remove(os.path.join(_bk_dir, _f))
_bk_routine = [f"protein_lab_202601{d:02d}_{h:06d}.db" for d, h in
               zip(range(1, 13), [0, 10000, 20000, 30000, 40000, 50000,
                                  100000, 110000, 120000, 130000, 140000, 150000])]
_bk_keep = ["protein_lab_manual_20260809_220811.db",     # 手工复制的，无代码生成它
            "protein_lab_manual_20260817_111645.db",
            "pre-migration_20260901_120000.db",          # models 的安全网
            "pre-enzyme-backfill_20260916_135559.db"]    # tools 回填的安全网
for _f in _bk_routine + _bk_keep:
    with open(os.path.join(_bk_dir, _f), "wb") as _fh:
        _fh.write(b"x" * 16)
_app_mod.backup_database()               # 12 份例行 + 本次新增 = 13 → 轮转到 10
_bk_left = os.listdir(_bk_dir)
_bk_routine_left = [f for f in _bk_left if _app_mod.ROUTINE_BACKUP_RE.match(f)]
assert len(_bk_routine_left) == _app_mod.ROUTINE_BACKUP_KEEP, \
    f"例行桶应留 {_app_mod.ROUTINE_BACKUP_KEEP} 份，实际 {len(_bk_routine_left)}: {sorted(_bk_routine_left)}"
for _f in _bk_keep:
    assert _f in _bk_left, f"安全网/手工备份被例行轮转误删: {_f}（P0 回归失败）"
assert not [f for f in _bk_left if f not in _bk_keep and f not in _bk_routine_left], \
    f"备份目录出现预期外的文件: {_bk_left}"
# 25b. 轮转掉的是**最旧**的例行备份，不是随机的
assert "protein_lab_20260101_000000.db" not in _bk_left, "应删除最旧的例行备份"
assert "protein_lab_20260112_150000.db" in _bk_left, "较新的例行备份应保留"
# 25c. 新写入的例行备份是**有效** SQLite 库（在线备份 API 的产物，不是空壳/半截文件）
_bk_newest = sorted(_bk_routine_left)[-1]
_bc = sqlite3.connect(os.path.join(_bk_dir, _bk_newest))
assert _bc.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "在线备份应通过完整性检查"
assert _bc.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0, \
    "在线备份应含表结构"
assert _bc.execute("PRAGMA user_version").fetchone()[0] == models.SCHEMA_VERSION, "备份应为当前 schema 版本"
_bc.close()
models.DB_PATH = _saved_db_path
print("25. 备份分桶轮转（例行 10 / 手工与 pre-* 安全网不动 / 在线备份可读）OK")

# ── 26. 批量删除的撤销不再静默丢失 ──
# 背景：旧实现逐条 _push_undo，而 undo 栈上限 20——delete-all 25 条实验时**前 5 条被静默挤掉**，
# 撤销只回来 15 条且毫无提示（静默数据丢失）。现改为压**一条** bulk 条目，条数与栈深无关。
_uc26 = client
_made26 = []
for _i in range(25):
    _made26.append(services.create_experiment(
        title=f"批量{_i:02d}", exp_type="其他", params={"i": _i}, results={},
        raw_snapshots=[("bli_curves", {"analysis_version": "v1", "curves": []})],
    )["id"])
_cnt26 = len(models.exp_list(limit=9999))
_depth26 = _uc26.get("/api/undo/status").get_json()["count"]
_r26 = _uc26.post("/api/experiments/delete-all", json={})
assert _r26.status_code == 200 and _r26.get_json()["deleted"] == _cnt26, _r26.get_json()
assert models.exp_list(limit=9999) == [], "delete-all 应清空"
assert _uc26.get("/api/undo/status").get_json()["count"] == _depth26 + 1, \
    f"delete-all 应只压一条 bulk 条目（旧实现会压 {min(_cnt26, 20)} 条）"
_u26 = _uc26.post("/api/undo", json={})
assert _u26.status_code == 200, _u26.get_json()
_j26 = _u26.get_json()
assert _j26.get("bulk") is True, f"应走 bulk 分支: {_j26}"
assert _j26["restored"] == _cnt26, f"应全量恢复 {_cnt26} 条，实际 {_j26['restored']}"
_after26 = models.exp_list(limit=9999)
assert len(_after26) == _cnt26, f"恢复后条数不符: {len(_after26)} != {_cnt26}"
_by_title26 = {e["title"]: e for e in _after26}
for _i in range(25):
    assert f"批量{_i:02d}" in _by_title26, f"批量{_i:02d} 未被恢复（静默丢失）"
    _rr26 = models.exp_raw_list(_by_title26[f"批量{_i:02d}"]["id"])
    assert len(_rr26) == 1 and _rr26[0]["data_type"] == "bli_curves", \
        f"批量{_i:02d} 的 raw 快照未重挂: {_rr26}"
    assert models.exp_raw_get(_rr26[0]["id"])["payload"]["analysis_version"] == "v1", \
        f"批量{_i:02d} raw payload 被改动"
# 26b. batch-delete 同样只压一条，且 restored 是条数（供前端按 bulk 文案渲染）
_ids26 = [e["id"] for e in models.exp_list(limit=9999)][:3]
_depth26b = _uc26.get("/api/undo/status").get_json()["count"]
assert _uc26.post("/api/experiments/batch-delete", json={"ids": _ids26}).get_json()["deleted"] == 3
assert _uc26.get("/api/undo/status").get_json()["count"] == _depth26b + 1, \
    "batch-delete 应只压一条 bulk 条目"
_ub26 = _uc26.post("/api/undo", json={}).get_json()
assert _ub26.get("bulk") is True and _ub26["restored"] == 3, _ub26
assert len(models.exp_list(limit=9999)) == _cnt26, "batch-delete 撤销后应回到原条数"
# 26c. 单条删除仍走单条路径（不受 bulk 影响），且删不存在的实验返回 404
#      ——此前 e is None 时照样调 exp_delete，"删成功"是假象
_single26 = models.exp_list(limit=1)[0]["id"]
_depth26c = _uc26.get("/api/undo/status").get_json()["count"]
assert _uc26.delete(f"/api/experiments/{_single26}").status_code == 200
assert _uc26.get("/api/undo/status").get_json()["count"] == _depth26c + 1, "单条删除应压一条"
_u26c = _uc26.post("/api/undo", json={}).get_json()
assert _u26c.get("restored") and not _u26c.get("bulk"), f"单条恢复不该走 bulk: {_u26c}"
assert _uc26.delete("/api/experiments/99999").status_code == 404, "删不存在的实验应 404"
print("26. 批量删除撤销（bulk 单条目 / 全量恢复 / raw 重挂 / 单条不受影响 / 404）OK")

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED")
