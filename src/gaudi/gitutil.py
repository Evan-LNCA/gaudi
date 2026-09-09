from __future__ import annotations

import subprocess
from pathlib import Path

from gaudi.errors import GaudiError


class GitRepo:
    """Git operations scoped to a working tree. Injected for tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            check=False,
        )

    def require(self) -> None:
        proc = self._run("rev-parse", "--is-inside-work-tree")
        if proc.returncode != 0 or proc.stdout.strip() != b"true":
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise GaudiError(f"Not a git repository: {self.root}" + (f" ({err})" if err else ""))

    def ls_files(self) -> list[str]:
        proc = self._run("ls-files", "-z")
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise GaudiError(f"git ls-files failed in {self.root}: {err}")
        out = proc.stdout.split(b"\0")
        paths: list[str] = []
        for raw in out:
            if not raw:
                continue
            paths.append(raw.decode("utf-8"))
        return paths

    def head_sha(self) -> str:
        proc = self._run("rev-parse", "HEAD")
        if proc.returncode != 0:
            return "UNBORN"
        return proc.stdout.decode("utf-8").strip()

    def is_dirty(self) -> bool:
        proc = self._run("status", "--porcelain", "-uall")
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise GaudiError(f"git status failed in {self.root}: {err}")
        for raw in proc.stdout.splitlines():
            line = raw.decode("utf-8", errors="replace")
            if len(line) < 4:
                continue
            path = line[3:].strip().replace("\\", "/")
            if path.startswith(".cursor/gaudi"):
                continue
            return True
        return False
