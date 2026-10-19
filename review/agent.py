"""Run one agent call with structured output, read-only and confined to the PR checkout.

Defense in depth: the PreToolUse hook is the allowlist (it runs first and its deny wins in
every mode); disallowed_tools removes the obvious tools from context; dontAsk denies anything
that would prompt; setting_sources=[] stops the PR from configuring its own reviewer.
"""

import os
from collections.abc import Callable
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage, query
from pydantic import BaseModel, ValidationError

READ_TOOLS = ("Read", "Grep", "Glob")
ANSWER_TOOL = "StructuredOutput"  # the SDK returns output_format results through this tool
DENIED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Task"]


class AgentError(RuntimeError):
    """The agent did not return valid structured output; callers fail closed."""


def _inside(root: Path, raw: str | None) -> bool:
    if not raw:
        return True  # Grep/Glob default to the cwd, which is root
    path = Path(raw) if os.path.isabs(raw) else root / raw
    resolved = path.resolve()  # follows symlinks, so a link out of the checkout is caught
    return resolved == root or root in resolved.parents


def make_guard(root: Path):
    root = root.resolve()

    async def guard(input_data, tool_use_id, context):
        tool = input_data.get("tool_name")
        if tool == ANSWER_TOOL:
            return {}
        args = input_data.get("tool_input") or {}
        targets = [args.get("file_path") or args.get("path")]
        if tool == "Glob":
            targets.append(os.path.dirname(args.get("pattern", "")) or None)
        if tool in READ_TOOLS and all(_inside(root, t) for t in targets):
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"review agents may only read files inside {root}",
            }
        }

    return guard


async def run_structured[T: BaseModel](
    prompt: str,
    schema: type[T],
    *,
    model: str,
    system_prompt: str,
    root: Path,
    max_turns: int = 30,
    query_fn: Callable = query,
) -> tuple[T, float | None]:
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        cwd=str(root),
        allowed_tools=list(READ_TOOLS),
        disallowed_tools=DENIED_TOOLS,
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=max_turns,
        output_format={"type": "json_schema", "schema": schema.model_json_schema()},
        hooks={"PreToolUse": [HookMatcher(hooks=[make_guard(root)])]},
    )
    final = None
    async for message in query_fn(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            final = message
    if final is None or final.subtype != "success" or final.is_error:
        raise AgentError(f"agent run failed: {final.subtype if final else 'no result'}")
    if final.structured_output is None:
        raise AgentError("agent finished without structured output")
    try:
        return schema.model_validate(final.structured_output), final.total_cost_usd
    except ValidationError as e:
        raise AgentError(f"agent output does not match {schema.__name__}: {e}") from e
