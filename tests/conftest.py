from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import commit_all, init_repo


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(".map\n.gaudi/\n", encoding="utf-8")
    (repo / ".dockerignore").write_text(".map\n.gaudi/\n", encoding="utf-8")
    (repo / "a.py").write_text(
        "def foo():\n    return 1\n\n\ndef helper():\n    return 2\n",
        encoding="utf-8",
    )
    (repo / "b.py").write_text(
        "from a import foo\n\ndef bar():\n    return foo()\n",
        encoding="utf-8",
    )
    commit_all(repo, "init")
    return repo
