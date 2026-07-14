"""telegram.py — Telegram bot integration for the daily voice-note check-in.

Single-user personal automation: the linked Telegram chat sends a voice note
(or text) describing the day, and this webhook transcribes it (reusing the
same ElevenLabs pipeline as the in-app voice note), runs it through the same
AI extraction + doctor-matching used by /visits/analyze, and saves it via the
same logic as POST /visits — so a Telegram-logged visit is indistinguishable
from one logged through the app.

Env vars:
  TELEGRAM_BOT_TOKEN     — from @BotFather
  TELEGRAM_CHAT_ID       — the single authorized chat; messages from any other
                           chat are silently ignored
  TELEGRAM_USER_EMAIL    — which FieldMind user visits get logged as
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
from routers.visits import _transcribe_audio_bytes, create_visit, analyze_visit_note
from models import AnalyzeNoteRequest, VisitCreate, AIExtraction

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
            "Send a voice note or a text message describing your visit — "
            "e.g. \"Saw Dr. Ivanov, talked about the iTero demo, he wants pricing info.\""
        )
        return {"ok": True}

    try:
        # Same function the app's own LogVisit screen calls (POST /visits/analyze) —
        # AI extraction, doctor matching, AND auto-create-if-unmatched all happen
        # inside it, so this is the single source of truth for that logic.
        result = await analyze_visit_note(AnalyzeNoteRequest(note=note_text), user=user)
    except HTTPException as e:
        await _telegram_send(f"Couldn't process that note: {e.detail}")
        return {"ok": True}
    except Exception:
        logger.exception("Telegram check-in AI analysis failed")
        await _telegram_send("Something went wrong analyzing that note — nothing was saved. Try again shortly.")
        return {"ok": True}

    doctor_id = result.get("doctor_id")
    newly_created_doctor_name = result.get("doctor_hint") if result.get("doctor_auto_created") else None
    if not doctor_id:
        await _telegram_send(
            "Couldn't find or add a doctor from that note. "
            "Please resend mentioning who you visited."
        )
        return {"ok": True}

    track_types = result.get("track_types") or []
    if "ITERO" in track_types and "INVISALIGN" not in track_types:
        track_type = "ITERO"
    elif "INVISALIGN" in track_types and "ITERO" not in track_types:
        track_type = "INVISALIGN"
    else:
        track_type = "BOTH"

    visit_body = VisitCreate(
        doctor_id=doctor_id,
        visit_type="In-person visit",
        track_type=track_type,
        free_text_note=note_text,
        confirmed_topics=result.get("topics") or [],
        confirmed_barriers=result.get("barriers") or [],
        sentiment=result.get("sentiment") or "Neutral",
        opportunity_state=result.get("opportunity_state") or "Unknown",
        next_step=result.get("suggested_next_action") or None,
        promises=[p for p in (result.get("promises_detected") or []) if p.get("task_title")],
        ai_extraction=AIExtraction(**result),
        itero_actions=result.get("itero_actions") or {},
        invisalign_actions=result.get("invisalign_actions") or {},
        commercial_actions=result.get("commercial_actions") or {},
    )

    try:
        saved = await create_visit(visit_body, user=user)
    except HTTPException as e:
        await _telegram_send(f"Couldn't save that visit: {e.detail}")
        return {"ok": True}

    doctor_name = newly_created_doctor_name or result.get("doctor_hint") or "the doctor"
    n_promises = len(saved.get("created_tasks") or [])
    promise_line = f" · {n_promises} follow-up{'s' if n_promises != 1 else ''} tracked" if n_promises else ""
    new_doctor_line = " (added as a new doctor)" if newly_created_doctor_name else ""
    await _telegram_send(f"Logged: {doctor_name}{new_doctor_line} — {result.get('sentiment', 'Neutral')} sentiment{promise_line}. ✓")
    return {"ok": True}
