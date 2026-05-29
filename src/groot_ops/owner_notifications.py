from __future__ import annotations

import base64
import json
import os
import urllib.request
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any

from .daily_summary import DailySummary, format_daily_summary
from .models import ClientConfig, Lead, utc_now_iso

MATON_GMAIL_SEND_URL = "https://api.maton.ai/google-mail/gmail/v1/users/me/messages/send"


@dataclass(frozen=True)
class OwnerSummaryEmail:
    to_email: str
    subject: str
    text_body: str
    html_body: str


def _lead_list(items: list[Lead], limit: int = 8) -> str:
    if not items:
        return "none"
    labels = [f"{lead.lead_id} ({lead.name or 'Unnamed'})" for lead in items[:limit]]
    if len(items) > limit:
        labels.append(f"+{len(items) - limit} more")
    return ", ".join(labels)


def _html_lead_list(items: list[Lead], limit: int = 8) -> str:
    if not items:
        return "<span style=\"color:#64748b;\">none</span>"
    rows = "".join(
        f"<li><strong>{escape(lead.lead_id)}</strong> — {escape(lead.name or 'Unnamed')}</li>"
        for lead in items[:limit]
    )
    if len(items) > limit:
        rows += f"<li>+{len(items) - limit} more</li>"
    return f"<ul style=\"margin:8px 0 0;padding-left:18px;\">{rows}</ul>"


def resolve_owner_email(config: ClientConfig, explicit_to: str | None = None) -> str:
    candidate = (explicit_to or config.owner_notification_destination or config.agent_email or "").strip()
    if not candidate:
        raise ValueError("owner email destination is not configured")
    if "@" not in candidate:
        raise ValueError("owner email destination does not look like an email address")
    return candidate


def build_owner_summary_email(
    config: ClientConfig,
    summary: DailySummary,
    *,
    recipient: str,
    summary_text: str | None = None,
) -> OwnerSummaryEmail:
    summary_text = summary_text or format_daily_summary(summary)
    subject = f"🌱 Groot Ops Daily Summary — {config.business_name}"
    generated_at = utc_now_iso()
    text_body = "\n".join(
        [
            f"Groot Ops Daily Summary — {config.business_name}",
            f"Generated: {generated_at}",
            "",
            summary_text,
            "",
            "Recommended owner actions:",
            f"1. Call or message hot leads: {_lead_list(summary.hot_leads)}",
            f"2. Follow up due leads: {_lead_list(summary.follow_ups_due)}",
            f"3. Review pending drafts: {_lead_list(summary.pending_approvals)}",
            f"4. Clean up leads with errors: {_lead_list(summary.errors)}",
            "",
            "Safety: No customer messages were sent automatically. Drafts remain for human review/approval.",
        ]
    )
    html_body = f"""
    <div style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.5;max-width:720px;">
      <h1 style="margin:0 0 6px;font-size:24px;">🌱 Groot Ops Daily Summary</h1>
      <p style="margin:0 0 18px;color:#475569;">{escape(config.business_name)} • Generated {escape(generated_at)}</p>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-bottom:18px;">
        <h2 style="font-size:18px;margin:0 0 10px;">Pipeline snapshot</h2>
        <pre style="white-space:pre-wrap;font-family:Arial,sans-serif;margin:0;color:#334155;">{escape(summary_text)}</pre>
      </div>
      <div style="background:#ecfdf5;border:1px solid #bbf7d0;border-radius:14px;padding:16px;margin-bottom:18px;">
        <h2 style="font-size:18px;margin:0 0 10px;">Recommended owner actions</h2>
        <p><strong>Call/message hot leads:</strong> {_html_lead_list(summary.hot_leads)}</p>
        <p><strong>Follow up due leads:</strong> {_html_lead_list(summary.follow_ups_due)}</p>
        <p><strong>Review pending drafts:</strong> {_html_lead_list(summary.pending_approvals)}</p>
        <p><strong>Clean up errors:</strong> {_html_lead_list(summary.errors)}</p>
      </div>
      <p style="font-size:13px;color:#64748b;">Safety: No customer messages were sent automatically. Drafts remain for human review/approval.</p>
    </div>
    """
    return OwnerSummaryEmail(to_email=recipient, subject=subject, text_body=text_body, html_body=html_body)


class MatonGmailSender:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("MATON_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("MATON_API_KEY is required for Maton Gmail sending")

    def send(self, *, to_email: str, subject: str, text_body: str, html_body: str) -> dict[str, Any]:
        message = MIMEMultipart("alternative")
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(text_body, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        request = urllib.request.Request(
            MATON_GMAIL_SEND_URL,
            data=json.dumps({"raw": raw}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else {"status": "sent"}


def send_owner_summary_email(
    config: ClientConfig,
    summary: DailySummary,
    *,
    summary_text: str | None = None,
    to_email: str | None = None,
    dry_run: bool = False,
    sender: MatonGmailSender | None = None,
) -> dict[str, Any]:
    if config.owner_notification_channel.lower() != "email" and not to_email:
        raise ValueError("owner notification channel must be email before sending owner summary email")
    recipient = resolve_owner_email(config, explicit_to=to_email)
    email = build_owner_summary_email(config, summary, recipient=recipient, summary_text=summary_text)
    if dry_run:
        return {
            "dry_run": True,
            "channel": "email",
            "to": recipient,
            "subject": email.subject,
            "text_size": len(email.text_body),
            "html_size": len(email.html_body),
        }
    sender = sender or MatonGmailSender()
    result = sender.send(
        to_email=email.to_email,
        subject=email.subject,
        text_body=email.text_body,
        html_body=email.html_body,
    )
    return {"channel": "email", "to": recipient, "subject": email.subject, "result": result}
