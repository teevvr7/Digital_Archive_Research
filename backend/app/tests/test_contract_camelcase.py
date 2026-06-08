"""API contract test — every response field must be camelCase.

Prevents the silent regression where a snake_case field leaks to the frontend
and renders as ``undefined`` in the UI.
"""

import re

from app.modules.auth.schemas import MeOut, TenantOut, UserOut

CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")


def _assert_all_camel(schema_class, seen: set | None = None):
    if seen is None:
        seen = set()
    if schema_class in seen:
        return
    seen.add(schema_class)

    for field_name, field_info in schema_class.model_fields.items():
        alias = schema_class.model_config.get("alias_generator", lambda x: x)(field_name)
        assert CAMEL_RE.match(alias), (
            f"{schema_class.__name__}.{field_name} serialises as '{alias}' — not camelCase"
        )


def test_user_out_is_camel():
    _assert_all_camel(UserOut)


def test_tenant_out_is_camel():
    _assert_all_camel(TenantOut)


def test_me_out_is_camel():
    _assert_all_camel(MeOut)
