#!/usr/bin/env python3
"""Starter command-hook for current Claude Code hook input/output semantics.

The only protocol requirements are JSON on stdin, an appropriate exit code,
and (for structured control) exactly one JSON object on stdout. Python and the
modules below are implementation choices, not Anthropic requirements.
"""

from __future__ import annotations

import json
import sys
from typing import Any


JsonObject = dict[str, Any]


def emit(payload: JsonObject) -> None:
    """Write the sole structured response to stdout."""
    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


def hook_output(event: str, **fields: Any) -> JsonObject:
    """Build an event-specific response with the required event-name tag."""
    return {"hookSpecificOutput": {"hookEventName": event, **fields}}


def handle_pre_tool_use(data: JsonObject) -> JsonObject | None:
    """Demonstrate deterministic validation before a tool runs."""
    if data.get("tool_name") != "Bash":
        return None

    tool_input = data.get("tool_input")
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    # Replace this small demonstration policy with a parser appropriate to your
    # environment. Never interpolate an untrusted command into another shell.
    blocked_fragments = ("rm -rf /", "git push --force", "git reset --hard")
    if any(fragment in command for fragment in blocked_fragments):
        return hook_output(
            "PreToolUse",
            permissionDecision="deny",
            permissionDecisionReason="Project policy rejected a destructive command.",
        )

    # Omitting permissionDecision leaves the normal permission system in charge.
    return None


def handle_post_tool_use(data: JsonObject) -> JsonObject | None:
    """Demonstrate a factual handoff that Claude sees on its next model call."""
    if data.get("tool_name") not in {"Write", "Edit"}:
        return None

    tool_input = data.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or not file_path:
        return None

    return hook_output(
        "PostToolUse",
        additionalContext=f"The file changed in this tool call was {file_path}.",
    )


def handle_stop(data: JsonObject) -> JsonObject | None:
    """Show the mandatory recursion guard for any Stop continuation policy."""
    if data.get("stop_hook_active"):
        return None

    # Add a deterministic completion check here. To allow stopping, return no
    # JSON. To continue, return for example:
    # return {"decision": "block", "reason": "Run the required tests first."}
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # stderr is diagnostic output. Exit 1 is non-blocking for most events;
        # choose a deliberate fail-closed policy only after checking the event.
        print(f"invalid hook input: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("invalid hook input: expected a JSON object", file=sys.stderr)
        return 1

    event = data.get("hook_event_name")
    handlers = {
        "PreToolUse": handle_pre_tool_use,
        "PostToolUse": handle_post_tool_use,
        "Stop": handle_stop,
    }
    handler = handlers.get(event)
    response = handler(data) if handler else None

    if response is not None:
        emit(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
