"""LinkedIn Scraper - HTML scraping."""
import asyncio
import httpx
from bs4 import BeautifulSoup
from typing import List, Optional, Callable
from urllib.parse import urljoin

from app.services.scraper_base import BaseScraper
from app.services.contact_finder import find_email_on_company_website, extract_emails_from_html


class LinkedInScraper(BaseScraper):
    BASE_URL = "https://www.linkedin.com"

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
        }

    def _build_search_url(self, page: int = 1) -> str:
        params = [f"keywords={self.profession.replace(' ', '%20')}"]
        if self.location and self.location.strip():
            params.append(f"location={self.location.strip().replace(' ', '%20')}")

        # Job type mapping (LinkedIn uses f_* parameters)
        job_type_map = {
            "Vollzeit": "f_JT=F",
            "Teilzeit": "f_JT=P",
            "Praktikum": "f_JT=I",
            "Werkstudent": "f_JT=C",
            "Ausbildung": "f_JT=A",
            "Vertrag": "f_JT=C",
            "Temporär": "f_JT=T",
        }
        if self.job_type in job_type_map:
            params.append(job_type_map[self.job_type])

        params.append(f"start={(page-1)*25}")
        query = "&".join(params)
        return f"{self.BASE_URL}/jobs/search/?{query}"

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
            if "/jobs/view/" in href:
                full = urljoin(self.BASE_URL, href)
                if full not in seen:
                    seen.add(full)
                    links.append(full)

        if not links:
            self.log("error", "No job links found. LinkedIn may require login or markup changed.")
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
        for sel in ["[data-testid='company-name']", ".company-name", ".topcard__org-name-link"]:
            el = soup.select_one(sel)
            if el:
                company_name = el.get_text(strip=True)
                break

        if not company_name:
            full_text = soup.get_text(" ", strip=True)
            m = re.search(r"\bbei\s+([A-ZÄÖÜ][\w&.-\s]{2,60})", full_text)
            if m:
                company_name = m.group(1).strip()

        city = ""
        full_text = soup.get_text(" ", strip=True)
        m = re.search(r"\b\d{5}\s+([A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\-\. ]{1,40})", full_text)
        if m:
            city = m.group(1).strip()

        company_website = ""
        excluded = ("linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com")
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

    async def _process_job(self, client: httpx.AsyncClient, link: str) -> Optional[dict]:
        if self._should_stop():
            return None

        detail_html = await self._fetch(client, link)
        if not detail_html:
            return None

        job = self._parse_detail(detail_html)

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
            self.log("info", f"DISCARDED '{job['name']}': no email found")
            return None

        self._add_company(job["name"], email, job["city"], job["website"], job["phone"], job["title"])
        return {"done": True}

    async def scrape(self) -> List[dict]:
        self.log("info", "=== LinkedIn Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")
        self.log("info", "WARNING: LinkedIn often blocks scrapers. Results may be limited.")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            max_pages = 3  # LinkedIn is more aggressive with blocking

            while page <= max_pages:
                if self._should_stop():
                    break

                url = self._build_search_url(page)
                self.log("info", f"Fetching LinkedIn page {page}: {url}")
                html = await self._fetch(client, url)
                if not html:
                    break

                links = self._parse_job_links(html)
                if not links:
                    break

                semaphore = asyncio.Semaphore(4)  # Lower concurrency for LinkedIn
                async def limited_process(link: str) -> Optional[dict]:
                    async with semaphore:
                        if self._should_stop():
                            return None
                        return await self._process_job(client, link)

                tasks = [limited_process(link) for link in links[:self.target_max]]
                await asyncio.gather(*tasks, return_exceptions=True)

                if len(links) < 25:
                    self.log("info", "Fewer than 25 job links -- likely last page.")
                    break

                page += 1
                await asyncio.sleep(1.0)  # Slower for LinkedIn

        self.log("info", "=== LinkedIn Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)}")
        return self.get_results()