from __future__ import annotations

from gaudi.ledger import fail_open_stdout, gaudi_subcommand, normalize


def test_normalize_cursor_camelcase_before_read() -> None:
    event = normalize(
        {
            "hookEventName": "beforeReadFile",
            "sessionId": "c-1",
            "generation_id": "g-9",
            "file_path": "src/app.py",
            "content": "print(1)\n",
        }
    )
    assert event.kind == "read"
    assert event.event_name == "beforeReadFile"
    assert event.conversation_id == "c-1"
    assert event.generation_id == "g-9"
    assert event.path == "src/app.py"
    assert event.content == "print(1)\n"


def test_normalize_cursor_conversation_id_variant() -> None:
    event = normalize(
        {
            "hook_event_name": "beforeReadFile",
            "conversation_id": "conv-2",
            "file_path": "/abs/a.py",
            "content": "x = 1\n",
        }
    )
    assert event.kind == "read"
    assert event.conversation_id == "conv-2"
    assert event.path == "/abs/a.py"


def test_normalize_claude_snake_case_read() -> None:
    event = normalize(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "claude-1",
            "tool_name": "Read",
            "tool_input": {"file_path": "src/a.py"},
        }
    )
    assert event.kind == "read"
    assert event.conversation_id == "claude-1"
    assert event.path == "src/a.py"
    assert event.content is None
    assert event.tool_name == "Read"


def test_normalize_copilot_filepath_sessionid() -> None:
    event = normalize(
        {
            "hookEventName": "PreToolUse",
            "sessionId": "cop-1",
            "tool_name": "read_file",
            "tool_input": {"filePath": "pkg/mod.py"},
        }
    )
    assert event.kind == "read"
    assert event.conversation_id == "cop-1"
    assert event.path == "pkg/mod.py"
    assert event.tool_name == "read_file"


def test_normalize_copilot_mixed_session_id_filepath() -> None:
    event = normalize(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "cop-2",
            "toolName": "view",
            "toolInput": {"filePath": "lib.ts"},
        }
    )
    assert event.kind == "read"
    assert event.conversation_id == "cop-2"
    assert event.path == "lib.ts"


def test_normalize_event_hint_when_name_missing() -> None:
    event = normalize({"file_path": "a.py", "content": "a"}, event_hint="beforeReadFile")
    assert event.kind == "read"
    assert event.event_name == "beforeReadFile"


def test_normalize_shell_cursor_and_claude_gaudi() -> None:
    cursor = normalize(
        {
            "hookEventName": "afterShellExecution",
            "conversation_id": "c-1",
            "command": "gaudi focus a.py",
        }
    )
    assert cursor.kind == "shell"
    assert cursor.command == "gaudi focus a.py"
    claude = normalize(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s-1",
            "tool_name": "Bash",
            "tool_input": {"command": "python -m gaudi index"},
        }
    )
    assert claude.kind == "shell"
    assert gaudi_subcommand(claude.command or "") == "index"


def test_normalize_copilot_run_in_terminal() -> None:
    event = normalize(
        {
            "hookEventName": "PostToolUse",
            "sessionId": "cop-3",
            "tool_name": "run_in_terminal",
            "tool_input": {"command": "gaudi where foo"},
        }
    )
    assert event.kind == "shell"
    assert gaudi_subcommand(event.command or "") == "where"


def test_normalize_ignores_non_read_pretooluse() -> None:
    event = normalize(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s",
            "tool_name": "Edit",
            "tool_input": {"file_path": "a.py"},
        }
    )
    assert event.kind == "other_tool"


def test_fail_open_never_empty_on_read_path() -> None:
    cursor = normalize({"hookEventName": "beforeReadFile", "file_path": "a.py"})
    assert fail_open_stdout(cursor, "cursor") == {"permission": "allow"}
    claude = normalize(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "a.py"},
        }
    )
    assert fail_open_stdout(claude, "claude") == {
        "hookSpecificOutput": {"permissionDecision": "allow"}
    }
    copilot = normalize(
        {
            "hookEventName": "PreToolUse",
            "tool_name": "read_file",
            "tool_input": {"filePath": "a.py"},
        }
    )
    assert fail_open_stdout(copilot, "copilot") == {
        "hookSpecificOutput": {"permissionDecision": "allow"}
    }


def test_fail_open_session_may_be_empty() -> None:
    event = normalize({"hook_event_name": "SessionEnd", "session_id": "s"})
    assert fail_open_stdout(event, "claude") == {}
