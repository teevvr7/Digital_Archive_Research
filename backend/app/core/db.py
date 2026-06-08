"""SQLAlchemy engine and session factory.

A single sync engine is shared by the API (FastAPI runs sync handlers in a
threadpool) and the RQ worker. We connect through Supabase's transaction pooler,
so server-side prepared statements must be disabled (``prepare_threshold=None``).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _make_engine():
    """Create the SQLAlchemy engine for the configured database URL."""
    connect_args: dict = {}
    # psycopg3: disable server-side prepared statements for the transaction pooler.
    if settings.prepare_threshold is None:
        connect_args["prepare_threshold"] = None
    else:
        connect_args["prepare_threshold"] = settings.prepare_threshold

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
        connect_args=connect_args,
    )


engine = _make_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
