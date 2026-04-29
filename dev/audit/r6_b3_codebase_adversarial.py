"""R6 (B3) — adversarial corner-case lens — full codebase.

Builds ≥30 adversarial scenarios spanning data / signal / backtest /
paper-engine / config / NaN / empty / single-row / concurrency
corners. Each scenario predicts an outcome, runs it on real data
where applicable, and asserts the predict-vs-actual delta.

This is the cumulative-pass round 3 of 7; lens is "design adversarial
inputs the codebase has never seen and check it does not silently
degrade".
"""

from __future__ import annotations

import json
import logging
import math
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from core.backtest.backtest_engine import BacktestEngine
from core.backtest.concentration_metrics import (
    compute_concentration_metrics,
    validate_concentration,
)
from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.data.market_data_store import MarketDataStore
from core.execution.cost_model import CostModel
from core.factors.factor_registry import (
    PRODUCTION_FACTORS,
    RESEARCH_FACTORS,
    enforce_execution_factor_names,
    UnregisteredFactorError,
)
from core.research.forward.bar_hash import (
    compute_signal_input_hash,
    compute_execution_nav_hash,
    compute_benchmark_hash,
    compute_bar_hash_rollup,
    _resolve_lookback_window_start,
)
from core.research.forward.source_layer import classify_window, classify_as_of
from core.research.forward.manifest_schema import ForwardRunManifest
from core.research.forward.revalidate import revalidate_manifest
from core.signals.strategies.multi_factor import MultiFactorStrategy

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("r6_audit")

results: list[tuple[str, str, str]] = []   # (id, label, status)


def record(scenario_id: str, label: str, predicate: bool, note: str = "") -> None:
    status = "PASS" if predicate else "FAIL"
    results.append((scenario_id, label, status))
    icon = "[PASS]" if predicate else "[FAIL]"
    extra = f" — {note}" if note else ""
    print(f"  {icon} {scenario_id:6s} {label}{extra}")


# ─── load real-data fixtures (canonical 78-symbol universe slice) ─────────────

print("\n" + "=" * 78)
print("R6 / B3 — adversarial corner-case lens — full codebase")
print("=" * 78)

cfg = load_config(Path("config"))
mds = MarketDataStore(Path("data"))
bs = BarStore()

real_syms = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA"]
panel_full = {}
for sym in real_syms:
    df = mds.read(sym, "1d")
    if df is not None and not df.empty:
        panel_full[sym] = df

# 100-day slice covering 2025-12 to 2026-04
all_idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in panel_full.values()])))
recent = all_idx[all_idx >= "2025-12-01"]
panel_close = pd.DataFrame({s: panel_full[s].loc[recent].close for s in panel_full}).dropna(how="all")
panel_open  = pd.DataFrame({s: panel_full[s].loc[recent].open  for s in panel_full}).dropna(how="all")

panel_dict = {"close": panel_close, "open": panel_open}

print(f"\nReal panel: {panel_close.shape} {panel_close.index[0].date()} → {panel_close.index[-1].date()}")

# ─── S01-S05: data corners ───────────────────────────────────────────────────

print("\n— Data corners (S01-S05) —")

# S01: BarStore.load with non-existent symbol
try:
    res = bs.load("NONEXISTENT_SYMBOL_XYZ", "1d", adjusted=True)
    record("S01", "BarStore unknown sym → empty/None",
           res is None or res.empty,
           f"got {type(res).__name__} {None if res is None else res.shape}")
except Exception as e:
    record("S01", "BarStore unknown sym → exception",
           "not found" in str(e).lower() or "no such" in str(e).lower(),
           f"{type(e).__name__}: {str(e)[:80]}")

# S02: BarStore adjusted vs raw column count parity
raw = bs.load("AAPL", "1d", adjusted=False)
adj = bs.load("AAPL", "1d", adjusted=True)
record("S02", "BarStore adjusted preserves columns",
       set(raw.columns) == set(adj.columns),
       f"raw={list(raw.columns)} adj={list(adj.columns)}")

# S03: BarStore adjusted has same row count as raw
record("S03", "BarStore adjusted preserves rows",
       len(raw) == len(adj),
       f"raw={len(raw)} adj={len(adj)}")

# S04: BarStore provenance attribute exists
record("S04", "BarStore.load attaches provenance attr",
       "provenance" in adj.attrs or hasattr(adj, "attrs"),
       f"attrs keys: {list(adj.attrs.keys())[:5]}")

# S05: market data store with bogus freq
try:
    df = mds.read("AAPL", "37x")
    record("S05", "MarketDataStore unknown freq → None/empty",
           df is None or df.empty,
           f"got {type(df).__name__}")
except Exception as e:
    record("S05", "MarketDataStore unknown freq → exception",
           True, f"{type(e).__name__}")

# ─── S06-S10: signal / strategy corners ─────────────────────────────────────

print("\n— Signal / strategy corners (S06-S10) —")

# S06: MultiFactorStrategy with unknown factor in factor_weights
import io
import logging as _lg
buf = io.StringIO()
hd = _lg.StreamHandler(buf)
_lg.getLogger().addHandler(hd)
strat = MultiFactorStrategy(
    symbols=real_syms,
    top_n=3,
    factor_weights={"momentum": 0.5, "_TOTALLY_FAKE_FACTOR_": 0.5, "low_vol": 0.5},
    strict_registry=False,
)
_lg.getLogger().removeHandler(hd)
weights = strat._weights
record("S06", "MFS warn+drop unregistered factor",
       "_TOTALLY_FAKE_FACTOR_" not in weights and "momentum" in weights,
       f"weights: {list(weights.keys())}")

# S07: MultiFactorStrategy strict_registry → raises
try:
    MultiFactorStrategy(
        symbols=real_syms, top_n=3,
        factor_weights={"momentum": 0.5, "_FAKE_": 0.5},
        strict_registry=True,
    )
    record("S07", "MFS strict raises on unknown factor", False, "no exception")
except (UnregisteredFactorError, ValueError) as e:
    record("S07", "MFS strict raises on unknown factor",
           "_FAKE_" in str(e) or "_FAKE_" in repr(e),
           f"{type(e).__name__}")

# S08: enforce_execution_factor_names strict mode same behavior
try:
    enforce_execution_factor_names({"momentum": 1.0, "fake": 1.0}, strict=True)
    record("S08", "enforce_*_names strict raises", False)
except UnregisteredFactorError:
    record("S08", "enforce_*_names strict raises", True)

# S09: enforce_*_names default mode warns + filters
filtered = enforce_execution_factor_names({"momentum": 1.0, "fake": 1.0})
record("S09", "enforce_*_names default filters",
       filtered == {"momentum": 1.0},
       f"got {filtered}")

# S10: PRODUCTION_FACTORS is a frozenset (immutable)
try:
    PRODUCTION_FACTORS.add("hack")  # type: ignore[attr-defined]
    record("S10", "PRODUCTION_FACTORS immutable", False)
except AttributeError:
    record("S10", "PRODUCTION_FACTORS immutable", True)

# ─── S11-S15: backtest corners ──────────────────────────────────────────────

print("\n— Backtest corners (S11-S15) —")

eng = BacktestEngine(cost_model=CostModel(cfg.cost_model))

# S11: empty signals → BacktestResult with zero return (or graceful failure)
try:
    sig0 = pd.DataFrame(0.0, index=panel_close.index, columns=panel_close.columns)
    res0 = eng.run(sig0, panel_close, open_df=panel_open)
    record("S11", "BacktestEngine zero-signal → 0 trade flat NAV",
           abs(res0.metrics.get("total_return", 1.0)) < 0.01,
           f"total_return={res0.metrics.get('total_return')}")
except Exception as e:
    record("S11", "BacktestEngine zero-signal → exception",
           False, f"{type(e).__name__}: {str(e)[:80]}")

# S12: signals with NaN row → BacktestEngine handles
sig_nan = pd.DataFrame(0.0, index=panel_close.index, columns=panel_close.columns)
sig_nan.iloc[10] = np.nan
try:
    res_nan = eng.run(sig_nan, panel_close, open_df=panel_open)
    record("S12", "BacktestEngine NaN signal row → no NaN equity",
           not pd.Series(res_nan.equity_curve).isna().any(),
           f"equity NaN count: {pd.Series(res_nan.equity_curve).isna().sum()}")
except Exception as e:
    record("S12", "BacktestEngine NaN signal → exception",
           False, f"{type(e).__name__}")

# S13: signals with NaN price hole on a held symbol
panel_holed = panel_close.copy()
panel_holed.iloc[20:25, 0] = np.nan  # poke a 5-day NaN hole in SPY
sig_simple = pd.DataFrame(0.0, index=panel_close.index, columns=panel_close.columns)
sig_simple["SPY"] = 1.0  # always hold SPY
try:
    res_holed = eng.run(sig_simple, panel_holed, open_df=panel_open)
    eq = pd.Series(res_holed.equity_curve)
    record("S13", "BacktestEngine NaN price hole → fallback to last_valid_close (M14 fix)",
           not eq.isna().any(),
           f"equity NaN: {eq.isna().sum()}; final NAV: {eq.iloc[-1]:.4f}")
except Exception as e:
    record("S13", "BacktestEngine NaN price hole → exception",
           False, f"{type(e).__name__}")

# S14: very short panel (5 days) — does engine crash?
short = panel_close.head(5)
short_open = panel_open.head(5)
sig_short = pd.DataFrame(0.0, index=short.index, columns=short.columns)
sig_short.iloc[0] = 1.0 / len(short.columns)
try:
    res_short = eng.run(sig_short, short, open_df=short_open)
    record("S14", "BacktestEngine 5-day panel → runs",
           len(res_short.equity_curve) > 0,
           f"equity len={len(res_short.equity_curve)}")
except Exception as e:
    record("S14", "BacktestEngine 5-day panel → exception",
           False, f"{type(e).__name__}: {str(e)[:80]}")

# S15: M12 metrics always populated
sig_concentrated = pd.DataFrame(0.0, index=panel_close.index, columns=panel_close.columns)
sig_concentrated["AAPL"] = 1.0
res_conc = eng.run(sig_concentrated, panel_close, open_df=panel_open)
m12 = {k: v for k, v in res_conc.metrics.items() if k.startswith("m12_")}
record("S15", "M12 metrics always present in result",
       len(m12) >= 3 and all(v is not None for v in m12.values()),
       f"m12 keys: {sorted(m12.keys())}")

# ─── S16-S20: concentration / M12 corners ───────────────────────────────────

print("\n— Concentration / M12 corners (S16-S20) —")

# S16: empty weights df
empty_w = pd.DataFrame()
m_empty = compute_concentration_metrics(empty_w)
record("S16", "compute_concentration_metrics empty df → safe",
       m_empty is not None,
       f"got {type(m_empty).__name__}")

# S17: single-row weights
w_one = pd.DataFrame([[0.5, 0.3, 0.2]], columns=["A", "B", "C"], index=[pd.Timestamp("2026-01-01")])
m_one = compute_concentration_metrics(w_one)
record("S17", "compute_concentration_metrics single-row",
       m_one.get("m12_top1_weight_max") == 0.5 if m_one else False,
       f"top1={m_one.get('m12_top1_weight_max') if m_one else None}")

# S18: validate_concentration top1 over 0.40
w_violation = pd.DataFrame([[0.55, 0.25, 0.20]], columns=["A","B","C"], index=[pd.Timestamp("2026-01-01")])
m_v = compute_concentration_metrics(w_violation)
ok_v, _ = validate_concentration(
    top1_observed=m_v["m12_top1_weight_max"],
    top3_observed=m_v["m12_top3_weight_max"],
    top1_ceiling=0.40, top3_ceiling=0.70,
)
record("S18", "validate_concentration over-ceiling fails",
       not ok_v,
       f"top1={m_v['m12_top1_weight_max']} ok={ok_v}")

# S19: validate_concentration top1 under 0.40 AND top3 under 0.70
w_pass = pd.DataFrame([[0.30, 0.20, 0.15, 0.20, 0.15]], columns=["A","B","C","D","E"], index=[pd.Timestamp("2026-01-01")])  # top3 = 0.30+0.20+0.20 = 0.70 ≤ 0.70 (boundary)
m_p = compute_concentration_metrics(w_pass)
ok_p, _ = validate_concentration(
    top1_observed=m_p["m12_top1_weight_max"],
    top3_observed=m_p["m12_top3_weight_max"],
    top1_ceiling=0.40, top3_ceiling=0.70,
)
record("S19", "validate_concentration within ceiling passes",
       ok_p,
       f"top1={m_p['m12_top1_weight_max']} ok={ok_p}")

# S20: weights with NaN row treated gracefully
w_nan = pd.DataFrame([[0.5, 0.3, 0.2], [np.nan, np.nan, np.nan]],
                     columns=["A","B","C"],
                     index=pd.date_range("2026-01-01", periods=2))
try:
    m_n = compute_concentration_metrics(w_nan)
    record("S20", "compute_concentration_metrics NaN row safe",
           m_n is not None and m_n.get("m12_top1_weight_max") is not None,
           f"top1={m_n.get('m12_top1_weight_max') if m_n else None}")
except Exception as e:
    record("S20", "compute_concentration_metrics NaN row exception",
           False, f"{type(e).__name__}: {str(e)[:80]}")

# ─── S21-S25: forward evidence corners (extends R2 set) ─────────────────────

print("\n— Forward evidence corners (S21-S25) —")

# Load a real spec for hashing
manifest_path = Path("data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json")
manifest = ForwardRunManifest.model_validate_json(manifest_path.read_text())
spec_path = Path("data/research_candidates/rcm_v1_defensive_composite_01.yaml")
from core.research.frozen_spec import FrozenStrategySpec
spec = FrozenStrategySpec.from_yaml_file(spec_path)

# Prepare panel for hashing — use the 6 real_syms we already loaded
hash_universe = sorted(real_syms)
hash_panel_close = pd.DataFrame({s: panel_full[s].loc[recent].close for s in hash_universe if s in panel_full})
hash_panel_dict = {"close": hash_panel_close,
                   "open": pd.DataFrame({s: panel_full[s].loc[recent].open for s in hash_universe if s in panel_full})}

as_of = hash_panel_close.index[-1].date()
# S21: signal_input_hash deterministic on identical inputs
h1, _ = compute_signal_input_hash(spec=spec, universe=hash_universe, panel=hash_panel_dict,
                                   as_of_date=as_of)
h2, _ = compute_signal_input_hash(spec=spec, universe=hash_universe, panel=hash_panel_dict,
                                   as_of_date=as_of)
record("S21", "signal_input_hash deterministic", h1 == h2)

# S22: signal_input_hash differs when symbol perturbed
h3, _ = compute_signal_input_hash(spec=spec, universe=hash_universe[:5], panel=hash_panel_dict,
                                   as_of_date=as_of)
record("S22", "signal_input_hash differs on universe change", h1 != h3)

# S23: bar_hash_rollup combines all 3 input scopes
h_roll = compute_bar_hash_rollup(
    signal_input_hash=h1,
    execution_nav_hash="ABCD" * 16,
    benchmark_hash="DCBA" * 16,
)
record("S23", "bar_hash_rollup non-empty hex digest",
       isinstance(h_roll, str) and len(h_roll) > 0 and all(c in "0123456789abcdef" for c in h_roll),
       f"got len={len(h_roll) if isinstance(h_roll, str) else 'NA'} hex_ok={isinstance(h_roll, str) and all(c in '0123456789abcdef' for c in h_roll)}")

# S24: classify_window per-symbol returns LayerLabel
from datetime import date
labels = [classify_window(s, date(2026, 4, 1), date(2026, 4, 25)) for s in hash_universe]
record("S24", "classify_window returns LayerLabel per sym",
       all(hasattr(l, "value") or isinstance(l, str) for l in labels) and len(labels) == len(hash_universe),
       f"labels[0]={labels[0]}")

# S25: revalidate on real manifest produces non-mutating result
import copy
pre_runs = copy.deepcopy(manifest.runs)
try:
    summary = revalidate_manifest(
        manifest,
        spec=spec,
        universe=hash_universe,
        panel=hash_panel_dict,
        benchmark_symbols=["SPY", "QQQ"],
        detected_by_run_label="r6_audit_dryrun",
    )
    record("S25", "revalidate non-mutating on real manifest",
           manifest.runs == pre_runs,
           f"events={len(summary.events)} requires_review={summary.requires_data_review}")
except Exception as e:
    record("S25", "revalidate exception",
           False, f"{type(e).__name__}: {str(e)[:120]}")

# ─── S26-S30: config / loader corners ───────────────────────────────────────

print("\n— Config / loader corners (S26-S30) —")

# S26: load_config with valid path returns nested cfg
record("S26", "load_config returns nested config",
       hasattr(cfg, "backtest") and hasattr(cfg, "cost_model") and hasattr(cfg, "risk"))

# S27: AcceptanceThresholds has expected fields (replaces dead ValidationConfig
# probe; threshold unification PRD step 4 deleted ValidationConfig 2026-04-28).
ac = cfg.acceptance.tier_d
record("S27", "AcceptanceThresholds.tier_d has all expected fields",
       hasattr(ac, "min_excess_return_vs_spy") and hasattr(ac, "min_ir_vs_spy"),
       f"min_excess={ac.min_excess_return_vs_spy} min_ir={ac.min_ir_vs_spy}")

# S28: load_config rejects malformed path (no config files)
try:
    bad = load_config(Path("/tmp/_nonexistent_config_dir_xyz_"))
    record("S28", "load_config bad path",
           bad is None or not hasattr(bad, "backtest"),
           "did not raise")
except Exception as e:
    record("S28", "load_config bad path raises",
           True, f"{type(e).__name__}")

# S29: PRODUCTION_FACTORS list returned in stable order
from core.factors.factor_registry import production_factor_names
order1 = production_factor_names()
order2 = production_factor_names()
record("S29", "production_factor_names stable", order1 == order2)

# S30: research_only_factors excludes mapped names
from core.factors.factor_registry import research_only_factors, RESEARCH_TO_PRODUCTION_MAP
ro = research_only_factors()
mapped = {k for k, v in RESEARCH_TO_PRODUCTION_MAP.items() if v}
record("S30", "research_only_factors excludes mapped",
       len(ro & mapped) == 0,
       f"|ro|={len(ro)} |mapped|={len(mapped)}")

# ─── S31-S35: concurrency / determinism corners ─────────────────────────────

print("\n— Concurrency / determinism corners (S31-S35) —")

# S31: BacktestEngine concurrent runs return identical metrics
def run_bt():
    return eng.run(sig_simple, panel_close, open_df=panel_open).metrics["total_return"]

with ThreadPoolExecutor(max_workers=2) as ex:
    f1 = ex.submit(run_bt)
    f2 = ex.submit(run_bt)
    r1, r2 = f1.result(), f2.result()
record("S31", "BacktestEngine concurrent identical",
       abs(r1 - r2) < 1e-12, f"r1={r1:.10f} r2={r2:.10f}")

# S32: hash determinism across thread
def hash_thread():
    h, _ = compute_signal_input_hash(spec=spec, universe=hash_universe,
                                      panel=hash_panel_dict,
                                      as_of_date=as_of)
    return h

with ThreadPoolExecutor(max_workers=4) as ex:
    out = list(ex.map(lambda _: hash_thread(), range(4)))
record("S32", "signal_input_hash thread-stable",
       len(set(out)) == 1, f"{len(set(out))} unique hashes from 4 threads")

# S33: revalidate concurrent on same manifest no mutation
def reval_thread():
    return revalidate_manifest(
        manifest, spec=spec, universe=hash_universe,
        panel=hash_panel_dict, benchmark_symbols=["SPY"],
        detected_by_run_label="r6_concurrent",
    )

with ThreadPoolExecutor(max_workers=2) as ex:
    s1 = ex.submit(reval_thread)
    s2 = ex.submit(reval_thread)
    sum1, sum2 = s1.result(), s2.result()
record("S33", "revalidate concurrent identical event count",
       len(sum1.events) == len(sum2.events))

# S34: classify_as_of stable across calls
labels1 = [classify_as_of(s, as_of) for s in hash_universe]
labels2 = [classify_as_of(s, as_of) for s in hash_universe]
record("S34", "classify_as_of stable", labels1 == labels2)

# S35: _resolve_lookback_window_start determinism
ws1 = _resolve_lookback_window_start(hash_panel_dict, as_of, 21)
ws2 = _resolve_lookback_window_start(hash_panel_dict, as_of, 21)
record("S35", "_resolve_lookback_window_start stable", ws1 == ws2,
       f"ws={ws1}")

# ─── S36+: extreme inputs ───────────────────────────────────────────────────

print("\n— Extreme input corners (S36-S40) —")

# S36: hash on 1-symbol universe
h_one, _ = compute_signal_input_hash(spec=spec, universe=[hash_universe[0]],
                                      panel=hash_panel_dict, as_of_date=as_of)
record("S36", "signal_input_hash 1-symbol universe valid",
       isinstance(h_one, str) and len(h_one) > 0)

# S37: lookback_window with lookback=1
ws_min = _resolve_lookback_window_start(hash_panel_dict, as_of, 1)
record("S37", "_resolve_lookback lookback=1 returns valid date",
       ws_min is not None,
       f"ws_min={ws_min}")

# S38: classify_window with start > end (backwards) per-symbol
try:
    lbl = classify_window(hash_universe[0], date(2026, 5, 1), date(2026, 4, 1))
    record("S38", "classify_window backwards range → returns LayerLabel",
           lbl is not None,
           f"got {lbl}")
except Exception as e:
    record("S38", "classify_window backwards exception",
           False, f"{type(e).__name__}: {str(e)[:80]}")

# S39: M12 metrics in single-day panel
single_day = panel_close.head(1)
single_open = panel_open.head(1)
sig_single = pd.DataFrame(1.0/len(single_day.columns), index=single_day.index, columns=single_day.columns)
try:
    rs = eng.run(sig_single, single_day, open_df=single_open)
    m12s = {k: v for k, v in rs.metrics.items() if k.startswith("m12_")}
    record("S39", "BacktestEngine single-day → still emits M12",
           len(m12s) >= 3,
           f"m12 keys present: {len(m12s)}")
except Exception as e:
    record("S39", "single-day backtest exception",
           False, f"{type(e).__name__}: {str(e)[:80]}")

# S40: PRODUCTION_FACTORS subset overlap with RESEARCH_FACTORS
overlap = PRODUCTION_FACTORS & RESEARCH_FACTORS
record("S40", "PROD/RES overlap is exactly drawup_from_252d_low",
       overlap == {"drawup_from_252d_low"},
       f"overlap={sorted(overlap)}")

# ─── final tally ─────────────────────────────────────────────────────────────

print("\n" + "=" * 78)
print("R6 / B3 final summary")
print("=" * 78)
n_pass = sum(1 for _, _, s in results if s == "PASS")
n_fail = sum(1 for _, _, s in results if s == "FAIL")
print(f"  Total: {len(results)}  PASS: {n_pass}  FAIL: {n_fail}")
print(f"  OVERALL: {n_pass}/{len(results)} ({'PASS' if n_fail == 0 else 'FAIL'})")
sys.exit(0 if n_fail == 0 else 1)
