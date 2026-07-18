"""
Extraction route: handles scraping requests from the frontend.
Supports: arbeitsagentur, azubiyo, aubiplus, ausbildungde, azubica, indeed, linkedin, xing
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import inspect

from app.services.extract_progress import reset, stream_generator

router = APIRouter()

# Lazy imports to avoid circular import issues at module level
SCRAPER_MAP = {}


def _load_scrapers():
    """Load scrapers lazily to avoid circular imports."""
    global SCRAPER_MAP
    if SCRAPER_MAP:
        return

    scrapers = {}

    try:
        from app.services.arbeitsagentur_scraper import ArbeitsagenturScraper
        scrapers["arbeitsagentur"] = ArbeitsagenturScraper
    except Exception as e:
        print(f"[WARN] Could not load arbeitsagentur_scraper: {e}")

    try:
        from app.services.azubiyo_scraper import AzubiyoScraper
        scrapers["azubiyo"] = AzubiyoScraper
    except Exception as e:
        print(f"[WARN] Could not load azubiyo_scraper: {e}")

    try:
        from app.services.aubiplus_scraper import AubiPlusScraper
        scrapers["aubiplus"] = AubiPlusScraper
    except Exception as e:
        print(f"[WARN] Could not load aubiplus_scraper: {e}")

    try:
        from app.services.ausbildungde_scraper import AusbildungDeScraper
        scrapers["ausbildungde"] = AusbildungDeScraper
    except Exception as e:
        print(f"[WARN] Could not load ausbildungde_scraper: {e}")

    try:
        from app.services.azubica import AzubicaScraper
        scrapers["azubica"] = AzubicaScraper
    except Exception as e:
        print(f"[WARN] Could not load azubica: {e}")

    try:
        from app.services.indeed_scraper import IndeedScraper
        scrapers["indeed"] = IndeedScraper
    except Exception as e:
        print(f"[WARN] Could not load indeed_scraper: {e}")

    try:
        from app.services.linkedin_scraper import LinkedInScraper
        scrapers["linkedin"] = LinkedInScraper
    except Exception as e:
        print(f"[WARN] Could not load linkedin_scraper: {e}")

    try:
        from app.services.xing_scraper import XingScraper
        scrapers["xing"] = XingScraper
    except Exception as e:
        print(f"[WARN] Could not load xing_scraper: {e}")

    SCRAPER_MAP = scrapers


class ExtractConfig(BaseModel):
    """Flexible config that works for ALL sources."""
    profession: str = ""
    location: str = ""
    locationScope: str = "Ganzer Ort"
    jobType: str = ""
    date: str = "Heute"
    maxJobs: int = 50


class ExtractPayload(BaseModel):
    source: str
    config: ExtractConfig
    fieldTags: List[str]
    maxResults: int = 50
    alreadyExtractedEmails: List[str] = []


class ExtractResponse(BaseModel):
    success: bool
    companies: List[dict]
    totalItems: int
    logs: List[dict]
    error: Optional[str] = None


def _get_profession(config: ExtractConfig, fieldTags: List[str]) -> str:
    """Get profession from config or fallback to first fieldTag."""
    profession = config.profession.strip() if config.profession else ""
    if not profession and fieldTags:
        profession = fieldTags[0].strip()
    return profession


def _build_scraper_kwargs(source: str, config: ExtractConfig, fieldTags: List[str], maxResults: int, add_log, already_extracted_emails: List[str] = None) -> Dict[str, Any]:
    """Build kwargs dynamically based on source type."""
    profession = _get_profession(config, fieldTags)

    kwargs = {
        "profession": profession,
        "location": config.location or "",
        "max_results": min(maxResults, 500),
        "field_tags": fieldTags,
        "log_callback": add_log,
    }

    if already_extracted_emails:
        kwargs["already_extracted_emails"] = already_extracted_emails

    if source in ("arbeitsagentur", "indeed", "linkedin", "xing"):
        kwargs["location_scope"] = config.locationScope or "Ganzer Ort"

    if source in ("arbeitsagentur", "indeed", "linkedin", "xing"):
        if not config.jobType:
            defaults = {
                "arbeitsagentur": "Ausbildung / Duales Studium",
                "indeed": "Ausbildung",
                "linkedin": "Praktikum",
                "xing": "Ausbildung",
            }
            kwargs["job_type"] = defaults.get(source, "Ausbildung")
        else:
            kwargs["job_type"] = config.jobType

    if source in ("arbeitsagentur", "indeed", "linkedin", "xing"):
        kwargs["date_filter"] = config.date or "Heute"

    return kwargs


@router.post("/extract", response_model=ExtractResponse)
async def extract_data(payload: ExtractPayload):
    """Main extraction endpoint."""
    _load_scrapers()

    logs = []

    def add_log(type_: str, message: str):
        logs.append({"type": type_, "message": message})
        print(f"[{type_.upper()}] {message}")

    # Reset the SSE event queue so the frontend starts from a clean state.
    try:
        reset()
    except Exception:
        pass

    add_log("info", f"=== NEW EXTRACTION REQUEST ===")
    add_log("info", f"Source: {payload.source}")
    add_log("info", f"Profession: '{payload.config.profession}'")
    add_log("info", f"Location: '{payload.config.location}'")
    add_log("info", f"Max Results: {payload.maxResults}")
    add_log("info", "Filter: Only companies with email will be kept")

    if payload.source not in SCRAPER_MAP:
        supported = ", ".join(SCRAPER_MAP.keys())
        add_log("error", f"Source '{payload.source}' not supported.")
        return ExtractResponse(
            success=False,
            companies=[],
            totalItems=0,
            logs=logs,
            error=f"Source '{payload.source}' not supported. Available: {supported}"
        )

    profession = _get_profession(payload.config, payload.fieldTags)
    if not profession:
        add_log("error", "Profession is empty!")
        return ExtractResponse(
            success=False,
            companies=[],
            totalItems=0,
            logs=logs,
            error="Profession is required but was empty."
        )

    try:
        ScraperClass = SCRAPER_MAP[payload.source]

        kwargs = _build_scraper_kwargs(
            source=payload.source,
            config=payload.config,
            fieldTags=payload.fieldTags,
            maxResults=payload.maxResults,
            add_log=add_log,
            already_extracted_emails=payload.alreadyExtractedEmails or [],
        )

        # Filter kwargs to only include what the scraper accepts
        sig = inspect.signature(ScraperClass.__init__)
        valid_params = set(sig.parameters.keys())
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_params}

        add_log("info", f"Scraper kwargs: {filtered_kwargs}")

        scraper = ScraperClass(**filtered_kwargs)
        scraper.source_label = payload.source
        scraper.already_extracted_emails = set(
            e.lower() for e in (payload.alreadyExtractedEmails or []) if e
        )
        try:
            from app.services.extract_progress import set_progress as _sp
            _sp(True, payload.source, "", "", 0, 0, "running")
        except Exception:
            pass
        companies = await asyncio.wait_for(scraper.scrape(), timeout=90.0)

        add_log("success", f"Extraction complete! {len(companies)} companies with email found.")

        # Tell the SSE stream the scrape is done.
        try:
            from app.services.extract_progress import set_progress as _sp
            _sp(True, payload.source, "", "", len(companies), 0, "done")
        except Exception:
            pass

        return ExtractResponse(
            success=True,
            companies=companies,
            totalItems=len(companies),
            logs=logs,
        )

    except asyncio.TimeoutError:
        add_log("error", "Scrape timed out after 50 seconds.")
        try:
            from app.services.extract_progress import set_progress as _sp
            _sp(False, payload.source, "", "", 0, 0, "error")
        except Exception:
            pass
        return ExtractResponse(
            success=False,
            companies=[],
            totalItems=0,
            logs=logs,
            error="Scrape timed out after 50 seconds. Please try again or reduce the number of results."
        )

    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback_str = traceback.format_exc()
        add_log("error", error_msg)
        add_log("error", f"Traceback: {traceback_str}")
        # Tell the SSE stream the scrape errored.
        try:
            from app.services.extract_progress import set_progress as _sp
            _sp(False, payload.source, "", "", len(getattr(e, "companies", [])), 0, "error")
        except Exception:
            pass
        return ExtractResponse(
            success=False,
            companies=[],
            totalItems=0,
            logs=logs,
            error=error_msg
        )


@router.get("/extract/stream")
async def extract_stream():
    """Server-Sent Events stream of live scraping progress.

    Emits `progress` events (current company, its logo URL,
    running email count) and `log` events, terminated by a
    `done` / `error` / `stopped` progress event.
    """
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/test-extract")
async def test_extract():
    """Quick test endpoint with fixed params."""
    import asyncio
    import traceback

    logs = []
    def add_log(type_: str, message: str):
        logs.append({"type": type_, "message": message})
        print(f"[{type_.upper()}] {message}")

    add_log("info", "=== TEST EXTRACTION ===")
    add_log("info", "Profession: Softwareentwickler")
    add_log("info", "Location: Berlin")
    add_log("info", "Max Results: 10")
    add_log("info", "Filter: Only companies with email")

    try:
        _load_scrapers()
        if "arbeitsagentur" not in SCRAPER_MAP:
            return {
                "success": False,
                "error": "Arbeitsagentur scraper not available",
                "logs": logs,
            }

        scraper = SCRAPER_MAP["arbeitsagentur"](
            profession="Softwareentwickler",
            location="Berlin",
            location_scope="Ganzer Ort",
            job_type="Arbeit",
            date_filter="Alle anzeigen",
            max_results=10,
            field_tags=["Softwareentwickler"],
            log_callback=add_log,
        )

        add_log("info", "Starting scrape with 60s timeout...")
        companies = await asyncio.wait_for(scraper.scrape(), timeout=60.0)

        add_log("success", f"Scrape complete! {len(companies)} companies with email found.")

        return {
            "success": True,
            "companies": companies,
            "totalItems": len(companies),
            "logs": logs,
        }

    except asyncio.TimeoutError:
        add_log("error", "Scrape timed out after 60 seconds!")
        return {
            "success": False,
            "companies": [],
            "totalItems": 0,
            "logs": logs,
            "error": "Scrape timed out after 60 seconds",
        }

    except Exception as e:
        add_log("error", str(e))
        return {
            "success": False,
            "companies": [],
            "totalItems": 0,
            "logs": logs,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }