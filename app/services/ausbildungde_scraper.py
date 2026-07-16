"""Ausbildung.de Scraper - HTML scraping."""
import asyncio
import httpx
from bs4 import BeautifulSoup
from typing import List, Optional, Callable
from app.services.scraper_base import BaseScraper


class AusbildungDeScraper(BaseScraper):
    BASE_URL = "https://www.ausbildung.de"

    def __init__(self, profession: str, location: str = "", max_results: int = 50,
                 field_tags: List[str] = None, log_callback: Optional[Callable] = None):
        super().__init__(profession, location, max_results, field_tags, log_callback)

    def _headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }

    def _build_search_url(self, page: int = 1) -> str:
        params = []
        if self.profession:
            params.append(f"q={self.profession.replace(' ', '+')}")
        if self.location:
            params.append(f"ort={self.location.replace(' ', '+')}")
        params.append(f"page={page}")
        query = "&".join(params)
        return f"{self.BASE_URL}/suche/?{query}"

    async def _fetch_page(self, client: httpx.AsyncClient, page: int) -> str:
        url = self._build_search_url(page)
        self.log("info", f"Fetching Ausbildung.de page {page}: {url}")
        try:
            resp = await client.get(url, headers=self._headers(), timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            self.log("error", f"HTTP {e.response.status_code} on Ausbildung.de")
            return ""
        except Exception as e:
            self.log("error", f"Ausbildung.de fetch error: {str(e)}")
            return ""

    def _parse_jobs(self, html: str) -> List[dict]:
        soup = BeautifulSoup(html, "html.parser")
        jobs = []

        selectors = [
            "[data-testid='job-card']", ".job-card", ".ausbildungsplatz",
            ".search-result-item", "article", ".card", ".result-item", ".stellenangebot",
        ]

        cards = []
        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                self.log("info", f"Found {len(cards)} cards with selector: {selector}")
                break

        if not cards:
            cards = soup.find_all("div", class_=lambda x: x and ("job" in x.lower() or "card" in x.lower() or "result" in x.lower() or "stelle" in x.lower() or "platz" in x.lower()))
            self.log("info", f"Fallback: found {len(cards)} potential cards")

        for card in cards[:self.max_results]:
            job = self._parse_card(card)
            if job:
                jobs.append(job)

        return jobs

    def _parse_card(self, card) -> Optional[dict]:
        try:
            name = ""
            for sel in [".company-name", ".arbeitgeber", "h3", "h2", ".title", "[data-testid='company-name']", ".firmenname", ".unternehmen"]:
                el = card.select_one(sel)
                if el:
                    name = el.get_text(strip=True)
                    break

            title = ""
            for sel in [".job-title", ".stellenangebotsTitel", "h3", "h2", ".title", "[data-testid='job-title']", ".beruf", ".ausbildungsberuf"]:
                el = card.select_one(sel)
                if el:
                    title = el.get_text(strip=True)
                    break

            city = ""
            for sel in [".location", ".ort", ".city", "[data-testid='location']", ".standort", ".einsatzort"]:
                el = card.select_one(sel)
                if el:
                    city = el.get_text(strip=True)
                    break

            link = ""
            a = card.find("a", href=True)
            if a:
                link = a["href"]
                if link.startswith("/"):
                    link = f"{self.BASE_URL}{link}"

            text = card.get_text(separator=" ", strip=True)
            email = self._extract_email(text)
            phone = self._extract_phone(text)
            website = self._extract_website(text)

            if name:
                return {"name": name, "title": title, "city": city, "email": email, "phone": phone, "website": website, "link": link}
        except Exception as e:
            self.log("error", f"Parse card error: {str(e)}")
        return None

    async def _fetch_detail(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url, headers=self._headers(), timeout=15.0, follow_redirects=True)
            return resp.text
        except:
            return ""

    async def scrape(self) -> List[dict]:
        self.log("info", "=== Ausbildung.de Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            page = 1
            while len(self.companies) < self.max_results:
                html = await self._fetch_page(client, page)
                if not html:
                    break

                jobs = self._parse_jobs(html)
                if not jobs:
                    self.log("info", "No jobs found on this page.")
                    break

                self.log("info", f"Processing {len(jobs)} jobs from page {page}...")

                for job in jobs:
                    if len(self.companies) >= self.max_results:
                        break

                    if job.get("link"):
                        detail_html = await self._fetch_detail(client, job["link"])
                        if detail_html:
                            detail_text = BeautifulSoup(detail_html, "html.parser").get_text(separator=" ", strip=True)
                            email = self._extract_email(detail_text) or job.get("email", "")
                            phone = self._extract_phone(detail_text) or job.get("phone", "")
                            website = self._extract_website(detail_text) or job.get("website", "")
                        else:
                            email = job.get("email", "")
                            phone = job.get("phone", "")
                            website = job.get("website", "")
                    else:
                        email = job.get("email", "")
                        phone = job.get("phone", "")
                        website = job.get("website", "")

                    self._add_company(job["name"], email, job.get("city", ""), website, phone, job.get("title", ""))

                if len(jobs) < 10:
                    break

                page += 1
                await asyncio.sleep(1.0)

        self.log("info", "=== Ausbildung.de Scraping Complete ===")
        self.log("info", f"Total companies: {len(self.companies)}")
        return self.get_results()