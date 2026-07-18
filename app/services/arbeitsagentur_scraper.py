"""Arbeitsagentur Scraper - Uses official API."""
import asyncio
import base64
import httpx
from typing import List, Optional, Callable
from app.services.scraper_base import BaseScraper
from app.services.contact_finder import find_email_on_company_website

API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
API_KEY = "jobboerse-jobsuche"

JOB_TYPE_MAP = {
    "Arbeit": 1,
    "Ausbildung / Duales Studium": 4,
    "Praktikum / Trainee / Werkstudent": 34,
    "Selbst\u00e4ndigkeit": 2,
}

DATE_FILTER_MAP = {
    "Alle anzeigen": None,
    "Heute": 1,
    "Gestern": 2,
    "1 Woche": 7,
    "2 Wochen": 14,
    "4 Wochen": 28,
}

RADIUS_MAP = {
    "Ganzer Ort": None,
    "10 km": 10,
    "15 km": 15,
    "25 km": 25,
    "50 km": 50,
    "100 km": 100,
    "200 km": 200,
}


class ArbeitsagenturScraper(BaseScraper):
    def __init__(self, profession: str, location: str = "", location_scope: str = "Ganzer Ort",
                 job_type: str = "Ausbildung / Duales Studium", date_filter: str = "Heute",
                 max_results: int = 50, field_tags: List[str] = None, log_callback: Optional[Callable] = None):
        super().__init__(profession, location, max_results, field_tags, log_callback)
        self.location_scope = location_scope
        self.job_type = job_type
        self.date_filter = date_filter

    def _headers(self):
        return {
            "X-API-Key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def _build_search_params(self, page: int = 1, size: int = 25) -> dict:
        params = {"was": self.profession, "page": page, "size": min(size, 100)}
        job_code = JOB_TYPE_MAP.get(self.job_type, 4)
        params["angebotsart"] = job_code
        if self.location and self.location.strip():
            params["wo"] = self.location.strip()
            radius = RADIUS_MAP.get(self.location_scope)
            if radius:
                params["umkreis"] = radius
        days = DATE_FILTER_MAP.get(self.date_filter)
        if days:
            params["veroeffentlichtseit"] = days
        return params

    async def _search_jobs(self, client: httpx.AsyncClient, page: int = 1) -> List[dict]:
        params = self._build_search_params(page=page)
        url = f"{API_BASE}/pc/v6/jobs"
        self.log("info", f"GET {url} | page={page} | was={self.profession}")
        try:
            resp = await client.get(url, params=params, headers=self._headers(), timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            self.log("info", f"Response keys: {list(data.keys())}")
            if "maxErgebnisse" in data:
                self.log("info", f"Total results available: {data['maxErgebnisse']}")
            jobs = data.get("ergebnisliste", [])
            if not isinstance(jobs, list):
                self.log("error", f"ergebnisliste is not a list! Type: {type(jobs)}")
                return []
            self.log("success", f"Page {page}: {len(jobs)} jobs found")
            return jobs
        except httpx.HTTPStatusError as e:
            self.log("error", f"HTTP {e.response.status_code}: {e.response.text[:300]}")
            return []
        except Exception as e:
            self.log("error", f"Search exception: {type(e).__name__}: {str(e)}")
            return []

    async def _get_job_details(self, client: httpx.AsyncClient, referenznummer: str):
        encoded_ref = base64.b64encode(referenznummer.encode()).decode()
        url = f"{API_BASE}/pc/v4/jobdetails/{encoded_ref}"
        try:
            resp = await client.get(url, headers=self._headers(), timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                self.log("info", f"Details 404 for {referenznummer[:30]}...")
            else:
                self.log("error", f"Details HTTP {e.response.status_code}")
            return None
        except Exception as e:
            self.log("error", f"Details exception: {str(e)}")
            return None

    def _get_city_from_job(self, job: dict) -> str:
        stellenlokationen = job.get("stellenlokationen", [])
        if isinstance(stellenlokationen, list) and len(stellenlokationen) > 0:
            first_loc = stellenlokationen[0]
            if isinstance(first_loc, dict):
                adresse = first_loc.get("adresse", {})
                if isinstance(adresse, dict):
                    ort = adresse.get("ort", "")
                    if ort:
                        return ort
        return job.get("ort", "") or job.get("einsatzort", "") or ""

    async def _process_job(self, client: httpx.AsyncClient, job: dict):
        # HARD STOP check
        if self._should_stop():
            return

        referenznummer = job.get("referenznummer", "")
        if not referenznummer:
            self.log("info", "Skipping: no referenznummer")
            return

        employer_name = job.get("firma", "")

        if not employer_name or not isinstance(employer_name, str):
            self.log("info", f"Skipping: invalid firma")
            return

        job_title = (
            job.get("stellenangebotsTitel", "")
            or job.get("beruf", "")
            or job.get("titel", "")
            or ""
        )

        city = self._get_city_from_job(job)

        # Try to get details with timeout
        description = ""
        employer_website = ""

        try:
            details = await asyncio.wait_for(
                self._get_job_details(client, referenznummer),
                timeout=5.0
            )

            if details and isinstance(details, dict):
                description = (
                    details.get("stellenangebotsBeschreibung", "")
                    or details.get("stellenbeschreibung", "")
                    or details.get("beschreibung", "")
                    or ""
                )
                ag = details.get("arbeitgeber", {})
                if isinstance(ag, dict):
                    employer_website = ag.get("homepage", "")
                if not employer_website:
                    employer_website = details.get("arbeitgeberHomepage", "")
                if not employer_website:
                    employer_website = details.get("homepage", "")
                if not employer_website:
                    employer_website = details.get("externeUrl", "")

            # Announce current company so the frontend can show its logo + name
            self._set_current(employer_name, employer_website if employer_website else "")

        except asyncio.TimeoutError:
            self.log("info", f"Detail timeout for {referenznummer[:20]}")
        except Exception as e:
            self.log("info", f"Detail error: {str(e)}")

        email = self._extract_email(description)
        phone = self._extract_phone(description)
        website = self._extract_website(description) or employer_website

        self.log("info", f"Company '{employer_name}': email='{email}'")

        if not email and employer_website:
            self.log("info", f"No email in description for '{employer_name}', checking website {employer_website}...")
            try:
                email = await asyncio.wait_for(
                    find_email_on_company_website(
                        client, employer_website, self._headers(), log=self.log
                    ),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                self.log("info", f"Website lookup timed out for '{employer_name}'")

        # Use _add_company which handles dedup and limit
        self._add_company(employer_name, email, city, website, phone, job_title)

    async def scrape(self) -> List[dict]:
        self.log("info", "=== Arbeitsagentur Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Target: {self.target_max} companies with email")
        self.log("info", "Will keep fetching pages until target is reached or no more results.")
        self._progress()

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            total_fetched = 0
            max_pages = 20  # Increased to find enough emails
            consecutive_empty = 0

            while not self._should_stop() and page <= max_pages and consecutive_empty < 3:
                jobs = await self._search_jobs(client, page=page)
                self.pages_fetched = page

                if not jobs:
                    self.log("info", "No jobs returned from API.")
                    consecutive_empty += 1
                    page += 1
                    continue
                else:
                    consecutive_empty = 0

                self.log("info", f"Processing {len(jobs)} jobs from page {page}...")
                self.log("info", f"Current progress: {len(self.companies)}/{self.target_max} companies")

                # Process jobs sequentially
                for job in jobs:
                    if self._should_stop():
                        self.log("info", f"Reached target limit ({self.target_max}). Stopping.")
                        break
                    await self._process_job(client, job)
                    total_fetched = len(self.companies)

                self.log("info", f"After page {page}: {len(self.companies)}/{self.target_max} companies")

                if len(jobs) < 25:
                    self.log("info", f"Last page reached ({len(jobs)} < 25).")
                    break

                page += 1
                await asyncio.sleep(0.3)

            if page > max_pages:
                self.log("info", f"Max page limit ({max_pages}) reached.")

        self.log("info", "=== Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)} (target was {self.target_max})")
        return self.get_results()