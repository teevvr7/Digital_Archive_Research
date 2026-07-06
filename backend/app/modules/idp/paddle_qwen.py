import os
import re
import json
import logging
from typing import Tuple, Dict, Any
from bs4 import BeautifulSoup
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def html_table_to_markdown(html_content: str) -> str:
    """Converts HTML <table> to Markdown table using BeautifulSoup."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        tables = soup.find_all('table')
        
        markdown_tables = []
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            
            md_rows = []
            for i, row in enumerate(rows):
                cols = row.find_all(['td', 'th'])
                cols_text = [c.get_text(strip=True) for c in cols]
                md_rows.append("| " + " | ".join(cols_text) + " |")
                
                # Add separator after header
                if i == 0:
                    md_rows.append("| " + " | ".join(["---"] * len(cols)) + " |")
            
            markdown_tables.append("\n".join(md_rows))
        
        return "\n\n".join(markdown_tables) if markdown_tables else html_content
    except Exception as e:
        logger.warning("Failed to convert HTML table to markdown: %s", e)
        return html_content


def clean_ocr_text(text: str) -> str:
    """Cleans OCR text: removes img tags and converts tables."""
    # 1. Remove <img ...> tags
    text = re.sub(r'<img[^>]*>', '', text)
    
    # 2. Extract <table> contents and convert to markdown
    def table_replacer(match):
        return html_table_to_markdown(match.group(0))
    
    cleaned_text = re.sub(r'<table>.*?</table>', table_replacer, text, flags=re.DOTALL)
    
    # 3. Clean up excessive whitespace
    cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text)
    
    return cleaned_text.strip()


def extract_and_combine_content(data: Any) -> str:
    """Helper to extract content from PaddleOCRVL results."""
    combined_content = []
    if isinstance(data, list) and data:
        if 'parsing_res_list' in data[0] and isinstance(data[0]['parsing_res_list'], list):
            for item in data[0]['parsing_res_list']:
                content = None
                if hasattr(item, 'content'):
                    content = item.content
                elif isinstance(item, dict):
                    content = item.get('content')
                
                if content is not None:
                    combined_content.append(content)
    return '\n'.join(combined_content)


def attempt_json_recovery(truncated_json_str: str) -> Dict[str, Any]:
    """Attempts to close a truncated JSON string for partial extraction."""
    temp_str = truncated_json_str.strip()
    for _ in range(5):
        try:
            return json.loads(temp_str)
        except json.JSONDecodeError:
            if temp_str.endswith('"'): 
                temp_str += ' }'
            elif temp_str.endswith(','): 
                temp_str = temp_str[:-1] + ' }'
            else: 
                temp_str += ' }'
    return {"requires_human_review": True, "error": "JSON Truncated"}


def ensure_structure(data: Dict[str, Any], json_schema: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Ensures the extracted JSON has all required top-level keys based on the schema to avoid frontend crashes."""
    if not json_schema:
        defaults = {
            "document_details": {},
            "vendor_details": {},
            "client_details": {},
            "line_items": [],
            "financials": {},
        }
    else:
        defaults = {}
        for key, val in json_schema.items():
            if isinstance(val, list):
                defaults[key] = []
            elif isinstance(val, dict):
                defaults[key] = {}
            elif isinstance(val, (float, int)):
                defaults[key] = 0.0
            elif isinstance(val, bool):
                defaults[key] = False
            else:
                defaults[key] = None
                
    defaults["requires_human_review"] = False
    defaults["validation_errors"] = []
    
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def validate_extraction(data: Dict[str, Any], json_schema: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Validates the extracted JSON data for errors and mathematical consistency."""
    data = ensure_structure(data, json_schema)
    issues = []
    
    # Dynamic Math Check: search for subtotal, tax_amount, and total/grand_total recursively
    def find_val(d, keys):
        if not isinstance(d, dict):
            return None
        for k, v in d.items():
            if k in keys:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
            if isinstance(v, dict):
                res = find_val(v, keys)
                if res is not None:
                    return res
        return None

    subtotal = find_val(data, ("subtotal", "sub_total"))
    tax = find_val(data, ("tax_amount", "tax", "vat_amount", "gst_amount"))
    total = find_val(data, ("total_amount", "grand_total", "total", "amount_due"))

    if subtotal is not None and tax is not None and total is not None:
        expected_total = subtotal + tax
        if abs(expected_total - total) > 0.02:
            issues.append(f"Math mismatch: Subtotal({subtotal}) + Tax({tax}) != Total({total})")

    # Dynamic vendor name check: search for vendor_name or company_name
    vendor_name = None
    for parent in ("vendor_details", "invoice_metadata", "metadata", "header"):
        if isinstance(data.get(parent), dict):
            vendor_name = data[parent].get("company_name") or data[parent].get("vendor_name")
            if vendor_name:
                break
    if not vendor_name:
        vendor_name = data.get("vendor_name") or data.get("company_name")

    # Only validate missing vendor if the schema actually defines a vendor key
    schema_has_vendor = False
    if json_schema:
        def has_key(s, keys):
            if not isinstance(s, dict):
                return False
            for k, v in s.items():
                if k in keys:
                    return True
                if isinstance(v, dict) and has_key(v, keys):
                    return True
            return False
        schema_has_vendor = has_key(json_schema, ("company_name", "vendor_name"))
    else:
        schema_has_vendor = True

    if schema_has_vendor and not vendor_name:
        issues.append("Missing Vendor Name")

    if issues:
        data["requires_human_review"] = True
        data["validation_errors"] = issues
    else:
        data["requires_human_review"] = data.get("requires_human_review", False)
        data["validation_errors"] = data.get("validation_errors", [])
        
    return data


def run_remote_paddle_qwen_extraction(
    file_bytes: bytes,
    filename: str,
    json_schema: Dict[str, Any],
    custom_prompt: str | None,
    use_image: bool = False,
    use_ocr: bool = True
) -> Tuple[Dict[str, Any], str, str, int]:
    """Uploads the document file and custom settings to the remote unified Paddle-Qwen service on Lightning AI.
    
    Falls back gracefully to mock results in local development/localhost settings.
    """
    # Force Mock fallback if allowed by settings and URL contains localhost/127.0.0.1 in development environment
    is_localhost = "localhost" in settings.paddle_ocr_url or "127.0.0.1" in settings.paddle_ocr_url
    if settings.allow_mock_fallback and is_localhost and settings.env == "development":
        logger.info("[MOCK] Simulating remote Unified Paddle-Qwen execution.")
        mock_data = {
            "document_details": {
                "document_type": "invoice",
                "invoice_number": "INV-2026-PADDLE",
                "invoice_date": "2026-06-22",
                "due_date": "2026-07-22"
            },
            "vendor_details": {
                "company_name": "ACME Corp Ltd",
                "person_name": "Sales ACME",
                "address": "123 Industrial Way, Tech City",
                "contact_info": "billing@acme.com"
            },
            "client_details": {
                "company_name": "DataWiz Corp",
                "person_name": "",
                "address": "",
                "contact_info": ""
            },
            "line_items": [
                {
                    "description": "Server Hosting (AWS)",
                    "quantity": 1.0,
                    "unit_price": 800.0,
                    "line_total": 800.0
                },
                {
                    "description": "Database Support Services",
                    "quantity": 1.0,
                    "unit_price": 150.0,
                    "line_total": 150.0
                }
            ],
            "financials": {
                "subtotal": 950.0,
                "tax_amount": 50.0,
                "total_amount": 1000.0
            },
            "requires_human_review": False,
            "validation_errors": []
        }
        return mock_data, json.dumps(mock_data), "mock ocr text", 1

    url = f"{settings.paddle_ocr_url}/v1/extract"
    logger.info("Executing unified remote Paddle-Qwen pipeline extraction at %s", url)

    try:
        files = {"file": (filename, file_bytes, "application/octet-stream")}
        payload_data = {
            "json_schema": json.dumps(json_schema),
            "custom_prompt": custom_prompt or "",
            "use_image": str(use_image).lower(),
            "use_ocr": str(use_ocr).lower()
        }
        
        # 120s timeout to allow remote cold-start VLM/LLM servers to response
        response = httpx.post(url, files=files, data=payload_data, timeout=120.0)
        response.raise_for_status()
        res_json = response.json()
        
        if res_json.get("status") == "success":
            return (
                res_json["data"], 
                res_json["raw_content"], 
                res_json.get("ocr_text", ""), 
                res_json.get("page_count", 1)
            )
        else:
            detail = res_json.get("detail", "Unknown remote pipeline error")
            raise RuntimeError(f"Unified remote pipeline failed: {detail}")
            
    except Exception as e:
        logger.exception("HTTP call to unified remote Paddle-Qwen server failed: %s", e)
        raise RuntimeError(f"Unified remote Paddle-Qwen pipeline request failed: {e}")


# --- Deprecated Legacy APIs kept for backward compatibility / tests ---

def run_paddle_ocr_prediction(image_path: str) -> str:
    """[DEPRECATED] Use run_remote_paddle_qwen_extraction directly."""
    logger.warning("run_paddle_ocr_prediction is deprecated. Running in mock mode.")
    return "ACME Corp Ltd\nINV-2026-PADDLE\nSubtotal: 950.00\nTax: 50.00\nTotal: 1000.00"


def extract_from_ocr_text(cleaned_text: str, custom_prompt: str | None = None) -> Tuple[Dict[str, Any], str]:
    """[DEPRECATED] Use run_remote_paddle_qwen_extraction directly."""
    logger.warning("extract_from_ocr_text is deprecated. Running in mock mode.")
    mock_res = {
        "document_details": {"document_type": "invoice", "invoice_number": "INV-2026-PADDLE"},
        "vendor_details": {"company_name": "ACME Corp Ltd"},
        "financials": {"subtotal": 950.0, "tax_amount": 50.0, "total_amount": 1000.0}
    }
    return mock_res, json.dumps(mock_res)
