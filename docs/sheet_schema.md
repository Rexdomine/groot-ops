# Sheet Schema

The lead repository can be either CSV or Google Sheets. Both use the same columns; use one row per lead.

## Required identity fields

- `lead_id`: Stable unique ID for the lead
- `created_at`: ISO timestamp when the lead arrived
- `name`: Lead full name
- `email`: Lead email, if available
- `phone`: Lead phone, if available
- `source`: Lead source such as Website, Zillow, Referral, Open House

## Qualification fields

- `budget`: Budget or price range
- `desired_location`: Neighborhood, city, or search area
- `timeline`: Desired purchase/sale timeline, e.g. `7 days`, `45 days`, `unknown`
- `property_type`: Condo, single family, townhome, etc.
- `message`: Original inquiry notes

## Workflow fields

- `last_contacted_at`: ISO timestamp of most recent contact
- `follow_up_due_at`: ISO timestamp for next follow-up
- `status`: Suggested values: `new`, `contacted`, `nurture`, `closed`, `lost`
- `approval_status`: Blank, `needs_approval`, `approved`, `rejected`, or `blocked`
- `draft_message`: Internal draft for human review
- `recommended_action`: Internal next-step recommendation
- Optional approval metadata such as `approved_by`, `approved_at`, `sent_at`, `approval_notes`, and `sent_by` is cleared when automation regenerates draft copy that no longer matches the approved draft.

## Automation output fields

- `lead_score`: Numeric 0-100 score from deterministic rules
- `lead_temperature`: `hot`, `warm`, `cold`, or `needs_info`
- `errors`: Semicolon-delimited data quality or draft validation issues
- `updated_at`: ISO timestamp when Groot Ops last processed the row
- `last_run_id`: Internal run UUID for the most recent processing run that touched the row

## Notes

Do not store secrets in the sheet. Do not add columns that imply automatic sending unless a future sender is implemented and gated by explicit approval.
