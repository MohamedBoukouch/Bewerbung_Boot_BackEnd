"""Indeed Scraper - Uses public job listing pages (no official API available)."""
import asyncio
import re
import httpx
from typing import List, Optional, Callable
from app.services.scraper_base import BaseScraper

BASE_URL = "https://de.indeed.com"
SEARCH_URL = f"{BASE_URL}/jobs"

JOB_TYPE_MAP = {
    "Vollzeit": "fulltime",
    "Teilzeit": "parttime",
    "Praktikum": "internship",
    "Werkstudent": "apprenticeship",
    "Ausbildung": "apprenticeship",
}

DATE_FILTER_MAP = {
    "Alle anzeigen": None,
    "Heute": 1,
    "Letzte 3 Tage": 3,
    "Letzte 7 Tage": 7,
    "Letzte 14 Tage": 14,
    "Letzte 30 Tage": 30,
}

RADIUS_MAP = {
    "Ganzer Ort": None,
    "5 km": 5,
    "10 km": 10,
    "15 km": 15,
    "25 km": 25,
    "50 km": 50,
    "100 km": 100,
}


class IndeedScraper(BaseScraper):
    def __init__(self, profession: str, location: str = "", location_scope: str = "Ganzer Ort",
                 job_type: str = "Ausbildung", date_filter: str = "Heute",
                 max_results: int = 50, field_tags: List[str] = None, log_callback: Optional[Callable] = None):
        super().__init__(profession, location, max_results, field_tags, log_callback)
        self.location_scope = location_scope
        self.job_type = job_type
        self.date_filter = date_filter

    def _headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def _build_search_params(self, start: int = 0) -> dict:
        params = {"q": self.profession, "start": start}
        if self.location and self.location.strip():
            params["l"] = self.location.strip()
            radius = RADIUS_MAP.get(self.location_scope)
            if radius:
                params["radius"] = radius
        job_code = JOB_TYPE_MAP.get(self.job_type)
        if job_code:
            params["jt"] = job_code
        days = DATE_FILTER_MAP.get(self.date_filter)
        if days:
            params["fromage"] = days
        return params

    def _extract_job_id(self, href: str) -> str:
        match = re.search(r"jk=([a-zA-Z0-9]+)", href)
        if match:
            return match.group(1)
        match = re.search(r"/viewjob\?jk=([a-zA-Z0-9]+)", href)
        if match:
            return match.group(1)
        return ""

    def _parse_search_results(self, html: str) -> List[dict]:
        jobs = []
        cards = re.findall(
            r'<div[^>]*class="[^"]*job_seen_beacon[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
            html, re.DOTALL
        )

        if not cards:
            cards = re.findall(
                r'<div[^>]*class="[^"]*slider_container[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
                html, re.DOTALL
            )

        for card in cards:
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)

        return jobs

    def _parse_job_card(self, card_html: str) -> dict:
        job = {}

        company_match = re.search(r'class="companyName"[^>]*>(.*?)</span>', card_html)
        if company_match:
            job["company"] = re.sub(r'<[^>]+>', '', company_match.group(1)).strip()
        else:
            company_match = re.search(r'class="company"[^>]*>(.*?)</span>', card_html)
            if company_match:
                job["company"] = re.sub(r'<[^>]+>', '', company_match.group(1)).strip()

        title_match = re.search(r'class="jobTitle"[^>]*>\s*<a[^>]*title="([^"]+)"', card_html)
        if title_match:
            job["title"] = title_match.group(1)
        else:
            title_match = re.search(r'class="jobTitle"[^>]*>(.*?)</span>', card_html)
            if title_match:
                job["title"] = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

        loc_match = re.search(r'class="companyLocation"[^>]*>(.*?)</div>', card_html)
        if loc_match:
            job["location"] = re.sub(r'<[^>]+>', '', loc_match.group(1)).strip()
        else:
            loc_match = re.search(r'class="location"[^>]*>(.*?)</div>', card_html)
            if loc_match:
                job["location"] = re.sub(r'<[^>]+>', '', loc_match.group(1)).strip()

        href_match = re.search(r'href="(/viewjob\?jk=[^"]+)"', card_html)
        if href_match:
            job["job_id"] = self._extract_job_id(href_match.group(1))

        if job.get("company") and job.get("job_id"):
            return job
        return None

    async def _search_jobs(self, client: httpx.AsyncClient, start: int = 0) -> List[dict]:
        params = self._build_search_params(start=start)
        self.log("info", f"GET {SEARCH_URL} | start={start} | q={self.profession}")
        try:
            resp = await client.get(SEARCH_URL, params=params, headers=self._headers(), timeout=15.0)
            resp.raise_for_status()
            html = resp.text
            jobs = self._parse_search_results(html)
            self.log("success", f"Page start={start}: {len(jobs)} jobs found")
            return jobs
        except httpx.HTTPStatusError as e:
            self.log("error", f"HTTP {e.response.status_code}: {e.response.text[:300]}")
            return []
        except Exception as e:
            self.log("error", f"Search exception: {type(e).__name__}: {str(e)}")
            return []

    async def _get_job_details(self, client: httpx.AsyncClient, job_id: str):
        url = f"{BASE_URL}/viewjob?jk={job_id}"
        try:
            resp = await client.get(url, headers=self._headers(), timeout=10.0)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                self.log("info", f"Details 404 for job {job_id}")
            else:
                self.log("error", f"Details HTTP {e.response.status_code}")
            return None
        except Exception as e:
            self.log("error", f"Details exception: {str(e)}")
            return None

    def _extract_description_from_html(self, html: str) -> str:
        desc_match = re.search(
            r'<div[^>]*id="jobDescriptionText"[^>]*>(.*?)</div>\s*(?:<div|<script|$)',
            html, re.DOTALL
        )
        if desc_match:
            desc = desc_match.group(1)
            desc = re.sub(r'<[^>]+>', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            return desc
        return ""

    def _extract_company_website_from_html(self, html: str) -> str:
        website_match = re.search(r'href="(https?://[^"]+)"[^>]*class="[^"]*company[^"]*"', html)
        if website_match:
            return website_match.group(1)
        apply_match = re.search(r'href="(https?://[^"]+)"[^>]*class="[^"]*apply[^"]*"', html)
        if apply_match:
            return apply_match.group(1)
        return ""

    def _get_city_from_location(self, location: str) -> str:
        if not location:
            return ""
        parts = location.split(",")
        return parts[0].strip()

    async def _process_job(self, client: httpx.AsyncClient, job: dict):
        job_id = job.get("job_id", "")
        if not job_id:
            self.log("info", "Skipping: no job_id")
            return

        employer_name = job.get("company", "")
        if not employer_name or not isinstance(employer_name, str):
            self.log("info", "Skipping: invalid company name")
            return

        job_title = job.get("title", "")
        location = job.get("location", "")
        city = self._get_city_from_location(location)

        dedup = self._dedup_key(employer_name, city)
        if dedup in self.seen_companies:
            self.log("info", f"Skipping duplicate: {employer_name}")
            return
        self.seen_companies.add(dedup)

        description = ""
        employer_website = ""

        try:
            html = await asyncio.wait_for(
                self._get_job_details(client, job_id),
                timeout=8.0
            )

            if html:
                description = self._extract_description_from_html(html)
                employer_website = self._extract_company_website_from_html(html)
        except asyncio.TimeoutError:
            self.log("info", f"Detail timeout for {job_id}")
        except Exception as e:
            self.log("info", f"Detail error: {str(e)}")

        email = self._extract_email(description)
        phone = self._extract_phone(description)
        website = self._extract_website(description) or employer_website

        self.log("info", f"Company '{employer_name}': email='{email}'")

        self._add_company(employer_name, email, city, website, phone, job_title)

    async def scrape(self) -> List[dict]:
        self.log("info", "=== Indeed Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")
        self.log("info", "Note: Only companies WITH email will be kept")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            start = 0
            total_fetched = 0
            max_pages = 10

            while total_fetched < self.max_results and start < max_pages * 10:
                jobs = await self._search_jobs(client, start=start)

                if not jobs:
                    self.log("info", "No jobs returned from page.")
                    break

                self.log("info", f"Processing {len(jobs)} jobs from start={start}...")

                for job in jobs:
                    if total_fetched >= self.max_results:
                        break
                    await self._process_job(client, job)
                    total_fetched = len(self.companies)

                self.log("info", f"Current companies with email: {total_fetched}")

                if len(jobs) < 10:
                    self.log("info", f"Last page reached ({len(jobs)} < 10).")
                    break

                start += 10
                await asyncio.sleep(1.5)

            if start >= max_pages * 10:
                self.log("info", f"Max page limit ({max_pages}) reached.")

        self.log("info", "=== Scraping Complete ===")
        self.log("info", f"Total unique companies with email: {len(self.companies)}")
        return self.get_results()