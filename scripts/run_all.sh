#!/usr/bin/env bash
# scripts/run_all.sh — PQS 组合运行脚本
#
# 用法
# ----
#   bash scripts/run_all.sh full          # 完整流程：下载 + 回测 + 报告
#   bash scripts/run_all.sh mine          # 策略挖掘循环（1h 预算）
#   bash scripts/run_all.sh daily         # 每日流程：增量更新 + 模拟盘 + 报告
#   bash scripts/run_all.sh backtest-only # 只跑回测（不下载）
#   bash scripts/run_all.sh status        # 查看模拟盘状态
#
# 环境
# ----
#   需要已激活 .venv，或使用系统 python（需安装 pqs[dev]）

set -euo pipefail

PYTHON=${PYTHON:-python}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

MODE="${1:-help}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

case "$MODE" in

  full)
    log "=== PQS 完整流程 ==="
    log "Step 1/3: 下载/更新市场数据"
    $PYTHON scripts/fetch_data.py

    log "Step 2/3: 运行回测"
    $PYTHON scripts/run_backtest.py

    log "Step 3/3: 生成主报告"
    $PYTHON scripts/generate_report.py --paper-status

    log "完成 ✓"
    ;;

  mine)
    log "=== PQS 策略挖掘循环 ==="
    $PYTHON scripts/run_mining.py --trials 80 --budget 3600
    log "挖掘完成 ✓"
    ;;

  mine-long)
    log "=== PQS 策略挖掘（长时间模式：4h, 200 trials）==="
    $PYTHON scripts/run_mining.py --trials 200 --budget 14400
    log "挖掘完成 ✓"
    ;;

  daily)
    log "=== PQS 每日流程 ==="
    log "Step 1/3: 增量更新行情"
    $PYTHON scripts/fetch_data.py --daily-only

    log "Step 2/3: 模拟盘（live 模式）"
    $PYTHON scripts/run_paper.py --mode live

    log "Step 3/3: 生成日报"
    $PYTHON scripts/generate_report.py --paper-status

    log "每日流程完成 ✓"
    ;;

  replay)
    FROM_DATE="${2:-2024-01-02}"
    log "=== PQS 模拟盘历史回放（from ${FROM_DATE}）==="
    log "⚠️  BIAS 警告：此模式存在前视偏差，结果仅供调试"
    $PYTHON scripts/run_paper.py --mode replay --from-date "$FROM_DATE"
    log "回放完成 ✓"
    ;;

  research)
    log "=== PQS 完整研究流程 ==="
    log "Step 1/5: 下载/更新数据"
    $PYTHON scripts/fetch_data.py --daily-only

    log "Step 2/5: Universe 重评估"
    $PYTHON scripts/run_universe_rebalance.py --top 15

    log "Step 3/5: 因子 IC 筛选"
    $PYTHON scripts/run_factor_screen.py --top 15

    log "Step 4/5: 策略挖掘 (multi_factor)"
    $PYTHON scripts/run_mining.py --type multi_factor --trials 40 --budget 1200

    log "Step 5/5: 完整回测 + 报告"
    $PYTHON scripts/run_backtest.py

    log "研究流程完成 ✓"
    ;;

  universe)
    log "=== Universe 重评估 ==="
    $PYTHON scripts/run_universe_rebalance.py "${@:2}"
    ;;

  factors)
    log "=== 因子筛选 ==="
    $PYTHON scripts/run_factor_screen.py "${@:2}"
    ;;

  xgb)
    log "=== GBM Feature Importance ==="
    $PYTHON scripts/run_xgb_importance.py "${@:2}"
    ;;

  check)
    log "=== PQS 系统健康检查 ==="
    log "Step 1/3: 运行测试"
    $PYTHON -m pytest tests/ -q --tb=no || { log "❌ 测试失败"; exit 1; }

    log "Step 2/3: 快速回测冒烟"
    $PYTHON scripts/run_backtest.py --no-walk-forward 2>&1 | grep -E "CAGR=|SPY \(bench"

    log "Step 3/3: Mining 排行榜"
    $PYTHON scripts/run_mining.py --leaderboard 2>&1 | tail -5

    log "✓ 健康检查完成"
    ;;

  backtest-only)
    log "=== PQS 回测（跳过数据下载）==="
    $PYTHON scripts/run_backtest.py
    log "回测完成 ✓"
    ;;

  backtest-quick)
    log "=== PQS 快速回测（跳过 walk-forward）==="
    $PYTHON scripts/run_backtest.py --no-walk-forward
    log "快速回测完成 ✓"
    ;;

  status)
    log "=== 模拟盘状态 ==="
    $PYTHON scripts/run_paper.py --mode status
    ;;

  leaderboard)
    log "=== Mining 排行榜 ==="
    $PYTHON scripts/run_mining.py --leaderboard
    ;;

  fetch-only)
    log "=== 仅下载数据 ==="
    $PYTHON scripts/fetch_data.py "${@:2}"
    log "下载完成 ✓"
    ;;

  help|*)
    echo ""
    echo "用法: bash scripts/run_all.sh <mode>"
    echo ""
    echo "可用 mode:"
    echo "  check           系统健康检查 (测试 + 回测 + 排行榜)"
    echo "  full            完整流程 (下载 + 回测 + 报告)"
    echo "  research        研究流程 (数据 + universe + factors + mining + 回测)"
    echo "  mine            策略挖掘 (1h, 80 trials/type)"
    echo "  mine-long       策略挖掘 (4h, 200 trials/type)"
    echo "  daily           每日流程 (增量更新 + 模拟盘 + 日报)"
    echo "  replay [date]   历史回放 (默认 from 2024-01-02)"
    echo "  backtest-only   只跑回测"
    echo "  backtest-quick  快速回测 (跳过 walk-forward)"
    echo "  universe        Universe 重评估"
    echo "  factors         因子 IC 筛选"
    echo "  xgb             GBM Feature Importance"
    echo "  status          查看模拟盘状态"
    echo "  leaderboard     查看 Mining 排行榜"
    echo "  fetch-only      只下载数据"
    echo ""
    echo "示例:"
    echo "  bash scripts/run_all.sh full"
    echo "  bash scripts/run_all.sh replay 2023-06-01"
    echo "  PYTHON=.venv/bin/python bash scripts/run_all.sh daily"
    echo ""
    ;;

esac
