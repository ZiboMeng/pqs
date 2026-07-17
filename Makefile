.PHONY: audit-check config-check safety-test test

config-check:
	.venv/bin/python -m core.config.loader --validate

safety-test: config-check
	.venv/bin/ruff check core scripts tests --select E9,F63,F7,F82
	.venv/bin/mypy core/trading core/runtime --no-error-summary
	.venv/bin/pytest -q tests/unit/trading tests/unit/runtime tests/unit/data/test_session_close_gate.py tests/unit/paper_trading/test_pretrade_boundary.py tests/unit/options

audit-check: safety-test
	.venv/bin/pip check
	.venv/bin/pip-audit --progress-spinner off

test:
	.venv/bin/pytest -q
