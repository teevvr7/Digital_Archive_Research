"""Pytest bootstrap for the backend test suite.

Loads ``backend/.env`` into ``os.environ`` so the DB-gated tests (tenant
isolation, search) can read ``ALEMBIC_DATABASE_URL``.

Why this is needed: the app's pydantic settings load ``.env`` via
``env_file=".env"``, but that only populates the ``settings`` object — it never
exports into ``os.environ``. The DB-gated tests check
``os.environ.get("ALEMBIC_DATABASE_URL")`` directly, so without this they skip
even when the value is present in ``.env``. ``load_dotenv`` bridges that gap with
no manual ``export`` required. (python-dotenv is already a project dependency.)
"""

from pathlib import Path

from dotenv import load_dotenv

# backend/app/tests/conftest.py → backend/.env
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)
