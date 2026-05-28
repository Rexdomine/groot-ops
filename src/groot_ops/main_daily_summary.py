from __future__ import annotations

import argparse

from .approval_queue import apply_approval_gate
from .config_loader import load_client_config
from .csv_repository import CsvLeadRepository
from .daily_summary import build_daily_summary, format_daily_summary
from .lead_scorer import score_lead
from .message_drafter import draft_followup, validate_draft
from .models import Lead


def _enrich_for_summary(leads: list[Lead], config) -> list[Lead]:
    """Fill derived fields in memory so the summary works before write-mode processing."""
    for lead in leads:
        if not lead.lead_temperature or not lead.lead_score or not lead.recommended_action:
            result = score_lead(lead, config)
            lead.lead_score = lead.lead_score or str(result.score)
            lead.lead_temperature = lead.lead_temperature or result.temperature
            lead.recommended_action = lead.recommended_action or result.recommended_action
            if result.errors and not lead.errors:
                lead.errors = ";".join(result.errors)
        if not lead.draft_message:
            lead.draft_message = draft_followup(lead, config)
            draft_errors = validate_draft(lead.draft_message, config)
            if draft_errors and not lead.errors:
                lead.errors = ";".join(draft_errors)
            if not lead.approval_status:
                apply_approval_gate(lead, draft_errors)
    return leads


def run_daily_summary(client_config_path: str) -> str:
    config = load_client_config(client_config_path)
    leads = _enrich_for_summary(CsvLeadRepository(config.leads_csv).list_leads(), config)
    summary = build_daily_summary(leads, config)
    output = format_daily_summary(summary)
    print(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Print Groot Ops daily lead pipeline summary.")
    parser.add_argument("--client", required=True, help="Path to client YAML config")
    args = parser.parse_args()
    run_daily_summary(args.client)


if __name__ == "__main__":
    main()
