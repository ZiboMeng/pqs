"""core.risk — 失效检测、熔断开关与压力测试。"""

from core.risk.failure_detector import FailureDetector, FailureSignal
from core.risk.kill_switch import KillSwitch, KillSwitchConfig, KillSwitchResult
from core.risk.stress_tester import (
    StressTester, StressScenario, StressResult, MonteCarloResult,
)

__all__ = [
    "FailureDetector", "FailureSignal",
    "KillSwitch", "KillSwitchConfig", "KillSwitchResult",
    "StressTester", "StressScenario", "StressResult", "MonteCarloResult",
]
