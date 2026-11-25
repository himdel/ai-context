# Contexts

Django app serving a REST API and static UI, running via uv.

## Session start

Read `docs/STATE.md` (where things stand) and `docs/IDEAS.md` (the backlog).
`docs/DECISIONS.md` holds the choices already made and why - skim it before reworking
anything in the tmux/session layer.

## Recording rules

- **Record as you go, unasked.** A decision made in conversation evaporates. Record the
  **why**, not just the what; facts recoverable from the code or `git log` do not belong
  in docs.
- **Where things go:** a real choice, or a constraint found the hard way, goes in
  `docs/DECISIONS.md`, newest first, dated. A record-now-do-later goes in
  `docs/IDEAS.md`. Anything user-facing that needs action goes in `CHANGELOG.md` per the
  rules below. Local-only learnings and followups stay in `CLAUDE.local.md`, which is
  gitignored - this repo is published.
- **Memory vs markdown.** Anything about *this repo* goes in `docs/`. Only facts about
  himdel, or how to work with him, belong in Claude memory.
- **Track external tool dependencies explicitly.** `pyproject.toml` only records Python
  deps, but the app shells out to tmux, a terminal emulator, `notify-send`, the `claude`
  binary and git. When adding a feature that shells out, document the tool in the README
  and deps list as **required or optional**, and prefer graceful fallback when an optional
  one is absent. Do this without being reminded.
- Absolute dates, always.

## Layout

| Path | Holds |
|---|---|
| `docs/STATE.md` | Where things stand right now. A snapshot - overwrite freely |
| `docs/DECISIONS.md` | Decision log, newest first, dated |
| `docs/IDEAS.md` | Backlog: record now, do later |
| `docs/CLAUDE-SESSION-FILES.md` | Format and gotchas of `~/.claude/sessions/<pid>.json` |
| `docs/HARNESSES.md` | The harness adapter contract and canonical conversation model |
| `docs/REPORT-ACTIONS.md` | Local report action API, confirmation, grouping and delivery contract |
| `contrib/opencode/` | Optional opencode plugin for repository context metadata |
| `contrib/skills/report-actions/` | Reusable report-authoring skill and registration-only helper |
| `tools/report_actions_smoke.py` | Isolated browser checks for report confirmations; all action APIs mocked |
| `CHANGELOG.md` | For people already running contexts. Rules below |
| `CLAUDE.local.md` | Local learnings and followups. Gitignored, stays out of the public repo |

Adding a file this table does not describe means the table is wrong - update it in the
same commit.

## Commits

- Work directly on `main` - no feature branches unless asked.
- When and how to commit, message style, and the `Co-Authored-By` trailer:
  see `~/.claude/CLAUDE.md`.
- Run `make fix` before staging.

## Running

- `make` / `make run` - start the dev server
- `uv run python manage.py ...` - manage.py commands
- `make fix` - ruff check + format, prettier
- `make lint` - ruff check + format, prettier (check only)

## Frontend

- Single-page app in `static/index.html` + ES modules in `static/js/`
- No build step, no framework - native `<script type="module">` with browser imports
- `static/style.css` - all CSS
- `static/js/utils.js` - pure utility functions, no app state
- `static/js/forge.js` - git forge (GitHub/GitLab/Gitea) URL builders
- `static/js/render.js` - markdown rendering, tool/block rendering, rich diagrams
- `static/vendor/plantuml/` - vendored PlantUML browser engine and support assets
- `static/js/activity.js`, `memories.js`, `repos.js`, `plans.js`, `skills.js`, `cronjobs.js` - per-screen modules
- Screen modules receive shared app state via `initX(deps)` pattern, not direct imports from index.html
- `index.html` is the glue: state management, routing, sidebar, conversations, init wiring

## Changelog

`CHANGELOG.md` is for people already running contexts, not a full history. Add
an entry (newest first) whenever a change:

- breaks existing behavior or usage
- adds or changes a dependency (say whether it's required or optional)
- changes or removes an existing config option or default
- otherwise needs action from current users (e.g. a new migration)

Group entries by date (newest first). Under each date, put an "Action required"
subsection before a "New features" one. Action entries: commit sha, one-line
description, then what breaks and how to cope - keep the reason to a short line,
no long technical rationale. Feature entries: one line with the sha. Skip
ordinary fixes and refactors.

## Invariants

- No containers, everything runs locally via uv
- No auth, CSRF, HTTPS - localhost by default; `BIND` opts into a trusted LAN
- Static files served from `static/` on `/`, with index.html for directories
- REST API on `/api/`
- Report action APIs and `/actions/<UUID>` are always loopback-only, even with LAN `BIND`
- All URL routes must work with and without trailing slash
- Minimal INSTALLED_APPS - only add what's actually needed
- No build step or bundler for frontend - ES modules served directly
- No emojis in code or docs

## Known gaps

- **Launching an agent needs a harness that implements `launch_argv`.** `POST
  /api/sessions/new` takes a `source` (default `claude`); resume and fork take the
  conversation's own. A harness we can only read returns None there and gets no session
  buttons - `can_launch` in the conversation payload says which. See `docs/HARNESSES.md`.
