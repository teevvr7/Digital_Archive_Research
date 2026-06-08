"""Alembic environment configuration.

Uses ALEMBIC_DATABASE_URL (direct/session connection on port 5432) — NOT the
transaction pooler — because migrations need a stable session and may use
features unsupported in transaction mode (e.g. CREATE INDEX CONCURRENTLY).
"""

import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend root (two levels up from this file).
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so their metadata is registered on Base.metadata.
import app.models  # noqa: F401
from app.models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Set ALEMBIC_DATABASE_URL (direct/session, port 5432) before running Alembic."
        )
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # one connection per migration run, released immediately
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
