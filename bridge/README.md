# Claude ↔ Codex Bridge — Operations Guide

This dir is a **shared markdown channel** for Claude (this CLI) and
Codex (another CLI on the same machine) to discuss tasks. Each
"turn" is appended to `claude-codex-bridge.md` and committed as
a single git commit.

**Stage 1 status**: user-driven relay. No daemon. The user manually
asks each side to read the bridge file and append a reply.

For the full schema, validation rules, and escalation logic see
[`PROTOCOL.md`](PROTOCOL.md). The charter for the current
conversation is **inline** at the top of `claude-codex-bridge.md`
(between the title and the first `---` separator).

---

## What user does

### Starting a conversation (turn 001)

1. Open `claude-codex-bridge.md`. If a prior conversation is still
   there, archive it first (see "Archiving" below).
2. Edit the inline charter at the top: set `Topic`, `Started`, and
   `Charter` (max_turns / escalate / end conditions). Charter
   syntax follows the format used in turn 001 of the existing
   conversations — see [`PROTOCOL.md`](PROTOCOL.md) §5.
3. Append the first turn yourself with `from=user`. Use the
   helper:

   ```bash
   echo "Your task description / charter framing" > /tmp/turn001.md
   bash bridge/append_turn.sh user /tmp/turn001.md
   ```

   The helper will compute `id=001`, `prev=GENESIS`, stamp `ts`,
   atomic-write the new turn, and `git commit` with the prescribed
   message format.

### Relaying turns

- Tell Codex: *"Read `bridge/claude-codex-bridge.md` to the end and
  append your reply."* Codex parses the last turn, looks up
  `prev` (12-char prefix of the last commit's hash) via
  `bash bridge/append_turn.sh --prev-commit`, appends a new turn
  with `from=codex`, commits.
- Tell Claude (this side): same, with `from=claude`.

Each round is roughly 30 seconds of your typing. The two agents do
all the actual work.

### Closing a conversation

- Both agents land back-to-back turns each containing the literal
  `AGREED` on its own line → done.
- OR a turn closes with `<!-- END id=NNN final=true -->` (instead
  of plain `<!-- END id=NNN -->`).
- OR you append a final turn with `<!-- final=true -->` in the
  body.
- OR an agent writes `ESCALATE` on its own line → review and
  either resume or archive.

### Archiving

```bash
mkdir -p bridge/archive
ts=$(date -u +%Y-%m-%d)
slug=$(grep -m1 '^Topic:' bridge/claude-codex-bridge.md \
       | sed 's/.*: *//' | tr ' /' '_-' | tr -d ':,()' | cut -c1-40)
mv bridge/claude-codex-bridge.md bridge/archive/${ts}_${slug}.md
# Recreate empty bridge file with a new charter:
cat > bridge/claude-codex-bridge.md <<'BRIDGE_EOF'
# Claude <-> Codex bridge

Topic: <fill in>
Started: <fill in UTC ISO8601>
Charter: max_turns=8 | escalate_to_user_when=<conditions> | end_condition=<conditions>

---
BRIDGE_EOF
git add bridge/ && git commit -m "bridge: archive <prior topic>, reset for new conversation"
```

---

## What an agent (Claude or Codex) does at each turn

This is the **operational checklist**. Full spec in `PROTOCOL.md`.

1. **Read** `bridge/claude-codex-bridge.md` end-to-end (don't just
   look at the last turn).
2. **Read** the inline charter at the top for max_turns / escalate
   conditions.
3. **Find** the last `<!-- END id=N -->` marker. Let `K = N`.
   - If there are no turns yet, only the user writes turn 001.
4. **Validate** per PROTOCOL §3:
   - id continuity (next must be K+1)
   - no half-open `<!-- TURN ... -->` after the last END
   - chain looks structurally consistent

   ```bash
   bash bridge/append_turn.sh --validate
   ```

   If validation fails → DO NOT WRITE; reply to user "validation
   failed at turn X, please review."
5. **Check escalation triggers** per PROTOCOL §6:
   - K reaching `charter.max_turns`
   - prior turn body contains literal `ESCALATE` on its own line
   - same argument repeated twice in last 4 turns (self-detect)
   - same agent has 3 disagreement turns without concession
   - last turn body word count exceeded charter.turn_size_max_words
   - the reply you'd write would require code edits / test runs /
     repo investigation outside the bridge file (escalate per
     codex's invariant from turn 002)

   If triggered → DO NOT WRITE; tell user.
6. **Look up `prev`**: the 12-char prefix of the git commit hash
   that introduced turn K. Use:

   ```bash
   bash bridge/append_turn.sh --prev-commit
   ```

7. **Compose** your reply. Stay within charter limits, on-topic.
8. **Append**:

   ```bash
   echo "Your reply body…" > /tmp/turn_body.md
   bash bridge/append_turn.sh <your-role> /tmp/turn_body.md
   ```

   The helper will write the marker block, atomic-rename, and
   commit with `bridge turn NNN from=<role>: <one-line>`.

9. **Stop**. Do not start the next turn yourself. Wait for user
   to ping the other side.

---

## Hard rules — for both agents

- ✗ Never edit a prior turn (your own or the other agent's).
- ✗ Never delete the file or rewrite the title/charter mid-thread.
- ✗ Never add `Co-Authored-By:` to bridge commits.
- ✗ Never continue past an escalation trigger.
- ✗ Never write `from=user` if you're claude or codex.
- ✗ Never trigger code edits / test runs / broader repo work
  inside a bridge turn — escalate to user per protocol §6 #6.
- ✓ Always read the full file before composing.
- ✓ Always validate the chain before you write.
- ✓ Always commit per turn — one commit, one turn.
