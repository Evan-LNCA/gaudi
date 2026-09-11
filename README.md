# Gaudi

Gaudi is a query engine for AI coding agents. It parses source with tree-sitter,
ranks definitions with a weighted PageRank, and answers scoped questions cheaply:

- `gaudi index` — a small hub + directory sketch (~250 tokens)
- `gaudi focus <path|symbol>` — a personalized neighborhood (never writes `.map`)
- `gaudi where <symbol>` — `path:line` plus signature

A ranked `.map` still exists as a cues-only outline, but agents should not always
read it. Prefer the index plus on-demand focus. Nobody hand-edits `.map`.

Supported languages: Python, JavaScript/TypeScript (JSX/TSX), Go, Rust, Java,
C#, C/C++, Ruby, PHP, Swift, Kotlin, Scala, Elixir, Lua, and Bash.

## Requirements

- Python 3.11+
- Git is optional (filesystem walk when there is no work tree, or pass `--no-git`)

Runtime dependencies are declared in `pyproject.toml`:

- `tree-sitter>=0.25`
- `tree-sitter-language-pack`
- `networkx`
- `pathspec`

## Install for local development

From this repository (no machine-specific paths):

```bash
python -m pip install -e .
python -m pip install -e ".[dev]"
```

PowerShell is the same:

```powershell
python -m pip install -e .
python -m pip install -e ".[dev]"
```

`python -m gaudi` works if the `gaudi` console script is not on `PATH`.

## When to run

| Situation | Command |
|---|---|
| First time in a repo | `gaudi install` (hooks/rules/ignores + generate) |
| Map/ignores only, no agent wiring | `gaudi generate` |
| After source changes, before trusting a saved `.map` | `gaudi generate` if `status` or the freshness line is stale |
| Day-to-day orientation | `gaudi index`, then `gaudi focus`, then `gaudi where` |
| Check whether `.map` matches HEAD + tree | `gaudi status` (exit 0/1, no stdout, does not write cache) |
| Before Docker/build/dist | `gaudi check-ship` |
| New Cursor agent session | sessionStart hook injects a cheap HEAD status; stop regenerates if stale |

`index` / `focus` / `where` parse the live tree. They stay useful when `.map` is
missing. If a `.map` is present and the freshness line says `fresh: false`,
regenerate before treating that saved outline as current.

## CLI commands

Run from the target repository (or pass `--root`):

```bash
cd /path/to/your/repo
gaudi generate
gaudi status
gaudi index
gaudi focus src/app.py
gaudi where fetchUser
gaudi check-ship
gaudi install
```

| Command | Purpose | Writes |
|---|---|---|
| `gaudi generate [--map-tokens N]` | Parse sources, update ignore files, cache tags in SQLite, write `.map`. | `.map`, `.gaudi/`, ignore files |
| `gaudi status` | Exit 0 only when `.map` matches HEAD and the source-tree fingerprint. Silent. Does not write the cache. | nothing |
| `gaudi index [--tokens 250] [--format json]` | Top hubs plus directory shape with def counts. | nothing |
| `gaudi focus <path\|symbol>... [--tokens 512] [--format json]` | Personalized PageRank neighborhood to stdout. Never writes `.map`. | nothing |
| `gaudi where <symbol> [--format json]` | Print `path:line` plus signature. | nothing |
| `gaudi check-ship` | Fail if the map could be copied into Docker/build/dist output. | nothing |
| `gaudi install [--target all\|cursor\|copilot]` | Install agent-facing instructions/hooks, update ignore files, and generate the map (quiet). | agent files + generate outputs |

Global flags (before the subcommand): `--version`, `--quiet` / `-q`, `--no-git`, `--root <dir>`.

`--quiet` suppresses the generate summary and the `*.map` hide warning from
`generate`, `index`, and `focus`. `--map-tokens` / `--tokens` apply to that
invocation only; persist a map budget in `.gaudi/config.json`.

`focus`, `where`, and `index` accept `--format json`. Text output includes a
freshness line (`fresh: true|false`) and truncation markers (`⋮ +N more defs`).

`gaudi generate` is standalone. It discovers files with
`git ls-files --cached --others --exclude-standard` when Git is available,
otherwise a pathspec walk. It writes `.map` and `.gaudi/` into `.gitignore`,
`.dockerignore` (creating them if needed), and any other existing `*ignore`
files except `.cursorignore`. It warns if `*.map` in `.gitignore` or
`.cursorignore` would hide `.map` from the agent.

Success summary (unless `--quiet`):

```text
wrote .map: 128 files, 940 defs, ~2011 tokens, 1.2s
```

Exit codes: `status` is 0 (fresh) or 1 (stale/missing). `check-ship` failures
are 1. Other Gaudi errors are 2.

## Generated files

| Path | Purpose | Commit? |
|---|---|---|
| `.map` | Ranked, cues-only signature map. | No |
| `.gaudi/cache/tags.sqlite` | Tag cache keyed by content hash; pruned to live files. | No |
| `.gaudi/config.json` | Local configuration (`map_tokens`, optional `exclude`, `max_file_bytes`). | No |
| `.dockerignore` | Created/updated so `COPY . .` does not ship the map. | Yes |
| `.github/copilot-instructions.md` | Copilot orientation installed by `gaudi install --target copilot` or `all`. | Usually yes |
| `.github/skills/gaudi/SKILL.md` | Copilot skill for index/focus/generate. | Usually yes |
| `.cursor/rules/gaudi-map.mdc` | Cursor rule: small index + on-demand focus. | Usually yes |
| `.cursor/hooks.json` and `.cursor/hooks/gaudi_*.py` | Cursor lifecycle hooks. | Usually yes |

The default map budget is 2048 tokens. Change it in
`.gaudi/config.json` (`map_tokens`) or for one run with
`gaudi generate --map-tokens <n>`. Optional `exclude` is a list of extra
gitignore-style globs. `max_file_bytes` defaults to 1 MiB.

Stdout-only answers: `index`, `focus`, `where`, `status`, `check-ship`.
`index` / `focus` / `where` still update `.gaudi/cache/tags.sqlite` as they parse.

## Git-optional behavior

Default: if `git rev-parse --is-inside-work-tree` is true, Gaudi lists files
via Git. Otherwise it walks the filesystem with pathspec (`.gitignore` plus
built-in excludes such as `.venv/`, `node_modules/`, `dist/`, `build/`).

`--no-git` forces that walk even inside a Git repo. Use it when Git is the
wrong file list (or unavailable) and you want ignore-file discovery instead
of `ls-files`. The walk records `head: NOGIT` and `dirty: false`. An unborn
Git repo (no commits yet) records `head: UNBORN` when Git is used.

## Agent behavior

`gaudi install` is idempotent. It wires the target repository so agents know
how to use Gaudi:

- GitHub Copilot gets `.github/copilot-instructions.md`.
- GitHub Copilot also gets `.github/skills/gaudi/SKILL.md`.
- Cursor gets `.cursor/rules/gaudi-map.mdc`.
- Cursor gets session lifecycle hooks.

Day-to-day orientation (do not tell agents to always Read `.map`):

1. `gaudi index` for hubs and directory shape.
2. `gaudi focus <path-or-symbol>` for the working area.
3. `gaudi where <symbol>` instead of grep-and-read for a definition.
4. `gaudi status` / `gaudi generate` when the freshness line says stale.

Treat Gaudi output as orientation-only and read real source files before editing.

## Freshness model

`.map` records Git `HEAD` (or `NOGIT` / `UNBORN`), dirty state as informational
metadata, and a source-tree fingerprint of supported-language files.
`gaudi status` ignores dirty: editing a non-source file does not force a
regenerate. `status` opens the tag cache read-only and does not write it.

Query commands parse the live tree without writing cache or map files. If `.map` is
absent, their freshness line is `true` (the answer is live). If `.map` is
present, `fresh: true` only when that map still matches HEAD + tree.

Cursor integration uses two hooks (installed scripts, not daily CLI):

- **sessionStart:** cheap `HEAD` check only; injects a short status message
  such as `Gaudi map: fresh` or `STALE`. It never dumps the map body and does
  not regenerate. A matching HEAD can still hide an uncommitted source-tree
  change — trust `gaudi status` or the query freshness line for the tree.
- **stop:** full freshness check; regenerates with `gaudi generate` if stale.

## Shipping safety

Generated maps are local development artifacts and should not be shipped.
`gaudi generate` and `gaudi install` append:

- `.gitignore` → `.map` and `.gaudi/`
- `.dockerignore` → `.map` and `.gaudi/` (covers `COPY . .`)
- Any existing `*ignore` files (e.g. `.npmignore`, `.vercelignore`, `.helmignore`) → `.map` and `.gaudi/`

The map is **not** added to `.cursorignore` because the agent must be able to
read it. Do not add a `*.map` glob — that hides `.map` from the agent.
Run `gaudi check-ship` before baking an image or publishing build artifacts.

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
ruff check src tests
mypy src
```

The package uses a `src/` layout. The console entry point is:

```text
gaudi = gaudi.cli:main
```

`benchmarks/bench.py` builds a 24-file synthetic Python tree and reports cold
vs warm `gaudi generate` (SQLite cache) plus tokens emitted. From the repo
root, after `python -m pip install -e .`:

```bash
python benchmarks/bench.py
```

## Cursor setup notes

Gaudi cannot flip IDE settings. After the first `gaudi install` in a real project:

1. Cursor **Settings → Hooks**: enable project hooks / trust the workspace.
2. Open the **Hooks** output channel. Start a **new Agent chat**. Confirm `gaudi_session_start` ran and injected a ~2-line status (`Gaudi map: fresh` or `STALE`), not the map body.
3. One-time: `python -m pip install -e .` on the Python Cursor uses for hooks (from this repository).
4. Optional: add a git remote for this repo if you want it on origin (do not expect a push from install).

Until those steps are confirmed, hook runtime in Cursor is **unverified**.

## User skill source

User skill: `/gaudi` at `skills/gaudi/SKILL.md` in this repository.
