---
name: gaudi
description: Query and maintain the Gaudi ranked codebase map for AI coding agents.
---

# Use Gaudi for orientation

Do not always read `.map`. Prefer a small index plus on-demand focus.

When the user asks to generate, refresh, or update a Gaudi map, work in the
target repository:

1. Verify that the Gaudi CLI is available:
   ```bash
   python -c "import gaudi"
   ```
   If it is unavailable, install it using the repository's normal Python
   environment, then retry.
2. From the repository root, run:
   ```bash
   gaudi generate
   ```
   Use `python -m gaudi generate` if the console command is unavailable.
3. Confirm `.map` exists. It is a cues-only orientation aid, not source-of-truth
   code, and must never be hand-edited.

For day-to-day orientation:

```bash
gaudi index
gaudi focus <path-or-symbol>
gaudi where <symbol>
gaudi status
```

`gaudi focus` prints a personalized neighborhood to stdout and never writes `.map`.
If the map or cache is missing or stale, run `gaudi generate` before relying on
queries. Cloud Agent does not run Cursor sessionStart, so it must check itself.

Read the actual source files before making edits. Do not infer behavior,
ownership, or implementation details from Gaudi output alone. Trust truncation
markers (`⋮ +N more defs`) and the freshness line.
