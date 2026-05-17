# Supplementary PRD —— chart-native / ML 按 literature-proven 路径重做

**日期**: 2026-05-16
**状态**: v1 —— 待用户 explicit-go 后启动。
**作者**: resident quant operator
**触发**: 用户质疑 Phase 3 是 naive 尝试而非 literature 路径;要求
websearch → supplementary PRD → 重做。
**SoT(文献基线)**: `docs/memos/20260516-ml_methodology_literature_review.md`
(Step1-5,17 来源 [S1-S15],全程未触 sealed)
**关联**: 主 PRD `docs/prd/20260515-chart_structure_input_representation_prd.md`
(本 PRD 取代其 Phase 3 的执行方法,Phase 1/2A/2B/4 基础设施保留)
**Lineage tag**: `ml-method-redo-2026-05-16`

> 使用方式同 PQS 惯例:每 Phase = 「Spec(可 implement)」+「Acceptance
> (可审计,编号即 checklist,标 Tier-M 机器可检 / Tier-H 人工复核)」。
> 全程守 §7 cross-cutting 纪律。

---

## §1 TL;DR

Phase 2A(family T incremental-IC)严谨、负结论可信,**不重做**。Phase 3
(3A/3B/3C)是从零监督小模型 = literature 明确预测会失败的 regime,
**其负结果作废(superseded,git 留痕),按本 PRD 重做**。重做 = 把
literature-proven 的 6 层(数据准备 / label / 验证 / 自监督预训练 /
chart-native+树基线 / ensemble)落成可执行规格,每层独立可验收。

**核心纪律**:旧 Phase 3 数字**不按 naive 方法重跑**(复现一个文献早
预测的"没结果"无价值);redo 用新管线产出**权威值**取代。sealed 2026
全程不读;mining panel 走 `partition_for_role(role="miner")`。

---

## §2 范围 / 不变量

**重做**:Phase 3 chart-native(3A/3B/3C)+ 新增数据准备/label/验证/
SSL/ensemble 层。
**保留不动**:Phase 1 family T 因子库、Phase 2A incremental-IC 结论、
Phase 2B SSL infra(TS2Vec/MiniROCKET/corpus manifest)、Phase 4
universe + `--universe` 全链路、temporal_split canonical 纪律、本会话
6 commit 的所有修复。
**不变量(违反需用户 explicit-go)**:
- sealed 2026 single-shot 全程**不读**(`fail_closed_if_2026_row_in_train_panel`)。
- mining/research panel 走 `partition_for_role(role="miner")` = train-only。
- 失败 attempt 只写 config-scoped + root_cause,**禁 blanket verdict**(D2)。
- 所有数字进对外结论前按主 PRD §C provenance 登记来源。
- websearch 仅方法/论文;禁当前年市场表现数据。

---

## §3 Phase R0 —— 数据准备 / 清洗层(literature §1.A)

### Spec
新模块 `core/ml/feature_prep.py`,在因子面板进任何模型**前**统一做(可
配置开关,`config/ml_feature_prep.yaml`):
1. **横截面 rank 归一化**:逐 rebalance 日,全 universe 按因子值排名 →
   [0,1] 百分位;**逐切片动态算**(防 look-ahead)。[S12]
2. **Winsorize**:1/99 百分位 hard-cap(阈值配置)。[S12]
3. **Sector-neutralization**:回归掉 GICS 行业均值(用 Phase 2B
   `config/sector_map.yaml` PIT sector);**vol-scaling**(按 trailing
   vol 缩放)。[S12]
4. **Fractional differentiation**(opt-in,默认 off):对价格序列找最小
   d 使 ADF 平稳,保留记忆;作为 raw/log-return 之外的可选输入。[S5][S9]
   阈值/d-grid 进 yaml,默认值标 PLACEHOLDER 待标定(§C 纪律)。

### Deliverables
| # | 产物 |
|---|---|
| R0-d1 | `core/ml/feature_prep.py`(rank-norm / winsorize / sector-neutral / vol-scale / frac-diff)|
| R0-d2 | `config/ml_feature_prep.yaml`(全阈值,无 hardcode)|
| R0-d3 | 单测覆盖 R0-A1..A4 |

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R0-A1 | rank-norm 逐日截面、值 ∈[0,1]、**因果**(截断面板算 t 日 == 全面板算 t 日)| `test_feature_prep_ranknorm_causal` | M |
| R0-A2 | winsorize 后无值超出 [p1,p99];阈值取自 yaml 非 hardcode | `test_feature_prep_winsorize` + `test_feature_prep_config_sourced` | M |
| R0-A3 | sector-neutral 后行业内均值≈0;sector 用 PIT(无未来重分类泄漏)| `test_feature_prep_sector_neutral_pit` | M |
| R0-A4 | frac-diff:输出通过 ADF 平稳 + d 最小性 + opt-in 默认 off 时面板 bit-identical | `test_feature_prep_fracdiff` | M |

---

## §4 Phase R1 —— Label 层(literature §1.B)

### Spec
`core/ml/labeling.py`:
1. **Sample-uniqueness / concurrency 加权**(HARD,所有 redo 训练必用):
   算每样本生命周期内并发标签数 → 平均唯一度(并发倒数均值)→ 作
   sample_weight(独立样本→1,完全重叠→0);bagging 时
   `max_samples=avg_uniqueness`。[S5][S8]
2. **Triple-barrier label**(评估用,与裸 21d fwd return 对比):上/下/
   竖障 → {+1,0,−1};障宽用 trailing vol 比例,配置化。[S5][S8]
3. 裸 21d fwd return 保留为对照 label(不删,做 A/B)。

### Deliverables
R1-d1 `core/ml/labeling.py`;R1-d2 `config/ml_labeling.yaml`;R1-d3 单测。

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R1-A1 | concurrency 加权:独立样本权重=1、完全重叠→0;数值手算对拍 | `test_labeling_uniqueness_weight` | M |
| R1-A2 | triple-barrier:已知路径手算 label 对拍;障宽取自 yaml | `test_labeling_triple_barrier` | M |
| R1-A3 | 因果:label 只用 [t, t+horizon] 内 bar,无未来泄漏 hard test | `test_labeling_causal` | M |

---

## §5 Phase R2 —— 验证层(literature §1.C;升级年块为 CPCV)

### Spec
`core/research/cpcv.py`:
1. **Purged + embargo k-fold**:purge = 删 label 形成期与 test 重叠的训练
   样本(前后都删);embargo = test 后删 ~1%(配置)观测,**只 test 后**。[S6][S11]
2. **CPCV**:N 连续不重叠组,所有 C(N,k) 组合做 test,产 OOS 分布 +
   φ[N,k]=(k/N)·C(N,k) 条回测路径。[S6][S10]
3. **过拟合度量**:每个 redo attempt 报 **Deflated Sharpe Ratio**(输入
   试验次数 n_trials + 偏度峰度)+ **PBO**。[S13][S14]
4. **强约束**:CPCV 只在 `partition_for_role(role="miner")` 产的
   **train-only panel** 上跑;validation/sealed 永不进。沿用本会话
   `validate_no_holdout_leakage` fail-closed。

### Deliverables
R2-d1 `core/research/cpcv.py`;R2-d2 DSR/PBO 计算 `core/research/overfit_metrics.py`;
R2-d3 单测(含 train-only fail-closed 回归)。

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R2-A1 | purge 删对样本(label 重叠 test 的训练样本全删)+ embargo 只 test 后 | `test_cpcv_purge_embargo` | M |
| R2-A2 | CPCV split 数 = C(N,k)、路径数 = φ[N,k];小例手算对拍 | `test_cpcv_paths` | M |
| R2-A3 | DSR/PBO 公式对已知输入对拍;n_trials 必填 | `test_overfit_metrics` | M |
| R2-A4 | CPCV panel 含 validation/sealed 行 → fail-closed raise | `test_cpcv_train_only_fail_closed` | M |

---

## §6 Phase R3 —— 自监督预训练(literature §1.D;Phase3 跳过的核心)

### Spec
复用 Phase 2B `core/ml/window_embedding.py`(TS2Vec)+ 新增 **MAE
(segment-wise masking)** encoder:
1. 在 `chart_structure_pretrain_corpus_v1`(train-only,Phase2B 已冻结)
   上**无标签预训练** TS2Vec + MAE。[S2]
2. 下游用 **linear-probe**(冻结 encoder + 线性头)+ **fine-tune**
   两种协议,小标签量。[S2]
3. TS 专属增广(jitter / permutation / segment-mask);**禁 CV/NLP
   增广**(rotation/crop 破坏时序)。[S2]
4. 借《Contrastive Asset Embeddings》噪声鲁棒正负对思想(共现 top-k
   比例假设检验)作为 TS2Vec 正负对的金融适配选项。[S4]

### Deliverables
R3-d1 MAE encoder + segment-mask;R3-d2 linear-probe / fine-tune harness;
R3-d3 TS 增广模块;R3-d4 预训练 run + checkpoint(corpus_manifest_id 记录)。

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R3-A1 | 预训练语料 = train-only(`train_years_only=true`,no sealed)| `test_pretrain_corpus_no_holdout`(复用 Phase2B P2-A5)| M |
| R3-A2 | MAE segment-mask 因果 + smoke 预训练 loss 下降 | `test_mae_encoder` | M |
| R3-A3 | linear-probe / fine-tune harness 跑通 smoke + 增广是 TS 专属(无 rotation/crop)| `test_pretrain_finetune_harness` | M |
| R3-A4 | 下游 attempt JSON 记 `pretrain_method` / `corpus_manifest_id` / `probe_or_finetune` | schema 校验 | M |

---

## §7 Phase R4 —— chart-native 重做 + 树基线(literature §1.E)

### Spec
在 R0→R1→R2→R3 管线上重做 chart-native:
1. **3A/3B/3C redo**:输入走 R0 预处理 + R1 加权 label;encoder 走 R3
   预训练→fine-tune(不再从零);评估走 R2 CPCV + DSR/PBO。
2. **GAF + 树基线(新增,literature 明示常反超从零 CNN)**:GASF/GADF
   特征 → XGBoost/LightGBM,与 3A 同裁判对比。[S7]
3. 每 attempt 一份 `data/audit/ml_redo/attempt_<id>.json`(扩 Phase3
   schema:加 pretrain / data_prep / cpcv / dsr / pbo 字段);失败必
   root_cause + config-scoped(D2)。

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R4-A1 | 每 attempt JSON 字段完整(含 pretrain/data_prep/cpcv/dsr/pbo)| `test_ml_redo_attempt_schema` | M |
| R4-A2 | 评估走 R2 CPCV + DSR/PBO(非裸 IC、非年块)| eval JSON 必有 `cpcv`/`deflated_sharpe`/`pbo` 字段 | M |
| R4-A3 | vs tabular baseline(动量)+ vs GAF-tree 双对比报出 | closeout `vs_tabular_baseline` + `vs_gaf_tree` 数值块 | M |
| R4-A4 | 失败 attempt root_cause 非空 + verdict_scope=config_scoped;无 blanket | schema + 人工复核 | H |
| R4-A5 | 旧 Phase3 三 JSON 标 `superseded_by=ml-method-redo-2026-05-16` | 文件标记 | M |

---

## §8 Phase R5 —— Ensemble(literature §1.F;主 PRD §5.2 定位兑现)

### Spec
`core/ml/stacking.py`:
1. **Stacking + out-of-fold**:base = {动量等表格因子模型, chart-native
   redo, 其它弱信号};base 的 **CPCV-OOF 预测**当 meta-feature;
   **meta-model = Ridge**(简单,抗 base 间相关过拟合)。[S15a][S15b]
2. 验证 chart-native 作为**弱但正交**信号 stack 进去是否产生边际增量
   (即便单挑输动量);走 R2 CPCV + DSR/PBO + NAV 相关性(anti-sibling)。
3. 结论 config-scoped;ensemble 候选要进 fleet 仍走主 PRD §7.2 三条 +
   G3 anti-sibling(不因 ensemble 豁免)。

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R5-A1 | OOF 用 CPCV(无 in-fold 泄漏);meta=Ridge | `test_stacking_oof_cpcv` | M |
| R5-A2 | ensemble vs 单 base 增量 + DSR/PBO 报出;chart-native 边际贡献量化 | closeout 数值块 | M |
| R5-A3 | ensemble 候选若提名 fleet,过主 PRD §7.2 + G3(无豁免)| `nominee_gate` 检查(有 consumer 时)| M |

---

## §9 Cross-cutting 纪律(全程)

1. **sealed 2026 不读**;mining panel `partition_for_role(role="miner")`
   + `validate_no_holdout_leakage` fail-closed(本会话已立)。
2. **CPCV/验证只在 train-only panel**;旧 Phase3 数字 superseded 不按
   naive 重跑。
3. 每 round:命名单测 + 全量 G1 → commit/push(specific files)→ loop
   log 11-part → 4-tier 自审。
4. 失败 = config-scoped + root_cause,**禁 blanket**(D2;Phase1.5→1.6
   先例)。
5. 数字进对外结论前 §C provenance 登记;PLACEHOLDER 阈值标"待标定"。
6. websearch(若再需)仅方法/论文,禁当前年市场数据。
7. D6 universe 隔离 + `--universe` 全链路传播(本会话已立)继续适用。

---

## §10 执行顺序 + fire trigger

```
R0 数据准备 ──┐
R1 label    ──┼─→ R2 验证层 ─→ R3 SSL 预训练 ─→ R4 chart-native redo ─→ R5 ensemble
(R0/R1 可并行,都只 dep 现有 infra;R2 dep R1 label horizon;
 R3 dep Phase2B infra;R4 dep R0+R1+R2+R3;R5 dep R4)
```
- Fire R0/R1:用户 explicit-go 本 PRD 后立即。
- Fire R4:R0-A*/R1-A*/R2-A*/R3-A* 全过。
- Fire R5:R4 产出 ≥1 个非 superseded attempt。
- 每 Phase closeout memo + termination promise
  `MLREDO-R0-DONE`..`-R5-DONE`;全完 → `MLREDODONE`。

---

## §11 验收总表(PRD 级)

| # | 项 | 验收 | Tier |
|---|---|---|---|
| G1 | 每 commit 后全量 pytest green | CI | M |
| G2 | 每 Phase closeout + per-attempt JSON schema | 文件 + schema | M |
| G3 | 失败 config-scoped 无 blanket | 人工 + `verdict_scope`/`root_cause` 字段 | H |
| G4 | sealed 2026 全程未读 | `fail_closed_if_2026_row_in_train_panel` + grep panel 范围 | M |
| G5 | CPCV/train-only 纪律 | R2-A4 fail-closed 回归 | M |
| G6 | 旧 Phase3 superseded 标记 + 不 naive 重跑 | R4-A5 文件标记 | M |
| G7 | 所有阈值 config 化无 hardcode | `test_*_config_sourced` + grep | M |
| G8 | 每条 proven 路径可追溯到 literature review [S#] | PRD↔memo 交叉引用 | H |

---

## §12 启动

本 PRD v1 → **用户 explicit-go** 后从 R0/R1 起逐 Phase 执行(operator
不自启 autonomous loop;ralph-loop execution 切分另出 execution PRD 或
按本 PRD §10 顺序直接做)。lineage `ml-method-redo-2026-05-16`;loop log
复用 `docs/memos/20260515-chart_structure_loop_log.md`(新 lineage tag 段)。
