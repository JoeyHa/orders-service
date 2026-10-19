#!/bin/sh
# Exit 0 if the pre-pr review (written by the Claude Code pre-pr skill) passed for HEAD.
# shortcut: checks HEAD only, not every ref being pushed; fine for one-branch-at-a-time pushes.
head=$(git rev-parse HEAD) || exit 1
git merge-base --is-ancestor "$head" origin/main 2>/dev/null && exit 0  # nothing new to review

marker="$(git rev-parse --git-dir)/pre-pr-review"
if [ -f "$marker" ] && [ "$(sed -n 1p "$marker")" = "$head" ] && [ "$(sed -n 2p "$marker")" = "PASS" ]; then
  exit 0
fi
echo "pre-pr review missing, blocked, or stale for $head. Run /pre-pr in Claude Code first." >&2
exit 1
