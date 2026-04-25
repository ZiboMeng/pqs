# Claude <-> Codex bridge

Topic: Trial user-driven Claude-Codex relay over a git-tracked bridge file
Started: 2026-04-25T04:41:36Z
Charter: max_turns=8 | escalate_to_user_when=implementation scope changes, repo writes beyond this bridge are needed, either side has low confidence, or Claude and Codex disagree after two consecutive turns | end_condition=one side writes final=true or both sides agree Stage 1 is workable

---

<!-- TURN id=001 from=user ts=2026-04-25T04:41:36Z prev=GENESIS -->
The user wants to try Claude's Stage 1 proposal first: a user-driven relay with no background scanner or code changes yet.

Protocol:
- Keep this file git tracked.
- Each complete turn is appended to this file and committed as its own git commit.
- Each turn uses:
  `<!-- TURN id=NNN from=<user|codex|claude> ts=<UTC ISO timestamp> prev=<previous turn commit hash or GENESIS> -->`
  followed by the message body and then:
  `<!-- END id=NNN -->`
- A side may stop the relay by writing `<!-- END id=NNN final=true -->`.
- Stop and escalate to the user when `max_turns` is reached, when the end condition is met, or when either side needs user arbitration.

Workflow:
1. User asks Codex to read the latest `from=claude` turn, append a `from=codex` reply, and commit it.
2. User asks Claude to read the latest `from=codex` turn, append a `from=claude` reply, and commit it.
3. Continue until the charter says to stop.
<!-- END id=001 -->
