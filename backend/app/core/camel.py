"""Shared Pydantic base model that serialises snake_case fields as camelCase.

The frontend consumes camelCase JSON (e.g. ``originalFilename``) while the Python/DB
layer uses snake_case (``original_filename``). Every API schema inherits from
:class:`CamelModel` so the conversion is automatic and consistent, and so response
objects can be built straight from SQLAlchemy ORM rows.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model: camelCase aliases, ORM construction, snake_case population."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    def to_response(self) -> dict[str, Any]:
        """Serialise using camelCase aliases (handy outside of FastAPI routes)."""
        return self.model_dump(by_alias=True)
