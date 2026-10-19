#!/bin/sh
# Claude Code PreToolUse hook: block `git push` / `gh pr create` until /pre-pr passed for HEAD.
input=$(cat)
case "$input" in
  *"git push"* | *"gh pr create"*) ;;
  *) exit 0 ;;
esac
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
"$(dirname "$0")/check-pre-pr.sh" || exit 2  # exit 2 blocks the tool call and shows stderr to Claude
