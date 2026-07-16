# """
# BEWERBUNG_BOOT_BACK - FastAPI with Google OAuth2 + Gmail API
# """
# from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends, Request
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import RedirectResponse, JSONResponse
# from pydantic import BaseModel, EmailStr
# from typing import List, Optional
# import os
# import json
# import base64
# import time
# from datetime import datetime, timedelta
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText
# from email.mime.base import MIMEBase
# from email import encoders

# # Google Auth
# from google_auth_oauthlib.flow import Flow
# from google.oauth2.credentials import Credentials
# from googleapiclient.discovery import build
# from google.auth.transport.requests import Request as GoogleRequest

# app = FastAPI(title="Bewerbung Boot API", version="2.0")

# # CORS
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["http://localhost:5173", "http://localhost:3000"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # ═══════════════════════════════════════════
# # CONFIGURATION - Set these in .env file!
# # ═══════════════════════════════════════════

# GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
# GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
# GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
# FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# # Scopes needed for Gmail sending
# SCOPES = [
#     "openid",
#     "https://www.googleapis.com/auth/userinfo.email",
#     "https://www.googleapis.com/auth/userinfo.profile",
#     "https://www.googleapis.com/auth/gmail.send",  # Send emails
#     "https://www.googleapis.com/auth/gmail.readonly",  # Read sent emails
# ]

# # In-memory token store (use Redis/DB in production!)
# # Key: user_id, Value: {access_token, refresh_token, expires_at, email}
# user_tokens = {}

# # ═══════════════════════════════════════════
# # PYDANTIC MODELS
# # ═══════════════════════════════════════════

# class CompanyData(BaseModel):
#     company_name: str
#     email: str
#     city: str
#     field: str
#     website: Optional[str] = ""
#     phone: Optional[str] = ""
#     job_title: Optional[str] = ""

# class EmailPayload(BaseModel):
#     subject: str
#     content: str
#     companies: List[CompanyData]
#     wait_time: int = 30
#     skip_sent: bool = False
#     sent_companies: List[str] = []

# class EmailResult(BaseModel):
#     email: str
#     company_name: str
#     status: str
#     message: str
#     timestamp: str

# class SendResponse(BaseModel):
#     success: bool
#     total: int
#     sent: int
#     skipped: int
#     failed: int
#     results: List[EmailResult]

# class UserInfo(BaseModel):
#     id: str
#     email: str
#     name: str
#     picture: Optional[str] = ""
#     connected: bool

# # ═══════════════════════════════════════════
# # GOOGLE AUTH HELPERS
# # ═══════════════════════════════════════════

# def get_google_flow():
#     """Create OAuth2 flow"""
#     return Flow.from_client_config(
#         {
#             "web": {
#                 "client_id": GOOGLE_CLIENT_ID,
#                 "client_secret": GOOGLE_CLIENT_SECRET,
#                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
#                 "token_uri": "https://oauth2.googleapis.com/token",
#                 "redirect_uris": [GOOGLE_REDIRECT_URI],
#             }
#         },
#         scopes=SCOPES,
#         redirect_uri=GOOGLE_REDIRECT_URI,
#     )

# def get_gmail_service(user_id: str):
#     """Get Gmail API service for a user"""
#     if user_id not in user_tokens:
#         return None

#     token_data = user_tokens[user_id]
#     creds = Credentials(
#         token=token_data["access_token"],
#         refresh_token=token_data.get("refresh_token"),
#         token_uri="https://oauth2.googleapis.com/token",
#         client_id=GOOGLE_CLIENT_ID,
#         client_secret=GOOGLE_CLIENT_SECRET,
#         scopes=SCOPES,
#     )

#     # Refresh if expired
#     if creds.expired and creds.refresh_token:
#         creds.refresh(GoogleRequest())
#         token_data["access_token"] = creds.token
#         token_data["expires_at"] = (datetime.now() + timedelta(seconds=creds.expiry.timestamp() - datetime.now().timestamp())).isoformat()

#     return build("gmail", "v1", credentials=creds)

# # ═══════════════════════════════════════════
# # AUTH ENDPOINTS
# # ═══════════════════════════════════════════

# @app.get("/api/auth/google/login")
# def google_login():
#     """Start Google OAuth2 flow"""
#     flow = get_google_flow()
#     authorization_url, state = flow.authorization_url(
#         access_type="offline",  # Get refresh token
#         include_granted_scopes="true",
#         prompt="consent",  # Force consent screen to get refresh token
#     )
#     return {"auth_url": authorization_url}

# @app.get("/api/auth/google/callback")
# def google_callback(code: str, state: str):
#     """Handle OAuth2 callback from Google"""
#     try:
#         flow = get_google_flow()
#         flow.fetch_token(code=code)

#         creds = flow.credentials

#         # Get user info
#         service = build("oauth2", "v2", credentials=creds)
#         user_info = service.userinfo().get().execute()

#         user_id = user_info["id"]

#         # Store tokens
#         user_tokens[user_id] = {
#             "access_token": creds.token,
#             "refresh_token": creds.refresh_token,
#             "expires_at": (datetime.now() + timedelta(seconds=creds.expiry.timestamp() - datetime.now().timestamp())).isoformat() if creds.expiry else None,
#             "email": user_info["email"],
#             "name": user_info.get("name", ""),
#             "picture": user_info.get("picture", ""),
#         }

#         # Redirect to frontend with success
#         return RedirectResponse(
#             url=f"{FRONTEND_URL}/dashboard-client/emails-senden?google_connected=true&email={user_info['email']}"
#         )

#     except Exception as e:
#         return RedirectResponse(
#             url=f"{FRONTEND_URL}/dashboard-client/emails-senden?error={str(e)}"
#         )

# @app.get("/api/auth/user", response_model=UserInfo)
# def get_current_user(user_id: str):
#     """Get current user info"""
#     if user_id not in user_tokens:
#         raise HTTPException(status_code=401, detail="Not authenticated")

#     user = user_tokens[user_id]
#     return UserInfo(
#         id=user_id,
#         email=user["email"],
#         name=user["name"],
#         picture=user.get("picture", ""),
#         connected=True,
#     )

# @app.post("/api/auth/logout")
# def logout(user_id: str):
#     """Logout and remove tokens"""
#     if user_id in user_tokens:
#         del user_tokens[user_id]
#     return {"success": True}

# @app.get("/api/auth/check")
# def check_auth(user_id: str):
#     """Check if user is authenticated with Gmail"""
#     if user_id not in user_tokens:
#         return {"connected": False}

#     # Try to get Gmail service to verify token works
#     try:
#         service = get_gmail_service(user_id)
#         if service:
#             profile = service.users().getProfile(userId="me").execute()
#             return {
#                 "connected": True,
#                 "email": profile.get("emailAddress"),
#                 "messages_total": profile.get("messagesTotal", 0),
#             }
#     except Exception:
#         pass

#     return {"connected": False}

# # ═══════════════════════════════════════════
# # EMAIL HELPERS (Gmail API)
# # ═══════════════════════════════════════════

# def create_message_with_attachments(
#     sender: str,
#     to: str,
#     subject: str,
#     html_content: str,
#     attachments: List[dict] = None
# ) -> dict:
#     """Create Gmail API message with attachments"""
#     message = MIMEMultipart("alternative")
#     message["to"] = to
#     message["from"] = sender
#     message["subject"] = subject

#     # Attach HTML body
#     msg_html = MIMEText(html_content, "html", "utf-8")
#     message.attach(msg_html)

#     # Attach files
#     if attachments:
#         for att in attachments:
#             part = MIMEBase("application", "octet-stream")
#             part.set_payload(att["content"])
#             encoders.encode_base64(part)
#             part.add_header(
#                 "Content-Disposition",
#                 f'attachment; filename="{att["filename"]}"'
#             )
#             message.attach(part)

#     raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
#     return {"raw": raw}

# def personalize_email(content: str, company: CompanyData) -> str:
#     """Replace placeholders"""
#     replacements = {
#         "{{COMPANY_NAME}}": company.company_name,
#         "{{COMPANY}}": company.company_name,
#         "{{CITY}}": company.city,
#         "{{FIELD}}": company.field,
#         "{{JOB_TITLE}}": company.job_title or "Ausbildungsplatz",
#         "{{WEBSITE}}": company.website or "",
#     }
#     for placeholder, value in replacements.items():
#         content = content.replace(placeholder, value)
#     return content

# # ═══════════════════════════════════════════
# # EMAIL ENDPOINTS
# # ═══════════════════════════════════════════

# @app.post("/api/email/send-batch", response_model=SendResponse)
# async def send_batch_emails(
#     user_id: str = Form(...),
#     payload: str = Form(...),
#     cv_file: Optional[UploadFile] = File(None),
#     motivation_letter: Optional[UploadFile] = File(None),
#     additional_files: Optional[List[UploadFile]] = File(None),
# ):
#     """Send batch emails via Gmail API"""

#     # Verify user is authenticated
#     if user_id not in user_tokens:
#         raise HTTPException(status_code=401, detail="Not authenticated with Google")

#     # Get Gmail service
#     service = get_gmail_service(user_id)
#     if not service:
#         raise HTTPException(status_code=401, detail="Failed to create Gmail service")

#     # Parse payload
#     try:
#         data = json.loads(payload)
#         payload_obj = EmailPayload(**data)
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

#     # Get sender email
#     sender_email = user_tokens[user_id]["email"]

#     # Prepare attachments
#     attachments = []
#     if cv_file:
#         content = await cv_file.read()
#         attachments.append({"filename": cv_file.filename, "content": content})
#     if motivation_letter:
#         content = await motivation_letter.read()
#         attachments.append({"filename": motivation_letter.filename, "content": content})
#     if additional_files:
#         for file in additional_files:
#             content = await file.read()
#             attachments.append({"filename": file.filename, "content": content})

#     results = []
#     sent_count = skipped_count = failed_count = 0

#     for company in payload_obj.companies:
#         # Skip if already sent
#         if payload_obj.skip_sent and company.email in payload_obj.sent_companies:
#             results.append(EmailResult(
#                 email=company.email,
#                 company_name=company.company_name,
#                 status="skipped",
#                 message="Already sent",
#                 timestamp=datetime.now().isoformat()
#             ))
#             skipped_count += 1
#             continue

#         try:
#             # Personalize content
#             personalized_html = personalize_email(payload_obj.content, company)
#             if "<" not in personalized_html:
#                 personalized_html = personalized_html.replace("\n", "<br>").replace("
# ", "<br>")

#             # Create message
#             message = create_message_with_attachments(
#                 sender=sender_email,
#                 to=company.email,
#                 subject=payload_obj.subject,
#                 html_content=personalized_html,
#                 attachments=attachments
#             )

#             # Send via Gmail API
#             sent = service.users().messages().send(userId="me", body=message).execute()

#             results.append(EmailResult(
#                 email=company.email,
#                 company_name=company.company_name,
#                 status="sent",
#                 message=f"Message ID: {sent['id']}",
#                 timestamp=datetime.now().isoformat()
#             ))
#             sent_count += 1

#         except Exception as e:
#             results.append(EmailResult(
#                 email=company.email,
#                 company_name=company.company_name,
#                 status="failed",
#                 message=str(e),
#                 timestamp=datetime.now().isoformat()
#             ))
#             failed_count += 1

#         # Wait between emails
#         if payload_obj.wait_time > 0:
#             time.sleep(payload_obj.wait_time)

#     return SendResponse(
#         success=True,
#         total=len(payload_obj.companies),
#         sent=sent_count,
#         skipped=skipped_count,
#         failed=failed_count,
#         results=results
#     )

# @app.get("/")
# def root():
#     return {"message": "Bewerbung Boot API v2.0", "status": "running", "auth": "Google OAuth2"}


# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)