"""Shared Pydantic base model that serialises snake_case fields as camelCase.

The frontend consumes camelCase JSON (e.g. ``originalFilename``) while the Python/DB
layer uses snake_case (``original_filename``). Every API schema inherits from
:class:`CamelModel` so the conversion is automatic and consistent, and so response
objects can be built straight from SQLAlchemy ORM rows.
"""

# Any is used for the generic dict returned by to_response().
from typing import Any

# BaseModel is pydantic's core class every schema ultimately inherits from.
# ConfigDict is how pydantic v2 configures model-wide behavior (as opposed to
# per-field behavior).
from pydantic import BaseModel, ConfigDict

# to_camel is a built-in pydantic helper that turns "original_filename" into
# "originalFilename" — we reuse it instead of writing our own converter.
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model: camelCase aliases, ORM construction, snake_case population."""

    # model_config controls this class (and every subclass that doesn't override it):
    model_config = ConfigDict(
        # Every field gets an automatic camelCase "alias" derived from its
        # snake_case Python name, used when serialising to JSON.
        alias_generator=to_camel,
        # Still allow constructing the model using the original snake_case
        # names in Python code (e.g. UserOut(user_id=...)), not just the alias.
        populate_by_name=True,
        # Allow building the model directly from an object's attributes
        # (e.g. a SQLAlchemy row), not just from a dict — this is what makes
        # `UserOut.model_validate(db_user)` work.
        from_attributes=True,
    )

    def to_response(self) -> dict[str, Any]:
        """Serialise using camelCase aliases (handy outside of FastAPI routes)."""
        # by_alias=True forces the camelCase names into the resulting dict,
        # exactly as they'd appear in the JSON body of an API response.
        return self.model_dump(by_alias=True)
