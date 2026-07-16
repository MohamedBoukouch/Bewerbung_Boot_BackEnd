# """
# Email Service - Handles all email sending logic
# """
# from fastapi import APIRouter, File, UploadFile, Form, HTTPException, BackgroundTasks
# from fastapi.responses import JSONResponse
# from pydantic import BaseModel, EmailStr
# from typing import List, Optional
# import smtplib
# import ssl
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText
# from email.mime.base import MIMEBase
# from email import encoders
# import json
# import time
# from datetime import datetime
# import os

# router = APIRouter(prefix="/api/email", tags=["email"])

# # Config
# SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
# SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# # Models
# class CompanyData(BaseModel):
#     company_name: str
#     email: str
#     city: str
#     field: str
#     website: Optional[str] = ""
#     phone: Optional[str] = ""
#     job_title: Optional[str] = ""

# class EmailPayload(BaseModel):
#     sender_email: EmailStr
#     sender_password: str
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

# # Helpers
# def personalize_email(content: str, company: CompanyData) -> str:
#     """Replace placeholders with company data"""
#     personalized = content
#     replacements = {
#         "{{COMPANY_NAME}}": company.company_name,
#         "{{COMPANY}}": company.company_name,
#         "{{CITY}}": company.city,
#         "{{FIELD}}": company.field,
#         "{{JOB_TITLE}}": company.job_title or "Ausbildungsplatz",
#         "{{WEBSITE}}": company.website or "",
#     }
#     for placeholder, value in replacements.items():
#         personalized = personalized.replace(placeholder, value)
#     return personalized

# def send_single_email(
#     sender_email: str,
#     sender_password: str,
#     recipient: str,
#     subject: str,
#     html_content: str,
#     attachments: List[dict] = None
# ) -> tuple[bool, str]:
#     """Send a single email via SMTP"""
#     try:
#         msg = MIMEMultipart("alternative")
#         msg["From"] = sender_email
#         msg["To"] = recipient
#         msg["Subject"] = subject
#         msg.attach(MIMEText(html_content, "html", "utf-8"))

#         if attachments:
#             for att in attachments:
#                 part = MIMEBase("application", "octet-stream")
#                 part.set_payload(att["content"])
#                 encoders.encode_base64(part)
#                 part.add_header(
#                     "Content-Disposition",
#                     f'attachment; filename="{att["filename"]}"'
#                 )
#                 msg.attach(part)

#         context = ssl.create_default_context()
#         with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
#             server.starttls(context=context)
#             server.login(sender_email, sender_password)
#             server.sendmail(sender_email, recipient, msg.as_string())

#         return True, "Email sent successfully"
#     except smtplib.SMTPAuthenticationError:
#         return False, "Authentication failed. Check email and app password."
#     except Exception as e:
#         return False, str(e)

# # Endpoints
# @router.post("/send-batch", response_model=SendResponse)
# async def send_batch_emails(
#     payload: str = Form(...),
#     cv_file: Optional[UploadFile] = File(None),
#     motivation_letter: Optional[UploadFile] = File(None),
#     additional_files: Optional[List[UploadFile]] = File(None),
# ):
#     try:
#         data = json.loads(payload)
#         payload_obj = EmailPayload(**data)
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

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
#         if payload_obj.skip_sent and company.email in payload_obj.sent_companies:
#             results.append(EmailResult(
#                 email=company.email,
#                 company_name=company.company_name,
#                 status="skipped",
#                 message="Already sent (skipped via status file)",
#                 timestamp=datetime.now().isoformat()
#             ))
#             skipped_count += 1
#             continue

#         personalized_html = personalize_email(payload_obj.content, company)
#         if "<" not in personalized_html:
#             personalized_html = personalized_html.replace("\n", "<br>").replace("
# ", "<br>")

#         success, message = send_single_email(
#             sender_email=payload_obj.sender_email,
#             sender_password=payload_obj.sender_password,
#             recipient=company.email,
#             subject=payload_obj.subject,
#             html_content=personalized_html,
#             attachments=attachments
#         )

#         if success:
#             sent_count += 1
#             status = "sent"
#         else:
#             failed_count += 1
#             status = "failed"

#         results.append(EmailResult(
#             email=company.email,
#             company_name=company.company_name,
#             status=status,
#             message=message,
#             timestamp=datetime.now().isoformat()
#         ))

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

# @router.get("/test-connection")
# async def test_email_connection(email: str, password: str):
#     try:
#         context = ssl.create_default_context()
#         with smtplib.SMTP(SMTP_PORT, SMTP_PORT) as server:
#             server.starttls(context=context)
#             server.login(email, password)
#         return {"success": True, "message": "Connection successful"}
#     except Exception as e:
#         return {"success": False, "message": str(e)}