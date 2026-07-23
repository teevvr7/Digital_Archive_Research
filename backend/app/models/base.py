"""Declarative base and shared mixins."""

import datetime
import uuid

# DateTime is the column type; MetaData holds naming rules; func gives SQL functions like now().
from sqlalchemy import DateTime, MetaData, func

# DeclarativeBase is what every ORM model class inherits from (directly or
# indirectly). Mapped/mapped_column are the SQLAlchemy 2.0-style way of
# declaring a typed column.
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint naming so Alembic autogenerate / downgrades are deterministic.
# Without this, Postgres/SQLAlchemy would pick auto-generated constraint names
# that can differ between runs, making migration diffs unpredictable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",  # index names, e.g. ix_documents_tenant_id
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # unique constraint names
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # check constraint names
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",  # foreign key names
    "pk": "pk_%(table_name)s",  # primary key names
}


class Base(DeclarativeBase):
    """Project-wide declarative base."""

    # Every table created from this Base uses the naming convention above,
    # so all constraint names across the entire schema are predictable.
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key column (Python-side default so ORM inserts get an id)."""
    # default=uuid.uuid4 means a new random UUID is generated in Python the
    # moment a new row object is created — before it's even sent to the
    # database — so the id is available immediately (e.g. for logging).
    return mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Adds a server-defaulted ``created_at`` column."""

    # Any model that inherits this mixin (alongside Base) automatically gets
    # a created_at column. server_default=func.now() means POSTGRES itself
    # fills in the value at insert time (not Python), so it's accurate even
    # if the app server's clock is wrong.
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
