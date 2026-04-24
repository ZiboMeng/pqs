# Phase State Snapshot

**Generated**: 2026-04-24T17:59:53+00:00
**Git HEAD**: `a28f78d`
**Registry DB**: `data/research_candidates/registry.db` (total rows: **2**)

This is a read-only, git-committable snapshot of the research
candidate registry and paper-run artifacts. The underlying
SQLite DB and paper-run CSV/JSON files are gitignored; this
markdown is the repo-level audit surface.

Regenerate with:

```bash
python dev/scripts/export/dump_phase_state_snapshot.py \
    --out docs/$(date -u +%Y%m%d)-phase_state_snapshot.md
```

---

## Registry records

### `candidate_2_orthogonal_01`

| Field | Value |
|-------|-------|
| status | **S2_paper_candidate** |
| source_trial_id | `cand2_equal_03` |
| source_lineage_tag | `phase-e-post-2026-04-24-cand2` |
| frozen_spec_path | `data/research_candidates/candidate_2_orthogonal_01.yaml` |
| decision_memo_path | `docs/20260424-candidate_2_decision_memo.md` |
| created_at | 2026-04-24T15:26:49.455324+00:00 |
| promoted_at | 2026-04-24T15:28:35.242683+00:00 |
| updated_at | 2026-04-24T15:28:51.363871+00:00 |

**Paper runs** (1):

- `data/paper_runs/candidate_2_orthogonal_01/20260424T152840Z/`
    - `benchmark_relative_paper.csv`
    - `fills.csv`
    - `live_like_pnl.csv`
    - `pnl_daily.csv`
    - `run_meta.json`
    - `signals_daily.csv`
    - `target_portfolio_daily.csv`
    - `turnover_log.csv`

### `rcm_v1_defensive_composite_01`

| Field | Value |
|-------|-------|
| status | **S2_paper_candidate** |
| source_trial_id | `f24aefecc91a` |
| source_lineage_tag | `post-2026-04-24-rcm-v1-lag1` |
| frozen_spec_path | `data/research_candidates/rcm_v1_defensive_composite_01.yaml` |
| decision_memo_path | `docs/20260424-rcm_v1_s1_candidate_memo.md` |
| created_at | 2026-04-23T23:39:14.783419+00:00 |
| promoted_at | 2026-04-23T23:39:14.783406+00:00 |
| updated_at | 2026-04-24T00:30:37.898964+00:00 |

**Paper runs** (1):

- `data/paper_runs/rcm_v1_defensive_composite_01/20260424T002411Z/`
    - `benchmark_relative_paper.csv`
    - `drift_nav_20260424T002419Z.csv`
    - `drift_nav_20260424T002510Z.csv`
    - `drift_nav_20260424T003710Z.csv`
    - `drift_nav_20260424T004808Z.csv`
    - `drift_nav_20260424T011525Z.csv`
    - `drift_nav_20260424T015313Z.csv`
    - `drift_nav_20260424T020109Z.csv`
    - `drift_nav_20260424T050003Z.csv`
    - `drift_nav_20260424T050713Z.csv`
    - `drift_nav_20260424T052740Z.csv`
    - `drift_nav_20260424T053515Z.csv`
    - `drift_nav_20260424T144033Z.csv`
    - `drift_nav_20260424T144715Z.csv`
    - `drift_nav_20260424T145409Z.csv`
    - `drift_nav_20260424T150246Z.csv`
    - `drift_nav_20260424T151057Z.csv`
    - `drift_nav_20260424T153052Z.csv`
    - `drift_nav_20260424T153948Z.csv`
    - `drift_nav_20260424T155214Z.csv`
    - `drift_nav_20260424T160844Z.csv`
    - `drift_nav_20260424T161212Z.csv`
    - `drift_nav_20260424T161836Z.csv`
    - `drift_nav_20260424T162205Z.csv`
    - `drift_nav_20260424T162843Z.csv`
    - `drift_nav_20260424T163735Z.csv`
    - `drift_nav_20260424T164232Z.csv`
    - `drift_nav_20260424T164633Z.csv`
    - `drift_nav_20260424T165847Z.csv`
    - `drift_nav_20260424T175244Z.csv`
    - `drift_nav_20260424T175651Z.csv`
    - `drift_positions_20260424T002419Z.csv`
    - `drift_positions_20260424T002510Z.csv`
    - `drift_positions_20260424T003710Z.csv`
    - `drift_positions_20260424T004808Z.csv`
    - `drift_positions_20260424T011525Z.csv`
    - `drift_positions_20260424T015313Z.csv`
    - `drift_positions_20260424T020109Z.csv`
    - `drift_positions_20260424T050003Z.csv`
    - `drift_positions_20260424T050713Z.csv`
    - `drift_positions_20260424T052740Z.csv`
    - `drift_positions_20260424T053515Z.csv`
    - `drift_positions_20260424T144033Z.csv`
    - `drift_positions_20260424T144715Z.csv`
    - `drift_positions_20260424T145409Z.csv`
    - `drift_positions_20260424T150246Z.csv`
    - `drift_positions_20260424T151057Z.csv`
    - `drift_positions_20260424T153052Z.csv`
    - `drift_positions_20260424T153948Z.csv`
    - `drift_positions_20260424T155214Z.csv`
    - `drift_positions_20260424T160844Z.csv`
    - `drift_positions_20260424T161212Z.csv`
    - `drift_positions_20260424T161836Z.csv`
    - `drift_positions_20260424T162205Z.csv`
    - `drift_positions_20260424T162843Z.csv`
    - `drift_positions_20260424T163735Z.csv`
    - `drift_positions_20260424T164232Z.csv`
    - `drift_positions_20260424T164633Z.csv`
    - `drift_positions_20260424T165847Z.csv`
    - `drift_positions_20260424T175244Z.csv`
    - `drift_positions_20260424T175651Z.csv`
    - `drift_report_20260424T002419Z.md`
    - `drift_report_20260424T002510Z.md`
    - `drift_report_20260424T003710Z.md`
    - `drift_report_20260424T004808Z.md`
    - `drift_report_20260424T011525Z.md`
    - `drift_report_20260424T015313Z.md`
    - `drift_report_20260424T020109Z.md`
    - `drift_report_20260424T050003Z.md`
    - `drift_report_20260424T050713Z.md`
    - `drift_report_20260424T052740Z.md`
    - `drift_report_20260424T053515Z.md`
    - `drift_report_20260424T144033Z.md`
    - `drift_report_20260424T144715Z.md`
    - `drift_report_20260424T145409Z.md`
    - `drift_report_20260424T150246Z.md`
    - `drift_report_20260424T151057Z.md`
    - `drift_report_20260424T153052Z.md`
    - `drift_report_20260424T153948Z.md`
    - `drift_report_20260424T155214Z.md`
    - `drift_report_20260424T160844Z.md`
    - `drift_report_20260424T161212Z.md`
    - `drift_report_20260424T161836Z.md`
    - `drift_report_20260424T162205Z.md`
    - `drift_report_20260424T162843Z.md`
    - `drift_report_20260424T163735Z.md`
    - `drift_report_20260424T164232Z.md`
    - `drift_report_20260424T164633Z.md`
    - `drift_report_20260424T165847Z.md`
    - `drift_report_20260424T175244Z.md`
    - `drift_report_20260424T175651Z.md`
    - `fills.csv`
    - `live_like_pnl.csv`
    - `pnl_daily.csv`
    - `run_meta.json`
    - `signals_daily.csv`
    - `target_portfolio_daily.csv`
    - `turnover_log.csv`

---

## Notes on scope

- This snapshot lists **registry rows only** — it does not
  reproduce the contents of frozen spec YAMLs or decision
  memos. Those files are already committed under their listed
  paths and serve as their own audit surface.
- Paper-run file listings are file names only (not content).
  Content sampling should use `scripts/paper_drift_report.py`.
- A snapshot becomes stale as soon as the registry changes.
  Re-run the script whenever governance state changes.

