from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from pathspec import PathSpec

from gaudi.gitutil import GitRepo
from gaudi.paths import DEFAULT_EXCLUDE_GLOBS, NOGIT_HEAD, GaudiConfig, should_skip


class SourceLister(Protocol):
    def list_rel_paths(self) -> list[str]:
        """Return repo-relative POSIX paths of candidate source files."""

    def head_sha(self) -> str: ...

    def is_dirty(self) -> bool: ...


class GitLister:
    def __init__(self, root: Path, git: GitRepo | None = None) -> None:
        self.root = root.resolve()
        self.git = git or GitRepo(self.root)

    def list_rel_paths(self) -> list[str]:
        return [p.replace("\\", "/") for p in self.git.ls_files()]

    def head_sha(self) -> str:
        return self.git.head_sha()

    def is_dirty(self) -> bool:
        return self.git.is_dirty()


class WalkLister:
    """Filesystem walk honoring .gitignore via pathspec. No git required."""

    def __init__(self, root: Path, extra_excludes: list[str] | None = None) -> None:
        self.root = root.resolve()
        self._spec = _ignore_spec(self.root, extra_excludes or [])

    def list_rel_paths(self) -> list[str]:
        out: list[str] = []
        root = self.root
        spec = self._spec
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
            if rel_dir == ".":
                rel_dir = ""
            kept: list[str] = []
            for name in dirnames:
                rel = f"{rel_dir}/{name}" if rel_dir else name
                if name.startswith(".") and name not in {".github", ".cursor"}:
                    if name in {".git", ".gaudi", ".venv"}:
                        continue
                if spec.match_file(rel + "/") or spec.match_file(rel):
                    continue
                if should_skip(rel):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in filenames:
                rel = f"{rel_dir}/{name}" if rel_dir else name
                rel = rel.replace("\\", "/")
                if spec.match_file(rel) or should_skip(rel):
                    continue
                out.append(rel)
        out.sort()
        return out

    def head_sha(self) -> str:
        return NOGIT_HEAD

    def is_dirty(self) -> bool:
        return False


def detect_lister(
    root: Path,
    *,
    no_git: bool = False,
    extra_excludes: list[str] | None = None,
) -> SourceLister:
    if not no_git:
        git = GitRepo(root)
        if git.is_work_tree():
            return GitLister(root, git)
    return WalkLister(root, extra_excludes=extra_excludes)


def compile_exclude_spec(config: GaudiConfig | None = None) -> PathSpec:
    lines = list(DEFAULT_EXCLUDE_GLOBS)
    if config is not None:
        lines.extend(config.exclude)
    return PathSpec.from_lines("gitignore", lines)


def _ignore_spec(root: Path, extra: list[str]) -> PathSpec:
    lines = list(DEFAULT_EXCLUDE_GLOBS)
    lines.extend(extra)
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        lines.extend(_ignore_lines(gitignore.read_text(encoding="utf-8")))
    return PathSpec.from_lines("gitignore", lines)


def _ignore_lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out
