## Gaudi Map (Codebase Orientation)

Before cross-file orientation, check `.cursor/gaudi/MAP.md` (or `.github/gaudi/MAP.md` if present).

- The map contains ranked signatures and architectural topology (PageRank), not source-of-truth implementations.
- Always use grep, code search, or file view for exact details before making edits. Do not edit based on the map alone.
- If the map is missing or stale, run `gaudi generate` (or `python -m gaudi generate`) first.
- Never hand-edit `MAP.md`.
