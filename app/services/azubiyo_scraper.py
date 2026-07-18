"""Azubiyo Scraper using Selenium for SPA rendering"""
import asyncio
import re
from typing import List, Optional, Callable

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup

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

    def _build_search_url(self, page: int = 1) -> str:
        params = []
        if self.profession:
            params.append(f"search={self.profession.replace(' ', '+')}")
        if self.location and self.location.strip():
            params.append(f"ort={self.location.strip().replace(' ', '+')}")
        params.append(f"page={page}")
        query = "&".join(params)
        return f"{self.BASE_URL}{self.SEARCH_PATH}?{query}"

    def _create_driver(self):
        """Create headless Chrome driver."""
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        try:
            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
        except Exception as e:
            self.log("error", f"Failed to create Chrome driver: {e}")
            # Try with webdriver-manager if chromedriver not found
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
                return driver
            except:
                raise

    def _fetch_with_selenium(self, url: str) -> str:
        """Fetch page with Selenium and return rendered HTML."""
        driver = None
        try:
            driver = self._create_driver()
            driver.get(url)
            
            # Wait for Angular/Vue to render content
            # Look for job cards or "no results" message
            wait = WebDriverWait(driver, 15)
            try:
                # Wait for either job listings or no-results message
                wait.until(lambda d: 
                    len(d.find_elements(By.CSS_SELECTOR, "[data-testid='job-card'], .job-card, .stellenangebot, article, .card")) > 0
                    or "keine Stellen" in d.page_source
                    or "0 Berufe" in d.page_source
                )
            except:
                pass  # Timeout, return what we have
            
            # Scroll to load lazy content
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            asyncio.run(asyncio.sleep(2))  # Wait for lazy load
            
            html = driver.page_source
            return html
            
        finally:
            if driver:
                driver.quit()

    def _parse_job_links(self, html: str) -> List[str]:
        """Extract job detail links from rendered HTML."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        seen = set()
        
        # Multiple possible selectors for job cards
        selectors = [
            "a[href*='/ausbildungsplatz/']",
            "a[href*='/ausbildung/']",
            "a[href*='/stelle/']",
            ".job-card a", 
            "article a",
            ".stellenangebot a",
            "[data-testid='job-card'] a",
        ]
        
        for selector in selectors:
            for a in soup.select(selector):
                href = a.get("href", "")
                if href and not href.startswith(("mailto:", "tel:", "#")):
                    full = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    if full not in seen:
                        seen.add(full)
                        links.append(full)
        
        if not links:
            self.log("error", "No job links found. Azubiyo SPA may have changed structure.")
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
        # Try multiple selectors
        for selector in [".company-name", ".arbeitgeber", "[data-testid='company-name']", "h2"]:
            el = soup.select_one(selector)
            if el:
                company_name = el.get_text(strip=True)
                break
        
        if not company_name:
            full_text = soup.get_text(" ", strip=True)
            m = re.search(r"\bbei\s+([A-ZÄÖÜ][\w&.\-\s]{2,60})", full_text)
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

    async def scrape(self) -> List[dict]:
        """Main scrape loop using Selenium for SPA rendering."""
        self.log("info", "=== Azubiyo Scraping Start (Selenium SPA) ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")

        page = 1
        max_pages = 3  # Limit pages to avoid long Selenium sessions

        while len(self.companies) < self.max_results and page <= max_pages:
            url = self._build_search_url(page)
            self.log("info", f"Fetching Azubiyo page {page} with Selenium: {url}")
            
            # Run Selenium in thread pool since it's blocking
            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(None, self._fetch_with_selenium, url)
            
            if not html:
                break

            job_links = self._parse_job_links(html)
            if not job_links:
                break

            for link in job_links:
                if len(self.companies) >= self.max_results:
                    break

                # Fetch detail page with Selenium
                detail_html = await loop.run_in_executor(None, self._fetch_with_selenium, link)
                if not detail_html:
                    continue

                job = self._parse_detail(detail_html)

                if not job["name"]:
                    self.log("info", f"Skipping (no company name): {link}")
                    continue

                dedup = self._dedup_key(job["name"], job["city"])
                if dedup in self.seen_companies:
                    self.log("info", f"Skipping duplicate: {job['name']}")
                    continue
                self.seen_companies.add(dedup)

                email = job["email"]

                # Try website if no email on offer page
                if not email and job["website"]:
                    self.log("info", f"No email on offer for '{job['name']}', checking website...")
                    # Use httpx for website (faster than Selenium)
                    import httpx
                    async with httpx.AsyncClient(follow_redirects=True) as client:
                        try:
                            email = await asyncio.wait_for(
                                find_email_on_company_website(
                                    client, job["website"], 
                                    {"User-Agent": "Mozilla/5.0"}, log=self.log
                                ),
                                timeout=15.0,
                            )
                        except asyncio.TimeoutError:
                            self.log("info", f"Website lookup timed out")

                if not email:
                    self.log("info", f"DISCARDED '{job['name']}': no email found")
                    continue

                if self._is_already_extracted(email):
                    self.log("info", f"SKIPPING '{job['name']}': email '{email}' already extracted previously")
                    continue

                self.log("info", f"KEPT '{job['name']}': email='{email}'")

                self.companies.append({
                    "company_name": job["name"],
                    "email": email,
                    "city": job["city"],
                    "website": job["website"],
                    "phone": job["phone"],
                    "job_title": job["title"],
                    "field": self.profession,
                    "source": "azubiyo",
                })

            self.log("info", f"Current companies with email: {len(self.companies)}")
            page += 1

        self.log("info", "=== Azubiyo Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)}")
        return self.get_results()