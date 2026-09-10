# Gaudi

Ranked signature map for AI coding agents (GitHub Copilot and Cursor). Parses Python, JavaScript, and TypeScript with tree-sitter, ranks defs with PageRank, and writes a **cues-only** outline to `.map` in the repository root. Agents still **Read** real files. Nobody hand-edits the map.

Requires Python 3.11+. No Aider.

## Install the CLI (once)

```powershell
pip install -e C:\Users\einfantino\projects\gaudi
```

## Use in any repo

```powershell
cd C:\Users\einfantino\projects\<repo>
gaudi generate
gaudi status
gaudi check-ship
```

`gaudi generate` is standalone and self-contained:
- Automatically secures `.map` and `.gaudi/` in `.gitignore`, `.dockerignore`, and any other `*ignore` files in the repository.
- Generates the map at `.map` in the repository root.
- Caches tags and stores configuration in `.gaudi/`.

Optional environment integration:
```powershell
gaudi install [--target all|cursor|copilot]
```
`install` is idempotent. It merges `.cursor/hooks.json` (for Cursor), appends instructions to `.github/copilot-instructions.md` (for GitHub Copilot), installs the `.github/skills/gaudi/SKILL.md` Copilot skill, writes `.cursor/rules/gaudi-map.mdc`, appends ignore rules, and generates `.map`.

The Copilot skill teaches agents that a request to generate or refresh a Gaudi
map means running `gaudi generate`, checking freshness with `gaudi status`, and
reading real source files rather than treating `.map` as authoritative.

Map path is `.map`. Cache: `.gaudi/cache/`. Config: `.gaudi/config.json` (`map_tokens`: 2048).

## Never ship the map

`gaudi generate` and `install` append:

- `.gitignore` → `.map` and `.gaudi/`
- `.dockerignore` → `.map` and `.gaudi/` (covers `COPY . .`)
- Any existing `*ignore` files (e.g. `.npmignore`, `.vercelignore`, `.helmignore`) → `.map` and `.gaudi/`

The map is **not** added to `.cursorignore` (the Agent must be able to Read it). Run `gaudi check-ship` before you bake an image or publish `dist/`.

## Hooks (project-level)

- **sessionStart:** cheap SHA/dirty check; injects ~2 lines of `additional_context`. Never dumps `.map`. Fire-and-forget (does not regenerate).
- **stop:** regenerates if the map is stale vs the worktree. Fail-open if `gaudi` is not installed.
- **afterFileEdit:** not used (body edits do not change signatures).

This repo does **not** replace `C:\Users\einfantino\.cursor\hooks.json` (keep the existing noop `sessionStart` and logbook `stop`).

### Cloud Agent

`sessionStart` does not run on Cloud Agent. The map is gitignored, so a cloud session starts without `.map`. The project rule still tells the agent to run `gaudi generate` if the file is missing. Cloud must have this package installed or generate is a no-op.

## Cursor Settings / Hooks tab (manual — Evan)

Gaudi cannot flip IDE settings. After the first `gaudi install` in a real project:

1. Cursor **Settings → Hooks**: enable project hooks / trust the workspace.
2. Open the **Hooks** output channel. Start a **new Agent chat**. Confirm `gaudi_session_start` ran and injected a ~2-line status (`Gaudi map: fresh` or `STALE — run gaudi generate before Read`), not the map body.
3. One-time: `pip install -e C:\Users\einfantino\projects\gaudi` on the Python Cursor uses for hooks.
4. Optional: add a git remote for `projects/gaudi` if you want it on origin (do not expect a push from install).

Until those steps are confirmed, hook runtime in Cursor is **unverified**.

## Slash command

User skill: `/gaudi` (`disable-model-invocation: true`) at `C:\Users\einfantino\.cursor\skills\gaudi\SKILL.md` (source copy in this repo: `skills/gaudi/SKILL.md`).
