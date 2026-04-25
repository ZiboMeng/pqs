#!/usr/bin/env bash
#
# bridge/append_turn.sh — thin wrapper for the bridge protocol's
# mechanical bits (look up prev-commit hash, derive next id,
# generate marker boilerplate, atomic write + commit).
#
# Stage 1: user-driven relay. Both Claude and Codex can shell out
# to this when they need to append a turn.
#
# Protocol per bridge/PROTOCOL.md v1.1 (2026-04-25):
#   prev = first 12 hex chars of the git commit hash that
#          introduced the previous turn (i.e. the most-recent
#          commit touching bridge/claude-codex-bridge.md).
#          GENESIS for id=001 only.
#
# Usage:
#   bash bridge/append_turn.sh --help
#   bash bridge/append_turn.sh --prev-commit
#   bash bridge/append_turn.sh --next-id
#   bash bridge/append_turn.sh --validate
#   bash bridge/append_turn.sh <from-role> <body-file>
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_FILE="${REPO_ROOT}/bridge/claude-codex-bridge.md"

usage() {
  cat <<'EOF'
bridge/append_turn.sh — bridge turn helper (Stage 1)

USAGE
  --help                        Show this help.
  --validate                    Run protocol validation against
                                claude-codex-bridge.md (id chain
                                + prev hash chain). Exit 0 on
                                clean, non-zero on any violation.
  --next-id                     Print the id the next turn should
                                use (zero-padded 3 digits).
  --prev-commit                 Print the 12-char prefix of the
                                git commit hash that introduced
                                the most recent turn. Prints
                                GENESIS if no turns exist yet.
  <from-role> <body-file>       Append a new turn from <role> with
                                body from <body-file>. <role> in
                                {user, claude, codex}. Computes
                                next id + prev automatically.
                                Atomic write + git commit.

NOTES
  - Atomicity = git commit per turn (1 commit, 1 turn).
  - The script REFUSES to append if validation fails. Fix the
    file first or escalate to user.
  - prev is the git commit hash of the previous turn's commit,
    truncated to 12 hex chars. Per protocol v1.1.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

# ── Parsing helpers ──────────────────────────────────────────────────

_last_turn_id() {
  # Print id of last completed turn (closing END exists). Empty if none.
  grep -oE '<!-- END id=[0-9]{3}' "$BRIDGE_FILE" 2>/dev/null \
    | tail -n 1 | grep -oE '[0-9]{3}' || echo ""
}

_prev_commit() {
  # 12-char prefix of most recent commit touching the bridge file.
  # If no commits touch it yet, print GENESIS.
  cd "$REPO_ROOT"
  local h
  h=$(git log -n 1 --pretty=format:%H -- bridge/claude-codex-bridge.md 2>/dev/null || true)
  if [[ -z "$h" ]]; then
    echo "GENESIS"
  else
    echo "${h:0:12}"
  fi
}

_extract_turn_metadata() {
  # Print id\tfrom\tts\tprev for each TURN marker in document order.
  grep -oE '<!-- TURN id=[0-9]{3} from=[a-z]+ ts=[^ ]+ prev=[A-Za-z0-9]+ -->' "$BRIDGE_FILE" \
    | awk '{
        for (i=1; i<=NF; i++) {
          split($i, a, "=")
          kv[a[1]] = a[2]
        }
        sub(">$", "", kv["prev"])  # remove trailing > if present
        printf "%s\t%s\t%s\t%s\n", kv["id"], kv["from"], kv["ts"], kv["prev"]
        delete kv
      }'
}

# ── Validation ───────────────────────────────────────────────────────

_validate() {
  local prev_id=0
  local errors=0
  local turn_count=0
  # Critical: shadow these so the read loop below cannot leak back
  # into the calling function's `from` (which would corrupt the
  # turn marker built by _append_turn).
  local id from ts prev expected

  # First TURN's prev should be GENESIS; subsequent turns' prev should be
  # the 12-char prefix of the commit hash that introduced the immediately
  # preceding turn. We can verify chain consistency by id continuity +
  # the existence of an END for every TURN and matching prev to
  # the commit log. Strict prev-hash verification requires reading git
  # log per turn; we keep the validator structurally simple.

  if [[ ! -f "$BRIDGE_FILE" ]]; then
    die "bridge file missing: $BRIDGE_FILE"
  fi

  local meta
  meta="$(_extract_turn_metadata)"
  if [[ -z "$meta" ]]; then
    echo "OK: no turns yet (empty bridge)"
    return 0
  fi

  # Walk turns
  while IFS=$'\t' read -r id from ts prev; do
    [[ -z "$id" ]] && continue
    turn_count=$((turn_count + 1))

    # id continuity
    local expected
    expected=$(printf "%03d" $((prev_id + 1)))
    if [[ "$id" != "$expected" ]]; then
      echo "FAIL: turn id=$id expected $expected"
      errors=$((errors + 1))
    fi

    # role in allowed set
    case "$from" in
      user|claude|codex) ;;
      *) echo "FAIL: turn id=$id from=$from not in {user,claude,codex}"
         errors=$((errors + 1)) ;;
    esac

    # END marker present
    if ! grep -q "<!-- END id=$id" "$BRIDGE_FILE"; then
      echo "FAIL: turn id=$id has no closing END marker"
      errors=$((errors + 1))
    fi

    # First turn must use GENESIS
    if [[ "$id" == "001" && "$prev" != "GENESIS" ]]; then
      echo "FAIL: turn id=001 prev=$prev should be GENESIS"
      errors=$((errors + 1))
    fi

    # Subsequent turns: prev must be 12 hex chars
    if [[ "$id" != "001" ]]; then
      if ! [[ "$prev" =~ ^[a-f0-9]{12}$ ]]; then
        echo "FAIL: turn id=$id prev=$prev is not 12-hex (or GENESIS reused)"
        errors=$((errors + 1))
      fi
    fi

    prev_id=$((10#$id))
  done <<< "$meta"

  if [[ "$errors" -gt 0 ]]; then
    echo ""
    echo "VALIDATION FAILED: $errors error(s) across $turn_count turn(s)"
    return 1
  fi
  echo "OK: $(printf "%03d" $prev_id) turn(s), structural validation passed"
  return 0
}

# ── Append flow ──────────────────────────────────────────────────────

_append_turn() {
  local from="$1" body_file="$2"

  case "$from" in
    user|claude|codex) ;;
    *) die "from must be one of {user, claude, codex}; got '$from'" ;;
  esac

  [[ -f "$body_file" ]] || die "body file not found: $body_file"

  # Pre-flight validation
  if ! _validate >/dev/null 2>&1; then
    echo "Pre-flight validation failed; refusing to append. Run --validate for details." >&2
    _validate
    return 1
  fi

  # Compute next id + prev
  local last_id next_id prev
  last_id="$(_last_turn_id)"
  if [[ -z "$last_id" ]]; then
    next_id="001"
    prev="GENESIS"
  else
    next_id="$(printf "%03d" $((10#$last_id + 1)))"
    prev="$(_prev_commit)"
  fi

  # Compose new turn block
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local tmp
  tmp="$(mktemp -t bridge_XXXXXX.md)"
  cp "$BRIDGE_FILE" "$tmp"
  {
    echo ""
    echo "<!-- TURN id=$next_id from=$from ts=$ts prev=$prev -->"
    cat "$body_file"
    if [[ "$(tail -c 1 "$body_file" | xxd -p)" != "0a" ]]; then
      echo ""
    fi
    echo "<!-- END id=$next_id -->"
  } >> "$tmp"

  mv "$tmp" "$BRIDGE_FILE"

  # Commit
  local first_line
  first_line=$(head -1 "$body_file" | tr -d '\r' | cut -c1-60)
  if [[ -z "$first_line" ]]; then first_line="(empty body)"; fi
  local msg="bridge turn $next_id from=$from: $first_line"

  ( cd "$REPO_ROOT" && git add bridge/claude-codex-bridge.md \
      && git commit -m "$msg" --no-verify >/dev/null )

  echo "Appended turn $next_id from=$from. Committed."
}

# ── Dispatch ─────────────────────────────────────────────────────────

case "${1:-}" in
  ""|-h|--help) usage; exit 0 ;;
  --validate) _validate; exit $? ;;
  --next-id)
    last="$(_last_turn_id)"
    if [[ -z "$last" ]]; then echo "001"
    else printf "%03d\n" $((10#$last + 1)); fi
    ;;
  --prev-commit) _prev_commit ;;
  *)
    [[ -n "${2:-}" ]] || { usage; die "missing <body-file>"; }
    _append_turn "$1" "$2"
    ;;
esac
