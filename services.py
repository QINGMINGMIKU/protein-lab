"""实验写入服务 — HTTP 与 MCP 共用的统一 create 入口。

设计意图：所有「创建实验」最终都走 create_experiment，未来在这里挂：
- 审计（audit_log）
- 谱系血缘（experiment_links / copied_from）
- 原始数据分离（experiment_raw + analysis_version）
"""
from datetime import datetime

import models


def auto_exp_name(exp_type: str, date: str = "") -> str:
    """自动命名: {date}_{exp_type}_{seq:02d}，seq 为当天同类型已有标题的最大后缀 + 1"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    seq = models.exp_next_seq(exp_type, date)
    return f"{date}_{exp_type}_{seq:02d}"


def create_experiment(title: str, exp_type: str, protein_ids: list[int] = None,
                      date: str = "", params: dict = None, results: dict = None,
                      notes: str = "", auto_name: bool = True) -> dict:
    """统一创建实验：校验 + 自动命名 + 落库，返回完整实验 dict。

    auto_name=False 时标题留空不自动命名（MCP 已要求 title 必填，走默认 True 也无副作用）。"""
    exp_type = (exp_type or "").strip()
    if not exp_type:
        raise ValueError("实验类型不能为空")
    title = (title or "").strip()
    if auto_name and not title:
        title = auto_exp_name(exp_type, date)
    if isinstance(protein_ids, list):
        protein_ids = [int(p) for p in protein_ids if p]
    eid = models.exp_create(
        title=title, exp_type=exp_type, protein_ids=protein_ids,
        date=date, params=params, results=results, notes=notes,
    )
    return models.exp_get(eid)
