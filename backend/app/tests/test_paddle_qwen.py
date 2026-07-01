import json
import uuid
from unittest.mock import MagicMock, patch
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.core.deps import get_tenant_db
from app.core.security import TokenData
from app.models.document_type import DocumentType
from app.models.document_template import DocumentTemplate
from app.modules.idp.paddle_qwen import (
    html_table_to_markdown,
    clean_ocr_text,
    attempt_json_recovery,
    ensure_structure,
    validate_extraction,
    run_paddle_ocr_prediction,
    extract_from_ocr_text,
    run_remote_paddle_qwen_extraction,
)
from app.modules.idp.pipeline import run_ai_extraction


# ---------------------------------------------------------------------------
# 1. Unit Tests for Utility Functions
# ---------------------------------------------------------------------------

def test_html_table_to_markdown_empty():
    text = "Plain text without tables"
    assert html_table_to_markdown(text) == text


def test_html_table_to_markdown_valid():
    html = """
    <table>
        <tr><th>Item</th><th>Price</th></tr>
        <tr><td>Apple</td><td>1.00</td></tr>
    </table>
    """
    expected = "| Item | Price |\n| --- | --- |\n| Apple | 1.00 |"
    # Basic containment check to be robust to exact spacing
    result = html_table_to_markdown(html)
    assert "Item | Price" in result
    assert "--- | ---" in result
    assert "Apple | 1.00" in result


def test_clean_ocr_text():
    raw_ocr = "Hello <img src='foo.png'> World <table><tr><td>Item</td></tr></table>"
    cleaned = clean_ocr_text(raw_ocr)
    assert "<img" not in cleaned
    assert "Item" in cleaned
    assert "| Item |" in cleaned or "Item" in cleaned


def test_attempt_json_recovery_success():
    truncated = '{"vendor_details": {"company_name": "ACME"'
    recovered = attempt_json_recovery(truncated)
    assert recovered.get("vendor_details", {}).get("company_name") == "ACME"


def test_attempt_json_recovery_failure():
    bad = "Not a json at all"
    recovered = attempt_json_recovery(bad)
    assert recovered.get("requires_human_review") is True
    assert recovered.get("error") == "JSON Truncated"


def test_ensure_structure():
    minimal = {"line_items": []}
    structured = ensure_structure(minimal)
    assert "document_details" in structured
    assert "vendor_details" in structured
    assert "client_details" in structured
    assert "line_items" in structured
    assert "financials" in structured
    assert "requires_human_review" in structured
    assert "validation_errors" in structured


def test_validate_extraction_math_ok():
    data = {
        "vendor_details": {"company_name": "ACME"},
        "financials": {
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "total_amount": 110.0
        }
    }
    validated = validate_extraction(data)
    assert validated["requires_human_review"] is False
    assert not validated["validation_errors"]


def test_validate_extraction_math_mismatch():
    data = {
        "vendor_details": {"company_name": "ACME"},
        "financials": {
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "total_amount": 125.0
        }
    }
    validated = validate_extraction(data)
    assert validated["requires_human_review"] is True
    assert any("Math mismatch" in err for err in validated["validation_errors"])


def test_validate_extraction_missing_vendor():
    data = {
        "vendor_details": {},
        "financials": {
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "total_amount": 110.0
        }
    }
    validated = validate_extraction(data)
    assert validated["requires_human_review"] is True
    assert any("Missing Vendor Name" in err for err in validated["validation_errors"])


# ---------------------------------------------------------------------------
# 2. Mock Prediction / LLM Runs
# ---------------------------------------------------------------------------

def test_run_remote_paddle_qwen_extraction_mock():
    # Test local mock mode triggering when URL contains localhost/127.0.0.1
    with patch("app.modules.idp.paddle_qwen.settings") as mock_settings:
        mock_settings.paddle_ocr_url = "http://localhost:8000/v1"
        mock_settings.env = "development"
        mock_settings.allow_mock_fallback = True
        
        result_json, raw, ocr, pages = run_remote_paddle_qwen_extraction(
            file_bytes=b"fake_bytes",
            filename="invoice.png",
            json_schema={"some": "schema"},
            custom_prompt="hints"
        )
        assert result_json["vendor_details"]["company_name"] == "ACME Corp Ltd"
        assert result_json["financials"]["total_amount"] == 1000.0
        assert "INV-2026-PADDLE" in raw
        assert ocr == "mock ocr text"
        assert pages == 1


def test_run_remote_paddle_qwen_extraction_api():
    # Test remote REST API call with httpx mock
    with patch("app.modules.idp.paddle_qwen.settings") as mock_settings, \
         patch("httpx.post") as mock_post:
        
        mock_settings.paddle_ocr_url = "https://remote-gpu-server/v1"
        mock_settings.env = "production"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "document_details": {"document_type": "invoice"},
                "vendor_details": {"company_name": "ACME Remote"},
                "financials": {"subtotal": 100.0, "tax_amount": 10.0, "total_amount": 110.0}
            },
            "raw_content": '{"vendor_details": {"company_name": "ACME Remote"}}',
            "ocr_text": "extracted remote text",
            "page_count": 2
        }
        mock_post.return_value = mock_response
        
        result_json, raw, ocr, pages = run_remote_paddle_qwen_extraction(
            file_bytes=b"fake_bytes",
            filename="invoice.png",
            json_schema={"some": "schema"},
            custom_prompt="hints"
        )
        
        assert result_json["vendor_details"]["company_name"] == "ACME Remote"
        assert "ACME Remote" in raw
        assert ocr == "extracted remote text"
        assert pages == 2
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Pipeline Dispatch Gating
# ---------------------------------------------------------------------------

def test_run_ai_extraction_dispatches_paddle_qwen():
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.id = uuid.uuid4()
    mock_doc.template_id = None
    mock_doc.filename = "test_doc.png"
    
    mock_doc_type = MagicMock(spec=DocumentType)
    mock_doc_type.extraction_method = "paddle_qwen"
    mock_doc_type.json_schema = {"_instruction": "Force math validation!", "_rules": "No negatives"}
    mock_db.get.return_value = mock_doc_type

    # Mock settings
    with patch("app.core.config.settings") as mock_settings, \
         patch("app.modules.idp.paddle_qwen.run_remote_paddle_qwen_extraction") as mock_extract:
        
        mock_settings.qwen_llm_model = "Qwen-VL"
        
        # Setup mock extract response
        mock_extract.return_value = (
            {
                "document_details": {"document_type": "invoice"},
                "vendor_details": {"company_name": "ACME"},
                "financials": {"subtotal": 100.0, "tax_amount": 0.0, "total_amount": 100.0}
            },
            "raw response json",
            "remote ocr text",
            1
        )
        
        outcome = run_ai_extraction(
            mock_db,
            mock_doc,
            b"fake_bytes",
            "image/png",
            "extracted text",
            False
        )
        
        assert outcome.extraction is not None
        assert outcome.extraction.document_type == "invoice"
        assert outcome.extraction.confidence == 0.9
        assert outcome.mode == "text_via_paddle"
        mock_extract.assert_called_once_with(
            file_bytes=b"fake_bytes",
            filename="test_doc.png",
            json_schema={},
            custom_prompt="Force math validation!\n\nNo negatives"
        )


# ---------------------------------------------------------------------------
# 4. Config Router API Gating
# ---------------------------------------------------------------------------

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


def test_get_idp_config_router(mock_auth_ctx):
    db, token = mock_auth_ctx
    doc_type_id = uuid.uuid4()
    
    # Mock document type
    mock_doc_type = DocumentType(
        id=doc_type_id,
        tenant_id=uuid.UUID(token.tenant_id),
        name="Invoice",
        extraction_method="default",
        json_schema={"some": "schema"}
    )
    
    # Mock db.get to return mock_doc_type
    db.get.return_value = mock_doc_type
    # Mock template query to return None (no promoted template)
    db.query.return_value.filter.return_value.first.return_value = None

    def override_get_tenant_db():
        yield db, token

    app.dependency_overrides[get_tenant_db] = override_get_tenant_db
    client = TestClient(app)
    
    response = client.get(f"/api/idp/config/{doc_type_id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["documentTypeId"] == str(doc_type_id)
    assert data["extractionMethod"] == "default"
    assert data["isCustomized"] is False
    
    app.dependency_overrides.clear()


def test_list_idp_config_router(mock_auth_ctx):
    db, token = mock_auth_ctx
    doc_type_id = uuid.uuid4()
    
    mock_doc_type = DocumentType(
        id=doc_type_id,
        tenant_id=uuid.UUID(token.tenant_id),
        name="Invoice",
        extraction_method="default",
        json_schema={"some": "schema"}
    )
    
    db.query.return_value.filter.return_value.all.return_value = [mock_doc_type]
    db.query.return_value.filter.return_value.first.return_value = None

    def override_get_tenant_db():
        yield db, token

    app.dependency_overrides[get_tenant_db] = override_get_tenant_db
    client = TestClient(app)
    
    response = client.get("/api/idp/config")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "configs" in data
    assert len(data["configs"]) == 1
    assert data["configs"][0]["documentTypeId"] == str(doc_type_id)
    assert data["configs"][0]["extractionMethod"] == "default"
    assert data["configs"][0]["isCustomized"] is False
    
    app.dependency_overrides.clear()


def test_post_idp_config_router_creates_template(mock_auth_ctx):
    db, token = mock_auth_ctx
    doc_type_id = uuid.uuid4()
    
    mock_doc_type = DocumentType(
        id=doc_type_id,
        name="Invoice",
        extraction_method="default"
    )
    db.get.return_value = mock_doc_type
    
    # Mock template lookup returns None (create new one)
    db.query.return_value.filter.return_value.first.return_value = None
 
    def override_get_tenant_db():
        yield db, token
 
    app.dependency_overrides[get_tenant_db] = override_get_tenant_db
    client = TestClient(app)
    
    payload = {
        "extractionMethod": "paddle_qwen",
        "jsonSchema": {"type": "object"},
        "instruction": "Test instruction",
        "rules": "Test rules"
    }
    
    response = client.post(f"/api/idp/config/{doc_type_id}", json=payload)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    assert data["extractionMethod"] == "paddle_qwen"
    assert data["instruction"] == "Test instruction"
    assert data["rules"] == "Test rules"
    assert data["isCustomized"] is True
    
    # Assert DB additions
    db.add.assert_called_once()
    db.commit.assert_called_once()
    
    app.dependency_overrides.clear()


def test_post_idp_config_router_invalid_method(mock_auth_ctx):
    db, token = mock_auth_ctx
    doc_type_id = uuid.uuid4()
    
    mock_doc_type = DocumentType(
        id=doc_type_id,
        name="Invoice",
        extraction_method="default"
    )
    db.get.return_value = mock_doc_type

    def override_get_tenant_db():
        yield db, token

    app.dependency_overrides[get_tenant_db] = override_get_tenant_db
    client = TestClient(app)
    
    payload = {
        "extractionMethod": "invalid_method",
    }
    
    response = client.post(f"/api/idp/config/{doc_type_id}", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Extraction method must be" in response.json()["detail"]
    
    app.dependency_overrides.clear()
