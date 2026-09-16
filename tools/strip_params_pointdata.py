"""tools/strip_params_pointdata.py — 历史酶活 `params.wells` 去逐点（一次性迁移）

背景：契约规则 A 要求「逐点数据只在 experiment_raw」。新写入的实验已合规，但 5 条历史实验的
`params.wells[*].times/.od` 仍内嵌曲线——那是**被当时时间窗截断后**的副本（#41 源 90 点只存
16 点）。#47 更糟：其 `times` 单位误为**分钟**，任何「从 params.wells 重拟合/出图」的路径都会
拿到 60× 的值和 0.49 min 的轴（注意：它**存档的 fit 是对的**，当年是用秒算的）。

本脚本把历史 params 清成合规形状：
  · 删 `wells[*].times` / `.od`；
  · **保留** name/ref/group/protein_id/mw/conc_ng_ml/conc_uM/fit/od_range（详情页/导出/对比都读这些）；
  · `meta` 与 `time_axis` 用 raw 的权威值（秒）覆写，并消掉 `meta.time_unit` 这个错误标签。

**唯一防线（fail-closed，逐实验原子）**：某孔的逐点**只有**在最新 `enzyme_traces` raw 里该孔
有完整曲线、且 raw 点数 ≥ params 点数时才允许删。任一孔不满足 → **整条实验跳过**，一个点都不动。
宁可留下不合规的历史数据，也不能删掉唯一副本或用截断覆盖全量。

跑法（**必须用 venv python**；写库前请先关闭运行中的服务）：
    .venv/Scripts/python.exe tools/strip_params_pointdata.py                 # 默认 dry-run
    .venv/Scripts/python.exe tools/strip_params_pointdata.py --apply         # 备份 + 写入
    .venv/Scripts/python.exe tools/strip_params_pointdata.py --only 31,33 --apply
    .venv/Scripts/python.exe tools/strip_params_pointdata.py --db <库路径>    # 演练用

幂等：已无逐点的实验判为 SKIP，重跑无副作用。`params` 是可变的「手动参数层」，覆写不违反
契约；raw 一行不动（规则 C）。
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import models

POINT_KEYS = ("times", "od")
BACKUP_PREFIX = "pre-strip-params_"
BACKUP_KEEP = 5
# 掉了就找不回来的孔位元数据（详情页 / 导出 / 对比都读）——显式列出，防手滑扩大删除面
KEEP_WELL_KEYS = ("name", "ref", "group", "protein_id", "mw",
                  "conc_ng_ml", "conc_uM", "fit", "od_range")


def _as_dict(v):
    """params/results 可能是双重编码的 JSON 字符串（历史遗留）——防御性解包。"""
    while isinstance(v, str):
        try:
            v = json.loads(v)
        except (ValueError, TypeError):
            return {}
    return v if isinstance(v, dict) else {}


def _wells_key(params: dict) -> str:
    """历史 params 用过 `wells` 与 `well_info` 两种键名——就地覆写，不换键名。"""
    return "wells" if isinstance(params.get("wells"), dict) else "well_info"


def latest_enzyme_raw(eid: int):
    """取**最后一条** enzyme_traces 快照（规则 C：最后一条 = 当前状态）。返回 (payload, raw_id)。"""
    for r in reversed(models.exp_raw_list(eid)):
        if (r.get("data_type") or "") != "enzyme_traces":
            continue
        row = models.exp_raw_get(r["id"]) or {}
        return _as_dict(row.get("payload")), r["id"]
    return None, None


def plan_experiment(eid: int, exp: dict = None) -> dict:
    """算出去逐点计划（**只读**，不写库）。返回 action ∈ {strip, skip, fail}。

    strip → {"params": <新 params>, "raw_id", "n_wells", "n_points"}；
    skip  → 合规/幂等/非酶活，无需动作；fail → 缺唯一副本，**必须跳过该实验**。
    """
    e = exp if exp is not None else models.exp_get(eid)
    if not e:
        return {"action": "fail", "reason": "实验不存在"}
    params = _as_dict(e.get("params"))
    if (params.get("calc_type") or "") != "enzyme":
        return {"action": "skip", "reason": f"非酶活实验（calc_type={params.get('calc_type')!r}）"}
    wkey = _wells_key(params)
    wells = params.get(wkey) or {}
    if not wells:
        return {"action": "skip", "reason": "无 wells"}
    pointed = {wid: w for wid, w in wells.items()
               if isinstance(w, dict) and any(k in w for k in POINT_KEYS)}
    if not pointed:
        return {"action": "skip", "reason": "已无逐点数据（幂等）"}

    payload, rid = latest_enzyme_raw(eid)
    if payload is None:
        return {"action": "fail",
                "reason": f"{len(pointed)} 个孔仍内嵌逐点，但无 enzyme_traces 原始快照"
                          f"——逐点是唯一副本，不可删"}
    raw_wells = payload.get("wells") or {}
    for wid, w in sorted(pointed.items()):
        rw = raw_wells.get(wid)
        if not isinstance(rw, dict):
            return {"action": "fail", "reason": f"{wid} 在原始快照中不存在——不可删其逐点"}
        rt, ro = rw.get("times") or [], rw.get("od") or []
        if not rt or len(rt) != len(ro):
            return {"action": "fail", "reason": f"{wid} 原始快照曲线不完整（{len(rt)} 点）"}
        n_arch = len(w.get("times") or [])
        if len(rt) < n_arch:
            return {"action": "fail",
                    "reason": f"{wid} 原始快照 {len(rt)} 点 < params {n_arch} 点"
                              f"——拒绝用截断数据覆盖全量"}

    new_wells = {}
    n_points = 0
    for wid, w in wells.items():
        if not isinstance(w, dict):
            new_wells[wid] = w
            continue
        if any(k in w for k in POINT_KEYS):
            n_points += len(w.get("times") or [])
        # 白名单式重建：只留 KEEP_WELL_KEYS 里实际存在的键
        new_wells[wid] = {k: v for k, v in w.items() if k in KEEP_WELL_KEYS}
    new_params = dict(params)
    new_params[wkey] = new_wells

    # meta：raw 的源文件解析值权威（时间是秒网格）；无论如何都摘掉 time_unit 误标
    raw_meta = _as_dict(payload.get("meta"))
    meta = dict(raw_meta) if raw_meta else dict(_as_dict(params.get("meta")))
    meta.pop("time_unit", None)
    new_params["meta"] = meta
    # time_axis：raw 的 payload.params.time_axis（秒）权威，params 里的可能是分钟
    rp = _as_dict(payload.get("params"))
    ta = rp.get("time_axis")
    if isinstance(ta, (list, tuple)) and len(ta) >= 2:
        try:
            new_params["time_axis"] = [float(ta[0]), float(ta[1])]
        except (TypeError, ValueError):
            pass

    return {"action": "strip", "params": new_params, "raw_id": rid,
            "n_wells": len(pointed), "n_points": n_points,
            "reason": f"{len(pointed)} 孔 × {n_points} 点由 raw#{rid} 覆盖"}


def targets_from_db(only=None) -> list:
    """扫描全部酶活实验（默认；--only 可限定）。"""
    out = []
    for e in models.exp_list(limit=9999):
        if only and e["id"] not in only:
            continue
        p = _as_dict(e.get("params"))
        if (p.get("calc_type") or "") == "enzyme":
            out.append(e["id"])
    return sorted(out)


def _backup() -> str:
    """在线备份到 backups/pre-strip-params_<ts>.db（保留 5 份）。

    用 `models.backup_db_to`（SQLite 在线备份 API）：事务一致，WAL 状态与并发读都不影响，
    胜过「checkpoint + copy」那种会因 checkpoint busy 而静默失效的做法。
    """
    bdir = os.path.join(os.path.dirname(models.DB_PATH), "backups")
    os.makedirs(bdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(bdir, f"{BACKUP_PREFIX}{stamp}.db")
    models.backup_db_to(dst)
    olds = sorted(f for f in os.listdir(bdir) if f.startswith(BACKUP_PREFIX))
    for f in olds[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(bdir, f))
        except OSError:
            pass
    return dst


def run(only=None, dry_run=True) -> int:
    ids = targets_from_db(only)
    print(f"酶活实验 {len(ids)} 条: {ids}\n")
    report = []
    for eid in ids:
        plan = plan_experiment(eid)
        if plan["action"] == "skip":
            report.append((eid, "SKIP", plan["reason"]))
            continue
        if plan["action"] == "fail":
            report.append((eid, "FAIL", plan["reason"]))
            continue
        if dry_run:
            report.append((eid, "DRY", plan["reason"]))
            continue
        models.exp_update(eid, params=plan["params"])
        report.append((eid, "WRITE", plan["reason"]))

    print("=" * 100)
    print(f"{'exp':>5}  {'结果':<6} 说明")
    print("-" * 100)
    for eid, status, note in report:
        print(f"{eid:>5}  {status:<6} {note}")
    print("=" * 100)

    if not dry_run:
        # 读回验证：逐点必须没了，而 fit / od_range 等元数据必须在（防白名单重建漏键）
        print("\n读回验证（逐点应消失 / fit 与 od_range 应保留）")
        bad = 0
        for eid, status, _ in report:
            if status != "WRITE":
                continue
            p = _as_dict((models.exp_get(eid) or {}).get("params"))
            wells = p.get(_wells_key(p)) or {}
            left = [w for w in wells.values() if isinstance(w, dict) and any(k in w for k in POINT_KEYS)]
            n_fit = sum(1 for w in wells.values() if isinstance(w, dict) and w.get("fit"))
            ok = not left
            bad += 0 if ok else 1
            print(f"  #{eid:<4} 残留逐点孔 {len(left)} | 带 fit 的孔 {n_fit} | {'✓' if ok else '✗'}")
        if bad:
            print(f"\n⚠ {bad} 条仍有残留逐点")
            return 1

    fails = [r for r in report if r[1] == "FAIL"]
    if fails:
        print(f"\n⚠ {len(fails)} 条因缺少原始副本被**跳过**（未改一行）——"
              f"这些实验的 params 保持原样，属已知不合规，需先补 raw 再清。")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="历史酶活 params.wells 去逐点（契约规则 A 合规化）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--only", default="", help="只处理指定实验 id，逗号分隔（如 31,33,41）")
    ap.add_argument("--db", default="", help="数据库路径（默认 models.DB_PATH = 生产库）")
    args = ap.parse_args()

    if args.db:
        models.DB_PATH = args.db

    only = None
    if args.only:
        only = {int(x) for x in args.only.split(",") if x.strip()}
        if not only:
            print(f"--only 解析为空")
            return 2

    print(f"数据库: {models.DB_PATH}")
    print(f"模式: {'APPLY（写库）' if args.apply else 'DRY-RUN（不写库）'}\n")
    if args.apply:
        print(f"已备份 → {_backup()}\n")
    return run(only, dry_run=not args.apply)


if __name__ == "__main__":
    raise SystemExit(main())