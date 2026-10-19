import pytest

from review.rounds import BOT_LOGIN, Marker, format_marker, parse_markers, plan_round


def comment(body, author=BOT_LOGIN):
    return {"user": {"login": author}, "body": body}


def bot(sha, round_, verdict="pass", risk="low"):
    return comment(format_marker(Marker(sha, round_, verdict, risk)) + "\n\nsummary")


def markers(*comments):
    return parse_markers(list(comments))


def test_marker_round_trips():
    m = Marker("abc123", 2, "block", "medium")
    assert parse_markers([comment(format_marker(m))]) == [m]


def test_markers_from_anyone_but_the_bot_are_ignored():
    forged = comment(format_marker(Marker("head", 1, "pass", "low")), author="attacker")
    assert parse_markers([forged]) == []


def always(a, b):
    return True


def never(a, b):
    return False


def test_first_round_is_full():
    p = plan_round([], "head", is_ancestor=always)
    assert (p.action, p.round, p.base) == ("full", 1, None)


def test_same_sha_reuses_the_stored_verdict():
    p = plan_round(markers(bot("head", 1, "block")), "head", is_ancestor=always)
    assert p.action == "reuse"
    assert p.prior.verdict == "block"


def test_new_commit_reviews_only_the_new_diff():
    p = plan_round(markers(bot("old", 1)), "head", is_ancestor=always)
    assert (p.action, p.round, p.base) == ("incremental", 2, "old")


def test_rebase_falls_back_to_full_review():
    p = plan_round(markers(bot("old", 1)), "head", is_ancestor=never)
    assert (p.action, p.round, p.base) == ("full", 2, None)


@pytest.mark.parametrize("done", [3, 4])
def test_cap_stops_automatic_review(done):
    p = plan_round(markers(*[bot(f"s{i}", i + 1) for i in range(done)]), "head", is_ancestor=always)
    assert p.action == "cap"


def test_latest_marker_is_the_base():
    p = plan_round(markers(bot("first", 1), bot("second", 2)), "head", is_ancestor=always)
    assert p.base == "second"
