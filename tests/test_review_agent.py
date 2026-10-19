import asyncio
import os
from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage

from review.agent import AgentError, make_guard, run_structured
from review.schema import RiskVerdict


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "pr").mkdir()
    (tmp_path / "pr" / "app.py").write_text("x = 1\n")
    (tmp_path / "secret.txt").write_text("token\n")
    return tmp_path / "pr"


def decide(root: Path, tool: str, **tool_input) -> str:
    out = asyncio.run(make_guard(root)({"tool_name": tool, "tool_input": tool_input}, None, None))
    return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")


def test_reads_inside_the_checkout_are_allowed(root):
    assert decide(root, "Read", file_path=str(root / "app.py")) == "allow"
    assert decide(root, "Read", file_path="app.py") == "allow"
    assert decide(root, "Grep", pattern="x", path="app.py") == "allow"
    assert decide(root, "Glob", pattern="**/*.py") == "allow"


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Read", {"file_path": "/proc/self/environ"}),  # the process env holds the token
        ("Read", {"file_path": "../secret.txt"}),
        ("Grep", {"pattern": "token", "path": "/"}),
        ("Glob", {"pattern": "/etc/**"}),
        ("Glob", {"pattern": "../**"}),
    ],
)
def test_reads_outside_the_checkout_are_denied(root, tool, tool_input):
    assert decide(root, tool, **tool_input) == "deny"


def test_symlink_escaping_the_checkout_is_denied(root):
    os.symlink(root.parent / "secret.txt", root / "innocent.md")
    assert decide(root, "Read", file_path="innocent.md") == "deny"


@pytest.mark.parametrize("tool", ["Bash", "Write", "Edit", "WebFetch", "Agent", "SomeFutureTool"])
def test_every_other_tool_is_denied(root, tool):
    assert decide(root, tool, command="cat /proc/self/environ", file_path="app.py") == "deny"


def result(**kw) -> ResultMessage:
    base = dict(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
        num_turns=1, session_id="s", total_cost_usd=0.01,
    )  # fmt: skip
    return ResultMessage(**(base | kw))


def fake_query(*messages, seen: dict | None = None):
    async def query(*, prompt, options):
        if seen is not None:
            seen["prompt"], seen["options"] = prompt, options
        for m in messages:
            yield m

    return query


def run(root, q):
    return asyncio.run(
        run_structured("p", RiskVerdict, model="m", system_prompt="s", root=root, query_fn=q)
    )


def test_returns_validated_output_and_cost(root):
    out = {"level": "medium", "reasons": ["x"], "evidence": ["app.py:1"]}
    verdict, cost = run(root, fake_query(result(structured_output=out)))
    assert verdict == RiskVerdict(**out)
    assert cost == 0.01


def test_locks_down_options(root):
    seen: dict = {}
    run(root, fake_query(result(structured_output={"level": "low", "reasons": []}), seen=seen))
    o = seen["options"]
    assert o.setting_sources == []  # never load .claude/ or CLAUDE.md from the PR
    assert o.permission_mode == "dontAsk"
    assert "Bash" in o.disallowed_tools
    assert o.cwd == str(root)
    assert o.output_format["type"] == "json_schema"
    assert o.hooks["PreToolUse"]


@pytest.mark.parametrize(
    "messages",
    [
        (),  # no result at all
        (result(subtype="error_max_structured_output_retries"),),
        (result(is_error=True, structured_output={"level": "low", "reasons": []}),),
        (result(structured_output=None),),  # "success" without output still fails
        (result(structured_output={"level": "catastrophic", "reasons": []}),),
    ],
)
def test_any_bad_result_fails_closed(root, messages):
    with pytest.raises(AgentError):
        run(root, fake_query(*messages))
