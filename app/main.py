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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ═══ Handle OPTIONS preflight for all routes ═══
# Return proper CORS headers so the browser accepts custom headers
# (e.g. Authorization: Bearer) on the actual request.
@app.options("/{path:path}")
async def options_handler(path: str):
    return JSONResponse(
        content={"ok": True},
        headers={
            "Access-Control-Allow-Origin": "http://localhost:5173",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )

app.include_router(extract_router, prefix="/api", tags=["Extraction"])
app.include_router(email_router, prefix="/api/email", tags=["Email"])
app.include_router(access_router, prefix="/api/access", tags=["Access"])


@app.get("/")
async def root():
    return {"message": "Bewerbung Boot API is running!", "version": "2.0.0"}