import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import extract_router, email_router, access_router

app = FastAPI(
    title="Bewerbung Boot Scraper API",
    description="Scraping + Email via Gmail API",
    version="2.0.0",
)

# Allowed origins
_DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://www.bewerbungs.online",
    "https://bewerbung-boot-front-end.vercel.app",
]

_ENV_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "").split(",")
    if o.strip()
]

# Merge env origins with defaults, preserving order and removing duplicates.
_ALLOWED_ORIGINS = []
_seen = set()
for origin in _ENV_ORIGINS + _DEFAULT_ORIGINS:
    if origin not in _seen:
        _ALLOWED_ORIGINS.append(origin)
        _seen.add(origin)

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
    return {
        "message": "Bewerbung Boot API is running!",
        "version": "2.0.0",
        "cors_origins": _ALLOWED_ORIGINS,
    }


@app.on_event("startup")
async def startup_event():
    print(f"[CORS] Allowed origins: {_ALLOWED_ORIGINS}")