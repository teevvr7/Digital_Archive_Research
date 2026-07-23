"""SQLAlchemy engine and session factory.

A single sync engine is shared by the API (FastAPI runs sync handlers in a
threadpool) and the RQ worker. We connect through Supabase's transaction pooler,
so server-side prepared statements must be disabled (``prepare_threshold=None``).
"""

# create_engine builds the low-level connection pool to Postgres.
from sqlalchemy import create_engine

# sessionmaker builds a factory that produces new ORM Session objects on demand.
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _make_engine():
    """Create the SQLAlchemy engine for the configured database URL."""
    # Extra keyword arguments to pass straight through to the underlying
    # psycopg3 driver connection (not SQLAlchemy itself).
    connect_args: dict = {}
    # psycopg3: disable server-side prepared statements for the transaction pooler.
    if settings.prepare_threshold is None:
        # None tells psycopg3 to never use server-side prepared statements —
        # required because Supabase's transaction pooler recycles the
        # underlying Postgres connection between statements, so a prepared
        # statement from one request could leak into an unrelated one.
        connect_args["prepare_threshold"] = None
    else:
        # Otherwise use whatever numeric threshold was configured.
        connect_args["prepare_threshold"] = settings.prepare_threshold

    return create_engine(
        settings.database_url,  # the Postgres connection string
        pool_pre_ping=True,  # test each connection with a cheap query before reusing it
        pool_size=5,  # keep up to 5 connections open and ready
        max_overflow=5,  # allow up to 5 more temporary connections under load
        future=True,  # opt into SQLAlchemy 2.0-style API behavior
        connect_args=connect_args,  # the psycopg3-specific args built above
    )


# The engine is created once, at import time, and reused for the whole
# process's lifetime — creating a new engine per request would be wasteful
# (each engine manages its own connection pool).
engine = _make_engine()

# SessionLocal is a callable factory: SessionLocal() returns a brand-new
# Session bound to the shared engine above. Every request/job creates its
# own Session so work never gets mixed up between concurrent requests.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,  # don't automatically flush pending changes before every query
    autocommit=False,  # never auto-commit — the caller controls transaction boundaries
    future=True,  # opt into SQLAlchemy 2.0-style Session behavior
)
