"""
SQLite 数据模型 — proteins + experiments 表的 CRUD
纯 sqlite3，无 ORM 依赖
"""
import sqlite3
import json
import os
import shutil
from datetime import datetime

from paths import app_base_dir

# 打包(onefile)后 __file__ 指向临时解压目录，DB 必须放 EXE 同目录；dev 下即源码目录
DB_PATH = os.path.join(app_base_dir(), "protein_lab.db")

# 实验类型清单（单一来源）——模板下拉 / MCP 工具描述都从这读，避免各处硬编码漂移
EXP_TYPES = ("BLI", "SDS-PAGE", "AKTA", "浓度测定", "酶活测定", "Weblogo", "其他")


def get_db(read_only: bool = False) -> sqlite3.Connection:
    """获取连接。read_only=True 时开 query_only——任何写操作被 SQLite 拒绝，
    供 MCP 读工具等只读契约使用（见 mcp_server.py 读写契约）。
    timeout=30：多写者（waitress 4 线程 + MCP 独立进程）共享同一库文件时互等，
    而非默认 5s 内撞锁直接抛 `database is locked`。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if read_only:
        conn.execute("PRAGMA query_only = ON")
    return conn


# ── Schema 迁移框架 ────────────────────────────────────────
# 用 PRAGMA user_version 记录 schema 版本；MIGRATIONS 按序逐条迁移，每步 BEGIN→迁移→
# user_version=N→COMMIT 原子。老库（user_version=0）从 v1 起跑：v1 全是 CREATE IF NOT
# EXISTS + 旧列清理，对已有表是 no-op——这是"非破坏性升级"的保证（数据原样不动）。

SCHEMA_VERSION = 3  # 当前 schema 版本（与 MIGRATIONS 末项一致）


def _migrate_v1_post(conn):
    """v1 附加清理：旧 schema 的 experiments 表可能残留 protein_id 列，删除之。

    注意 `ALTER TABLE ... DROP COLUMN` 需要 SQLite 3.35+（2021-03 发布）。Python 3.9 部分
    构建自带更老的 sqlite（如 3.31/3.34），此时硬删会抛语法错误把迁移搞崩——列残留无害
    （代码已无任何引用），低版本下跳过即可，等升级 Python 后自然清除。
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(experiments)").fetchall()]
    if "protein_id" not in cols:
        return
    ver = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
    if ver >= (3, 35, 0):
        conn.execute("ALTER TABLE experiments DROP COLUMN protein_id")
    # else: SQLite < 3.35 不支持 DROP COLUMN，protein_id 残留（无引用、无害），跳过


MIGRATIONS = [
    {
        "version": 1,
        "sql": [
            """CREATE TABLE IF NOT EXISTS proteins (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                sequence    TEXT NOT NULL,
                mw          REAL,
                nW          INTEGER DEFAULT 0,
                nY          INTEGER DEFAULT 0,
                nC          INTEGER DEFAULT 0,
                ext_red     REAL,
                ext_ox      REAL,
                abs_0_1pct  REAL,
                tag         TEXT DEFAULT '',
                notes       TEXT DEFAULT '',
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                updated_at  TEXT DEFAULT (datetime('now','localtime'))
            )""",
            """CREATE TABLE IF NOT EXISTS experiments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                exp_type    TEXT NOT NULL,
                date        TEXT DEFAULT (date('now','localtime')),
                params      TEXT DEFAULT '{}',
                results     TEXT DEFAULT '{}',
                notes       TEXT DEFAULT '',
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            )""",
            """CREATE TABLE IF NOT EXISTS experiment_proteins (
                experiment_id INTEGER NOT NULL,
                protein_id    INTEGER NOT NULL,
                PRIMARY KEY (experiment_id, protein_id),
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
                FOREIGN KEY (protein_id) REFERENCES proteins(id) ON DELETE CASCADE
            )""",
        ],
        "post": _migrate_v1_post,
    },
    {
        "version": 2,
        # experiment_raw：原始数据快照，只写一次、从不 UPDATE（规则 #2/#8）。
        # FK ON DELETE SET NULL：删实验不删 raw（规则 #5），双向保险。
        "sql": [
            """CREATE TABLE IF NOT EXISTS experiment_raw (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER,
                data_type     TEXT NOT NULL,
                payload       TEXT NOT NULL,
                created_at    TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_raw_exp ON experiment_raw(experiment_id)",
        ],
    },
    {
        "version": 3,
        # research_nodes：研究脉络树（v0.1.0）。三节点类型 goal/experiment/conclusion。
        # parent_id 自引用 FK，删父级联删子树；exp_id 指向实验，删实验 FK SET NULL
        # 保留节点作断链占位。白名单边校验在 service 层（research.py），表层只存
        # free_attach 逃生舱标记——不做 CHECK 约束，留逃生舱可打破任意边（IP 本地产物）。
        "sql": [
            """CREATE TABLE IF NOT EXISTS research_nodes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                node_type   TEXT NOT NULL,           -- goal | experiment | conclusion
                parent_id   INTEGER REFERENCES research_nodes(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                detail      TEXT DEFAULT '',
                exp_id      INTEGER REFERENCES experiments(id) ON DELETE SET NULL,
                tag         TEXT DEFAULT '',
                free_attach INTEGER DEFAULT 0,       -- 逃生舱：自由挂载，打破白名单
                sort_order  INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_research_parent ON research_nodes(parent_id)",
        ],
    },
]


def _backup_before_migration():
    """迁移前就地把库备份到 backups/（pre-migration 标记），保留最近 5 份。

    为什么需要：迁移在 import models 时触发（app.py 顶部 import），而 app.py 的启动例行
    备份在 main 块才执行——备份到手的已是迁移后库。这里在**首个未应用迁移**之前快照一份，
    为未来可能的破坏性迁移（如 DROP COLUMN 带数据）留迁移前回滚点。仅清理 pre-migration_
    前缀，不动 app.py 的 protein_lab_ 例行备份。
    """
    backup_dir = os.path.join(os.path.dirname(DB_PATH), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"pre-migration_{stamp}.db")
    shutil.copy2(DB_PATH, dst)
    existing = sorted(
        [f for f in os.listdir(backup_dir)
         if f.startswith("pre-migration_") and f.endswith(".db")],
        reverse=True,
    )
    for old in existing[5:]:
        os.remove(os.path.join(backup_dir, old))


def _migrate():
    # 先短连接读当前版本，再决定是否备份：迁移前必须无打开的写连接（Windows 文件句柄）
    conn = get_db()
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if current < MIGRATIONS[-1]["version"] and os.path.exists(DB_PATH):
        _backup_before_migration()
    conn = get_db()
    try:
        for m in MIGRATIONS:
            v = m["version"]
            if current >= v:
                continue
            conn.execute("BEGIN")
            try:
                for stmt in m["sql"]:
                    conn.execute(stmt)
                if m.get("post"):
                    m["post"](conn)
                conn.execute(f"PRAGMA user_version = {v}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            current = v
    finally:
        conn.close()


def init_db():
    """迁移到最新 schema。保持历史语义：import models 即触发（models.py 末尾调用）。
    迁移后切 WAL（持久化在库文件头，设一次即可；:memory: 测试库是 no-op）——
    WAL 下读者不阻塞写者，Web 4 线程 + MCP 进程并存更稳；但备份裸 copy 主文件会漏
    未 checkpoint 的 WAL 内容，备份前必须 wal_checkpoint（见 app.py backup_database）。"""
    _migrate()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()


# ── Proteins CRUD ──────────────────────────────────────────

def protein_list(search: str = "", tag_filter: str = "") -> list[dict]:
    conn = get_db()
    clauses = []
    params = []
    if search:
        clauses.append("(name LIKE ? OR tag LIKE ? OR notes LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if tag_filter:
        # tag_filter 逗号分隔，要求同时匹配多个标签（交集）
        # 标签字段以 "tag1, tag2"（逗号+空格）存储：先把 ", " 折叠为 ","
        # 再匹配，才能精确命中非首位的标签（如 "5.5A"）；多词标签内部空格不受影响
        for t in tag_filter.split(","):
            t = t.strip()
            if t:
                clauses.append("(',' || REPLACE(',' || tag, ', ', ',') || ',' LIKE ?)")
                params.append(f"%,{t},%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM proteins{where} ORDER BY updated_at DESC", params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def protein_tags() -> list[str]:
    """提取所有已有标签（去重排序）"""
    conn = get_db()
    rows = conn.execute("SELECT tag FROM proteins WHERE tag != ''").fetchall()
    conn.close()
    tags = set()
    for r in rows:
        for t in r["tag"].split(","):
            t = t.strip()
            if t:
                tags.add(t)
    return sorted(tags)


def protein_get(protein_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM proteins WHERE id = ?", (protein_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def protein_get_by_name(name: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM proteins WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def protein_create(name: str, sequence: str, tag: str = "", notes: str = "",
                   mw: float = 0, nW: int = 0, nY: int = 0, nC: int = 0,
                   ext_red: float = 0, ext_ox: float = 0, abs_0_1pct: float = 0) -> int:
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("""
        INSERT INTO proteins (name, sequence, mw, nW, nY, nC, ext_red, ext_ox, abs_0_1pct, tag, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (name, sequence.upper(), mw, nW, nY, nC, ext_red, ext_ox, abs_0_1pct, tag, notes, now, now))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def protein_update(protein_id: int, **kwargs) -> bool:
    safe_columns = frozenset({"name", "sequence", "tag", "notes", "mw",
                               "nW", "nY", "nC", "ext_red", "ext_ox", "abs_0_1pct"})
    updates = {}
    for k, v in kwargs.items():
        if k in safe_columns:
            updates[k] = v
    if not updates:
        return False
    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 列名来自 frozenset 白名单 + 硬编码的 updated_at，安全
    cols = []
    values = []
    for col, val in updates.items():
        cols.append(f'"{col}"=?')
        values.append(val)
    set_clause = ", ".join(cols)
    values.append(protein_id)
    conn = get_db()
    conn.execute(f"UPDATE proteins SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()
    return True


def protein_delete(protein_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM proteins WHERE id=?", (protein_id,))
    conn.commit()
    conn.close()
    return True


def protein_delete_all() -> int:
    conn = get_db()
    cur = conn.execute("DELETE FROM proteins")
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


# ── Experiments CRUD ───────────────────────────────────────

def _json_unwrap(val):
    """防御性解包：历史数据可能把 JSON 字符串再编码一层（双重编码），循环解到非字符串为止。
    结果不强制 dict——旧浓度格式的 results 可能是 list，须原样保留。"""
    while isinstance(val, str):
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            break
    return val


def _set_exp_proteins(conn: sqlite3.Connection, experiment_id: int,
                      protein_ids: list[int]) -> None:
    """同步实验-蛋白关联（先删后插）"""
    conn.execute("DELETE FROM experiment_proteins WHERE experiment_id = ?",
                 (experiment_id,))
    for pid in protein_ids:
        if pid:
            conn.execute(
                "INSERT OR IGNORE INTO experiment_proteins (experiment_id, protein_id) VALUES (?,?)",
                (experiment_id, pid))


def exp_list(exp_type: str = "", limit: int = 50, calc_type: str = "") -> list[dict]:
    import identity
    conn = get_db()
    base = """
        SELECT e.*, GROUP_CONCAT(p.name, ', ') as protein_names
        FROM experiments e
        LEFT JOIN experiment_proteins ep ON e.id = ep.experiment_id
        LEFT JOIN proteins p ON ep.protein_id = p.id
    """
    fetch_limit = max(int(limit or 50), 1)
    if calc_type:
        fetch_limit = max(fetch_limit * 20, 500)
    if exp_type and not calc_type:
        rows = conn.execute(
            base + "WHERE e.exp_type = ? GROUP BY e.id ORDER BY e.date DESC, e.created_at DESC LIMIT ?",
            (exp_type, fetch_limit)).fetchall()
    else:
        rows = conn.execute(
            base + "GROUP BY e.id ORDER BY e.date DESC, e.created_at DESC LIMIT ?",
            (fetch_limit,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["protein_names"] = d["protein_names"] or ""
        d["params"] = _json_unwrap(d.get("params"))
        d["results"] = _json_unwrap(d.get("results"))
        results.append(identity.annotate(d))
    want = identity.normalize_calc_type(calc_type)
    if want:
        results = [d for d in results if d.get("calc_type") == want][:limit]
    return results


def exp_next_seq_slug(slug: str, date: str = "") -> int:
    """自动命名序号：当天同 slug 标题 `{date}_{slug}_{NN}` 的最大后缀 + 1。

    按 slug（calc_type）计，不按 exp_type 列——稀释与 BLI 拟合同属 BLI 族但序号独立。
    """
    conn = get_db()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    prefix = f"{date}_{slug}_"
    rows = conn.execute(
        "SELECT title FROM experiments WHERE date = ?",
        (date,)).fetchall()
    conn.close()
    best = 0
    for r in rows:
        title = r["title"] if "title" in r.keys() else r[0]
        if not title or not str(title).startswith(prefix):
            continue
        tail = str(title)[len(prefix):]
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            best = max(best, int(digits))
    return best + 1


def exp_next_seq(exp_type: str, date: str = "") -> int:
    """自动命名序号：当天同类型已有标题里 `{date}_{exp_type}_{NN}` 的最大后缀 + 1。

    用 MAX 后缀而非 COUNT，避免删除中间记录（如撤销 _02）后下一个自动名与现存标题撞名。
    """
    conn = get_db()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT title FROM experiments WHERE exp_type = ? AND date = ?",
        (exp_type, date)).fetchall()
    conn.close()
    prefix = f"{date}_{exp_type}_"
    max_seq = 0
    for r in rows:
        t = r["title"] or ""
        if t.startswith(prefix):
            suf = t[len(prefix):]
            if suf.isdigit():
                max_seq = max(max_seq, int(suf))
    return max_seq + 1


def exp_get(exp_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("""
        SELECT e.*, GROUP_CONCAT(p.name, ', ') as protein_names
        FROM experiments e
        LEFT JOIN experiment_proteins ep ON e.id = ep.experiment_id
        LEFT JOIN proteins p ON ep.protein_id = p.id
        WHERE e.id = ? GROUP BY e.id
    """, (exp_id,)).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    d["protein_names"] = d["protein_names"] or ""
    d["params"] = _json_unwrap(d.get("params"))
    d["results"] = _json_unwrap(d.get("results"))
    # 同时返回 protein_ids 数组方便前端编辑
    ids = conn.execute(
        "SELECT protein_id FROM experiment_proteins WHERE experiment_id = ?",
        (exp_id,)).fetchall()
    d["protein_ids"] = [r["protein_id"] for r in ids]
    conn.close()
    return d


def exp_create(title: str, exp_type: str, protein_ids: list[int] = None,
               date: str = "", params: dict = None, results: dict = None,
               notes: str = "") -> int:
    conn = get_db()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("""
        INSERT INTO experiments (title, exp_type, date, params, results, notes, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (title, exp_type, date,
          json.dumps(params or {}, ensure_ascii=False),
          json.dumps(results or {}, ensure_ascii=False),
          notes, now))
    eid = cur.lastrowid
    if protein_ids:
        _set_exp_proteins(conn, eid, protein_ids)
    conn.commit()
    conn.close()
    return eid


def exp_create_with_raw(title: str, exp_type: str, protein_ids: list[int] = None,
                        date: str = "", params: dict = None, results: dict = None,
                        notes: str = "", raw_snapshots: list[tuple[str, object]] = None) -> int:
    """原子创建实验 + 落原始数据快照（单事务，要么全成要么全不成）。

    raw_snapshots: [(data_type, payload), ...]。供 services.create_experiment 统一写入时
    携带 raw（BLI/AKTA save），避免「先建实验、再单独 exp_save_raw」的部分写入——raw 落库
    失败会留下无快照的孤儿实验（规则 #8 可复现性被破坏）。
    """
    conn = get_db()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("BEGIN")
    try:
        cur = conn.execute("""
            INSERT INTO experiments (title, exp_type, date, params, results, notes, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (title, exp_type, date,
              json.dumps(params or {}, ensure_ascii=False),
              json.dumps(results or {}, ensure_ascii=False),
              notes, now))
        eid = cur.lastrowid
        if protein_ids:
            _set_exp_proteins(conn, eid, protein_ids)
        for data_type, payload in (raw_snapshots or []):
            conn.execute(
                "INSERT INTO experiment_raw (experiment_id, data_type, payload) VALUES (?,?,?)",
                (eid, data_type, json.dumps(payload, ensure_ascii=False)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return eid


EXP_SAFE_COLUMNS = frozenset({"title", "exp_type", "date", "notes", "params", "results"})


def exp_update(exp_id: int, protein_ids: list[int] = None, **kwargs) -> bool:
    """更新实验字段 + 蛋白关联"""
    conn = get_db()
    changed = False

    # 更新标量字段
    updates = {}
    for k, v in kwargs.items():
        if k in EXP_SAFE_COLUMNS:
            val = v
            # params/results 落库恒为 JSON 字符串：非 str（dict/list/标量）一律 dumps，str 原样（防重复编码）
            if k in ("params", "results") and not isinstance(val, str):
                val = json.dumps(val, ensure_ascii=False)
            updates[k] = val
    if updates:
        cols = []
        values = []
        for col, val in updates.items():
            cols.append(f'"{col}"=?')
            values.append(val)
        values.append(exp_id)
        conn.execute(f"UPDATE experiments SET {', '.join(cols)} WHERE id=?", values)
        changed = True

    # 更新蛋白关联
    if protein_ids is not None:
        _set_exp_proteins(conn, exp_id, protein_ids)
        changed = True

    conn.commit()
    conn.close()
    return changed


def exp_delete(exp_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM experiments WHERE id=?", (exp_id,))
    conn.commit()
    conn.close()
    return True


def exp_delete_all() -> int:
    conn = get_db()
    cur = conn.execute("DELETE FROM experiments")
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


# ── experiment_raw：原始数据快照 ───────────────────────────
# 规则 #2/#5/#8：payload 只写一次、从不 UPDATE；同实验多次分析=多行快照；
# 删实验时 FK SET NULL 保留 raw，不级联删除。

def exp_save_raw(exp_id: int, data_type: str, payload) -> int:
    """原始数据快照入库。只插不更——重复调用生成新行，旧行永不改动。"""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO experiment_raw (experiment_id, data_type, payload) VALUES (?,?,?)",
        (exp_id, data_type, json.dumps(payload, ensure_ascii=False)))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def exp_raw_list(exp_id: int, with_version: bool = False) -> list[dict]:
    """某实验的全部原始数据快照元数据（不含 payload 大字段，避免大字段进列表）。

    with_version=True 时额外读 payload 里的 analysis_version（轻量，仅提取版本号，
    不把整个 payload 放回列表）——详情页展示"分析版本"用，MCP/列表仍走轻量路径。
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT id, experiment_id, data_type, created_at FROM experiment_raw "
        "WHERE experiment_id = ? ORDER BY id", (exp_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if with_version:
            ver = conn.execute(
                "SELECT payload FROM experiment_raw WHERE id = ?", (r["id"],)).fetchone()
            d["analysis_version"] = _version_from_payload(ver["payload"]) if ver else None
        out.append(d)
    conn.close()
    return out


def _version_from_payload(payload: str):
    """从 raw payload JSON 提取 analysis_version（缺省 None）。"""
    try:
        p = _json_unwrap(payload)
        return p.get("analysis_version") if isinstance(p, dict) else None
    except Exception:
        return None


def exp_raw_get(raw_id: int) -> dict | None:
    """单条原始数据（含 payload，_json_unwrap 解包为 dict）"""
    conn = get_db()
    row = conn.execute("SELECT * FROM experiment_raw WHERE id = ?", (raw_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["payload"] = _json_unwrap(d.get("payload"))
    return d


def exp_raw_relink(raw_ids: list[int], new_exp_id: int) -> None:
    """把孤儿 raw 重挂到恢复的实验上（undo 恢复实验后用）。

    场景：删除实验物理删行 → experiment_raw.experiment_id 被 FK SET NULL 置空；
    undo 恢复重建实验得到新 id，这些 raw 需要重挂回才能继续在详情页看到。
    只改关联字段、不动 payload——与「raw 只插不更」规则不冲突（payload 始终未变）。
    """
    conn = get_db()
    conn.execute("BEGIN")
    try:
        for rid in raw_ids:
            conn.execute("UPDATE experiment_raw SET experiment_id = ? WHERE id = ?",
                         (new_exp_id, rid))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── research_nodes：研究脉络树（v0.1.0）───────────────────
# 三节点类型 goal(目标)/experiment(实验引用或计划占位)/conclusion(结论)。
# 白名单边校验在 research.py service 层（留 free_attach 逃生舱），这里只管存取——
# SQL 全在 models.py，业务规则不进表（不建 CHECK，逃生舱可打破任意边）。

RESEARCH_NODE_TYPES = ("goal", "experiment", "conclusion")
RESEARCH_SAFE_COLUMNS = frozenset({"node_type", "title", "detail", "parent_id",
                                   "exp_id", "tag", "free_attach", "sort_order"})


def research_node_create(node_type: str, title: str, detail: str = "",
                         parent_id: int = None, exp_id: int = None,
                         tag: str = "", free_attach: bool = False,
                         sort_order: int = 0) -> int:
    """新建研究节点，返回 id。结构校验（白名单/根须目标）由 service 层负责。"""
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO research_nodes
            (node_type, title, detail, parent_id, exp_id, tag, free_attach, sort_order)
        VALUES (?,?,?,?,?,?,?,?)
    """, (node_type, title, detail, parent_id, exp_id, tag,
          1 if free_attach else 0, sort_order))
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return nid


def research_node_get(node_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM research_nodes WHERE id = ?",
                       (node_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def research_node_update(node_id: int, **kwargs) -> bool:
    """更新研究节点标量字段（列名白名单过滤）。parent_id/exp_id 传 None 可置空。"""
    updates = {}
    for k, v in kwargs.items():
        if k in RESEARCH_SAFE_COLUMNS:
            # 三元右结合陷阱：必须显式括号，否则非 free_attach 列真值也会被存成 1
            val = (1 if v else 0) if k == "free_attach" else v
            updates[k] = val
    if not updates:
        return False
    cols = ", ".join(f'"{c}"=?' for c in updates)
    conn = get_db()
    conn.execute(f"UPDATE research_nodes SET {cols} WHERE id=?",
                 list(updates.values()) + [node_id])
    conn.commit()
    conn.close()
    return True


def research_node_delete_subtree(node_id: int) -> int:
    """物理删除节点及其整棵子树，返回删除节点数。

    收集后代 id 后单事务统一删——比逐层递归删更原子；FK ON DELETE CASCADE 为兜底。
    """
    conn = get_db()
    stack = [node_id]
    ids = []
    seen = set()
    while stack:
        nid = stack.pop()
        if nid in seen:  # 防环兜底：历史/异常数据成环时避免 ids 无限增长
            continue
        seen.add(nid)
        ids.append(nid)
        rows = conn.execute("SELECT id FROM research_nodes WHERE parent_id=?",
                            (nid,)).fetchall()
        stack.extend(r["id"] for r in rows)
    conn.execute("BEGIN")
    try:
        conn.executemany("DELETE FROM research_nodes WHERE id=?", [(i,) for i in ids])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return len(ids)


def research_nodes_all() -> list[dict]:
    """全部研究节点（扁平列表，供 service 建树）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM research_nodes ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def research_node_children(parent_id: int) -> list[dict]:
    """某节点的直接子节点（按 sort_order 排序）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM research_nodes WHERE parent_id=? ORDER BY sort_order, id",
        (parent_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def research_nodes_root() -> list[dict]:
    """根节点（parent_id 为 NULL）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM research_nodes WHERE parent_id IS NULL "
        "ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Init on import ─────────────────────────────────────────
init_db()
