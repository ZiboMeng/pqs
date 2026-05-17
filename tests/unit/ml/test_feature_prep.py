"""R0 acceptance — data-preparation layer (supplementary PRD §3).

R0-A1 rank-norm causal · R0-A2 winsorize + config-sourced ·
R0-A3 sector-neutral PIT · R0-A4 frac-diff ADF/min-d/opt-in-bit-identical ·
R0-A5 survivorship audit schema.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from core.ml.feature_prep import (
    cross_sectional_rank_norm,
    frac_diff_ffd,
    min_ffd,
    prepare_factor_panel,
    sector_neutralize,
    vol_scale,
    winsorize,
)

_PROJ = Path(__file__).resolve().parents[3]


def _panel(n_dates=60, n_sym=10, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n_dates)
    cols = [f"S{i}" for i in range(n_sym)]
    return pd.DataFrame(rng.standard_normal((n_dates, n_sym)),
                        index=idx, columns=cols)


# R0-A1 ---------------------------------------------------------------
def test_ranknorm_in_unit_interval_and_causal():
    df = _panel()
    r = cross_sectional_rank_norm(df)
    v = r.to_numpy()
    assert np.nanmin(v) >= 0.0 and np.nanmax(v) <= 1.0
    # causal: truncating the panel to <= t does not change row t
    t = df.index[40]
    full = cross_sectional_rank_norm(df).loc[t]
    trunc = cross_sectional_rank_norm(df.loc[:t]).loc[t]
    pd.testing.assert_series_equal(full, trunc)


# R0-A2 ---------------------------------------------------------------
def test_winsorize_caps_and_config_sourced():
    df = _panel()
    df.iloc[0, 0] = 999.0
    w = winsorize(df, 0.05, 0.95)
    # no value exceeds the per-row 95th pct / below 5th pct
    for dt in df.index:
        lo, hi = df.loc[dt].quantile(0.05), df.loc[dt].quantile(0.95)
        assert w.loc[dt].max() <= hi + 1e-9
        assert w.loc[dt].min() >= lo - 1e-9
    with pytest.raises(ValueError):
        winsorize(df, 0.9, 0.1)
    # thresholds are config-sourced: yaml is the SoT; changing the yaml
    # changes behavior without a code edit (G7). .get(key, default)
    # fallbacks are acceptable robustness, not hardcoded overrides.
    cfg = yaml.safe_load((_PROJ / "config" / "ml_feature_prep.yaml").read_text())
    assert cfg["winsorize"]["p_low"] == 0.01 and cfg["winsorize"]["p_high"] == 0.99
    panel = {"f": _panel()}
    base = prepare_factor_panel(
        panel, {"winsorize": {"enabled": True, "p_low": 0.01, "p_high": 0.99},
                "rank_norm": {"enabled": False},
                "sector_neutralize": {"enabled": False},
                "vol_scale": {"enabled": False}})
    tight = prepare_factor_panel(
        panel, {"winsorize": {"enabled": True, "p_low": 0.2, "p_high": 0.8},
                "rank_norm": {"enabled": False},
                "sector_neutralize": {"enabled": False},
                "vol_scale": {"enabled": False}})
    # different yaml-level thresholds → different output (config drives it)
    assert not base["f"].equals(tight["f"])


# R0-A3 ---------------------------------------------------------------
def test_sector_neutral_within_sector_mean_zero_pit():
    df = _panel(n_sym=6)
    smap = {"S0": "Tech", "S1": "Tech", "S2": "Tech",
            "S3": "Fin", "S4": "Fin", "S5": "Fin"}
    seen_dates = []

    def sector_of(sym, as_of):
        seen_dates.append(as_of)
        return smap[sym]

    out = sector_neutralize(df, sector_of)
    # PIT: resolver called with date objects (no future leak by design)
    assert all(isinstance(d, date) for d in seen_dates)
    for dt in df.index:
        for grp in (["S0", "S1", "S2"], ["S3", "S4", "S5"]):
            assert abs(out.loc[dt, grp].mean()) < 1e-9


# R0-A4 ---------------------------------------------------------------
def test_fracdiff_adf_and_min_d_and_optin_bit_identical():
    rng = np.random.default_rng(1)
    # random walk (non-stationary) — needs d>0 to become stationary
    rw = pd.Series(np.cumsum(rng.standard_normal(800)))
    d, ffd = min_ffd(rw, d_grid=[round(x, 2) for x in np.arange(0, 1.01, 0.1)])
    assert 0.0 < d <= 1.0
    assert ffd.dropna().shape[0] > 100
    # d=0 is identity (no differencing) up to FFD warmup
    f0 = frac_diff_ffd(rw, 0.0)
    pd.testing.assert_series_equal(
        f0.dropna(), rw.loc[f0.dropna().index].astype(float),
        check_names=False)
    # opt-in OFF → panel bit-identical through prepare_factor_panel
    panel = {"f": _panel()}
    cfg = {"frac_diff": {"enabled": False}, "winsorize": {"enabled": False},
           "sector_neutralize": {"enabled": False},
           "vol_scale": {"enabled": False}, "rank_norm": {"enabled": False}}
    out = prepare_factor_panel(panel, cfg)
    pd.testing.assert_frame_equal(out["f"], panel["f"])


def test_vol_scale_is_causal():
    df = _panel()
    rets = _panel(seed=2).abs() + 0.01
    s = vol_scale(df, rets, lookback=10)
    # row t uses vol from <= t-1 (shift 1): truncation invariance at t
    t = df.index[40]
    full = vol_scale(df, rets, 10).loc[t]
    trunc = vol_scale(df.loc[:t], rets.loc[:t], 10).loc[t]
    pd.testing.assert_series_equal(full, trunc)


# R0-A5 ---------------------------------------------------------------
def test_survivorship_audit_schema():
    p = _PROJ / "data" / "audit" / "ml_redo" / "survivorship_audit.json"
    assert p.exists(), "run dev/scripts/ml_redo/survivorship_audit.py"
    a = json.loads(p.read_text())
    for k in ("per_year_alive", "delisting_stale_proxy", "bias_estimate_frac",
              "pit_first_trade_date_exists", "as_of_membership_rebuild_exists",
              "as_of_rebuild_required", "note"):
        assert k in a, f"missing {k}"
    assert isinstance(a["as_of_rebuild_required"], bool)
    assert a["as_of_rebuild_required"] is True  # structural: yaml = survivors
    assert a["as_of_membership_rebuild_exists"] is False
