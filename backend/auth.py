"""Authentication utilities — JWT + bcrypt + role guards.

Phase Audit P2 — brute force protection added via a MongoDB `login_attempts`
collection. We key attempts by both `ip:email` and `email` so that an attacker
rotating IPs is still throttled per email. A TTL index purges old attempts.
"""
import os
import jwt
import bcrypt
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Ensure .env is loaded even if this module is imported before server.py executes load_dotenv
load_dotenv(Path(__file__).parent / ".env")

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

# Brute-force protection knobs.
LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "15"))

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(user_id: str, role: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# Dependency injected later with the db handle
_db = None


def set_db(db):
    global _db
    _db = db


# ============================================================
# Brute-force protection (Phase Audit P2)
# ============================================================
def _login_attempt_keys(ip: Optional[str], email: str) -> list[str]:
    """Two complementary identifiers — IP+email AND email-only.

    Per-IP+email blocks credential stuffing from a single host.
    Per-email blocks an attacker who rotates IPs against one account.
    """
    email = (email or "").lower().strip()
    keys = []
    if ip:
        keys.append(f"ip:{ip}|email:{email}")
    keys.append(f"email:{email}")
    return keys


async def assert_not_locked_out(ip: Optional[str], email: str):
    """Raise HTTP 429 if the caller has burned through their failure budget.

    Reads `login_attempts` documents — `last_attempt_at` is a BSON Date so the
    TTL index in `server.py` can auto-evict stale rows. Attempts older than
    the lockout window don't count.
    """
    if _db is None:  # pragma: no cover — set on startup
        return
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    docs = await _db.login_attempts.find(
        {"identifier": {"$in": _login_attempt_keys(ip, email)}},
        {"_id": 0, "count": 1, "last_attempt_at": 1},
    ).to_list(2)
    over = any(
        (d.get("count", 0) >= LOGIN_MAX_FAILURES)
        and _to_dt(d.get("last_attempt_at")) >= cutoff
        for d in docs
    )
    if over:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {LOGIN_LOCKOUT_MINUTES} minutes.",
        )


def _to_dt(v) -> datetime:
    """Coerce `last_attempt_at` to a timezone-aware UTC datetime.

    Supports both BSON Date and legacy ISO strings (zero migration risk if any
    old rows linger in the DB).
    """
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


async def record_failed_login(ip: Optional[str], email: str):
    """Increment failure counters for both keys."""
    if _db is None:  # pragma: no cover
        return
    now = datetime.now(timezone.utc)
    for key in _login_attempt_keys(ip, email):
        await _db.login_attempts.update_one(
            {"identifier": key},
            {"$inc": {"count": 1}, "$set": {"last_attempt_at": now}},
            upsert=True,
        )


async def clear_login_attempts(ip: Optional[str], email: str):
    """Wipe failure counters after a successful auth."""
    if _db is None:  # pragma: no cover
        return
    await _db.login_attempts.delete_many(
        {"identifier": {"$in": _login_attempt_keys(ip, email)}}
    )


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    user = await _db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("active_status", True):
        raise HTTPException(status_code=403, detail="User is deactivated")
    return user


def require_roles(*roles: str):
    # Owner role implicitly satisfies any Admin requirement
    effective = set(roles)
    if "Admin" in effective:
        effective.add("Owner")
    # SeniorTM is a Phase-L hybrid — a TM AND a Manager. Any endpoint
    # allowed to Manager or TM is therefore allowed to SeniorTM as well.
    # This centralises the promise "SeniorTM ≥ union(TM, Manager)" so it
    # holds for every current AND future route without a manual sweep.
    if effective & {"Manager", "TM"}:
        effective.add("SeniorTM")

    async def _checker(user: dict = Depends(get_current_user)):
        if user["role"] not in effective:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: requires role(s) {', '.join(roles)}",
            )
        return user

    return _checker
