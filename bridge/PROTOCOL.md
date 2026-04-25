# Claude ↔ Codex Bridge — Protocol Spec

**Version**: 1.1  (2026-04-25, Stage 1, post-codex-alignment)
**Scope**: Stage 1 = user-driven relay. No daemon. Spec is also
forward-compatible with a future Stage 2 watcher.

---

## 1. Turn marker grammar

A turn is a contiguous block in `claude-codex-bridge.md` of the form:

```
<!-- TURN id=NNN from=<role> ts=<ISO8601> prev=<git-commit-hash-12> -->
<turn body, freeform markdown>
<!-- END id=NNN -->
```

Field rules:

- `id` — zero-padded 3-digit integer, monotonically increasing from
  `001`. Each new turn must have `id = previous_completed_id + 1`.
- `from` ∈ `{user, claude, codex}`.
- `ts` — ISO 8601 UTC, e.g. `2026-04-25T17:30:00Z`. Coarse second
  precision is fine.
- `prev` — **the git commit hash of the commit that introduced the
  previous turn**, truncated to first 12 hex chars. `GENESIS` is
  used **only** for `id=001`.
- `<!-- END id=NNN -->` — closing marker's `id` MUST match the
  opening `id`. Any mismatch is a hard error: do not parse, do not
  append; escalate to user.
- A side may close the relay early by writing
  `<!-- END id=NNN final=true -->`. Treat as conversation end.

Why git commit hash for `prev`: the protocol already requires
"1 commit per completed turn" (§2.6). The commit hash is therefore
always available, recorded by git, and `git show <hash>` lets the
user inspect any prior turn directly. Using `sha256(body)` was
considered but rejected — it requires a separate hash computation
and doesn't add anything git doesn't already provide.

## 2. Append protocol (every turn)

1. **Read** `claude-codex-bridge.md` end-to-end.
2. **Read** the inline charter (the section at the top of the file
   between the title and the first `---` separator) for current
   topic / max_turns / escalation rules.
3. **Locate** the last `<!-- END id=K -->`. If none → next id is
   `001`, prev is `GENESIS`, and only the user writes turn 001 (an
   agent must NOT write turn 001).
4. **Verify** the document tail is clean: no half-open
   `<!-- TURN ... -->` after the last END. If a half-open TURN is
   present → escalate to user; do NOT append.
5. **Look up** the git commit hash that introduced turn K. Marker-
   specific (preferred — anchored on the TURN open line for turn K,
   which only exists in the commit that introduced turn K):

   ```bash
   git log --pretty=format:%H -1 \
       -G "^<!-- TURN id=$(printf "%03d" $K) " \
       -- bridge/claude-codex-bridge.md
   ```

   Or simpler heuristic: the most-recent commit that touches
   `bridge/claude-codex-bridge.md` is turn K's commit, since the
   protocol requires 1 commit per turn. Truncate to 12 hex chars.

   **Do NOT** use `--diff-filter=A`. That filter matches only
   commits where the file is newly added, which is only the very
   first commit that created `bridge/claude-codex-bridge.md`.
   For every turn after id=001 it returns empty/wrong. (Spec
   precision noted by codex in turn 004 of the Stage 1 trial.)
6. **Compose** the new turn block with `id = K+1`, `from`, `ts`,
   `prev` filled in, body authored by the agent.
7. **Append** to `claude-codex-bridge.md` via atomic write
   (write to `.tmp` + rename) or via direct `git add` + `git commit`.
8. **Commit** with message:

   ```
   bridge turn NNN from=<role>: <one-line summary>
   ```

   Summary is one short sentence, ≤ 60 chars. Do **NOT** add
   `Co-Authored-By:` lines on bridge commits — keep `git log`
   clean.

## 3. Validation rules

A turn is **valid** iff ALL of:

- `id` is exactly `previous_completed_id + 1`.
- `prev` matches the 12-char prefix of the git commit hash that
  introduced the previous turn (or `GENESIS` for `id=001`).
- `<!-- END id=N -->` matches the opening `<!-- TURN id=N ... -->`.
- `from` is one of `{user, claude, codex}`.
- `ts` parses as ISO 8601 UTC.
- Turn body is valid UTF-8.

If a turn fails validation, the next agent MUST NOT continue —
escalate to user.

Soft (non-blocking) check: turn body word count vs the inline
charter's `turn_size_max_words`. Exceeding it triggers escalation
per §6.

## 4. Atomicity & race

Stage 1 is single-writer-at-a-time (user manually relays). Race is
not a concern at this stage but the spec is forward-compatible:

- `git commit` per turn is the atomicity unit. Two concurrent
  writers will produce a merge conflict — easy to detect, easy
  to reject.
- A failed mid-turn (write half a turn block, then crash) leaves
  a half-open `<!-- TURN ... -->` without a matching `END`. §2 step
  4 catches this. Recovery: user manually closes or removes the
  half-turn (rare).

Stage 2 will need a `bridge/.lock` advisory file or `flock(1)` on
the bridge file during write. Out of Stage 1 scope.

## 5. Charter

The charter for the current conversation is **inline** at the top
of `claude-codex-bridge.md`, between the title and the first `---`
separator. It looks like:

```
# Claude <-> Codex bridge

Topic: <one-liner>
Started: <UTC ISO8601>
Charter: max_turns=N | escalate_to_user_when=<conditions> | end_condition=<conditions>

---

<!-- TURN id=001 ... -->
```

Update the charter only **between** conversations, never mid-thread.

## 6. Escalation triggers

Any of these → next turn must be `from=user` (or no turn at all),
NOT a continuation by claude/codex:

1. `id` reaches `charter.max_turns`.
2. Agent self-detects "this argument has already been made twice
   in the last 4 turns" — heuristic; the agent stops on its own.
3. Same agent has written 3 turns expressing disagreement without
   the other side conceding — heuristic; agent stops on its own.
4. Any agent writes the literal token `ESCALATE` on its own line in
   the turn body. Treat as immediate escalation, regardless of
   id/turn-count.
5. A turn body word count exceeds the charter's
   `turn_size_max_words` (default 2000). Soft cap; agent stops.
6. **A turn would require code edits, test runs, or repo-wide
   investigation outside the bridge file itself.** Per the
   codex-introduced invariant in turn 002: the relay is for
   protocol/decision discussion only. Real work is escalated to
   user, who launches it as a separate task outside the bridge.

## 7. End conditions

Conversation closes (no further turns by anyone) when ANY of:

- Both `claude` and `codex` write the literal token `AGREED` on
  their own line in **consecutive** turns.
- A turn closes with `<!-- END id=NNN final=true -->` instead of
  the plain END marker.
- User writes a turn with body containing `<!-- final=true -->`.
- An escalation trigger fires and user has not resumed the relay.

After end / escalation, no agent appends further until user
explicitly opens the next conversation (typically by archiving the
current bridge file under `bridge/archive/` and resetting — see
§8).

## 8. Multi-conversation (out of Stage 1 scope, but future-proof)

Stage 1 supports exactly **one** active conversation in
`claude-codex-bridge.md`. To start a new topic:

1. Move current `claude-codex-bridge.md` to
   `bridge/archive/<YYYY-MM-DD>_<slug>.md`.
2. Recreate `claude-codex-bridge.md` with a fresh title + new
   inline charter + first `---` + waiting for user turn 001.

Future Stage 2 may support `bridge/topic_<slug>.md` for parallel
conversations; protocol fields are forward-compatible.

## 9. Things agents MUST NOT do

- ✗ Edit any prior turn (your own or the other agent's).
- ✗ Delete the bridge file or rewrite the title/charter mid-thread.
- ✗ Skip the prev field or use a stale value.
- ✗ Write a turn whose `from` doesn't match the agent identity
  (claude must not write `from=codex`).
- ✗ Continue past an escalation trigger.
- ✗ Add `Co-Authored-By:` to bridge commits.
- ✗ Trigger code edits / test runs / broader repo investigation
  inside a bridge turn — escalate to user instead.

## 10. What agents MUST do at every turn

- ✓ Read the entire current `claude-codex-bridge.md` first.
- ✓ Re-read the inline charter to confirm rules haven't changed.
- ✓ Validate the last turn (id continuity + prev hash) BEFORE
  composing a reply.
- ✓ If validation fails, escalate to user instead of writing.
- ✓ Keep your turn body within `charter.turn_size_max_words` and
  on-topic for the charter's stated topic.
- ✓ Commit with the prescribed message format (no co-author line).
- ✓ Stop after one turn. Wait for user to ping the other side.
