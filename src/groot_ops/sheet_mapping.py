from __future__ import annotations

import re
from typing import Any

CANONICAL_FIELDS = [
    "lead_id",
    "name",
    "email",
    "phone",
    "source",
    "budget",
    "desired_location",
    "timeline",
    "property_type",
    "message",
    "status",
    "last_contacted_at",
    "follow_up_due_at",
]

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "lead_id": ("lead id", "lead_id", "id", "crm id", "client id", "customer id", "custom lead id"),
    "name": ("name", "full name", "client name", "customer", "customer name", "buyer name", "lead name", "contact name"),
    "email": ("email", "email address", "e mail", "mail"),
    "phone": ("phone", "phone number", "mobile", "mobile number", "whatsapp", "whatsapp number", "contact number", "tel"),
    "source": ("source", "lead source", "channel", "origin"),
    "budget": ("budget", "price", "price range", "max price", "minimum budget", "maximum budget", "range"),
    "desired_location": ("desired location", "preferred location", "preferred area", "location", "area", "looking in", "neighborhood", "neighbourhood"),
    "timeline": ("timeline", "move date", "move-in timeline", "move in timeline", "move-in date", "when buying", "buying timeline", "timeframe"),
    "property_type": ("property type", "home type", "unit type", "house type", "property"),
    "message": ("message", "notes", "comments", "requirements", "inquiry notes", "client notes", "request", "description"),
    "status": ("status", "lead status", "stage", "pipeline stage"),
    "last_contacted_at": ("last contacted", "last contacted at", "last follow up", "last touch"),
    "follow_up_due_at": ("follow up due", "follow-up due", "next follow up", "next follow-up", "follow up date"),
}


def normalize_header(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def _score_header(field: str, header: str) -> int:
    normalized = normalize_header(header)
    if not normalized:
        return 0
    aliases = FIELD_ALIASES.get(field, ())
    if normalized == field.replace("_", " "):
        return 100
    for alias in aliases:
        alias_norm = normalize_header(alias)
        if normalized == alias_norm:
            return 95
        if alias_norm in normalized or normalized in alias_norm:
            return 78
    field_tokens = set(field.split("_"))
    header_tokens = set(normalized.split())
    if field_tokens and field_tokens <= header_tokens:
        return 70
    return 0


def infer_column_mapping(headers: list[str], saved_mapping: dict[str, str] | None = None) -> dict[str, str]:
    """Map internal lead fields to the user's existing sheet headers.

    The return shape is {canonical_field: original_header}. Explicit saved mappings
    win first; the rest are inferred from common real-estate spreadsheet synonyms.
    """
    cleaned_headers = [str(header).strip() for header in headers if str(header).strip()]
    available = set(cleaned_headers)
    mapping: dict[str, str] = {}

    for field, header in (saved_mapping or {}).items():
        if field in CANONICAL_FIELDS and header in available:
            mapping[field] = header

    used = set(mapping.values())
    for field in CANONICAL_FIELDS:
        if field in mapping:
            continue
        best_header = ""
        best_score = 0
        for header in cleaned_headers:
            if header in used:
                continue
            score = _score_header(field, header)
            if score > best_score:
                best_header = header
                best_score = score
        if best_header and best_score >= 70:
            mapping[field] = best_header
            used.add(best_header)
    return mapping


def slugify_lead_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug[:64]


def map_sheet_row(headers: list[str], row: list[Any], mapping: dict[str, str]) -> dict[str, Any]:
    original = {header: (row[index] if index < len(row) else "") for index, header in enumerate(headers) if header}
    data: dict[str, Any] = {}
    mapped_headers = set(mapping.values())
    for field, header in mapping.items():
        data[field] = original.get(header, "")
    for header, value in original.items():
        if header not in mapped_headers:
            data[header] = value
        data[f"original_{header}"] = value
    if not str(data.get("lead_id") or "").strip():
        data["lead_id"] = slugify_lead_id(str(data.get("name") or data.get("email") or data.get("phone") or ""))
    return data


def row_for_original_headers(lead_data: dict[str, Any], headers: list[str], mapping: dict[str, str]) -> list[Any]:
    reverse_mapping = {header: field for field, header in mapping.items()}
    row = []
    for header in headers:
        canonical_field = reverse_mapping.get(header)
        if canonical_field:
            row.append(lead_data.get(canonical_field, lead_data.get(f"original_{header}", "")))
        else:
            row.append(lead_data.get(header, lead_data.get(f"original_{header}", "")))
    return row
