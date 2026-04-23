# LLM Proposal Seed Context (PRD M6 Phase 1)

Before asking an LLM to propose new candidate factors, inject the
following 5 sections of current repo state so the LLM doesn't reinvent
existing factors or violate constraints.

**How to collect**: run the commands below and paste output into the
LLM conversation.

---

## Section 1: PRODUCTION_FACTORS set (currently executed)

```bash
/home/zibo/miniconda3/envs/pqs/bin/python -c "
from core.factors.factor_registry import PRODUCTION_FACTORS
for f in sorted(PRODUCTION_FACTORS):
    print(f)
"
```

**Expected**: 7 factors — `low_vol`, `momentum`, `quality`, `pv_div`,
`rel_strength`, `market_trend`, `drawup_from_252d_low`.

**Instruction to LLM**: any proposed candidate that is a near-duplicate
of these must explicitly explain **incremental** value (e.g. sign-flip,
timescale variant, regime conditioning).

## Section 2: RESEARCH_FACTORS set (available but not promoted)

```bash
/home/zibo/miniconda3/envs/pqs/bin/python -c "
from core.factors.factor_registry import RESEARCH_FACTORS
for f in sorted(RESEARCH_FACTORS):
    print(f)
"
```

**Expected**: 39 factors covering momentum / vol / reversal / quality /
price-volume / cross-sectional / intraday families.

**Instruction to LLM**: candidates that are a thin variant of an
existing RESEARCH_FACTOR should note ρ estimate and why the variant
might add value.

## Section 3: Last rejected / archived candidates

```bash
ls research/llm_candidates/*/ 2>/dev/null | tail -20
find data/ml/llm_candidates -name verdict.json 2>/dev/null | \
  xargs -I{} sh -c 'echo "=== {} ==="; jq "{verdict, factor_name, reason}" {}' | head -80
```

**Instruction to LLM**: read these 5+ recent verdicts; **do not** repropose
factors whose verdict was REJECT for the same reason.

## Section 4: Current universe composition

```bash
/home/zibo/miniconda3/envs/pqs/bin/python -c "
import yaml
u = yaml.safe_load(open('config/universe.yaml').read())
print('seed_pool (', len(u['seed_pool']), '):', u['seed_pool'])
print('sector_etfs (', len(u['sector_etfs']), '):', u['sector_etfs'])
print('factor_etfs (', len(u['factor_etfs']), '):', u['factor_etfs'])
print('cross_asset (', len(u['cross_asset']), '):', u['cross_asset'])
"
```

**Instruction to LLM**: universe is currently 53 tradable symbols. If
proposing a cross-sectional factor, consider: is the universe wide
enough for this factor's CS rank to be meaningful? (e.g., ranking
within 53 symbols has more noise than within 500).

## Section 5: Current regime mix

```bash
/home/zibo/miniconda3/envs/pqs/bin/python -c "
import sys
sys.path.insert(0, '.')
from core.data.market_data_store import MarketDataStore
from core.data.vix_loader import load_vix_series
from core.regime.regime_detector import RegimeDetector
from core.config.loader import load_config
from pathlib import Path
import pandas as pd

cfg = load_config(Path('config'))
store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
spy = store.read('SPY', '1d')['close'].tail(252)
vix = load_vix_series(store, spy.index, mode='lenient')
detector = RegimeDetector(cfg.regime)
regime = detector.classify_series(spy, vix)
print(regime.value_counts().sort_index())
"
```

**Instruction to LLM**: if current 252d is dominated by one regime
(e.g. 90% BULL), don't propose factors that only work in a rare regime
(e.g. CRISIS-only) unless you explicitly flag in suitable_regime.

---

## How to use

When starting a new LLM-round:

1. Run all 5 commands above, paste output into the conversation.
2. Paste `docs/20260421-llm_proposal_prompt_template.md` system prompt.
3. State the direction you want the LLM to explore (e.g. "propose 3
   intraday-momentum-interaction candidates for tech-heavy regime").
4. Receive YAML candidates.
5. Run funnel per `docs/20260421-llm_funnel_checklist.md`.
6. Human review → promote / archive / reject.

## Minimum context age

Re-collect seed context at the START of every new round. Stale seed
→ LLM reproposes factors that were already rejected.

## Phase 2 automation

If conversation overhead becomes a bottleneck, a future
`scripts/llm_propose_round.py` could:
- auto-collect sections 1-5
- inject into a structured API call (Anthropic messages endpoint)
- receive structured YAML candidates
- write to `research/llm_candidates/round_NN/*.yaml`

Don't build this until you've run 10+ manual rounds and can point to
specific friction the automation would remove.
