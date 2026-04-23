# LLM Candidate Funnel Checklist (PRD M6 Phase 1)

After an LLM returns a candidate YAML, run this **mandatory** 6-step
sequence. Skipping steps is not permitted — the funnel is what
guarantees LLM output is subjected to the same rigor as human-written
candidates.

---

## Step 0: Save YAML to repo

```bash
# Determine round number (next after latest existing)
LAST=$(ls -d research/llm_candidates/round_* 2>/dev/null | tail -1 | sed 's/.*round_//')
NEXT=$(printf "%02d" $((10#$LAST + 1)))
mkdir -p research/llm_candidates/round_$NEXT
# Paste YAML to research/llm_candidates/round_$NEXT/<factor_name>.yaml
# Add compute_fn to research/llm_candidates/round_$NEXT/compute_fns.py
```

**Verification**: file is git-tracked (research/ is NOT gitignored).

## Step 1: Shape + leakage + dedup (mandatory first)

```bash
python scripts/llm_factor_propose.py \
    --input research/llm_candidates/round_$NEXT/<factor_name>.yaml
```

**Possible verdicts**:
- `REJECT` — shape failure / obvious leakage → fix YAML + resubmit, or
  if fundamental → give up on this candidate
- `ARCHIVE` — passed shape/leakage but IC too weak → keep file but don't
  pursue further
- `NEEDS_HUMAN_REVIEW` — passed all gates OR dedup-flagged → continue

**KEEP is not a valid outcome** of this step (per PRD §2.2).

## Step 2: Deep check (only if Step 1 = NEEDS_HUMAN_REVIEW)

```bash
python scripts/llm_candidate_deep_check.py \
    --candidate research/llm_candidates/round_$NEXT/<factor_name>.yaml \
    --universe-size 30
```

**Checks**: OOS walk-forward IR (30-sym panel), regime 6-class sign
consistency, time quartile stability.

**Pass criteria**: OOS IR ≥ 0.30, regime correct sign ≥ 4/6, no quartile
sign-flip.

**Artifacts**: `data/ml/llm_deep_checks/<factor_name>/deep_check.json`

## Step 3: Orthogonalization (if dedup-flagged in Step 1)

```bash
python scripts/llm_candidate_orthogonalization.py \
    --candidate research/llm_candidates/round_$NEXT/<factor_name>.yaml
```

**Purpose**: residualize against existing factors to check incremental IC.

**Verdicts**: LOW / MEDIUM / HIGH retention of original IC after
orthogonalization. LOW means "explained by existing factors", archive.
MEDIUM means "partial novelty", continue. HIGH is rare — strong
independence signal.

## Step 4: Factor backtest (only if Step 2 PASS)

```bash
python scripts/llm_candidate_factor_backtest.py \
    --candidate research/llm_candidates/round_$NEXT/<factor_name>.yaml
```

**5-gate verdict**:
1. cost stress (1x vs 2x)
2. QQQ full-period excess
3. QQQ holdout excess
4. MaxDD absolute ≤ -25%
5. MaxDD relative ≤ 1.5× SPY

ALL 5 must pass for promote consideration. MaxDD is strictest (CLAUDE.md
invariant).

## Step 5: Composite integration test (only if Step 4 all pass)

```bash
python scripts/llm_composite_backtest.py \
    --components "new_factor:0.15,drawup:0.15,rel_strength:0.30,quality:0.30,low_vol:0.15"
```

Test the candidate as a **component** in a composite, not a standalone
strategy. Many LLM factors that fail single-factor MaxDD pass as
15%-weighted composite components (CLAUDE.md Round 5-8 finding).

## Step 6: Human review + decide

Look at the aggregated artifacts:
- `data/ml/llm_candidates/<factor_name>/verdict.json`
- `data/ml/llm_deep_checks/<factor_name>/deep_check.json`
- `data/ml/llm_factor_backtests/<factor_name>/factor_backtest.json`
- `data/ml/llm_composite_backtests/<config>/composite_backtest.json`

Decide:

- **ARCHIVE** (most common) — keep YAML in repo, don't promote. Add a
  one-line note to `docs/20260420-ralph_loop_log.md` explaining the rejection
  reason.

- **PROMOTE_TO_RESEARCH** — add to `core/factors/factor_registry.py::RESEARCH_FACTORS`.
  This makes the factor available to `scripts/run_factor_screen.py` and
  `scripts/run_xgb_importance.py` but NOT to `MultiFactorStrategy`.

- **PROMOTE_TO_PRODUCTION** (rare, requires user auth per PRD §13.2 halt):
  1. Add inline computation to `MultiFactorStrategy.generate()`
  2. Add name to `PRODUCTION_FACTORS`
  3. Add weight slot to `MultiFactorSpace.suggest()` and `_TUNED_FACTORS`
  4. Run `scripts/run_mining.py` to find best weight combination
  5. Take best spec_id → `scripts/promote_strategy.py --spec-id <id> --promote`
  6. Review + git commit the promoted `config/production_strategy.yaml`

The R15 `drawup_from_252d_low` promotion followed this exact path.

---

## Anti-patterns (do not do)

- Do NOT skip Step 2 even if Step 1 says NEEDS_HUMAN_REVIEW "looks good"
- Do NOT promote to PRODUCTION on a single-factor backtest pass without
  composite integration testing
- Do NOT trust LLM self-evaluation of the candidate (LLM is candidate
  generator, not judge — PRD §2.2 constraint)
- Do NOT accept "looks intuitive / economically plausible" as evidence
  of validity. Only numerical OOS evidence counts.
- Do NOT squash multiple candidates into one YAML to "save time". Each
  factor gets its own YAML and its own funnel.

## Anti-pattern detection checklist (reverse review)

Before promoting, answer these out loud:

- [ ] Is this a sign-flipped version of an existing factor? (check ρ)
- [ ] Does the IC concentrate in a single time period (>60% of total IC
      from one quartile)?
- [ ] Does the factor require > 5 symbols to avoid zero-variance rows?
      If no, reject (universe too thin).
- [ ] Is the factor tested on at least 5 years of data?
- [ ] Does the factor survive 2× cost stress? (mandatory, not optional)
- [ ] Is the factor correlated > 0.7 with ANY existing promoted factor?
      If yes, can you articulate incremental edge (non-linear / regime
      / timescale)? If no incremental edge story, archive.

If any answer is "no" or "don't know" → not ready for promote.
