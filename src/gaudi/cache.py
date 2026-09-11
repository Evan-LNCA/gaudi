from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from gaudi.extract import DefTag, FileTags
from gaudi.paths import CACHE_FILE, under

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
  content_hash TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  payload TEXT NOT NULL
);
"""


class TagCache:
    def __init__(self, root: Path, *, readonly: bool = False) -> None:
        self.path = under(root, CACHE_FILE)
        self._readonly = readonly
        self._conn: sqlite3.Connection | None = None
        if readonly:
            if not self.path.is_file():
                return
            self._conn = sqlite3.connect(
                f"file:{self.path.as_posix()}?mode=ro",
                uri=True,
            )
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, content_hash: str) -> FileTags | None:
        if self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT payload FROM tags WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if row is None:
            return None
        raw = json.loads(row[0])
        defs = [
            DefTag(
                path=d["path"],
                name=d["name"],
                kind=d["kind"],
                line=d["line"],
                signature=d["signature"],
            )
            for d in raw["defs"]
        ]
        return FileTags(path=raw["path"], defs=defs, refs=list(raw["refs"]))

    def put(self, content_hash: str, tags: FileTags) -> None:
        if self._readonly or self._conn is None:
            return
        payload = json.dumps(
            {
                "path": tags.path,
                "defs": [
                    {
                        "path": d.path,
                        "name": d.name,
                        "kind": d.kind,
                        "line": d.line,
                        "signature": d.signature,
                    }
                    for d in tags.defs
                ],
                "refs": tags.refs,
            },
            ensure_ascii=False,
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO tags(content_hash, path, payload) VALUES (?, ?, ?)",
            (content_hash, tags.path, payload),
        )

    def prune(self, live_hashes: Iterable[str]) -> int:
        if self._readonly or self._conn is None:
            return 0
        live = set(live_hashes)
        rows = self._conn.execute("SELECT content_hash FROM tags").fetchall()
        dropped = 0
        for (digest,) in rows:
            if digest not in live:
                self._conn.execute("DELETE FROM tags WHERE content_hash = ?", (digest,))
                dropped += 1
        return dropped

    def hashes(self) -> set[str]:
        if self._conn is None:
            return set()
        rows = self._conn.execute("SELECT content_hash FROM tags").fetchall()
        return {row[0] for row in rows}

    def save(self) -> None:
        if self._readonly or self._conn is None:
            return
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
