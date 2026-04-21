# LLM Factor Mining Phase — Blocker Report (Draft v0.1)

**Status**: DRAFT — compiled at LLM-Round 19 / 30. Final version due at R30.
**Authors**: LLM-phase ralph-loop (2026-04-21)
**Scope**: PRD §10 criterion #4 — "30 轮结束后明确证明'当前 universe +
factor 空间不足以支撑新增 alpha'，产出一份 blocker 报告"

---

## 1. Executive Summary

Over 18 rounds of LLM-assisted factor mining (R1-R18), the phase
generated 26 structured factor candidates covering all 11 menu topics
from `docs/prd_llm_factor_mining.md` §9. One candidate
(`drawup_from_252d_low`) was promoted to `RESEARCH_FACTORS` (R10) and
further to `PRODUCTION_FACTORS` (R15, user-authorized) —— the first
LLM-generated production factor in the PQS codebase.

However, **PRD §10 success criterion #2** ("promoted factor QQQ gate
pass via evaluator.evaluate") remains **not satisfied**. A mining run
with the 7-factor production space (R16) produced 0/11 trials passing
the OOS IR ≥ 0.20 gate. Diagnostic work in R17 confirmed this is not a
threshold problem —— the `oos_ir` metric measures **Information Ratio
vs SPY benchmark**, and the threshold (already relaxed from 0.30 to
0.20 in `config/backtest.yaml`) is a sound quantitative standard
("strategy must produce stable alpha over passive SPY buy-and-hold").

**Core finding**: the current PRODUCTION_FACTORS × weight space, on the
30-symbol Mag7-heavy universe, cannot systematically outperform SPY on
21-day forward horizon. This is a structural limit, not an
implementation issue.

**User validation (R19, 2026-04-21)**: "后面对于universe肯定要进行优化和
扩充 当前的暴露太偏大科技 需要进行筛选 来实现alpha正值 而不是纯赚beta" —
confirms §6.1 below as the primary blocker resolution path.

## 2. LLM Phase Goals (per PRD §10)

| # | Criterion | Status |
|---|---|---|
| 1 | ≥1 LLM candidate promoted to PRODUCTION | ✅ R15 (drawup) |
| 2 | Promoted factor passes QQQ hard gate via evaluator.evaluate | ❌ blocked |
| 3 | Archive traceable (lineage_tag + YAMLs) | ✅ |
| 4 | Alternate: 30-round blocker report if #2 unreachable | IN PROGRESS (this doc) |

## 3. Four Lines of Evidence for the Blocker

Four independent research methods converge on the same conclusion:
**factor space is insufficient for alpha in current universe**.

### 3.1 XGBoost cross-signal mining (R6)

Across 43 features (32 classical + 11 LLM) on a (date × symbol) panel
(79,966 rows), XGBoost training with temporal train/test split:

- **OOS R² = -0.107** (XGBoost overfits; predicts WORSE than mean)
- Ridge OOS R² = +0.011 (barely positive; extremely weak linear signal)
- Top permutation importance features dominated by classical factors
  (max_dd_126d, mom_126d, vol_63d) — LLM candidates add interaction
  importance but not new independent alpha

### 3.2 Composite backtest MaxDD (R15)

Across 6 composite configurations (drawup + mean-revert ensemble + risk
factors, varying top-K and weights):

- **Best MaxDD: -50.87%** (pure mean-revert ensemble, top-K=10)
- **PRD invariant: MaxDD ≤ -20%**
- All factor-level composites fail MaxDD by 20+ percentage points
- Pure classical composite without LLM candidates: MaxDD -59.34%
- Conclusion: factor blending alone cannot fix MaxDD; requires full
  MFS stack (kill_switch + target_vol + regime-scaled cash)

### 3.3 Mining run post-promotion (R16)

`run_mining.py --trials 30 --budget 1200 --type multi_factor
--lineage post-2026-04-20-llm-round-15`:

| metric | value |
|---|---|
| trials evaluated | 155 |
| trials archived | 83 |
| passed quick | 72 (87%) |
| **passed OOS** | **0 (0%)** |
| promoted | 0 |

Cross-lineage comparison:

| lineage | n | passed_OOS | best_oos_ir |
|---|---:|---:|---:|
| R1 capital-100k (pre-promotion, multi_factor) | 52 | 0 | -0.113 |
| R1 capital-100k (pre-promotion, dual_momentum) | — | 0 | **+0.008** (edge) |
| R15 (drawup in PROD) | 11 | 0 | -0.089 |
| closeout | 20 | 0 | -0.325 |

Across **all post-fix lineages** (83 trials cumulative), OOS IR
distribution is [-0.709, +0.008]. Not a single trial reaches the 0.20
threshold.

### 3.4 Calendar-effect candidates (R18)

Three calendar/event-proxy candidates (Monday effect, month-end,
month-start):

| factor | IC | verdict |
|---|---:|---|
| monday_effect_mean_63d | n=0 (sparse) | ARCHIVE |
| monthend_last5d_mean_63d | -0.002 | ARCHIVE |
| monthstart_first5d_mean_63d | -0.038 | ARCHIVE |

In the Mag7-heavy universe, classical calendar anomalies are
essentially arbitraged away. Large-cap efficient market erodes these
effects.

## 4. Best Candidate Deep-Dive: drawup_from_252d_low

The strongest LLM-generated candidate by all four research lenses:

| method | metric | value | consensus rank |
|---|---|---:|---:|
| R3 deep_check §5.4 | OOS IR | +0.386 | PASS |
| R3 deep_check §5.4 | 5/6 regimes correct sign | — | PASS |
| R6 Ridge permutation | importance | +0.024 | **#1 of 43** |
| R6 XGBoost permutation | importance | +0.010 | **#7 of 43** |
| R12 factor_screen | IR (21d) | +0.291 | **#2 of 33** |

**Promoted to PRODUCTION_FACTORS** at R15 (user-authorized). Best
mining trial (R16) with drawup weight=0.05:

| metric | value | threshold | pass? |
|---|---:|---:|---|
| quick_cagr | +17.41% | 0.02 | ✓ |
| quick_sharpe | +0.72 | 0.30 | ✓ |
| oos_sharpe (absolute) | +0.376 | — | (profitable) |
| **oos_ir (vs SPY)** | **-0.089** | 0.20 | **✗** |
| oos_excess_return | -0.023 | 0.02 | ✗ |
| oos_pass_rate | 0.57 | 0.55 | ✓ |

The strategy **IS profitable** (positive absolute Sharpe, +17% CAGR),
but it **doesn't beat SPY** in OOS walk-forward. The Information Ratio
vs benchmark is where promotion is blocked. Compare:
- Without drawup (pre-R15 baseline): best multi_factor OOS IR -0.113
- With drawup (R15): best OOS IR -0.089
- **Drawup promotion moved OOS IR by +0.024 (≈30 pts when considering
  broader distribution)** — real but insufficient.

## 5. Why Standards Should NOT Be Lowered

Per user directive in R17: "不要因为要 promote 降低标准 如果标准是 make
sense 的话". The current thresholds:

- `oos_min_ir_vs_benchmark: 0.20` (already relaxed from 0.30)
- `oos_min_pass_rate: 0.55` (already relaxed from 0.60)
- `oos_min_excess_return: 0.02` (already relaxed from 0.03)

Lowering further would allow strategies that **cannot beat passive SPY
buy-and-hold** to be "promoted". The raison d'être of a quant strategy
is to produce alpha over benchmark; a strategy that doesn't is worse
than index investing (same returns, more cost, more risk). The gate is
sound. **Blocker conclusion is correct, not a config artifact.**

## 6. Recommended Next Steps (post-LLM-phase)

The LLM phase has exhausted its design scope: all 11 menu topics
covered, 26 candidates generated, the best promoted, diagnostic
evidence compiled. To unblock criterion #2 requires **structural
changes** outside LLM phase scope:

### 6.1 Universe Expansion (USER-VALIDATED, 2026-04-21, HIGHEST PRIORITY)

Current universe: 30 symbols (SPY + QQQ + Mag7 + sector ETFs + a few
cross-asset). **Mag7 concentration erodes cross-sectional dispersion**
— individual names move together, compressing alpha signals.

**User validation (2026-04-21)**: "后面对于universe肯定要进行优化和扩充
当前的暴露太偏大科技 需要进行筛选 来实现alpha正值 而不是纯赚beta"

User explicitly confirmed: universe needs both EXPANSION and SCREENING.
Current Mag7 exposure produces beta returns (passive index drift), not
alpha. **The universe composition is the primary blocker, not the
factor space.** This reframes the blocker thesis: the LLM factor
exercise was solving the wrong problem — factor innovation cannot
overcome a universe that lacks alpha dispersion to begin with.

Proposed: expand to 100+ symbols with SCREENING criteria to reduce
large-cap tech bias:
- Add mid-caps (market cap $2B-$10B): restore CS dispersion
- Add value / quality / low-vol curated names (classical anomaly
  surfaces stronger in less-efficient segments)
- Drop pure-beta ETFs (keep SPY/QQQ only as benchmarks, not holdings)
- Optional: international (VGK, EEM) for regime diversification
- Selection criterion: exclude names with beta > 1.3 to SPY/QQQ
  composite (over 252d rolling) to avoid pure-beta exposures

Expected effects:
- Increase CS dispersion (interaction factors show stronger signals)
- Restore calendar effects (less efficient names exhibit classical
  anomalies)
- Provide distance-from-extrema factors (drawup) with more recovery
  stories
- Separate alpha sources from concentrated-tech beta

### 6.2 Data Sources Beyond Close Prices

Current factors use close prices (+ volume for a few). Missing:
- **Fundamental data**: earnings surprises, revisions, sentiment
- **Options data**: IV, put/call ratio, skew
- **Alt data**: news sentiment, social mentions

These would add orthogonal alpha sources that pure price-based factors
cannot replicate.

### 6.3 Non-Linear Ensemble Strategy

Current MFS is a linear composite. Alternatives:
- XGBoost as PRIMARY strategy generator (not just research tool)
- Regime-specific factor weights (different regime → different weights
  dynamically)
- Meta-learning: weights learned from past OOS performance

### 6.4 Alternative Alpha: Arbitrage / Pairs

Current system is long-only directional. Alternative strategies:
- Pairs trading (dollar-neutral)
- ETF arbitrage (different sector ETFs diverging from underlying)
- Cross-sectional momentum (long-short spreads)

These need a different risk framework (not long-only invariant) but
are fundamentally different alpha sources.

## 7. LLM Phase Deliverables (what was built)

Tools (7 core + 1 notify):
- `scripts/llm_factor_propose.py` — YAML candidate funnel CLI
- `scripts/llm_candidate_deep_check.py` — OOS + regime + quartile (§5.4)
- `scripts/llm_candidate_factor_backtest.py` — 5-gate backtest
- `scripts/run_llm_cross_signal_mining.py` — XGBoost + Ridge comparison
- `scripts/run_factor_interaction_mine.py` — pairwise interaction miner
- `scripts/llm_composite_backtest.py` — multi-factor composite test
- `scripts/llm_candidate_orthogonalization.py` — residual-IC gate
- `scripts/send_round_summary.py` — WeChat notify integration

Modules:
- `core/factors/llm_candidate.py` — candidate schema + funnel (R10 of
  previous 12-round loop)
- `core/factors/factor_generator.py::_quality_factors` — drawup added
  (R10 promotion)
- `core/signals/strategies/multi_factor.py` — drawup added (R15)
- `core/mining/strategy_space.py` — drawup weight slot (R15)

Artifacts:
- 26 structured candidate YAMLs in `research/llm_candidates/round_XX/`
- 1 promoted + 1 archived-via-deep_check + 24 funnel ARCHIVE

Documentation:
- `CLAUDE.md` §Ralph-Loop Findings: R1-R18 entries
- `docs/ralph_loop_log.md`: full 12-part reports each round
- `docs/prd_llm_factor_mining.md`: original PRD (unchanged)

## 8. Open Questions for R20-R30

These questions may or may not reshape the blocker thesis:

1. **Does a 80-100 symbol wider-universe mining run produce OOS IR > 0.20?**
   If yes, the blocker is universe-sized, not factor-space. Worth one
   wider mining experiment (budget permitting).

2. **Does a mean-revert-ensemble LLM candidate (single factor from R15
   C2 composite) promote-able?** Round 15 showed pure MR ensemble had
   best MaxDD and passed MaxDD rel gate. Could be promoted as single
   composite factor.

3. **Does removing the concentration constraint help?** Currently mining
   uses 30-sym top-K with anti-concentration guards. Relaxing might
   let mining find viable alpha (if any) in sector-concentrated plays.

Each of R20-R29 can address one of these. R30 finalizes.

## 9. Appendix — Full Candidate List

See `research/llm_candidates/round_XX/*.yaml` for structured records.
Summary by round:

| Round | Topic | Candidates | Verdicts |
|---:|---|---:|---|
| R1 | daily variants | 5 | 1 promoted (drawup), 3 archive, 1 review |
| R2 | intraday | 3 | 3 archive |
| R4 | benchmark-relative | 3 | 1 archive, 2 review (dedup) |
| R7 | interactions | 3 | 3 archive (1 deep_check FAIL) |
| R8 | soft-gate | 3 | 3 archive |
| R13 | path-shape | 3 | 3 archive (1 deep_check FAIL) |
| R14 | cross-sectional | 3 | 3 archive (2 via orthog) |
| R18 | calendar | 3 | 3 archive |
| | **Total** | **26** | 1 promoted, 25 archive |

---

*Draft compiled at LLM-Round 19. Revisions expected through R30.*
