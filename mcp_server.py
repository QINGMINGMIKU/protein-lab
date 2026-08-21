#!/usr/bin/env python3
"""
Protein Lab MCP Server — 供 Claude 通过 MCP 协议访问蛋白数据库和计算工具
stdio 传输，标准 MCP JSON-RPC 协议

在 Claude Code 中配置:
  .claude/settings.json → mcpServers:
    "protein-lab": {
      "command": "python",
      "args": ["path/to/protein_lab/mcp_server.py"]
    }
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models
import services
import research
import compare
from calculators import calc_ext_coeff, calc_conc, calc_dilution_series, convert_concentration

# ── MCP 读写契约（数据完整性规则 #6）──────────────────────
# 读工具（search/get/list/calculate_*）是纯函数：只查询 + 纯计算，零写库。
# 唯一写工具是 save_experiment（走 services.create_experiment 统一写入入口）。
# 新工具必须归入二者之一；读工具若意外触库写入，由 test_models 的"读零写库"
# 断言拦截（逐工具调用后对比库内容不变）。

SERVER_VERSION = "1.1.0"
WRITE_TOOLS = {"save_experiment"}


def _sanitize(p: dict, include_fp: bool = False) -> dict:
    """序列脱敏收口（IP 保护）：返回的蛋白 dict 一律剔除 sequence 明文。

    序列明文绝不出本地计算边界——AI/MCP 消费端只拿派生物（MW/ε/浓度）与指纹。
    include_fp=True 时（get_protein）额外给 SHA-256 指纹前 12 位，替代明文序列：
    可用来比对两蛋白是否同序列，又不泄露具体氨基酸。
    """
    import hashlib
    out = {k: v for k, v in p.items() if k != "sequence"}
    if include_fp and p.get("sequence"):
        out["sequence_fp"] = hashlib.sha256(p["sequence"].encode()).hexdigest()[:12]
    return out


def _strip_sequences(obj):
    """递归剔除嵌套 dict 里的 sequence 明文（IP 保护兜底）。

    蛋白库走 _sanitize；实验 params/results/raw 存档可能内嵌序列（历史数据 /
    外部写入），凡 MCP 把实验 payload 交出去的读工具都要过这里——"序列明文
    绝不出本地计算边界"对实验数据同样成立。
    """
    if isinstance(obj, dict):
        return {k: _strip_sequences(v) for k, v in obj.items() if k != "sequence"}
    if isinstance(obj, list):
        return [_strip_sequences(v) for v in obj]
    return obj


class InvalidParams(Exception):
    """工具参数错误 → JSON-RPC -32602（缺必填 / 类型错 / 语义不满足）。

    与 -32000（内部错误）分开：参数问题不该被当成服务端故障抛给调用方。
    """


def _need(args, tool, *keys):
    """断言必填参数在场（None / 空串视为缺失），缺失抛 InvalidParams。"""
    missing = [k for k in keys if args.get(k) in (None, "")]
    if missing:
        raise InvalidParams(f"{tool}: 缺少必填参数: {', '.join(missing)}")


def _fnum(args, tool, key, default=None):
    """数值参数：缺失用默认；给了但转不了 float 报 -32602（而非原始 ValueError）。"""
    if key not in args or args[key] is None:
        return default
    try:
        return float(args[key])
    except (TypeError, ValueError):
        raise InvalidParams(f"{tool}: 参数 '{key}' 应为数值，收到 {args[key]!r}")


def _inum(args, tool, key, default=None):
    """整数参数：缺失用默认；给了但转不了 int 报 -32602。"""
    if key not in args or args[key] is None:
        return default
    try:
        return int(args[key])
    except (TypeError, ValueError):
        raise InvalidParams(f"{tool}: 参数 '{key}' 应为整数，收到 {args[key]!r}")

# ── MCP JSON-RPC dispatcher ────────────────────────────────

def send_response(id_, result):
    msg = {"jsonrpc": "2.0", "id": id_, "result": result}
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def send_error(id_, code, message):
    msg = {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


TOOLS = [
    {
        "name": "search_proteins",
        "description": "按名称/标签搜索蛋白库。返回匹配蛋白的 id、名称、MW、消光系数等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词（匹配名称或标签）"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_protein",
        "description": "按名称获取蛋白完整信息（MW、消光系数、氨基酸组成、序列指纹）——序列明文按 IP 保护策略不返回，只给 SHA-256 指纹前 12 位",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "蛋白名称（精确匹配）"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "list_proteins",
        "description": "列出蛋白库中所有蛋白",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "calculate_concentration",
        "description": "由 A280 和蛋白名称计算摩尔浓度与质量浓度。也可直接传序列。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "蛋白库中的蛋白名称"},
                "sequence": {"type": "string", "description": "或直接提供氨基酸序列（当蛋白不在库中时）"},
                "a280": {"type": "number", "description": "A280 吸光度值"},
                "oxidized": {"type": "boolean", "description": "Cys 是否为氧化态/二硫键，默认 true"},
                "path_length_cm": {"type": "number", "description": "光程 (cm)，默认 1.0"}
            },
            "required": ["a280"]
        }
    },
    {
        "name": "convert_concentration",
        "description": "6 种浓度单位互转（M、uM、nM、mg/mL、ug/mL、ng/uL）。跨摩尔/质量换算需提供 mw (Da)，如 1 µM × MW/1000 = ng/uL。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "浓度数值"},
                "from_unit": {"type": "string", "description": "源单位: M / uM / nM / mg/mL / ug/mL / ng/uL"},
                "to_unit": {"type": "string", "description": "目标单位: M / uM / nM / mg/mL / ug/mL / ng/uL"},
                "mw": {"type": "number", "description": "分子量 (Da)，跨摩尔↔质量换算时必填"}
            },
            "required": ["value", "from_unit", "to_unit"]
        }
    },
    {
        "name": "calculate_dilution",
        "description": "计算 BLI/ELISA 等实验的梯度稀释方案。返回每一步所需的母液和缓冲液体积。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "蛋白库中的蛋白名称（可选，仅用于记录）"},
                "stock_conc_uM": {"type": "number", "description": "母液浓度 (μM)"},
                "start_conc_uM": {"type": "number", "description": "起始最高浓度 (μM)"},
                "dilution_factor": {"type": "number", "description": "稀释倍数，默认 2（即 2× 系列稀释）"},
                "n_steps": {"type": "integer", "description": "梯度步数，默认 8"},
                "vol_per_well_uL": {"type": "number", "description": "每孔所需体积 (μL)，默认 200"},
                "dead_vol_uL": {"type": "number", "description": "额外死体积 (μL)，默认 5"}
            },
            "required": ["stock_conc_uM", "start_conc_uM"]
        }
    },
    {
        "name": "list_experiments",
        "description": "列出归档的实验记录，可按类型筛选",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exp_type": {"type": "string", "description": f"实验类型族: {', '.join(models.EXP_TYPES)}（兼容旧筛选）"},
                "calc_type": {"type": "string", "description": "规范分析身份: concentration / dilution / bli_fit / akta / enzyme / weblogo / sds_page / other"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 30"}
            },
            "required": []
        }
    },
    {
        "name": "get_experiment",
        "description": "获取单条实验完整详情：params/results（含蛋白快照）+ 原始数据快照元数据 _raw（含分析版本，BLI/AKTA 曲线可复现）。序列明文按 IP 保护策略剔除",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exp_id": {"type": "integer", "description": "实验 id"}
            },
            "required": ["exp_id"]
        }
    },
    {
        "name": "get_experiment_raw",
        "description": "获取单条原始数据快照完整 payload（BLI 传感器曲线 / AKTA 峰轨迹等，用于复现分析）。序列明文按 IP 保护策略剔除",
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_id": {"type": "integer", "description": "原始快照 id（get_experiment 的 _raw[].id）"}
            },
            "required": ["raw_id"]
        }
    },
    {
        "name": "list_protein_tags",
        "description": "列出蛋白库当前全部标签（去重排序），可用于 search_proteins 的标签筛选",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_research_trees",
        "description": "列出研究脉络森林（v0.1.0）：全部根目标，每棵递归嵌套 children。节点类型 goal(目标)/experiment(实验，含 exp_id 关联或为计划占位)/conclusion(结论)；evidence chain：目标→实验→结论→新目标",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_research_node",
        "description": "获取研究脉络单节点：递归子树 + 根→节点链（breadcrumb）+ 关联实验摘要。用于看一个目标/实验/结论的完整证据链上下文",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "integer", "description": "研究节点 id"}
            },
            "required": ["node_id"]
        }
    },
    {
        "name": "get_research_context",
        "description": "研究目标上下文（v0.1.2）：goal 本体 + 父目标链 + 子树实验 key results（完整 params/results + 原始快照元数据 _raw，序列明文剔除）+ 结论 epistemic status（立场 + 来源实验是否归档）+ 开放目标（子树内无结论的目标）。使能 AI 回答：现在在研究什么 / 哪些结论缺实验支持 / 哪些实验互相矛盾 / 目标验证到什么程度",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer", "description": "研究目标节点 id（根目标或子目标）"}
            },
            "required": ["goal_id"]
        }
    },
    {
        "name": "compare_experiments",
        "description": "横切对比同类实验的关键数（WT vs variant）：KD / 浓度 / 峰 / 酶活斜率。必须 2 条及以上且 calc_type 相同。只给对齐表，不下结论。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exp_ids": {"type": "array", "items": {"type": "integer"}, "description": "实验 id 列表，至少 2 个"}
            },
            "required": ["exp_ids"]
        }
    },
    {
        "name": "save_experiment",
        "description": "归档一条实验记录到数据库。可选挂到研究脉络目标下（v0.1.1）：传 goal_id（已有 goal 节点 id）或 new_goal={title,tag}（自动建根 goal 节点 + experiment 节点），二选一，都不传 = 暂不关联",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "实验标题"},
                "exp_type": {"type": "string", "description": f"实验类型: {', '.join(models.EXP_TYPES)}"},
                "protein_names": {"type": "array", "items": {"type": "string"}, "description": "关联蛋白名称列表（可选）"},
                "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                "params": {"type": "object", "description": "实验参数 (JSON object)。浓度测定建议传 a280 + (mw_da 或 epsilon_red/epsilon_ox)，计算出的浓度放 results.mean_uM / mean_mg_ml；服务端保存时自动附上绑定的蛋白快照并规范成标准形态"},
                "results": {"type": "object", "description": "实验结果 (JSON object)"},
                "notes": {"type": "string", "description": "备注"},
                "goal_id": {"type": "integer", "description": "已有研究脉络 goal 节点 id（与 new_goal 互斥，都给时 goal_id 优先）"},
                "new_goal": {"type": "object", "description": "新建根目标节点，自动建为根 goal 节点 + experiment 节点。形如 {\"title\": \"TIM 优化\", \"tag\": \"稳定性,TIM\"}",
                             "properties": {
                                 "title": {"type": "string"},
                                 "tag": {"type": "string"}
                             }}
            },
            "required": ["title", "exp_type"]
        }
    },
]


# 读工具 = 全部工具 - 写工具。新增工具若忘记归入 WRITE_TOOLS，会在这里立刻暴露（守卫断言）。
READ_TOOLS = {t["name"] for t in TOOLS} - WRITE_TOOLS


def handle_initialize(id_, params):
    return send_response(id_, {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "protein-lab", "version": SERVER_VERSION}
    })


def handle_tools_list(id_, params):
    return send_response(id_, {"tools": TOOLS})


def handle_tools_call(id_, params):
    tool_name = params.get("name", "")
    args = params.get("arguments", {}) or {}
    # 读写契约（规则 #6）：读工具零写库无运行时拦截——它们内部走 models 可写连接，
    # 任何 assert 都拦不住。真正的防线是 test_models 的"读零写库"断言（逐个调用后
    # 库内容逐字节不变），新增读工具必须在 test 的 read_cases 里注册。
    # WRITE_TOOLS / READ_TOOLS 仅作契约声明 + 测试引用，提醒新工具归入哪一侧。

    try:
        if tool_name == "search_proteins":
            _need(args, tool_name, "query")
            result = models.protein_list(args["query"])
            # 序列脱敏收口：不返序列明文（_sanitize）
            brief = [_sanitize(r) for r in result]
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(brief, ensure_ascii=False, indent=2)}]})

        elif tool_name == "get_protein":
            _need(args, tool_name, "name")
            p = models.protein_get_by_name(args["name"])
            if not p:
                return send_response(id_, {"content": [{"type": "text", "text": f"未找到蛋白: {args['name']}"}]})
            # 序列脱敏：指纹替代明文（include_fp）
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(_sanitize(p, include_fp=True), ensure_ascii=False, indent=2)}]})

        elif tool_name == "list_proteins":
            result = models.protein_list()
            brief = [_sanitize(r) for r in result]
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(brief, ensure_ascii=False, indent=2)}]})

        elif tool_name == "calculate_concentration":
            _need(args, tool_name, "a280")
            a280 = _fnum(args, tool_name, "a280")
            oxidized = bool(args.get("oxidized", True))
            path = _fnum(args, tool_name, "path_length_cm", 1.0)

            name = args.get("name")
            sequence = args.get("sequence")
            if not name and not sequence:
                raise InvalidParams(f"{tool_name}: 需要提供 name（库内蛋白）或 sequence（直接序列）之一")

            if name:
                p = models.protein_get_by_name(name)
                if not p:
                    return send_response(id_, {"content": [{"type": "text", "text": f"未找到蛋白: {name}"}]})
                epsilon = p["ext_ox"] if oxidized else p["ext_red"]
                mw = p["mw"]
            else:
                c = calc_ext_coeff(sequence)
                epsilon = c["ext_ox"] if oxidized else c["ext_red"]
                mw = c["mw"]

            result = calc_conc(a280, epsilon, mw, path)
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        elif tool_name == "convert_concentration":
            _need(args, tool_name, "value", "from_unit", "to_unit")
            value = _fnum(args, tool_name, "value")
            try:
                result = convert_concentration(value, args["from_unit"], args["to_unit"], args.get("mw"))
            except ValueError as err:
                raise InvalidParams(f"{tool_name}: {err}") from err  # 未知单位 / 跨摩尔质量缺 mw → 参数错
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps({
                "value": result, "from_unit": args["from_unit"], "to_unit": args["to_unit"],
                "mw": args.get("mw")}, ensure_ascii=False, indent=2)}]})

        elif tool_name == "calculate_dilution":
            _need(args, tool_name, "stock_conc_uM", "start_conc_uM")
            stock = _fnum(args, tool_name, "stock_conc_uM")
            start = _fnum(args, tool_name, "start_conc_uM")
            factor = _fnum(args, tool_name, "dilution_factor", 2)
            steps = _inum(args, tool_name, "n_steps", 8)
            vol = _fnum(args, tool_name, "vol_per_well_uL", 200)
            dead = _fnum(args, tool_name, "dead_vol_uL", 5)

            result = calc_dilution_series(stock, start, factor, steps, vol, dead)
            data = {
                "stock_conc_uM": stock,
                "dilution_factor": factor,
                "n_steps": steps,
                "vol_per_well_uL": vol,
                "steps": [{"step": s.step, "conc_uM": s.conc_uM,
                           "stock_vol_uL": s.stock_vol_uL,
                           "buffer_vol_uL": s.buffer_vol_uL} for s in result]
            }
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}]})

        elif tool_name == "list_experiments":
            exp_type = args.get("exp_type", "") or ""
            calc_type = args.get("calc_type", "") or ""
            limit = _inum(args, tool_name, "limit", 30)
            rows = models.exp_list(exp_type, limit, calc_type=calc_type)
            brief = [{k: row.get(k) for k in ("id", "title", "exp_type", "calc_type", "date", "protein_names")}
                     for row in rows]
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(brief, ensure_ascii=False, indent=2)}]})

        elif tool_name == "get_experiment":
            _need(args, tool_name, "exp_id")
            exp_id = _inum(args, tool_name, "exp_id")
            exp = models.exp_get(exp_id)
            if not exp:
                return send_response(id_, {"content": [{"type": "text", "text": f"未找到实验: {exp_id}"}]})
            exp["params"] = _strip_sequences(exp.get("params"))
            exp["results"] = _strip_sequences(exp.get("results"))
            import identity
            exp = identity.annotate(exp)
            exp["key_results"] = compare.key_results(exp)
            exp["_raw"] = models.exp_raw_list(exp_id, with_version=True)  # 快照元数据（含分析版本）
            exp["_raw_count"] = len(exp["_raw"])
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(exp, ensure_ascii=False, indent=2)}]})

        elif tool_name == "get_experiment_raw":
            _need(args, tool_name, "raw_id")
            raw_id = _inum(args, tool_name, "raw_id")
            raw = models.exp_raw_get(raw_id)
            if not raw:
                return send_response(id_, {"content": [{"type": "text", "text": f"未找到原始快照: {raw_id}"}]})
            raw["payload"] = _strip_sequences(raw.get("payload"))
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(raw, ensure_ascii=False, indent=2)}]})

        elif tool_name == "list_protein_tags":
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(models.protein_tags(), ensure_ascii=False, indent=2)}]})

        elif tool_name == "list_research_trees":
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(research.build_trees(), ensure_ascii=False, indent=2)}]})

        elif tool_name == "get_research_node":
            _need(args, tool_name, "node_id")
            nid = _inum(args, tool_name, "node_id")
            node = research.get_node_with_subtree(nid)
            if not node:
                return send_response(id_, {"content": [{"type": "text", "text": f"未找到研究节点: {nid}"}]})
            node["chain"] = research.get_chain(nid)
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(node, ensure_ascii=False, indent=2)}]})

        elif tool_name == "get_research_context":
            _need(args, tool_name, "goal_id")
            gid = _inum(args, tool_name, "goal_id")
            ctx = research.get_research_context(gid)
            if ctx is None:
                return send_response(id_, {"content": [{"type": "text", "text": f"未找到目标节点: {gid}"}]})
            ctx = _strip_sequences(ctx)  # IP 保护兜底：内嵌实验 params/results 一律剔序列明文
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(ctx, ensure_ascii=False, indent=2)}]})

        elif tool_name == "compare_experiments":
            _need(args, tool_name, "exp_ids")
            ids = args.get("exp_ids")
            if not isinstance(ids, list) or len(ids) < 2:
                raise InvalidParams(f"{tool_name}: exp_ids 须为至少 2 个整数的列表")
            out = compare.compare_experiments(ids)
            out = _strip_sequences(out)
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=2)}]})

        elif tool_name == "save_experiment":
            _need(args, tool_name, "title", "exp_type")
            exp_type = args["exp_type"]
            if exp_type not in models.EXP_TYPES:
                raise InvalidParams(
                    f"{tool_name}: exp_type 必须是 {', '.join(models.EXP_TYPES)} 之一，收到 {exp_type!r}")
            protein_ids = []
            for name in args.get("protein_names", []):
                p = models.protein_get_by_name(name)
                if p:
                    protein_ids.append(p["id"])
            goal_id = _inum(args, tool_name, "goal_id", None) if "goal_id" in args else None
            new_goal = args.get("new_goal")
            if new_goal is not None and not isinstance(new_goal, dict):
                raise InvalidParams(f"{tool_name}: new_goal 应为对象，收到 {type(new_goal).__name__}")
            if goal_id is not None and new_goal:
                new_goal = None  # 互斥，都给时 goal_id 优先
            saved = services.create_experiment(
                title=args["title"],
                exp_type=exp_type,
                protein_ids=protein_ids,
                date=args.get("date", ""),
                params=args.get("params", {}),
                results=args.get("results", {}),
                notes=args.get("notes", ""),
                goal_id=goal_id,
                new_goal=new_goal,
            )
            saved["params"] = _strip_sequences(saved.get("params"))
            saved["results"] = _strip_sequences(saved.get("results"))
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(saved, ensure_ascii=False, indent=2)}]})

        else:
            return send_error(id_, -32601, f"Unknown tool: {tool_name}")

    except InvalidParams as e:
        return send_error(id_, -32602, str(e))
    except ValueError as e:
        # 业务级参数错误（来自 services.create_experiment 等的 ValueError），与 InvalidParams 同语义
        return send_error(id_, -32602, f"{tool_name}: {e}")
    except Exception as e:
        return send_error(id_, -32000, f"{tool_name}: {e}")


# ── Main loop ──────────────────────────────────────────────

def main():
    # Windows 中文环境 stdio 默认 cp936，MCP 协议要求 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        id_ = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "initialize":
            handle_initialize(id_, params)
        elif method.startswith("notifications/"):
            pass  # 通知类（initialized/cancelled/progress）按规范不回复
        elif method == "tools/list":
            handle_tools_list(id_, params)
        elif method == "tools/call":
            handle_tools_call(id_, params)
        elif method == "ping":
            send_response(id_, {})
        else:
            send_error(id_, -32601, f"Unknown method: {method}")


if __name__ == "__main__":
    main()
