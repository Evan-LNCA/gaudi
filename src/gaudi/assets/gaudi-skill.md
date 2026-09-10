---
name: gaudi
description: Generate and maintain the Gaudi ranked codebase map for AI coding agents.
---

# Generate a Gaudi map

When the user asks to generate, refresh, or update a Gaudi map, work in the
target repository (the workspace being analyzed):

1. Verify that the Gaudi CLI is available:
   ```powershell
   python -c "import gaudi"
   ```
   If it is unavailable, install it using the repository's normal Python
   environment, then retry.
2. From the repository root, run:
   ```powershell
   gaudi generate
   ```
   Use `python -m gaudi generate` if the console command is unavailable.
3. Confirm the generated `.map` exists. It is a cues-only orientation aid,
   not source-of-truth code and must never be hand-edited.

Before using an existing map for broad orientation, check it with:

```powershell
gaudi status
```

If the map is missing or stale, run `gaudi generate` before relying on it.
The normal Cursor integration also checks freshness at session start and
regenerates at session stop. Cloud Agent does not run that Cursor hook, so it
must perform this check itself.

Use `.map` to identify likely architectural hubs and signatures, then read the
actual source files before making edits. Do not infer behavior, ownership, or
implementation details from the map alone.
