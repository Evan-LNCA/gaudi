from __future__ import annotations

from pathlib import Path

from gaudi.errors import ShipError
from gaudi.paths import GAUDI_DIR

GITIGNORE_LINE = ".cursor/gaudi/"
DOCKERIGNORE_GAUDI = ".cursor/gaudi/"
DOCKERIGNORE_CURSOR = ".cursor/"


def dockerignore_lines() -> list[str]:
    return [DOCKERIGNORE_GAUDI, DOCKERIGNORE_CURSOR]


def ensure_ignore_lines(path: Path, lines: list[str]) -> None:
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
        body = "\n".join(existing).rstrip() + "\n"
        path.write_text(body, encoding="utf-8")


def _dockerignore_excludes_gaudi(text: str) -> bool:
    patterns = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line.rstrip("/"))
    for pat in patterns:
        if pat in {".cursor", ".cursor/gaudi", "**/.cursor", "**/.cursor/gaudi"}:
            return True
        if pat.startswith("!") and "cursor" in pat:
            continue
    return False


def check_ship(root: Path) -> None:
    for artifact in ("dist", "build"):
        nested = root / artifact / ".cursor" / "gaudi"
        if nested.exists():
            raise ShipError(
                f"{artifact}/ contains .cursor/gaudi/; refuse to ship the map"
            )

    dockerignore = root / ".dockerignore"
    if not dockerignore.is_file():
        raise ShipError(
            "No .dockerignore; `COPY . .` would include .cursor/gaudi/. Run `gaudi install`."
        )
    if not _dockerignore_excludes_gaudi(dockerignore.read_text(encoding="utf-8")):
        raise ShipError(
            ".dockerignore does not exclude .cursor/gaudi/ or .cursor/; `COPY . .` would ship the map"
        )
