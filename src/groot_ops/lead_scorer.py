from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ClientConfig, Lead


@dataclass(frozen=True)
class ScoreResult:
    score: int
    temperature: str
    recommended_action: str
    errors: list[str]


def _timeline_days(text: str) -> int | None:
    value = (text or "").lower()
    if not value or value in {"unknown", "n/a", "na"}:
        return None
    if "week" in value:
        match = re.search(r"(\d+)", value)
        return (int(match.group(1)) if match else 1) * 7
    if "month" in value:
        match = re.search(r"(\d+)", value)
        return (int(match.group(1)) if match else 1) * 30
    match = re.search(r"(\d+)", value)
    if match:
        return int(match.group(1))
    if "now" in value or "asap" in value or "immediate" in value:
        return 0
    return None


def score_lead(lead: Lead, config: ClientConfig) -> ScoreResult:
    score = 0
    errors: list[str] = []

    if lead.phone or lead.email:
        score += 15
    else:
        errors.append("missing_contact")
    if not lead.phone:
        errors.append("missing_phone")
    if lead.budget:
        score += 20
    else:
        errors.append("missing_budget")
    if lead.desired_location:
        score += 15
    else:
        errors.append("missing_location")
    if any(word in (lead.message or "").lower() for word in ["pre-approved", "preapproved", "tour", "showing", "offer"]):
        score += 20

    days = _timeline_days(lead.timeline)
    if days is None:
        errors.append("missing_timeline")
    elif days <= config.hot_timeline_days:
        score += 30
    elif days <= config.warm_timeline_days:
        score += 20
    else:
        score += 5

    if errors and ("missing_contact" in errors or len(errors) >= 3):
        temperature = "needs_info"
        action = "Collect missing lead details before follow-up."
    elif score >= 75:
        temperature = "hot"
        action = "Call or text now and offer specific showing times."
    elif score >= 45:
        temperature = "warm"
        action = "Send personalized follow-up and schedule a consultation."
    else:
        temperature = "cold"
        action = "Add to nurture and check in with a low-pressure question."

    return ScoreResult(score=min(score, 100), temperature=temperature, recommended_action=action, errors=errors)
