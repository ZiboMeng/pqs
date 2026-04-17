# Factor Candidate Research Funnel

## 最小闭环流程

```
1. 生成候选 (LLM 或人工)
   → 填写 YAML schema (见下方模板)
   → 保存到 data/factor_candidates/NNN_name.yaml

2. 去重检查
   → 计算与现有因子的相关性 (threshold: 0.7 触发审查)
   → 工具: python scripts/run_factor_screen.py

3. IC 筛选
   → Rank IC + IR + p-value
   → 工具: python scripts/run_factor_screen.py --horizon 5 10 21

4. OOS 验证
   → Walk-forward IC 稳定性 (至少 2/4 子期正 IC)

5. 决策
   → KEEP: 更新 YAML status=keep, 考虑加入 MultiFactorStrategy
   → REJECT: 更新 YAML status=reject + rejection_reason
   → ARCHIVE: 更新 YAML status=archive (有潜力但当前不适用)
```

## YAML 模板

```yaml
factor_name: ""
hypothesis: ""
formula: ""
required_fields: []
suitable_horizon: []
suitable_universe: ""
suitable_regime: []
expected_edge: ""
expected_risk: ""
possible_failure_modes: []
novelty_vs_existing: ""

status: candidate  # candidate | research | validation | keep | reject | archive
created_by: LLM    # LLM | manual
created_date: ""
dedup_check: false
dedup_max_corr: null
leakage_check: false
ic_screen: null
oos_validation: null
regime_robustness: null
rejection_reason: null
decision_date: null
```

## 反向审查清单 (进入 KEEP 前必须通过)

- [ ] 不是已有因子的改名
- [ ] 相关性 > 0.7 时有增量价值说明
- [ ] ≥ 3/6 regime 下 IC 为正
- [ ] 不集中于单一时期 (< 60% IC 来自一个 quartile)
- [ ] 2x 成本压力测试存活
- [ ] 不只对 < 5 个标的有效
- [ ] 不是 timing/selection/survivorship bias 的伪装

## 限制

当前为手动流程。自动化因子漏斗管道（batch candidate → screen → validate → archive）是后续改进方向。
