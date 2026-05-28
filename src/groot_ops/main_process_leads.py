from __future__ import annotations

import argparse

from .activity_log import ActivityLog
from .approval_queue import apply_approval_gate
from .config_loader import load_client_config
from .csv_repository import CsvLeadRepository
from .lead_scorer import score_lead
from .message_drafter import draft_followup, validate_draft
from .models import Lead, utc_now_iso


def process_leads(client_config_path: str, dry_run: bool = True) -> list[Lead]:
    config = load_client_config(client_config_path)
    repository = CsvLeadRepository(config.leads_csv)
    activity_log = ActivityLog(config.activity_log_csv)
    leads = repository.list_leads()

    print(f"Groot Ops lead processing for {config.business_name}")
    print(f"Mode: {'DRY RUN (no writes)' if dry_run else 'WRITE'}")

    for lead in leads:
        previous_draft_message = lead.draft_message
        result = score_lead(lead, config)
        lead.lead_score = str(result.score)
        lead.lead_temperature = result.temperature
        lead.recommended_action = result.recommended_action
        lead.errors = ";".join(result.errors)
        lead.draft_message = draft_followup(lead, config)
        draft_errors = validate_draft(lead.draft_message, config)
        if draft_errors:
            existing = [lead.errors] if lead.errors else []
            lead.errors = ";".join(existing + draft_errors)
        apply_approval_gate(lead, draft_errors, previous_draft_message=previous_draft_message)
        lead.updated_at = utc_now_iso()

        print(f"\nLead {lead.lead_id} — {lead.name or 'Unnamed'}")
        print(f"  Score: {lead.lead_score} ({lead.lead_temperature})")
        print(f"  Recommended action: {lead.recommended_action}")
        print(f"  Approval status: {lead.approval_status}")
        if lead.errors:
            print(f"  Errors: {lead.errors}")
        print(f"  Draft: {lead.draft_message}")
        activity_log.record("lead_processed", lead.lead_id, f"{lead.lead_temperature}:{lead.approval_status}", dry_run)

    if dry_run:
        print(f"\nDry run complete: {len(leads)} lead row(s) would be updated in {config.leads_csv}")
    else:
        repository.save_leads(leads)
        print(f"\nUpdated {len(leads)} lead row(s) in {config.leads_csv}")
    return leads


def main() -> None:
    parser = argparse.ArgumentParser(description="Process real estate leads and prepare approval queue drafts.")
    parser.add_argument("--client", required=True, help="Path to client YAML config")
    parser.add_argument("--write", action="store_true", help="Write CSV/log file updates. Omit for safe dry-run mode.")
    parser.add_argument("--dry-run", action="store_true", help="Deprecated no-op; dry-run is the default unless --write is set")
    args = parser.parse_args()
    if args.write and args.dry_run:
        parser.error("--write and --dry-run cannot be used together")
    process_leads(args.client, dry_run=not args.write)


if __name__ == "__main__":
    main()
