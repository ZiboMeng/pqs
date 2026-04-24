"""Tests for intraday report generation."""

import sqlite3


from core.reporting.intraday_report import generate_intraday_report


def _create_test_db(path: str, with_data: bool = True):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS bar_checkpoints (
        run_id TEXT, last_bar_ts TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS intraday_fills (
        run_id TEXT, date TEXT, bar_ts TEXT, symbol TEXT, side TEXT,
        qty REAL, price REAL, slippage_usd REAL, commission_usd REAL, cash_delta REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS intraday_equity (
        run_id TEXT, date TEXT, bar_ts TEXT, equity REAL, cash REAL, portfolio_value REAL)""")

    if with_data:
        run_id = "test_run_001"
        conn.execute("INSERT INTO bar_checkpoints VALUES (?, ?, ?)",
                     (run_id, "2025-04-01 15:30", "2025-04-01 16:00"))
        for i in range(5):
            conn.execute("INSERT INTO intraday_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (run_id, "2025-04-01", f"2025-04-01 {10+i}:30", "SPY",
                          "BUY" if i % 2 == 0 else "SELL",
                          100.0, 450.0 + i, 0.5, 0.3, -45000 if i % 2 == 0 else 45000))
        for i in range(10):
            eq = 10000 + i * 50
            conn.execute("INSERT INTO intraday_equity VALUES (?, ?, ?, ?, ?, ?)",
                         (run_id, "2025-04-01", f"2025-04-01 {9+i}:30",
                          eq, eq * 0.3, eq * 0.7))
    conn.commit()
    conn.close()


class TestIntradayReport:
    def test_empty_db(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_test_db(db, with_data=False)
        report = generate_intraday_report(db)
        assert "No intraday sessions found" in report

    def test_report_with_data(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_test_db(db, with_data=True)
        report = generate_intraday_report(db, run_id="test_run_001")
        assert "Intraday Session Report" in report
        assert "test_run_001" in report
        assert "SPY" in report
        assert "Fills Summary" in report
        assert "Equity Path" in report

    def test_fills_summary_counts(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_test_db(db, with_data=True)
        report = generate_intraday_report(db, run_id="test_run_001")
        assert "5" in report  # 5 fills
        assert "BUY" not in report or "买入" in report  # Chinese labels

    def test_equity_path_metrics(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_test_db(db, with_data=True)
        report = generate_intraday_report(db, run_id="test_run_001")
        assert "$10,000" in report or "10000" in report
        assert "最大回撤" in report

    def test_diagnostics_section(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_test_db(db, with_data=True)
        report = generate_intraday_report(db, run_id="test_run_001")
        assert "诊断" in report
        assert "checkpoint" in report

    def test_specific_run_id(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_test_db(db, with_data=True)
        report = generate_intraday_report(db, run_id="nonexistent")
        assert "No fills recorded" in report
