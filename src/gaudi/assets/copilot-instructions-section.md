## Gaudi Map (Codebase Orientation)

Do not always read `.map`. Use a small index plus on-demand queries.

- Run `gaudi index` for hubs and directory shape (~250 tokens).
- Run `gaudi focus <path-or-symbol>` for the working area. It prints to stdout and never writes `.map`.
- Run `gaudi where <symbol>` for `path:line` plus signature.

The output contains ranked signatures, not source-of-truth implementations. Always grep, search, or open the real file before editing. Do not edit from Gaudi output alone.

If output is missing or the freshness line says stale, run `gaudi generate` (or `python -m gaudi generate`) first, then retry the query. Never hand-edit `.map`. Truncation markers (`⋮ +N more defs`, `showing N of M files`) mean those defs were not shown — read the source.
