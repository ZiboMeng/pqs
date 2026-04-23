#!/usr/bin/env python
"""Dump a ready-to-paste context pack for external LLMs (Gemini / Codex / etc).

PRD: docs/20260421-prd_framework_completion.md §11 M15 (reframed)
Companion doc: docs/20260421-llm_external_llm_handoff.md

Generates a markdown file containing:
  - Current PRODUCTION_FACTORS list
  - Current RESEARCH_FACTORS list
  - Recent rejected/archived candidates with reasons
  - Current universe composition (53 tradable symbols)
  - Recent regime distribution (last 252d)
  - The system-prompt template from docs/20260421-llm_external_llm_handoff.md

User copies the entire output into a chat window with Gemini / Codex /
whatever LLM they have, and asks for N factor candidates.

Output: docs/llm_handoff_seed_<timestamp>.md (ephemeral; regenerable)

Usage:
  python scripts/dump_llm_handoff_context.py
  python scripts/dump_llm_handoff_context.py --out my_seed.md
  python scripts/dump_llm_handoff_context.py --lookback-days 252
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _get_factor_lists():
    from core.factors.factor_registry import PRODUCTION_FACTORS, RESEARCH_FACTORS
    return sorted(PRODUCTION_FACTORS), sorted(RESEARCH_FACTORS)


def _get_universe():
    import yaml
    u = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    return {
        "seed_pool": u.get("seed_pool", []),
        "sector_etfs": u.get("sector_etfs", []),
        "factor_etfs": u.get("factor_etfs", []),
        "cross_asset": u.get("cross_asset", []),
        "blacklist": u.get("blacklist", []),
    }


def _get_recent_candidates(n: int = 10):
    """Scan research/llm_candidates/round_*/*.yaml, pull factor_name + status."""
    import yaml
    candidates_dir = ROOT / "research" / "llm_candidates"
    if not candidates_dir.exists():
        return []
    rows = []
    for round_dir in sorted(candidates_dir.glob("round_*"), reverse=True):
        for yaml_path in round_dir.glob("*.yaml*"):  # include .promoted
            try:
                content = yaml.safe_load(yaml_path.read_text())
                if not isinstance(content, dict):
                    continue
                name = content.get("factor_name", yaml_path.stem)
                # Check verdict in data/ml/llm_candidates/
                verdict_path = ROOT / "data" / "ml" / "llm_candidates" / name / "verdict.json"
                verdict = "unknown"
                reason = ""
                if verdict_path.exists():
                    try:
                        v = json.loads(verdict_path.read_text())
                        verdict = v.get("verdict", "unknown")
                        reason = v.get("reason", "")
                    except Exception:
                        pass
                is_promoted = yaml_path.suffix == ".promoted"
                rows.append({
                    "round": round_dir.name,
                    "name": name,
                    "verdict": "PROMOTED" if is_promoted else verdict,
                    "reason": reason[:200] if reason else "",
                })
            except Exception:
                continue
            if len(rows) >= n:
                return rows
    return rows


def _get_regime_distribution(lookback_days: int = 252):
    try:
        import pandas as pd
        from core.config.loader import load_config
        from core.data.market_data_store import MarketDataStore
        from core.regime.regime_detector import RegimeDetector
        from core.data.vix_loader import load_vix_series
    except Exception as exc:
        return {"error": f"import failed: {exc}"}
    try:
        cfg = load_config(ROOT / "config")
        store = MarketDataStore(data_dir=ROOT / cfg.system.paths.data_dir)
        spy_df = store.read("SPY", "1d")
        if spy_df is None or spy_df.empty:
            return {"error": "SPY data unavailable"}
        spy = spy_df["close"].tail(lookback_days)
        vix = load_vix_series(store, spy.index, mode="lenient")
        regime = RegimeDetector(cfg.regime).classify_series(spy, vix)
        counts = regime.value_counts().sort_index()
        return {str(k): int(v) for k, v in counts.items()}
    except Exception as exc:
        return {"error": str(exc)}


def _render_markdown(
    production: list, research: list, candidates: list,
    universe: dict, regime: dict, lookback_days: int,
) -> str:
    lines = []
    lines.append("# External LLM Factor Proposal Context Pack")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**Lookback**: last {lookback_days} trading days for regime stats")
    lines.append("")
    lines.append("> Copy EVERYTHING below (from `--- PASTE TO LLM BELOW ---` to end)")
    lines.append("> into a chat window with Gemini / Codex / 任意 LLM, then ask:")
    lines.append(">")
    lines.append("> _\"请生成 N 个 factor candidate YAMLs per the schema above, each")
    lines.append("> with compute_fn python implementation.\"_")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("--- PASTE TO LLM BELOW ---")
    lines.append("")
    # System prompt (reuse template body)
    lines.append("## ROLE")
    lines.append("")
    lines.append("You are a quantitative factor research candidate generator for the")
    lines.append("PQS (Personal Quantitative System) framework. You are NOT the final")
    lines.append("judge of factor validity. Your output will be fed into a rigorous")
    lines.append("validation funnel (IC screening / OOS walk-forward / regime")
    lines.append("robustness / cost stress / QQQ gate) — all gates must pass before")
    lines.append("any human decides whether to promote to RESEARCH_FACTORS or")
    lines.append("PRODUCTION_FACTORS.")
    lines.append("")
    lines.append("## HARD RULES")
    lines.append("")
    lines.append("1. NEVER output verdict=KEEP. Your YAML does not have a verdict field.")
    lines.append("2. Every candidate must fill ALL fields in the YAML schema below.")
    lines.append("3. No look-ahead: factor must not use data unavailable at signal_timestamp.")
    lines.append("4. Long-only only. No factors implying 'short X when Y'.")
    lines.append("5. No external data beyond: close, open, high, low, volume, regime label,")
    lines.append("   benchmark series (SPY, QQQ).")
    lines.append("")
    lines.append("## REPO STATE")
    lines.append("")
    lines.append(f"### PRODUCTION_FACTORS ({len(production)}; currently executed)")
    lines.append("")
    for f in production:
        lines.append(f"- {f}")
    lines.append("")
    lines.append(f"### RESEARCH_FACTORS ({len(research)}; available, not promoted)")
    lines.append("")
    for f in research:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("### Recent candidates (do NOT re-propose these)")
    lines.append("")
    if candidates:
        for c in candidates:
            lines.append(f"- `{c['name']}` ({c['round']}) — {c['verdict']}"
                         + (f" ({c['reason']})" if c['reason'] else ""))
    else:
        lines.append("- (none yet)")
    lines.append("")
    lines.append("### Universe (53 tradable symbols; cross-sectional validity depends on panel width)")
    lines.append("")
    for key, syms in universe.items():
        if syms:
            lines.append(f"- **{key}** ({len(syms)}): {', '.join(syms)}")
    lines.append("")
    lines.append(f"### Recent regime distribution (last {lookback_days} days)")
    lines.append("")
    if "error" in regime:
        lines.append(f"- (unavailable: {regime['error']})")
    else:
        total = sum(regime.values())
        for r, c in sorted(regime.items(), key=lambda x: -x[1]):
            pct = c / total * 100 if total else 0
            lines.append(f"- **{r}**: {c} days ({pct:.1f}%)")
    lines.append("")
    lines.append("## EXPLORATION DIRECTIONS (pick ONE per candidate)")
    lines.append("")
    for direction in [
        "benchmark-relative (vs SPY, QQQ, sector ETF, equal-weight)",
        "regime-conditioned (factor × regime indicator; multiply, not replace)",
        "path-shape (drawup, distance-from-extrema, consolidation time)",
        "multi-horizon composite (5d + 21d + 63d signals)",
        "factor interaction (product / difference / ratio of two base factors)",
        "event-based (day-of-week, turn-of-month proxies)",
        "cross-sectional (rank change, dispersion-adjusted, universe-aware)",
        "intraday-specific (overnight gap, first-bar vs last-bar, intraday vol ratio)",
    ]:
        lines.append(f"- {direction}")
    lines.append("")
    lines.append("## YAML OUTPUT SCHEMA")
    lines.append("")
    lines.append("```yaml")
    lines.append('factor_name: "descriptive_lowercase_snake_case"')
    lines.append('hypothesis: "One-line economic or behavioral rationale."')
    lines.append("formula: |")
    lines.append("  pseudocode or pandas expression; specify:")
    lines.append("    - lag / shift(1) placement")
    lines.append("    - rolling window sizes")
    lines.append("    - normalization (z-score / percent rank / etc.)")
    lines.append('compute_fn_path: "research.llm_candidates.round_NN.compute_fns:factor_name"')
    lines.append('required_fields: ["close", "volume"]')
    lines.append("suitable_horizon: [5, 21]")
    lines.append('suitable_universe: "expanded_53" | "tech_heavy" | "diversifier_only"')
    lines.append('suitable_regime: [BULL, NEUTRAL]  # or "all"')
    lines.append('expected_edge: "Expected IC sign + rough magnitude"')
    lines.append('expected_risk: "What goes wrong if crowded / what it correlates with"')
    lines.append("possible_failure_modes:")
    lines.append('  - "Specific failure mode 1"')
    lines.append('  - "Specific failure mode 2"')
    lines.append('novelty_vs_existing_factors: "Compare vs PRODUCTION_FACTORS; disclose corr estimate"')
    lines.append("```")
    lines.append("")
    lines.append("Also provide the python compute_fn, to go in")
    lines.append("`research/llm_candidates/round_NN/compute_fns.py`:")
    lines.append("")
    lines.append("```python")
    lines.append("def factor_name(price_df, vol_df=None, regime=None, **kwargs):")
    lines.append("    # returns a DataFrame (date × symbol) with factor values")
    lines.append("    ...")
    lines.append("```")
    lines.append("")
    lines.append("Deliver N candidates. Number them clearly. Do NOT include verdict,")
    lines.append("score, or pass/fail guess — the PQS funnel handles validation.")
    lines.append("")
    lines.append("--- PASTE TO LLM ABOVE ---")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## User instructions (after you get LLM response)")
    lines.append("")
    lines.append("1. Pick next round number:")
    lines.append("   ```bash")
    lines.append("   LAST=$(ls -d research/llm_candidates/round_* 2>/dev/null | tail -1 | sed 's/.*round_//')")
    lines.append("   NEXT=$(printf \"%02d\" $((10#$LAST + 1)))")
    lines.append("   mkdir -p research/llm_candidates/round_$NEXT")
    lines.append("   ```")
    lines.append("2. Save each YAML candidate as `research/llm_candidates/round_<NEXT>/<factor_name>.yaml`")
    lines.append("3. Combine all compute_fn implementations in `research/llm_candidates/round_<NEXT>/compute_fns.py`")
    lines.append("4. Add header comment to each YAML noting LLM source:")
    lines.append("   ```yaml")
    lines.append("   # Source: Gemini 2.5 (external LLM handoff per PRD M15)")
    lines.append("   # Round: <NEXT>")
    lines.append(f"   # Submitted: {datetime.now(timezone.utc).date().isoformat()}")
    lines.append("   ```")
    lines.append("5. `git add research/llm_candidates/round_<NEXT>/` + commit")
    lines.append("6. Next Claude session will auto-discover + funnel them")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump context pack for external LLMs (PRD M15)")
    parser.add_argument("--out", default=None,
                        help="Output markdown path (default: docs/llm_handoff_seed_<ts>.md)")
    parser.add_argument("--lookback-days", type=int, default=252,
                        help="Regime distribution lookback window")
    parser.add_argument("--n-recent-candidates", type=int, default=10)
    args = parser.parse_args()

    production, research = _get_factor_lists()
    universe = _get_universe()
    candidates = _get_recent_candidates(args.n_recent_candidates)
    regime = _get_regime_distribution(args.lookback_days)

    md = _render_markdown(
        production, research, candidates, universe, regime, args.lookback_days,
    )

    if args.out is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.out = f"docs/llm_handoff_seed_{ts}.md"
    out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)

    print(f"Context pack written: {out_path}")
    print(f"  PRODUCTION_FACTORS: {len(production)}")
    print(f"  RESEARCH_FACTORS: {len(research)}")
    print(f"  Recent candidates: {len(candidates)}")
    print(f"  Universe symbols: {sum(len(v) for v in universe.values() if isinstance(v, list))}")
    if "error" not in regime:
        print(f"  Regime distribution: {regime}")
    print()
    print("Next step: open the file, copy the section between")
    print("  '--- PASTE TO LLM BELOW ---' and '--- PASTE TO LLM ABOVE ---',")
    print("  paste into Gemini / Codex chat, ask for N candidates.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
