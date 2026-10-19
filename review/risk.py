"""L4: decide a PR's risk. Deterministic floors first; models may only raise the level."""

from fnmatch import fnmatchcase

from review.policy import Floors
from review.schema import Level, max_level


def _changed_files(diff: str) -> dict[str, list[str]]:
    """Map each touched path (old and new names) to its added/removed lines."""
    files: dict[str, list[str]] = {}
    current: list[str] = []
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ")):
            name = line[4:]
            if name != "/dev/null":
                path = name[2:] if name[:2] in ("a/", "b/") else name
                current = files.setdefault(path, [])
        elif line.startswith(("+", "-")):
            current.append(line[1:])
    return files


def apply_floors(diff: str, floors: Floors) -> tuple[Level, list[str]]:
    level: Level = "low"
    reasons: list[str] = []
    for path, lines in _changed_files(diff).items():
        for rule_level, globs in floors.paths.items():
            for glob in globs:
                if fnmatchcase(path, glob):
                    level = max_level(level, rule_level)
                    reasons.append(f"{path} matches {glob} ({rule_level})")
        for rule_level, patterns in floors.content.items():
            for pattern in patterns:
                if any(pattern.search(line) for line in lines):
                    level = max_level(level, rule_level)
                    reasons.append(f"{path}: changed line matches {pattern.pattern} ({rule_level})")
    return level, reasons
