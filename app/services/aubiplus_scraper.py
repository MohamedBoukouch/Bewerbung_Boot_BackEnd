"""
AubiPlus Scraper - HTML scraping
https://www.aubi-plus.de

Email is MANDATORY. If no email on the offer page, visits the company
website and extracts from Impressum/Kontakt. Companies without email
are DISCARDED.
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
                if full not in seen and full != f"{self.BASE_URL}/":
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
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/premium/" in href or "/unternehmen/" in href or "/firma/" in href:
                company_name = a.get_text(strip=True)
                if company_name:
                    break

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
            if "website" in link_text or "webseite" in link_text or "homepage" in link_text:
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

    async def _process_job(self, client: httpx.AsyncClient, link: str) -> Optional[dict]:
        # HARD STOP check
        if self._should_stop():
            return None

        detail_html = await self._fetch(client, link)
        if not detail_html:
            return None

        job = self._parse_detail(detail_html, link)

        if not job["name"]:
            self.log("info", f"Skipping (no company name): {link}")
            return None

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
            return None

        self._add_company(job["name"], email, job["city"], job["website"], job["phone"], job["title"])
        return {"done": True}

    async def scrape(self) -> List[dict]:
        self.log("info", "=== AubiPlus Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            max_pages = 5
            all_links: List[str] = []

            while len(all_links) < self.target_max * 3 and page <= max_pages:
                # HARD STOP check
                if self._should_stop():
                    break

                url = self._build_search_url(page)
                self.log("info", f"Fetching AubiPlus page {page}: {url}")
                html = await self._fetch(client, url)
                if not html:
                    break

                links = self._parse_job_links(html)
                if not links:
                    break

                all_links.extend(links)

                if len(links) < 5:
                    self.log("info", "Fewer than 5 job links -- likely last page.")
                    break

                page += 1
                await asyncio.sleep(0.3)

            if not all_links:
                self.log("info", "No job links found. Scraping complete.")
                return self.get_results()

            self.log("info", f"Total job links found: {len(all_links)}. Fetching details concurrently...")

            semaphore = asyncio.Semaphore(8)
            async def limited_process(link: str) -> Optional[dict]:
                async with semaphore:
                    if self._should_stop():
                        return None
                    return await self._process_job(client, link)

            tasks = [limited_process(link) for link in all_links[:self.target_max * 3]]
            await asyncio.gather(*tasks, return_exceptions=True)

        self.log("info", "=== AubiPlus Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)}")
        return self.get_results()