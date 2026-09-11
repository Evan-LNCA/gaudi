from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

from gaudi.mapgen import generate
from gaudi.paths import CACHE_FILE, token_count

N_FILES = 24
DEFS_PER_FILE = 8


def _write_fixture(root: Path) -> None:
    src = root / "pkg"
    src.mkdir(parents=True, exist_ok=True)
    for i in range(N_FILES):
        lines = [f"# module {i}"]
        for j in range(DEFS_PER_FILE):
            callee = f"fn_{i}_{(j + 1) % DEFS_PER_FILE}"
            lines.append(f"def fn_{i}_{j}():")
            lines.append(f"    return {callee}() if {j} else {i}")
            lines.append("")
        (src / f"mod_{i:02d}.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _time_generate(root: Path) -> tuple[float, int, int, int]:
    started = time.perf_counter()
    result = generate(root, quiet=True, no_git=True)
    elapsed = time.perf_counter() - started
    return elapsed, result.files, result.defs, result.tokens


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gaudi-bench-") as tmp:
        root = Path(tmp)
        _write_fixture(root)
        cache = root / CACHE_FILE
        if cache.is_file():
            cache.unlink()
        cold, files, defs, tokens = _time_generate(root)
        warms = [_time_generate(root)[0] for _ in range(3)]
        warm = statistics.median(warms)
        text = (root / ".map").read_text(encoding="utf-8")
        print("fixture: synthetic Python tree (no git)")
        print(f"files: {files}  defs: {defs}  tokens: {tokens}  chars: {len(text)}")
        print(f"token_count(.map): {token_count(text)}")
        print(f"cold generate: {cold:.3f}s")
        print(f"warm generate (median of 3): {warm:.3f}s")
        print(f"speedup: {cold / warm:.1f}x" if warm else "speedup: n/a")


if __name__ == "__main__":
    main()
