#!/usr/bin/env bash
# Protein Lab — Linux / macOS 启动脚本（对应 Windows 的 启动.bat）
# 用法：./启动.sh [--port 8080] [--mcp]
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

# 解释器优先级：$PROTEIN_LAB_PYTHON > 项目内 Linux venv > 项目内 venv > 用户级 venv > python3
PY="${PROTEIN_LAB_PYTHON:-}"
if [ -z "$PY" ]; then
    for cand in \
        ".venv-linux/bin/python" \
        ".venv/bin/python" \
        "$HOME/.venvs/protein-lab/bin/python"; do
        if [ -x "$cand" ]; then
            PY="$cand"
            break
        fi
    done
fi
if [ -z "$PY" ]; then
    PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
    echo "未找到 Python 解释器。请安装 Python 3，或用 PROTEIN_LAB_PYTHON 指定路径。" >&2
    exit 1
fi

exec "$PY" app.py "$@"
