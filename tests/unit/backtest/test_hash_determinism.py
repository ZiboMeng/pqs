"""M11a hash-determinism test — set iteration order in BacktestEngine.

`BacktestEngine._generate_orders` iterates `set(...)` which depends on
Python's per-process hash randomization (PYTHONHASHSEED). Two runs of
the same code on the same data in different processes can iterate
symbols in different order. With a binding cash budget, the order in
which BUY/SELL orders are fitted into available cash is observable in
the resulting fills and equity curve — producing a monotone-signed
paper-vs-replay drift artifact.

This test runs an identical backtest in two subprocesses with different
PYTHONHASHSEED env vars and asserts the resulting equity curves and
fills are byte-identical.

Pre-M11a-fix this test would FAIL with non-trivial probability (the
unsorted set iteration order varies across hash seeds when the cash
budget bites). Post-fix (`sorted(set(...))`) it MUST pass.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


_HARNESS = textwrap.dedent(
    """
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, %r)

    import numpy as np
    import pandas as pd

    from core.backtest.backtest_engine import BacktestEngine
    from core.config.loader import load_config
    from core.execution.cost_model import CostModel

    cm = CostModel(load_config(Path('config')).cost_model)

    # 8 symbols whose names produce DIFFERENT hash orderings under
    # different PYTHONHASHSEEDs (verified empirically). Designed so the
    # full target portfolio exceeds available cash → integer-share
    # rounding asymmetry surfaces if iteration order varies.
    syms = ['SYM_AAA', 'SYM_BBB', 'SYM_CCC', 'SYM_DDD',
            'SYM_EEE', 'SYM_FFF', 'SYM_GGG', 'SYM_HHH']

    idx = pd.bdate_range('2024-01-02', periods=8)
    rng = np.random.default_rng(42)
    closes = pd.DataFrame(
        {s: 100.0 + rng.standard_normal(len(idx)).cumsum()
         for s in syms},
        index=idx,
    )
    opens = closes.copy()
    # Equal-weight target with a binding cash constraint via integer shares
    sig = pd.DataFrame({s: 0.125 for s in syms}, index=idx)

    eng = BacktestEngine(
        cost_model=cm,
        initial_capital=10_000.0,
        integer_shares=True,
        stale_days_threshold=10,
    )
    res = eng.run(signals_df=sig, price_df=closes, open_df=opens)

    out = {
        'equity': [round(float(x), 8) for x in res.equity_curve.values],
        'cash':   [round(float(x), 8) for x in res.cash_curve.values],
        'fills':  [
            {
                'symbol': f.symbol,
                'side':   f.side.value,
                'qty':    round(float(f.executed_qty), 8),
                'price':  round(float(f.executed_price), 8),
                'fill_date': str(f.fill_date.date()),
            }
            for f in res.trades
        ],
    }
    print(json.dumps(out, sort_keys=True))
    """
)


def _run_with_seed(seed: str) -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        [sys.executable, "-c", _HARNESS % str(repo_root)],
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        cwd=str(repo_root),
        capture_output=True, text=True, check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"subprocess failed (seed={seed}): {proc.stderr[-2000:]}"
        )
    # The harness prints a single JSON line; ignore any logger output above.
    last_line = [l for l in proc.stdout.splitlines() if l.startswith("{")][-1]
    return json.loads(last_line)


def test_backtest_deterministic_across_pythonhashseed():
    """Same code + same data in two processes with PYTHONHASHSEED=0 vs
    PYTHONHASHSEED=1 must produce byte-identical equity curves and fills."""
    out_a = _run_with_seed("0")
    out_b = _run_with_seed("1")

    assert out_a["equity"] == out_b["equity"], (
        f"Equity curve drifted across hash seeds — set iteration is "
        f"not deterministic.\nseed=0: {out_a['equity']}\nseed=1: {out_b['equity']}"
    )
    assert out_a["cash"] == out_b["cash"], (
        f"Cash curve drifted across hash seeds.\n"
        f"seed=0: {out_a['cash']}\nseed=1: {out_b['cash']}"
    )
    assert out_a["fills"] == out_b["fills"], (
        f"Fills drifted across hash seeds (n_a={len(out_a['fills'])}, "
        f"n_b={len(out_b['fills'])})."
    )
