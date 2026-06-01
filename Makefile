run:
	uv run python manage.py runserver 127.0.0.1:8042

lint:
	uv run ruff check
	uv run ruff format --check
	./node_modules/.bin/prettier --check static/

fix:
	uv run ruff check --fix
	uv run ruff format
	./node_modules/.bin/prettier --write static/

migrate:
	uv run python manage.py migrate

reindex:
	DJANGO_SETTINGS_MODULE=contexts.settings uv run python -c "import django; django.setup(); from api.models import ConversationIndex; ConversationIndex.objects.all().update(file_mtime=0); print('Reset', ConversationIndex.objects.count(), 'index entries')"

.PHONY: run lint fix migrate reindex
