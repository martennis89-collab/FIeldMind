"""emails.py — Resend API wrappers for transactional emails.

Calls Resend's REST API directly via httpx (same pattern already used for
Telegram/ElevenLabs elsewhere in this codebase) instead of pulling in the
`resend` SDK for a single endpoint.

Every sender function returns bool (sent or not) and never raises — a
failed email must not break the request that triggered it (e.g. a password
reset should still record the token even if Resend is briefly down; the
user can just request another link).
"""
import html
import os
import logging
import httpx

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "FieldTracker <onboarding@resend.dev>")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")

_BRAND_PRIMARY = "#274035"
_BRAND_SECONDARY = "#c26d53"


def _wrap(title: str, body_html: str) -> str:
    return f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 24px; color: #1f2a24;">
  <div style="font-size: 13px; letter-spacing: 0.2em; text-transform: uppercase; color: {_BRAND_SECONDARY}; font-weight: 600; margin-bottom: 24px;">FieldTracker</div>
  <h1 style="font-size: 20px; font-weight: 600; color: {_BRAND_PRIMARY}; margin: 0 0 16px;">{title}</h1>
  {body_html}
  <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e0d8; font-size: 12px; color: #8a8478;">
    FieldTracker — your second brain in the field.
  </div>
</div>
""".strip()


async def _send_email(to: str, subject: str, html: str) -> bool:
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured; skipping email to %s (subject=%r)", to, subject)
        return False
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={"from": SENDER_EMAIL, "to": [to], "subject": subject, "html": html},
            )
            r.raise_for_status()
        return True
    except Exception:
        logger.exception("Resend send failed (to=%s, subject=%r)", to, subject)
        return False


def _greeting(full_name: str) -> str:
    name = html.escape(full_name.strip()) if full_name and full_name.strip() else ""
    return f"Hi {name}," if name else "Hi,"


async def send_password_reset_email(to: str, full_name: str, reset_token: str) -> bool:
    reset_link = f"{FRONTEND_URL}/reset-password?token={reset_token}"
    subject = "Reset your FieldTracker password"
    body = f"""
    <p style="font-size: 15px; line-height: 1.6; margin: 0 0 16px;">{_greeting(full_name)}</p>
    <p style="font-size: 15px; line-height: 1.6; margin: 0 0 24px;">
      We received a request to reset your FieldTracker password. This link expires in 1 hour.
    </p>
    <a href="{reset_link}" style="display: inline-block; background: {_BRAND_PRIMARY}; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 600;">
      Reset password
    </a>
    <p style="font-size: 13px; line-height: 1.6; color: #6b6558; margin: 24px 0 0;">
      If you didn't request this, you can safely ignore this email — your password won't change.
    </p>
    """
    return await _send_email(to, subject, _wrap(subject, body))


async def send_weekly_report_reminder_email(to: str, full_name: str, week_start: str, week_end: str) -> bool:
    subject = "Your weekly report is overdue"
    reports_link = f"{FRONTEND_URL}/reports"
    body = f"""
    <p style="font-size: 15px; line-height: 1.6; margin: 0 0 16px;">{_greeting(full_name)}</p>
    <p style="font-size: 15px; line-height: 1.6; margin: 0 0 24px;">
      You haven't submitted your weekly report for <strong>{html.escape(week_start)} – {html.escape(week_end)}</strong> yet.
      FieldTracker drafts it from your logged activity — you just review and submit.
    </p>
    <a href="{reports_link}" style="display: inline-block; background: {_BRAND_PRIMARY}; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 600;">
      Submit report
    </a>
    """
    return await _send_email(to, subject, _wrap(subject, body))


async def send_unachieved_meetings_reminder_email(to: str, full_name: str, meetings: list) -> bool:
    n = len(meetings)
    subject = f"{n} meeting{'s' if n != 1 else ''} today still need{'s' if n == 1 else ''} to be completed"
    calendar_link = f"{FRONTEND_URL}/calendar"
    rows = "".join(
        f'<li style="font-size: 14px; line-height: 1.8;">'
        f'<strong>{html.escape(m["time_label"])}</strong> — {html.escape(m["doctor_name"])}'
        f'{" · iTero demo" if m.get("is_demo") else ""}'
        f"</li>"
        for m in meetings
    )
    body = f"""
    <p style="font-size: 15px; line-height: 1.6; margin: 0 0 16px;">{_greeting(full_name)}</p>
    <p style="font-size: 15px; line-height: 1.6; margin: 0 0 16px;">
      These meetings from today are still marked Scheduled — log what happened to keep your record straight:
    </p>
    <ul style="margin: 0 0 24px; padding-left: 20px; color: #1f2a24;">{rows}</ul>
    <a href="{calendar_link}" style="display: inline-block; background: {_BRAND_PRIMARY}; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 600;">
      Open calendar
    </a>
    """
    return await _send_email(to, subject, _wrap(subject, body))
