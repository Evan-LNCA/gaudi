from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

GAUDI_DIR = Path(".gaudi")
MAP_REL = Path(".map")
CACHE_REL = GAUDI_DIR / "cache"
CACHE_FILE = CACHE_REL / "tags.sqlite"
CONFIG_REL = GAUDI_DIR / "config.json"
RULE_REL = Path(".cursor") / "rules" / "gaudi-map.mdc"
CLAUDE_MD_REL = Path("CLAUDE.md")
AGENTS_MD_REL = Path("AGENTS.md")
COPILOT_INSTRUCTIONS_REL = Path(".github") / "copilot-instructions.md"
COPILOT_SKILL_REL = Path(".github") / "skills" / "gaudi" / "SKILL.md"
HOOKS_JSON_REL = Path(".cursor") / "hooks.json"
HOOK_START_REL = Path(".cursor") / "hooks" / "gaudi_session_start.py"
HOOK_STOP_REL = Path(".cursor") / "hooks" / "gaudi_stop.py"
LEDGER_FILE = GAUDI_DIR / "ledger.sqlite"
CURSOR_LEDGER_HOOK_REL = Path(".cursor") / "hooks" / "gaudi_ledger.py"
COPILOT_LEDGER_JSON_REL = Path(".github") / "hooks" / "gaudi-ledger.json"
COPILOT_LEDGER_HOOK_REL = Path(".github") / "hooks" / "gaudi_ledger.py"
CLAUDE_SETTINGS_REL = Path(".claude") / "settings.json"
CLAUDE_LEDGER_HOOK_REL = Path(".claude") / "hooks" / "gaudi_ledger.py"
GAUDI_MD_MARKER = "## Gaudi Map"
CURSOR_RULE_MARKER = "# Gaudi map"
DEFAULT_CACHE_READ_MULTIPLIER = 0.1
DEFAULT_MIN_SESSIONS = 10

DEFAULT_MAP_TOKENS = 2048
DEFAULT_INDEX_TOKENS = 250
DEFAULT_FOCUS_TOKENS = 512
DEFAULT_MAX_FILE_BYTES = 1_048_576
NOGIT_HEAD = "NOGIT"

SKIP_DIR_NAMES = frozenset(
    {".venv", "node_modules", "dist", "build", ".gaudi", ".git", "__pycache__"}
)

DEFAULT_EXCLUDE_GLOBS = (
    ".venv/",
    "node_modules/",
    "dist/",
    "build/",
    ".gaudi/",
    ".git/",
    "__pycache__/",
    "*.min.js",
    "*.min.css",
    "*.min.mjs",
    "*.min.cjs",
)

SOURCE_SUFFIXES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".ex": "elixir",
    ".exs": "elixir",
    ".lua": "lua",
    ".sh": "bash",
    ".bash": "bash",
}

POOL_MIN_FILES = 4
POOL_MIN_BYTES = 64_000


@dataclass
class LedgerConfig:
    enabled: bool = True
    cache_read_multiplier: float = DEFAULT_CACHE_READ_MULTIPLIER
    arm: str | None = None
    min_sessions: int = DEFAULT_MIN_SESSIONS


@dataclass
class GaudiConfig:
    map_tokens: int = DEFAULT_MAP_TOKENS
    exclude: list[str] = field(default_factory=list)
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    ledger: LedgerConfig = field(default_factory=LedgerConfig)


def under(root: Path, rel: Path) -> Path:
    return root / rel


def should_skip(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return any(part in SKIP_DIR_NAMES for part in parts)


def token_count(text: str) -> int:
    return (len(text) + 3) // 4


def tokens_from_size(n: int) -> int:
    return (n + 3) // 4


def parse_ledger_config(data: object, cfg_path: Path) -> LedgerConfig:
    cfg = LedgerConfig()
    if data is None:
        return cfg
    if not isinstance(data, dict):
        raise ValueError(f"{cfg_path} ledger must be an object")
    if "enabled" in data:
        enabled = data["enabled"]
        if not isinstance(enabled, bool):
            raise ValueError(f"{cfg_path} ledger.enabled must be a boolean")
        cfg.enabled = enabled
    if "cache_read_multiplier" in data:
        multiplier = data["cache_read_multiplier"]
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
            raise ValueError(f"{cfg_path} ledger.cache_read_multiplier must be a number")
        cfg.cache_read_multiplier = float(multiplier)
    if "arm" in data:
        arm = data["arm"]
        if arm is not None and not isinstance(arm, str):
            raise ValueError(f"{cfg_path} ledger.arm must be a string or null")
        cfg.arm = arm
    if "min_sessions" in data:
        min_sessions = data["min_sessions"]
        if isinstance(min_sessions, bool) or not isinstance(min_sessions, int):
            raise ValueError(f"{cfg_path} ledger.min_sessions must be an integer")
        cfg.min_sessions = min_sessions
    return cfg


def instruction_rel_for_harness(harness: str) -> Path | None:
    if harness == "cursor":
        return RULE_REL
    if harness == "copilot":
        return COPILOT_INSTRUCTIONS_REL
    if harness == "claude":
        return CLAUDE_MD_REL
    if harness == "agents":
        return AGENTS_MD_REL
    return None
