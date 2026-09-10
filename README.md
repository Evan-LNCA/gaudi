# Gaudi

Gaudi generates a ranked signature map for AI coding agents such as GitHub
Copilot and Cursor. It parses Python, JavaScript, and TypeScript with
tree-sitter, ranks definitions with a PageRank-style graph, and writes a
**cues-only** outline to `.map` in the repository root.

The map is an orientation aid, not source code. Agents should use it to find
likely architectural hubs, then read the real files before editing. Nobody
hand-edits `.map`.

## Requirements

- Python 3.11+
- Git
- No Aider dependency

Runtime dependencies are declared in `pyproject.toml`:

- `tree-sitter`
- `tree-sitter-language-pack`
- `networkx`

## Install for local development

From this repository:

```powershell
pip install -e C:\Users\einfantino\projects\gaudi
```

To include the test dependency:

```powershell
pip install -e C:\Users\einfantino\projects\gaudi[dev]
```

## CLI commands

Run commands from the target repository that should receive a map:

```powershell
cd C:\Users\einfantino\projects\<repo>
gaudi generate
gaudi status
gaudi check-ship
```

| Command | Purpose |
|---|---|
| `gaudi generate` | Parse tracked source files, update ignore files, cache tags, and write `.map`. |
| `gaudi status` | Exit 0 only when `.map` matches the current Git/source-tree state. |
| `gaudi check-ship` | Fail if the map could be copied into Docker/build/dist output. |
| `gaudi install [--target all\|cursor\|copilot]` | Install agent-facing instructions/hooks, update ignore files, and generate the map. |

`gaudi generate` is standalone and self-contained. It automatically secures
`.map` and `.gaudi/` in `.gitignore`, `.dockerignore`, and any other existing
`*ignore` files in the repository.

## Generated files

| Path | Purpose | Commit? |
|---|---|---|
| `.map` | Ranked, cues-only signature map. | No |
| `.gaudi/cache/` | Parsed tag cache keyed by content hash. | No |
| `.gaudi/config.json` | Local configuration, currently `map_tokens`. | No |
| `.github/copilot-instructions.md` | Copilot orientation instructions installed by `gaudi install --target copilot` or `all`. | Usually yes |
| `.github/skills/gaudi/SKILL.md` | Copilot skill that teaches agents what “generate a Gaudi map” means. | Usually yes |
| `.cursor/rules/gaudi-map.mdc` | Cursor rule for reading and refreshing the map. | Usually yes |
| `.cursor/hooks.json` and `.cursor/hooks/gaudi_*.py` | Cursor lifecycle hooks. | Usually yes |

The default map budget is 2048 tokens and can be changed in
`.gaudi/config.json` or with `gaudi generate --map-tokens <n>`.

## Agent behavior

`gaudi install` is idempotent. It wires the target repository so agents know
how to use Gaudi:

- GitHub Copilot gets `.github/copilot-instructions.md`.
- GitHub Copilot also gets `.github/skills/gaudi/SKILL.md`.
- Cursor gets `.cursor/rules/gaudi-map.mdc`.
- Cursor gets session lifecycle hooks.

The Copilot skill teaches agents that a request to generate, refresh, or update
a Gaudi map means:

1. Verify the Gaudi CLI is available.
2. Run `gaudi generate` from the target repository root.
3. Use `gaudi status` to detect staleness before relying on an existing map.
4. Treat `.map` as orientation-only and read real source files before editing.

## Freshness model

`.map` records the Git `HEAD`, dirty state, and a source-tree fingerprint.
`gaudi status` recomputes freshness and returns success only when the current
repository matches the map header and tree fingerprint.

Cursor integration uses two hooks:

- **sessionStart:** cheap `HEAD`/dirty check; injects a short status message
  such as `Gaudi map: fresh` or `Gaudi map: STALE — run gaudi generate before
  Read`. It never dumps the map body and does not regenerate.
- **stop:** full freshness check; regenerates with `gaudi generate` if stale.

Cloud Agent does not run Cursor's `sessionStart` hook. The installed Copilot
instructions and skill tell it to run `gaudi generate` if `.map` is missing or
stale.

## Shipping safety

Generated maps are local development artifacts and should not be shipped.
`gaudi generate` and `gaudi install` append:

- `.gitignore` → `.map` and `.gaudi/`
- `.dockerignore` → `.map` and `.gaudi/` (covers `COPY . .`)
- Any existing `*ignore` files (e.g. `.npmignore`, `.vercelignore`, `.helmignore`) → `.map` and `.gaudi/`

The map is **not** added to `.cursorignore` because the agent must be able to
read it. Run `gaudi check-ship` before baking an image or publishing build
artifacts.

## Development

Run the test suite:

```powershell
pytest -q
```

The package uses a `src/` layout. The console entry point is:

```text
gaudi = gaudi.cli:main
```

## Cursor setup notes

Gaudi cannot flip IDE settings. After the first `gaudi install` in a real project:

1. Cursor **Settings → Hooks**: enable project hooks / trust the workspace.
2. Open the **Hooks** output channel. Start a **new Agent chat**. Confirm `gaudi_session_start` ran and injected a ~2-line status (`Gaudi map: fresh` or `STALE — run gaudi generate before Read`), not the map body.
3. One-time: `pip install -e C:\Users\einfantino\projects\gaudi` on the Python Cursor uses for hooks.
4. Optional: add a git remote for `projects/gaudi` if you want it on origin (do not expect a push from install).

Until those steps are confirmed, hook runtime in Cursor is **unverified**.

## User skill source

User skill: `/gaudi` (`disable-model-invocation: true`) at `C:\Users\einfantino\.cursor\skills\gaudi\SKILL.md` (source copy in this repo: `skills/gaudi/SKILL.md`).
