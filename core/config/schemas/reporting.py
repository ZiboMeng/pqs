"""Reporting configuration schemas."""

from typing import List
from pydantic import BaseModel, Field


class ReportSectionConfig(BaseModel):
    enabled: bool = True


class ReportingConfig(BaseModel):
    """Unified master report configuration."""

    language: str = Field(default="zh", pattern="^(zh|en|bilingual)$")
    output_format: str = Field(default="markdown", pattern="^(markdown|html)$")

    # Which sections to include
    include_portfolio_section: bool = True
    include_interday_section: bool = True
    include_intraday_section: bool = True
    include_paper_trading_section: bool = True
    include_benchmark_section: bool = True
    include_risk_section: bool = True
    include_factor_driver_section: bool = True
    include_news_event_section: bool = True
    include_diagnostics_section: bool = True
    include_forward_look_section: bool = True

    # Charts
    generate_charts: bool = True
    chart_dpi: int = Field(default=150, ge=72, le=300)
    chart_style: str = "seaborn-v0_8-darkgrid"

    # Benchmarks shown in report
    benchmarks: List[str] = Field(default=["SPY", "QQQ"])

    keep_n_daily_reports: int = Field(default=30, ge=1)
