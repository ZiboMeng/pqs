#!/usr/bin/env python
"""Build research baseline snapshot for PQS.

PRD: docs/20260421-prd_framework_completion.md M0 — replaces hardcoded test counts /
lineage summaries / config assertions in documentation with a machine-readable
snapshot that can be re-generated on demand.

Writes JSON with:
  - git SHA / branch / dirty state
  - pytest collection count (fast; --run-tests to also run full suite)
  - mining archive per-lineage stats
  - config YAML sha256 hashes
  - factor registry hashes (PRODUCTION / RESEARCH / MAP)
  - python + key package versions
  - production strategy status (if config/production_strategy.yaml exists — M1)

Output:
  data/baseline/snapshot_<ts>.json  — timestamped snapshot
  data/baseline/latest.json         — copy of newest snapshot for convenient reference
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str, str]:
    """Run command, return (rc, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(
            cmd, cwd=cwd or ROOT, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:  # pragma: no cover — defensive
        return -1, "", f"{type(exc).__name__}: {exc}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def collect_git() -> dict:
    rc1, sha, _ = _run(["git", "rev-parse", "HEAD"])
    rc2, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    rc3, status, _ = _run(["git", "status", "--porcelain"])
    rc4, subj, _ = _run(["git", "log", "-1", "--pretty=%s"])
    lines = [l for l in status.splitlines() if l.strip()]
    return {
        "head_sha": sha.strip() if rc1 == 0 else None,
        "branch": branch.strip() if rc2 == 0 else None,
        "head_subject": subj.strip() if rc4 == 0 else None,
        "dirty": bool(lines),
        "n_changed_files": len(lines),
        "changed_files": lines[:50],  # cap to avoid giant snapshot
    }


def collect_tests(run_full: bool) -> dict:
    """Fast path: pytest --collect-only for count (~1.5s).
    Full path (--run-tests): actual pytest -q (~10 min on 3000+ tests)
    to capture pass/fail. Timeout 1200s; if exceeded, `run_error`
    field is populated (no silent "not run" misleading state)."""
    out: dict = {"collected": None, "passed": None, "failed": None,
                 "skipped": None, "xfailed": None, "duration_sec": None,
                 "run_error": None}
    # Fast collect
    rc, so, _ = _run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header"],
        timeout=60,
    )
    if rc == 0:
        import re
        for line in so.splitlines():
            # matches both "1109 tests collected" and "====== 1109 tests collected in 1.57s ======"
            m = re.search(r"(\d+)\s+tests?\s+collected", line)
            if m:
                out["collected"] = int(m.group(1))
                break

    if run_full:
        # 1200s timeout: full unit+integration suite at 3167 tests takes
        # ~640s on dev hardware; 1200s gives comfortable margin for slow
        # CI nodes without making timeout silent failure too long-lived.
        rc, so, se = _run([sys.executable, "-m", "pytest", "-q", "--tb=no"],
                           timeout=1200)
        import re
        summary_parsed = False
        # Parse last summary line like "1109 passed, 3 warnings in 97.12s (0:01:37)"
        for line in so.splitlines()[::-1]:
            s = line.strip()
            if " passed" in s or " failed" in s:
                for key in ["passed", "failed", "skipped", "xfailed"]:
                    m = re.search(rf"(\d+) {key}", s)
                    if m:
                        out[key] = int(m.group(1))
                m2 = re.search(r"in ([\d.]+)s", s)
                if m2:
                    out["duration_sec"] = float(m2.group(1))
                summary_parsed = True
                break
        if not summary_parsed:
            # Surface explicit error so caller does NOT see misleading
            # "not run" message. Captures rc + last 200 chars of stderr.
            tail_err = (se[-200:] if se else "").strip()
            out["run_error"] = (
                f"pytest summary not parsed (rc={rc}). "
                f"Possibly timed out at 1200s or pytest crashed. "
                f"stderr tail: {tail_err!r}"
            )
    return out


def collect_archive() -> dict:
    """Mining archive per-lineage summary."""
    try:
        from core.mining.archive import MiningArchive
    except Exception as exc:
        return {"error": f"import failed: {exc}"}
    try:
        a = MiningArchive()
        lb = a.leaderboard(n=10000)  # upper bound
    except Exception as exc:
        return {"error": f"leaderboard load failed: {exc}"}
    if lb is None or lb.empty:
        return {"total_trials": 0, "lineages": {}}

    lineages: dict = {}
    for lt, grp in lb.groupby("lineage_tag"):
        oos_ir = grp.get("oos_ir")
        lineages[str(lt)] = {
            "n_trials": int(len(grp)),
            "n_quick_pass": int(grp.get("passed_quick", False).fillna(False).astype(bool).sum()) if "passed_quick" in grp.columns else None,
            "n_oos_pass": int(grp.get("passed_oos", False).fillna(False).astype(bool).sum()) if "passed_oos" in grp.columns else None,
            "n_qqq_gate_pass": int(grp.get("passed_qqq_gate", False).fillna(False).astype(bool).sum()) if "passed_qqq_gate" in grp.columns else None,
            "best_oos_ir": float(oos_ir.max()) if oos_ir is not None and not oos_ir.empty else None,
            "worst_oos_ir": float(oos_ir.min()) if oos_ir is not None and not oos_ir.empty else None,
        }

    try:
        promoted = a.get_promoted()
        promoted_ids = [p.spec_id for p in promoted] if promoted else []
    except Exception:
        promoted_ids = []

    return {
        "total_trials": int(len(lb)),
        "n_lineages": len(lineages),
        "lineages": lineages,
        "promoted_spec_ids": promoted_ids,
    }


def collect_config_hashes() -> dict:
    hashes: dict = {}
    for p in sorted((ROOT / "config").glob("*.yaml")):
        hashes[p.name] = _sha256_file(p)
    return hashes


def collect_factor_registry() -> dict:
    try:
        from core.factors.factor_registry import (
            PRODUCTION_FACTORS, RESEARCH_FACTORS, RESEARCH_TO_PRODUCTION_MAP,
        )
    except Exception as exc:
        return {"error": f"import failed: {exc}"}
    prod = sorted(PRODUCTION_FACTORS)
    res = sorted(RESEARCH_FACTORS)
    mp_items = sorted(RESEARCH_TO_PRODUCTION_MAP.items())
    return {
        "production_factors": prod,
        "production_count": len(prod),
        "production_hash": _sha256_str("|".join(prod)),
        "research_factors": res,
        "research_count": len(res),
        "research_hash": _sha256_str("|".join(res)),
        "map_count": len(mp_items),
        "map_hash": _sha256_str("|".join(f"{k}->{v}" for k, v in mp_items)),
    }


def collect_python_env() -> dict:
    info: dict = {"version": sys.version.split()[0], "executable": sys.executable}
    pkgs: dict = {}
    for name in ["pandas", "numpy", "scipy", "sklearn", "xgboost", "optuna",
                 "pydantic", "yaml", "pyarrow", "yfinance"]:
        try:
            mod = __import__(name)
            pkgs[name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            pkgs[name] = None
    info["packages"] = pkgs
    return info


def collect_production_strategy() -> dict:
    """Read config/production_strategy.yaml if M1 has landed; else return stub."""
    p = ROOT / "config" / "production_strategy.yaml"
    if not p.exists():
        return {"exists": False, "note": "M1 not yet landed; no production strategy artifact"}
    try:
        import yaml  # noqa: WPS433
        cfg = yaml.safe_load(p.read_text())
    except Exception as exc:
        return {"exists": True, "parse_error": str(exc)}
    return {
        "exists": True,
        "status": cfg.get("status"),
        "strategy_type": cfg.get("strategy_type"),
        "source": cfg.get("source"),
        "validation": cfg.get("validation"),
        "fingerprints_present": bool(cfg.get("fingerprints")),
        "hash_of_yaml": _sha256_file(p),
    }


def collect_universe() -> dict:
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    except Exception as exc:
        return {"error": str(exc)}
    counts = {}
    for key in ["seed_pool", "sector_etfs", "factor_etfs", "cross_asset", "macro_reference", "blacklist"]:
        v = cfg.get(key, [])
        if isinstance(v, list):
            counts[key] = len(v)
    tradable = []
    for key in ["seed_pool", "sector_etfs", "factor_etfs", "cross_asset"]:
        v = cfg.get(key, [])
        if isinstance(v, list):
            tradable.extend(v)
    tradable = sorted(set(tradable))
    return {
        "counts": counts,
        "tradable_count": len(tradable),
        "tradable_hash": _sha256_str("|".join(tradable)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PQS research baseline snapshot (PRD §M0)")
    parser.add_argument("--run-tests", action="store_true",
                        help="Also run full pytest -q (slow, ~90s). Default: only collect count (~1.5s).")
    parser.add_argument("--out-dir", default="data/baseline", help="Output directory")
    parser.add_argument("--stdout", action="store_true",
                        help="Also print JSON to stdout")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = {
        "schema_version": "1.0",
        "timestamp": ts,
        "git": collect_git(),
        "tests": collect_tests(run_full=args.run_tests),
        "archive": collect_archive(),
        "config_hashes": collect_config_hashes(),
        "factor_registry": collect_factor_registry(),
        "universe": collect_universe(),
        "python_env": collect_python_env(),
        "production_strategy": collect_production_strategy(),
    }

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    snap_path = out_dir / f"snapshot_{ts}.json"
    latest_path = out_dir / "latest.json"
    snap_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    shutil.copy(snap_path, latest_path)

    if args.stdout:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        # brief summary to stdout
        print(f"Baseline snapshot written:")
        print(f"  {snap_path}")
        print(f"  {latest_path}")
        print(f"Git HEAD: {snapshot['git']['head_sha'][:12] if snapshot['git']['head_sha'] else 'UNKNOWN'}"
              f" ({'dirty' if snapshot['git']['dirty'] else 'clean'})")
        t = snapshot["tests"]
        if t["collected"] is not None:
            if t["passed"] is not None:
                print(f"Tests: {t['passed']} passed / {t['failed'] or 0} failed / {t['skipped'] or 0} skipped"
                      f" / {t['xfailed'] or 0} xfailed  (collected={t['collected']}, {t['duration_sec']}s)")
            elif t.get("run_error"):
                # --run-tests was attempted but failed/timed out — surface
                # the error rather than print misleading "not run" message.
                print(f"Tests: collected={t['collected']}; ERROR running full suite — {t['run_error']}")
            else:
                print(f"Tests: collected={t['collected']} (not run; use --run-tests to execute)")
        fr = snapshot["factor_registry"]
        if "production_count" in fr:
            print(f"Factor registry: {fr['production_count']} PROD / {fr['research_count']} RESEARCH / {fr['map_count']} MAP")
        uv = snapshot["universe"]
        if "tradable_count" in uv:
            print(f"Universe: {uv['tradable_count']} tradable symbols")
        arc = snapshot["archive"]
        if "total_trials" in arc:
            print(f"Archive: {arc['total_trials']} trials across {arc.get('n_lineages', 0)} lineages"
                  f" ({len(arc.get('promoted_spec_ids', []))} promoted)")
        ps = snapshot["production_strategy"]
        print(f"Production strategy: exists={ps.get('exists')} status={ps.get('status')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
