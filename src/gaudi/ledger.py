from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gaudi.paths import (
    CONFIG_REL,
    CURSOR_RULE_MARKER,
    GAUDI_MD_MARKER,
    LEDGER_FILE,
    MAP_REL,
    LedgerConfig,
    instruction_rel_for_harness,
    parse_ledger_config,
    token_count,
    under,
)
from gaudi.scorecard import (
    CompactionSnap,
    QuerySnap,
    ReadSnap,
    ScorecardInput,
    SessionSnap,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  conversation_id TEXT PRIMARY KEY,
  harness TEXT NOT NULL,
  arm TEXT NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL,
  turns INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY,
  conversation_id TEXT,
  ts REAL NOT NULL,
  cmd TEXT NOT NULL,
  emitted_tokens INTEGER NOT NULL,
  baseline_tokens INTEGER NOT NULL,
  turn INTEGER
);
CREATE TABLE IF NOT EXISTS oriented (
  query_id INTEGER NOT NULL,
  path TEXT NOT NULL,
  source_tokens INTEGER NOT NULL,
  FOREIGN KEY (query_id) REFERENCES queries(id)
);
CREATE TABLE IF NOT EXISTS reads (
  id INTEGER PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  ts REAL NOT NULL,
  path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  tokens INTEGER NOT NULL,
  turn INTEGER,
  first_read INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS compactions (
  conversation_id TEXT NOT NULL,
  ts REAL NOT NULL,
  context_tokens INTEGER,
  context_window_size INTEGER,
  message_count INTEGER
);
CREATE TABLE IF NOT EXISTS generations (
  conversation_id TEXT NOT NULL,
  generation_id TEXT NOT NULL,
  turn INTEGER NOT NULL,
  PRIMARY KEY (conversation_id, generation_id)
);
"""

_HEAD_RE = re.compile(r"^head:\s*(\S+)\s*$", re.M)
_GAUDI_CMD_RE = re.compile(r"\bgaudi(?:\s+-m\s+gaudi)?\s+(generate|index|focus|where)\b")
_PYTHON_GAUDI_RE = re.compile(
    r"\bpython(?:3|\s+-m)?\s+gaudi\s+(generate|index|focus|where)\b"
)

READ_TOOLS = frozenset(
    {
        "Read",
        "read",
        "read_file",
        "readFile",
        "view",
        "View",
        "view_file",
        "viewFile",
        "view_files",
        "viewFiles",
    }
)
SHELL_TOOLS = frozenset(
    {
        "Bash",
        "bash",
        "shell",
        "Shell",
        "run_in_terminal",
        "runInTerminal",
        "execute",
        "PowerShell",
        "powershell",
    }
)
_KIND_BY_EVENT = {
    "beforereadfile": "read",
    "pretooluse": "pre_tool",
    "posttooluse": "post_tool",
    "aftershellexecution": "shell",
    "beforeshellexecution": "shell",
    "sessionstart": "session_start",
    "sessionend": "session_end",
    "stop": "session_end",
    "precompact": "compact",
    "userpromptsubmit": "prompt",
}


@dataclass(frozen=True)
class LedgerEvent:
    kind: str
    event_name: str
    conversation_id: str | None
    generation_id: str | None
    path: str | None
    content: str | None
    command: str | None
    tool_name: str | None
    context_tokens: int | None
    context_window_size: int | None
    message_count: int | None


def _get(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _norm_event_name(name: str) -> str:
    return name.replace("_", "").replace("-", "").lower()


def _conversation_id(raw: dict[str, Any]) -> str | None:
    return _as_str(
        _get(raw, "conversation_id", "session_id", "sessionId", "conversationId")
    )


def _tool_name(raw: dict[str, Any], tool_input: dict[str, Any]) -> str | None:
    return _as_str(
        _get(raw, "tool_name", "toolName", "tool") or _get(tool_input, "tool_name", "toolName")
    )


def _read_path(raw: dict[str, Any], tool_input: dict[str, Any]) -> str | None:
    return _as_str(
        _get(raw, "file_path", "filePath")
        or _get(tool_input, "file_path", "filePath", "path")
    )


def _command(raw: dict[str, Any], tool_input: dict[str, Any]) -> str | None:
    return _as_str(
        _get(raw, "command")
        or _get(tool_input, "command", "commandLine", "cmd")
    )


def _content(raw: dict[str, Any], tool_input: dict[str, Any]) -> str | None:
    value = _get(raw, "content") or _get(tool_input, "content")
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def normalize(raw: dict[str, Any], event_hint: str | None = None) -> LedgerEvent:
    """Map Cursor / Claude / Copilot hook payloads onto one event."""
    tool_input = _as_dict(_get(raw, "tool_input", "toolInput", "input"))
    event_name = _as_str(_get(raw, "hook_event_name", "hookEventName")) or event_hint or ""
    folded = _norm_event_name(event_name)
    kind = _KIND_BY_EVENT.get(folded, "unknown")
    tool = _tool_name(raw, tool_input)
    path = _read_path(raw, tool_input)
    command = _command(raw, tool_input)
    if kind == "pre_tool" and (tool in READ_TOOLS or (path and tool is None)):
        kind = "read"
    elif kind == "pre_tool":
        kind = "other_tool"
    elif kind == "post_tool":
        if tool in SHELL_TOOLS or (command and "gaudi " in command):
            kind = "shell"
        elif tool in READ_TOOLS or path:
            kind = "read"
        else:
            kind = "other_tool"
    elif kind == "unknown" and path and (tool in READ_TOOLS or tool is None):
        kind = "read"
    return LedgerEvent(
        kind=kind,
        event_name=event_name or (event_hint or "unknown"),
        conversation_id=_conversation_id(raw),
        generation_id=_as_str(_get(raw, "generation_id", "generationId")),
        path=path,
        content=_content(raw, tool_input),
        command=command,
        tool_name=tool,
        context_tokens=_as_int(
            _get(raw, "context_tokens", "contextTokens", "pre_compact_token_count")
        ),
        context_window_size=_as_int(
            _get(raw, "context_window_size", "contextWindowSize")
        ),
        message_count=_as_int(_get(raw, "message_count", "messageCount")),
    )


def fail_open_stdout(event: LedgerEvent, harness: str) -> dict[str, Any]:
    name = _norm_event_name(event.event_name)
    if name == "beforereadfile" or (event.kind == "read" and harness == "cursor"):
        return {"permission": "allow"}
    if name == "pretooluse" or (
        event.kind in {"read", "other_tool", "pre_tool"} and harness in {"copilot", "claude"}
    ):
        return {"hookSpecificOutput": {"permissionDecision": "allow"}}
    return {}


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_ledger_config(root: Path) -> LedgerConfig:
    cfg_path = under(root, CONFIG_REL)
    if not cfg_path.is_file():
        return LedgerConfig()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{cfg_path} must contain a JSON object")
    return parse_ledger_config(data.get("ledger"), cfg_path)


def workspace_root(payload: dict[str, Any]) -> Path:
    roots = payload.get("workspace_roots") or payload.get("workspaceRoots")
    if isinstance(roots, list) and roots:
        return Path(str(roots[0])).resolve()
    cwd = payload.get("cwd")
    if cwd:
        return Path(str(cwd)).resolve()
    return Path.cwd().resolve()


def current_conversation_id() -> str | None:
    return os.environ.get("GAUDI_CONVERSATION_ID") or os.environ.get("GAUDI_SESSION_ID")


class Ledger:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = under(self.root, LEDGER_FILE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def save(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _ensure_session(
        self,
        conversation_id: str,
        harness: str,
        arm: str,
        ts: float,
    ) -> None:
        row = self._conn.execute(
            "SELECT conversation_id FROM sessions WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is not None:
            return
        self._conn.execute(
            "INSERT INTO sessions(conversation_id, harness, arm, started_at, ended_at, turns) "
            "VALUES (?, ?, ?, ?, NULL, 0)",
            (conversation_id, harness, arm, ts),
        )

    def _turn(
        self,
        conversation_id: str,
        generation_id: str | None,
        *,
        bump_prompt: bool,
    ) -> int:
        bump = False
        if generation_id:
            exists = self._conn.execute(
                "SELECT turn FROM generations WHERE conversation_id = ? AND generation_id = ?",
                (conversation_id, generation_id),
            ).fetchone()
            if exists is None:
                counted = self._conn.execute(
                    "SELECT COUNT(*) FROM generations WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                if counted is not None and int(counted[0]) > 0:
                    bump = True
        elif bump_prompt:
            bump = True
        row = self._conn.execute(
            "SELECT turns FROM sessions WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        turn = int(row[0]) if row else 0
        if bump:
            turn += 1
        turn = max(turn, 1)
        self._conn.execute(
            "UPDATE sessions SET turns = ? WHERE conversation_id = ?",
            (turn, conversation_id),
        )
        if generation_id:
            self._conn.execute(
                "INSERT OR REPLACE INTO generations(conversation_id, generation_id, turn) "
                "VALUES (?, ?, ?)",
                (conversation_id, generation_id, turn),
            )
        return turn

    def record_session_start(
        self,
        conversation_id: str,
        harness: str,
        arm: str,
        ts: float | None = None,
    ) -> None:
        ts = time.time() if ts is None else ts
        self._ensure_session(conversation_id, harness, arm, ts)
        self._conn.execute(
            "UPDATE sessions SET harness = ?, arm = ?, started_at = COALESCE(started_at, ?) "
            "WHERE conversation_id = ?",
            (harness, arm, ts, conversation_id),
        )

    def record_session_end(self, conversation_id: str, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE conversation_id = ?",
            (ts, conversation_id),
        )

    def record_query(
        self,
        cmd: str,
        emitted_tokens: int,
        baseline_tokens: int,
        oriented: list[tuple[str, int]],
        conversation_id: str | None = None,
        turn: int | None = None,
        ts: float | None = None,
    ) -> int:
        ts = time.time() if ts is None else ts
        cur = self._conn.execute(
            "INSERT INTO queries(conversation_id, ts, cmd, emitted_tokens, baseline_tokens, turn) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, ts, cmd, emitted_tokens, baseline_tokens, turn),
        )
        query_id = cur.lastrowid
        if query_id is None:
            raise RuntimeError("sqlite did not return a query id")
        query_id = int(query_id)
        self._conn.executemany(
            "INSERT INTO oriented(query_id, path, source_tokens) VALUES (?, ?, ?)",
            [(query_id, path, tokens) for path, tokens in oriented],
        )
        return query_id

    def record_read(
        self,
        conversation_id: str,
        path: str,
        content_hash: str,
        tokens: int,
        turn: int | None,
        first_read: bool,
        ts: float | None = None,
    ) -> None:
        ts = time.time() if ts is None else ts
        self._conn.execute(
            "INSERT INTO reads(conversation_id, ts, path, content_hash, tokens, turn, first_read) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, ts, path, content_hash, tokens, turn, int(first_read)),
        )

    def hash_seen(self, conversation_id: str, content_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM reads WHERE conversation_id = ? AND content_hash = ? LIMIT 1",
            (conversation_id, content_hash),
        ).fetchone()
        return row is not None

    def record_compaction(
        self,
        conversation_id: str,
        context_tokens: int | None,
        context_window_size: int | None,
        message_count: int | None,
        ts: float | None = None,
    ) -> None:
        ts = time.time() if ts is None else ts
        self._conn.execute(
            "INSERT INTO compactions(conversation_id, ts, context_tokens, context_window_size, message_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, ts, context_tokens, context_window_size, message_count),
        )

    def attribute_shell(self, conversation_id: str, command: str) -> None:
        cmd = gaudi_subcommand(command)
        if cmd is None:
            return
        row = self._conn.execute(
            "SELECT id FROM queries WHERE conversation_id IS NULL AND cmd = ? ORDER BY ts DESC LIMIT 1",
            (cmd,),
        ).fetchone()
        if row is None:
            return
        self._conn.execute(
            "UPDATE queries SET conversation_id = ? WHERE id = ?",
            (conversation_id, row[0]),
        )

    def snapshots(self) -> ScorecardInput:
        sessions = [
            SessionSnap(
                conversation_id=row[0],
                harness=row[1],
                arm=row[2],
                turns=int(row[3]),
            )
            for row in self._conn.execute(
                "SELECT conversation_id, harness, arm, turns FROM sessions"
            )
        ]
        oriented_by_query: dict[int, list[tuple[str, int]]] = {}
        for query_id, path, source_tokens in self._conn.execute(
            "SELECT query_id, path, source_tokens FROM oriented"
        ):
            oriented_by_query.setdefault(int(query_id), []).append((path, int(source_tokens)))
        queries = [
            QuerySnap(
                conversation_id=row[1],
                cmd=row[2],
                emitted_tokens=int(row[3]),
                baseline_tokens=int(row[4]),
                turn=row[5],
                oriented=tuple(oriented_by_query.get(int(row[0]), ())),
            )
            for row in self._conn.execute(
                "SELECT id, conversation_id, cmd, emitted_tokens, baseline_tokens, turn FROM queries"
            )
        ]
        reads = [
            ReadSnap(
                conversation_id=row[0],
                path=row[1],
                tokens=int(row[2]),
                turn=row[3],
                first_read=bool(row[4]),
            )
            for row in self._conn.execute(
                "SELECT conversation_id, path, tokens, turn, first_read FROM reads"
            )
        ]
        compactions = [
            CompactionSnap(
                conversation_id=row[0],
                context_tokens=row[1],
                context_window_size=row[2],
                message_count=row[3],
            )
            for row in self._conn.execute(
                "SELECT conversation_id, context_tokens, context_window_size, message_count FROM compactions"
            )
        ]
        return ScorecardInput(
            sessions=tuple(sessions),
            queries=tuple(queries),
            reads=tuple(reads),
            compactions=tuple(compactions),
        )


def gaudi_subcommand(command: str) -> str | None:
    match = _GAUDI_CMD_RE.search(command) or _PYTHON_GAUDI_RE.search(command)
    if match:
        return match.group(1)
    return None


def detect_arm(root: Path, harness: str, config: LedgerConfig) -> str:
    override = os.environ.get("GAUDI_LEDGER_ARM") or config.arm
    if override:
        return override
    rel = instruction_rel_for_harness(harness)
    if rel is None:
        return "off"
    path = under(root, rel)
    if not path.is_file():
        return "off"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "off"
    marker = CURSOR_RULE_MARKER if harness == "cursor" else GAUDI_MD_MARKER
    return "on" if marker in text else "off"


def _session_start_text(root: Path) -> str:
    map_posix = MAP_REL.as_posix()
    if _cheap_fresh(root):
        return session_start_fresh_text()
    return (
        "Gaudi map: STALE — run gaudi generate, then gaudi index or gaudi focus. "
        f"Path: {map_posix}"
    )


def _cheap_fresh(root: Path) -> bool:
    map_path = under(root, MAP_REL)
    if not map_path.is_file():
        return False
    try:
        text = map_path.read_text(encoding="utf-8")
    except OSError:
        return False
    match = _HEAD_RE.search(text)
    if match is None:
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    if proc.returncode != 0:
        return False
    return proc.stdout.decode("utf-8", errors="replace").strip() == match.group(1)


def _read_bytes(root: Path, event: LedgerEvent) -> tuple[bytes | None, str | None]:
    if event.content is not None:
        return event.content.encode("utf-8"), event.path
    if not event.path:
        return None, None
    path = Path(event.path)
    if not path.is_absolute():
        path = root / path
    try:
        return path.read_bytes(), str(path)
    except OSError:
        return None, event.path


def handle_hook(
    payload: dict[str, Any],
    *,
    harness: str,
    event_hint: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    event = normalize(payload, event_hint=event_hint)
    harness = harness or os.environ.get("GAUDI_HARNESS") or ""
    response = fail_open_stdout(event, harness)
    try:
        root = root or workspace_root(payload)
        config = load_ledger_config(root)
        if not config.enabled:
            return _session_response(root, event, harness, response)
        _apply_event(root, event, harness, config)
        return _session_response(root, event, harness, response)
    except Exception:
        return response


def _session_response(
    root: Path,
    event: LedgerEvent,
    harness: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    if event.kind != "session_start":
        return response
    cid = event.conversation_id
    extra: dict[str, Any] = {}
    if cid:
        extra["env"] = {"GAUDI_CONVERSATION_ID": cid}
    if harness == "cursor":
        return extra
    ctx = _session_start_text(root)
    extra["hookSpecificOutput"] = {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    }
    extra["additional_context"] = ctx
    return extra


def _apply_event(root: Path, event: LedgerEvent, harness: str, config: LedgerConfig) -> None:
    led = Ledger(root)
    try:
        cid = event.conversation_id
        arm = detect_arm(root, harness or "agents", config)
        if event.kind == "session_start" and cid:
            led.record_session_start(cid, harness or "unknown", arm)
            led.save()
            return
        if event.kind == "session_end" and cid:
            led._ensure_session(cid, harness or "unknown", arm, time.time())
            led.record_session_end(cid)
            led.save()
            return
        if event.kind == "prompt" and cid:
            led._ensure_session(cid, harness or "unknown", arm, time.time())
            led._turn(cid, event.generation_id, bump_prompt=True)
            led.save()
            return
        if event.kind == "compact" and cid:
            led._ensure_session(cid, harness or "unknown", arm, time.time())
            led.record_compaction(
                cid,
                event.context_tokens,
                event.context_window_size,
                event.message_count,
            )
            led.save()
            return
        if event.kind == "shell" and cid and event.command:
            led._ensure_session(cid, harness or "unknown", arm, time.time())
            led.attribute_shell(cid, event.command)
            led.save()
            return
        if event.kind == "read" and cid:
            led._ensure_session(cid, harness or "unknown", arm, time.time())
            data, path = _read_bytes(root, event)
            if data is None or path is None:
                led.save()
                return
            digest = _hash_bytes(data)
            first = not led.hash_seen(cid, digest)
            turn = led._turn(cid, event.generation_id, bump_prompt=False)
            text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            led.record_read(cid, path, digest, token_count(text), turn, first)
            led.save()
            return
        led.save()
    finally:
        led.close()


def try_record_query(
    root: Path,
    cmd: str,
    emitted_tokens: int,
    baseline_tokens: int,
    oriented: list[tuple[str, int]],
    *,
    enabled: bool,
    conversation_id: str | None = None,
) -> None:
    if not enabled:
        return
    try:
        led = Ledger(root)
        try:
            cid = conversation_id if conversation_id is not None else current_conversation_id()
            turn: int | None = None
            if cid:
                row = led._conn.execute(
                    "SELECT turns FROM sessions WHERE conversation_id = ?",
                    (cid,),
                ).fetchone()
                if row is not None:
                    turn = int(row[0])
            led.record_query(cmd, emitted_tokens, baseline_tokens, oriented, cid, turn)
            led.save()
        finally:
            led.close()
    except (OSError, sqlite3.Error) as exc:
        print(f"warning: gaudi ledger write failed: {exc}", file=sys.stderr)


def load_snapshots(root: Path) -> ScorecardInput:
    path = under(root, LEDGER_FILE)
    if not path.is_file():
        return ScorecardInput()
    try:
        led = Ledger(root)
        try:
            return led.snapshots()
        finally:
            led.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Corrupt gaudi ledger at {path}: {exc}") from exc


def gaudi_section_text(text: str) -> str:
    start = text.find(GAUDI_MD_MARKER)
    if start < 0:
        return ""
    rest = text[start + 1 :]
    nxt = rest.find("\n## ")
    if nxt < 0:
        return text[start:]
    return text[start : start + 1 + nxt]


def instruction_tokens(root: Path, harness: str) -> int:
    rel = instruction_rel_for_harness(harness)
    if rel is None:
        return 0
    path = under(root, rel)
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Cannot read instruction file {path}") from exc
    if harness == "cursor":
        return token_count(text)
    return token_count(gaudi_section_text(text))


def session_start_fresh_text() -> str:
    return (
        f"Gaudi map: fresh ({MAP_REL.as_posix()}). "
        "Use gaudi index / gaudi focus. Cues only — Read source before editing."
    )


def session_start_tokens() -> int:
    return token_count(session_start_fresh_text())

