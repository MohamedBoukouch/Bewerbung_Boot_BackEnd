"""Xing Scraper - Uses public job search pages (no official public API for search)."""
import asyncio
import re
import httpx
from typing import List, Optional, Callable
from app.services.scraper_base import BaseScraper

BASE_URL = "https://www.xing.com"
SEARCH_URL = f"{BASE_URL}/jobs/search"

JOB_TYPE_MAP = {
    "Vollzeit": "FULL_TIME",
    "Teilzeit": "PART_TIME",
    "Praktikum": "INTERNSHIP",
    "Werkstudent": "WORKING_STUDENT",
    "Ausbildung": "APPRENTICESHIP",
    "Freelance": "FREELANCE",
}

DATE_FILTER_MAP = {
    "Alle anzeigen": None,
    "Heute": "1",
    "Letzte 3 Tage": "3",
    "Letzte Woche": "7",
    "Letzte 2 Wochen": "14",
    "Letzter Monat": "30",
}

RADIUS_MAP = {
    "Ganzer Ort": None,
    "5 km": "5",
    "10 km": "10",
    "25 km": "25",
    "50 km": "50",
    "100 km": "100",
}


class XingScraper(BaseScraper):
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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
        }

    def _build_search_params(self, page: int = 1) -> dict:
        params = {"query": self.profession}
        if self.location and self.location.strip():
            params["location"] = self.location.strip()
            radius = RADIUS_MAP.get(self.location_scope)
            if radius:
                params["radius"] = radius
        job_code = JOB_TYPE_MAP.get(self.job_type)
        if job_code:
            params["employment_type"] = job_code
        days = DATE_FILTER_MAP.get(self.date_filter)
        if days:
            params["published_since"] = days
        params["page"] = page
        return params

    def _parse_search_results(self, html: str) -> List[dict]:
        jobs = []
        cards = re.findall(
            r'<article[^>]*data-testid="job-search-result"[^>]*>(.*?)</article>',
            html, re.DOTALL
        )

        if not cards:
            cards = re.findall(
                r'<div[^>]*class="[^"]*job-card[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
                html, re.DOTALL
            )

        if not cards:
            cards = re.findall(
                r'<li[^>]*class="[^"]*job-search-result[^"]*"[^>]*>(.*?)</li>',
                html, re.DOTALL
            )

        for card in cards:
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)

        return jobs

    def _parse_job_card(self, card_html: str) -> dict:
        job = {}

        href_match = re.search(r'href="(/jobs/[^"]+)"', card_html)
        if href_match:
            job["job_path"] = href_match.group(1)
            job_id_match = re.search(r'/jobs/([a-zA-Z0-9_-]+)', job["job_path"])
            if job_id_match:
                job["job_id"] = job_id_match.group(1)

        company_match = re.search(r'class="[^"]*company-name[^"]*"[^>]*>(.*?)</span>', card_html)
        if company_match:
            job["company"] = re.sub(r'<[^>]+>', '', company_match.group(1)).strip()
        else:
            company_match = re.search(r'class="[^"]*employer[^"]*"[^>]*>(.*?)</span>', card_html)
            if company_match:
                job["company"] = re.sub(r'<[^>]+>', '', company_match.group(1)).strip()

        title_match = re.search(r'class="[^"]*job-title[^"]*"[^>]*>(.*?)</span>', card_html)
        if title_match:
            job["title"] = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        else:
            title_match = re.search(r'<a[^>]*href="/jobs/[^"]*"[^>]*>(.*?)</a>', card_html)
            if title_match:
                job["title"] = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

        loc_match = re.search(r'class="[^"]*location[^"]*"[^>]*>(.*?)</span>', card_html)
        if loc_match:
            job["location"] = re.sub(r'<[^>]+>', '', loc_match.group(1)).strip()
        else:
            loc_match = re.search(r'class="[^"]*job-location[^"]*"[^>]*>(.*?)</span>', card_html)
            if loc_match:
                job["location"] = re.sub(r'<[^>]+>', '', loc_match.group(1)).strip()

        if job.get("company") and job.get("job_id"):
            return job
        return None

    async def _search_jobs(self, client: httpx.AsyncClient, page: int = 1) -> List[dict]:
        params = self._build_search_params(page=page)
        self.log("info", f"GET {SEARCH_URL} | page={page} | query={self.profession}")
        try:
            resp = await client.get(SEARCH_URL, params=params, headers=self._headers(), timeout=15.0)
            resp.raise_for_status()
            html = resp.text
            jobs = self._parse_search_results(html)
            self.log("success", f"Page {page}: {len(jobs)} jobs found")
            return jobs
        except httpx.HTTPStatusError as e:
            self.log("error", f"HTTP {e.response.status_code}: {e.response.text[:300]}")
            return []
        except Exception as e:
            self.log("error", f"Search exception: {type(e).__name__}: {str(e)}")
            return []

    async def _get_job_details(self, client: httpx.AsyncClient, job_path: str):
        url = f"{BASE_URL}{job_path}"
        try:
            resp = await client.get(url, headers=self._headers(), timeout=10.0)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                self.log("info", f"Details 404 for {job_path}")
            else:
                self.log("error", f"Details HTTP {e.response.status_code}")
            return None
        except Exception as e:
            self.log("error", f"Details exception: {str(e)}")
            return None

    def _extract_description_from_html(self, html: str) -> str:
        desc_match = re.search(
            r'<div[^>]*class="[^"]*job-description[^"]*"[^>]*>(.*?)</div>\s*(?:<div|<section|<script|$)',
            html, re.DOTALL
        )
        if desc_match:
            desc = desc_match.group(1)
            desc = re.sub(r'<[^>]+>', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            return desc

        desc_match = re.search(
            r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>',
            html, re.DOTALL
        )
        if desc_match:
            desc = desc_match.group(1)
            desc = re.sub(r'<[^>]+>', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            return desc

        return ""

    def _extract_company_website_from_html(self, html: str) -> str:
        website_match = re.search(r'href="(https?://[^"]+)"[^>]*class="[^"]*company-website[^"]*"', html)
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
        job_path = job.get("job_path", "")
        if not job_path:
            self.log("info", "Skipping: no job_path")
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
                self._get_job_details(client, job_path),
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
        self.log("info", "=== Xing Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")
        self.log("info", "Note: Only companies WITH email will be kept")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            total_fetched = 0
            max_pages = 10

            while total_fetched < self.max_results and page <= max_pages:
                jobs = await self._search_jobs(client, page=page)

                if not jobs:
                    self.log("info", "No jobs returned from page.")
                    break

                self.log("info", f"Processing {len(jobs)} jobs from page {page}...")

                for job in jobs:
                    if total_fetched >= self.max_results:
                        break
                    await self._process_job(client, job)
                    total_fetched = len(self.companies)

                self.log("info", f"Current companies with email: {total_fetched}")

                if len(jobs) < 20:
                    self.log("info", f"Last page reached ({len(jobs)} < 20).")
                    break

                page += 1
                await asyncio.sleep(2.0)

            if page > max_pages:
                self.log("info", f"Max page limit ({max_pages}) reached.")

        self.log("info", "=== Scraping Complete ===")
        self.log("info", f"Total unique companies with email: {len(self.companies)}")
        return self.get_results()