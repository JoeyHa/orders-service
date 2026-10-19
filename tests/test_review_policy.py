from pathlib import Path

import pytest
from pydantic import ValidationError

from review.policy import load_floors
from review.schema import Finding, Review, max_level

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = """# Review guide

## Risk floors

```json
{
  "paths": {"high": [".github/**"], "medium": ["migrations/**"]},
  "content": {"medium": ["with_for_update", "text\\\\("]},
  "why": {".github/**": "ci", "migrations/**": "schema", "with_for_update": "locks",
          "text\\\\(": "raw sql"}
}
```

## Other section
"""


def test_parses_paths_and_content():
    floors = load_floors(SAMPLE)
    assert floors.paths == {"high": [".github/**"], "medium": ["migrations/**"]}
    assert [p.pattern for p in floors.content["medium"]] == ["with_for_update", "text\\("]
    assert floors.why["migrations/**"] == "schema"


def test_rule_without_a_why_is_rejected():
    with pytest.raises(ValueError, match="why"):
        load_floors(SAMPLE.replace('"migrations/**": "schema", ', ""))


def test_why_for_an_unknown_rule_is_rejected():
    with pytest.raises(ValueError, match="why"):
        load_floors(SAMPLE.replace('"ci"', '"ci", "gone/**": "typo"'))


def test_missing_floors_section_fails_closed():
    with pytest.raises(ValueError, match="Risk floors"):
        load_floors("# Review guide\n\nNo floors here.\n")


def test_unknown_level_is_rejected():
    bad = SAMPLE.replace('"high": [".github/**"]', '"critical": [".github/**"]')
    with pytest.raises(ValueError, match="critical"):
        load_floors(bad)


def test_invalid_regex_is_rejected():
    bad = SAMPLE.replace("with_for_update", "with_for_update(")
    with pytest.raises(ValueError, match="regex"):
        load_floors(bad)


def test_repo_review_md_declares_floors():
    floors = load_floors((ROOT / "REVIEW.md").read_text())
    assert "migrations/**" in floors.paths["medium"]
    assert "REVIEW.md" in floors.paths["high"]


def test_finding_requires_evidence_and_positive_line():
    with pytest.raises(ValidationError):
        Finding(file="app/x.py", line=0, severity="blocking", evidence="x", why="y")
    with pytest.raises(ValidationError):
        Finding(file="app/x.py", line=3, severity="blocking", evidence="", why="y")


def test_unknown_severity_is_rejected():
    with pytest.raises(ValidationError):
        Finding(file="a.py", line=1, severity="critical", evidence="x", why="y")


def test_review_json_schema_is_exposed_for_the_agent():
    schema = Review.model_json_schema()
    assert schema["type"] == "object"
    assert {"summary", "findings"} <= set(schema["required"])


@pytest.mark.parametrize(
    "levels,expected",
    [(["low", "medium"], "medium"), (["high", "low"], "high"), (["low"], "low")],
)
def test_max_level(levels, expected):
    assert max_level(*levels) == expected
