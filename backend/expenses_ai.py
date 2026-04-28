"""Receipt OCR extraction using Claude Sonnet 4.5 vision via Emergent Universal Key."""
import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

logger = logging.getLogger(__name__)

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MODEL_PROVIDER = "anthropic"
MODEL_NAME = "claude-sonnet-4-5-20250929"

SYSTEM_PROMPT = """You are an AI receipt parser for a field-rep expense tracking app. Given a photograph of a receipt, extract ONLY these fields and return STRICT JSON:

{
  "amount": <number or null>,
  "currency": <"USD"|"EUR"|"GBP"|"INR"|"AED"|"SAR"|"PLN"|"BGN"|other 3-letter code or null>,
  "expense_date": <"YYYY-MM-DD" or null>,
  "vendor": <string or null>,
  "category_hint": <"Petrol"|"Food"|null>,
  "confidence": <number 0-1>,
  "notes": <string or null>
}

Rules:
- amount must be the total / grand total (not subtotal, not tax line). If multiple totals appear, pick the largest.
- expense_date is the date PRINTED on the receipt. If only a partial date is visible, return null.
- vendor is the merchant name (e.g. "Shell", "Starbucks", "McDonald's"). Use what's printed.
- category_hint: "Petrol" if it's clearly a gas/petrol/fuel station, "Food" if it's a restaurant/cafe/grocery, otherwise null.
- If the image is not a receipt or unreadable, return all nulls and confidence=0.
- Do NOT include any extra fields or commentary.
- Output JSON ONLY.
"""


def _safe_parse_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    # try direct parse
    try:
        return json.loads(raw)
    except Exception:
        pass
    # extract first {...} block
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


async def extract_receipt(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Run vision OCR on a receipt image. Returns structured fields with safe defaults."""
    default = {
        "amount": None,
        "currency": None,
        "expense_date": None,
        "vendor": None,
        "category_hint": None,
        "confidence": 0,
        "notes": None,
    }
    if not EMERGENT_KEY:
        logger.warning("EMERGENT_LLM_KEY missing; skipping receipt OCR")
        return default
    if not image_bytes:
        return default

    b64 = base64.b64encode(image_bytes).decode("ascii")
    try:
        chat = (
            LlmChat(
                api_key=EMERGENT_KEY,
                session_id=f"receipt-ocr-{uuid.uuid4()}",
                system_message=SYSTEM_PROMPT,
            )
            .with_model(MODEL_PROVIDER, MODEL_NAME)
        )
        msg = UserMessage(
            text="Extract the receipt fields and return JSON only.",
            file_contents=[ImageContent(image_base64=b64)],
        )
        raw = await chat.send_message(msg)
        parsed = _safe_parse_json(raw)
        if not parsed:
            logger.warning("Receipt OCR: could not parse JSON response: %s", raw[:200] if raw else "<empty>")
            return default
        # Coerce types defensively
        out = {**default, **{k: parsed.get(k) for k in default.keys() if k in parsed}}
        # Amount → float
        if out["amount"] is not None:
            try:
                out["amount"] = float(str(out["amount"]).replace(",", ""))
            except Exception:
                out["amount"] = None
        # Date sanity
        if out["expense_date"]:
            try:
                datetime.strptime(out["expense_date"], "%Y-%m-%d")
            except Exception:
                out["expense_date"] = None
        # Confidence to float 0..1
        try:
            out["confidence"] = max(0.0, min(1.0, float(out.get("confidence") or 0)))
        except Exception:
            out["confidence"] = 0.0
        # Category hint to allowed set
        if out["category_hint"] not in ("Petrol", "Food"):
            out["category_hint"] = None
        return out
    except Exception:
        logger.exception("Receipt OCR call failed")
        return default


def hash_receipt(image_bytes: bytes) -> str:
    """SHA-1 hex of the image bytes — used for duplicate detection per-TM."""
    import hashlib
    return hashlib.sha1(image_bytes).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
