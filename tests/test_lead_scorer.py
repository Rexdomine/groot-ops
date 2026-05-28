from groot_ops.config_loader import load_client_config
from groot_ops.lead_scorer import score_lead
from groot_ops.models import Lead


def test_hot_lead_scoring():
    config = load_client_config("configs/sample_realtor.yaml")
    lead = Lead(
        lead_id="T1",
        name="Hot Buyer",
        phone="555",
        email="hot@example.invalid",
        budget="700000",
        desired_location="Downtown",
        timeline="7 days",
        property_type="Condo",
        message="Pre-approved and wants a tour.",
    )

    result = score_lead(lead, config)

    assert result.temperature == "hot"
    assert result.score >= 75
    assert "showing" in result.recommended_action.lower()


def test_needs_info_when_core_details_missing():
    config = load_client_config("configs/sample_realtor.yaml")
    lead = Lead(lead_id="T2", email="x@example.invalid", timeline="unknown", message="Hello")

    result = score_lead(lead, config)

    assert result.temperature == "needs_info"
    assert "missing_budget" in result.errors
    assert "missing_timeline" in result.errors
