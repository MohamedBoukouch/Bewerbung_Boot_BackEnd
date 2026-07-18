"""
AubiPlus Scraper v2 - Fixed to reach exact target limit
https://www.aubi-plus.de

Strategy: Process job links page by page, keep going until target_max reached.
Email is MANDATORY. If no email on offer page, visits company website.
"""
import asyncio
import re
from typing import List, Optional, Callable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.services.scraper_base import BaseScraper
from app.services.contact_finder import find_email_on_company_website, extract_emails_from_html

POSTAL_CITY_RE = re.compile(r"\b\d{5}\s+([A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\-\. ]{1,40})")


class AubiPlusScraper(BaseScraper):
    BASE_URL = "https://www.aubi-plus.de"
    SEARCH_PATH = "/aktuelle-ausbildungsplaetze/"

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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }

    def _build_search_url(self, page: int = 1) -> str:
        params = [f"s={self.profession.replace(' ', '+')}"]
        if self.location and self.location.strip():
            params.append(f"mSuggest={self.location.strip().replace(' ', '+')}")
        params.append(f"seite={page}")
        query = "&".join(params)
        return f"{self.BASE_URL}{self.SEARCH_PATH}?{query}"

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
            if any(seg in href for seg in ("/ausbildung/", "/stellenangebot/", "/ausbildungsplatz/", "/job/", "/stelle/")):
                full = urljoin(self.BASE_URL, href)
                if full not in seen and full != f"{self.BASE_URL}/" and full.startswith(self.BASE_URL):
                    seen.add(full)
                    links.append(full)

        if not links:
            self.log("error", "No job links found. AubiPlus site markup may have changed.")
        else:
            self.log("info", f"Found {len(links)} job links on this page.")
        return links

    def _parse_detail(self, html: str, detail_url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")

        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

        company_name = ""
        # Try multiple selectors for company name
        for sel in [".company-name", ".arbeitgeber", "[data-testid='company-name']", ".firmenname", ".unternehmen"]:
            el = soup.select_one(sel)
            if el:
                company_name = el.get_text(strip=True)
                if company_name:
                    break

        # Fallback: look for links to company pages
        if not company_name:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/premium/" in href or "/unternehmen/" in href or "/firma/" in href or "/arbeitgeber/" in href:
                    company_name = a.get_text(strip=True)
                    if company_name:
                        break

        # Fallback: regex from text
        if not company_name:
            full_text = soup.get_text(" ", strip=True)
            m = re.search(r"\bbei\s+([A-ZÄÖÜ][\w&.-\s]{2,60})", full_text)
            if m:
                company_name = m.group(1).strip()

        city = ""
        full_text = soup.get_text(" ", strip=True)
        m = POSTAL_CITY_RE.search(full_text)
        if m:
            city = m.group(1).strip()

        company_website = ""
        excluded_domains = ("aubi-plus.de", "facebook.com", "instagram.com", "linkedin.com",
                            "tiktok.com", "youtube.com", "twitter.com", "x.com", "whatsapp.com")
        candidates = soup.find_all("a", href=True)
        for a in candidates:
            href = a["href"]
            if href.startswith(("mailto:", "tel:", "#", "javascript:")):
                continue
            if not href.startswith("http"):
                continue
            if any(dom in href for dom in excluded_domains):
                continue
            link_text = a.get_text(strip=True).lower()
            if "website" in link_text or "webseite" in link_text or "homepage" in link_text or "zur webseite" in link_text:
                company_website = href
                break
        if not company_website:
            for a in candidates:
                href = a["href"]
                if href.startswith("http") and not any(dom in href for dom in excluded_domains):
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

        job = self._parse_detail(detail_html, link)

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
            self.log("info", f"DISCARDED '{job['name']}': no email found (offer + website tried)")
            return False

        self._add_company(job["name"], email, job["city"], job["website"], job["phone"], job["title"])
        return True

    async def scrape(self) -> List[dict]:
        self.log("info", "=== AubiPlus Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Target: {self.target_max} companies with email")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")
        self.log("info", "Will keep fetching pages until target is reached or no more results.")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            max_pages = 20  # Increased - keep going until we hit target or run out
            consecutive_empty = 0
            max_consecutive_empty = 3

            while not self._should_stop() and page <= max_pages and consecutive_empty < max_consecutive_empty:
                url = self._build_search_url(page)
                self.log("info", f"Fetching AubiPlus page {page}: {url}")
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

                # Process each link sequentially (safer for rate limiting)
                for link in links:
                    if self._should_stop():
                        self.log("info", f"Reached target limit ({self.target_max}). Stopping.")
                        break

                    await self._process_job(client, link)

                    # Small delay between requests
                    await asyncio.sleep(0.2)

                self.log("info", f"After page {page}: {len(self.companies)}/{self.target_max} companies")

                # Check if we got fewer links than expected (last page indicator)
                if len(links) < 10:
                    self.log("info", f"Fewer than 10 job links ({len(links)}) -- likely last page, but will check next.")

                page += 1
                await asyncio.sleep(0.5)

            if page > max_pages:
                self.log("info", f"Max page limit ({max_pages}) reached.")
            if consecutive_empty >= max_consecutive_empty:
                self.log("info", f"Stopped after {max_consecutive_empty} consecutive empty pages.")

        self.log("info", "=== AubiPlus Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)} (target was {self.target_max})")
        return self.get_results()