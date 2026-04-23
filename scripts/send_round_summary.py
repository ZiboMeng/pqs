#!/usr/bin/env python3
"""Send an LLM-Round summary to the configured notify backend
(config/notify.yaml). Reads round summary from stdin OR a file,
sends as info-level notification.

When `notify.enabled: true` and `backend: wecom_bot`, this pushes
to the WeChat Work group bot webhook set by `PQS_WECOM_WEBHOOK_URL`.
Stdout backend prints to console (useful when env var not set yet).

Usage
-----
    # From a markdown file (last N chars of docs/20260420-ralph_loop_log.md)
    python scripts/send_round_summary.py --file docs/20260420-ralph_loop_log.md \
        --last-section

    # From a heredoc or echoed string
    echo "Round 11: 3 dedup candidates orthog FIXED — 1 MEDIUM" | \
        python scripts/send_round_summary.py --title "LLM-Round 11"

    # Force stdout backend (testing)
    python scripts/send_round_summary.py --title ... --stdout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging_setup import get_logger, setup_logging
from core.notify import get_notifier, StdoutNotifier
from core.notify.factory import load_notify_config

setup_logging()
logger = get_logger("send_round_summary")


def _extract_last_section(md_path: Path) -> str:
    """Take the last `##`-level section from a markdown log. Used to
    grab the current round's summary from `docs/20260420-ralph_loop_log.md`."""
    text = md_path.read_text()
    # Split by top-level section markers (## at line start, or ---)
    # Last "## LLM-Round N" section
    idx = text.rfind("## LLM-Round")
    if idx < 0:
        idx = text.rfind("## Round")
    if idx < 0:
        return text[-4000:]  # fallback: last 4KB
    section = text[idx:]
    # Truncate if >4KB (WeChat message limits)
    if len(section) > 3800:
        section = section[:3800] + "\n\n...(truncated)"
    return section


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="LLM-Round Summary",
                        help="Notification title")
    parser.add_argument("--file", default=None,
                        help="Markdown file to extract summary from")
    parser.add_argument("--last-section", action="store_true",
                        help="Extract last ## LLM-Round section from file")
    parser.add_argument("--stdout", action="store_true",
                        help="Force stdout backend (ignore config)")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    # Body source: file or stdin
    if args.file:
        p = Path(args.file)
        if not p.exists():
            logger.error("File not found: %s", p)
            sys.exit(2)
        if args.last_section:
            body = _extract_last_section(p)
        else:
            body = p.read_text()
    else:
        body = sys.stdin.read()

    if not body.strip():
        logger.error("Empty body — nothing to send")
        sys.exit(2)

    # Pick notifier
    if args.stdout:
        n = StdoutNotifier()
        logger.info("Using StdoutNotifier (--stdout forced)")
    else:
        cfg = load_notify_config(Path(args.config_dir) / "notify.yaml")
        n = get_notifier(cfg)
        logger.info("Using notifier: %s", type(n).__name__)

    result = n.info(args.title, body)
    logger.info("Sent: success=%s backend=%s error=%s skipped=%s",
                result.success, result.backend, result.error,
                result.skipped_reason)
    sys.exit(0 if result.success else 3)


if __name__ == "__main__":
    main()
