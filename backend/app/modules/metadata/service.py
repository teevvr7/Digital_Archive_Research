"""Metadata Custom Fields service business logic."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_field import CustomField, DocumentFieldValue
from app.models.document_type_field import DocumentTypeField
from app.modules.metadata.schemas import CustomFieldOut, FieldValueOut


def _field_to_out(field: CustomField) -> CustomFieldOut:
    return CustomFieldOut(
        id=field.id,
        tenant_id=field.tenant_id,
        name=field.name,
        field_type=field.field_type,
        options=field.options or [],
        position=field.position,
        created_at=field.created_at,
    )


def list_custom_fields(db: Session, tenant_id: uuid.UUID) -> list[CustomField]:
    """List all custom fields defined for a tenant sorted by position."""
    return (
        db.query(CustomField)
        .filter(CustomField.tenant_id == tenant_id)
        .order_by(CustomField.position.asc(), CustomField.created_at.asc())
        .all()
    )


def create_custom_field(
    db: Session,
    tenant_id: uuid.UUID,
    name: str,
    field_type: str,
    options: list[Any] | None = None,
    position: int = 0,
) -> CustomField:
    """Create a typed custom field definition for a tenant."""
    field = CustomField(
        tenant_id=tenant_id,
        name=name,
        field_type=field_type,
        options=options or [],
        position=position,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


def patch_custom_field(
    db: Session,
    tenant_id: uuid.UUID,
    field_id: uuid.UUID,
    name: str | None = None,
    field_type: str | None = None,
    options: list[Any] | None = None,
    position: int | None = None,
) -> CustomField:
    """Partial update of custom field schema."""
    field = db.get(CustomField, field_id)
    if not field or field.tenant_id != tenant_id:
        raise ValueError("Custom field not found")

    if name is not None:
        field.name = name
    if field_type is not None:
        field.field_type = field_type
    if options is not None:
        field.options = options
    if position is not None:
        field.position = position

    db.commit()
    db.refresh(field)
    return field


def delete_custom_field(db: Session, tenant_id: uuid.UUID, field_id: uuid.UUID) -> None:
    """Delete a custom field definition and its associated values."""
    field = db.get(CustomField, field_id)
    if not field or field.tenant_id != tenant_id:
        raise ValueError("Custom field not found")

    db.delete(field)
    db.commit()


def assign_field_to_type(
    db: Session,
    tenant_id: uuid.UUID,
    document_type_id: uuid.UUID,
    field_id: uuid.UUID,
    is_required: bool = False,
    position: int = 0,
) -> DocumentTypeField:
    """Assign a predefined custom field to a DocumentType."""
    existing = (
        db.query(DocumentTypeField)
        .filter(
            DocumentTypeField.tenant_id == tenant_id,
            DocumentTypeField.document_type_id == document_type_id,
            DocumentTypeField.field_id == field_id,
        )
        .first()
    )
    if existing:
        existing.is_required = is_required
        existing.position = position
        db.commit()
        db.refresh(existing)
        return existing

    mapping = DocumentTypeField(
        tenant_id=tenant_id,
        document_type_id=document_type_id,
        field_id=field_id,
        is_required=is_required,
        position=position,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def list_type_fields(db: Session, tenant_id: uuid.UUID, document_type_id: uuid.UUID) -> list[DocumentTypeField]:
    """Get all predefined custom fields configured for a specific DocumentType."""
    return (
        db.query(DocumentTypeField)
        .filter(
            DocumentTypeField.tenant_id == tenant_id,
            DocumentTypeField.document_type_id == document_type_id,
        )
        .order_by(DocumentTypeField.position.asc())
        .all()
    )


def fetch_field_values_for_docs(db: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[FieldValueOut]]:
    """Batch fetch all custom field values assigned to a list of document IDs."""
    if not doc_ids:
        return {}

    values = (
        db.query(DocumentFieldValue)
        .filter(DocumentFieldValue.document_id.in_(doc_ids))
        .all()
    )

    result: dict[uuid.UUID, list[FieldValueOut]] = {did: [] for did in doc_ids}
    for fv in values:
        field_out = _field_to_out(fv.field) if fv.field else None
        out = FieldValueOut(
            id=fv.id,
            document_id=fv.document_id,
            field_id=fv.field_id,
            value=fv.value,
            field=field_out,
        )
        result[fv.document_id].append(out)

    return result


def set_field_value(
    db: Session,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    field_id: uuid.UUID,
    value: Any,
) -> DocumentFieldValue:
    """Set or update a custom field value on a specific document."""
    field = db.get(CustomField, field_id)
    if not field or field.tenant_id != tenant_id:
        raise ValueError("Custom field not found")

    existing = (
        db.query(DocumentFieldValue)
        .filter(
            DocumentFieldValue.tenant_id == tenant_id,
            DocumentFieldValue.document_id == document_id,
            DocumentFieldValue.field_id == field_id,
        )
        .first()
    )

    if existing:
        existing.value = value
        db.commit()
        db.refresh(existing)
        return existing

    fv = DocumentFieldValue(
        tenant_id=tenant_id,
        document_id=document_id,
        field_id=field_id,
        value=value,
    )
    db.add(fv)
    db.commit()
    db.refresh(fv)
    return fv


def delete_field_value(
    db: Session,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    field_id: uuid.UUID,
) -> None:
    """Remove a custom field value from a document."""
    existing = (
        db.query(DocumentFieldValue)
        .filter(
            DocumentFieldValue.tenant_id == tenant_id,
            DocumentFieldValue.document_id == document_id,
            DocumentFieldValue.field_id == field_id,
        )
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
