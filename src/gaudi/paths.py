from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

GAUDI_DIR = Path(".gaudi")
MAP_REL = Path(".map")
CACHE_REL = GAUDI_DIR / "cache"
CACHE_FILE = CACHE_REL / "tags.sqlite"
CONFIG_REL = GAUDI_DIR / "config.json"
RULE_REL = Path(".cursor") / "rules" / "gaudi-map.mdc"
COPILOT_INSTRUCTIONS_REL = Path(".github") / "copilot-instructions.md"
COPILOT_SKILL_REL = Path(".github") / "skills" / "gaudi" / "SKILL.md"
HOOKS_JSON_REL = Path(".cursor") / "hooks.json"
HOOK_START_REL = Path(".cursor") / "hooks" / "gaudi_session_start.py"
HOOK_STOP_REL = Path(".cursor") / "hooks" / "gaudi_stop.py"

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
class GaudiConfig:
    map_tokens: int = DEFAULT_MAP_TOKENS
    exclude: list[str] = field(default_factory=list)
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


def under(root: Path, rel: Path) -> Path:
    return root / rel


def should_skip(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return any(part in SKIP_DIR_NAMES for part in parts)


def token_count(text: str) -> int:
    return (len(text) + 3) // 4
