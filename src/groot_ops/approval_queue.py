from __future__ import annotations

from .models import Lead


NEEDS_APPROVAL = "needs_approval"
APPROVED = "approved"
REJECTED = "rejected"


def _clear_approval_metadata(lead: Lead) -> None:
    """Remove fields that imply a human approved or sent the current draft."""
    for field_name in ("approved_by", "approved_at", "sent_at", "approval_notes", "sent_by"):
        if hasattr(lead, field_name):
            setattr(lead, field_name, "")
        if field_name in lead.extra:
            lead.extra[field_name] = ""


def apply_approval_gate(lead: Lead, draft_errors: list[str], previous_draft_message: str | None = None) -> None:
    """Set approval state for an internally generated draft.

    Valid drafts enter the queue. Invalid drafts are blocked and must not be send-eligible.
    Existing explicit approvals are preserved only if they still apply to the exact
    generated draft currently on the lead. If automation regenerates different
    copy, the lead must return to the approval queue before any send action.
    """
    if draft_errors:
        lead.approval_status = "blocked"
        _clear_approval_metadata(lead)
        return
    if lead.approval_status == APPROVED and lead.draft_message and previous_draft_message == lead.draft_message:
        return
    if lead.approval_status == APPROVED:
        _clear_approval_metadata(lead)
    lead.approval_status = NEEDS_APPROVAL


def is_send_eligible(lead: Lead) -> bool:
    return lead.approval_status == APPROVED and bool(lead.draft_message and lead.draft_message.strip())
