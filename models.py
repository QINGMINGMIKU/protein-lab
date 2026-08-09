"""
SQLite 数据模型 — proteins + experiments 表的 CRUD
纯 sqlite3，无 ORM 依赖
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "protein_lab.db")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """创建表（如果不存在）+ 自动迁移旧 schema"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS proteins (
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
        );

        CREATE TABLE IF NOT EXISTS experiments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            exp_type    TEXT NOT NULL,
            date        TEXT DEFAULT (date('now','localtime')),
            params      TEXT DEFAULT '{}',
            results     TEXT DEFAULT '{}',
            notes       TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS experiment_proteins (
            experiment_id INTEGER NOT NULL,
            protein_id    INTEGER NOT NULL,
            PRIMARY KEY (experiment_id, protein_id),
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
            FOREIGN KEY (protein_id) REFERENCES proteins(id) ON DELETE CASCADE
        );
    """)
    # 自动迁移：如果旧表有 protein_id 列，删除之 (SQLite 3.35+)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(experiments)").fetchall()]
    if "protein_id" in cols:
        conn.execute("ALTER TABLE experiments DROP COLUMN protein_id")
    conn.commit()
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
        for t in tag_filter.split(","):
            t = t.strip()
            if t:
                clauses.append("(',' || tag || ',' LIKE ?)")
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


def exp_list(exp_type: str = "", limit: int = 50) -> list[dict]:
    conn = get_db()
    base = """
        SELECT e.*, GROUP_CONCAT(p.name, ', ') as protein_names
        FROM experiments e
        LEFT JOIN experiment_proteins ep ON e.id = ep.experiment_id
        LEFT JOIN proteins p ON ep.protein_id = p.id
    """
    if exp_type:
        rows = conn.execute(
            base + "WHERE e.exp_type = ? GROUP BY e.id ORDER BY e.date DESC, e.created_at DESC LIMIT ?",
            (exp_type, limit)).fetchall()
    else:
        rows = conn.execute(
            base + "GROUP BY e.id ORDER BY e.date DESC, e.created_at DESC LIMIT ?",
            (limit,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["protein_names"] = d["protein_names"] or ""
        results.append(d)
    return results


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
            if isinstance(val, dict):
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


# ── Init on import ─────────────────────────────────────────
init_db()
