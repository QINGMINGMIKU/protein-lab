# Bigo.bio BDA Workbench 全应用 UI/前端重设计计划

- **Branch:** `ui-design`
- **Date:** 2026-08-20
- **Status:** Implemented
- **Visual source:** Molecular Blueprint (`2026-07-25-bigo-bda-landing-page-design.md`) — tokens only, not the marketing landing page.

## Summary

- Keep Flask, Jinja, native JavaScript, existing database and APIs. No React, Astro, or frontend build chain.
- Visible brand: **Bigo.bio BDA Workbench**. Default English with instant Chinese switch. `/` continues into Research Trace.
- Cover `/research`, `/proteins`, `/calculator`, `/experiments` and experiment detail. Fix mobile nav, toolbars, table overflow, and vertical-glyph stacking.

## Global Constraints

- Warm Paper palette (ui-design2, source: BDA-demo): canvas `#F3F0EA`, surface `#FBF8F1`, carbon `#141414`, graphite `#4E4A44`, amber accent `#C8791E` (hover `#A96316`), structural rule `#D8D1C5`. Semantic status: success `#3F7A57`, warning `#B97922`, danger `#B4483F`, info `#4A6478`.
- Desktop max frame 1920px with five-column fixed dashed guides; hide guides below 1024px. Workbench spacing 32–64px, not marketing 192px pauses.
- Cards 6–14px radius with soft shadow; buttons stay square (`rounded-none`). 1px solid borders (dashed only for grid guides and free-attach chains). Minimum hit target 44px. Focus: 2px amber outline with 2px offset.
- Amber-filled controls use carbon text. Status never relies on color alone; stance chips use semantic success green.
- Local fonts only: Inter Variable, JetBrains Mono (default UI mono), Noto Sans SC. No CDN.
- `window.BigoI18n` in `static/i18n.js`: `t`, `apply`, `setLocale("en"|"zh-CN")`, `locale`. Persist `localStorage["bigo.locale"]`. Default `en`.
- User-entered titles, tags, sequences, and experiment names are not translated. Stored exp types, node types, and stance keywords stay as stored values; labels map at display time.
- Preserve all `/api/*` contracts, tool IDs (`conc|dilution|bli|akta|weblogo|enzyme|copy`), and research DOM ids (`researchFlow`, `researchFlowBack`, `res-layout`, `res-detail-side`).
- Repo / Python / DB / MCP identifiers remain `protein_lab`.

## Implementation Changes

### 1. Design system, brand, app shell
Unified CSS tokens, five-column scaffold, Bigo.bio header, mobile full-screen menu (Escape, focus lock, scroll lock), inline SVG icons, local fonts under `static/fonts/`.

### 2. Bilingual layer
`static/i18n.js` + `inject_static_version()` includes it. Unknown backend errors show a localized generic title with expandable raw message.

### 3. Page flows
- **Research Trace:** two-level root list → single-root evidence chain. Semantic `<ul>/<li>` vertical chain, default expanded, solid parent links / dashed free-attach. Node shows title, type, tags, stance chip. Actions in sticky desktop sidebar / mobile drawer.
- **Protein Library:** desktop table; 390–767px record list. Unified search/tag/FASTA/add toolbar. Bulk actions only after selection. Detail as sidebar/drawer. Monospace sequence with safe wrap or local scroll.
- **BDA Workbench:** four groups (Prepare / Analyze / Sequence / Reuse) keeping original tool IDs. Hash `#tool=`. `?load_exp=` wins. BLI / AKTA / enzyme: upload + core + results + save visible; secondary params in keyboardable Advanced `<details>`. Wide tables only inside `.table-scroll`.
- **Evidence Archive:** desktop table / mobile record list. Confirmations name the object and impact. Detail: summary → research → results → collapsed raw snapshot → export/load actions.

## Verification

Each loop: implement → `python test_models.py` `test_bli.py` `test_akta.py` `test_research.py` `test_ui.py` → browser check → fix.

CI must run `test_research.py` and `test_ui.py` before the build.

## Loop Log

| Loop | Date | Tests | Notes |
|------|------|-------|-------|
| 2 | 2026-08-20 | all five scripts passed | English default copy, i18n wiring, enzyme Advanced time panel, CI includes research+ui tests. |
| 3 | 2026-08-20 | all five scripts passed | Dialog overlay/Escape cancel as null; unique mobile+desktop bulk IDs; Weblogo search restored; leftover JS i18n; stack-on-narrow; exp-type option apply scoped. |
| 4 | 2026-08-20 | all five scripts passed | PLAN gap-fill: spec packs static/fonts only; backend errors expandable; named archive deletes; evidence-status on BLI/AKTA/enzyme; 44px hits; cyan/carbon; detail load/export after raw. |
| 5 | 2026-08-20 | all five scripts passed | PyInstaller onedir smoke (`dist/protein_lab/_internal/static/fonts/NotoSansSC-Regular.otf`); Chrome matrix 390–2560 × 10 routes no page overflow; enzyme plate local `.table-scroll`; error toasts 8s; mobile sticky actions padded. |
| 6 | 2026-08-21 | all five scripts passed | **ui-design2 分支 — Warm Paper 迁移**（源：BDA-demo `frontend/src/index.css`）：token 换纸面琥珀（`#F3F0EA`/`#FBF8F1`/`#C8791E`）、JetBrains Mono 换 IBM Plex Mono（打包进 static/fonts）、dashed→solid 边框、卡片圆角+soft shadow、按钮保持方角、语义状态色（success/danger/info）、stance support 改语义绿、app.js/模板内联色收敛到 CSS 变量。布局结构（1920 五列引导线/44px 命中区/类名/DOM id）全部保留。 |

## ui-design2 — Warm Paper 迁移决策

- 仅换视觉语言，不动布局结构、DOM id、API 契约、i18n。
- 跟随 BDA-demo：默认字体栈 JetBrains Mono → Noto Sans SC（中文 fallback），`tabular-nums` 对齐数据列。
- `grid-guides` 与 `free-attach` 虚线保留（布局引导 / 自由挂载语义），其余全部 solid。
- `.btn` 保持 `border-radius: 0`（BDA 按钮方角）；卡片/面板/下拉 6–14px 圆角 + shadow。
- 立场 chip 支持态从 cyan 改为语义绿 `--success`（支持=绿 / 反驳=红 / 部分=橙 / 不确定=灰蓝，与 BDA statusTone 语义一致）。

## Explicit exclusions

No marketing landing page, dashboard, CMS, analytics, schema changes, or public API changes.
