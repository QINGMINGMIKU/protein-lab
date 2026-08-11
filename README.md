# Protein Lab v0.0.4

本地蛋白质实验管理系统。Flask 后端 + 纯 SQLite，无需网络、数据完全本地。

## 功能

- **蛋白库** — 手动添加 / FASTA 批量导入 / 搜索匹配 / 标签筛选与编辑 / **批量改标签**（选中多条添加/移除标签）/ **点击表头按 MW、消光系数排序**
- **计算工具**（5 个标签页）：
  - 蛋白浓度 — Beer-Lambert 计算（Biopython ProtParam 消光系数，与 Expasy 一致）
  - BLI 浓度梯度 — 递推稀释 + 统一体积 + 整百微升取整
  - Weblogo — 勾选蛋白生成序列标识图；**长序列自动分块换行**（每块 50 位，编号连续）；可选**位点区间**（起止位置）和**多聚体裁剪**（二聚体填 2 自动裁剪为单亚基）；**生成结果服务端缓存 + 切页自动恢复**（生成中切到其他页面看数据再回来，结果秒回、不丢失）
  - 酶活计算 — TECAN Spark xlsx 解析 + 96 孔板 UI + 动力学拟合（ΔOD/min、R²）+ Michaelis-Menten 曲线 + 阴性扣除；一键导出作图 Excel（**孔位-时间-OD 长格式** + 动力学汇总两个 Sheet，Origin/Prism 直接可用）
  - 从实验复制 — 卡片式浏览历史实验，按类型过滤/搜索，一键加载到对应工具
- **实验自动命名** — 系统变量 `{日期}_{实验类型}_{序号}`（如 `2026-08-11_酶活测定_01`），同一天同类型自动递增序号；可随时用自定义名称覆盖（留空即用默认名）。**导出也遵循自动命名**：作图 Excel、Weblogo PNG、动力学/MM 曲线 PNG 的文件名都用它（图按 `{名}_{图类型}` 区分）
- **图片下载** — Weblogo、动力学曲线、MM 曲线图下方一键下载 PNG（自动命名）；实验详情页的 Weblogo 图也可下载
- **实验归档** — 一键保存 / 单条或多条导出 Excel / 实验详情子页面 / 批量删除 + 撤销
- **MCP 服务器** — 7 个工具，供 Claude 等 AI 通过 MCP 协议调用

## 运行方式

### 方式一：源码 + venv（开发 / 无打包需求）

- Windows 双击 `启动.bat`，macOS 双击 `启动.command`，浏览器自动打开 <http://127.0.0.1:5000>。
- 首次运行自动创建 `.venv` 并安装依赖。关闭窗口即停止服务。
- 启动时自动备份数据库到 `backups/`（保留最近 10 份）。

### 方式二：打包版（v0.0.4，无需 Python）

- 从 GitHub Release 下载 `protein-lab-windows.zip` 或 `protein-lab-macos.zip`，解压后进入 `protein_lab/` 目录，双击 `protein_lab.exe`（Windows）/ 运行 `protein_lab`（macOS）即可。放在**可写目录**（如桌面/下载，不要放 `C:\Program Files`）。
- 打包采用 **onedir 目录形态**（非单文件）：**免启动解压、秒开、杀毒误报低**。
- 后端用生产 WSGI 服务器（waitress）：**启动无"开发服务器"警告、不刷访问日志**，控制台只显示产品 banner。
- 默认端口 **5000**，被占用时自动顺延（5001、5002…）不冲突；需固定端口用 `--port`：
  ```bash
  protein_lab.exe --port 8080
  ```
- 数据库 `protein_lab.db` 与 `backups/` 自动创建在**程序同目录**。首次运行是空库，想带现有数据，用 `--import-db`：
  ```bash
  protein_lab.exe --import-db <旧 protein_lab.db 路径>
  ```
- macOS 首次打开如提示"无法验证开发者"：右键 → 打开；或终端执行 `xattr -d com.apple.quarantine /路径/protein_lab/protein_lab`。

## 打包与发布

- 本地构建（Windows）：`.venv\Scripts\pip install -r requirements-build.txt` → `.venv\Scripts\pyinstaller protein_lab.spec --noconfirm` → 产物在 `dist/protein_lab/` 目录。
- CI 自动构建：**推送 `v*` tag** 时，GitHub Actions 在 `windows-latest` + `macos-latest` 分别构建 Windows / macOS 的 onedir 目录，压缩为 `protein-lab-windows.zip` / `protein-lab-macos.zip` 自动附加到该 tag 的 Release。无需自购 Mac。
- macOS 构建产物在 Mac 上运行，Mac 的 `.venv/bin/python` 同理（路径不同）。

## 配置 MCP（可选）

**方式 A（推荐，打包版）** — 直接用二进制 + `--mcp`：

```json
{
  "mcpServers": {
    "protein-lab": {
      "type": "stdio",
      "command": "C:/路径/protein_lab/protein_lab.exe",
      "args": ["--mcp"]
    }
  }
}
```
macOS 把 command 换成二进制路径（如 `/Applications/protein_lab/protein_lab`）。

**方式 B（源码 + venv）** — 注意用 venv 的 python（MCP 需要 biopython）：

```json
{
  "mcpServers": {
    "protein-lab": {
      "type": "stdio",
      "command": "/路径/protein_lab/.venv/Scripts/python.exe",
      "args": ["/路径/protein_lab/mcp_server.py"]
    }
  }
}
```
macOS 下 venv 路径为 `.venv/bin/python`。

## 目录结构

```
protein_lab/
├── app.py              Flask 主应用（含 --mcp / --import-db 入口分发）
├── calculators.py      计算核心（MW / ε / 浓度 / 稀释 / 酶活拟合）
├── models.py           SQLite 数据模型（DB 路径由 paths.app_base_dir() 决定）
├── mcp_server.py       MCP stdio 服务器
├── paths.py            路径解析（PyInstaller 打包与 dev 双模式）
├── fonts.py            CJK 字体解析 + matplotlib 中文配置
├── protein_lab.spec    PyInstaller 打包配置
├── requirements.txt    运行时依赖
├── requirements-build.txt  打包依赖（pyinstaller）
├── 启动.bat            一键启动（Windows）
├── 启动.command        一键启动（macOS）
├── templates/          Jinja2 页面模板
├── static/             JS + CSS
├── fonts/              Noto Sans SC（OFL，打包进二进制）
├── .github/workflows/  CI 双平台构建
├── backups/            数据库自动备份
└── protein_lab.db     自动生成，首次运行创建
```
