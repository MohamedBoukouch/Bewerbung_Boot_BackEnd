"""LinkedIn Scraper - Uses public job/company pages (HTTP + BeautifulSoup).

LinkedIn is heavily bot-protected, so this is a best-effort scraper:
it searches public job listings and pulls the description/company site,
then extracts emails the same way the other platforms do. Companies
without a discoverable email are skipped (matching the app's rule).
"""
import asyncio
import re
import httpx
from typing import List, Optional, Callable
from app.services.scraper_base import BaseScraper

BASE_URL = "https://www.linkedin.com"
SEARCH_URL = f"{BASE_URL}/jobs/search"

DATE_FILTER_MAP = {
    "Alle anzeigen": None,
    "Heute": 1,
    "Letzte Woche": 7,
    "Letzter Monat": 30,
}

JOB_TYPE_MAP = {
    "Vollzeit": "F",
    "Teilzeit": "P",
    "Praktikum": "I",
    "Werkstudent": "I",
    "Ausbildung": "I",
    "Vertrag": "C",
    "Temporär": "T",
}


class LinkedInScraper(BaseScraper):
    def __init__(self, profession: str, location: str = "", location_scope: str = "Ganzer Ort",
                 job_type: str = "Praktikum", date_filter: str = "Heute",
                 max_results: int = 50, field_tags: List[str] = None, log_callback: Optional[Callable] = None):
        super().__init__(profession, location, max_results, field_tags, log_callback)
        self.location_scope = location_scope
        self.job_type = job_type
        self.date_filter = date_filter

    def _headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    def _build_search_params(self, start: int = 0) -> dict:
        params = {"keywords": self.profession, "start": start}
        if self.location and self.location.strip():
            params["location"] = self.location.strip()
        days = DATE_FILTER_MAP.get(self.date_filter)
        if days:
            params["f_TPR"] = f"r{days * 86400}"  # seconds
        jt = JOB_TYPE_MAP.get(self.job_type)
        if jt:
            params["f_JT"] = jt
        return params

    def _parse_search_results(self, html: str) -> List[dict]:
        # LinkedIn job cards carry data-occludable-job-id; links to /jobs/view/<id>
        jobs = []
        # Extract job view ids + company names from the search HTML.
        for m in re.finditer(
            r'data-entity-urn="urn:li:jobPosting:(\d+)"', html
        ):
            job_id = m.group(1)
            # Find the nearest company name before this match.
            seg = html[max(0, m.start() - 1200):m.start()]
            comp = re.findall(r'class="[^"]*companyName[^"]*"[^>]*>([^<]+)<', seg)
            company = re.sub(r'\s+', ' ', comp[-1]).strip() if comp else ""
            jobs.append({"job_id": job_id, "company": company})
        # Fallback: links to /jobs/view/
        if not jobs:
            for m in re.finditer(r'/jobs/view/(\d+)', html):
                jobs.append({"job_id": m.group(1), "company": ""})
        return jobs

    async def _get_job_details(self, client: httpx.AsyncClient, job_id: str):
        url = f"{BASE_URL}/jobs/view/{job_id}"
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
            self.log("info", f"Details exception: {str(e)}")
            return None

    def _extract_company_from_html(self, html: str, fallback: str) -> str:
        m = re.search(r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>([^<]+)<', html)
        if m:
            return re.sub(r'\s+', ' ', m.group(1)).strip()
        m = re.search(r'"companyName":"([^"]+)"', html)
        if m:
            return m.group(1).strip()
        return fallback

    def _extract_city(self, html: str) -> str:
        m = re.search(r'"jobLocation":\[?\{[^}]*?"name":"([^"]+)"', html)
        if m:
            return m.group(1).split(",")[0].strip()
        m = re.search(r'class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>([^<]+)<', html)
        if m:
            return m.group(1).split(",")[0].strip()
        return ""

    def _extract_website(self, html: str) -> str:
        m = re.search(r'"companyUrl":"(https?:[^"]+)"', html)
        if m:
            return m.group(1)
        m = re.search(r'href="(https?://[^"]+)"[^>]*class="[^"]*company[^"]*"', html)
        if m:
            return m.group(1)
        return ""

    async def _process_job(self, client: httpx.AsyncClient, job: dict):
        job_id = job.get("job_id", "")
        if not job_id:
            self.log("info", "Skipping: no job_id")
            return

        employer_name = (job.get("company") or "").strip()
        if not employer_name:
            self.log("info", "Skipping: no company name yet")
            return

        job_title = job.get("title", "")
        city = ""

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
                employer_name = self._extract_company_from_html(html, employer_name) or employer_name
                city = self._extract_city(html)
                employer_website = self._extract_website(html)
                # Description lives in the job posting JSON / sections.
                desc = re.search(r'"description":\s*"(.*?)"(,"|\s*})', html)
                if desc:
                    description = desc.group(1).encode().decode("unicode_escape")
                else:
                    dm = re.search(r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>', html, re.DOTALL)
                    if dm:
                        description = re.sub(r'<[^>]+>', ' ', dm.group(1))
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
        self.log("info", "=== LinkedIn Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")
        self.log("info", "Note: Only companies WITH email will be kept")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            start = 0
            total_fetched = 0
            max_pages = 10

            while total_fetched < self.max_results and start < max_pages * 25:
                params = self._build_search_params(start=start)
                self.log("info", f"GET {SEARCH_URL} | start={start} | keywords={self.profession}")
                try:
                    resp = await client.get(SEARCH_URL, params=params, headers=self._headers(), timeout=15.0)
                    resp.raise_for_status()
                    html = resp.text
                except Exception as e:
                    self.log("error", f"Search error: {str(e)}")
                    break

                jobs = self._parse_search_results(html)
                self.log("info", f"Page start={start}: {len(jobs)} jobs found")

                if not jobs:
                    self.log("info", "No jobs returned.")
                    break

                for job in jobs:
                    if total_fetched >= self.max_results:
                        break
                    await self._process_job(client, job)
                    total_fetched = len(self.companies)

                self.log("info", f"Current companies with email: {total_fetched}")

                if len(jobs) < 25:
                    self.log("info", "Last page reached.")
                    break

                start += 25
                await asyncio.sleep(1.5)

            if start >= max_pages * 25:
                self.log("info", f"Max page limit ({max_pages}) reached.")

        self.log("info", "=== Scraping Complete ===")
        self.log("info", f"Total unique companies with email: {len(self.companies)}")
        return self.get_results()
