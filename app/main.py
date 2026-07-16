import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes import extract_router, email_router, access_router

app = FastAPI(
    title="Bewerbung Boot Scraper API",
    description="Scraping + Email via Gmail API",
    version="2.0.0",
)

# ═══ CORS — MUST be before routers ═══
# Origins are configurable so the same build works locally and on Render.
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(extract_router, prefix="/api", tags=["Extraction"])
app.include_router(email_router, prefix="/api/email", tags=["Email"])
app.include_router(access_router, prefix="/api/access", tags=["Access"])


@app.get("/")
async def root():
    return {"message": "Bewerbung Boot API is running!", "version": "2.0.0"}