"""AI extraction using Claude Sonnet 4.5 via Emergent Universal Key."""
import os
import json
import re
import logging
from typing import Optional
from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MODEL_PROVIDER = "anthropic"
MODEL_NAME = "claude-sonnet-4-5-20250929"

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
- suggested_due_date (ISO date YYYY-MM-DD; if not specified in the note, suggest 3 business days from today)
- priority: "Low" | "Medium" | "High"

MARKET_SIGNALS: short string observations relevant to market intelligence (e.g., "Doctor cited competitor X in city Y", "Affordability concern raised by Active segment").

COMMERCIAL_ACTIONS — detect execution-layer signals from the note. All booleans default false. Only flip true if explicitly mentioned. Dates are ISO YYYY-MM-DD. Fields:
- demo_discussed, demo_booked, demo_booked_date, demo_completed, demo_completed_date
- boost_discussed (any mention of "boost" pricing), trade_in_discussed, trade_in_interest, growth_program_explained
- proposal_discussed, proposal_sent, proposal_sent_date, proposal_follow_up_done

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
  "commercial_actions": {
    "demo_discussed": false, "demo_booked": false, "demo_booked_date": null,
    "demo_completed": false, "demo_completed_date": null,
    "boost_discussed": false, "trade_in_discussed": false, "trade_in_interest": false,
    "growth_program_explained": false,
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
    return {
        "summary": "",
        "topics": [],
        "barriers": [],
        "sentiment": "Neutral",
        "opportunity_state": "Unknown",
        "promises_detected": [],
        "suggested_next_action": "",
        "market_signals": [],
        "privacy_warnings": ([reason] if reason else []),
        "commercial_actions": {
            "demo_discussed": False, "demo_booked": False, "demo_booked_date": None,
            "demo_completed": False, "demo_completed_date": None,
            "boost_discussed": False, "trade_in_discussed": False, "trade_in_interest": False,
            "growth_program_explained": False,
            "proposal_discussed": False, "proposal_sent": False, "proposal_sent_date": None,
            "proposal_follow_up_done": False,
        },
    }


async def analyze_note(note: str, session_id: str) -> dict:
    """Run AI extraction. Always returns the schema, never raises."""
    note = (note or "").strip()
    if not note:
        return _empty_result()
    if not EMERGENT_KEY:
        logger.warning("EMERGENT_LLM_KEY missing; returning empty extraction")
        return _empty_result("AI not configured")
    try:
        chat = LlmChat(
            api_key=EMERGENT_KEY,
            session_id=session_id,
            system_message=SYSTEM_PROMPT,
        ).with_model(MODEL_PROVIDER, MODEL_NAME)
        msg = UserMessage(text=f"Visit note:\n\"\"\"\n{note}\n\"\"\"\n\nReturn the JSON object now.")
        raw = await chat.send_message(msg)
        data = _safe_json(raw if isinstance(raw, str) else str(raw))
        if not data:
            logger.warning("AI returned non-JSON: %s", str(raw)[:300])
            return _empty_result("AI parse error")

        # Normalise + clamp
        result = _empty_result()
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

        # Commercial actions
        ca_in = data.get("commercial_actions") or {}
        ca = result["commercial_actions"]
        for k in ca.keys():
            if k.endswith("_date"):
                ca[k] = ca_in.get(k) or None
            else:
                ca[k] = bool(ca_in.get(k))
        return result
    except Exception as e:
        logger.exception("AI analyze_note failed: %s", e)
        return _empty_result(f"AI error: {type(e).__name__}")
