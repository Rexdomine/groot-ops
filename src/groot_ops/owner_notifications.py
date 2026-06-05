from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any

from .daily_summary import DailySummary, format_daily_summary
from .models import ClientConfig, Lead, utc_now_iso

MATON_GMAIL_SEND_URL = "https://api.maton.ai/google-mail/gmail/v1/users/me/messages/send"
RESERVED_TEST_EMAIL_DOMAINS = {
    "example.com",
    "example.invalid",
    "example-real-estate-international.com",
}


def _is_reserved_test_email(email: str) -> bool:
    _, separator, domain = email.strip().lower().rpartition("@")
    return bool(separator and domain in RESERVED_TEST_EMAIL_DOMAINS)


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


def _html_button(label: str, href: str, *, primary: bool = False) -> str:
    background = "#012d1d" if primary else "#ffffff"
    color = "#ffffff" if primary else "#012d1d"
    border = "#012d1d" if primary else "#c1c8c2"
    return (
        f'<a href="{escape(href, quote=True)}" style="display:inline-block;background:{background};color:{color};'
        f'border:1px solid {border};border-radius:999px;padding:11px 16px;text-decoration:none;'
        f'font-weight:800;font-size:14px;line-height:1;">{escape(label)}</a>'
    )


def _dashboard_url(config: ClientConfig) -> str:
    base_url = os.environ.get("GROOT_OPS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    path = f"/clients/{urllib.parse.quote(config.client_id)}/dashboard"
    url = f"{base_url}{path}" if base_url else path
    dashboard_token = os.environ.get("GROOT_OPS_DASHBOARD_TOKEN", "").strip()
    if dashboard_token:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}token={urllib.parse.quote(dashboard_token)}"
    return url


def _metric_card(label: str, value: int, caption: str, *, accent: str = "#c1ecd4") -> str:
    return f"""
      <td style="padding:6px;width:33.33%;vertical-align:top;">
        <div style="background:#ffffff;border:1px solid #e6eff8;border-top:4px solid {accent};border-radius:18px;padding:18px;min-height:118px;">
          <div style="font-size:32px;line-height:1;color:#012d1d;font-weight:900;letter-spacing:-.04em;">{value}</div>
          <div style="color:#012d1d;font-weight:900;margin:6px 0 4px;">{escape(label)}</div>
          <div style="color:#414844;font-size:13px;line-height:1.4;">{escape(caption)}</div>
        </div>
      </td>
    """


def _lead_action_buttons(lead: Lead) -> str:
    buttons: list[str] = []
    if lead.phone:
        buttons.append(_html_button("Call now", f"tel:{lead.phone}"))
    if lead.email:
        buttons.append(_html_button("Email lead", f"mailto:{lead.email}"))
    if not buttons:
        buttons.append('<span style="color:#717973;font-size:13px;font-weight:700;">Open dashboard to review contact details</span>')
    return '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">' + "".join(buttons) + "</div>"


def _html_lead_cards(items: list[Lead], empty_message: str, limit: int = 4) -> str:
    if not items:
        return f'<p style="margin:8px 0 0;color:#717973;font-weight:700;">{escape(empty_message)}</p>'
    rows = "".join(
        f"""
        <div style="background:#ffffff;border:1px solid #e6eff8;border-radius:16px;padding:14px;margin-top:10px;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div>
              <div style="color:#012d1d;font-weight:900;">{escape(lead.name or 'Unnamed lead')}</div>
              <div style="color:#717973;font-size:13px;font-weight:700;">Lead {escape(lead.lead_id)}</div>
            </div>
            <div style="background:#ffdf9c;color:#5b4300;border-radius:999px;padding:5px 9px;font-size:12px;font-weight:900;white-space:nowrap;">{escape(lead.lead_temperature or lead.status or 'review')}</div>
          </div>
          {f'<p style="margin:10px 0 0;color:#414844;font-size:13px;line-height:1.45;">{escape(lead.recommended_action)}</p>' if lead.recommended_action else ''}
          {f'<p style="margin:10px 0 0;color:#ba1a1a;font-size:13px;line-height:1.45;"><strong>Issue:</strong> {escape(lead.errors)}</p>' if lead.errors else ''}
          {_lead_action_buttons(lead)}
        </div>
        """
        for lead in items[:limit]
    )
    if len(items) > limit:
        rows += f'<p style="margin:10px 0 0;color:#717973;font-weight:700;">+{len(items) - limit} more in the dashboard</p>'
    return rows


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
    dashboard_url = _dashboard_url(config)
    text_body = "\n".join(
        [
            f"Groot Ops Daily Summary — {config.business_name}",
            f"Generated: {generated_at}",
            f"Dashboard: {dashboard_url}",
            "",
            summary_text,
            "",
            "Recommended owner actions:",
            f"1. Call or message hot leads: {_lead_list(summary.hot_leads)}",
            f"2. Follow up due leads: {_lead_list(summary.follow_ups_due)}",
            f"3. Review pending drafts / approve drafts waiting for review: {_lead_list(summary.pending_approvals)}",
            f"4. Fix data issues / cleanup errors: {_lead_list(summary.errors)}",
            "",
            "Safety: No customer messages were sent automatically. Drafts remain for human review/approval.",
        ]
    )
    html_body = f"""
    <div style="margin:0;padding:0;background:#f6faff;color:#141d23;font-family:Inter,Arial,sans-serif;">
      <div style="max-width:760px;margin:0 auto;padding:28px 16px;">
        <div style="background:#012d1d;border-radius:28px 28px 0 0;padding:30px;color:#ffffff;">
          <div style="display:inline-block;background:#c1ecd4;color:#012d1d;border-radius:999px;padding:7px 12px;font-weight:900;font-size:12px;letter-spacing:.08em;text-transform:uppercase;">Groot Ops command center</div>
          <h1 style="margin:16px 0 8px;font-size:30px;line-height:1.05;letter-spacing:-.04em;color:#ffffff;">Daily lead follow-up summary</h1>
          <p style="margin:0;color:#c1ecd4;font-size:15px;line-height:1.5;">{escape(config.business_name)} • Generated {escape(generated_at)}</p>
          <div style="margin-top:22px;">{_html_button('Open dashboard', dashboard_url)}</div>
        </div>
        <div style="background:#ffffff;border:1px solid #dbe4ed;border-top:0;border-radius:0 0 28px 28px;padding:24px;box-shadow:0 20px 40px rgba(0,0,0,.08);">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 -6px 18px;">
            <tr>
              {_metric_card('Hot leads', len(summary.hot_leads), 'Call these first', accent='#fdcb52')}
              {_metric_card('Follow-ups due', len(summary.follow_ups_due), 'Needs owner action')}
              {_metric_card('Needs approval', len(summary.pending_approvals), 'Drafts waiting')}
            </tr>
          </table>

          <div style="background:#ecf5fe;border:1px solid #dbe4ed;border-radius:22px;padding:18px;margin-bottom:18px;">
            <h2 style="font-size:18px;line-height:1.2;margin:0 0 6px;color:#012d1d;">Today's priority queue</h2>
            <p style="margin:0;color:#414844;font-size:14px;line-height:1.45;">Start with hot leads, then clear follow-ups and draft approvals. This email is designed for quick action; the dashboard has the full queue.</p>
          </div>

          <div style="margin-bottom:18px;">
            <h3 style="margin:0;color:#012d1d;font-size:16px;">🔥 Call or message hot leads</h3>
            {_html_lead_cards(summary.hot_leads, 'No hot leads right now — keep monitoring new activity.')}
          </div>

          <div style="margin-bottom:18px;">
            <h3 style="margin:0;color:#012d1d;font-size:16px;">⏰ Follow-ups due</h3>
            {_html_lead_cards(summary.follow_ups_due, 'No overdue follow-ups right now.')}
          </div>

          <div style="margin-bottom:18px;">
            <h3 style="margin:0;color:#012d1d;font-size:16px;">✅ Approve drafts</h3>
            {_html_lead_cards(summary.pending_approvals, 'No draft approvals are waiting.')}
          </div>

          <div style="background:#fff8e7;border:1px solid #ffdf9c;border-radius:20px;padding:16px;margin-bottom:18px;">
            <h3 style="margin:0 0 8px;color:#5b4300;font-size:16px;">Fix data issues</h3>
            {_html_lead_cards(summary.errors, 'No cleanup errors found.')}
          </div>

          <div style="background:#ecfff3;border:1px solid #c1ecd4;border-radius:20px;padding:16px;margin-bottom:18px;">
            <strong style="display:block;color:#012d1d;margin-bottom:5px;">Safety note</strong>
            <p style="margin:0;color:#414844;font-size:14px;line-height:1.45;">Messages stay in human-review mode. No customer messages were sent automatically; drafts remain for owner approval before live outreach.</p>
          </div>

          <div style="text-align:center;margin:24px 0 6px;">
            {_html_button('Open dashboard', dashboard_url, primary=True)}
            <p style="margin:12px 0 0;color:#717973;font-size:12px;line-height:1.4;">Groot Ops • Lead follow-up automation for real estate teams</p>
          </div>
        </div>
      </div>
    </div>
    """
    return OwnerSummaryEmail(to_email=recipient, subject=subject, text_body=text_body, html_body=html_body)


def build_owner_setup_confirmation_email(
    config: ClientConfig,
    *,
    recipient: str,
    dashboard_url: str | None = None,
) -> OwnerSummaryEmail:
    dashboard_url = dashboard_url or _dashboard_url(config)
    subject = f"🌱 Groot Ops setup is ready — {config.business_name}"
    frequency_label = (config.process_leads_frequency or "manual").replace("_", " ").title().replace("2H", "2h")
    text_body = "\n".join(
        [
            f"Groot Ops setup is ready — {config.business_name}",
            "",
            f"Hi {config.agent_name or 'there'},",
            "Your Groot Ops lead follow-up workspace has been created.",
            "",
            "Your private dashboard:",
            dashboard_url,
            "",
            "Setup summary:",
            f"- Business: {config.business_name}",
            f"- Primary agent: {config.agent_name}",
            f"- Owner updates: {config.owner_notification_channel.title()} to {config.owner_notification_destination or config.agent_email}",
            f"- Daily summary time: {config.daily_summary_time}",
            f"- Lead processing: {frequency_label}",
            "",
            "What to do next:",
            "1. Open the private dashboard from this email.",
            "2. Run the daily summary preview.",
            "3. Review lead follow-up drafts before any live outreach.",
            "4. Mark the pilot active only after the previews look right.",
            "",
            "Safety: No customer messages are sent automatically during the pilot. Groot prepares summaries and drafts for human review.",
            "",
            "Keep this email so you can return to your private dashboard anytime.",
        ]
    )
    html_body = f"""
    <div style="margin:0;padding:0;background:#f6faff;color:#141d23;font-family:Inter,Arial,sans-serif;">
      <div style="max-width:720px;margin:0 auto;padding:28px 16px;">
        <div style="background:#012d1d;border-radius:30px 30px 0 0;padding:32px;color:#ffffff;">
          <div style="display:inline-block;background:#c1ecd4;color:#012d1d;border-radius:999px;padding:7px 12px;font-weight:900;font-size:12px;letter-spacing:.08em;text-transform:uppercase;">Groot Ops command center</div>
          <h1 style="margin:16px 0 10px;font-size:31px;line-height:1.05;letter-spacing:-.04em;color:#ffffff;">Your setup is ready</h1>
          <p style="margin:0;color:#c1ecd4;font-size:15px;line-height:1.5;">{escape(config.business_name)} is ready for safe lead follow-up previews.</p>
          <div style="margin-top:24px;">{_html_button('Open private dashboard', dashboard_url)}</div>
        </div>
        <div style="background:#ffffff;border:1px solid #dbe4ed;border-top:0;border-radius:0 0 30px 30px;padding:24px;box-shadow:0 20px 40px rgba(0,0,0,.08);">
          <p style="margin:0 0 18px;color:#414844;font-size:15px;line-height:1.55;">Hi {escape(config.agent_name or 'there')}, Groot Ops saved your lead follow-up workspace. Use the private dashboard button above whenever you want to check setup health, preview owner summaries, or review lead drafts.</p>

          <div style="background:#ecf5fe;border:1px solid #dbe4ed;border-radius:22px;padding:18px;margin-bottom:18px;">
            <h2 style="font-size:18px;line-height:1.2;margin:0 0 12px;color:#012d1d;">Setup overview</h2>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;color:#414844;font-size:14px;line-height:1.45;">
              <tr><td style="padding:7px 0;font-weight:900;color:#012d1d;width:36%;">Business</td><td style="padding:7px 0;">{escape(config.business_name)}</td></tr>
              <tr><td style="padding:7px 0;font-weight:900;color:#012d1d;">Primary agent</td><td style="padding:7px 0;">{escape(config.agent_name)}</td></tr>
              <tr><td style="padding:7px 0;font-weight:900;color:#012d1d;">Owner updates</td><td style="padding:7px 0;">{escape(config.owner_notification_channel.title())} • {escape(config.owner_notification_destination or config.agent_email)}</td></tr>
              <tr><td style="padding:7px 0;font-weight:900;color:#012d1d;">Daily summary</td><td style="padding:7px 0;">{escape(config.daily_summary_time)}</td></tr>
              <tr><td style="padding:7px 0;font-weight:900;color:#012d1d;">Lead processing</td><td style="padding:7px 0;">{escape(frequency_label)}</td></tr>
            </table>
          </div>

          <div style="margin-bottom:18px;">
            <h2 style="font-size:18px;line-height:1.2;margin:0 0 10px;color:#012d1d;">What to do next</h2>
            <ol style="margin:0;padding-left:20px;color:#414844;font-size:14px;line-height:1.7;">
              <li>Open your private dashboard from this email.</li>
              <li>Run the daily summary preview to confirm the owner update is useful.</li>
              <li>Preview lead follow-up drafts and approve the tone before live outreach.</li>
              <li>Mark the pilot active only after the previews look right.</li>
            </ol>
          </div>

          <div style="background:#ecfff3;border:1px solid #c1ecd4;border-radius:20px;padding:16px;margin-bottom:18px;">
            <strong style="display:block;color:#012d1d;margin-bottom:5px;">Safety note</strong>
            <p style="margin:0;color:#414844;font-size:14px;line-height:1.45;">No customer messages are sent automatically during the pilot. Groot Ops prepares summaries and drafts so the owner stays in control.</p>
          </div>

          <div style="background:#fff8e7;border:1px solid #ffdf9c;border-radius:20px;padding:16px;margin-bottom:18px;">
            <strong style="display:block;color:#5b4300;margin-bottom:5px;">Keep this email</strong>
            <p style="margin:0;color:#5b4300;font-size:14px;line-height:1.45;">This is your easiest way back to the private dashboard. You do not need to memorize or manually paste a token.</p>
          </div>

          <div style="text-align:center;margin:24px 0 6px;">
            {_html_button('Open private dashboard', dashboard_url, primary=True)}
            <p style="margin:12px 0 0;color:#717973;font-size:12px;line-height:1.4;">Groot Ops • Lead follow-up automation for real estate teams</p>
          </div>
        </div>
      </div>
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


def _resolve_setup_confirmation_recipient(config: ClientConfig, explicit_to: str | None = None) -> str:
    candidates = [explicit_to, config.owner_notification_destination, config.agent_email]
    for candidate in candidates:
        email = (candidate or "").strip()
        if email and "@" in email:
            return email
    raise ValueError("setup confirmation email destination is not configured")


def send_owner_setup_confirmation_email(
    config: ClientConfig,
    *,
    dashboard_url: str | None = None,
    to_email: str | None = None,
    dry_run: bool = False,
    sender: MatonGmailSender | None = None,
) -> dict[str, Any]:
    recipient = _resolve_setup_confirmation_recipient(config, explicit_to=to_email)
    email = build_owner_setup_confirmation_email(config, recipient=recipient, dashboard_url=dashboard_url)
    if dry_run or _is_reserved_test_email(recipient):
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
    if dry_run or _is_reserved_test_email(recipient):
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
