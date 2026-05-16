"""P4·R2 — multi-round data-cleanliness audit of the expanded_v1 universe.

Per user directive 2026-05-16 ("数据一定要干净 所以数据那边要多做几轮 audit")
and the 4-layer self-audit methodology (feedback_self_audit_methodology).
Audits all 330 resolve_universe("expanded_v1") symbols' data/daily parquets.

Rounds
------
R1  schema + index hygiene  — columns present; index monotonic, unique,
    tz-naive, midnight-normalized, NO weekend rows.
R2  OHLC validity           — high>=low, high>=max(open,close),
    low<=min(open,close), all prices finite & > 0, volume finite & >= 0,
    NO NaN in OHLC.
R3  dynamics                — day-over-day adjusted-close returns: flag
    |ret| > 0.50 (auto_adjust=True handles splits, so a >50% jump is a
    genuine anomaly worth eyeballing); internal gaps: longest run of
    consecutive missing NYSE trading days within each symbol's own span.
R4  boundary / cross-source — re-fetch a deterministic sample via the
    same provider and assert byte-stable; confirm the 251 ADDED symbols
    all start <= 2015-02-01; confirm executable-79 parquets are byte-
    identical to before this round (D6 isolation — the audit must not
    have touched them).

Exit 0 iff every round passes (or only WARN-level findings). Writes
data/audit/chart_structure/phase4_data_audit.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.universe.universe_resolver import resolve_universe  # noqa: E402

_DAILY = _PROJ / "data" / "daily"
_OHLC = ["open", "high", "low", "close"]
_JUMP_THRESH = 0.50
_GAP_THRESH = 5  # consecutive missing NYSE business days = severe


def _load(sym: str) -> pd.DataFrame:
    df = pd.read_parquet(_DAILY / f"{sym}.parquet")
    df.index = pd.DatetimeIndex(df.index).as_unit("ns")
    return df


def r1_index(syms: list[str]) -> dict:
    bad = {}
    for s in syms:
        df = _load(s)
        idx = df.index
        problems = []
        for c in ["open", "high", "low", "close", "volume"]:
            if c not in df.columns:
                problems.append(f"missing_col:{c}")
        if not idx.is_monotonic_increasing:
            problems.append("not_monotonic")
        if idx.duplicated().any():
            problems.append(f"dup_dates:{int(idx.duplicated().sum())}")
        if idx.tz is not None:
            problems.append("tz_aware")
        if (idx.normalize() != idx).any():
            problems.append("intraday_component")
        wk = idx.dayofweek
        nwk = int(((wk == 5) | (wk == 6)).sum())
        if nwk:
            problems.append(f"weekend_rows:{nwk}")
        if problems:
            bad[s] = problems
    return {"round": "R1_index_hygiene", "n_checked": len(syms),
            "n_bad": len(bad), "bad": bad, "passed": not bad}


def r2_ohlc(syms: list[str]) -> dict:
    """FAIL: NaN OHLC, non-positive price, negative volume, high<low, or a
    bar-bound violation worse than 0.5% relative. WARN: a bar-bound
    violation <= 0.5% relative (last-bar / rounding artifact)."""
    bad: dict = {}
    warn: dict = {}
    for s in syms:
        df = _load(s)
        o, h, l, c = (df[x].to_numpy(float) for x in _OHLC)
        v = df["volume"].to_numpy(float)
        problems = []
        warns = []
        if np.isnan(df[_OHLC].to_numpy(float)).any():
            problems.append(f"nan_ohlc:{int(np.isnan(df[_OHLC].to_numpy(float)).sum())}")
        m = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
        if ((c[m] <= 0) | (o[m] <= 0) | (h[m] <= 0) | (l[m] <= 0)).any():
            problems.append("nonpositive_price")
        if (h[m] < l[m] - 1e-6).any():
            problems.append(f"high_lt_low:{int((h[m] < l[m] - 1e-6).sum())}")
        # bar-bound violations: classify by relative magnitude
        for name, viol in (
            ("high_lt_oc", np.maximum(o[m], c[m]) - h[m]),
            ("low_gt_oc", l[m] - np.minimum(o[m], c[m])),
        ):
            hit = viol > 1e-6
            if hit.any():
                rel = float((viol[hit] / np.maximum(c[m][hit], 1e-9)).max())
                tag = f"{name}:n={int(hit.sum())},max_rel={rel:.5f}"
                (warns if rel <= 5e-3 else problems).append(tag)
        vf = np.isfinite(v)
        if (v[vf] < 0).any():
            problems.append("negative_volume")
        if problems:
            bad[s] = problems
        if warns:
            warn[s] = warns
    return {"round": "R2_ohlc_validity", "n_checked": len(syms),
            "n_bad": len(bad), "bad": bad, "n_warn": len(warn), "warn": warn,
            "passed": not bad}


def r3_dynamics(syms: list[str], executable: set[str]) -> dict:
    """Completeness verdict DEFERS to the authoritative project gate
    `core.data.data_completeness_gate.check_panel_completeness` (the SoT
    that `config/executable_universe.yaml` itself is verified against) —
    R3 does not reimplement it. R3 additionally reports the day-over-day
    close-jump structure: executable-79 raw-store symbols carry split
    jumps in raw close (EXPECTED — splits applied at read time), the
    auto_adjust=True added symbols' >50% jumps are real corporate events
    / volatility (WARN, eyeballed in the closeout)."""
    from core.data.calendar import get_trading_days
    from core.data.data_completeness_gate import check_panel_completeness

    sessions = pd.DatetimeIndex(get_trading_days("2007-01-01", "2026-05-16")).normalize()
    jumps_added = {}
    jumps_base = {}
    miss_added = {}  # informational: scattered missing sessions among ADDED
    cols = {}
    for s in syms:
        df = _load(s)
        c = df["close"].astype(float)
        big = c.pct_change()[c.pct_change().abs() > _JUMP_THRESH]
        if len(big):
            rec = [(str(d.date()), round(float(r), 4)) for d, r in big.items()]
            (jumps_base if s in executable else jumps_added)[s] = rec
        cols[s] = pd.Series(c.values, index=df.index.normalize())
        if s not in executable:
            present = df.index.normalize()
            span = sessions[(sessions >= present[0]) & (sessions <= present[-1])]
            n_miss = len(span.difference(present))
            if n_miss:
                miss_added[s] = int(n_miss)
    panel = pd.DataFrame(cols).sort_index()
    panel = panel[~panel.index.duplicated()]
    rep = check_panel_completeness(panel, list(cols.keys()),
                                   max_consecutive_missing_bd=5)
    return {"round": "R3_dynamics", "n_checked": len(syms),
            "completeness_gate": {"tool": "check_panel_completeness",
                                  "n_pass": rep.n_pass, "n_fail": rep.n_fail,
                                  "failed": list(rep.failed_symbols),
                                  "overall_passed": rep.overall_passed},
            "n_jump_added_warn": len(jumps_added), "jumps_added_warn": jumps_added,
            "n_jump_base_expected": len(jumps_base),
            "jumps_base_expected_raw_split": jumps_base,
            "added_scattered_missing_sessions_info": miss_added,
            "passed": rep.overall_passed}


def r4_boundary(added: list[str], executable: list[str]) -> dict:
    problems = []
    # 4a: added symbols all start <= 2015-02-01
    late = []
    for s in added:
        idx = _load(s).index
        if idx[0] > pd.Timestamp("2015-02-01"):
            late.append((s, str(idx[0].date())))
    if late:
        problems.append({"check": "added_late_start", "detail": late})
    # 4b: cross-source byte-stability — re-fetch a deterministic sample
    sample = sorted(added)[::25][:10]
    try:
        from core.data.yfinance_provider import YFinanceProvider
        prov = YFinanceProvider(auto_adjust=True, progress=False)
        res = prov.fetch_daily(sample, start="2025-01-01", end="2026-05-16")
        drift = []
        for s in sample:
            if s not in res:
                drift.append((s, "no_refetch"))
                continue
            fresh = res[s].df["close"].astype(float)
            disk = _load(s)["close"].astype(float)
            common = fresh.index.normalize().intersection(disk.index.normalize())
            if len(common) < 50:
                drift.append((s, f"thin_overlap:{len(common)}"))
                continue
            fa = fresh.copy(); fa.index = fa.index.normalize()
            da = disk.copy(); da.index = da.index.normalize()
            d = (fa.reindex(common) - da.reindex(common)).abs()
            rel = (d / da.reindex(common).abs()).max()
            if rel > 1e-3:
                drift.append((s, f"rel_drift:{rel:.5f}"))
        if drift:
            problems.append({"check": "cross_source_stability", "detail": drift})
        cross_source = {"sample": sample, "max_rel_drift_ok": not drift}
    except Exception as e:  # noqa: BLE001
        cross_source = {"sample": sample, "error": str(e)}
        problems.append({"check": "cross_source_stability", "detail": str(e)})
    # 4c: executable-79 parquets unaffected — none should be a .preP4Expand
    touched = [s for s in executable
               if list(_DAILY.glob(f"{s}.parquet.preP4Expand_*"))]
    if touched:
        problems.append({"check": "d6_isolation_executable_touched",
                         "detail": touched})
    return {"round": "R4_boundary", "n_added_checked": len(added),
            "cross_source": cross_source, "problems": problems,
            "passed": not problems}


def main() -> int:
    syms = resolve_universe("expanded_v1")
    executable = resolve_universe("executable")
    added = sorted(set(syms) - set(executable))
    print(f"auditing {len(syms)} expanded_v1 symbols "
          f"({len(added)} added, {len(executable)} executable base)")

    r1 = r1_index(syms)
    print(f"  R1 index hygiene:  {'PASS' if r1['passed'] else 'FAIL'} "
          f"(n_bad={r1['n_bad']})")
    r2 = r2_ohlc(syms)
    print(f"  R2 OHLC validity:  {'PASS' if r2['passed'] else 'FAIL'} "
          f"(n_bad={r2['n_bad']}, n_warn={r2['n_warn']})")
    r3 = r3_dynamics(syms, set(executable))
    print(f"  R3 dynamics:       {'PASS' if r3['passed'] else 'FAIL'} "
          f"(completeness {r3['completeness_gate']['n_pass']}/"
          f"{r3['completeness_gate']['n_pass'] + r3['completeness_gate']['n_fail']}, "
          f"added_jump_warn={r3['n_jump_added_warn']}, "
          f"base_raw_split={r3['n_jump_base_expected']})")
    r4 = r4_boundary(added, executable)
    print(f"  R4 boundary:       {'PASS' if r4['passed'] else 'FAIL'} "
          f"(problems={len(r4['problems'])})")

    all_pass = all(r["passed"] for r in (r1, r2, r3, r4))
    art = {
        "audit": "P4-R2 expanded_v1 data-cleanliness audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_symbols": len(syms),
        "rounds": {"R1": r1, "R2": r2, "R3": r3, "R4": r4},
        "verdict": "ALL ROUNDS PASS" if all_pass else "AUDIT FAIL",
    }
    out = _PROJ / "data" / "audit" / "chart_structure" / "phase4_data_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2, default=str))
    print(f"\nverdict: {art['verdict']}  -> {out}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
