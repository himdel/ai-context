# Contexts

Django app serving a REST API and static UI, running via uv.

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

## Invariants

- No containers, everything runs locally via uv
- No auth, CSRF, HTTPS - localhost only
- Static files served from `static/` on `/`, with index.html for directories
- REST API on `/api/`
- All URL routes must work with and without trailing slash
- Minimal INSTALLED_APPS - only add what's actually needed
- No build step or bundler for frontend - ES modules served directly
- No emojis in code or docs
