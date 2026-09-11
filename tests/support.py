from __future__ import annotations

import subprocess
from pathlib import Path

from gaudi.cli import main
from gaudi.gitutil import git_executable
from gaudi.paths import MAP_REL


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        [git_executable(), "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', errors='replace')}"
        )
    return proc


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run([git_executable(), "init"], cwd=path, check=True, capture_output=True)
    git(path, "config", "user.email", "gaudi-test@example.com")
    git(path, "config", "user.name", "Gaudi Test")
    git(path, "config", "commit.gpgsign", "false")
    return path


def commit_all(path: Path, message: str) -> None:
    git(path, "add", "-A")
    git(path, "commit", "-m", message)


def run_cli(repo: Path, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


def map_text(repo: Path) -> str:
    return (repo / MAP_REL).read_text(encoding="utf-8")


def map_body(text: str) -> str:
    parts = text.split("\n\n", 1)
    return parts[1] if len(parts) > 1 else ""
