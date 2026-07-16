"""
Email Router — Gmail API send only
Reads Google tokens from session JWT cookie (set by access router)
NO OAuth endpoints here — all OAuth is in access.py
"""
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Request, Response
from pydantic import BaseModel
from typing import List, Optional
import os
import json
import base64
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    print("WARNING: Google libraries not installed. Run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")

# ═══ IMPORT from auth service (NOT from access router) ═══
from app.services.auth import (
    decode_session_token,
    get_token_from_request,
    create_session_token,
    set_session_cookie,
    COOKIE_NAME,
)

router = APIRouter(tags=["Email"])

# ── Configuration ──────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.send",
]

# ── Pydantic Models ────────────────────────────────────────
class CompanyData(BaseModel):
    company_name: str
    email: str
    city: str
    field: str
    website: Optional[str] = ""
    phone: Optional[str] = ""
    job_title: Optional[str] = ""

class EmailPayload(BaseModel):
    subject: str
    content: str
    companies: List[CompanyData]
    wait_time: int = 30
    skip_sent: bool = False
    sent_companies: List[str] = []

class EmailResult(BaseModel):
    email: str
    company_name: str
    status: str
    message: str
    timestamp: str

class SendResponse(BaseModel):
    success: bool
    total: int
    sent: int
    skipped: int
    failed: int
    results: List[EmailResult]
    new_token: Optional[str] = None

# ── Helper Functions ───────────────────────────────────────
def create_message(sender: str, to: str, subject: str, html_content: str, attachments: List[dict] = None):
    message = MIMEMultipart("alternative")
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    message.attach(MIMEText(html_content, "html", "utf-8"))
    if attachments:
        for att in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(att["content"])
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{att["filename"]}"')
            message.attach(part)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}

def personalize_email(content: str, company: CompanyData) -> str:
    replacements = {
        "{{COMPANY_NAME}}": company.company_name,
        "{{COMPANY}}": company.company_name,
        "{{CITY}}": company.city,
        "{{FIELD}}": company.field,
        "{{JOB_TITLE}}": company.job_title or "Ausbildungsplatz",
        "{{WEBSITE}}": company.website or "",
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    return content

# ═══════════════════════════════════════════════════════════
# EMAIL SENDING — ONLY endpoint in this router
# ═══════════════════════════════════════════════════════════

@router.post("/send-batch", response_model=SendResponse)
async def send_batch_emails(
    request: Request,
    response: Response,
    payload: str = Form(...),
    cv_file: UploadFile = File(...),           # ← REQUIRED
    motivation_letter: Optional[UploadFile] = File(None),
    additional_files: Optional[List[UploadFile]] = File(None),
):
    if not GOOGLE_AVAILABLE:
        raise HTTPException(status_code=500, detail="Google libraries not installed")

    # ── 1. Get session from token ─────────────────────────
    token = get_token_from_request(request)
    new_session_token = None
    if not token:
        raise HTTPException(status_code=401, detail="Pas de session. Veuillez vous reconnecter.")

    session_data = decode_session_token(token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée.")

    code = session_data.get("code")
    if not code:
        raise HTTPException(status_code=401, detail="Code d'accès manquant dans la session.")

    # ── 2. Get Google tokens from session_data ──
    google_data = session_data.get("google_tokens")

    if not google_data:
        raise HTTPException(
            status_code=401,
            detail="Google non connecté. Veuillez vous reconnecter et lier votre compte Google."
        )

    access_token = google_data.get("access_token")
    refresh_token = google_data.get("refresh_token")

    if not access_token:
        raise HTTPException(status_code=401, detail="Token Google invalide.")

    # ── 3. Parse payload ────────────────────────────────────
    try:
        data = json.loads(payload)
        payload_obj = EmailPayload(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

    sender_email = google_data["email"]

    # ── 4. Build Google credentials ────────────────────────
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )

    # ── 5. Refresh token if expired ────────────────────────
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request as GoogleRequest
        try:
            creds.refresh(GoogleRequest())
            # Update stored token in session
            session_data["google_tokens"]["access_token"] = creds.token
            
            new_session_token = create_session_token(
                code=session_data["code"],
                email=session_data["email"],
                pack=session_data["pack"],
                expires_at_str=None,
                exp_timestamp=session_data.get("exp"),
                google_tokens=session_data["google_tokens"],
            )
            set_session_cookie(response, new_session_token)
            print(f"[EMAIL] Token refreshed for code {code}")
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Erreur de rafraîchissement Google: {str(e)}")

    service = build("gmail", "v1", credentials=creds)

    # ── 6. Build attachments ────────────────────────────────
    attachments = []

    # CV — REQUIRED
    cv_content = await cv_file.read()
    attachments.append({"filename": cv_file.filename, "content": cv_content})

    # Motivation letter — OPTIONAL
    if motivation_letter:
        ml_content = await motivation_letter.read()
        attachments.append({"filename": motivation_letter.filename, "content": ml_content})

    # Additional files — OPTIONAL
    if additional_files:
        for file in additional_files:
            af_content = await file.read()
            attachments.append({"filename": file.filename, "content": af_content})

    # ── 7. Send emails ──────────────────────────────────────
    results = []
    sent_count = skipped_count = failed_count = 0

    for idx, company in enumerate(payload_obj.companies):
        if payload_obj.skip_sent and company.email in payload_obj.sent_companies:
            results.append(EmailResult(
                email=company.email,
                company_name=company.company_name,
                status="skipped",
                message="Already sent",
                timestamp=datetime.now().isoformat()
            ))
            skipped_count += 1
            continue

        try:
            personalized_html = personalize_email(payload_obj.content, company)
            if "<" not in personalized_html:
                personalized_html = personalized_html.replace("\\n", "<br>").replace("\n", "<br>")

            message = create_message(
                sender=sender_email,
                to=company.email,
                subject=payload_obj.subject,
                html_content=personalized_html,
                attachments=attachments
            )

            sent = service.users().messages().send(userId="me", body=message).execute()

            results.append(EmailResult(
                email=company.email,
                company_name=company.company_name,
                status="sent",
                message=f"Message ID: {sent['id']}",
                timestamp=datetime.now().isoformat()
            ))
            sent_count += 1

        except Exception as e:
            error_msg = str(e)
            print(f"[SEND ERROR] {company.email}: {error_msg}")
            results.append(EmailResult(
                email=company.email,
                company_name=company.company_name,
                status="failed",
                message=error_msg[:200],
                timestamp=datetime.now().isoformat()
            ))
            failed_count += 1

        if payload_obj.wait_time > 0 and idx < len(payload_obj.companies) - 1:
            time.sleep(payload_obj.wait_time)

    return SendResponse(
        success=True,
        total=len(payload_obj.companies),
        sent=sent_count,
        skipped=skipped_count,
        failed=failed_count,
        results=results,
        new_token=new_session_token
    )