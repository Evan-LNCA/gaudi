from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaudi.ledger import (
    Ledger,
    detect_arm,
    gaudi_section_text,
    handle_hook,
    load_ledger_config,
    try_record_query,
)
from gaudi.mapgen import generate, load_config
from gaudi.paths import CONFIG_REL, CURSOR_RULE_MARKER, LEDGER_FILE, RULE_REL, token_count, tokens_from_size
from gaudi.query import run_focus, run_index, run_where


def test_generate_records_query_and_source_bytes(git_repo: Path) -> None:
    result = generate(git_repo)
    assert "a.py" in result.source_bytes
    assert "b.py" in result.source_bytes
    assert result.baseline_tokens == sum(tokens_from_size(size) for size in result.source_bytes.values())
    assert result.saved_tokens == max(result.baseline_tokens - result.tokens, 0)
    led = Ledger(git_repo)
    try:
        snaps = led.snapshots()
    finally:
        led.close()
    assert any(q.cmd == "generate" for q in snaps.queries)
    gen = next(q for q in snaps.queries if q.cmd == "generate")
    assert gen.baseline_tokens == result.baseline_tokens
    assert gen.emitted_tokens == result.tokens
    assert gen.oriented


def test_focus_where_index_json_baselines(git_repo: Path) -> None:
    generate(git_repo)
    focused = run_focus(git_repo, ["b.py"], tokens=128, fmt="json")
    payload = json.loads(focused.text)
    assert payload["baseline_tokens"] > 0
    assert payload["saved_tokens"] == max(payload["baseline_tokens"] - payload["tokens"], 0)
    shown = {row["path"] for row in payload["files"]}
    for path in shown:
        assert path in focused.source_bytes

    where = run_where(git_repo, "foo", fmt="json")
    where_payload = json.loads(where.text)
    a_tokens = tokens_from_size((git_repo / "a.py").stat().st_size)
    assert where_payload["baseline_tokens"] == a_tokens
    assert where_payload["saved_tokens"] == max(
        where_payload["baseline_tokens"] - where_payload["tokens"], 0
    )

    idx = run_index(git_repo, fmt="json")
    index_payload = json.loads(idx.text)
    map_tokens = token_count((git_repo / ".map").read_text(encoding="utf-8"))
    assert index_payload["baseline_tokens"] == map_tokens
    assert "saved_tokens" in index_payload


def test_ledger_disabled_skips_rows(git_repo: Path) -> None:
    generate(git_repo)
    cfg = git_repo / CONFIG_REL
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["ledger"] = {"enabled": False}
    cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    run_focus(git_repo, ["foo"], tokens=64)
    led = Ledger(git_repo)
    try:
        n_focus = sum(1 for q in led.snapshots().queries if q.cmd == "focus")
    finally:
        led.close()
    assert n_focus == 0


def test_load_config_ledger_fail_fast(git_repo: Path) -> None:
    generate(git_repo)
    cfg = git_repo / CONFIG_REL
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["ledger"] = {"enabled": "yes"}
    cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ledger.enabled"):
        load_config(git_repo)
    data["ledger"] = ["nope"]
    cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ledger must be an object"):
        load_config(git_repo)


def test_handle_hook_cursor_read_and_repeat(git_repo: Path) -> None:
    src = git_repo / "a.py"
    content = src.read_text(encoding="utf-8")
    payload = {
        "hookEventName": "beforeReadFile",
        "sessionId": "sess-1",
        "workspace_roots": [str(git_repo)],
        "file_path": str(src),
        "content": content,
    }
    out = handle_hook(payload, harness="cursor", event_hint="beforeReadFile", root=git_repo)
    assert out == {"permission": "allow"}
    out2 = handle_hook(payload, harness="cursor", event_hint="beforeReadFile", root=git_repo)
    assert out2 == {"permission": "allow"}
    led = Ledger(git_repo)
    try:
        snaps = led.snapshots()
    finally:
        led.close()
    assert len(snaps.reads) == 2
    assert snaps.reads[0].first_read is True
    assert snaps.reads[1].first_read is False
    assert snaps.sessions[0].harness == "cursor"


def test_handle_hook_claude_hashes_from_disk(git_repo: Path) -> None:
    src = git_repo / "b.py"
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "claude-sess",
        "cwd": str(git_repo),
        "tool_name": "Read",
        "tool_input": {"file_path": str(src)},
    }
    out = handle_hook(payload, harness="claude", root=git_repo)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    led = Ledger(git_repo)
    try:
        snaps = led.snapshots()
    finally:
        led.close()
    assert len(snaps.reads) == 1
    assert snaps.reads[0].tokens == token_count(src.read_text(encoding="utf-8"))


def test_shell_attributes_unscoped_query(git_repo: Path) -> None:
    generate(git_repo)
    handle_hook(
        {
            "hookEventName": "afterShellExecution",
            "conversation_id": "sess-shell",
            "command": "gaudi generate",
            "workspace_roots": [str(git_repo)],
        },
        harness="cursor",
        event_hint="afterShellExecution",
        root=git_repo,
    )
    led = Ledger(git_repo)
    try:
        snaps = led.snapshots()
    finally:
        led.close()
    gens = [q for q in snaps.queries if q.cmd == "generate"]
    assert gens
    assert gens[0].conversation_id == "sess-shell"


def test_session_start_cursor_does_not_inject_context(git_repo: Path) -> None:
    out = handle_hook(
        {
            "hookEventName": "sessionStart",
            "sessionId": "s-ctx",
            "workspace_roots": [str(git_repo)],
        },
        harness="cursor",
        event_hint="sessionStart",
        root=git_repo,
    )
    assert "additional_context" not in out
    assert out.get("env", {}).get("GAUDI_CONVERSATION_ID") == "s-ctx"


def test_gaudi_section_stops_at_next_heading() -> None:
    text = "## Intro\n\n## Gaudi Map\nbody\n\n## Other\nrest\n"
    section = gaudi_section_text(text)
    assert section.startswith("## Gaudi Map")
    assert "body" in section
    assert "## Other" not in section


def test_detect_arm_from_marker(git_repo: Path) -> None:
    generate(git_repo)
    cfg = load_ledger_config(git_repo)
    assert detect_arm(git_repo, "cursor", cfg) == "off"
    rule = git_repo / RULE_REL
    rule.parent.mkdir(parents=True, exist_ok=True)
    rule.write_text(f"{CURSOR_RULE_MARKER}\n", encoding="utf-8")
    assert detect_arm(git_repo, "cursor", cfg) == "on"


def test_try_record_query_respects_enabled(tmp_path: Path) -> None:
    try_record_query(tmp_path, "focus", 1, 10, [("a.py", 10)], enabled=False)
    assert not (tmp_path / LEDGER_FILE).is_file()
