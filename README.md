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
| Token scorecard (human) | `gaudi stats` / `gaudi stats --ab` |
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
gaudi stats
```

| Command | Purpose | Writes |
|---|---|---|
| `gaudi generate [--map-tokens N]` | Parse sources, update ignore files, cache tags in SQLite, write `.map`. | `.map`, `.gaudi/`, ignore files, ledger row |
| `gaudi status` | Exit 0 only when `.map` matches HEAD and the source-tree fingerprint. Silent. Does not write the cache. | nothing |
| `gaudi index [--tokens 250] [--format json]` | Top hubs plus directory shape with def counts. | tag cache + ledger row |
| `gaudi focus <path\|symbol>... [--tokens 512] [--format json]` | Personalized PageRank neighborhood to stdout. Never writes `.map`. | tag cache + ledger row |
| `gaudi where <symbol> [--format json]` | Print `path:line` plus signature. | tag cache + ledger row |
| `gaudi check-ship` | Fail if the map could be copied into Docker/build/dist output. | nothing |
| `gaudi install [--target all\|cursor\|copilot\|claude\|agents] [--yes] [--with-ledger]` | Install agent-facing instructions/hooks, update ignore files, and generate the map (quiet). `--with-ledger` is opt-in. | agent files + generate outputs |
| `gaudi stats [--format json] [--ab]` | Human-facing token scorecard from `.gaudi/ledger.sqlite`. Not mentioned in agent rules. | nothing |

Global flags (before the subcommand): `--version`, `--quiet` / `-q`, `--no-git`, `--root <dir>`.

`--quiet` suppresses the generate summary and the `*.map` hide warning from
`generate`, `index`, and `focus`. `--map-tokens` / `--tokens` apply to that
invocation only; persist a map budget in `.gaudi/config.json`.

`focus`, `where`, and `index` accept `--format json`. JSON includes
`baseline_tokens` and `saved_tokens`. Text output includes a freshness line
(`fresh: true|false`) and truncation markers (`⋮ +N more defs`).

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
| `.gaudi/ledger.sqlite` | Token scorecard ledger (queries always; reads/sessions when `--with-ledger`). | No |
| `.gaudi/config.json` | Local configuration (`map_tokens`, optional `exclude`, `max_file_bytes`, optional `ledger`). | No |
| `.dockerignore` | Created/updated so `COPY . .` does not ship the map. | Yes |
| `CLAUDE.md` | Claude Code orientation installed by `gaudi install --target claude` or `all`. | Usually yes |
| `AGENTS.md` | Generic agent orientation installed by `gaudi install --target agents` or `all`. | Usually yes |
| `.github/copilot-instructions.md` | Copilot orientation installed by `gaudi install --target copilot` or `all`. | Usually yes |
| `.github/skills/gaudi/SKILL.md` | Copilot skill for index/focus/generate. | Usually yes |
| `.cursor/rules/gaudi-map.mdc` | Cursor rule: small index + on-demand focus. | Usually yes |
| `.cursor/hooks.json` and `.cursor/hooks/gaudi_*.py` | Cursor lifecycle hooks. Ledger shim only with `--with-ledger`. | Usually yes |
| `.github/hooks/gaudi-ledger.json` and `gaudi_ledger.py` | Copilot ledger hooks (`--with-ledger`). | Usually yes |
| `.claude/settings.json` and `.claude/hooks/gaudi_ledger.py` | Claude ledger hooks (`--with-ledger`); other settings keys are preserved. | Usually yes |

The default map budget is 2048 tokens. Change it in
`.gaudi/config.json` (`map_tokens`) or for one run with
`gaudi generate --map-tokens <n>`. Optional `exclude` is a list of extra
gitignore-style globs. `max_file_bytes` defaults to 1 MiB. Optional nested
`ledger` keys are listed under [Token scorecard](#token-scorecard). Bad types
fail fast, same as `exclude`.

Stdout-only answers: `index`, `focus`, `where`, `status`, `check-ship`, `stats`.
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

- Claude Code gets `CLAUDE.md`.
- Generic agents get `AGENTS.md`.
- GitHub Copilot gets `.github/copilot-instructions.md`.
- GitHub Copilot also gets `.github/skills/gaudi/SKILL.md`.
- Cursor gets `.cursor/rules/gaudi-map.mdc`.
- Cursor gets session lifecycle hooks.

Missing instruction files are created with the shared Gaudi section. If a file
already contains `## Gaudi Map` (or the Cursor rule is already ours), install
skips it. If the file exists without that marker, an interactive TTY asks
before appending markdown or replacing `.cursor/rules/gaudi-map.mdc` (default
**No**). Non-TTY runs skip those existing files unless you pass `--yes` / `-y`.
Cursor hooks are still merged silently.

`gaudi install --with-ledger` adds an extra shared hook shim for the same
`--target` (Cursor / Copilot / Claude). Default `gaudi install` is unchanged.
The generic `agents` target never gets hooks.

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

## Token scorecard

`gaudi stats` estimates orientation compression the same way RTK does:
`(len(text) + 3) // 4`. Percentages are comparable; absolute counts are
approximate. No harness exposes billed tokens, output tokens, or provider
cache hits, so this is **not** a dollar figure.

It is a human command. Do not add it to agent rules, Copilot instructions, or
skills — those files sit in context every turn.

### Turn it on

| Tier | How | What you get |
|---|---|---|
| A (default) | Run `generate` / `index` / `focus` / `where` as usual. Disable with `ledger.enabled: false`. | Gross compression: emitted vs a local baseline. One SQLite row per command; no extra file I/O. |
| B (opt-in) | `gaudi install --with-ledger` (follows `--target`) | Observed file reads, first vs repeat in a session, instruction overhead, compaction. Spawns Python per observed tool — use this for eval runs, not by default. |

```bash
gaudi install --with-ledger
gaudi stats
gaudi stats --format json
gaudi stats --ab
```

`--with-ledger` for `cursor` / `copilot` / `claude` installs a shared shim.
`agents` has no hook API, so it stays Tier A.

Example (`gaudi stats` after some queries; reads stay zero until Tier B):

```text
Gaudi scorecard — chars/4 estimate, not billed tokens

MEASURED (0 sessions, CLI estimates only, harness=none)
  reads         0 files   0 tokens   (first 0 / repeat 0)
  gaudi output  2 calls    420 tokens
  instruction  0 sessions 0 tokens
  compactions   0 sessions had 1+

ATTRIBUTED (counterfactual)
  surfaced, never read   0 files   0 tokens

NET (cache_read_multiplier 0.1)
  credit 0  debit 420  net -420 input tokens avoided

GROSS COMPRESSION (rtk gain comparable)
  focus  180 emitted / 8.4k baseline  98%
  index  240 emitted / 2.0k baseline  88%

Not measurable locally: dollars, output tokens, turn-count effects. Run `gaudi stats --ab`.
```

**MEASURED** is observed. **ATTRIBUTED** is a counterfactual: files a query
surfaced that were never read in that session (needs Tier B). **NET** weights
fresh tokens at full price and later turns / repeats at
`cache_read_multiplier` (default 0.1), then subtracts Gaudi's own output and
instruction overhead. **GROSS** is the RTK-style headline (`baseline - emitted`).

Baselines:

| Command | Emitted | Baseline |
|---|---|---|
| `generate` | `.map` | All indexed source files |
| `index` | index text | `.map` if present, else all indexed source |
| `focus` | focus text | Source of **shown** files only |
| `where` | where text | Matching files |

`--format json` on `index` / `focus` / `where` includes `baseline_tokens` and
`saved_tokens`.

### Config

Optional nested object in `.gaudi/config.json`:

```json
{
  "map_tokens": 2048,
  "ledger": {
    "enabled": true,
    "cache_read_multiplier": 0.1,
    "arm": null,
    "min_sessions": 10
  }
}
```

`GAUDI_LEDGER_ARM=on|off` overrides `ledger.arm` for a paired trial. Session
start stamps `on` when that harness's Gaudi marker is installed, else `off`.

### A/B

`gaudi stats --ab` compares per-session **measured** medians (read tokens,
Gaudi emitted, turns) within a harness, then overall. Below `min_sessions`
(default 10) per arm per harness it prints counts and refuses a verdict.
Mixing Cursor and Copilot sessions into one median would hide hook-coverage
differences, so the report does not do that.

### What Tier B can and cannot see

| Target | Records | Instruction overhead | Known gap |
|---|---|---|---|
| `cursor` | File reads, session/turns, compaction | Whole `.cursor/rules/gaudi-map.mdc` | Hook runtime still needs the [Cursor setup notes](#cursor-setup-notes) |
| `copilot` | File reads, session/stop, compaction | Gaudi section of `.github/copilot-instructions.md` | Copilot agent hooks are Preview; matchers are ignored so the shim filters tool names |
| `claude` | File reads (Read tool), session, compaction | Gaudi section of `CLAUDE.md` | `@`-mentions skip the Read hook, so those bytes are not counted |
| `agents` | none | Gaudi section of `AGENTS.md` (Tier A debit only) | No hook API |

The ledger stores counts, paths, and hashes — never file bodies. Hooks fail
open so a scorecard bug cannot block Read.

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

Representative numbers from that fixture (local Windows run, 2026-09-11):

| Metric | Value |
|---|---|
| Files / defs / tokens | 24 / 192 / 1086 |
| Cold generate | 0.60s |
| Warm generate (median of 3) | 0.019s |
| Cache speedup | ~32x |

Times vary by machine. Re-run the script for current numbers.

## Cursor setup notes

Gaudi cannot flip IDE settings. After the first `gaudi install` in a real project:

1. Cursor **Settings → Hooks**: enable project hooks / trust the workspace.
2. Open the **Hooks** output channel. Start a **new Agent chat**. Confirm `gaudi_session_start` ran and injected a ~2-line status (`Gaudi map: fresh` or `STALE`), not the map body.
3. One-time: `python -m pip install -e .` on the Python Cursor uses for hooks (from this repository).
4. Optional: add a git remote for this repo if you want it on origin (do not expect a push from install).
5. For the scorecard's observed-read tier: `gaudi install --target cursor --with-ledger`, then confirm `gaudi_ledger` also fires on a file read. The sessionStart message stays two lines; it never dumps stats into context.

Until those steps are confirmed, hook runtime in Cursor is **unverified**.

## Copilot and Claude ledger notes

Same Python requirement as Cursor hooks (`python -m pip install -e .` on the
interpreter the harness uses).

- **GitHub Copilot (VS Code):** `gaudi install --target copilot --with-ledger`
  writes `.github/hooks/gaudi-ledger.json`. Agent hooks are Preview and may be
  disabled by org policy. Confirm in **Developer: Show Agent Debug Logs**.
- **Claude Code:** `gaudi install --target claude --with-ledger` merges a
  matcher block into `.claude/settings.json` (other keys are kept) and copies
  `.claude/hooks/gaudi_ledger.py`. Type `/hooks` to confirm the Gaudi entries.
  `@file` references are not Read tool calls, so they will not show up as
  measured reads.

## User skill source

User skill: `/gaudi` at `skills/gaudi/SKILL.md` in this repository.
