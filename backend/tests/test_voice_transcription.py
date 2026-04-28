"""Tests for POST /api/visits/transcribe (Whisper voice memo transcription)."""
import os
import io
import math
import struct
import wave
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _make_wav(seconds=1.0, freq=440.0, sr=16000):
    """Synthesize a short sine-wave WAV (non-empty audio). Whisper may return empty text
    for pure tones; that's treated as a soft success per the review_request."""
    n = int(seconds * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / sr))) for i in range(n))
        w.writeframes(frames)
    return buf.getvalue()


@pytest.fixture(scope="module")
def tm_token():
    return _login("tm1@field.io", "tm123")


@pytest.fixture(scope="module")
def mgr_token():
    return _login("manager@field.io", "manager123")


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@field.io", "admin123")


# ---------- AUTH ----------
def test_transcribe_requires_auth():
    wav = _make_wav()
    r = requests.post(
        f"{BASE_URL}/api/visits/transcribe",
        files={"audio": ("voice.wav", wav, "audio/wav")},
        timeout=30,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"


# ---------- EMPTY BODY ----------
def test_transcribe_empty_audio_returns_400(tm_token):
    r = requests.post(
        f"{BASE_URL}/api/visits/transcribe",
        headers={"Authorization": f"Bearer {tm_token}"},
        files={"audio": ("voice.wav", b"", "audio/wav")},
        timeout=30,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------- VALID AUDIO (all roles) ----------
@pytest.mark.parametrize("role", ["tm", "mgr", "admin"])
def test_transcribe_valid_audio_returns_200(role, tm_token, mgr_token, admin_token):
    tok = {"tm": tm_token, "mgr": mgr_token, "admin": admin_token}[role]
    wav = _make_wav(seconds=1.0)
    r = requests.post(
        f"{BASE_URL}/api/visits/transcribe",
        headers={"Authorization": f"Bearer {tok}"},
        files={"audio": ("voice.wav", wav, "audio/wav")},
        timeout=60,
    )
    # Whisper may return 200 with empty text for non-speech audio (soft success)
    assert r.status_code == 200, f"[{role}] expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "text" in data, f"[{role}] response missing 'text' field: {data}"
    assert isinstance(data["text"], str), f"[{role}] 'text' must be str"


# ---------- SIZE LIMIT (optional) ----------
def test_transcribe_oversize_returns_413(tm_token):
    # Build a >25MB body quickly (zero-filled bytes won't hit Whisper — we expect 413 before any API call)
    big = b"\x00" * (26 * 1024 * 1024)
    r = requests.post(
        f"{BASE_URL}/api/visits/transcribe",
        headers={"Authorization": f"Bearer {tm_token}"},
        files={"audio": ("big.wav", big, "audio/wav")},
        timeout=60,
    )
    assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"
