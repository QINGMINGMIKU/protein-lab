"""一次性验证：从备份库回放「载入计算工具」酶活路径（只读，不碰生产库）。

同时证明两件事：
1. 回填前备份有效可读（不然后续出事没退路）；
2. 每条实验经 /api/enzyme/restore 能还原**源文件全量点数** + 时间窗下标 + 版本。
"""
import importlib
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKUP = sys.argv[1] if len(sys.argv) > 1 else ""
BACKUP = os.path.abspath(BACKUP)

# 测试库隔离顺序（CLAUDE.md）：先复制生产库到临时路径，绝不在生产库上跑
tmpdir = tempfile.mkdtemp(prefix="verify_enzyme_")
tmpdb = os.path.join(tmpdir, "protein_lab.db")
# 先 checkpoint 再复制：刚写的行可能还在 WAL 里，只 copy .db 会漏（假失败）。
# 服务在跑时 checkpoint 可能 busy → 重试；仍 busy 就带上 -wal/-shm 一起复制。
import sqlite3
import time as _t
for _ in range(5):
    _c = sqlite3.connect(BACKUP)
    try:
        _busy = _c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    finally:
        _c.close()
    if not _busy:
        break
    _t.sleep(1.0)
shutil.copy2(BACKUP, tmpdb)
for _s in ("-wal", "-shm"):                      # checkpoint 没成功时的兜底
    if os.path.exists(BACKUP + _s):
        shutil.copy2(BACKUP + _s, tmpdb + _s)

import models
importlib.reload(models)
models.DB_PATH = tmpdb
models.init_db()

from app import app
app.config["TESTING"] = True
c = app.test_client()

print(f"验证库: {tmpdb}\n")

TARGETS = {31: 90, 33: 180, 41: 90, 44: 90, 47: 90}
bad = 0
for eid, expect_src in sorted(TARGETS.items()):
    e = models.exp_get(eid)
    if not e:
        print(f"#{eid} 实验不存在"); bad += 1; continue
    params = e.get("params") or {}
    while isinstance(params, str):
        params = json.loads(params)
    arch = max((len((w or {}).get("times") or [])
                for w in (params.get("wells") or {}).values()), default=0)

    raws = [r for r in models.exp_raw_list(eid) if r["data_type"] == "enzyme_traces"]
    payload = (models.exp_raw_get(raws[-1]["id"]) or {}).get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    n_raw = max((len((w or {}).get("times") or []) for w in (payload.get("wells") or {}).values()),
                default=0)

    # 走真实端点回放
    r = c.post("/api/enzyme/restore", json={"payload": payload})
    if r.status_code != 200:
        print(f"#{eid} restore HTTP {r.status_code}: {r.get_json()}"); bad += 1; continue
    d = r.get_json()
    n_restore = max((len((w or {}).get("times") or []) for w in (d.get("wells") or {}).values()),
                    default=0)
    lo, hi = d.get("time_lo"), d.get("time_hi")
    w = d.get("version_warning")
    p = d.get("params") or {}
    switches = sorted(k for k in ("sub_blank", "show_blank", "align_start", "align_end",
                                  "error_bar", "group") if k in p)

    ok = (n_raw == expect_src and n_restore == expect_src
          and isinstance(lo, int) and isinstance(hi, int) and 0 <= lo <= hi < n_restore)
    bad += 0 if ok else 1
    print(f"#{eid:<3} 源 {expect_src:>3} | raw {n_raw:>3} | restore {n_restore:>3} "
          f"| 时间窗 idx [{lo},{hi}]（{hi - lo + 1} 点，全长 {d.get('n_points')}）"
          f" | 快照手动参数 {switches or '（历史未采集）'}"
          f" | {'✓' if ok else '✗'}{'  版本告警: ' + w if w else ''}")

print()
print("全部通过 ✓" if not bad else f"⚠ {bad} 条异常")
shutil.rmtree(tmpdir, ignore_errors=True)
raise SystemExit(1 if bad else 0)