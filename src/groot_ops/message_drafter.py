from __future__ import annotations

from .models import ClientConfig, Lead


PROHIBITED_PHRASES = ["guaranteed", "best rate", "available for sure"]


def draft_followup(lead: Lead, config: ClientConfig) -> str:
    name = lead.name.split()[0] if lead.name else "there"
    location = lead.desired_location or "your target area"
    property_type = lead.property_type or "homes"
    if lead.lead_temperature == "needs_info":
        body = (
            f"Hi {name}, this is {config.agent_name} with {config.business_name}. "
            f"Thanks for reaching out about {property_type} in {location}. "
            "What budget range, timeline, and best phone number should I use to help narrow options?"
        )
    elif lead.lead_temperature == "hot":
        body = (
            f"Hi {name}, this is {config.agent_name} with {config.business_name}. "
            f"I saw your interest in {property_type} around {location}. "
            "Are you available today or tomorrow to talk through options and set up a showing?"
        )
    elif lead.lead_temperature == "warm":
        body = (
            f"Hi {name}, this is {config.agent_name} with {config.business_name}. "
            f"I can help you compare {property_type} in {location}. "
            "Would a quick 15-minute call this week work to confirm priorities and next steps?"
        )
    else:
        body = (
            f"Hi {name}, this is {config.agent_name} with {config.business_name}. "
            f"Thanks for checking out {property_type} in {location}. "
            "Would you like me to send a few helpful market updates as you explore?"
        )
    return f"{body} {config.required_disclaimer}".strip()


def validate_draft(message: str, config: ClientConfig) -> list[str]:
    errors: list[str] = []
    if not message or not message.strip():
        errors.append("draft_empty")
    if len(message) > config.max_draft_chars:
        errors.append("draft_too_long")
    if config.required_disclaimer and config.required_disclaimer not in message:
        errors.append("missing_required_disclaimer")
    lowered = message.lower()
    for phrase in PROHIBITED_PHRASES:
        if phrase in lowered:
            errors.append(f"prohibited_phrase:{phrase}")
    return errors
