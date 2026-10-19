"""Parse unified diffs by structure, not by line prefix.

Inside a hunk, every line is content: an added line whose text starts with "++ " shows up as
"+++ ...", which a prefix check would mistake for a file header. The hunk header's line counts
say exactly how many lines belong to the hunk.
"""

import codecs
import re
from dataclasses import dataclass

_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_GIT_HEADER = re.compile(rf"^diff --git ({_QUOTED}) ({_QUOTED})$")


@dataclass(frozen=True)
class DiffLine:
    path: str  # new path, or the old path for a deleted file
    kind: str  # "+", "-" or " "
    new_line: int | None  # new-side line number for "+" and " "
    text: str


def _unquote(raw: str) -> str:
    """Git C-quotes unusual names ("a/\\303\\274.yml"); undo it so path rules still match."""
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return codecs.escape_decode(raw[1:-1].encode())[0].decode("utf-8", "replace")
    return raw


def _name(raw: str) -> str | None:
    raw = _unquote(raw)
    if raw == "/dev/null":
        return None
    return raw[2:] if raw[:2] in ("a/", "b/") else raw


def _header_paths(rest: str) -> set[str]:
    """Paths from an unquoted "a/X b/Y" header, which is ambiguous when X contains " b/"."""
    n = (len(rest) - 5) // 2  # same name twice: "a/" + X + " b/" + X
    if (
        n > 0
        and rest.startswith("a/")
        and rest[2 : 2 + n] == rest[-n:]
        and rest[2 + n : 5 + n] == " b/"
    ):
        return {rest[2 : 2 + n]}
    # otherwise record every possible split: an extra path can only raise the floor
    paths = set()
    for i in range(len(rest)):
        if rest.startswith(" b/", i) and rest.startswith("a/"):
            paths.update({rest[2:i], rest[i + 3 :]})
    return paths


def parse_diff(diff: str) -> tuple[set[str], list[DiffLine]]:
    """All touched paths (old and new names) and every hunk line."""
    paths: set[str] = set()
    lines: list[DiffLine] = []
    old = new = None
    old_left = new_left = n = 0
    for raw in diff.split("\n"):  # not splitlines(): U+2028 etc. are content, not line ends
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
                paths.update(p for p in map(_name, match.groups()) if p)
            elif raw.startswith("diff --git "):
                paths.update(_header_paths(raw[len("diff --git ") :]))
        elif raw.startswith(("rename from ", "rename to ")):
            paths.add(_unquote(raw.split(" ", 2)[2]))
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
