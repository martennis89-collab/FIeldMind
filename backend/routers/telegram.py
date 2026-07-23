"""telegram.py — Telegram bot integration for the daily voice-note check-in.

Single-user personal automation: the linked Telegram chat sends a voice note
(or text) describing the day, and this webhook transcribes it (reusing the
same ElevenLabs pipeline as the in-app voice note) and hands it to
routers.assistant._execute_smart_action — the same engine the in-app Quick
Capture voice flow uses — which figures out whether this is a visit report,
a meeting/demo booking request, or a standalone personal task, and performs
it. A Telegram-logged action is indistinguishable from one done through the
app itself.

Env vars:
  TELEGRAM_BOT_TOKEN     — from @BotFather
  TELEGRAM_CHAT_ID       — the single authorized chat; messages from any other
                           chat are silently ignored
  TELEGRAM_USER_EMAIL    — which FieldMind user actions get logged as
  TELEGRAM_WEBHOOK_SECRET — random string; must match the secret_token set via
                           Telegram's setWebhook call, checked against the
                           X-Telegram-Bot-Api-Secret-Token header on every
                           incoming request
"""
from __future__ import annotations
import logging
import os

import httpx
from fastapi import Request, HTTPException

from server import api, db
from routers.visits import _transcribe_audio_bytes
from routers.assistant import _execute_smart_action

logger = logging.getLogger(__name__)


async def _telegram_send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception:
        logger.exception("Telegram sendMessage failed")


async def _download_telegram_voice(file_id: str) -> bytes:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        audio = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        audio.raise_for_status()
        return audio.content


def _format_result_message(result: dict) -> str:
    status = result.get("status")
    if status == "needs_clarification":
        return result.get("reason") or "I need a bit more detail to do that — could you resend with more info?"
    if status == "error":
        return f"Couldn't do that: {result.get('detail', 'unknown error')}"

    action = result.get("action")
    if action == "task":
        return f"Logged task: {'; '.join(result.get('task_titles') or [])}. ✓"

    if action in ("meeting", "demo"):
        doctor_name = result.get("doctor_name") or "the doctor"
        new_doctor_line = " (added as a new doctor)" if result.get("doctor_auto_created") else ""
        kind = "iTero demo" if action == "demo" else "Meeting"
        when = (result.get("scheduled_at") or "")[:16].replace("T", " at ")
        return f"{kind} booked with {doctor_name}{new_doctor_line} for {when}. ✓"

    if action == "visit":
        doctor_name = result.get("doctor_name") or "the doctor"
        new_doctor_line = " (added as a new doctor)" if result.get("doctor_auto_created") else ""
        n_promises = result.get("n_promises") or 0
        promise_line = f" · {n_promises} follow-up{'s' if n_promises != 1 else ''} tracked" if n_promises else ""
        date_line = f" · dated {result['visit_date']}" if result.get("visit_date") else ""
        return f"Logged: {doctor_name}{new_doctor_line} — {result.get('sentiment', 'Neutral')} sentiment{promise_line}{date_line}. ✓"

    return "Done. ✓"


@api.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    secret_expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    secret_got = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not secret_expected or secret_got != secret_expected:
        raise HTTPException(status_code=403, detail="Forbidden")

    body = await request.json()
    message = body.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    expected_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not expected_chat_id or chat_id != expected_chat_id:
        # Ignore messages from anyone else — 200 so Telegram doesn't retry.
        return {"ok": True}

    user = await db.users.find_one({"email": os.environ.get("TELEGRAM_USER_EMAIL", "")}, {"_id": 0})
    if not user:
        await _telegram_send("FieldMind isn't linked to a user account yet (TELEGRAM_USER_EMAIL misconfigured).")
        return {"ok": True}

    note_text = None
    if message.get("voice"):
        try:
            raw = await _download_telegram_voice(message["voice"]["file_id"])
            note_text = await _transcribe_audio_bytes(raw, "voice.ogg", "audio/ogg")
        except HTTPException as e:
            await _telegram_send(f"Couldn't transcribe that voice note ({e.detail}). Try again or send text instead.")
            return {"ok": True}
    elif message.get("text") and not message["text"].startswith("/"):
        note_text = message["text"]

    if not note_text:
        await _telegram_send(
            "Send a voice note or a text message — a visit report, \"book a meeting with "
            "Dr. X on Friday at 2pm\", \"book an iTero demo with Dr. X\", or a personal "
            "reminder all work, e.g. \"Saw Dr. Ivanov, talked about the iTero demo, he wants pricing info.\""
        )
        return {"ok": True}

    result = await _execute_smart_action(user, note_text)
    await _telegram_send(_format_result_message(result))
    return {"ok": True}
