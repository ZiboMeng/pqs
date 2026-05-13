# PRD — Alt-archetype C: Cross-asset systematic

**Date**: 2026-05-12
**Status**: DESIGN
**Lineage**: `alt-archetype-cross-asset-2026-05-12`

---

## §1 Hypothesis

Pure cross-asset rotation among equities + bonds + commodities +
cash gives diversification independent of any individual stock alpha.
cycle04 cycle04-cross-asset attempted this with cluster_cap construction
but cluster A (drawup+amihud anchored) still tied to stock-side
sibling pattern.

Pure macro/cross-asset alpha (no stock-side individual picking) breaks
the geometry entirely.

---

## §2 Existing infrastructure leverage

- 6 Macro factors (Bucket Macro): yield curve, fed funds, DXY, WTI,
  VIX, CPI YoY
- 5 Sector relative (Bucket C)
- PRD-E TAA framework (dormant) — Phase 1+2 ship at PRD-E1 close:
  `core/research/taa/regime_rules.py`,
  `core/research/taa/asset_class_builder.py`,
  `core/research/taa/taa_harness.py`
- TAA verdict was 5/7 hard gates pass — defensive sleeve confirmed
  STRONG; standalone alpha non-viable (G2 + G6 fail)

**Insight**: TAA failed as STANDALONE because BULL year underperforms
SPY. But as DEFENSIVE OVERLAY (long-only with macro regime tilt) the
5 passing gates are exactly what fleet wants.

---

## §3 Design — TAA reactivation as defensive sleeve

**Reuse PRD-E TAA framework (mark dormant → mark active)** as a
defensive sleeve. NOT standalone alpha. Combines with cycle #09
nominee in 2-candidate fleet:
- BULL regime: lean into cycle #09 nominee (~80%) + TAA defensive 20%
- BEAR/CRISIS regime: invert — TAA defensive ~70% + cycle #09 30%

This is the **two-stage allocation** PRD-C-PRD-1 vision: stock
candidates + macro regime sleeve. PRD-E TAA Phase 2 G1 (2018 vs SPY
+8.08%) demonstrated the defensive sleeve works.

**Engineering**:
- TAA framework already shipped (PRD-E1 close `core/research/taa/`)
- Need: integrate with cycle #09 candidate output via fleet allocator
- Need: shadow mode for 1-2 quarters before live

**Estimate**: 2 weeks (mostly fleet integration, TAA modules dormant
but functional)

---

## §4 Acceptance

- TAA standalone gates from PRD-E1 close memo (5/7 pass; documented
  acceptable as defensive)
- Fleet-combined acceptance via Candidate Fleet Allocator PRD (which
  is HARD PAUSED but can be reactivated for this purpose per CLAUDE.md)
- Forward observation: TD60 GREEN/YELLOW/RED similar to Trial 9

---

## §5 Fire trigger

- IF Trial 9 GREEN at TD60 → fleet has 2 candidates (Trial 9 + TAA
  defensive); reactivate Fleet Allocator + TAA modules
- IF cycle #09 produces nominee → 2-candidate fleet (cycle #09 +
  TAA defensive)
- IF both above happen → 3-candidate fleet

Independent of Trial 9 verdict timing (TAA modules are ready; just
need fleet wiring).
