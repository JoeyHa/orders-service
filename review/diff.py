"""Parse unified diffs by structure, not by line prefix.

Inside a hunk, every line is content: an added line whose text starts with "++ " shows up as
"+++ ...", which a prefix check would mistake for a file header. The hunk header's line counts
say exactly how many lines belong to the hunk.
"""

import re
from dataclasses import dataclass

_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


@dataclass(frozen=True)
class DiffLine:
    path: str  # new path, or the old path for a deleted file
    kind: str  # "+", "-" or " "
    new_line: int | None  # new-side line number for "+" and " "
    text: str


def _name(raw: str) -> str | None:
    if raw == "/dev/null":
        return None
    return raw[2:] if raw[:2] in ("a/", "b/") else raw


def parse_diff(diff: str) -> tuple[set[str], list[DiffLine]]:
    """All touched paths (old and new names) and every hunk line."""
    paths: set[str] = set()
    lines: list[DiffLine] = []
    old = new = None
    old_left = new_left = n = 0
    for raw in diff.splitlines():
        if (old_left > 0 or new_left > 0) and raw[:1] not in ("+", "-", " ", "\\"):
            old_left = new_left = 0  # malformed counts: hunk lines never start otherwise
        if old_left > 0 or new_left > 0:
            kind, text, path = raw[:1], raw[1:], new or old
            if kind == "+":
                lines.append(DiffLine(path, "+", n, text))
                n, new_left = n + 1, new_left - 1
            elif kind == "-":
                lines.append(DiffLine(path, "-", None, text))
                old_left -= 1
            elif kind == " ":
                lines.append(DiffLine(path, " ", n, text))
                n, old_left, new_left = n + 1, old_left - 1, new_left - 1
            continue  # "\ No newline at end of file" and anything else: not a line
        if raw.startswith("diff "):
            old = new = None
            # renames, empty files and mode changes have no ---/+++ lines; git always prints this
            if match := _GIT_HEADER.match(raw):
                paths.update(match.groups())
        elif raw.startswith(("rename from ", "rename to ")):
            paths.add(raw.split(" ", 2)[2])
        elif raw.startswith("--- "):
            old = _name(raw[4:])
        elif raw.startswith("+++ "):
            new = _name(raw[4:])
            paths.update(p for p in (old, new) if p)
        elif match := _HUNK.match(raw):
            old_left = int(match.group(1) or 1)
            n = int(match.group(2))
            new_left = int(match.group(3) or 1)
    return paths, lines
