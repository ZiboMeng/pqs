"""Track B Step 5 — C2 pairwise correlation budget tests.

PRD §4.2 + §5.4: ``check_correlation_budget(returns_df) →
CorrelationBudgetStatus``. Pure-functional; no manifest mutation in
Step 5 — observe() / Step 8 is the boundary that wires status onto
the fleet manifest event list (codex round-25 boundary).

Boundaries:
  - Step 5 uses *realized* candidate daily returns, NOT IC.
  - ``warn`` threshold default 0.70; ``reject`` default 0.85.
  - Below ``corr_min_overlap_days`` (default 60) → ``insufficient_data``
    so caller fails-closed rather than assuming "ok".
  - All hardening (NaN, inf, non-numeric, all-NaN column, zero variance)
    must surface as domain ValueError.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.fleet import (
    CorrelationBudgetStatus,
    CorrelationPair,
    FleetAllocator,
    FleetCandidate,
    FleetConfig,
)


def _alloc(*, warn=0.70, reject=0.85, lookback=252, min_overlap=60):
    cfg = FleetConfig(
        candidates=[
            FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
            FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
        ],
        max_pairwise_corr_warn=warn,
        max_pairwise_corr_reject=reject,
        corr_lookback_days=lookback,
        corr_min_overlap_days=min_overlap,
    )
    return FleetAllocator(cfg)


def _alloc_three(*, warn=0.70, reject=0.85):
    cfg = FleetConfig(
        candidates=[
            FleetCandidate(candidate_id="c1", role="core", base_weight=1 / 3),
            FleetCandidate(candidate_id="c2", role="core", base_weight=1 / 3),
            FleetCandidate(candidate_id="s1", role="satellite", base_weight=1 / 3),
        ],
        split_policy="equal_weight",
        max_pairwise_corr_warn=warn,
        max_pairwise_corr_reject=reject,
    )
    return FleetAllocator(cfg)


def _returns_df(*, n=120, candidates=("c1", "c2"), seed=0, correlation=0.0):
    """Generate ``n`` daily returns for each candidate with a controlled
    pairwise correlation between the first two columns. Subsequent columns
    are independent of the first two."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    base = rng.standard_normal(n) * 0.01
    noise = rng.standard_normal(n) * 0.01
    if correlation == 0.0:
        col2 = noise
    else:
        col2 = correlation * base + np.sqrt(1 - correlation ** 2) * noise
    cols = {candidates[0]: base, candidates[1]: col2}
    for c in candidates[2:]:
        cols[c] = rng.standard_normal(n) * 0.01
    return pd.DataFrame(cols, index=idx)


# ---------------------------------------------------------------------------
# Happy path: ok / warn / reject classifications
# ---------------------------------------------------------------------------


def test_ok_when_pairwise_corr_below_warn():
    alloc = _alloc()
    df = _returns_df(n=120, correlation=0.10)
    s = alloc.check_correlation_budget(df)
    assert isinstance(s, CorrelationBudgetStatus)
    assert s.level == "ok"
    assert s.max_pairwise_corr is not None and s.max_pairwise_corr < 0.70
    assert s.n_observations == 120
    assert s.lookback_requested == 252
    assert len(s.pairs) == 1
    assert s.pairs[0].level == "ok"
    assert s.reason is None


def test_warn_when_pairwise_corr_in_warn_band():
    alloc = _alloc()
    df = _returns_df(n=120, correlation=0.78)
    s = alloc.check_correlation_budget(df)
    assert s.level == "warn"
    assert 0.70 <= s.max_pairwise_corr < 0.85
    assert any(p.level == "warn" for p in s.pairs)
    assert all(p.level != "reject" for p in s.pairs)
    assert s.reason is not None and "warn" in s.reason


def test_reject_when_pairwise_corr_above_reject():
    alloc = _alloc()
    df = _returns_df(n=120, correlation=0.92)
    s = alloc.check_correlation_budget(df)
    assert s.level == "reject"
    assert s.max_pairwise_corr >= 0.85
    assert any(p.level == "reject" for p in s.pairs)
    assert s.reason is not None and "reject" in s.reason


def test_aggregate_level_is_worst_pair_level_three_candidates():
    """3 candidates → 3 pairs. If any pair is reject, aggregate is reject."""
    alloc = _alloc_three()
    rng = np.random.default_rng(42)
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    a = rng.standard_normal(n) * 0.01
    # b correlated 0.92 with a (reject), c independent of both
    b = 0.92 * a + np.sqrt(1 - 0.92 ** 2) * rng.standard_normal(n) * 0.01
    c = rng.standard_normal(n) * 0.01
    df = pd.DataFrame({"c1": a, "c2": b, "s1": c}, index=idx)
    s = alloc.check_correlation_budget(df)
    assert s.level == "reject"
    # Exactly one pair (c1, c2) should be reject
    reject_pairs = [p for p in s.pairs if p.level == "reject"]
    assert len(reject_pairs) == 1
    # And the {c1, c2} pair is the offender
    pair = reject_pairs[0]
    assert {pair.candidate_a, pair.candidate_b} == {"c1", "c2"}


# ---------------------------------------------------------------------------
# Threshold boundary semantics
# ---------------------------------------------------------------------------


def test_pair_at_warn_boundary_is_warn_not_ok():
    """rho exactly at warn threshold (0.70) → warn (>= comparison)."""
    alloc = _alloc(warn=0.70, reject=0.85)
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    rng = np.random.default_rng(7)
    a = rng.standard_normal(n) * 0.01
    # Construct b s.t. realized correlation is approximately exactly 0.70.
    # Sample many seeds until we land in [0.695, 0.705].
    for trial_seed in range(200):
        rng_t = np.random.default_rng(1000 + trial_seed)
        noise = rng_t.standard_normal(n) * 0.01
        b = 0.70 * a + np.sqrt(1 - 0.70 ** 2) * noise
        rho = np.corrcoef(a, b)[0, 1]
        if 0.695 <= rho <= 0.705:
            break
    df = pd.DataFrame({"c1": a, "c2": b}, index=idx)
    s = alloc.check_correlation_budget(df)
    # Warn band is inclusive on the lower bound.
    if rho >= 0.70:
        assert s.level == "warn"
    else:
        assert s.level == "ok"


def test_pair_at_reject_boundary_is_reject_not_warn():
    alloc = _alloc()
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    rng = np.random.default_rng(11)
    a = rng.standard_normal(n) * 0.01
    for trial_seed in range(200):
        rng_t = np.random.default_rng(2000 + trial_seed)
        noise = rng_t.standard_normal(n) * 0.01
        b = 0.85 * a + np.sqrt(1 - 0.85 ** 2) * noise
        rho = np.corrcoef(a, b)[0, 1]
        if 0.846 <= rho <= 0.855:
            break
    df = pd.DataFrame({"c1": a, "c2": b}, index=idx)
    s = alloc.check_correlation_budget(df)
    if rho >= 0.85:
        assert s.level == "reject"
    else:
        assert s.level == "warn"


# ---------------------------------------------------------------------------
# Insufficient overlap
# ---------------------------------------------------------------------------


def test_insufficient_data_when_below_min_overlap():
    alloc = _alloc(min_overlap=60)
    df = _returns_df(n=30, correlation=0.92)  # only 30 rows
    s = alloc.check_correlation_budget(df)
    assert s.level == "insufficient_data"
    assert s.max_pairwise_corr is None
    assert s.pairs == []
    assert s.n_observations == 30
    assert "60" in (s.reason or "")


def test_insufficient_data_when_dropna_drops_below_min_overlap():
    """Even if raw rows are 120, if NaNs in different rows drop the
    intersection below min_overlap, status must be insufficient_data."""
    alloc = _alloc(min_overlap=60)
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    rng = np.random.default_rng(1)
    a = rng.standard_normal(n) * 0.01
    b = rng.standard_normal(n) * 0.01
    # NaN out alternating rows in c1 and c2 so dropna leaves ~0 rows.
    a_with_nan = a.copy()
    b_with_nan = b.copy()
    a_with_nan[::2] = np.nan
    b_with_nan[1::2] = np.nan
    df = pd.DataFrame({"c1": a_with_nan, "c2": b_with_nan}, index=idx)
    s = alloc.check_correlation_budget(df)
    assert s.level == "insufficient_data"


def test_lookback_truncation_does_not_exceed_recent_history():
    """If returns extend further back than lookback, only the most recent
    lookback rows are used. Guard against an old-history contamination
    bug where ancient returns dominate the correlation estimate."""
    alloc = _alloc(lookback=60, min_overlap=30)
    n = 200
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    rng = np.random.default_rng(13)
    # First half: highly correlated. Second half (most recent 100): independent.
    a_recent = rng.standard_normal(60) * 0.01
    b_recent = rng.standard_normal(60) * 0.01  # independent
    a_old = rng.standard_normal(n - 60) * 0.01
    b_old = a_old.copy()  # perfectly correlated
    a = np.concatenate([a_old, a_recent])
    b = np.concatenate([b_old, b_recent])
    df = pd.DataFrame({"c1": a, "c2": b}, index=idx)
    s = alloc.check_correlation_budget(df)
    # Only the recent 60 rows should drive the result → ok or low-warn,
    # NOT reject (which it would be if we used the full 200 rows).
    assert s.level in ("ok", "warn")
    assert s.n_observations == 60


# ---------------------------------------------------------------------------
# Input hardening (codex R25 P0.1 + R27 P2 idiom carried into Step 5)
# ---------------------------------------------------------------------------


def test_rejects_non_dataframe():
    alloc = _alloc()
    with pytest.raises(TypeError, match="DataFrame"):
        alloc.check_correlation_budget([[0.01, 0.02], [0.02, 0.01]])


def test_rejects_single_candidate():
    alloc = _alloc()
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    df = pd.DataFrame({"c1": np.zeros(n)}, index=idx)
    with pytest.raises(ValueError, match=">= 2 candidate columns"):
        alloc.check_correlation_budget(df)


def test_rejects_non_datetime_index():
    alloc = _alloc()
    df = pd.DataFrame(
        {"c1": [0.01, 0.02, 0.03], "c2": [0.02, 0.01, 0.03]},
        index=["2024-01-02", "2024-01-03", "2024-01-04"],
    )
    with pytest.raises(ValueError, match="DatetimeIndex"):
        alloc.check_correlation_budget(df)


def test_rejects_duplicate_index():
    alloc = _alloc()
    df = pd.DataFrame(
        {"c1": [0.01, 0.02, 0.03], "c2": [0.02, 0.01, 0.03]},
        index=pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-04"]),
    )
    with pytest.raises(ValueError, match="duplicate index"):
        alloc.check_correlation_budget(df)


def test_rejects_inf():
    alloc = _alloc()
    df = _returns_df(n=120, correlation=0.10)
    df.iloc[5, 0] = np.inf
    with pytest.raises(ValueError, match="inf"):
        alloc.check_correlation_budget(df)


def test_rejects_non_numeric_dtype():
    alloc = _alloc()
    df = pd.DataFrame(
        {"c1": ["a", "b", "c"], "c2": ["d", "e", "f"]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    with pytest.raises(ValueError, match="non-numeric"):
        alloc.check_correlation_budget(df)


def test_rejects_all_nan_column():
    alloc = _alloc()
    df = _returns_df(n=120, correlation=0.10)
    df["c2"] = np.nan
    with pytest.raises(ValueError, match="all-NaN"):
        alloc.check_correlation_budget(df)


def test_rejects_zero_variance_column_via_nan_corr():
    """Constant return series → pandas .corr() yields NaN. Step 5 surfaces
    a clear domain error rather than silently returning NaN max_corr."""
    alloc = _alloc()
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    rng = np.random.default_rng(5)
    df = pd.DataFrame(
        {"c1": np.zeros(n), "c2": rng.standard_normal(n) * 0.01},
        index=idx,
    )
    with pytest.raises(ValueError, match="non-finite|zero-variance"):
        alloc.check_correlation_budget(df)


# ---------------------------------------------------------------------------
# Step 5 boundary: NO manifest mutation
# ---------------------------------------------------------------------------


def test_step5_does_not_mutate_manifest():
    """Step 5 is pure-functional. Calling check_correlation_budget must not
    write to any manifest. Step 8 (frozen) will translate violations into
    FleetEvent c2_corr_violation entries on observe()."""
    alloc = _alloc()
    df = _returns_df(n=120, correlation=0.92)
    # check_correlation_budget — should NOT raise NotImplementedError now
    # (Step 5 just landed) but observe() is still frozen.
    s = alloc.check_correlation_budget(df)
    assert s.level == "reject"
    # observe() must still raise NotImplementedError("frozen") — Step 8 is
    # the boundary that wires C2 status onto the manifest event list.
    with pytest.raises(NotImplementedError, match="frozen"):
        alloc.observe(as_of_date=pd.Timestamp("2026-04-29").date())


# ---------------------------------------------------------------------------
# Pair structural detail
# ---------------------------------------------------------------------------


def test_pair_record_uses_pair_a_b_in_canonical_order():
    """Audit R2.6 (2026-04-29): pairs MUST be enumerated in canonical
    lexicographic order so semantically-identical inputs with reordered
    columns produce byte-identical CorrelationBudgetStatus. Anything
    less corrupts fleet manifest event hashing once Step 8 lands."""
    alloc = _alloc_three()
    rng = np.random.default_rng(99)
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "c1": rng.standard_normal(n) * 0.01,
            "c2": rng.standard_normal(n) * 0.01,
            "s1": rng.standard_normal(n) * 0.01,
        },
        index=idx,
    )
    s = alloc.check_correlation_budget(df)
    pair_keys = [(p.candidate_a, p.candidate_b) for p in s.pairs]
    # 3 candidates → 3 unordered pairs in lexicographic order
    assert len(pair_keys) == 3
    assert pair_keys == [("c1", "c2"), ("c1", "s1"), ("c2", "s1")]
    # Per-pair (a, b) order must satisfy a < b
    for p in s.pairs:
        assert p.candidate_a < p.candidate_b


def test_pair_order_invariant_across_input_column_permutations():
    """Audit R2.6 regression: passing the SAME data with columns in a
    different order MUST return byte-identical pair entries. Pre-fix,
    pair tuples flipped (e.g. ('s1', 'c1') vs ('c1', 's1')) depending
    on input column order — would have hashed differently in a fleet
    manifest event."""
    alloc = _alloc_three()
    n = 120
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    rng = np.random.default_rng(7)
    arrs = {ch: rng.standard_normal(n) * 0.01 for ch in ("a", "b", "c")}
    df_natural = pd.DataFrame(
        {"c1": arrs["a"], "c2": arrs["b"], "s1": arrs["c"]}, index=idx
    )
    df_reordered = pd.DataFrame(
        {"s1": arrs["c"], "c2": arrs["b"], "c1": arrs["a"]}, index=idx
    )
    s_natural = alloc.check_correlation_budget(df_natural)
    s_reordered = alloc.check_correlation_budget(df_reordered)
    # JSON-bytes equality is the strongest determinism check (what fleet
    # event serialization will use).
    assert s_natural.model_dump_json() == s_reordered.model_dump_json()


def test_correlation_pair_correlation_in_neg1_pos1_range():
    alloc = _alloc()
    df = _returns_df(n=120, correlation=-0.30)  # negative correlation
    s = alloc.check_correlation_budget(df)
    p = s.pairs[0]
    assert -1.0 <= p.correlation <= 1.0
    # Negative correlation → ok level (still under warn 0.70 in absolute terms;
    # the budget is one-sided per PRD §4.2 — only POSITIVE collapse hurts
    # variance reduction; negative correlation is GOOD for the fleet).
    assert s.level == "ok"
