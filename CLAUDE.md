# Contexts

Django app serving a REST API and static UI, running via uv.

## Running

- `make` / `make run` - start the dev server
- `uv run python manage.py ...` - manage.py commands
- `make fix` - ruff check + format
- `make lint` - ruff check + format (check only)

## Invariants

- No containers, everything runs locally via uv
- No auth, CSRF, HTTPS - localhost only
- Static files served from `static/` on `/`, with index.html for directories
- REST API on `/api/`
- All URL routes must work with and without trailing slash
- Minimal INSTALLED_APPS - only add what's actually needed
- No emojis in code or docs
