---
name: gaudi
description: >-
  Install and generate the Gaudi ranked codebase map into the current workspace (CLI check,
  agent rules / Copilot instructions, hooks merge, gitignore/dockerignore, initial generate).
---

# Gaudi Codebase Map

Run this in the **target repo** (the project to map).

## 1. Verify or Install Gaudi CLI

Check if Gaudi is available:
```powershell
python -c "import gaudi"
```
If not installed:
```powershell
pip install -e C:\Users\einfantino\projects\gaudi
```

## 2. Run Installation

From the workspace root, run:
```powershell
gaudi install
```
(Or `python -m gaudi install`).
This command is idempotent:
- Appends `.cursor/gaudi/` to `.gitignore` and `.dockerignore`.
- Configures Cursor rules and hooks in `.cursor/` (if using Cursor).
- Merges Gaudi orientation instructions into `.github/copilot-instructions.md` (for GitHub Copilot).
- Generates the initial ranked signature map at `.cursor/gaudi/MAP.md`.

## 3. Using the Map in GitHub Copilot & Cursor

- **Read the Map for Orientation:** Before wide recursive searches, read `.cursor/gaudi/MAP.md` for high-PageRank architectural hubs and signatures.
- **Refresh Staleness:** If the map is missing or out-of-date, run:
  ```powershell
  gaudi generate
  ```
- **Source of Truth:** Grep and view the actual source files before modifying code. Never treat the map as the full source of truth or edit `MAP.md` by hand.

