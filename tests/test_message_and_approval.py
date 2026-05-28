from groot_ops.approval_queue import apply_approval_gate, is_send_eligible
from groot_ops.config_loader import load_client_config
from groot_ops.message_drafter import draft_followup, validate_draft
from groot_ops.models import Lead


def test_draft_includes_disclaimer_and_validates():
    config = load_client_config("configs/sample_realtor.yaml")
    lead = Lead(
        lead_id="T3",
        name="Jordan Lee",
        desired_location="Downtown",
        property_type="Condo",
        lead_temperature="hot",
    )

    message = draft_followup(lead, config)

    assert "Jordan" in message
    assert config.required_disclaimer in message
    assert validate_draft(message, config) == []


def test_validation_blocks_prohibited_or_missing_disclaimer():
    config = load_client_config("configs/sample_realtor.yaml")

    errors = validate_draft("Guaranteed best rate for you", config)

    assert "missing_required_disclaimer" in errors
    assert any(error.startswith("prohibited_phrase") for error in errors)


def test_approval_gate_requires_approved_status_and_draft():
    lead = Lead(lead_id="T4", draft_message="hello")
    apply_approval_gate(lead, [])

    assert lead.approval_status == "needs_approval"
    assert not is_send_eligible(lead)

    lead.approval_status = "approved"
    assert is_send_eligible(lead)

    lead.draft_message = ""
    assert not is_send_eligible(lead)


def test_approval_gate_preserves_approval_only_for_exact_current_draft():
    lead = Lead(lead_id="T5", approval_status="approved", draft_message="approved copy")
    lead.extra["approved_by"] = "manager@example.invalid"
    apply_approval_gate(lead, [], previous_draft_message="approved copy")

    assert lead.approval_status == "approved"
    assert lead.extra["approved_by"] == "manager@example.invalid"

    lead.draft_message = "regenerated copy"
    apply_approval_gate(lead, [], previous_draft_message="approved copy")

    assert lead.approval_status == "needs_approval"
    assert lead.extra["approved_by"] == ""
