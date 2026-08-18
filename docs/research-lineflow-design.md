# Research Lineflow — 证据链 UI 重设计（设计稿，不动代码）

## 起源

评价拍板（2026-08-17）：研究脉络是「证据链」—— 目标 → 实验 → 结论 → 新目标。
当前 v0.1.0/v0.1.1 流程图卡片+连接线+tag 配色+折叠，**信息密度过高 / 拐弯太多**（评审 H/M 多条指出）。

设计目标：
- **直线**——证据链一眼读到底，不拐弯
- **重度简化**——卡片只放必要信息
- **极简直线+箭头**——连接线不抢戏
- **默认全展开**——折叠是少数场景
- **AI 操作优先**（MCP 端不受影响），但**人能一眼看懂**

## 4 个判断

| 项 | 决策 |
|---|---|
| 布局主轴 | 上下纵向（深度 = 行；同级 = 缩进+竖线连接） |
| 信息密度 | 重度简化：仅类型 icon + 标题 + tag chips |
| 连接线 | SVG 极简直线+箭头，弱色（父类型色 alpha 0.3） |
| 折叠 | 默认全展开；折叠按钮只在 ≥2 子节点时出现 |

## 旧版 vs 新版（文字版对比）

### 旧版（v0.1.0 流程图）
```
┌─ TIM 优化 ─────────────────┐
│ [icon] 标题                │
│ tag chip · tag chip        │
│ ▸ 折叠   [实验1] [实验2]   │ ←─ 卡片宽 232px，折叠/操作按钮挤一排
│  ↓ elbow   ↓ elbow         │ ←─ SVG 肘形拐弯连接
│ [实验1]   [实验2]          │
└─────────────────────────────┘
```

### 新版（lineflow）
```
ROOT: TIM 优化            [⛓ 自由] [edit]   ← 顶部分离工具条
│
├─ 🧪 2026-08-17_BLI_01     [PD1] [BLI]
│   │
│   └─ ✓ BLI KD=99.2nM     [支持]
│
├─ 🧪 2026-08-17_AKTA_01    [PD1]
│   │
│   └─ ✗ 峰位置偏移         [反驳]
│
└─ 🧪 2026-08-18_酶活_01    [PD1]       ← 折叠按钮：3 个同级 ≥2 才出
    │
    └─ △ 速率 +15%          [部分]
```

## 核心变更

### 1. 布局算法（旧 → 新）

**旧** `researchFlowLayout`：DFS 算 x/y，x=depth*280px, y=row 计数器 → 横滚 5+ 级。
**新** `lineflowLayout`：纯树形缩进 = 文本流。不用 SVG 坐标。
- 渲染 = `<ul>`/`<li>` 嵌套 DOM
- CSS `border-left: 2px solid var(--line-color)` on `<li>` 当连接线
- 深度 = DOM 层级（浏览器天然支持，无 JS 计算）
- 同级：CSS `padding-left` 一致
- 折叠：`details/summary` 原生 HTML，零 JS

### 2. 节点卡片（重度简化）

```
<div class="lf-node lf-node--experiment">
  <span class="lf-type">🧪</span>
  <span class="lf-title">2026-08-17_BLI_01</span>
  <span class="lf-tag">PD1</span>
  <span class="lf-tag">BLI</span>
</div>
```

**不再画**：
- ❌ 卡片左缘色条（用 icon 替代类型）
- ❌ 折叠按钮（在 li 上，无 children 时不渲染）
- ❌ 操作按钮（hover 显 inline 文本链："查看实验 →  关联到其他目标 →  编辑"）
- ❌ **结论块整卡左缘色条 + 卡片 tag 文字跟随立场**（旧版做法，v0.1.0 评审批过太重）——

**保留 + 强化结论立场色**（AI 决策可读 + 人能一眼看立场）：
- ✅ 节点类型 icon（goal 🎯 / experiment 🧪 / conclusion ✓/✗/△/○）
- ✅ 标题（链接到详情）
- ✅ tag chips（同名 tag 用同一浅色底）
- ✅ free_attach ⛓ 标记（仅在 experiment/conclusion 是 free_attach 时小标）
- ✅ breadcrumb 链视图（详情面板里，与 lineflow 共存）
- ✅ 选中态：背景色块（统一 `--accent` 半透明，不抢语义色）
- ✅ **结论 stance chip 强色**——专门画"立场色 chip"在结论节点的标题旁边（不是整卡片左缘），只标立场词（支持/反驳/部分/不确定），其他 tag 走浅底色 chip

### 2.1 结论 stance 视觉（旧版 vs 新版）

旧版（v0.1.0）：
- 整卡左缘色条 = stance 色
- 卡片内所有 tag 文字 = stance 色
- **问题**：整卡 232px 都染立场色，力度过强；同时把无关 tag 也染色（"PD1" 被染成支持绿，误导）

新版（lineflow）：
- 节点 icon 已经标识 type（conclusion = ✓/✗/△/○）
- 标题旁一个 **小尺寸 stance chip**，只显示 stance 词：
  ```
  ✓ BLI KD=99.2nM    [支持]
  ✗ 峰位置偏移       [反驳]
  △ 速率 +15%       [部分]
  ○ 重复性未测       [不确定]
  ```
- chip 颜色 = stance 浅底色 + 深字（与原 `RES_STANCE_CHIP` 配色一致：支持 #2e7d32/#e8f5e9，类推）
- **只标 stance 词**——PD1/BLI 这类普通 tag 走浅灰底 chip，不被立场色污染
- 整卡不再染色，**人眼聚焦在"这个结论站什么立场"**

CSS：
```css
.lf-stance { font-size: 11px; padding: 1px 8px; border-radius: 10px; margin-left: 6px; }
.lf-stance--support  { background: #e8f5e9; color: #2e7d32; }
.lf-stance--rebut    { background: #ffebee; color: #c62828; }
.lf-stance--partial  { background: #fff3e0; color: #e65100; }
.lf-stance--uncertain{ background: #f5f5f5; color: #757575; }
.lf-stance--other    { background: #f0f0f3; color: #5a6478; }
```

JS：复用 `resStanceKey()`（原立场键函数），但不再画整卡左缘色，只画 stance chip。

### 2.2 stance 操控控件（v0.1.2 增量）

立场色是 AI 决策可读信号，但**只展示不操控 = 死数据**。v0.1.2 在节点详情面板加 stance 控件。

**交互位置**：选中 conclusion 节点 → 详情面板出现「立场」控件（下拉 select）。experiment/goal 节点详情面板**不显示**（这些节点没有 stance 概念）。

**存储位置**：复用 `research_nodes.tag` 字段（与现状一致：'支持' / '反驳' / '部分' / '不确定'）。**零 schema 变更**，与 v0.1.0 评审批过的 stance 实现路径一致。

**下拉选项**（6 项含「清除」）：
```
[立场] ▼
  ───────
  （清除）           ← 移除 stance 词，节点走 other 灰色
  ✓ 支持            ← 绿
  ✗ 反驳            ← 红
  △ 部分            ← 橙
  ○ 不确定          ← 灰
  （未设）other     ← 与「清除」等价，但显式表达"未表态"
```

**保存语义**：
- 选 stance → 移除 tag 里旧的 stance 词，加入新的（保证唯一）
- 选「清除」/「other」→ 移除 tag 里所有 stance 词
- **不动** tag 里非 stance 词（PD1/BLI 保留）

JS 核心函数：
```js
const STANCE_VALUES = [
  { value: "",        label: "（清除）",   key: "other" },
  { value: "支持",   label: "✓ 支持",     key: "support" },
  { value: "反驳",   label: "✗ 反驳",     key: "rebut" },
  { value: "部分",   label: "△ 部分",     key: "partial" },
  { value: "不确定", label: "○ 不确定",   key: "uncertain" },
];
const STANCE_KEYWORDS = ["支持", "反驳", "部分", "不确定"];

function applyStanceToTag(tag, stanceValue) {
  // 移除旧的 stance 词
  const parts = String(tag || "").split(",").map(s => s.trim()).filter(Boolean);
  const kept = parts.filter(p => !STANCE_KEYWORDS.includes(p));
  // 加入新 stance 词（除非"清除"）
  if (stanceValue) kept.push(stanceValue);
  return kept.join(",");
}
```

**API 调用**：
- PUT `/api/research/nodes/<id>` body `{ tag: "PD1,BLI,支持" }` —— 现有端点，不动
- 成功后 `researchLoad()` 重拉数据 → 控件 + chip 同步更新

**详情面板布局**（在 conclusion 节点详情面板里）：
```
─────────────────────────────────────
立场  [✓ 支持  ▼]        ← 控件（仅 conclusion 节点）
─────────────────────────────────────
```

**快捷键 / 二次交互**：
- 不做行内下拉（避免与折叠/选中态交互冲突）
- 不做 drag 改 stance（避免与目标节点拖拽混淆——CLAUDE.md 已明确不做画布拖拽）
- 不做批量 stance（v0.1.2 单节点够用，批量等 v0.1.3 Comparison 时再说）

**为什么不在 `/research` 根列表上做 stance 控件**：
- 根列表显示根目标，conclusion 不在根列表第一屏
- 详情面板是"已知节点 + 已知上下文"的最稳交互

**测试覆盖**（test_research 14 节增量）：
- 14a. PUT stance 词到 tag：`update_node(node_id, tag="支持")` → 节点 chip 变色
- 14b. 替换：原 tag 里有「反驳」+「PD1」，改 stance 为「支持」→ tag 变「PD1,支持」
- 14c. 清除：选「清除」 → tag 里所有 stance 词移除，PD1/BLI 保留
- 14d. experiment/goal 节点详情面板**不显示** stance 控件
- 14e. stance 控件保存失败（API 4xx）→ 详情面板报错 toast，控件回到原值

### 3. 连接线（极简）

不用 SVG 路径肘形。改用 CSS `border-left`：

```css
.lf-tree li {
  position: relative;
  padding: 4px 0 4px 16px;
  border-left: 1px solid var(--line-color);
}
.lf-tree li::before {
  content: "";
  position: absolute;
  left: -1px; top: 14px;
  width: 12px; height: 1px;
  background: var(--line-color);
}
```

- 父类型 = 连接线颜色（alpha 0.3，让卡片自身说话）
- goal→goal: 绿 0.3
- goal→experiment: 绿 0.3（与 goal 节点同色，因为是父 goal 的延伸）
- experiment→conclusion: 蓝 0.3
- free_attach 边：虚线 `border-left-style: dashed`

### 4. 折叠（默认全展开）

```html
<details open>
  <summary>🎯 TIM 优化 <span class="lf-meta">3 子节点</span></summary>
  <ul>...</ul>
</details>
```

- `<details open>` 默认展开
- 折叠按钮 = `<summary>` 自带三角标（浏览器原生，零 CSS）
- 隐藏整棵子树时：`details:not([open])` 隐藏 `<ul>`
- **不画**折叠按钮单独控件——`<summary>` 自带的三角已够用
- 过滤态仍可强制全开（`<details open>` 不变），用 `[hidden]` 类标 dim

### 5. dim（搜索过滤时）

旧版：节点 `opacity: 0.4` + 子树连接线不跟随。
新版：dim 节点不隐藏，**但加左侧"未命中"竖线**：
```css
.lf-node--dim { opacity: 0.4; }
.lf-node--hit { /* 高亮背景 */ background: rgba(67, 97, 238, 0.08); }
```

- 命中节点仍可读
- 非命中节点仍可见（让用户看到"这一段是 dim 的，但上下文完整"）
- 不用透明度整体压暗，避免 0.4 边比 dim 父还显眼

### 6. 选中态

```css
.lf-node--selected {
  background: rgba(67, 97, 238, 0.1);
  box-shadow: inset 3px 0 0 var(--accent);
}
```

- 选中态 = 背景色块（不用左缘色条覆盖类型色）
- 与 dim、tag chips、icon 不冲突

### 7. 详情面板

旧版：链视图 breadcrumb + 节点详情 + children chips + 实验引用卡 + 计划占位。
新版：保留全部，**但布局更克制**——链视图放顶部一行，子节点 chips 单独一行，实验引用卡只显示实验类型+标题+日期，**不再画卡片**：

```
ROOT → 🧪 BLI 实验 → ✓ 结论            ← breadcrumb
─────────────────────
标题：2026-08-17_BLI_01
标签：PD1, BLI
立场  [✓ 支持 ▼]   ← v0.1.2 增量：仅 conclusion 节点显示，下拉含清除
关联实验：→ 详情 | 从-计算复制 | + 关联到其他目标
子节点：🧪 实验2   ✓ 结论1   ✓ 结论2      ← chips
─────────────────────
```

### 8. CSS 变量

```css
:root {
  --lf-line-goal: rgba(76, 175, 121, 0.3);
  --lf-line-experiment: rgba(74, 144, 217, 0.3);
  --lf-line-conclusion: rgba(217, 106, 166, 0.3);
  --lf-line-free: rgba(184, 134, 11, 0.4);
  --lf-accent: #4361ee;
  --lf-bg-dim: transparent;
  --lf-bg-hit: rgba(67, 97, 238, 0.08);
  --lf-bg-selected: rgba(67, 97, 238, 0.1);
  --lf-tag-bg: #f0f0f3;
  --lf-tag-bg-strong: #e8ebf3;
  --lf-line: #c3c8d4;
}
```

### 9. 数据契约

**不破坏**：
- 后端 `/api/research/nodes` 返 `research.build_trees()`（森林 + 嵌套 children）—— 旧/新通用
- 模型层 `research_nodes` 表 + `WHITELIST` + `free_attach` —— 不动
- MCP `list_research_trees` / `get_research_node` —— 不动
- 选中态 / 详情面板 API —— 不动

**前端替换**：
- `renderResearchFlow` 旧 `researchFlowLayout` + `<svg>` 路径 → 新 `<details>/<ul>/<li>` 文本流
- `RES_FLOW`/`RES_FLOW_EDGE`/`PLOT_STYLE` 颜色常量（部分保留给其他模块复用）
- `.res-flow-*` CSS 类 → `.lf-*` 新命名空间

## 不做

- ❌ 不重写 models / research service / MCP
- ❌ 不重写详情面板逻辑（链视图 / chips / 实验引用 / 计划占位）
- ❌ 不重写面包屑（链视图在详情面板里）
- ❌ 不画水平横轴流程图（原 `researchFlowLayout` + 卡片 232px 固定宽）
- ❌ 不画 SVG elbow path
- ❌ 不画左缘色条覆盖类型色
- ❌ 不画"其他"灰色与"无 tag"的微差配色（统一用浅底 tag 底色，文字差异够用）

## 评估

- **易读性**：✓ 缩进 + 文本流 = 任何网页/终端用户都看得懂
- **AI 操作**：✓ MCP 端零影响；详情/选中/CRUD API 不动
- **移动端**：✓ 纯文本流 + 缩进天然响应式，无横滚
- **打印/PDF**：✓ 文本流好打印（论文图备查可导出 SVG 当前方案作废，但 CLAUDE.md 路线表里 Prism 出版已 defer）
- **评审指出的"折叠/dim 拐弯"**：✓ 折叠走 `<details>` 原生；dim 走 `[hidden]` 类

## 评审预期

旧版 4 个 M11/M12/M14 + L2/L4/L6/L18/L19 视觉冲突问题：
- M11 连接线按父类型着色 vs 子卡片左缘色冲突 → 改 CSS border-left + 弱色解决
- M12 dim 边不跟随 → 改 dim 整体不透明度而非节点 + 子树分离
- M14 折叠态 + 过滤态 → 走 `<details open>` 原生
- L2-L19 配色微差 → 统一 CSS 变量
- **结论立场色**：v0.1.0 用「整卡左缘色条 + 卡片 tag 文字跟随立场」力度过强，污染无关 tag；新版用**只标 stance 词的 chip**（窄、强语义、不污染其他 tag）——AI 决策可读 + 人眼能一眼看立场

## 下一步

1. 用户 review 这份设计
2. 通过后改 `static/app.js` 渲染函数（`renderResearchFlow` → `renderLineflow`）
3. 改 `static/style.css` 加 `.lf-*` 命名空间，删旧 `.res-flow-*`
4. `templates/research.html` 微调（容器、按钮文案）
5. 跑 test_research（13 节）确认 API 契约不破
6. 手工 e2e：浏览器跑 /research 验证视觉
7. 改完一并 commit
</content>
</invoke>