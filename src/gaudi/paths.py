from pathlib import Path

GAUDI_DIR = Path(".cursor") / "gaudi"
MAP_REL = GAUDI_DIR / "MAP.md"
CACHE_REL = GAUDI_DIR / "cache"
CACHE_FILE = CACHE_REL / "tags.json"
CONFIG_REL = GAUDI_DIR / "config.json"
RULE_REL = Path(".cursor") / "rules" / "gaudi-map.mdc"
COPILOT_INSTRUCTIONS_REL = Path(".github") / "copilot-instructions.md"
HOOKS_JSON_REL = Path(".cursor") / "hooks.json"
HOOK_START_REL = Path(".cursor") / "hooks" / "gaudi_session_start.py"
HOOK_STOP_REL = Path(".cursor") / "hooks" / "gaudi_stop.py"

DEFAULT_MAP_TOKENS = 2048
SKIP_DIR_NAMES = frozenset({".venv", "node_modules", "dist", "build"})

SOURCE_SUFFIXES = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
}


def under(root: Path, rel: Path) -> Path:
    return root / rel


def should_skip(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return any(part in SKIP_DIR_NAMES for part in parts)
