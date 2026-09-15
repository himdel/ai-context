run:
	uv run python manage.py runserver $${PORT:-8062}

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
	DJANGO_SETTINGS_MODULE=contexts.settings uv run python -c "import django; django.setup(); from api.models import ConversationIndex; ConversationIndex.objects.all().update(revision=\"\"); print('Reset', ConversationIndex.objects.count(), 'index entries')"

run-%:
	CONTEXTS_INSTANCE=$* PORT=$${PORT:-8063} $(MAKE) run

migrate-%:
	CONTEXTS_INSTANCE=$* uv run python manage.py migrate

reindex-%:
	CONTEXTS_INSTANCE=$* DJANGO_SETTINGS_MODULE=contexts.settings uv run python -c "import django; django.setup(); from api.models import ConversationIndex; ConversationIndex.objects.all().update(revision=\"\"); print('Reset', ConversationIndex.objects.count(), 'index entries')"

.PHONY: run lint fix migrate reindex
