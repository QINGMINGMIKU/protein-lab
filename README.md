# Protein Lab v0.0.1

本地蛋白质实验管理系统。Flask 后端 + 纯 SQLite，无需网络、数据完全本地。

## 功能

- **蛋白库** — 手动添加 / FASTA 批量导入 / 搜索匹配
- **计算工具** — Beer-Lambert 浓度计算（Pace 1995 消光系数，与 Expasy ProtParam 一致）、BLI 梯度稀释规划（递推稀释 + 统一体积 + 整百微升取整）
- **实验归档** — 从计算工具一键保存 / 按实验导出 Excel / 历史实验回填
- **MCP 服务器** — 7 个工具，供 Claude 等 AI 通过 MCP 协议调用

## 环境要求

- Python 3.9+
- 依赖：`pip install -r requirements.txt`

## 启动

双击 `启动.bat`，浏览器自动打开 http://127.0.0.1:5000。关闭命令行窗口即停止服务。

## 配置 MCP（可选）

在 Claude Code 的 `.claude/settings.json` 中添加：

```json
{
  "mcpServers": {
    "protein-lab": {
      "command": "python",
      "args": ["path/to/protein_lab/mcp_server.py"]
    }
  }
}
```

## 目录结构

```
protein_lab/
├── app.py              Flask 主应用
├── calculators.py      计算核心（MW / ε / 浓度 / 稀释）
├── models.py           SQLite 数据模型
├── mcp_server.py       MCP stdio 服务器
├── requirements.txt    依赖
├── 启动.bat            一键启动
├── templates/          Jinja2 页面模板
├── static/             JS + CSS
└── protein_lab.db     自动生成，首次运行创建
```
