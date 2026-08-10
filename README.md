# Protein Lab v0.0.3

本地蛋白质实验管理系统。Flask 后端 + 纯 SQLite，无需网络、数据完全本地。

## 功能

- **蛋白库** — 手动添加 / FASTA 批量导入 / 搜索匹配 / 标签筛选与编辑 / **批量改标签**（选中多条添加/移除标签）/ **点击表头按 MW、消光系数排序**
- **计算工具**（5 个标签页）：
  - 蛋白浓度 — Beer-Lambert 计算（Biopython ProtParam 消光系数，与 Expasy 一致）
  - BLI 浓度梯度 — 递推稀释 + 统一体积 + 整百微升取整
  - Weblogo — 勾选蛋白生成序列标识图；**长序列自动分块换行**（每块 50 位，编号连续）；可选**位点区间**（起止位置）和**多聚体裁剪**（二聚体填 2 自动裁剪为单亚基）
  - 酶活计算 — TECAN Spark xlsx 解析 + 96 孔板 UI + 动力学拟合（ΔOD/min、R²）+ Michaelis-Menten 曲线 + 阴性扣除
  - 从实验复制 — 卡片式浏览历史实验，按类型过滤/搜索，一键加载到对应工具
- **实验归档** — 一键保存 / 单条或多条导出 Excel / 实验详情子页面 / 批量删除 + 撤销
- **MCP 服务器** — 7 个工具，供 Claude 等 AI 通过 MCP 协议调用

## 环境要求

- Python 3.9+
- 推荐使用虚拟环境（venv），依赖：`pip install -r requirements.txt`

## 启动

双击 `启动.bat`（Windows）或 `启动.command`（macOS），浏览器自动打开 <http://127.0.0.1:5000>。关闭窗口即停止服务。

启动时自动备份数据库到 `backups/`（保留最近 10 份）。

## 配置 MCP（可选）

在项目根目录 `.mcp.json` 中添加（注意用 venv 的 python，MCP 需要 biopython）：

```json
{
  "mcpServers": {
    "protein-lab": {
      "command": "path/to/protein_lab/.venv/Scripts/python.exe",
      "args": ["path/to/protein_lab/mcp_server.py"]
    }
  }
}
```

macOS 下 venv 路径为 `.venv/bin/python`。

## 目录结构

```
protein_lab/
├── app.py              Flask 主应用
├── calculators.py      计算核心（MW / ε / 浓度 / 稀释 / 酶活拟合）
├── models.py           SQLite 数据模型
├── mcp_server.py       MCP stdio 服务器
├── requirements.txt    依赖
├── 启动.bat            一键启动（Windows）
├── 启动.command        一键启动（macOS）
├── templates/          Jinja2 页面模板
├── static/             JS + CSS
├── backups/            数据库自动备份
└── protein_lab.db     自动生成，首次运行创建
```
