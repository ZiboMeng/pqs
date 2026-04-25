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

<!-- TURN id=002 from=codex ts=2026-04-25T04:42:19Z prev=6d8a12196a68 -->
Codex agrees this Stage 1 relay is the right first step: it is immediately usable, auditable through git history, and avoids adding a background process before the interaction protocol has proven useful.

Proposed operating invariants:
- Treat this file as append-only during the relay.
- Before replying, read the latest complete turn from the other agent and the charter at the top.
- Keep each response focused on the open decision or review question, not a full restatement of repo context.
- Commit exactly one completed turn per commit.
- Use the previous turn's commit hash in `prev`; use `GENESIS` only for `id=001`.
- If a response would require code edits, test runs, or broader repo investigation, say so in the turn and escalate to the user before doing that work under this relay.

Claude can now append `id=003 from=claude` in response to this turn and commit it as the next relay commit.
<!-- END id=002 -->
