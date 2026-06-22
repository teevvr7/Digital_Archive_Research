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

def test_run_paddle_ocr_prediction_mock():
    # Force _paddle_pipeline to be mock or simulate it
    with patch("app.modules.idp.paddle_qwen._paddle_pipeline", "mock"):
        res = run_paddle_ocr_prediction("fake_image.png")
        assert "ACME Corp Ltd" in res
        assert "INV-2026-PADDLE" in res


def test_extract_from_ocr_text_mock():
    # Force mock mode by having "localhost:8001" in settings.qwen_llm_url
    with patch("app.modules.idp.paddle_qwen.settings") as mock_settings:
        mock_settings.qwen_llm_url = "http://localhost:8001/v1"
        mock_settings.vlm_api_key = ""
        mock_settings.qwen_llm_model = "Qwen-VL"
        
        result_json, raw = extract_from_ocr_text("some text")
        assert result_json["vendor_details"]["company_name"] == "ACME Corp Ltd"
        assert result_json["financials"]["total_amount"] == 1000.0
        assert "INV-2026-PADDLE" in raw


# ---------------------------------------------------------------------------
# 3. Pipeline Dispatch Gating
# ---------------------------------------------------------------------------

def test_run_ai_extraction_dispatches_paddle_qwen():
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.id = uuid.uuid4()
    mock_doc.template_id = None
    
    mock_doc_type = MagicMock(spec=DocumentType)
    mock_doc_type.extraction_method = "paddle_qwen"
    mock_doc_type.json_schema = {"_prompt": "Force math validation!"}
    mock_db.get.return_value = mock_doc_type

    # Mock settings
    with patch("app.core.config.settings") as mock_settings, \
         patch("app.modules.idp.parsing.open_pdf") as mock_open_pdf, \
         patch("app.modules.idp.paddle_qwen.run_paddle_ocr_prediction", return_value="Some text") as mock_predict, \
         patch("app.modules.idp.paddle_qwen.extract_from_ocr_text") as mock_extract:
        
        mock_settings.vlm_max_pages = 2
        mock_settings.vlm_render_dpi = 120
        mock_settings.qwen_llm_model = "Qwen-VL"
        
        # Setup mock extract response
        mock_extract.return_value = (
            {
                "document_details": {"document_type": "invoice"},
                "vendor_details": {"company_name": "ACME"},
                "financials": {"subtotal": 100.0, "tax_amount": 0.0, "total_amount": 100.0}
            },
            "raw response json"
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
        mock_predict.assert_called_once()
        mock_extract.assert_called_once_with("Some text", "Force math validation!")


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
        "promptHints": {"subtotal": "Look for subtotal"}
    }
    
    response = client.post(f"/api/idp/config/{doc_type_id}", json=payload)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    assert data["extractionMethod"] == "paddle_qwen"
    assert data["promptHints"] == {"subtotal": "Look for subtotal"}
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
