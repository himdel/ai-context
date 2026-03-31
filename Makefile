run:
	uv run python manage.py runserver 127.0.0.1:8000

lint:
	uv run ruff check
	uv run ruff format --check

fix:
	uv run ruff check --fix
	uv run ruff format

migrate:
	uv run python manage.py migrate

.PHONY: run lint fix migrate
