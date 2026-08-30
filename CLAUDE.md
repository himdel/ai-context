# Contexts

Django app serving a REST API and static UI, running via uv.

## Commits

- Work directly on `main` - no feature branches unless asked.
- When and how to commit, message style, and the `Assisted-by` trailer:
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
- No auth, CSRF, HTTPS - localhost only
- Static files served from `static/` on `/`, with index.html for directories
- REST API on `/api/`
- All URL routes must work with and without trailing slash
- Minimal INSTALLED_APPS - only add what's actually needed
- No build step or bundler for frontend - ES modules served directly
- No emojis in code or docs
