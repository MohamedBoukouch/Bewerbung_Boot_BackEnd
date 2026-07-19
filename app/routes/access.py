from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, field_validator
from fastapi.responses import RedirectResponse
import os
import secrets
import httpx
import time
import json
import fcntl
import pathlib

from app.services import sheets_client
from app.services.auth import (
    create_session_token,
    decode_session_token,
    set_session_cookie,
    clear_session_cookie,
    COOKIE_NAME,
    get_token_from_request,
)

router = APIRouter()

# CORS preflight handlers for access routes
@router.options("/leads/submit")
@router.options("/validate-code")
@router.options("/activate-code")
@router.options("/session")
@router.options("/google-status")
@router.options("/logout")
@router.options("/google-login")
@router.options("/google/callback")
async def cors_preflight():
    return Response(status_code=204)

# ═══════════════════════════════════════════════════════════
# FILE STORES (persistent across workers & restarts)
# ═══════════════════════════════════════════════════════════

PENDING_FILE = pathlib.Path("/tmp/bb_pending_codes.json")
GOOGLE_TOKENS_FILE = pathlib.Path("/tmp/bb_google_tokens.json")

def _load_json_file(filepath: pathlib.Path):
    if not filepath.exists():
        return {}
    try:
        with open(filepath, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except Exception:
        return {}

def _save_json_file(filepath: pathlib.Path, data: dict):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f)
        fcntl.flock(f, fcntl.LOCK_UN)

# ── Pending codes (OAuth state) ──
def _load_pending():
    return _load_json_file(PENDING_FILE)

def _save_pending(data):
    _save_json_file(PENDING_FILE, data)

def _store_pending(state: str, code: str):
    data = _load_pending()
    now = time.time()
    data = {k: v for k, v in data.items() if v.get("exp", 0) > now}
    data[state] = {"code": code.strip().upper(), "exp": now + 600}
    _save_pending(data)
    print(f"[STORE] Saved state={state}, code={code.strip().upper()}")

def _get_pending(state: str):
    data = _load_pending()
    now = time.time()
    data = {k: v for k, v in data.items() if v.get("exp", 0) > now}
    _save_pending(data)
    entry = data.pop(state, None)
    if entry:
        _save_pending(data)
        print(f"[STORE] Found and removed state={state}, code={entry['code']}")
        return entry["code"]
    print(f"[STORE] State {state} not found")
    return None

# ── Google tokens (linked by access code) ──
def _load_google_tokens():
    return _load_json_file(GOOGLE_TOKENS_FILE)

def _save_google_tokens(data):
    _save_json_file(GOOGLE_TOKENS_FILE, data)

def store_google_tokens(access_code: str, tokens: dict):
    data = _load_google_tokens()
    now = time.time()
    data = {k: v for k, v in data.items() if v.get("stored_at", 0) > now - 7776000}
    data[access_code.upper()] = {
        **tokens,
        "stored_at": now,
    }
    _save_google_tokens(data)
    print(f"[GOOGLE] Tokens stored for code={access_code}")

def get_google_tokens(access_code: str):
    data = _load_google_tokens()
    return data.get(access_code.upper())

def delete_google_tokens(access_code: str):
    data = _load_google_tokens()
    if access_code.upper() in data:
        del data[access_code.upper()]
        _save_google_tokens(data)

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "https://bewerbung-boot-backend.onrender.com/api/access/google/callback"
)
FRONTEND_CALLBACK_URL = os.environ.get(
    "FRONTEND_CALLBACK_URL",
    "http://localhost:5173/auth/callback"
)
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

PACK_DURATIONS = {
    "باقة تجريبية": 1,
    "ستاندار": 30,
    "باقة 3 أشهر": 90,
    "باقة 6 أشهر": 180,
}

PACK_PRICES = {
    "باقة تجريبية": 0,
    "ستاندار": 200,
    "باقة 3 أشهر": 450,
    "باقة 6 أشهر": 720,
}

# ═══════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════

class SubmitLeadBody(BaseModel):
    pack: str
    full_name: str
    email: EmailStr
    whatsapp: str

    @field_validator("full_name", "whatsapp")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Champ requis.")
        return v


class ValidateCodeBody(BaseModel):
    code: str


class ActivateCodeBody(BaseModel):
    code: str
    email: EmailStr


# ═══════════════════════════════════════════════════════════
# LEADS
# ═══════════════════════════════════════════════════════════

@router.post("/leads/submit")
async def submit_lead(body: SubmitLeadBody):
    duration_days = PACK_DURATIONS.get(body.pack)
    if duration_days is None:
        raise HTTPException(status_code=400, detail=f"Pack inconnu: {body.pack}")

    try:
        await sheets_client.submit_lead(
            pack=body.pack,
            duration_days=duration_days,
            full_name=body.full_name,
            email=body.email,
            whatsapp=body.whatsapp,
        )
    except sheets_client.SheetsClientError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "status": "pending",
        "message": "Merci ! Nous vous contacterons très bientôt sur WhatsApp pour confirmer votre paiement.",
    }


# ═══════════════════════════════════════════════════════════
# CODE VALIDATION
# ═══════════════════════════════════════════════════════════

@router.post("/validate-code")
async def validate_code(body: ValidateCodeBody, response: Response):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code manquant.")

    try:
        result = await sheets_client.validate_code(code)
    except sheets_client.SheetsClientError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not result.get("found"):
        raise HTTPException(status_code=404, detail="Ce code n'existe pas.")

    status = result.get("status")

    if status == "pending":
        return {
            "status": "pending",
            "message": "Votre accès est en cours de confirmation. Nous vous contacterons très bientôt sur WhatsApp.",
        }

    if status == "expired":
        raise HTTPException(status_code=410, detail="Ce code a expiré.")

    if status == "google_required":
        return {
            "status": "google_required",
            "pack": result.get("pack"),
            "duration_days": result.get("duration_days"),
            # The secure/private email from the sheet (column E). The Google
            # login email must match this to keep the account binding secure.
            "sheet_email": result.get("sheet_email"),
        }

    if status == "logged_in":
        # Check if Google is already connected for this code.
        # If the Gmail account is not linked yet, we do NOT log the user in
        # directly — they must connect Google first (required to send emails).
        google_tokens = get_google_tokens(code)

        if not google_tokens:
            return {
                "status": "google_required",
                "pack": result.get("pack"),
                "duration_days": result.get("duration_days"),
                "sheet_email": result.get("sheet_email"),
            }

        google_connected = True

        # The email is NEVER taken from the lead's private email.
        # It only comes from the Google account after OAuth (google_tokens).
        gmail_email = google_tokens.get("email")

        token = create_session_token(
            code=code,
            email=gmail_email,
            pack=result.get("pack"),
            expires_at_str=result.get("expiresAt"),
            google_tokens=google_tokens,
        )
        set_session_cookie(response, token)

        return {
            "status": "logged_in",
            "token": token,
            "session": {
                "code": code,
                "email": gmail_email,
                "pack": result.get("pack"),
            },
            "google_connected": google_connected,
            "google_user": {
                "email": google_tokens.get("email"),
                "name": google_tokens.get("name"),
                "picture": google_tokens.get("picture"),
            },
        }

    raise HTTPException(status_code=409, detail=f"Statut de code inconnu: {status}")


@router.post("/activate-code")
async def activate_code(body: ActivateCodeBody, response: Response):
    code = body.code.strip().upper()
    email = body.email.strip()

    try:
        result = await sheets_client.activate_code(code, email)
    except sheets_client.SheetsClientError as e:
        raise HTTPException(status_code=409, detail=str(e))

    token = create_session_token(
        code=code,
        email=email,
        pack=result.get("pack"),
        expires_at_str=result.get("expiresAt"),
        google_tokens=None,
    )
    set_session_cookie(response, token)

    return {
        "status": "logged_in",
        "token": token,
        "session": {"code": code, "email": email, "pack": result.get("pack")},
    }


# ═══════════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════════

@router.get("/session")
async def get_session(request: Request):
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Pas de session.")

    data = decode_session_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée.")

    google_data = data.get("google_tokens")

    # Filter private tokens (access/refresh) out of the frontend response.
    session_info = {
        "code": data.get("code"),
        "email": data.get("email"),
        "pack": data.get("pack"),
    }

    google_user = None
    if google_data:
        google_user = {
            "email": google_data.get("email"),
            "name": google_data.get("name", ""),
            "picture": google_data.get("picture", ""),
        }

    return {
        "status": "logged_in",
        "session": session_info,
        "google_connected": google_data is not None,
        "google_user": google_user,
    }


@router.get("/google-status")
async def google_status(request: Request):
    """Check if Google is connected for current session."""
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Pas de session.")

    data = decode_session_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Session invalide.")

    google_data = data.get("google_tokens")
    
    if not google_data:
        return {"connected": False}
    
    return {
        "connected": True,
        "email": google_data.get("email"),
        "name": google_data.get("name", ""),
        "picture": google_data.get("picture", ""),
    }


@router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"status": "logged_out"}


# ═══════════════════════════════════════════════════════════
# GOOGLE OAUTH
# ═══════════════════════════════════════════════════════════

@router.get("/google-login")
async def google_login_init(code: str):
    """Step 1: Store pending access code, return Google auth URL."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(32)
    _store_pending(state, code)

    scope = "openid email profile https://www.googleapis.com/auth/gmail.send"
    auth_url = (
        f"{GOOGLE_AUTH_URL}"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope.replace(' ', '%20')}"
        f"&state={state}"
        f"&access_type=offline"
        f"&prompt=select_account+consent"  # <-- FIXED: select_account forces account picker
    )

    return {"auth_url": auth_url}


@router.get("/google/callback")
async def google_callback(response: Response, code: str = None, state: str = None, error: str = None):
    """Step 2: Google redirects here. Exchange code, store tokens, activate access code, set session."""

    if error:
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error={error}")

    if not code:
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=missing_code")

    if not state:
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=missing_state")

    # Retrieve pending access code from file store
    pending_code = _get_pending(state)
    if not pending_code:
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=expired_or_invalid_state")

    # Exchange authorization code for access token
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

        if token_res.status_code != 200:
            err = token_res.text[:200]
            return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=token_exchange_failed")

        token_data = token_res.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token:
            return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=no_access_token")

        # Get user info from Google
        user_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if user_res.status_code != 200:
            return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=userinfo_failed")

        user_info = user_res.json()
        google_email = user_info.get("email")

        if not google_email:
            return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=no_email")

    # Activate the access code with the Google email
    try:
        result = await sheets_client.activate_code(pending_code, google_email)
    except sheets_client.SheetsClientError as e:
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error={str(e)}")

    # Store Google tokens linked to the access code
    google_tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "email": google_email,
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
    }
    store_google_tokens(pending_code, google_tokens)

    # Create session token WITH google_tokens
    session_token = create_session_token(
        code=pending_code,
        email=google_email,
        pack=result.get("pack"),
        expires_at_str=result.get("expiresAt"),
        google_tokens=google_tokens,
    )
    set_session_cookie(response, session_token)

    # Redirect to frontend callback with the session token in URL params
    return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?token={session_token}")