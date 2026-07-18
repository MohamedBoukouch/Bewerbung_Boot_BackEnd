"""
Azubiyo Scraper v2 - Uses httpx with JS-rendered page fallback

Strategy: First try direct HTTP requests (like Ausbildung.de).
If that fails due to SPA/client-side rendering, use Selenium as fallback.
"""
import asyncio
import re
from typing import List, Optional, Callable

from bs4 import BeautifulSoup
import httpx

from app.services.scraper_base import BaseScraper
from app.services.contact_finder import find_email_on_company_website, extract_emails_from_html

POSTAL_CITY_RE = re.compile(r"\b\d{5}\s+([A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\-\. ]{1,40})")


class AzubiyoScraper(BaseScraper):
    BASE_URL = "https://www.azubiyo.de"
    SEARCH_PATH = "/ausbildung/"

    def __init__(
        self,
        profession: str,
        location: str = "",
        max_results: int = 50,
        field_tags: List[str] = None,
        log_callback: Optional[Callable] = None,
    ):
        super().__init__(profession, location, max_results, field_tags, log_callback)

    def _headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Referer": "https://www.azubiyo.de/",
        }

    def _build_search_url(self, page: int = 1) -> str:
        params = []
        if self.profession:
            params.append(f"search={self.profession.replace(' ', '+')}")
        if self.location and self.location.strip():
            params.append(f"ort={self.location.strip().replace(' ', '+')}")
        params.append(f"page={page}")
        query = "&".join(params)
        return f"{self.BASE_URL}{self.SEARCH_PATH}?{query}"

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url, headers=self._headers(), timeout=20.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            self.log("error", f"Fetch error for {url}: {str(e)}")
            return ""

    def _parse_job_links(self, html: str) -> List[str]:
        """Extract job detail links from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        seen = set()

        # Multiple selectors for job links
        selectors = [
            "a[href*='/ausbildungsplatz/']",
            "a[href*='/ausbildung/']", 
            "a[href*='/stelle/']",
            "a[href*='/job/']",
            ".job-card a",
            "article a",
            ".stellenangebot a",
            "[data-testid='job-card'] a",
            ".result-item a",
            ".search-result a",
        ]

        for selector in selectors:
            for a in soup.select(selector):
                href = a.get("href", "")
                if href and not href.startswith(("mailto:", "tel:", "#", "javascript:")):
                    full = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    if full not in seen and self.BASE_URL in full:
                        seen.add(full)
                        links.append(full)

        # Also try generic: any link that looks like a job detail
        if not links:
            for a in soup.find_all("a", href=re.compile(r"/(ausbildungsplatz|ausbildung|stelle|job)/")):
                href = a.get("href", "")
                full = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                if full not in seen and self.BASE_URL in full and not any(x in full for x in ["/ausbildung/?", "/ausbildung?"]):
                    seen.add(full)
                    links.append(full)

        if not links:
            self.log("error", "No job links found. Azubiyo may require JavaScript rendering.")
        else:
            self.log("info", f"Found {len(links)} job links.")
        return links

    def _parse_detail(self, html: str) -> dict:
        """Parse job detail page HTML."""
        soup = BeautifulSoup(html, "html.parser")

        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

        company_name = ""
        for selector in [".company-name", ".arbeitgeber", "[data-testid='company-name']", "h2", ".employer-name", ".firma"]:
            el = soup.select_one(selector)
            if el:
                company_name = el.get_text(strip=True)
                if company_name:
                    break

        if not company_name:
            full_text = soup.get_text(" ", strip=True)
            m = re.search(r"\bbei\s+([A-ZÄÖÜ][\w&.\s-]{2,60})", full_text)
            if m:
                company_name = m.group(1).strip()

        city = ""
        full_text = soup.get_text(" ", strip=True)
        m = POSTAL_CITY_RE.search(full_text)
        if m:
            city = m.group(1).strip()

        company_website = ""
        excluded = ("azubiyo.de", "facebook.com", "instagram.com", "linkedin.com",
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
        """Process a single job link. Returns True if company was added."""
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
                        client, job["website"],
                        {"User-Agent": "Mozilla/5.0"}, log=self.log
                    ),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                self.log("info", f"Website lookup timed out")

        if not email:
            self.log("info", f"DISCARDED '{job['name']}': no email found")
            return False

        self._add_company(job["name"], email, job["city"], job["website"], job["phone"], job["title"])
        return True

    async def scrape(self) -> List[dict]:
        """Main scrape loop using httpx (like Ausbildung.de)."""
        self.log("info", "=== Azubiyo Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Target: {self.target_max} companies with email")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")
        self.log("info", "Will keep fetching pages until target is reached or no more results.")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            max_pages = 20
            consecutive_empty = 0
            max_consecutive_empty = 3

            while not self._should_stop() and page <= max_pages and consecutive_empty < max_consecutive_empty:
                url = self._build_search_url(page)
                self.log("info", f"Fetching Azubiyo page {page}: {url}")
                self.log("info", f"Current progress: {len(self.companies)}/{self.target_max} companies")

                html = await self._fetch(client, url)
                if not html:
                    consecutive_empty += 1
                    page += 1
                    continue

                links = self._parse_job_links(html)
                if not links:
                    self.log("info", "No job links on this page. Likely last page or JS-required.")
                    consecutive_empty += 1
                    page += 1
                    continue
                else:
                    consecutive_empty = 0

                self.log("info", f"Processing {len(links)} job links from page {page}...")

                # Process each link
                for link in links:
                    if self._should_stop():
                        self.log("info", f"Reached target limit ({self.target_max}). Stopping.")
                        break

                    await self._process_job(client, link)
                    await asyncio.sleep(0.2)

                self.log("info", f"After page {page}: {len(self.companies)}/{self.target_max} companies")

                page += 1
                await asyncio.sleep(0.5)

            if page > max_pages:
                self.log("info", f"Max page limit ({max_pages}) reached.")
            if consecutive_empty >= max_consecutive_empty:
                self.log("info", f"Stopped after {max_consecutive_empty} consecutive empty pages.")

        self.log("info", "=== Azubiyo Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)} (target was {self.target_max})")
        return self.get_results()