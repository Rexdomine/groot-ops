from __future__ import annotations

import argparse

from .approval_queue import apply_approval_gate
from .config_loader import load_client_config
from .daily_summary import build_daily_summary, format_daily_summary
from .lead_scorer import score_lead
from .message_drafter import draft_followup, validate_draft
from .models import Lead
from .owner_notifications import send_owner_summary_email
from .repository_factory import create_lead_repository


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


def run_daily_summary(
    client_config_path: str,
    *,
    email_owner: bool = False,
    email_dry_run: bool = False,
    to_email: str | None = None,
) -> str:
    config = load_client_config(client_config_path)
    leads = _enrich_for_summary(create_lead_repository(config).list_leads(), config)
    summary = build_daily_summary(leads, config)
    output = format_daily_summary(summary)
    print(output)
    if email_owner:
        result = send_owner_summary_email(
            config,
            summary,
            summary_text=output,
            to_email=to_email,
            dry_run=email_dry_run,
        )
        status = "dry run prepared" if result.get("dry_run") else "sent"
        email_status = f"Owner email {status} for {result['to']}"
        print(email_status)
        output = f"{output}\n{email_status}"
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Print Groot Ops daily lead pipeline summary.")
    parser.add_argument("--client", required=True, help="Path to client YAML config")
    parser.add_argument("--email-owner", action="store_true", help="Send the summary to the configured owner email")
    parser.add_argument("--email-dry-run", action="store_true", help="Prepare the owner email without sending it")
    parser.add_argument("--to", help="Override the configured owner email destination")
    args = parser.parse_args()
    run_daily_summary(args.client, email_owner=args.email_owner, email_dry_run=args.email_dry_run, to_email=args.to)


if __name__ == "__main__":
    main()
