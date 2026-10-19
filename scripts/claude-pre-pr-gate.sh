#!/bin/sh
# Claude Code PreToolUse hook: block `gh pr create` until /pre-pr passed for HEAD.
# Pushes are allowed (WIP backup and sharing); review is gated where a PR is opened.
# Matches only as a command (line start or after ; & |), not as text inside strings.
# shortcut: misses wrapped forms (`sh -c ...`) and PRs opened outside Claude Code; the CI review (L5) is the backstop.
# Fails open on python errors on purpose: this runs on every Bash call, failing closed would block all of them.
python3 -c '
import json, re, sys
cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
gated = re.search(r"(?:^|[;&|])\s*gh\s+pr\s+create\b", cmd, re.M)
sys.exit(0 if gated else 1)
' || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
"$(dirname "$0")/check-pre-pr.sh" || exit 2  # exit 2 blocks the tool call and shows stderr to Claude
