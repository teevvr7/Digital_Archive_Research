"""Tests for the Spreadsheet Center export module.

Covers:
- Alias normalisation & parse_amount utilities (pure unit tests)
- /export/meta endpoint
- /export/fields endpoint
- /export/spreadsheet endpoint
"""

import csv
import io
import json
import uuid
from datetime import date
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.main import app
from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.models.document import Document, STATUS_COMPLETED
from app.models.document_type import DocumentType
from app.models.document_template import DocumentTemplate, TEMPLATE_PROMOTED
from app.modules.export.normalise import normalise_keys, parse_amount


@pytest.fixture
def mock_auth_ctx():
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    token = TokenData({
        "sub": user_id,
        "email": "admin@example.com",
        "app_metadata": {
            "tenant_id": tenant_id,
            "role": "admin",
        },
    })
    db = MagicMock()
    return db, token


def test_normalise_utilities():
    # 1. Alias mapping checks
    data = {
        "vendor_name": "Acme Corp",
        "invoice_no": "INV-001",
        "grand_total": "$ 1,234.56",
        "line_items": [{"description": "Item 1", "amount": 100.0}],
        "custom_unrelated_key": "some_value"
    }
    norm = normalise_keys(data)
    assert norm["vendor"] == "Acme Corp"
    assert norm["invoiceNumber"] == "INV-001"
    assert norm["totalAmount"] == "$ 1,234.56"
    assert "lineItems" in norm
    assert norm["custom_unrelated_key"] == "some_value"

    # 2. Currency parser checks
    assert parse_amount("$ 1,234.56") == 1234.56
    assert parse_amount("RM500") == 500.0
    assert parse_amount(100) == 100.0
    assert parse_amount(None) is None
    assert parse_amount("not_a_number") is None


def test_export_meta_endpoint(mock_auth_ctx):
    db, token = mock_auth_ctx

    doc_type = DocumentType(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(token.tenant_id),
        name="invoice",
        json_schema={}
    )

    template = DocumentTemplate(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(token.tenant_id),
        document_type_id=doc_type.id,
        name="Invoice Template",
        status=TEMPLATE_PROMOTED
    )

    # Mock database queries inside get_export_meta using side effects for join/filter
    mock_query_dt = MagicMock()
    mock_query_dt.filter.return_value.all.return_value = [doc_type]

    mock_query_tpl = MagicMock()
    mock_query_tpl.join.return_value.filter.return_value.all.return_value = [(template, doc_type)]

    def db_query_side_effect(*args):
        if len(args) == 1 and args[0] == DocumentType:
            return mock_query_dt
        return mock_query_tpl

    db.query.side_effect = db_query_side_effect
    db.execute.return_value.all.return_value = [("invoice", 3)]

    def override_get_tenant_db():
        yield db, token

    app.dependency_overrides[get_tenant_db] = override_get_tenant_db
    client = TestClient(app)

    response = client.get("/api/export/meta")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "documentTypes" in data
    assert "templates" in data
    assert data["documentTypes"][0]["name"] == "invoice"
    assert data["documentTypes"][0]["count"] == 3
    assert data["templates"][0]["name"] == "Invoice Template"

    app.dependency_overrides.clear()


def test_export_fields_endpoint(mock_auth_ctx):
    db, token = mock_auth_ctx

    # Mock DB query for existing keys in database
    db.scalars.return_value.all.return_value = ["vendor_name", "invoice_no", "line_items"]

    def override_get_tenant_db():
        yield db, token

    app.dependency_overrides[get_tenant_db] = override_get_tenant_db
    client = TestClient(app)

    # When no template is selected
    response = client.post("/api/export/fields", json={"documentType": "invoice"})
    assert response.status_code == status.HTTP_200_OK
    fields = response.json()
    # "vendor_name" -> "vendor", "invoice_no" -> "invoiceNumber"
    # "line_items" is filtered out from fields because it is an array key
    assert "vendor" in fields
    assert "invoiceNumber" in fields
    assert "lineItems" not in fields

    app.dependency_overrides.clear()


def test_export_spreadsheet_preview_and_csv(mock_auth_ctx):
    db, token = mock_auth_ctx

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(token.tenant_id),
        filename="invoice_a.pdf",
        original_filename="invoice_a.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        storage_key="store_a",
        status=STATUS_COMPLETED,
        document_type="invoice",
        extracted_data={
            "vendor_name": "ODETTE'S FLORALS",
            "invoice_no": "1001",
            "grand_total": "$ 250.00",
            "line_items": [
                {
                    "parent_item_description": "Bridal Bouquet",
                    "parent_quantity": 1,
                    "parent_unit_price": "$ 250.00",
                    "parent_total_amount": "$ 250.00",
                    "sub_items": [
                        {"sub_item_description": "5 Wild Flowers", "sub_quantity": 5}
                    ]
                }
            ]
        },
        uploaded_by=uuid.uuid4(),
        uploaded_at=date(2026, 7, 10)
    )

    db.scalars.return_value.all.return_value = [doc]

    def override_get_tenant_db():
        yield db, token

    app.dependency_overrides[get_tenant_db] = override_get_tenant_db
    client = TestClient(app)

    # 1. Test preview JSON (summary mode)
    response = client.post(
        "/api/export/spreadsheet?format=preview",
        json={
            "documentType": "invoice",
            "columns": ["vendor", "invoiceNumber", "totalAmount"],
            "mode": "summary"
        }
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "rows" in data
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["vendor"] == "ODETTE'S FLORALS"
    assert row["invoiceNumber"] == "1001"
    assert row["totalAmount"] == 250.0  # parsed float
    assert row["itemCount"] == 1

    # 2. Test preview JSON (expanded mode)
    response = client.post(
        "/api/export/spreadsheet?format=preview",
        json={
            "documentType": "invoice",
            "columns": ["vendor", "invoiceNumber"],
            "mode": "expanded"
        }
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    rows = data["rows"]
    assert len(rows) == 2  # 1 parent + 1 sub-item
    assert rows[0]["depth"] == 0
    assert rows[0]["itemDescription"] == "Bridal Bouquet"
    assert rows[1]["depth"] == 1
    assert rows[1]["itemDescription"] == "5 Wild Flowers"

    # 3. Test CSV download format (summary mode)
    response = client.post(
        "/api/export/spreadsheet?format=csv",
        json={
            "documentType": "invoice",
            "columns": ["vendor", "invoiceNumber", "totalAmount"],
            "mode": "summary"
        }
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["Content-Disposition"] == "attachment; filename=export.csv"
    csv_text = response.text
    reader = csv.DictReader(io.StringIO(csv_text))
    csv_rows = list(reader)
    assert len(csv_rows) == 1
    assert csv_rows[0]["vendor"] == "ODETTE'S FLORALS"
    assert csv_rows[0]["totalAmount"] == "250.0"

    app.dependency_overrides.clear()
