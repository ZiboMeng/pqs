# chart-native S1 → evidence-only forward-init(evidence-gated,非反应式)

**日期**: 2026-05-18
**candidate**: `chart_native_s1_evidence_v1`
**role**: `evidence_only_observation`(standalone 轨,**不入 fleet**)
**spec_hash**: `d035c1840dd0bccb96638fdd82d642b7d92323b64cabf0aff5598f5701a52361`
**frozen_probe_beta_sha256**: `439ee31e1de3e5f8fdd89864062d21492f505317a005856f7ffe8b4704b94fb7`
**start_date**: 2026-05-19(freeze 2026-05-18)
**纪律**: [[feedback_promotion_only_falsification_evidence_gated]]
(harness)+ [[feedback_no_blanket_failure_verdict]] +
[[feedback_self_audit_methodology]] R3 实跑 +
[[feedback_temporal_split_discipline]](sealed 2026 NEVER read)。

---

## §1 为什么 forward-init(决策链,不是赌气)

用户 2026-05-18 立的 harness 规则:**不晋升只能靠"strategy 自身有
缺陷"的证伪证据;怀疑只是证伪动机不是拒绝理由;但也禁反应式
promote;证据不足→做更多实验→再决定**。本决策严格按此:

1. **原版(因果干净,GAF 窗结束在 bar i)PASS Track-A 全 17 关**
   —— adjusted 价 / train-only ridge probe / validation frozen-OOS /
   sealed 2026 未读。cum_ret +2042% / Sharpe 1.589 / MaxDD -16.8% /
   vs_spy +1409% / vs_qqq +1546%。
2. **4 个证伪尝试,无一拿到 strategy-自身缺陷证据**:
   - neg-control(打乱标签)→ 该塌则塌 → 清掉 harness/pooling artifact;
   - no-overlap(我额外加 21d-gap 的**致残诊断变体**)→ IC/20x 仍
     保住 → 清掉 overlap/lookahead;
   - survivorship n=8 → 数据覆盖断崖(90% 票 2015 才有,非晚 IPO)
     造成 n=8 退化 confound,**INCONCLUSIVE,不作证据**(没凭它拒);
   - **survivorship 70 票真代理**(2015-06 数据起点全宽 universe minus
     9 真·晚进入者)→ **PASS Track-A 全 17 关,cum_ret +2163% /
     Sharpe 1.62 ≈ 原版** → edge 干净存活,**非 survivorship 驱动**。
3. **结构残留 = 诚实留痕,非拒绝理由**:2015 前真 point-in-time /
   退市票 survivorship **结构性无法离线测**(无退市库;数据集本身
   即 2015+ 厂商幸存横截面;C5 同类)。按 harness:**测不到 ≠ 默认拒**;
   且 **forward observation 本就是测它的机制**(真实时 OOS、无
   survivorship)= path-1 的目的。
4. **其余疑虑按 harness 明确不是拒绝理由**:PBO red_flag 已 audit
   证 single-signal 下 folds-as-configs 误用 = N/A 非有效证据;
   "太好" / pooled-IC 可能膨胀 = 证伪动机(已做 4 个),非拒绝依据。

**∴ 证据充分。forward-init = 4 证伪清场后唯一残留正是 forward 要测
的东西,evidence-grounded,不是为守规则赌气 promote。**

> **自纠留痕**:我先前(commit `1777cdc`)凭怀疑+先验+我自加的
> 致残变体判 "NOT promote"(违反 harness,已撤回 `8e2c3e0`);随即
> 又差点为"显得守规则"立刻 forward-init(同错反向)。最终决策按
> 用户 2 次澄清校准:**evidence-gated 双向**,先做完 survivorship
> 取证,证据充分才 init。

## §2 strategy 定义(frozen 契约)

GAF(WINDOW_LEN=63)窗 of adjusted close → **冻结** torchvision
ResNet18 IMAGENET1K_V1(`fc=Identity`,全参 `requires_grad_(False)`,
`eval()`)512 维特征 → ridge probe(λ=10)**仅在 train-year 行拟合
后冻结** → 横截面 score → cap_aware_cross_asset / monthly / top-10 /
cluster_cap 0.20 / max_single 0.10 / asset_class_caps。

**Frozen-probe 契约**:`beta`(512 维)持久化为 sha256 钉死的 .npy
sidecar,**forward observation 期间永不重训**。backbone 由
torchvision 版本钉死(确定性)。

## §3 artifacts(均 commit)

| 文件 | 内容 |
|---|---|
| `data/research_candidates/chart_native_s1_evidence_v1.yaml` | frozen spec(含 evidence/caveat 块) |
| `..._forward_manifest.json` | manifest + TD000 baseline,status=in_progress |
| `..._forward_nav.parquet` | frozen baseline NAV(forward 增量 append) |
| `..._frozen_probe_beta.npy` | 冻结 ridge β(sha256 `439ee31e…`) |
| `dev/scripts/chart_native_l3/init_chart_native_evidence.py` | init 脚本(仿 pead standalone 模式,idempotent) |

证伪证据快照:`data/audit/chart_native_l3_SURVIVORSHIP_n8_degenerate.json`
(inconclusive)、`..._70name_meaningful.json`(decisive PASS)。

## §4 TD60 决策点 ~2026-08-13(与 pead 同窗)

- **GREEN**:realized Sharpe > 0.8 + MaxDD < 15% + 与现有 forward
  candidate 日收益 Pearson < 0.70 → 考虑 Phase 2(更强 backbone /
  LP-FT per task#23 lit review;non-fleet 仍 evidence-only)。
- **YELLOW**:Sharpe 0.4-0.8 或 MaxDD 15-25% → 续 TD90。
- **RED**:Sharpe < 0.4 或 MaxDD > 25% → close evidence 轨。
- 任意时点拿到 **strategy-自身缺陷证伪证据**(如 forward 真实数据
  暴露 survivorship/构造缺陷)→ 立即 halt(harness 唯一合法 halt)。

## §5 scope / 诚实边界(不 over-claim)

- **config-scoped 研究信号 forward 观察轨**,evidence-only,**不入
  fleet allocation**;learned probe(非 ResearchCompositeSpec),走
  standalone 轨(同 pead / simple_baseline 先例),**不**用 main
  composite runner。
- pooled-IC 幅度可能膨胀(Track-A 用 portfolio 指标非 pooled IC);
  DSR placeholder-N 非锚;from-scratch CNN 输 pretrain→probe(稳定)。
- pre-2015 真 survivorship **结构性未测**(诚实,非假装)——forward
  soak 是它的 OOS 测试。
- daily-ritual observe 脚本 = 跟进项(仿 pead observe 增量模式)。

## §6 关联
[[project-backtest-robustness-ml-redo-2026-05]]
[[feedback_promotion_only_falsification_evidence_gated]]
[[feedback_no_blanket_failure_verdict]]
path-1: `docs/memos/20260518-path1_forward_replaces_sealed_singleshot.md`
claim 纪律: `docs/memos/20260518-auditor_claim_discipline_response.md`
