"""telegram.py — Telegram bot integration for the daily voice-note check-in.

Single-user personal automation: the linked Telegram chat sends a voice note
(or text) describing the day, and this webhook transcribes it (reusing the
same ElevenLabs pipeline as the in-app voice note), runs it through the same
AI extraction + doctor-matching used by /visits/analyze, and saves it via the
same logic as POST /visits — so a Telegram-logged visit is indistinguishable
from one logged through the app.

Notes that don't name any doctor at all (e.g. "call the bank about the
marketing materials") are logged as a standalone personal/admin task instead
of a doctor visit — see _log_standalone_task.

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
from datetime import datetime, timezone, timedelta
import logging
import os

import httpx
from fastapi import Request, HTTPException

from ai import extract_task_from_text
from server import api, db
from routers.visits import _transcribe_audio_bytes, create_visit, analyze_visit_note
from routers.tasks import create_task
from models import AnalyzeNoteRequest, VisitCreate, AIExtraction, TaskCreate

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


async def _log_standalone_task(note_text: str, user: dict, visit_analysis: dict) -> None:
    """A Telegram note that doesn't name a doctor at all — e.g. "call Viktoria at
    TBI Bank about the marketing materials" — isn't a visit. Log it as a personal/
    admin task instead of erroring out asking for a doctor.
    """
    promises = [p for p in (visit_analysis.get("promises_detected") or []) if p.get("task_title")]
    if not promises:
        # The visit-analysis prompt is dental-context-heavy and may miss a
        # generic task — retry with the task-focused extractor.
        task_result = await extract_task_from_text(note_text)
        if task_result.get("task_title"):
            promises = [task_result]

    if not promises:
        await _telegram_send(
            "Got it, but I couldn't find an actionable task in that note. "
            "Try being more specific, e.g. \"Call Viktoria at TBI Bank about the marketing materials.\""
        )
        return

    today = datetime.now(timezone.utc).date()
    created_titles = []
    for p in promises[:3]:
        title = (p.get("task_title") or "").strip()
        if not title:
            continue
        due = p.get("suggested_due_date") or (today + timedelta(days=14)).isoformat()
        prio = p.get("priority") if p.get("priority") in ("Low", "Medium", "High") else "Medium"
        task_body = TaskCreate(
            doctor_id=None,
            task_title=title,
            task_description=p.get("task_description") or note_text[:400],
            due_date=due,
            priority=prio,
            created_from_ai=True,
            ai_confirmed=True,
            category="other",
        )
        try:
            await create_task(task_body, user=user)
            created_titles.append(title)
        except HTTPException as e:
            logger.warning("Telegram standalone task creation failed: %s", e.detail)

    if created_titles:
        summary = "; ".join(created_titles)
        await _telegram_send(f"Logged task: {summary}. ✓")
    else:
        await _telegram_send("Something went wrong saving that task — nothing was saved. Try again shortly.")


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

    if not doctor_id and not result.get("doctor_name_heard"):
        # No doctor named at all — this isn't a visit, it's a personal/admin task.
        await _log_standalone_task(note_text, user, result)
        return {"ok": True}

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
