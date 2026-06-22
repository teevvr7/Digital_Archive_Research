import os
import re
import time
import json
import logging
import tempfile
from typing import Any, Tuple, Dict
from bs4 import BeautifulSoup
from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy singleton for PaddleOCRVL pipeline
_paddle_pipeline = None

def _get_paddle_pipeline():
    global _paddle_pipeline
    if _paddle_pipeline is None:
        try:
            from paddleocr import PaddleOCRVL
            logger.info("Initializing PaddleOCRVL (Backend: %s)", settings.paddle_ocr_url)
            _paddle_pipeline = PaddleOCRVL(
                vl_rec_backend="vllm-server",
                vl_rec_server_url=settings.paddle_ocr_url,
                vl_rec_api_model_name=settings.paddle_ocr_model
            )
            logger.info("PaddleOCRVL pipeline initialized successfully.")
        except ImportError:
            logger.warning("paddleocr library not installed locally. PaddleOCRVL will run in Mock Mode.")
            _paddle_pipeline = "mock"
        except Exception as e:
            logger.exception("Failed to initialize PaddleOCRVL pipeline: %s", e)
            _paddle_pipeline = "mock"
    return _paddle_pipeline


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


def ensure_structure(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures the extracted JSON has all required top-level keys to avoid frontend crashes."""
    defaults = {
        "document_details": {},
        "vendor_details": {},
        "client_details": {},
        "line_items": [],
        "financials": {},
        "requires_human_review": False,
        "validation_errors": []
    }
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def validate_extraction(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validates the extracted JSON data for errors and mathematical consistency."""
    data = ensure_structure(data)
    issues = []
    
    financials = data.get("financials", {})
    subtotal = financials.get("subtotal") or 0.0
    tax = financials.get("tax_amount") or 0.0
    total = financials.get("total_amount") or 0.0
    
    # Math Check
    expected_total = subtotal + tax
    if abs(expected_total - total) > 0.02:
        issues.append(f"Math mismatch: Subtotal({subtotal}) + Tax({tax}) != Total({total})")
    
    # Critical Fields Check
    if not data.get("vendor_details", {}).get("company_name"):
        issues.append("Missing Vendor Name")
    
    if issues:
        data["requires_human_review"] = True
        data["validation_errors"] = issues
    else:
        # Preserve existing flag if recovery failed
        data["requires_human_review"] = data.get("requires_human_review", False)
        
    return data


def run_paddle_ocr_prediction(image_path: str) -> str:
    """Predicts OCR text on an image using PaddleOCRVL or a fallback mock."""
    pipeline = _get_paddle_pipeline()
    if pipeline == "mock":
        # Returning a mock HTML-table based layout for local testing without GPU
        logger.info("[MOCK] Running mock PaddleOCRVL prediction for image %s", image_path)
        return """
        Invoice
        Vendor: ACME Corp Ltd
        Address: 123 Industrial Way, Tech City
        Client: DataWiz Corp
        Date: 2026-06-22
        Invoice Number: INV-2026-PADDLE
        
        <table>
            <tr>
                <th>description</th>
                <th>quantity</th>
                <th>unit_price</th>
                <th>line_total</th>
            </tr>
            <tr>
                <td>Server Hosting (AWS)</td>
                <td>1</td>
                <td>800.00</td>
                <td>800.00</td>
            </tr>
            <tr>
                <td>Database Support Services</td>
                <td>1</td>
                <td>150.00</td>
                <td>150.00</td>
            </tr>
        </table>
        
        Subtotal: 950.00
        Tax Amount: 50.00
        Total Amount: 1000.00
        """
    
    results = pipeline.predict(image_path)
    return extract_and_combine_content(results)


def extract_from_ocr_text(cleaned_text: str, custom_prompt: str | None = None) -> Tuple[Dict[str, Any], str]:
    """Calls Qwen LLM/VLM model to perform structured financial JSON extraction from cleaned OCR text."""
    client = OpenAI(base_url=settings.qwen_llm_url, api_key="EMPTY")
    
    prompt_to_use = (
        "You are a precise data extraction assistant specialized in financial documents.\n"
        "Extract information from the provided text and return it strictly as a JSON object matching the target structure.\n"
        "Be as concise as possible to avoid truncation.\n"
    )
    
    # Target format schema matches old IDP app2.py
    target_schema_format = {
      "document_details": {
        "document_type": "invoice or receipt or contract",
        "invoice_number": "string",
        "invoice_date": "YYYY-MM-DD",
        "due_date": "YYYY-MM-DD"
      },
      "vendor_details": {
        "company_name": "string",
        "person_name": "string",
        "address": "string",
        "contact_info": "string"
      },
      "client_details": {
        "company_name": "string",
        "person_name": "string",
        "address": "string",
        "contact_info": "string"
      },
      "line_items": [
        {
          "description": "string",
          "quantity": "float",
          "unit_price": "float",
          "line_total": "float"
        }
      ],
      "financials": {
        "subtotal": "float",
        "tax_amount": "float",
        "total_amount": "float"
      }
    }
    
    payload_system = f"{prompt_to_use}\n\nTARGET JSON SCHEMA:\n{json.dumps(target_schema_format, indent=2)}"
    if custom_prompt:
        payload_system += f"\n\nAdditional Instructions:\n{custom_prompt}"
        
    # Mock fallback for LLM connection in local test environments
    if "localhost:8001" in settings.qwen_llm_url or not settings.vlm_api_key:
        logger.info("[MOCK] Running mock Qwen LLM extraction.")
        mock_output = json.dumps({
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
          }
        })
        return json.loads(mock_output), mock_output
        
    response = client.chat.completions.create(
        model=settings.qwen_llm_model,
        messages=[
            {"role": "system", "content": payload_system},
            {"role": "user", "content": f"Text to process:\n{cleaned_text}"}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    
    raw_content = (response.choices[0].message.content or "").strip()
    try:
        result_json = json.loads(raw_content)
    except json.JSONDecodeError:
        result_json = attempt_json_recovery(raw_content)
        result_json["requires_human_review"] = True
        if "validation_errors" not in result_json:
            result_json["validation_errors"] = []
        result_json["validation_errors"].append("LLM output was truncated/incomplete")
        
    return result_json, raw_content
