from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from gaudi.errors import GaudiError

_GIT_FALLBACKS = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)

_git_exe: str | None = None


def git_executable() -> str:
    global _git_exe
    if _git_exe is not None:
        return _git_exe
    found = shutil.which("git")
    if found:
        _git_exe = found
        return found
    for candidate in _GIT_FALLBACKS:
        if Path(candidate).is_file():
            _git_exe = candidate
            return candidate
    _git_exe = "git"
    return "git"


class GitRepo:
    """Git operations scoped to a working tree. Injected for tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        exe = git_executable()
        try:
            return subprocess.run(
                [exe, "-C", str(self.root), *args],
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GaudiError(f"git executable not found ({exe})") from exc

    def is_work_tree(self) -> bool:
        try:
            proc = self._run("rev-parse", "--is-inside-work-tree")
        except GaudiError:
            return False
        return proc.returncode == 0 and proc.stdout.strip() == b"true"

    def require(self) -> None:
        if not self.is_work_tree():
            raise GaudiError(f"Not a git repository: {self.root}")

    def ls_files(self) -> list[str]:
        proc = self._run("ls-files", "-z", "--cached", "--others", "--exclude-standard")
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
            if path == ".map" or path.startswith((".gaudi", ".cursor/gaudi")):
                continue
            return True
        return False
