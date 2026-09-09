from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from gaudi.extract import DefTag, FileTags
from gaudi.paths import CACHE_FILE, under


class TagCache:
    def __init__(self, root: Path) -> None:
        self.path = under(root, CACHE_FILE)
        self._data: dict[str, Any] = {}
        if self.path.is_file():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, content_hash: str) -> FileTags | None:
        raw = self._data.get(content_hash)
        if not raw:
            return None
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
        self._data[content_hash] = {
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
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
