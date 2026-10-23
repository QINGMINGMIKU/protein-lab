# 2026-10-22 维护轮记录（功能冻结基线）

本轮目标不是加功能，而是把「交接/维护会踩的坑」处理到可接受，然后冻结功能，
由真实使用决定下一步。完成标准：核心流程正常、已知高风险问题处理完、剩余问题有记录。

## 本轮做了什么

### 1. 数据安全

| 改动 | 说明 |
|---|---|
| `import models` 无副作用 | 删除 models.py 末尾的 `init_db()`。显式初始化点：`app.py` main、`mcp_server.main()`、所有 `test_*.py`、`tools/*.py` |
| `PROTEIN_LAB_DB` 环境变量 | `models.DB_PATH` 可用环境变量覆盖，测试/脚本无需改代码即可指向临时库 |
| `test_backup.py` | ① 子进程验证 import 不建库且环境变量生效；② 在线备份包含尚未 checkpoint 的 WAL 写入；③ 恢复流程（删 `-wal`/`-shm` → 覆盖主库 → 重开）数据等于备份点；④ 备份文件可在空目录独立打开并迁移 |

验收证据：跑完整测试套件后，生产 `protein_lab.db` 的 mtime 未变化。

### 2. 维护负担

| 改动 | 说明 |
|---|---|
| `exports.py` | 从 app.py 抽出 Excel 导出（`export_excel` / `_enzyme_raw_wells` / 宽格式写器） |
| `jsonutil.py` | 收口历史双重编码 JSON 的防御性解包（`unwrap_json` / `as_dict`），identity.py 与 tools 复用 |
| 前端拆分 | `static/app.js` → 9 个 `app-*.js`（core/proteins/calculator/experiments/enzyme/weblogo-bulk/bli-akta/research/init），拼接后与拆分前**逐字节一致**（199784 字节） |
| 镜像常量断言 | `test_ui.py §12` 逐值比对前端 `CONC_UNITS` 与 `calculators.CONC_UNITS`、`ENZYME_ANALYSIS_VERSION` |

### 3. 交接一致性

- `requirements.txt` 补齐直接依赖：`numpy` / `pandas` / `matplotlib`（此前靠 logomaker 传递安装）。
- 文档与代码对齐：`import models` 不再初始化库、`static/app.js` → `app-*.js`、MCP 工具数 13 → 19、venv 说明、测试套件清单、Comparison 状态。
- `inject_static_version()` 改为扫描 `static/` 全部 `.js`/`.css`，拆分文件不再需要手工登记。

### 4. 使用回归

- `test_e2e.py`：真实样例走通 **导入 → 分析/绘图 → 保存 → 读原始快照 → restore → 再分析 → 导出**。
  - AKTA：`fixtures/1YPI_32 002.zip`（git 跟踪，CI 必跑）
  - BLI：`REF/20260708.csv`（缺失跳过）
  - 酶活：`REF/20260809_174326.xlsx`（缺失跳过）
  - 跨模块：档案列表、`loadable` 判定、汇总导出
- CI 的 Run tests 行已加入 `test_backup.py` 与 `test_e2e.py`。

## 遗留问题（不阻塞使用，已记录）

1. **非 `app.py` 入口不会自动建库**：`waitress-serve app:app`、gunicorn 等 WSGI 入口不再触发
   `init_db()`（这正是消除 import 副作用的结果）。正式入口只有 `python app.py`、
   `python app.py --mcp`、测试与 tools 脚本。若将来接外部 WSGI 服务器，需在启动脚本里显式
   `models.init_db()`。
2. **`--import-db` 仍用 `shutil.copy2`**：如果源库正在被服务写入且 WAL 未 checkpoint，
   直接复制主文件可能丢掉最新写入。使用前应先关闭源库服务（或对其做一次在线备份再导入）。
3. **Comparison 已实现，`used_sample_from` 未实现**：v0.1.6 的采样来源标注仍在待办（见 CLAUDE.md 路线）。
4. **CI 的 e2e 只覆盖 AKTA**：`REF/` 被 gitignore，BLI/酶活真实样例不会进 CI；本地跑才会执行。
5. **前端没有浏览器级自动化测试**：拆分经过 `node --check` 与源码级断言，但页面交互仍靠手动验证。
6. **undo 栈是内存态**：重启即失，上限 20 条（批量删除压一条），已知限制，不做持久化回收站。
7. **`supporting_exp_ids` 生产未使用**：现网研究节点该字段全为 `[]`，值得后续复盘是否删减。
8. **matplotlib 字体粗体告警**：打包字体只有 Regular，日志里的 `findfont: Failed to find font weight bold`
   无害，不影响出图。

## 冻结后的规则

- 只修**影响使用或数据正确性**的 bug。
- 新功能先看工具是否持续帮到科研，再决定是否投入。
- 任何涉及删改数据的测试仍必须用独立临时库或先备份（最高优先级不变）。
