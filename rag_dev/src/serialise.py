"""Serialization utilities for RAG ingestion. Handles generic schema-agnostic conversion of JSON structures."""

def json_to_markdown(data: dict, title: str = "Document") -> str:
    """Convert any JSON dict to readable markdown. Fully schema-agnostic.

    Handles arrays of dicts (line items) as list items, nested dicts as subsections,
    and scalar key-values as list bullet points.
    """
    lines = [f"# {title}", ""]

    for key, value in data.items():
        label = key.replace("_", " ").title()

        if isinstance(value, list) and value and isinstance(value[0], dict):
            # Array of objects -> numbered list (e.g., line_items)
            lines.append(f"## {label}")
            for i, item in enumerate(value, 1):
                parts = [f"**{k.replace('_', ' ').title()}**: {v}" for k, v in item.items() if v]
                lines.append(f"{i}. {' | '.join(parts)}")
            lines.append("")

        elif isinstance(value, dict):
            # Nested object -> sub-section
            lines.append(f"## {label}")
            for k, v in value.items():
                if v:
                    lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
            lines.append("")

        elif isinstance(value, list):
            # Simple list
            lines.append(f"- **{label}**: {', '.join(str(v) for v in value)}")

        else:
            # Scalar value
            if value is not None and value != "":
                lines.append(f"- **{label}**: {value}")

    return "\n".join(lines).strip()

def json_to_text(data: dict) -> str:
    """Fallback plain-text flat key-value serializer for comparison."""
    lines = []
    for k, v in data.items():
        if isinstance(v, list):
            lines.append(f"{k}: {str(v)}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)
