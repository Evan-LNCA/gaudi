from __future__ import annotations

from pathlib import Path

from pathspec import PathSpec

from gaudi.errors import ShipError

IGNORE_LINES = [".map", ".gaudi/"]
GITIGNORE_LINE = ".map"
GITIGNORE_LINES = list(IGNORE_LINES)
DOCKERIGNORE_LINES = list(IGNORE_LINES)


def dockerignore_lines() -> list[str]:
    return list(IGNORE_LINES)


def ensure_ignore_lines(path: Path, lines: list[str]) -> bool:
    existing: list[str] = []
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        existing = text.splitlines()
    have = {ln.strip() for ln in existing}
    changed = False
    for line in lines:
        if line.strip() not in have:
            existing.append(line)
            have.add(line.strip())
            changed = True
    if not path.is_file() or changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(existing).rstrip()
        path.write_text((body + "\n") if body else "", encoding="utf-8")
    return changed


def update_all_ignore_files(root: Path) -> list[Path]:
    updated: list[Path] = []
    # Always ensure .gitignore and .dockerignore
    for base in (".gitignore", ".dockerignore"):
        target = root / base
        ensure_ignore_lines(target, IGNORE_LINES)
        updated.append(target)

    # Check for any other *ignore files in repo root
    try:
        for entry in root.iterdir():
            if not entry.is_file():
                continue
            name_lower = entry.name.lower()
            if name_lower == ".cursorignore":
                continue
            if name_lower.endswith("ignore") and entry.name not in {".gitignore", ".dockerignore"}:
                ensure_ignore_lines(entry, IGNORE_LINES)
                updated.append(entry)
    except OSError:
        pass
    return updated


def _dockerignore_excludes_map(text: str) -> bool:
    patterns = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    spec = PathSpec.from_lines("gitwildmatch", patterns)
    return spec.match_file(".map") and spec.match_file(".gaudi/keep")


def check_ship(root: Path) -> None:
    for artifact in ("dist", "build"):
        for leak in (".map", ".gaudi", Path(".cursor") / "gaudi"):
            nested = root / artifact / leak
            if nested.exists():
                raise ShipError(
                    f"{artifact}/ contains {leak}; refuse to ship the map"
                )

    dockerignore = root / ".dockerignore"
    if not dockerignore.is_file():
        raise ShipError(
            "No .dockerignore; `COPY . .` would include .map. Run `gaudi generate`."
        )
    if not _dockerignore_excludes_map(dockerignore.read_text(encoding="utf-8")):
        raise ShipError(
            ".dockerignore does not exclude .map and .gaudi/; `COPY . .` would ship the map"
        )
