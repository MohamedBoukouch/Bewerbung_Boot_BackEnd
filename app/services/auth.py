import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from fastapi import Request

SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("SESSION_SECRET_KEY is not configured")
ALGORITHM = "HS256"
COOKIE_NAME = "bb_session"

ENV = os.environ.get("ENV", "dev")
IS_PROD = ENV == "production"

COOKIE_SECURE = IS_PROD
COOKIE_SAMESITE = "none" if IS_PROD else "lax"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def get_token_from_request(request: Request) -> Optional[str]:
    """Helper to extract JWT token from Authorization header, ?token= query
    param, or cookie fallback. Query param is used by the Google OAuth callback
    so the SPA does not depend on the cross-site session cookie."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    token = request.query_params.get("token")
    if token:
        return token
    return request.cookies.get(COOKIE_NAME)


def _expiry_timestamp(expires_at_str: Optional[str]) -> int:
    """'dd/MM/yyyy HH:mm' -> timestamp unix. Fallback sur +24h si absent/invalide."""
    if expires_at_str:
        try:
            dt = datetime.strptime(expires_at_str.strip(), "%d/%m/%Y %H:%M")
            return int(dt.timestamp())
        except ValueError:
            pass
    return int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())


def create_session_token(
    code: str,
    email: str,
    pack: str,
    expires_at_str: Optional[str] = None,
    google_tokens: Optional[dict] = None,
    exp_timestamp: Optional[int] = None
) -> str:
    payload = {
        "code": code,
        "email": email,
        "pack": pack,
        "exp": exp_timestamp if exp_timestamp is not None else _expiry_timestamp(expires_at_str),
    }
    if google_tokens:
        payload["google_tokens"] = google_tokens
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_session_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def set_session_cookie(response, token: str):
    """Set the JWT session cookie on the response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


def clear_session_cookie(response):
    """Clear the session cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
    )