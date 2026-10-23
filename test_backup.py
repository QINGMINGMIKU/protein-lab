"""test_backup.py — 数据安全回归（assert 脚本）

跑法（必须用 venv python）：
    .venv/Scripts/python.exe test_backup.py

覆盖：
1. `import models` **没有副作用**：不创建、不修改数据库文件（2026-10-22 维护轮）
2. `PROTEIN_LAB_DB` 环境变量可把库指向临时路径（测试/诊断用）
3. 在线备份（SQLite backup API）在 WAL 写入未 checkpoint 时仍包含最新数据
4. 备份可恢复：复制回主库 + 删除 -wal/-shm + 重新打开，数据与备份时一致

数据安全：全程临时目录，不触碰生产 protein_lab.db。
"""
import os
import sys
import shutil
import sqlite3
import subprocess
import tempfile
import importlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="protein_lab_backup_")
PROD_DB = os.path.join(TMP, "protein_lab.db")

# ── 1. import 无副作用：子进程里只 import models，不得创建库文件 ──
PROBE_DB = os.path.join(TMP, "probe.db")
env = dict(os.environ, PROTEIN_LAB_DB=PROBE_DB)
probe = subprocess.run(
    [sys.executable, "-c", "import models; print(models.DB_PATH)"],
    cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
)
assert probe.returncode == 0, probe.stderr
assert not os.path.exists(PROBE_DB), \
    f"import models 不应创建数据库，实际生成了 {PROBE_DB}"
assert probe.stdout.strip() == PROBE_DB, \
    f"PROTEIN_LAB_DB 未生效: {probe.stdout.strip()}"

# 显式 init 后才允许创建（入口契约）
inited = subprocess.run(
    [sys.executable, "-c", "import models; models.init_db()"],
    cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
)
assert inited.returncode == 0, inited.stderr
assert os.path.exists(PROBE_DB), "models.init_db() 应创建数据库"
os.remove(PROBE_DB)
for suffix in ("-wal", "-shm"):
    if os.path.exists(PROBE_DB + suffix):
        os.remove(PROBE_DB + suffix)
print("1. import models 无副作用 / init_db 显式建库 OK")

# ── 2. 临时库隔离（本进程）──
import models
importlib.reload(models)
models.DB_PATH = PROD_DB
models.init_db()
assert models.DB_PATH == PROD_DB and not models.DB_PATH.endswith(
    os.path.join("WeeklyReport", "protein_lab", "protein_lab.db")), \
    "测试必须使用临时库"
print("2. 临时库隔离 OK:", models.DB_PATH)

# ── 3. WAL 未 checkpoint 时，在线备份仍含最新写入 ──
# 单独开一个连接关掉 autocheckpoint，写入后保持连接不关：主库的 -wal 里留着数据。
writer = sqlite3.connect(PROD_DB, timeout=30)
try:
    writer.execute("PRAGMA wal_autocheckpoint = 0")
    writer.execute(
        "INSERT INTO proteins (name, sequence, tag, notes) VALUES (?,?,?,?)",
        ("WAL_ONLY", "MKRWAS", "backup-test", "未 checkpoint 也要进备份"),
    )
    writer.commit()
    assert os.path.exists(PROD_DB + "-wal"), "WAL 模式应生成 -wal 文件"

    backup_path = os.path.join(TMP, "backup.db")
    models.backup_db_to(backup_path)
finally:
    writer.close()

bconn = sqlite3.connect(backup_path)
try:
    row = bconn.execute(
        "SELECT name, tag FROM proteins WHERE name='WAL_ONLY'").fetchone()
finally:
    bconn.close()
assert row == ("WAL_ONLY", "backup-test"), \
    f"备份应包含 WAL 中尚未 checkpoint 的写入，实际 {row!r}"
print("3. WAL 在线备份包含最新写入 OK")

# ── 4. 恢复：复制回主库 + 清 -wal/-shm，数据回到备份时点 ──
# 备份后再写一条，模拟「备份之后又做了实验」
models.protein_create("AFTER_BACKUP", "MKRWAS")
assert models.protein_get_by_name("AFTER_BACKUP") is not None

# 按 README/CLAUDE.md 的恢复步骤：关连接（本测试每次调用即关）→ 覆盖主库 →
# 删残留 -wal/-shm（否则 SQLite 会把旧 WAL 重放到刚恢复的库上）→ 重开。
for suffix in ("-wal", "-shm"):
    stale = PROD_DB + suffix
    if os.path.exists(stale):
        os.remove(stale)
shutil.copy2(backup_path, PROD_DB)

assert models.protein_get_by_name("WAL_ONLY") is not None, "恢复后应保留备份时数据"
assert models.protein_get_by_name("AFTER_BACKUP") is None, \
    "备份之后的新数据不应出现在恢复结果里（恢复到备份时点）"
assert models.protein_list(), "恢复后库应可正常查询"
print("4. 备份恢复（含 -wal/-shm 清理）OK")

# ── 5. 迁移前备份也走同一套恢复路径 ──
# 直接把备份当主库打开即可读取（SQLite 文件自包含），确保没有依赖原目录的副作用。
restored = tempfile.mkdtemp(prefix="protein_lab_restored_")
restored_db = os.path.join(restored, "protein_lab.db")
shutil.copy2(backup_path, restored_db)
models.DB_PATH = restored_db
models.init_db()  # 恢复库应能直接迁移/打开
assert models.protein_get_by_name("WAL_ONLY") is not None
print("5. 备份文件独立可打开/可迁移 OK")

print("\nALL PASSED")
