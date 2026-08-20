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

- Lab canvas `#E1E4E2`, instrument white `#F8F9F8`, carbon `#141716`, graphite `#626966`, assay cyan `#00D8C5`, deep cyan `#00AFA1`, structural rule `rgba(20, 23, 22, 0.15)`.
- Desktop max frame 1920px with five-column fixed dashed guides; hide guides below 1024px. Workbench spacing 32–64px, not marketing 192px pauses.
- Zero radius, no shadows, 1px dashed borders. Minimum hit target 44px. Focus: 2px cyan outline with 2px offset.
- Cyan-filled controls use carbon text. Status never relies on color alone.
- Local fonts only: Inter Variable, IBM Plex Mono, Noto Sans SC. No CDN.
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

## Explicit exclusions

No marketing landing page, dashboard, CMS, analytics, schema changes, or public API changes.
