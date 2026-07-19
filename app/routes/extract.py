"""
Extraction route: handles scraping requests from the frontend.
MULTI-SOURCE MODE: always runs multiple platforms concurrently and merges results.
This eliminates "0 emails" problems caused by a single broken platform.
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import inspect

from app.services.extract_progress import reset, stream_generator, request_stop, get_stop_event

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


# Sources that are always queried in the background regardless of user choice.
# These are the most reliable platforms for German apprenticeship/company emails.
DEFAULT_SOURCES = [
    "arbeitsagentur",
    "ausbildungde",
    "azubiyo",
    "aubiplus",
    "azubica",
    "indeed",
    "linkedin",
    "xing",
    "stepstone",
    "jobware",
    "monster",
    "kimeta",
    "jobboerse_de",
    "stellenanzeigen_de",
    "meinestadt",
    "jooble",
    "glassdoor",
    "jobmensa",
    "workwise",
    "absolventa",
    "berufsstart",
    "meinpraktikum",
    "praktikum_info",
    "praktika_de",
    "workingstudentjobs_de",
    "staufenbiel",
    "eures",
    "make_it_in_germany",
    "interamt",
    "bund_de",
    "lehrstellenradar",
    "handwerk_de",
    "ihk",
    "talent",
    "joblift",
    "yourfirm",
    "yourfirm_ausbildung",
    "connectoor",
    "jobtensor",
    "germantechjobs",
    "berlin_startup_jobs",
    "arbeitnow",
    "wellfound",
    "relocate_me",
    "jobvector",
    "academics",
    "medi_jobs",
    "hotelcareer",
    "gastrojobs",
    "logistik_jobs",
    "salesjob",
    "greenjobs",
    "unicum",
    "campusjaeger",
    "jobstairs",
    "heyjobs",
    "hokify",
]


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


def _build_scraper_kwargs(source: str, config: ExtractConfig, fieldTags: List[str], maxResults: int, add_log) -> Dict[str, Any]:
    """Build kwargs dynamically based on source type."""
    profession = _get_profession(config, fieldTags)

    kwargs = {
        "profession": profession,
        "location": config.location or "",
        "max_results": min(maxResults, 500),
        "field_tags": fieldTags,
        "log_callback": add_log,
    }

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


async def _run_single_source(source: str, payload: ExtractPayload, add_log) -> List[dict]:
    """Run a single scraper source with timeout and error handling."""
    try:
        ScraperClass = SCRAPER_MAP[source]
        kwargs = _build_scraper_kwargs(
            source=source,
            config=payload.config,
            fieldTags=payload.fieldTags,
            maxResults=payload.maxResults,
            add_log=add_log,
        )

        sig = inspect.signature(ScraperClass.__init__)
        valid_params = set(sig.parameters.keys())
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_params}

        scraper = ScraperClass(**filtered_kwargs)
        scraper.source_label = source
        scraper.target_max = payload.maxResults

        add_log("info", f"[{source}] Starting scrape...")

        companies = await asyncio.wait_for(scraper.scrape(), timeout=180.0)
        add_log("success", f"[{source}] Found {len(companies)} companies with email")
        return companies

    except asyncio.TimeoutError:
        add_log("error", f"[{source}] Timed out after 180s")
        return []
    except Exception as e:
        add_log("error", f"[{source}] Failed: {str(e)}")
        return []


@router.post("/extract", response_model=ExtractResponse)
async def extract_data(payload: ExtractPayload):
    """Main extraction endpoint. Runs MULTIPLE sources concurrently and merges results."""
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

    add_log("info", "=== MULTI-SOURCE EXTRACTION REQUEST ===")
    add_log("info", f"Selected source: {payload.source}")
    add_log("info", f"Profession: '{payload.config.profession}'")
    add_log("info", f"Location: '{payload.config.location}'")
    add_log("info", f"Max Results: {payload.maxResults}")
    add_log("info", "Strategy: Multiple platforms concurrently -> merge & deduplicate")

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

    # Build the list of sources to run:
    # Always include reliable defaults + the user-selected source (if different).
    sources_to_run = list(DEFAULT_SOURCES)
    if payload.source not in sources_to_run:
        sources_to_run.insert(0, payload.source)

    # Keep only sources that are actually available
    sources_to_run = [s for s in sources_to_run if s in SCRAPER_MAP]

    add_log("info", f"Will query {len(sources_to_run)} platforms: {', '.join(sources_to_run)}")

    try:
        # Notify SSE that scraping is starting
        try:
            from app.services.extract_progress import set_progress as _sp
            _sp(True, payload.source, "", "", 0, 0, "running")
        except Exception:
            pass

        # Run all sources concurrently
        tasks = [
            _run_single_source(source, payload, add_log)
            for source in sources_to_run
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results from all sources
        all_companies: List[dict] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                add_log("error", f"[{sources_to_run[i]}] Unhandled error: {result}")
            elif isinstance(result, list):
                all_companies.extend(result)
            else:
                add_log("error", f"[{sources_to_run[i]}] Unexpected result type: {type(result)}")

        add_log("info", f"Raw total from all sources: {len(all_companies)}")

        # Cross-source deduplication by (normalized company name, normalized email)
        seen = set()
        unique_companies: List[dict] = []
        for c in all_companies:
            name = (c.get("company_name") or c.get("name") or "").strip().lower()
            email = (c.get("email") or "").strip().lower()
            if not name or not email:
                continue
            key = f"{name}|{email}"
            if key in seen:
                continue
            seen.add(key)
            unique_companies.append(c)

        add_log("info", f"After cross-source deduplication: {len(unique_companies)}")

        # Strict limit to requested maxResults
        if len(unique_companies) > payload.maxResults:
            add_log("info", f"Limiting to exact {payload.maxResults} requested.")
            unique_companies = unique_companies[:payload.maxResults]

        add_log("success", f"Multi-source extraction complete! {len(unique_companies)} companies with email found.")

        # Tell SSE stream the scrape is done.
        try:
            from app.services.extract_progress import set_progress as _sp
            _sp(True, payload.source, "", "", len(unique_companies), 0, "done")
        except Exception:
            pass

        return ExtractResponse(
            success=True,
            companies=unique_companies,
            totalItems=len(unique_companies),
            logs=logs,
        )

    except asyncio.TimeoutError:
        add_log("error", "Global scrape timed out after 10 minutes.")
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
            error="Scrape timed out after 10 minutes. Please try again or reduce the number of results."
        )

    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback_str = traceback.format_exc()
        add_log("error", error_msg)
        add_log("error", f"Traceback: {traceback_str}")
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
            error=error_msg
        )


@router.get("/extract/stream")
async def extract_stream():
    """Server-Sent Events stream of live scraping progress."""
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/extract/stop")
async def extract_stop():
    """Request the currently running scrape to stop and return partial results."""
    request_stop()
    return {"status": "stopped", "message": "Stop signal sent. Scrapers will finish current item and return partial results."}


@router.get("/test-extract")
async def test_extract():
    """Quick test endpoint with fixed params (uses multi-source mode)."""
    import asyncio
    import traceback

    logs = []

    def add_log(type_: str, message: str):
        logs.append({"type": type_, "message": message})
        print(f"[{type_.upper()}] {message}")

    add_log("info", "=== TEST EXTRACTION (MULTI-SOURCE) ===")
    add_log("info", "Profession: Softwareentwickler")
    add_log("info", "Location: Berlin")
    add_log("info", "Max Results: 10")

    try:
        _load_scrapers()

        class FakePayload:
            source = "arbeitsagentur"
            config = ExtractConfig(
                profession="Softwareentwickler",
                location="Berlin",
                locationScope="Ganzer Ort",
                jobType="Ausbildung / Duales Studium",
                date="Heute",
                maxJobs=10,
            )
            fieldTags = ["Softwareentwickler"]
            maxResults = 10

        payload = FakePayload()
        response = await extract_data(payload)
        return {
            "success": response.success,
            "companies": response.companies,
            "totalItems": response.totalItems,
            "logs": response.logs,
            "error": response.error,
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
