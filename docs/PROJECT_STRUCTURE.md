# Project Structure

This repository is structured as a production Django platform for the PNG Nursing Council and Medical Board online registration workflows.

## Source Layout

- `manage.py` - Django management entrypoint.
- `ndoh_workforce_registry/` - project configuration, URL routing, WSGI/ASGI, middleware, and settings.
- `apps/` - business-domain Django applications.
- `templates/` - shared project templates and app template overrides.
- `static/` - source static assets maintained in version control.
- `docs/` - operating guides, launch documentation, security matrices, generated brief source files, and project governance material.
- `docker/` - container build assets.
- `tools/` - local audit, maintenance, and data inspection utilities.
- `notebooks/` - local data-cleansing notebooks and templates. Raw workbooks and generated data extracts are excluded from source control.
- `docs/status/` - historical fix summaries and management status reports.

## Runtime-Only Paths

The following paths are intentionally excluded from version control:

- `.env` and `.runtime_secret_key` - local secrets.
- `db.sqlite3` and `*.sqlite3` - developer databases.
- `media/` - uploaded documents and repository files.
- `staticfiles/` - generated `collectstatic` output.
- `__pycache__/`, `.pytest_cache/`, and other local caches.
- `docs/command_logs/` - machine-generated command output.

## Production Baseline

Production deployments should use:

- `DEBUG=False`.
- PostgreSQL through `DATABASE_ENGINE=postgresql`.
- strong `SECRET_KEY` supplied by the hosting secret store.
- explicit `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- HTTPS security settings enabled.
- a non-root container user, as defined in `docker/Dockerfile`.

Use `.env.example` as the starting point for environment provisioning.
