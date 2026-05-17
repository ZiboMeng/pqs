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

Phase 2A 比 naive 好(rank+边界 purge)但**仍非 literature-grade**(缺
sample-uniqueness 加权/sector-neutral/winsorize/CPCV/DSR——operator 上一轮
"不重做"判断已纠正,见 §5.5/§13),其"family T 无增量"地基结论须在
**R2.5 复检**(R4 前)。Phase 3(3A/3B/3C)是从零监督小模型 = literature
明确预测会失败的 regime,
**其负结果作废(superseded,git 留痕),按本 PRD 重做**。重做 = 把
literature-proven 的 6 层(数据准备 / label / 验证 / 自监督预训练 /
chart-native+树基线 / ensemble)落成可执行规格,每层独立可验收。

**核心纪律**:旧 Phase 3 数字**不按 naive 方法重跑**(复现一个文献早
预测的"没结果"无价值);redo 用新管线产出**权威值**取代。sealed 2026
全程不读;mining panel 走 `partition_for_role(role="miner")`。

---

## §2 范围 / 不变量

**重做 / 复检**:Phase 3 chart-native(3A/3B/3C)redo + **Phase 2A 地基
复检(R2.5)** + **Phase 2B 表征全量预训练 + 下游 IC(R3+R2.5-b,从未
跑过)** + **Phase 4 universe 规模审计(R-P4ext,~1k)** + 新增数据准备/
label/验证/SSL/ensemble 层。
**保留不动**:Phase 1 family T 因子库(特征本身,causal 已硬测)、
Phase 2B SSL **模块代码**(TS2Vec/MiniROCKET/corpus manifest 不重写,
但全量预训练 + 下游实验补做)、Phase 4 D6 隔离 + `--universe` 全链路
(本会话 GAP1-4 已立,expanded_v1=328 保留作对照不废弃)、
temporal_split canonical 纪律、本会话 6 commit 的所有修复。
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
| R0-d3 | 单测覆盖 R0-A1..A5 |
| R0-d4 | **survivorship-rigor audit**:量化当前 universe 的幸存者偏差(PIT first-trade-date 已防 look-ahead 纳入,但无 as-of-date 历史成分重建 + 手动删退市如 K)→ `data/audit/ml_redo/survivorship_audit.json`(每年存活/退市计数 + 偏差幅度估计 + 是否需 as-of 重建的判定)|

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R0-A1 | rank-norm 逐日截面、值 ∈[0,1]、**因果**(截断面板算 t 日 == 全面板算 t 日)| `test_feature_prep_ranknorm_causal` | M |
| R0-A2 | winsorize 后无值超出 [p1,p99];阈值取自 yaml 非 hardcode | `test_feature_prep_winsorize` + `test_feature_prep_config_sourced` | M |
| R0-A3 | sector-neutral 后行业内均值≈0;sector 用 PIT(无未来重分类泄漏)| `test_feature_prep_sector_neutral_pit` | M |
| R0-A4 | frac-diff:输出通过 ADF 平稳 + d 最小性 + opt-in 默认 off 时面板 bit-identical | `test_feature_prep_fracdiff` | M |
| R0-A5 | survivorship audit JSON 存在 + schema 完整(per-year alive/delisted + 偏差估计 + as-of-rebuild 判定);判定 = `as_of_rebuild_required: bool`(若 true → 进 R-P4ext 处理,不在 R0 重建)| `test_survivorship_audit_schema` | M |

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

## §5.5 Phase R2.5 —— P2 literature-grade 复检(地基审计,**R4 前必做**)

**缘由**:audit 发现(§13)operator 上一轮称"Phase 2A 严谨、不重做"是
overclaim —— P2A 缺 sample-uniqueness 加权 / sector-neutral / winsorize /
vol-scale / CPCV / DSR;P2B 的 MiniROCKET/TS2Vec **从未跑过下游 IC、
TS2Vec 仅 40 步 smoke 从未全量预训练**。"结构信息无增量"是地基性结论,
若是 naive-prep 下的 false negative,R4 的前提就错。**必须在 R4 之前
用 R0/R1/R2 全套复检。**

### Spec
- **R2.5-a family T 复检**:在 R0(rank-norm/winsorize/sector-neutral/
  vol-scale)+ R1(并发加权 label)+ R2(CPCV)上重做 family T
  incremental-IC(对照 = 不含 family T 的 175 因子 rank:ndcg,B3
  colsample=1.0 配对),报 ΔIC mean / 95%CI / paired-t **+ Deflated
  Sharpe / PBO**。verdict config-scoped(D2)。
- **R2.5-b P2B 表征下游激活**:R3 全量预训练后(依赖 R3-A2 full-pretrain),
  把 MiniROCKET / TS2Vec / MAE embedding 作为**增量因子列**注入现有
  `build_ml_panel` → rank:ndcg,测增量 IC(同 R2.5-a 裁判)。这是
  Phase 2B 当初 evidence-gated 推迟、从未执行的实验,本 PRD 兑现。
- 三组都走 `partition_for_role(role="miner")` train-only + CPCV;
  sealed 不读。

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| R2.5-A1 | family T 复检报 ΔIC mean/CI/paired-t/**DSR/PBO**;col-diff==12 family T;config-scoped verdict | `test_p2_recheck_report_schema` | M |
| R2.5-A2 | P2B 表征(≥MiniROCKET+TS2Vec)下游 incremental-IC 报出,同裁判 | 报告 JSON schema | M |
| R2.5-A3 | R2.5-b 依赖 R3-A2(full-pretrain,非 smoke);依赖未满足则 fail-closed | `test_p2_recheck_requires_full_pretrain` | M |
| R2.5-A4 | verdict 措辞 config-scoped、无 blanket(family T / 结构表征"无信息"禁写死)| 人工 + `verdict_scope` 字段 | H |

**关键**:R2.5 若推翻"结构无增量"(family T 或 P2B 表征在 literature-
grade 下显著为正)→ 主 PRD chart-structure 叙事改写,R4 优先级与设计
据此调整。R2.5 仍负 → R4 在更强证据下继续(D2,不终止)。

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
| R3-A2a | MAE segment-mask 因果 + 模块单测(smoke loss 下降)| `test_mae_encoder` | M |
| R3-A2 | **FULL 预训练已执行(非 smoke)**:TS2Vec + MAE 在 full corpus 上跑到收敛,checkpoint + 训练曲线落盘 `data/audit/ml_redo/pretrain_<enc>.json`,含 `is_full_pretrain:true` / `n_steps` / `corpus_manifest_id` / loss 曲线 / 收敛判据(loss plateau 或 max_steps);**禁 `is_full_pretrain:false` 进 R2.5-b/R4** | `test_full_pretrain_artifact_schema` + 产物存在 | M |
| R3-A3 | linear-probe / fine-tune harness 跑通 + 增广是 TS 专属(无 rotation/crop)| `test_pretrain_finetune_harness` | M |
| R3-A4 | 下游 attempt JSON 记 `pretrain_method` / `corpus_manifest_id` / `probe_or_finetune` / `is_full_pretrain` | schema 校验 | M |

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

## §8.5 Phase R-P4ext —— universe 规模审计 + expanded_v2(~1000)

**缘由**:audit 发现(§13)P4 expanded_v1=328 的规模是**非实测
PLACEHOLDER**——主 PRD §C 自承"expanded universe 规模 200-500 /
~200 下限 = judgment 非实测"。literature(Gu-Kelly-Xiu 用全 CRSP
~数千 cross-section;SSL 低数据 regime 明示需大样本;CPCV/DSR 多重检验
需横截面宽度)+ Phase 2A 负结果根因之一就是"票池太小 + 老因子吃饱
趋势"。328 在 literature 标准下偏小,**"做出来了但规模没实证依据"=
没做透**。

### Spec
1. **polygon 覆盖度审计**:对 Russell-1000 级别(~1000,目标 ~1k;
   上限按 polygon 实际可用 + 数据完整度定,**不拍脑袋**)枚举候选成分,
   逐 symbol 查 polygon 日线覆盖年限 + 完整度,产
   `data/audit/ml_redo/universe_v2_coverage.json`。
2. **`config/universe_expanded_v2.yaml`**:覆盖度审计通过的成分(目标
   ~1000;实际 N 由数据定,记录 drop reason)。**不动** universe.yaml /
   executable_universe.yaml / universe_expanded_v1.yaml。
3. **as-of-date 成分**(接 R0-A5):若 survivorship audit 判
   `as_of_rebuild_required:true`,v2 成分必须含历史退市名 + 记录每名
   存活区间(缓解幸存者偏差),否则记录"current-constituents,残留
   survivorship,evidence caveat"。
4. **D6 隔离 + 全链路传播**:走本会话已建 `resolve_universe` +
   `--universe` 全链路(mining→spec→forward→promote);新增
   `expanded_v2` 选项;executable/expanded_v1 **byte-identical 不变**。
5. integrity smoke(weekend-row / cross-symbol date / completeness gate)
   同 P4。

### Acceptance
| AC | 判据 | 验收 | Tier |
|---|---|---|---|
| RP4-A1 | coverage audit JSON 存在 + 每 symbol 有覆盖年限/完整度/drop-reason;N 由数据定非拍脑袋 | `test_universe_v2_coverage_schema` | M |
| RP4-A2 | `resolve_universe("expanded_v2")` 可解析;executable/expanded_v1 bit-for-bit 不变(回归)| `test_resolve_expanded_v2` + 复用 P4-A2 回归 | M |
| RP4-A3 | `--universe expanded_v2` 全链路(mining/backtest/forward/promote)可达 + 产物记 universe(复用 GAP1-4 测)| `test_universe_flag_all_entrypoints` 扩 expanded_v2 | M |
| RP4-A4 | expanded_v2 过 completeness gate + weekend/cross-symbol smoke | gate + smoke 测 | M |
| RP4-A5 | survivorship:as_of_rebuild_required 时 v2 含退市名 + 存活区间;否则显式 caveat 记录 | `test_universe_v2_survivorship` | M |

**规模不锁死**:目标 ~1000 是 literature-informed judgment;**最终 N
由 polygon 覆盖度审计的数据依据定**(§C 纪律:不拍脑袋);若 ~1000
覆盖度不足则记录实际可达上限 + root-cause,**禁** blanket"大 universe
无用"。expanded_v1(328)保留作对照,不废弃。

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
R0 数据准备(+survivorship audit)─┐
R1 label                          ─┼─→ R2 验证层 ─→ R3 SSL 全量预训练 ─┐
R-P4ext universe v2 审计(∥,只 dep 现有 universe infra)──────────────┤
                                                                       ↓
        R2.5 P2 地基复检(family T + P2B 表征,dep R0/R1/R2/R3-A2)
                                                                       ↓
                              R4 chart-native redo ─→ R5 ensemble
```
- Fire R0/R1/R-P4ext:用户 explicit-go 本 PRD 后立即(三者可并行)。
- Fire R3 full-pretrain:R0/R1/R2 + (若 v2 用)R-P4ext 数据就绪。
- **Fire R2.5(地基复检)**:R0-A*/R1-A*/R2-A*/R3-A2 全过。**R2.5 必须
  在 R4 之前**——R4 是在 P2 地基上盖楼,地基负结论若 false negative
  则 R4 前提错。
- Fire R4:R2.5 完成(无论正负,verdict 记录即可,D2)+ R0..R3 全过。
- Fire R5:R4 产出 ≥1 个非 superseded attempt。
- 每 Phase closeout memo + termination promise
  `MLREDO-R0-DONE` / `-R1` / `-R2` / `-RP4` / `-R3` / `-R2.5` /
  `-R4` / `-R5`;全完 → `MLREDODONE`。

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
| G9 | universe 规模有数据依据(非 PLACEHOLDER):expanded_v2 N 由 coverage audit 定 | RP4-A1 + §13 cross-walk | M |
| G10 | P2 地基复检(R2.5)在 R4 之前完成且 verdict 记录 | 执行序 + R2.5 closeout | M |
| G11 | SSL 是 FULL 预训练非 smoke 才进下游 | R3-A2 `is_full_pretrain` 字段 fail-closed | M |

---

## §13 Audit cross-walk —— P1-P4「做出来但没做透」对照(folded → R 相位)

用户要求:对比之前 P1-P4 结论/结果 vs 文献综述 memo vs 本 PRD,找
**"只做出来、没做彻底"**的项,全部 fold 进 supplement。

| 之前 P1-P4 | 之前结论/状态 | 文献 memo 指出的不足 | 做透了? | folded → |
|---|---|---|---|---|
| P1 family T 12 特征 | 造好 + 因果硬测过 | 特征本身 OK;但从未经 sector-neutral/winsorize/vol-scale 预处理评估 | 特征✅ / 评估❌ | R0 + R2.5-a |
| P2A incremental-IC | "family T 无显著增量"(operator 曾称"严谨不重做")| 缺 sample-uniqueness 加权 / sector-neutral / winsorize / vol-scale / CPCV / DSR-PBO;**operator overclaim 已纠正** | ❌ 地基未做透 | **R2.5-a** |
| P2B MiniROCKET/TS2Vec/MAE | 模块 ship + 单测,**下游 IC 从未跑;TS2Vec 仅 40 步 smoke 从未全量预训练** | literature 核心 = SSL 全量预训练→probe/finetune;P2B 停在"造好" | ❌ 科学测试从未执行 | **R3(full-pretrain)+ R2.5-b** |
| P3 3A/3B/3C | "underperforms"(本会话修 temporal_split 后) | 从零监督小模型 = literature 预测失败 regime(无 SSL/数据准备/加权 label/CPCV/TS 增广) | ❌ naive | R0+R1+R2+R3+**R4**(superseded 重做) |
| P3 评估协议 | 年块 fit/OOS + 边界 purge(本会话修) | 非 CPCV;无 Deflated Sharpe / PBO 多重检验校正 | ⚠️ 半 | **R2** |
| P4 universe | expanded_v1=328(79 base+249)| 规模 = 主 PRD §C 自承 **PLACEHOLDER 非实测**;literature 需更大 cross-section(~1k Russell-1000 级);残留 survivorship(无 as-of 重建)| ❌ 规模无实证 + survivorship | **R-P4ext + R0-A5** |
| P4 D6 隔离 / `--universe` 全链路 | 本会话已修(GAP1-4 端到端 + bit-identical)| 充分 | ✅ | 复用,RP4-A2/A3 扩 v2 |
| 全项目级(超出本 PRD scope,记录不扩)| cycle04-12 等从无 triple-barrier/meta-label/sample-uniqueness/CPCV/DSR-PBO/stacking | 同类方法论欠缺;本 PRD 在 redo 内补齐并立 infra(R1/R2/R5)→ 未来 cycle 可复用 | ❌ 项目级 | infra 立于 R1/R2/R5;全项目回灌 = 另议,不在本 PRD |

**判读**:P1 特征 + P4 隔离机制 + 本会话 temporal_split 修复 = 做透的,
保留;P2A 评估 / P2B 科学测试 / P3 方法 / P4 规模 + survivorship = "只做
出来没做透",已分别 fold 进 R0/R2.5/R3/R4/R-P4ext。**operator 上一轮
"Phase 2A 不重做"判断已纠正并写入 §5.5 缘由 + 本表(诚实留痕,不
hand-wave)。**

---

## §12 启动

本 PRD v1 → **用户 explicit-go** 后从 R0/R1 起逐 Phase 执行(operator
不自启 autonomous loop;ralph-loop execution 切分另出 execution PRD 或
按本 PRD §10 顺序直接做)。lineage `ml-method-redo-2026-05-16`;loop log
复用 `docs/memos/20260515-chart_structure_loop_log.md`(新 lineage tag 段)。
