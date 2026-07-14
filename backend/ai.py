"""AI extraction using Claude Sonnet 4.5 via the Anthropic API directly."""
import os
import json
import re
import logging
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL_NAME = "claude-sonnet-4-5-20250929"
_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None

# Patterns that look like a credential the upstream LLM SDK might echo back to
# us in an exception message. We blunt-redact them before showing the error
# string to non-admin users in the UI.
#  - sk-/Bearer style API tokens
#  - JWT-ish triple-segment base64 tokens
#  - The literal ANTHROPIC_API_KEY value (whatever it is)
_SECRET_PATTERNS = [
    re.compile(r"\b(sk|pk|rk|api|key|token|bearer)[-_a-z0-9]*[ =:]\S+", re.IGNORECASE),
    re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}\b"),  # JWT
    re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"),  # generic long opaque token
]


def _sanitise_ai_error(e: Exception) -> str:
    """Return a short, safe error reason for the UI.

    We KEEP the exception type (useful for users to report) and a redacted
    snippet of the message. We DROP anything that could leak a key/token.
    """
    detail = str(e).strip()
    if ANTHROPIC_KEY:
        detail = detail.replace(ANTHROPIC_KEY, "<redacted>")
    for pat in _SECRET_PATTERNS:
        detail = pat.sub("<redacted>", detail)
    if len(detail) > 180:
        detail = detail[:180] + "…"
    detail = detail.strip()
    return f"{type(e).__name__}: {detail}" if detail else type(e).__name__

SYSTEM_PROMPT = """You are an AI assistant for a Field Intelligence Platform used by dental/medical Territory Managers (TMs) to log conversations with doctors about Invisalign and aligner products.

Your job: analyze a TM's free-text visit note and extract structured tags. You must NEVER invent facts. If you are uncertain, mark as "Unknown" or omit. Preserve the user's intent.

CRITICAL SAFETY RULES:
- Never extract or repeat patient names, patient medical details, internal pricing, revenue, or pipeline values.
- If you detect possible patient names (e.g., "the patient John") or medical details, add a clear warning to "privacy_warnings".
- Never paraphrase the original note; the platform stores the raw note untouched.

CONTROLLED VOCABULARIES (use exact strings; pick the closest matches; you may include up to 5):

TOPICS:
Clinical: "Case selection confidence", "ClinCheck understanding", "Clinical confidence", "Complex case discussion", "Extraction cases", "Retained teeth", "Predictability concerns"
Product: "Invisalign pricing", "iTero value", "3D face scan", "SmileView", "SmileVideo", "iTero demo", "Digital workflow", "Align Digital Platform"
Business: "Business confidence", "Patient affordability perception", "Lead generation concerns", "Marketing", "Time constraints", "Case acceptance", "Growth programs awareness", "Discount/program awareness"
Programs: "Peer-to-peer", "TPS service", "Certification interest", "Event invitation", "Staff training", "Doctor education", "Clinical support"
Platform: "Docloc benefits", "Practice App", "Case Assessment", "Prospect", "Invisalign options", "Virtual care"

BARRIERS:
Pricing: "Patient affordability concern", "Doctor margin concern", "Perceived unfair pricing", "Does not understand growth programs", "Discount confusion", "Thinks Invisalign is too expensive"
Clinical: "Low clinical confidence", "Unsure aligners work", "Complex case uncertainty", "Extraction case concern", "Retained teeth concern", "Predictability concern", "ClinCheck confidence issue"
Business: "Low business confidence", "Does not know how to present Invisalign", "Afraid patients will reject price", "Low case acceptance confidence", "Low patient demand belief"
Operational: "Lack of time", "Staff not trained", "Workflow complexity", "Too many steps", "Does not use digital tools consistently"
Competition: "Prefers braces", "Uses other aligner system", "Believes braces are more profitable", "Negative past aligner experience"

SENTIMENT (one of): "Very Negative", "Negative", "Neutral", "Positive", "Very Positive"
OPPORTUNITY_STATE (one of): "Blocked", "Stuck", "Advancing", "Unknown"
- Blocked: resistant, negative, not open
- Stuck: interested but has barriers (price/confidence/time/workflow)
- Advancing: taking action, requesting training, certification, follow-up, accepting more
- Unknown: not enough info

PROMISES: actionable follow-ups the TM committed to (e.g., "send certification info", "book iTero demo", "arrange P2P", "send TPS info", "invite to event"). Each promise needs:
- task_title (short imperative, e.g. "Send certification info")
- task_description (1 sentence context)
- suggested_due_date (ISO date YYYY-MM-DD ONLY if the note itself specifies or implies a date, e.g. "next Monday" or "in two weeks" — you don't know today's date, so never guess one; otherwise return null and the caller will apply a sensible default)
- priority: "Low" | "Medium" | "High"

MARKET_SIGNALS: short string observations relevant to market intelligence (e.g., "Doctor cited competitor X in city Y", "Affordability concern raised by Active segment").

DOCTOR_MATCH — if a list of "Doctors available" is provided below the note, and the note
clearly names one of them (allowing for minor spelling/transcription variation, e.g. voice-to-text
mishearing), return that doctor's EXACT name string from the provided list in "doctor_match".
If no list is provided, no doctor is named, or you are not confident, return null. NEVER invent
a name that isn't in the provided list.

DOCTOR_NAME_HEARD — separately from doctor_match, always report the doctor's name as it was
actually said/written in the note (your best-effort transcription of the name itself), even if
it did NOT match anyone in the provided list — this lets the caller offer to add a new doctor.
Null only if the note genuinely doesn't name any doctor at all.

TRACK_TYPES — detect which product tracks the visit covered. Return a list with any of: "ITERO" (scanner/iTero/digital scan), "INVISALIGN" (aligners/clear aligners/Invisalign-specific). Empty list if neither — defaults to BOTH downstream.

ITERO_ACTIONS — scanner-only execution signals from the note. Booleans default false; only flip true if explicitly mentioned. Dates ISO YYYY-MM-DD. Fields:
- demo_discussed, demo_booked, demo_booked_date, demo_completed, demo_completed_date
- scanner_interest_level: one of "Low" | "Medium" | "High" | "None"
- scanner_concerns: list of short scanner-specific concern phrases (e.g., "price", "training", "ROI")

INVISALIGN_ACTIONS — aligner-only execution signals. Booleans default false:
- growth_program_explained, certification_interest, tps_discussed, p2p_suggested, staff_training_needed
- clinical_confidence: "Low" | "Medium" | "High" | "Unknown"
- business_confidence: "Low" | "Medium" | "High" | "Unknown"
- patient_affordability_perception: "Concerned" | "Neutral" | "Confident" | "Unknown"

COMMERCIAL_ACTIONS — track-agnostic pricing/proposal:
- boost_discussed, trade_in_discussed, trade_in_interest
- proposal_discussed, proposal_sent, proposal_sent_date, proposal_follow_up_done

Strict separation:
- Never put demo_* under invisalign_actions.
- Never put growth/certification/TPS/P2P/confidence under itero_actions.

OUTPUT FORMAT — ALWAYS return ONLY a single JSON object, no prose, no markdown fences:
{
  "summary": "1-2 sentence neutral factual summary, no patient details",
  "topics": ["..."],
  "barriers": ["..."],
  "sentiment": "Neutral",
  "opportunity_state": "Unknown",
  "promises_detected": [
    {"task_title": "", "task_description": "", "suggested_due_date": "YYYY-MM-DD", "priority": "Medium"}
  ],
  "suggested_next_action": "",
  "market_signals": [],
  "privacy_warnings": [],
  "doctor_match": null,
  "doctor_name_heard": null,
  "track_types": [],
  "itero_actions": {
    "demo_discussed": false, "demo_booked": false, "demo_booked_date": null,
    "demo_completed": false, "demo_completed_date": null,
    "scanner_interest_level": "None", "scanner_concerns": []
  },
  "invisalign_actions": {
    "growth_program_explained": false, "certification_interest": false, "tps_discussed": false,
    "p2p_suggested": false, "staff_training_needed": false,
    "clinical_confidence": "Unknown", "business_confidence": "Unknown",
    "patient_affordability_perception": "Unknown"
  },
  "commercial_actions": {
    "boost_discussed": false, "trade_in_discussed": false, "trade_in_interest": false,
    "proposal_discussed": false, "proposal_sent": false, "proposal_sent_date": null,
    "proposal_follow_up_done": false
  }
}
"""


def _safe_json(text: str) -> Optional[dict]:
    if not text:
        return None
    # strip code fences
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    # try direct
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # find first {...} block
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _empty_result(reason: str = "") -> dict:
    """Empty extraction skeleton. `reason` populates `ai_error` (NOT
    `privacy_warnings` — the latter is reserved for real patient/PII concerns
    detected in the note itself).
    """
    return {
        "summary": "",
        "topics": [],
        "barriers": [],
        "sentiment": "Neutral",
        "opportunity_state": "Unknown",
        "promises_detected": [],
        "suggested_next_action": "",
        "market_signals": [],
        "privacy_warnings": [],
        "ai_error": (reason or None),
        "track_types": [],
        "itero_actions": {
            "demo_discussed": False, "demo_booked": False, "demo_booked_date": None,
            "demo_completed": False, "demo_completed_date": None,
            "scanner_interest_level": "None", "scanner_concerns": [],
        },
        "invisalign_actions": {
            "growth_program_explained": False, "certification_interest": False, "tps_discussed": False,
            "p2p_suggested": False, "staff_training_needed": False,
            "clinical_confidence": "Unknown", "business_confidence": "Unknown",
            "patient_affordability_perception": "Unknown",
        },
        "commercial_actions": {
            "boost_discussed": False, "trade_in_discussed": False, "trade_in_interest": False,
            "proposal_discussed": False, "proposal_sent": False, "proposal_sent_date": None,
            "proposal_follow_up_done": False,
        },
        "doctor_id": None,
        "doctor_hint": None,
        "doctor_name_heard": None,
    }


async def analyze_note(note: str, session_id: str, doctors: Optional[list] = None) -> dict:
    """Run AI extraction. Always returns the schema, never raises.

    `doctors`: optional list of {"id": str, "doctor_name": str} the caller may name in
    the note — used to auto-match which doctor the visit was with (e.g. from a voice
    note dictated before picking a doctor manually).
    """
    note = (note or "").strip()
    if not note:
        return _empty_result()
    if not _client:
        logger.warning("ANTHROPIC_API_KEY missing; returning empty extraction")
        return _empty_result("AI not configured")
    try:
        names_block = ""
        if doctors:
            names_block = "\n\nDoctors available (match one if the note clearly names them):\n- " + "\n- ".join(
                d["doctor_name"] for d in doctors[:300] if d.get("doctor_name")
            )
        response = await _client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Visit note:\n\"\"\"\n{note}\n\"\"\"{names_block}\n\nReturn the JSON object now."}],
        )
        raw = response.content[0].text if response.content else ""
        data = _safe_json(raw)
        if not data:
            logger.warning("AI returned non-JSON: %s", str(raw)[:300])
            return _empty_result("AI parse error")

        # Normalise + clamp
        result = _empty_result()
        result["ai_error"] = None
        result["summary"] = (data.get("summary") or "")[:600]
        result["topics"] = [str(t) for t in (data.get("topics") or [])][:8]
        result["barriers"] = [str(b) for b in (data.get("barriers") or [])][:8]
        s = data.get("sentiment") or "Neutral"
        if s not in ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]:
            s = "Neutral"
        result["sentiment"] = s
        op = data.get("opportunity_state") or "Unknown"
        if op not in ["Blocked", "Stuck", "Advancing", "Unknown"]:
            op = "Unknown"
        result["opportunity_state"] = op
        promises = data.get("promises_detected") or []
        norm_promises = []
        for p in promises[:6]:
            if not isinstance(p, dict):
                continue
            norm_promises.append(
                {
                    "task_title": str(p.get("task_title") or "").strip()[:160],
                    "task_description": str(p.get("task_description") or "").strip()[:400],
                    "suggested_due_date": p.get("suggested_due_date"),
                    "priority": p.get("priority") if p.get("priority") in ("Low", "Medium", "High") else "Medium",
                }
            )
        result["promises_detected"] = [p for p in norm_promises if p["task_title"]]
        result["suggested_next_action"] = (data.get("suggested_next_action") or "")[:400]
        result["market_signals"] = [str(m) for m in (data.get("market_signals") or [])][:6]
        result["privacy_warnings"] = [str(w) for w in (data.get("privacy_warnings") or [])][:6]

        # Track types
        tracks_in = data.get("track_types") or []
        result["track_types"] = [t for t in tracks_in if t in ("ITERO", "INVISALIGN")][:2]

        # iTero actions
        ia_in = data.get("itero_actions") or {}
        ia = result["itero_actions"]
        for k in ("demo_discussed", "demo_booked", "demo_completed"):
            ia[k] = bool(ia_in.get(k))
        for k in ("demo_booked_date", "demo_completed_date"):
            ia[k] = ia_in.get(k) or None
        sil = ia_in.get("scanner_interest_level") or "None"
        ia["scanner_interest_level"] = sil if sil in ("Low", "Medium", "High", "None") else "None"
        ia["scanner_concerns"] = [str(c) for c in (ia_in.get("scanner_concerns") or [])][:6]

        # Invisalign actions
        inv_in = data.get("invisalign_actions") or {}
        inv = result["invisalign_actions"]
        for k in ("growth_program_explained", "certification_interest", "tps_discussed",
                  "p2p_suggested", "staff_training_needed"):
            inv[k] = bool(inv_in.get(k))
        for k, opts in (("clinical_confidence", ("Low", "Medium", "High", "Unknown")),
                        ("business_confidence", ("Low", "Medium", "High", "Unknown")),
                        ("patient_affordability_perception", ("Concerned", "Neutral", "Confident", "Unknown"))):
            v = inv_in.get(k) or inv[k]
            inv[k] = v if v in opts else inv[k]

        # Commercial (track-agnostic)
        ca_in = data.get("commercial_actions") or {}
        ca = result["commercial_actions"]
        for k in ca.keys():
            if k.endswith("_date"):
                ca[k] = ca_in.get(k) or None
            else:
                ca[k] = bool(ca_in.get(k))

        # Doctor match — only accept an exact (case-insensitive) match against the
        # provided list. Never let the model invent or fuzzy-guess a doctor we can't verify.
        hint = (data.get("doctor_match") or "").strip()
        if hint and doctors:
            match = next((d for d in doctors if (d.get("doctor_name") or "").strip().lower() == hint.lower()), None)
            if match:
                result["doctor_id"] = match["id"]
                result["doctor_hint"] = match["doctor_name"]
        # Raw name as heard, independent of whether it matched the roster — lets the
        # caller offer to create a new doctor when it's a genuine non-match.
        result["doctor_name_heard"] = (data.get("doctor_name_heard") or "").strip()[:120] or None
        return result
    except Exception as e:
        logger.exception("AI analyze_note failed: %s", e)
        # Surface a sanitised error reason for the user UI. We strip anything
        # that resembles a key or token so we don't leak secrets to non-admin
        # users via the visit detail screen.
        reason = _sanitise_ai_error(e)
        return _empty_result(reason)


async def extract_task_from_text(text: str, doctor_names: Optional[list] = None) -> dict:
    """Extract a single structured task/promise from a quick voice or typed note.

    Returns: {
      "task_title": str,           # short imperative; empty if nothing actionable
      "task_description": str,     # one-sentence context
      "is_promise": bool,          # true if the TM committed to do something
      "suggested_due_date": str|None,  # YYYY-MM-DD, default = 3 business days out
      "priority": "Low"|"Medium"|"High",
      "doctor_hint": str|None,     # best-match doctor name from the provided list
    }

    No AI invented facts — if no actionable task is detected, task_title is "".
    """
    text = (text or "").strip()
    if not text:
        return {
            "task_title": "", "task_description": "",
            "is_promise": False, "suggested_due_date": None,
            "priority": "Medium", "doctor_hint": None,
        }
    if not _client:
        return {
            "task_title": text[:120],
            "task_description": text[:400],
            "is_promise": False,
            "suggested_due_date": None,
            "priority": "Medium",
            "doctor_hint": None,
        }
    try:
        names_block = ""
        if doctor_names:
            names_block = "\n\nDoctor names available:\n- " + "\n- ".join(doctor_names[:200])
        response = await _client.messages.create(
            model=MODEL_NAME,
            max_tokens=1024,
            system=(
                "You convert a TM's short note into ONE actionable task or promise.\n"
                "Output STRICT JSON with these keys ONLY: task_title (string, short imperative <=160 chars), "
                "task_description (string, one sentence, <=400 chars), is_promise (bool — true if the TM said they'd do it), "
                "suggested_due_date (YYYY-MM-DD or null; if no date specified, suggest 3 business days from today), "
                "priority ('Low'|'Medium'|'High'), doctor_hint (string|null — only echo a name from the provided list if you find a clear match in the note).\n"
                "Never invent details. If the note isn't actionable, return task_title as empty string."
            ),
            messages=[{"role": "user", "content": f"Note:\n{text}{names_block}\n\nReturn JSON only."}],
        )
        raw = response.content[0].text if response.content else ""

        m = re.search(r"\{[\s\S]+\}", raw or "")
        data = json.loads(m.group(0)) if m else {}
        title = (data.get("task_title") or "").strip()[:160]
        desc = (data.get("task_description") or "").strip()[:400]
        is_promise = bool(data.get("is_promise"))
        due = data.get("suggested_due_date")
        if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(due)):
            due = None
        prio = data.get("priority")
        if prio not in ("Low", "Medium", "High"):
            prio = "Medium"
        hint = (data.get("doctor_hint") or None)
        if hint and doctor_names and hint not in doctor_names:
            # Keep only an exact match — never let the model invent a doctor
            hint = None
        return {
            "task_title": title,
            "task_description": desc,
            "is_promise": is_promise,
            "suggested_due_date": due,
            "priority": prio,
            "doctor_hint": hint,
        }
    except Exception as e:
        logger.exception("AI extract_task_from_text failed: %s", e)
        return {
            "task_title": text[:120],
            "task_description": text[:400],
            "is_promise": False,
            "suggested_due_date": None,
            "priority": "Medium",
            "doctor_hint": None,
            "ai_error": _sanitise_ai_error(e),
        }
