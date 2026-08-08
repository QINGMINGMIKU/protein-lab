#!/usr/bin/env python3
"""
Protein Lab MCP Server — 供 Claude 通过 MCP 协议访问蛋白数据库和计算工具
stdio 传输，标准 MCP JSON-RPC 协议

在 Claude Code 中配置:
  .claude/settings.json → mcpServers:
    "protein-lab": {
      "command": "python",
      "args": ["c:/WorkSpace/WeeklyReport/protein_lab/mcp_server.py"]
    }
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models
from calculators import calc_ext_coeff, calc_conc, calc_dilution_series

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
        "description": "按名称获取蛋白完整信息（序列、MW、消光系数、氨基酸组成）",
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
                "exp_type": {"type": "string", "description": "实验类型: BLI, SDS-PAGE, AKTA, 浓度测定, 其他"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 30"}
            },
            "required": []
        }
    },
    {
        "name": "save_experiment",
        "description": "归档一条实验记录到数据库",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "实验标题"},
                "exp_type": {"type": "string", "description": "实验类型: BLI, SDS-PAGE, AKTA, 浓度测定, 其他"},
                "protein_names": {"type": "array", "items": {"type": "string"}, "description": "关联蛋白名称列表（可选）"},
                "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                "params": {"type": "object", "description": "实验参数 (JSON object)"},
                "results": {"type": "object", "description": "实验结果 (JSON object)"},
                "notes": {"type": "string", "description": "备注"}
            },
            "required": ["title", "exp_type"]
        }
    },
]


def handle_initialize(id_, params):
    return send_response(id_, {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "protein-lab", "version": "1.0.0"}
    })


def handle_tools_list(id_, params):
    return send_response(id_, {"tools": TOOLS})


def handle_tools_call(id_, params):
    tool_name = params.get("name", "")
    args = params.get("arguments", {})

    try:
        if tool_name == "search_proteins":
            result = models.protein_list(args.get("query", ""))
            # 精简输出，不返完整序列
            brief = [{k: v for k, v in r.items() if k != "sequence"} for r in result]
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(brief, ensure_ascii=False, indent=2)}]})

        elif tool_name == "get_protein":
            p = models.protein_get_by_name(args["name"])
            if not p:
                return send_response(id_, {"content": [{"type": "text", "text": f"未找到蛋白: {args['name']}"}]})
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(p, ensure_ascii=False, indent=2)}]})

        elif tool_name == "list_proteins":
            result = models.protein_list()
            brief = [{k: v for k, v in r.items() if k != "sequence"} for r in result]
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(brief, ensure_ascii=False, indent=2)}]})

        elif tool_name == "calculate_concentration":
            a280 = float(args["a280"])
            oxidized = args.get("oxidized", True)
            path = float(args.get("path_length_cm", 1.0))

            name = args.get("name")
            sequence = args.get("sequence")

            if name:
                p = models.protein_get_by_name(name)
                if not p:
                    return send_response(id_, {"content": [{"type": "text", "text": f"未找到蛋白: {name}"}]})
                epsilon = p["ext_ox"] if oxidized else p["ext_red"]
                mw = p["mw"]
            elif sequence:
                c = calc_ext_coeff(sequence)
                epsilon = c["ext_ox"] if oxidized else c["ext_red"]
                mw = c["mw"]
            else:
                return send_response(id_, {"content": [{"type": "text", "text": "需要提供 name 或 sequence"}]})

            result = calc_conc(a280, epsilon, mw, path)
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        elif tool_name == "calculate_dilution":
            stock = float(args["stock_conc_uM"])
            start = float(args["start_conc_uM"])
            factor = float(args.get("dilution_factor", 2))
            steps = int(args.get("n_steps", 8))
            vol = float(args.get("vol_per_well_uL", 200))
            dead = float(args.get("dead_vol_uL", 5))

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
            exp_type = args.get("exp_type", "")
            limit = int(args.get("limit", 30))
            result = models.exp_list(exp_type, limit)
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

        elif tool_name == "save_experiment":
            protein_ids = []
            for name in args.get("protein_names", []):
                p = models.protein_get_by_name(name)
                if p:
                    protein_ids.append(p["id"])
            eid = models.exp_create(
                title=args["title"],
                exp_type=args["exp_type"],
                protein_ids=protein_ids,
                date=args.get("date", ""),
                params=args.get("params", {}),
                results=args.get("results", {}),
                notes=args.get("notes", ""),
            )
            saved = models.exp_get(eid)
            return send_response(id_, {"content": [{"type": "text", "text": json.dumps(saved, ensure_ascii=False, indent=2)}]})

        else:
            return send_error(id_, -32601, f"Unknown tool: {tool_name}")

    except Exception as e:
        return send_error(id_, -32000, str(e))


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
        elif method == "notifications/initialized":
            pass  # 无需回复
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
