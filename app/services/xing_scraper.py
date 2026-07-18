"""Xing Scraper - HTML scraping."""
import asyncio
import httpx
from bs4 import BeautifulSoup
from typing import List, Optional, Callable
from urllib.parse import urljoin

from app.services.scraper_base import BaseScraper
from app.services.contact_finder import find_email_on_company_website, extract_emails_from_html


class XingScraper(BaseScraper):
    BASE_URL = "https://www.xing.com"

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
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }

    def _build_search_url(self, page: int = 1) -> str:
        params = [f"keywords={self.profession.replace(' ', '%20')}"]
        if self.location and self.location.strip():
            params.append(f"location={self.location.strip().replace(' ', '%20')}")

        # Job type mapping
        job_type_map = {
            "Vollzeit": "FULL_TIME",
            "Teilzeit": "PART_TIME",
            "Praktikum": "INTERN",
            "Werkstudent": "WORKING_STUDENT",
            "Ausbildung": "TRAINEE",
            "Freelance": "FREELANCE",
        }
        if self.job_type in job_type_map:
            params.append(f"employmentType={job_type_map[self.job_type]}")

        params.append(f"page={page}")
        query = "&".join(params)
        return f"{self.BASE_URL}/jobs/search?{query}"

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url, headers=self._headers(), timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            self.log("error", f"Fetch error for {url}: {str(e)}")
            return ""

    def _parse_job_links(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/jobs/" in href and href != "/jobs/":
                full = urljoin(self.BASE_URL, href)
                if full not in seen:
                    seen.add(full)
                    links.append(full)

        if not links:
            self.log("error", "No job links found. Xing markup may have changed.")
        else:
            self.log("info", f"Found {len(links)} job links on page.")
        return links

    def _parse_detail(self, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")

        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

        company_name = ""
        for sel in ["[data-testid='company-name']", ".company-name", ".organization-name"]:
            el = soup.select_one(sel)
            if el:
                company_name = el.get_text(strip=True)
                break

        if not company_name:
            full_text = soup.get_text(" ", strip=True)
            m = re.search(r"\bbei\s+([A-ZÄÖÜ][\w&.\s-]{2,60})", full_text)
            if m:
                company_name = m.group(1).strip()

        city = ""
        full_text = soup.get_text(" ", strip=True)
        m = re.search(r"\b\d{5}\s+([A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\-\. ]{1,40})", full_text)
        if m:
            city = m.group(1).strip()

        company_website = ""
        excluded = ("xing.com", "facebook.com", "instagram.com", "linkedin.com",
                    "tiktok.com", "youtube.com", "twitter.com", "x.com")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and not any(d in href for d in excluded):
                company_website = href
                break

        page_emails = extract_emails_from_html(html)
        direct_email = page_emails[0] if page_emails else ""
        phone = self._extract_phone(full_text)

        return {
            "name": company_name or "",
            "title": title,
            "city": city,
            "website": company_website,
            "phone": phone,
            "email": direct_email,
        }

    async def _process_job(self, client: httpx.AsyncClient, link: str) -> bool:
        if self._should_stop():
            return False

        detail_html = await self._fetch(client, link)
        if not detail_html:
            return False

        job = self._parse_detail(detail_html)

        if not job["name"]:
            self.log("info", f"Skipping (no company name): {link}")
            return False

        self._set_current(job["name"], job["website"])

        email = job["email"]

        if not email and job["website"]:
            self.log("info", f"No email on offer for '{job['name']}', checking website {job['website']}...")
            try:
                email = await asyncio.wait_for(
                    find_email_on_company_website(
                        client, job["website"], self._headers(), log=self.log
                    ),
                    timeout=8.0,
                )
            except asyncio.TimeoutError:
                self.log("info", f"Website lookup timed out for '{job['name']}'")

        if not email:
            self.log("info", f"DISCARDED '{job['name']}': no email found")
            return False

        self._add_company(job["name"], email, job["city"], job["website"], job["phone"], job["title"])
        return True

    async def scrape(self) -> List[dict]:
        self.log("info", "=== Xing Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Target: {self.target_max} companies with email")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")
        self.log("info", "Will keep fetching pages until target is reached or no more results.")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            max_pages = 10
            consecutive_empty = 0

            while not self._should_stop() and page <= max_pages and consecutive_empty < 3:
                url = self._build_search_url(page)
                self.log("info", f"Fetching Xing page {page}: {url}")
                self.log("info", f"Current progress: {len(self.companies)}/{self.target_max} companies")

                html = await self._fetch(client, url)
                if not html:
                    consecutive_empty += 1
                    page += 1
                    continue

                links = self._parse_job_links(html)
                if not links:
                    self.log("info", "No job links on this page. Likely last page.")
                    consecutive_empty += 1
                    page += 1
                    continue
                else:
                    consecutive_empty = 0

                self.log("info", f"Processing {len(links)} job links from page {page}...")

                for link in links:
                    if self._should_stop():
                        self.log("info", f"Reached target limit ({self.target_max}). Stopping.")
                        break

                    await self._process_job(client, link)
                    await asyncio.sleep(0.2)

                self.log("info", f"After page {page}: {len(self.companies)}/{self.target_max} companies")

                if len(links) < 20:
                    break

                page += 1
                await asyncio.sleep(0.5)

            if page > max_pages:
                self.log("info", f"Max page limit ({max_pages}) reached.")

        self.log("info", "=== Xing Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)} (target was {self.target_max})")
        return self.get_results()