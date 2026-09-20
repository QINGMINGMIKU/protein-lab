"""tools/backfill_enzyme_raw.py — 历史酶活实验补写 experiment_raw 快照（一次性迁移脚本）

背景：酶活模块「载入计算工具」此前只读 `params.wells`（按时间窗**截断后**的曲线），
原始全量数据虽有落 raw 的设计，但 5 条历史实验里 3 条从未写过 raw、2 条写的是 v1 形状
（无 `params` 槽、六开关与源文件名缺失）。本脚本按「实验存储三段式契约」（见 CLAUDE.md）
把历史实验补齐成 v2 形状。

跑法（**必须用 venv python**）：
    .venv/Scripts/python.exe tools/backfill_enzyme_raw.py              # 默认 dry-run，只报告不写库
    .venv/Scripts/python.exe tools/backfill_enzyme_raw.py --apply      # 备份 + 写入
    .venv/Scripts/python.exe tools/backfill_enzyme_raw.py --apply --force   # 忽略幂等跳过
    .venv/Scripts/python.exe tools/backfill_enzyme_raw.py --only 31,33 --apply
    .venv/Scripts/python.exe tools/backfill_enzyme_raw.py --rollback 5,6

安全闸（写生产库前请先**关闭运行中的服务**）：
1. 默认 dry-run，不加 --apply 绝不写库；
2. --apply 前 `PRAGMA wal_checkpoint(TRUNCATE)` + 复制到 `backups/pre-enzyme-backfill_<ts>.db`（留 5 份）；
3. **指纹校验 fail-closed**：逐点比对源 xlsx 与存档 `params.wells` 的 OD，任一条不过就**中止该条**；
4. 幂等：已有 v2 形状（payload 含 `params` 槽）的快照 → 跳过，重跑无副作用；
5. raw **只插不更**（`models.exp_save_raw`）——旧行原样保留，`--rollback` 只删带 `backfill` 标记的行。

已知局限（如实记录）：历史实验的**六个作图开关从未落过库**，无从考证当时取值，回填的
`params` 只带 `time_axis`，开关字段留空 → 复制回填时走 UI 默认值。原始数据点会完整恢复，
但当时的显示开关无法复原——这是数据从未采集导致的，不是本次改造的缺陷。
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import models
from calculators import ENZYME_ANALYSIS_VERSION, parse_tecan_xlsx

# 已核实的映射：实验 id → 源 xlsx（相对 <source-root>）。全部经逐点 OD 比对通过。
TARGETS = {
    31: "Excel/20260815_164746.xlsx",
    33: "Excel/20260816_183541.xlsx",
    41: "Excel/20260818_164808.xlsx",
    44: "Excel/20260823.xlsx",
    47: "Origin/20260830_141108.xlsx",
}
DEFAULT_SOURCE_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "..", "Enzyme")
BACKUP_PREFIX = "pre-enzyme-backfill_"
BACKUP_KEEP = 5
OD_TOL = 1e-9
TIME_TOL = 0.02   # 存档 times 曾被 round(3) → 秒/分换算后容差放宽


def _sha12(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _basename(rel: str) -> str:
    return os.path.basename(rel.replace("\\", "/"))


# ── 指纹校验 ──────────────────────────────────────────────
def _match_slice(src_times, arch_times):
    """在源时间轴上定位存档序列所在的**连续切片**，返回 (offset, scale) 或 None。

    历史存档是「时间窗筛选后的连续子序列」，且 times 单位有两种写法：
    秒（Web 上传路径，直取源值）与分钟（#47 MCP 手写，= 源秒值/60 且 round(3)）。
    两者都试，命中即返回。"""
    n = len(arch_times)
    if n == 0 or n > len(src_times):
        return None
    for scale in (1.0, 60.0):
        # 容差随 scale 放大：分钟写法存档被 round(3) → 还原成秒后量化误差 ≤0.06 s，
        # 秒写法直取源值（浮点往返 ≤1e-9）。时间只是**对齐**用，OD 逐点相等才是真闸门。
        tol = TIME_TOL + 0.005 * scale
        for off in range(len(src_times) - n + 1):
            seg = src_times[off:off + n]
            if all(abs(seg[i] - arch_times[i] * scale) < tol for i in range(n)):
                return off, scale
    return None


def verify(parsed_wells: dict, arch_wells: dict):
    """逐点 OD 精确比对（fail-closed）。返回 (ok, note, offset_map)。

    存档孔位必须在源文件中存在；每个有 times 的孔都要能定位切片且 OD 逐点相等。
    没有 times 的孔（已是新契约形状）只校验孔位存在。"""
    missing = sorted(set(arch_wells) - set(parsed_wells))
    if missing:
        return False, f"存档孔位在源文件中缺失: {missing}", {}
    checked = matched = 0
    offsets = {}
    for wid, a in arch_wells.items():
        at, ao = (a or {}).get("times") or [], (a or {}).get("od") or []
        if not at:
            continue
        hit = _match_slice(parsed_wells[wid]["times"], at)
        if not hit:
            return False, f"{wid} 时间网格与源文件不匹配（存档首点 {at[0]}）", {}
        off, _ = hit
        so = parsed_wells[wid]["od"]
        for i in range(len(at)):
            if ao[i] is None or abs(so[off + i] - ao[i]) > OD_TOL:
                return False, (f"{wid} 第 {i} 点 OD 不一致: 源 {so[off+i]} vs 存档 {ao[i]}"), {}
        checked += 1
        matched += len(at)
        offsets[wid] = off
    if not checked:
        return True, "无可比对序列（存档不含 times，仅校验孔位）", offsets
    return True, f"{checked} 孔 × {matched} 点 OD 全部一致", offsets


# ─ payload 构造 ──────────────────────────────────────────
def build_payload(parsed: dict, arch_params: dict, rel: str, verify_note: str,
                  offsets: dict) -> dict:
    """按 v2 契约构造 payload：原始数据取**源文件全量**；手动参数从存档 params 抽取。

    `times` 统一写**秒**（规范单位，见 CLAUDE.md「单位铁律」）；存档若为分钟则换算。
    """
    arch_wells = arch_params.get("wells") or arch_params.get("well_info") or {}
    arch_unit = (arch_params.get("meta") or {}).get("time_unit")
    to_sec = 60.0 if arch_unit == "min" else 1.0

    wells = {}
    for wid, s in parsed["wells"].items():
        a = arch_wells.get(wid) or {}
        wells[wid] = {
            "name": a.get("name"),
            "ref": a.get("ref") or "",
            "group": a.get("group") or "",
            "times": list(s["times"]),   # 源文件全量（秒）
            "od": list(s["od"]),
        }

    # meta：源解析值权威（temps 是秒网格），叠加存档里有而源没有的溯源键（丢掉 unit 误标）
    meta = dict(parsed.get("meta") or {})
    for k, v in (arch_params.get("meta") or {}).items():
        if k not in meta and k != "time_unit":
            meta[k] = v

    time_axis = arch_params.get("time_axis")
    if isinstance(time_axis, (list, tuple)) and len(time_axis) >= 2:
        try:
            time_axis = [round(float(time_axis[0]) * to_sec, 3), round(float(time_axis[1]) * to_sec, 3)]
        except (TypeError, ValueError):
            time_axis = None
    else:
        time_axis = None

    params = {
        "calc_type": "enzyme",
        "meta": meta,
        "source_file": _basename(rel),
        "time_axis": time_axis,
        "well_count": len(wells),
        # 六开关**有意不写**：历史从未采集，写默认值等于伪造「当时就是默认」
    }
    return {
        "analysis_version": ENZYME_ANALYSIS_VERSION,
        "calc_type": "enzyme",
        "params": params,
        "source_file": _basename(rel),
        "meta": meta,
        "wells": wells,
        "backfill": {
            "by": "tools/backfill_enzyme_raw.py",
            "at": datetime.now().isoformat(timespec="seconds"),
            "source_path": rel.replace("\\", "/"),
            "source_sha256": _sha12(os.path.join(DEFAULT_SOURCE_ROOT, rel)) if os.path.exists(
                os.path.join(DEFAULT_SOURCE_ROOT, rel)) else None,
            "archived_time_unit": arch_unit,
            "verify": verify_note,
        },
    }


def _has_v2_raw(eid: int) -> bool:
    """幂等判定：已有酶活 raw 且其 payload 含 params 槽（= 已回填或新前端所写）。"""
    for r in models.exp_raw_list(eid):
        if (r.get("data_type") or "") != "enzyme_traces":
            continue
        row = models.exp_raw_get(r["id"]) or {}
        p = row.get("payload") or {}
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except (ValueError, TypeError):
                continue
        if isinstance(p, dict) and isinstance(p.get("params"), dict) and p.get("params"):
            return True
    return False


# ── 备份 ──────────────────────────────────────────────────
def _backup() -> str:
    """checkpoint 后复制生产库到 backups/（照 models._backup_before_migration 的做法，保留 5 份）。

    **必须确认 checkpoint 真的跑完**再复制：服务在跑时若恰有并发读，checkpoint 会返回 busy，
    此时复制到的 .db 可能**不含 WAL 里尚未落盘的内容** —— 备份静默失效。返回 (busy, log, n)
    三元组，非 0 就重试几次，仍不行则**中止回填**（宁可不写，也不能拿一份残缺备份当安全网）。"""
    bdir = os.path.join(os.path.dirname(models.DB_PATH), "backups")
    os.makedirs(bdir, exist_ok=True)
    for attempt in range(5):
        conn = models.get_db()
        try:
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            conn.close()
        busy, log_pages, checkpointed = (tuple(row) + (0, 0, 0))[:3]
        if not busy:
            break
        print(f"  checkpoint 被占用（busy={busy}，未落盘 {log_pages - checkpointed} 页），"
              f"重试 {attempt + 1}/5 …")
        time.sleep(1.0)
    else:
        raise RuntimeError(
            "WAL checkpoint 反复失败——备份不可靠。请**关闭正在运行的服务**后重试。")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(bdir, f"{BACKUP_PREFIX}{stamp}.db")
    shutil.copy2(models.DB_PATH, dst)
    # 复制后校验：WAL/SHM 若仍有内容说明快照不完整
    for suffix in ("-wal", "-shm"):
        side = models.DB_PATH + suffix
        if os.path.exists(side) and os.path.getsize(side) > 0 and suffix == "-wal":
            print(f"   {os.path.basename(side)} 非空（{os.path.getsize(side)} B）——"
                  f"备份可能不含最新写入，请核对后用 --rollback 或从旧备份恢复")
    olds = sorted(f for f in os.listdir(bdir) if f.startswith(BACKUP_PREFIX))
    for f in olds[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(bdir, f))
        except OSError:
            pass
    return dst


# ── 主流程 ────────────────────────────────────────────────
def run(targets: dict, source_root: str, dry_run: bool = True, force: bool = False) -> int:
    """执行回填，返回退出码（有 FAIL → 1）。dry_run=True 时绝不写库。"""
    report = []
    for eid, rel in sorted(targets.items()):
        path = os.path.join(source_root, rel)
        e = models.exp_get(eid)
        if not e:
            report.append((eid, rel, "FAIL", "实验不存在"))
            continue
        p = e.get("params") or {}
        if isinstance(p, str):
            p = json.loads(p)
        if (p.get("calc_type") or "") != "enzyme":
            report.append((eid, rel, "FAIL", f"calc_type={p.get('calc_type')!r} 非 enzyme"))
            continue
        arch_wells = p.get("wells") or p.get("well_info") or {}
        if not arch_wells:
            report.append((eid, rel, "FAIL", "存档无 wells"))
            continue
        if not os.path.exists(path):
            report.append((eid, rel, "FAIL", f"源文件不存在: {path}"))
            continue
        if _has_v2_raw(eid) and not force:
            report.append((eid, rel, "SKIP", "已有 v2 快照（幂等）；--force 可强制补写"))
            continue
        try:
            parsed = parse_tecan_xlsx(path)
        except Exception as ex:
            report.append((eid, rel, "FAIL", f"解析失败: {ex}"))
            continue
        ok, note, offsets = verify(parsed.get("wells") or {}, arch_wells)
        if not ok:
            report.append((eid, rel, "FAIL", f"指纹校验未通过: {note}"))
            continue
        payload = build_payload(parsed, p, rel, note, offsets)
        if dry_run:
            report.append((eid, rel, "DRY",
                           f"{note}；将写入 {len(payload['wells'])} 孔 × "
                           f"{len(next(iter(payload['wells'].values()))['times'])} 点"))
            continue
        rid = models.exp_save_raw(eid, "enzyme_traces", payload)
        report.append((eid, rel, "WRITE", f"raw#{rid} {note}"))

    # 报告
    print("\n" + "=" * 96)
    print(f"{'exp':>5}  {'结果':<6} {'源文件':<34} 说明")
    print("-" * 96)
    for eid, rel, status, note in report:
        print(f"{eid:>5}  {status:<6} {rel:<34} {note}")
    print("=" * 96)

    # 点数对照（回填后读回验证）
    if not dry_run:
        print("\n点数对照（实验 | 存档 params 点数 | 现存 raw 点数）")
        for eid, rel, status, note in report:
            if status != "WRITE":
                continue
            e = models.exp_get(eid)
            aw = (e.get("params") or {}).get("wells") or {}
            n_arch = max((len((w or {}).get("times") or []) for w in aw.values()), default=0)
            raw_wells = {}
            for r in reversed(models.exp_raw_list(eid)):
                if r["data_type"] == "enzyme_traces":
                    raw_wells = (models.exp_raw_get(r["id"]) or {}).get("payload", {}).get("wells") or {}
                    break
            n_raw = max((len((w or {}).get("times") or []) for w in raw_wells.values()), default=0)
            print(f"  #{eid:<4} params {n_arch:>4} 点 → raw {n_raw:>4} 点"
                  f"{'  ✓ 全量恢复' if n_raw > n_arch else ''}")

    fails = [r for r in report if r[2] == "FAIL"]
    if fails:
        print(f"\n⚠ {len(fails)} 条失败——已中止这些条目，未写入任何数据。")
    return 1 if fails else 0


def rollback(raw_ids: list) -> int:
    """只删带 `backfill` 标记的 raw 行（防误删真实快照）。"""
    conn = models.get_db()
    removed = 0
    try:
        for rid in raw_ids:
            row = conn.execute("SELECT payload FROM experiment_raw WHERE id = ?", (rid,)).fetchone()
            if not row:
                print(f"raw#{rid}: 不存在，跳过")
                continue
            try:
                payload = json.loads(row["payload"])
            except (ValueError, TypeError):
                payload = {}
            if not isinstance(payload, dict) or "backfill" not in payload:
                print(f"raw#{rid}: 无 backfill 标记，**拒绝删除**（保护真实快照）")
                continue
            conn.execute("DELETE FROM experiment_raw WHERE id = ?", (rid,))
            removed += 1
    finally:
        conn.commit()
        conn.close()
    print(f"已删除 {removed} 条回填快照")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="历史酶活实验补写 experiment_raw 快照（v2 契约）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--force", action="store_true", help="忽略幂等跳过")
    ap.add_argument("--only", default="", help="只处理指定实验 id，逗号分隔（如 31,33）")
    ap.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help="源数据根目录（默认 ../Enzyme）")
    ap.add_argument("--db", default="", help="数据库路径（默认 models.DB_PATH = 生产库）")
    ap.add_argument("--rollback", default="", help="删除指定 raw id（只删带 backfill 标记的）")
    args = ap.parse_args()

    if args.db:
        models.DB_PATH = args.db

    if args.rollback:
        ids = [int(x) for x in args.rollback.split(",") if x.strip()]
        return rollback(ids)

    targets = TARGETS
    if args.only:
        want = {int(x) for x in args.only.split(",") if x.strip()}
        targets = {k: v for k, v in TARGETS.items() if k in want}
        if not targets:
            print(f"--only {args.only} 未匹配任何目标（可选 {sorted(TARGETS)}）")
            return 2

    print(f"数据库: {models.DB_PATH}")
    print(f"源根目录: {os.path.abspath(args.source_root)}")
    print(f"模式: {'APPLY（写库）' if args.apply else 'DRY-RUN（不写库）'}  目标: {sorted(targets)}")
    if args.apply:
        dst = _backup()
        print(f"已备份 → {dst}")
    return run(targets, args.source_root, dry_run=not args.apply, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())