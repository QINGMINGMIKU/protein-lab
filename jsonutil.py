"""JSON 防漂移小工具 — 历史数据可能把 JSON 字符串再编码一层（双重编码）。

`models`（params/results/payload/raw）、`identity`（读取历史实验判身份）、
`tools/strip_params_pointdata`（一次性迁移）都要解这份历史格式。此前三处各写一遍，
且宽容度不同（一处最多解 3 层、两处循环到底）——统一到这里，避免下次只改一处。
"""
import json


def unwrap_json(val):
    """循环解到非字符串为止。结果不强制 dict——旧浓度格式的 results 可能是 list。"""
    while isinstance(val, str):
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            break
    return val


def as_dict(val) -> dict:
    """解包后只接受 dict；其余（list / None / 坏 JSON）一律 {}。"""
    val = unwrap_json(val)
    return val if isinstance(val, dict) else {}
