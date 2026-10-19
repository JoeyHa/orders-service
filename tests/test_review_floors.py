from review.policy import load_floors
from review.risk import apply_floors

FLOORS = load_floors(
    """## Risk floors

```json
{
  "paths": {"high": [".github/**", "REVIEW.md"], "medium": ["migrations/**", "app/auth.py"]},
  "content": {"medium": ["with_for_update", "\\\\b(DROP|ALTER)\\\\b"]}
}
```
"""
)


def diff(path: str, *lines: str, old: str | None = None, new: str | None = None) -> str:
    old = old or f"a/{path}"
    new = new or f"b/{path}"
    body = "\n".join(lines)
    return f"diff --git a/{path} b/{path}\n--- {old}\n+++ {new}\n@@ -1,2 +1,2 @@\n{body}\n"


def test_docs_only_change_is_low():
    level, reasons = apply_floors(diff("README.md", "+more docs"), FLOORS)
    assert (level, reasons) == ("low", [])


def test_path_rule_sets_floor_with_reason():
    level, reasons = apply_floors(diff("migrations/versions/0002.py", "+x = 1"), FLOORS)
    assert level == "medium"
    assert reasons == ["migrations/versions/0002.py matches migrations/** (medium)"]


def test_highest_floor_wins():
    d = diff("app/auth.py", "+x") + diff(".github/workflows/ci.yml", "+y")
    level, _ = apply_floors(d, FLOORS)
    assert level == "high"


def test_deleted_file_is_checked_by_its_old_path():
    level, _ = apply_floors(diff("app/auth.py", "-gone", new="/dev/null"), FLOORS)
    assert level == "medium"


def test_removed_line_triggers_content_rule():
    d = diff("app/api/orders.py", "-    stmt = stmt.with_for_update()", "+    stmt = stmt")
    level, reasons = apply_floors(d, FLOORS)
    assert level == "medium"
    assert reasons == ["app/api/orders.py: changed line matches with_for_update (medium)"]


def test_content_rule_respects_word_boundaries():
    level, _ = apply_floors(diff("app/ui.py", "+dropdown = 1"), FLOORS)
    assert level == "low"


def test_diff_headers_are_not_scanned_as_content():
    # the file name matches \bALTER\b, but only changed lines count
    level, _ = apply_floors(diff("docs/ALTER.md", "+hello"), FLOORS)
    assert level == "low"


def test_each_rule_is_reported_once_per_file():
    d = diff("app/x.py", "+a.with_for_update()", "+b.with_for_update()")
    _, reasons = apply_floors(d, FLOORS)
    assert len(reasons) == 1


def test_added_line_that_looks_like_a_header_is_still_content():
    # "+++ x" inside a hunk is an added line starting with "++ ", not a file header
    d = (
        "--- a/app/x.py\n+++ b/app/x.py\n@@ -1,1 +1,3 @@\n keep\n"
        "+++ stmt.with_for_update()\n"
        "+-- ALTER TABLE orders\n"
    )
    level, reasons = apply_floors(d, FLOORS)
    assert level == "medium"
    assert {r.split(":")[0] for r in reasons} == {"app/x.py"}


def test_pure_rename_without_content_change_hits_path_floor():
    d = (
        "diff --git a/app/auth.py b/app/security.py\n"
        "similarity index 100%\nrename from app/auth.py\nrename to app/security.py\n"
    )
    assert apply_floors(d, FLOORS)[0] == "medium"


def test_empty_or_mode_only_change_hits_path_floor():
    d = (
        "diff --git a/.github/workflows/x.yml b/.github/workflows/x.yml\n"
        "new file mode 100644\nindex 0000000..e69de29\n"
    )
    assert apply_floors(d, FLOORS)[0] == "high"


def test_unicode_line_separator_cannot_hide_content():
    # str.splitlines() also splits on U+2028; a diff line ends only at "\n"
    d = "--- a/app/x.py\n+++ b/app/x.py\n@@ -0,0 +1,1 @@\n+x = 1 ALTER TABLE orders\n"
    assert apply_floors(d, FLOORS)[0] == "medium"


def test_git_quoted_non_ascii_path_still_hits_path_floor():
    # git C-quotes unusual names: "a/.github/workflows/\303\274.yml"
    q = '"a/.github/workflows/\\303\\274.yml" "b/.github/workflows/\\303\\274.yml"'
    d = f"diff --git {q}\nnew file mode 100644\n"
    assert apply_floors(d, FLOORS)[0] == "high"


def test_git_quoted_path_in_file_headers():
    d = (
        'diff --git "a/app/auth \\"v2\\".py" "b/app/auth \\"v2\\".py"\n'
        '--- "a/app/auth \\"v2\\".py"\n+++ "b/app/auth \\"v2\\".py"\n'
        "@@ -0,0 +1,1 @@\n+stmt.with_for_update()\n"
    )
    _, reasons = apply_floors(d, FLOORS)
    assert reasons == ['app/auth "v2".py: changed line matches with_for_update (medium)']
