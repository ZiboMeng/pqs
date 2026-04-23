# Transformer Research Phase 1 — Findings

**Date**: 2026-04-21
**PRD**: `docs/20260421-prd_framework_completion.md` §M8 → §11 M16
**Run**: `scripts/run_transformer_research.py --horizon 21 --seq-len 63 --epochs 5`
**Artifact**: `data/ml/transformer/phase1_daily_h21/summary.json`

## TL;DR

**Transformer is worse than Ridge on this setup.** Small-data / daily /
short-horizon forecasting does not suit transformer capacity. Use Ridge
for linear baselines, XGBoost for feature importance. Transformer Phase 1
findings justify **not** pursuing Phase 2 on daily features.

## Setup

- **Hardware**: GTX 1650 (4GB VRAM), CUDA 13, PyTorch 2.11
- **Model**: `core/ml/transformer_encoder.py::SmallEncoder`
  - 1-layer transformer encoder, `d_model=64, nhead=4, dim_ff=128`
  - Learnable linear projection + sinusoidal positional encoding
  - Global average pool → linear head (scalar forward return)
  - **35,713 trainable parameters** (comfortably fits 4GB VRAM)
- **Data**:
  - 53-symbol universe × 19 years daily closes
  - 33 factors from `generate_all_factors`
  - Target: 21-day forward return
  - Panel: 133,751 (date × symbol) rows × 33 features
  - Sequences: last 63 daily factor snapshots per (symbol, date)
  - Temporal split: 80% train / 20% test (104k train, 26k test)
- **Training**: 5 epochs, batch 64, Adam lr=1e-3, MSE loss

## Results (OOS R²)

| Model | OOS R² | Δ vs Ridge |
|---|---:|---:|
| **Ridge** (α=1000) | **+0.012** | baseline |
| XGBoost (n=200, max_depth=4) | -0.110 | -0.122 |
| Transformer (1-layer, 35k params) | -0.207 | -0.219 |

- Only Ridge has positive OOS R² (weakly predictive)
- XGBoost overfits (test R² < 0 means worse than predicting the mean)
- Transformer is the most overfit of the three

Training loss decreased monotonically (0.0094 → 0.0061 over 5 epochs), so the
model **was** learning in-sample patterns — but those patterns did not
generalize. This is consistent with the expected failure mode on small data.

## Interpretation

**Why Ridge wins**:
- Linear regularization is aggressive (α=1000) and matches the weak,
  approximately-linear signal structure in factor → forward-return panels.
- No capacity for overfitting on 33 features.

**Why transformer is worst**:
- 35k parameters is small for a transformer but **large relative to the
  effective signal** (~linear + small nonlinear residual).
- Daily forecasting for 21-day horizon is fundamentally hard: signal/noise
  ratio in daily panels is very low (IC magnitudes 0.02-0.10 in the best
  factors per CLAUDE.md research notes).
- Sequence structure at the daily level has limited extra information:
  factors already encode rolling statistics; transformer is just relearning
  them with noise.

**Where transformer might help** (not tested in Phase 1):
- **Intraday sequences**: minute-bar sequences might carry microstructure
  information that factors don't summarize. But this requires 1m data
  infrastructure + much more RAM.
- **Multi-asset attention**: cross-sectional relationships that neither
  Ridge nor XGBoost can easily capture. Needs rewrite of input tensor
  shape (currently per-symbol independent).
- **Longer horizons**: 63d or 252d forecasting, where path shape matters more.

## Decision

**Do not proceed to transformer Phase 2 on daily features.** The Phase 1
benchmark shows no incremental value over Ridge/XGBoost at this scope.

**If transformer research continues, pivot to one of**:
1. Intraday 5m/15m sequences — needs different data pipeline + larger VRAM
   (not feasible on 1650 without significant model shrinkage)
2. Multi-asset cross-sectional transformer — rewrite `SmallEncoder` to take
   `(n_symbols, seq_len, n_features)` tensors and apply attention across
   symbols, not just time. Research-only, multi-month effort.
3. Longer horizons (252d) — expand target generation + accept smaller
   sample size for holdout

None of these are prioritized. Recommend closing M8 Phase 1 as
"scaffold shipped + honest negative finding on daily scope" and
parking transformer work until evidence suggests a specific direction.

## Artifacts

- Summary JSON: `data/ml/transformer/phase1_daily_h21/summary.json`
- Reproduce: `python scripts/run_transformer_research.py --horizon 21 --seq-len 63 --epochs 5`
- Compare to XGBoost weight research (M7): `python scripts/run_xgb_weight_model.py`

## Engineering notes

Issues observed during Phase 1 run:
- Panel-building loop over `(date, symbol) × factor` is slow (~5 min for
  53-sym × 19yr). Could vectorize via `.stack().unstack()` for speed but
  doesn't change conclusion.
- Sequence construction uses per-symbol iteration; clean but memory-heavy.
- GPU utilization was low (batches finish in ms; bottleneck is CPU data prep).

If revisiting, vectorize panel build first.
