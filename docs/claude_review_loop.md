# Claude Review Loop

## Project Goal
- Build a personal US equities quant research and paper-trading system that can sustainably outperform SPY and QQQ.
- Keep max drawdown around 15%-20% and preserve crisis resilience.
- Prioritize research credibility, execution consistency, and disciplined promotion over fast candidate churn.

## Round 1
### Claude Did
- Opened research cycle `2026-04-26-01` under the partial-unfreeze rules.
- Pre-registered immutable promotion criteria in `data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml`.
- Added `--end-date` and `--drop-symbols` to `scripts/run_research_miner.py` so the mining panel could honor the cycle's G4 cutoff without editing frozen config.
- Ran a 200-trial TPE mining cycle on the 78-symbol panel capped at `2023-12-31`.
- Produced a closeout package with memo, candidate artifacts, concentration report, pseudo-OOS summary, regime breakdown, correlation report, and `dev/scripts/research_cycle/run_close_eval.py`.
- Closed the cycle as `0 nominee` because the top trial failed the hard gate `watchlist_total_share <= 0.30`.

### Evidence / Changed Files
- `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`
- `data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml`
- `data/research_candidates/research-cycle-2026-04-26-01_closeout_eval.json`
- `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml`
- `scripts/run_research_miner.py`
- `dev/scripts/research_cycle/run_close_eval.py`

### Review Conclusion
- Keep:
  - The pre-registration discipline and the refusal to soften criteria after the fact.
  - The research conclusion that this cycle should end with `0 nominee`.
  - The substantive findings: watch-share gate binding, realized beta anomaly, and pseudo-OOS drawdown concern.
- Change:
  - The artifact/state semantics for the top trial are not aligned with the closeout conclusion.
- Rework:
  - The final candidate artifact package should not leave any ambiguity about whether this cycle produced an S1 candidate.

### Main Issues
1. The written conclusion says `0 nominee` and `no S1 advancement`, but `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml` still exists and says `CURRENT STAGE: S1 RESEARCH_CANDIDATE`.
2. The same YAML still contains `pending_closeout_eval` fields even though closeout already happened.
3. New workflow/tooling was added, but there is no targeted regression coverage for the new behaviors in this cycle's delivery.

### Next Instruction To Claude
Please do not open a new research cycle yet. First fix the closeout consistency of cycle `2026-04-26-01`.

Goals:
- Make the final artifacts fully consistent with the conclusion `0 nominee, no S1 advancement`.
- Remove any ambiguity that could cause a human or a script to misread this top trial as a real S1 candidate.

Required actions:
1. Audit `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml` against the closeout memo and identify every state/wording mismatch.
2. Implement one clear correction path:
   - either downgrade/rename the artifact so it is unmistakably not an S1 candidate,
   - or keep the artifact but rewrite its naming and status fields so it clearly represents a failed hard-gate top trial, not an advanced candidate.
3. Remove all `pending_closeout_eval` placeholders and write the final closeout result into the canonical artifact(s).
4. Add the minimum necessary tests for:
   - `scripts/run_research_miner.py --end-date`
   - `scripts/run_research_miner.py --drop-symbols`
   - `dev/scripts/research_cycle/run_close_eval.py` behavior when a candidate fails a hard gate
5. In your next summary, structure the response as:
   - Inconsistencies found
   - Chosen fix and why
   - Files changed
   - Tests added/run
   - Final artifact semantics after the fix

Constraints:
- Do not start a new mining cycle.
- Do not change the criteria for cycle `2026-04-26-01`.
- Do not revisit paper-slot decisions.
- Only fix closeout consistency for this cycle.

## Priority Clarification

The current top priority is still the closeout-consistency fix above.
Do not reinterpret the task as a broad project audit.

Additional execution guidance for Claude:

1. First locate the concrete review comments / requested fixes already on the table for cycle `2026-04-26-01`, then execute them directly.
2. Treat any broader repository-status audit as background only, not as the main task.
3. In the next response, confirm explicitly:
   - what concrete closeout issue you are fixing first,
   - where the canonical artifact mismatch lives,
   - what you changed to make the final semantics unambiguous.

Advisory only, unless already within the closeout-fix scope:
- `core/research/forward/runner.py` appears to keep forward manifests at `in_progress` and may not promote them to `decision_pending` when the max decision day is reached.
- `README.md` may lag the actual 2026-04-26 project state.

Do not prioritize those advisory items ahead of the cycle `2026-04-26-01` closeout consistency repair unless the user explicitly redirects you.

## Round 2 Audit (Codex)

### What I Checked
- `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml`
- `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`
- `data/research_candidates/research-cycle-2026-04-26-01_closeout_eval.json`
- `dev/scripts/research_cycle/run_close_eval.py`
- `scripts/run_research_miner.py`
- `tests/unit/mining/test_research_miner.py`
- `docs/memos/20260426-research_layer_partial_unfreeze.md`

### Review Conclusion
- Claude's Round-1 audit target was correct: the cycle's closeout semantics are still not closed.
- This is not just a wording cleanup. It is an artifact-contract problem.
- Do not treat the issue as solved until the canonical artifact naming, status semantics, and closeout write-back are consistent.

### Code-Backed Findings
1. The current artifact naming still contradicts the governing memo.
   - `docs/memos/20260426-research-cycle-2026-04-26-01_close.md` says `0 nominee` and `no candidate advancing`.
   - But the canonical file is still named `research-cycle-2026-04-26-01_S1_nominee.yaml`.
   - The header inside that file still says `CURRENT STAGE: S1 RESEARCH_CANDIDATE`.
   - Per `docs/memos/20260426-research_layer_partial_unfreeze.md`, a hard-gate fail is not eligible to be the lineage's nominee. So `S1_nominee` is not just awkward naming; it is semantically wrong.

2. The canonical YAML was never finalized after closeout.
   - `benchmark_relative_summary`, `oos_holdout_summary`, `robustness_summary`, and `acceptance_decision` are still `pending_closeout_eval`.
   - `dev/scripts/research_cycle/run_close_eval.py` writes sidecar artifacts and `*_closeout_eval.json`, but it does not write the final result back into the canonical YAML.
   - As shipped, the pipeline can produce a closeout memo and decision table while leaving the main spec in a pre-closeout placeholder state.

3. The contradiction exists in more than one place, so a one-file fix is not enough.
   - The closeout memo artifact table still lists `research-cycle-2026-04-26-01_S1_nominee.yaml` as the candidate spec.
   - `closeout_eval.json` still uses `candidate_id: research-cycle-2026-04-26-01_S1_nominee`.
   - All sidecar filenames also inherit the same wrong nominee semantics.
   - If you only edit comments in the YAML, a human or downstream script can still infer "real S1 candidate" from filenames and ids.

4. The promised regression coverage is still missing.
   - `tests/unit/mining/test_research_miner.py` does not cover the new `--end-date` and `--drop-symbols` behavior.
   - There is no targeted test file for `dev/scripts/research_cycle/run_close_eval.py`.
   - So the two new workflow guarantees introduced this cycle are still unpinned.

### Recommended Fix Path
Preferred path: rename the artifact family away from `S1_nominee`.

Reason:
- The unfreeze memo explicitly allows `0 nominee` as a valid outcome.
- A hard-gate fail cannot keep `nominee` semantics without breaking the memo's own logic.
- "keep the file but add a clarifying comment" is not enough because the filename, `candidate_id`, and sidecar artifact names still advertise the wrong state.

Recommended target semantics:
- Treat trial `62445bdc62ae` as the lineage's top trial / failed-gate top trial, not an S1 candidate.
- Rename the canonical artifact family to something like:
  - `research-cycle-2026-04-26-01_top_trial_failed_gate.yaml`
  - or another equally explicit non-S1, non-nominee name
- Update all sidecars and references to match that new canonical id.
- Update the closeout memo so section 2 and the artifact table describe it as the top trial that failed G2.A, not as an S1 nominee.

### Minimum Required Implementation Work
1. Fix naming and semantics consistently across:
   - canonical YAML
   - sidecar artifact filenames
   - `closeout_eval.json`
   - closeout memo references

2. Remove all `pending_closeout_eval` placeholders from the canonical artifact.

3. Add an explicit closeout result block into the canonical artifact.
   Suggested fields are fine as dicts or strings, but they must be final values, not placeholders:
   - `benchmark_relative_summary`
   - `oos_holdout_summary`
   - `robustness_summary`
   - `acceptance_decision`

4. Close the pipeline gap in code.
   - Either extend `run_close_eval.py` to write canonical final summaries into the canonical YAML,
   - or add a separate finalize step immediately after `run_close_eval.py`.
   - But the end state must be one-command reproducible. Manual memo-writing plus stale YAML is not acceptable as the steady-state contract.

### Tests I Want Added
1. `tests/unit/mining/test_research_miner.py`
   - test that `--end-date` actually truncates the panel
   - test that `--drop-symbols` actually removes requested symbols from the tradable panel

2. New targeted test file for closeout, e.g. `tests/unit/research/test_run_close_eval.py`
   - hard-gate fail produces `g2_a_overall_pass = false`
   - closeout artifacts reflect the fail cleanly
   - canonical artifact finalization removes `pending_closeout_eval`
   - candidate naming / acceptance semantics are non-S1 when the hard gate fails

### Next Instruction To Claude
Please continue from Round 1, but tighten the fix scope as follows:

1. Do not just edit comments inside `research-cycle-2026-04-26-01_S1_nominee.yaml`.
2. First decide and state the replacement canonical semantics for a top trial that failed a hard gate.
3. Then implement that semantics consistently across filename, `candidate_id`, sidecars, closeout JSON, and closeout memo.
4. Add canonical artifact write-back so the closeout pipeline no longer leaves placeholder summaries behind.
5. Add the missing regression tests for `run_research_miner.py` and closeout finalization.

### Acceptance Bar For The Next Claude Reply
- No remaining `S1_nominee` / `S1_RESEARCH_CANDIDATE` semantics for this failed cycle artifact family
- No remaining `pending_closeout_eval`
- A clear explanation of the new artifact contract
- Tests added for both mining-panel controls and hard-gate closeout behavior
