"""Azubica Scraper v2 - Scrapes regional Ausbildungsatlas pages

Azubica.de is a regional Ausbildungsatlas platform (PDF magazine), NOT a searchable job board.
Strategy: Scrape regional atlas pages for company listings, then find emails via company websites.
"""
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
import httpx

from app.services.scraper_base import BaseScraper
from app.services.contact_finder import find_email_on_company_website, extract_emails_from_html

POSTAL_CITY_RE = re.compile(r"\b\d{5}\s+([A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\-\. ]{1,40})")


class AzubicaScraper(BaseScraper):
    BASE_URL = "https://www.azubica.de"

    # Regional atlas URL slugs (city -> slug)
    REGION_MAP = {
        "berlin": "ausbildungsatlas-berlin",
        "hamburg": "ausbildungsatlas-hamburg",
        "münchen": "ausbildungsatlas-muenchen",
        "muenchen": "ausbildungsatlas-muenchen",
        "köln": "ausbildungsatlas-koeln",
        "koeln": "ausbildungsatlas-koeln",
        "frankfurt": "ausbildungsatlas-frankfurt",
        "stuttgart": "ausbildungsatlas-stuttgart",
        "düsseldorf": "ausbildungsatlas-duesseldorf",
        "duesseldorf": "ausbildungsatlas-duesseldorf",
        "dortmund": "ausbildungsatlas-dortmund",
        "essen": "ausbildungsatlas-essen",
        "leipzig": "ausbildungsatlas-leipzig",
        "bremen": "ausbildungsatlas-bremen",
        "dresden": "ausbildungsatlas-dresden",
        "hannover": "ausbildungsatlas-hannover",
        "nürnberg": "ausbildungsatlas-nuernberg",
        "nuernberg": "ausbildungsatlas-nuernberg",
        "duisburg": "ausbildungsatlas-duisburg",
        "bochum": "ausbildungsatlas-bochum",
        "wuppertal": "ausbildungsatlas-wuppertal",
        "bielefeld": "ausbildungsatlas-bielefeld",
        "bonn": "ausbildungsatlas-bonn",
        "mannheim": "ausbildungsatlas-mannheim",
        "karlsruhe": "ausbildungsatlas-karlsruhe",
        "wiesbaden": "ausbildungsatlas-wiesbaden",
        "münster": "ausbildungsatlas-muenster",
        "muenster": "ausbildungsatlas-muenster",
        "augsburg": "ausbildungsatlas-augsburg",
        "gelsenkirchen": "ausbildungsatlas-gelsenkirchen",
        "aachen": "ausbildungsatlas-aachen",
        "krefeld": "ausbildungsatlas-krefeld",
        "oberhausen": "ausbildungsatlas-oberhausen",
        "lübeck": "ausbildungsatlas-luebeck",
        "luebeck": "ausbildungsatlas-luebeck",
        "braunschweig": "ausbildungsatlas-braunschweig",
        "kiel": "ausbildungsatlas-kiel",
        "chemnitz": "ausbildungsatlas-chemnitz",
        "mainz": "ausbildungsatlas-mainz",
        "magdeburg": "ausbildungsatlas-magdeburg",
        "freiburg": "ausbildungsatlas-freiburg",
        "erfurt": "ausbildungsatlas-erfurt",
        "kassel": "ausbildungsatlas-kassel",
        "halle": "ausbildungsatlas-halle",
        "saarbrücken": "ausbildungsatlas-saarbruecken",
        "saarbruecken": "ausbildungsatlas-saarbruecken",
        "mönchengladbach": "ausbildungsatlas-moenchengladbach",
        "moenchengladbach": "ausbildungsatlas-moenchengladbach",
        "rostock": "ausbildungsatlas-rostock",
        "potsdam": "ausbildungsatlas-potsdam",
        "regensburg": "ausbildungsatlas-regensburg",
        "würzburg": "ausbildungsatlas-wuerzburg",
        "wuerzburg": "ausbildungsatlas-wuerzburg",
        "heidelberg": "ausbildungsatlas-heidelberg",
        "darmstadt": "ausbildungsatlas-darmstadt",
        "ingolstadt": "ausbildungsatlas-ingolstadt",
        "solingen": "ausbildungsatlas-solingen",
        "zwickau": "ausbildungsatlas-zwickau",
        "ulm": "ausbildungsatlas-ulm",
        "cottbus": "ausbildungsatlas-cottbus",
        "salzgitter": "ausbildungsatlas-salzgitter",
        "pforzheim": "ausbildungsatlas-pforzheim",
        "göttingen": "ausbildungsatlas-goettingen",
        "goettingen": "ausbildungsatlas-goettingen",
        "offenbach": "ausbildungsatlas-offenbach",
        "reutlingen": "ausbildungsatlas-reutlingen",
        "koblenz": "ausbildungsatlas-koblenz",
        "siegen": "ausbildungsatlas-siegen",
        "trier": "ausbildungsatlas-trier",
        "hildesheim": "ausbildungsatlas-hildesheim",
        "jena": "ausbildungsatlas-jena",
        "bremerhaven": "ausbildungsatlas-bremerhaven",
        "erlangen": "ausbildungsatlas-erlangen",
        "witten": "ausbildungsatlas-witten",
        "ratingen": "ausbildungsatlas-ratingen",
        "bergisch gladbach": "ausbildungsatlas-bergisch-gladbach",
        "neuss": "ausbildungsatlas-neuss",
        "moers": "ausbildungsatlas-moers",
        "marl": "ausbildungsatlas-marl",
        "bergheim": "ausbildungsatlas-bergheim",
        "wesel": "ausbildungsatlas-wesel",
        "hattingen": "ausbildungsatlas-hattingen",
        "herne": "ausbildungsatlas-herne",
        "herten": "ausbildungsatlas-herten",
        "recklinghausen": "ausbildungsatlas-recklinghausen",
        "castrop-rauxel": "ausbildungsatlas-castrop-rauxel",
        "gütersloh": "ausbildungsatlas-guetersloh",
        "guetersloh": "ausbildungsatlas-guetersloh",
        "iserlohn": "ausbildungsatlas-iserlohn",
        "lünen": "ausbildungsatlas-luenen",
        "luenen": "ausbildungsatlas-luenen",
        "unna": "ausbildungsatlas-unna",
        "menden": "ausbildungsatlas-menden",
        "lippstadt": "ausbildungsatlas-lippstadt",
        "soest": "ausbildungsatlas-soest",
        "warendorf": "ausbildungsatlas-warendorf",
        "ahlen": "ausbildungsatlas-ahlen",
        "beckum": "ausbildungsatlas-beckum",
        "rheda-wiedenbrück": "ausbildungsatlas-rheda-wiedenbrueck",
        "rheda-wiedenbrueck": "ausbildungsatlas-rheda-wiedenbrueck",
        "herford": "ausbildungsatlas-herford",
        "bad salzuflen": "ausbildungsatlas-bad-salzuflen",
        "lemgo": "ausbildungsatlas-lemgo",
        "detmold": "ausbildungsatlas-detmold",
        "paderborn": "ausbildungsatlas-paderborn",
        "büren": "ausbildungsatlas-bueren",
        "bueren": "ausbildungsatlas-bueren",
        "brilon": "ausbildungsatlas-brilon",
        "marsberg": "ausbildungsatlas-marsberg",
        "warburg": "ausbildungsatlas-warburg",
        "hoexter": "ausbildungsatlas-hoexter",
        "holzminden": "ausbildungsatlas-holzminden",
        "bodenwerder": "ausbildungsatlas-bodenwerder",
        "bad pyrmont": "ausbildungsatlas-bad-pyrmont",
        "hameln": "ausbildungsatlas-hameln",
        "springe": "ausbildungsatlas-springe",
        "bad harzburg": "ausbildungsatlas-bad-harzburg",
        "goslar": "ausbildungsatlas-goslar",
        "wernigerode": "ausbildungsatlas-wernigerode",
        "halberstadt": "ausbildungsatlas-halberstadt",
        "quedlinburg": "ausbildungsatlas-quedlinburg",
        "blankenburg": "ausbildungsatlas-blankenburg",
        "osterode": "ausbildungsatlas-osterode",
        "northeim": "ausbildungsatlas-northeim",
        "einbeck": "ausbildungsatlas-einbeck",
        "nordenham": "ausbildungsatlas-nordenham",
        "wilhelmshaven": "ausbildungsatlas-wilhelmshaven",
        "aurich": "ausbildungsatlas-aurich",
        "emden": "ausbildungsatlas-emden",
        "leer": "ausbildungsatlas-leer",
        "papenburg": "ausbildungsatlas-papenburg",
        "meppen": "ausbildungsatlas-meppen",
        "lingen": "ausbildungsatlas-lingen",
        "cloppenburg": "ausbildungsatlas-cloppenburg",
        "vechta": "ausbildungsatlas-vechta",
        "oldenburg": "ausbildungsatlas-oldenburg",
        "delmenhorst": "ausbildungsatlas-delmenhorst",
        "norden": "ausbildungsatlas-norden",
        "esens": "ausbildungsatlas-esens",
        "wittmund": "ausbildungsatlas-wittmund",
        "jever": "ausbildungsatlas-jever",
        "varel": "ausbildungsatlas-varel",
        "brake": "ausbildungsatlas-brake",
        "elsfleth": "ausbildungsatlas-elsfleth",
        "nordhorn": "ausbildungsatlas-nordhorn",
        "melle": "ausbildungsatlas-melle",
        "osnabrück": "ausbildungsatlas-osnabrueck",
        "osnabrueck": "ausbildungsatlas-osnabrueck",
        "georgsmarienhütte": "ausbildungsatlas-georgsmarienhuette",
        "georgsmarienhuette": "ausbildungsatlas-georgsmarienhuette",
        "münsterland": "ausbildungsatlas-muensterland",
        "muensterland": "ausbildungsatlas-muensterland",
        "steinfurt": "ausbildungsatlas-steinfurt",
        "coesfeld": "ausbildungsatlas-coesfeld",
        "borken": "ausbildungsatlas-borken",
        "ahaus": "ausbildungsatlas-ahaus",
        "kleve": "ausbildungsatlas-kleve",
        "viersen": "ausbildungsatlas-viersen",
        "grevenbroich": "ausbildungsatlas-grevenbroich",
        "kaarst": "ausbildungsatlas-kaarst",
        "willich": "ausbildungsatlas-willich",
        "tönisvorst": "ausbildungsatlas-toenisvorst",
        "toenisvorst": "ausbildungsatlas-toenisvorst",
        "kempen": "ausbildungsatlas-kempen",
        "netetal": "ausbildungsatlas-netetal",
        "brüggen": "ausbildungsatlas-brueggen",
        "brueggen": "ausbildungsatlas-brueggen",
        "schwalmtal": "ausbildungsatlas-schwalmtal",
        "niederkrüchten": "ausbildungsatlas-niederkruechten",
        "niederkruechten": "ausbildungsatlas-niederkruechten",
        "erkrath": "ausbildungsatlas-erkrath",
        "haan": "ausbildungsatlas-haan",
        "heiligenhaus": "ausbildungsatlas-heiligenhaus",
        "velbert": "ausbildungsatlas-velbert",
        "mettmann": "ausbildungsatlas-mettmann",
        "wülfrath": "ausbildungsatlas-wuelfrath",
        "wuelfrath": "ausbildungsatlas-wuelfrath",
        "hilden": "ausbildungsatlas-hilden",
        "langenfeld": "ausbildungsatlas-langenfeld",
        "monheim": "ausbildungsatlas-monheim",
        "leichlingen": "ausbildungsatlas-leichlingen",
        "burscheid": "ausbildungsatlas-burscheid",
        "odenthal": "ausbildungsatlas-odenthal",
        "kürten": "ausbildungsatlas-kuerten",
        "kuerten": "ausbildungsatlas-kuerten",
        "engelskirchen": "ausbildungsatlas-engelskirchen",
        "overath": "ausbildungsatlas-overath",
        "rösrath": "ausbildungsatlas-roesrath",
        "roesrath": "ausbildungsatlas-roesrath",
        "troisdorf": "ausbildungsatlas-troisdorf",
        "sankt augustin": "ausbildungsatlas-sankt-augustin",
        "siegburg": "ausbildungsatlas-siegburg",
        "hürth": "ausbildungsatlas-huerth",
        "huerth": "ausbildungsatlas-huerth",
        "brühl": "ausbildungsatlas-bruehl",
        "bruehl": "ausbildungsatlas-bruehl",
        "wesseling": "ausbildungsatlas-wesseling",
        "bornheim": "ausbildungsatlas-bornheim",
        "alsdorf": "ausbildungsatlas-alsdorf",
        "baesweiler": "ausbildungsatlas-baesweiler",
        "eschweiler": "ausbildungsatlas-eschweiler",
        "stolberg": "ausbildungsatlas-stolberg",
        "würselen": "ausbildungsatlas-wuerselen",
        "wuerselen": "ausbildungsatlas-wuerselen",
        "herzogenrath": "ausbildungsatlas-herzogenrath",
        "simmerath": "ausbildungsatlas-simmerath",
        "monschau": "ausbildungsatlas-monschau",
        "roetgen": "ausbildungsatlas-roetgen",
        "langerwehe": "ausbildungsatlas-langerwehe",
        "nideggen": "ausbildungsatlas-nideggen",
        "heimbach": "ausbildungsatlas-heimbach",
        "titz": "ausbildungsatlas-titz",
        "jülich": "ausbildungsatlas-juelich",
        "juelich": "ausbildungsatlas-juelich",
        "linnich": "ausbildungsatlas-linnich",
        "aldenhoven": "ausbildungsatlas-aldenhoven",
        "inden": "ausbildungsatlas-inden",
        "dueren": "ausbildungsatlas-dueren",
        "nörvenich": "ausbildungsatlas-noervenich",
        "noervenich": "ausbildungsatlas-noervenich",
        "merzenich": "ausbildungsatlas-merzenich",
        "büsdorf": "ausbildungsatlas-buesdorf",
        "buesdorf": "ausbildungsatlas-buesdorf",
        "mechernich": "ausbildungsatlas-mechernich",
        "bad münstereifel": "ausbildungsatlas-bad-muenstereifel",
        "bad-muenstereifel": "ausbildungsatlas-bad-muenstereifel",
        "nettersheim": "ausbildungsatlas-nettersheim",
        "blankenheim": "ausbildungsatlas-blankenheim",
        "dahlem": "ausbildungsatlas-dahlem",
        "kall": "ausbildungsatlas-kall",
        "hellenthal": "ausbildungsatlas-hellenthal",
        "schleiden": "ausbildungsatlas-schleiden",
        "gemünd": "ausbildungsatlas-gemuend",
        "gemuend": "ausbildungsatlas-gemuend",
        "vettweiß": "ausbildungsatlas-vettweiss",
        "vettweiss": "ausbildungsatlas-vettweiss",
    }

    def __init__(
        self,
        profession: str,
        location: str = "",
        max_results: int = 50,
        field_tags: List[str] = None,
        log_callback: Optional[Callable] = None,
    ):
        super().__init__(profession, location, max_results, field_tags, log_callback)

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

            wait = WebDriverWait(driver, 15)
            try:
                wait.until(lambda d: len(d.find_elements(By.TAG_NAME, "body")) > 0)
            except:
                pass

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            asyncio.run(asyncio.sleep(2))

            return driver.page_source

        finally:
            if driver:
                driver.quit()

    def _get_atlas_urls(self) -> List[str]:
        """Build list of regional atlas URLs to scrape."""
        urls = []

        if self.location:
            loc = self.location.strip().lower()
            # Exact match
            if loc in self.REGION_MAP:
                slug = self.REGION_MAP[loc]
                urls.append(f"{self.BASE_URL}/{slug}/")
            else:
                # Partial match
                for key, slug in self.REGION_MAP.items():
                    if loc in key or key in loc:
                        urls.append(f"{self.BASE_URL}/{slug}/")
                        break

                if not urls:
                    self.log("info", f"No regional atlas found for '{self.location}', trying main page...")
                    urls.append(f"{self.BASE_URL}/")
        else:
            self.log("info", "No location specified, scraping main page...")
            urls.append(f"{self.BASE_URL}/")

        return urls

    def _parse_companies_from_atlas(self, html: str) -> List[dict]:
        """Extract company data from atlas page HTML."""
        soup = BeautifulSoup(html, "html.parser")
        companies = []

        # Azubica pages have company listings in various formats
        # Try to find company containers
        selectors = [
            ".company", ".company-item", ".employer", ".employer-item",
            ".ausbildungsbetrieb", ".betrieb", ".firmen-entry",
            "[class*='company']", "[class*='employer']", "[class*='firmen']",
            "[class*='ausbildungs']", ".card", ".item", ".entry",
            "article", "section",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                self.log("info", f"Found {len(elements)} elements with selector '{selector}'")
                for el in elements:
                    company = self._extract_company_from_element(el)
                    if company and company.get("name"):
                        companies.append(company)
                if companies:
                    break

        # Fallback: extract from all external links
        if not companies:
            self.log("info", "No structured data found, trying link extraction...")
            companies = self._extract_companies_from_links(soup)

        return companies

    def _extract_company_from_element(self, el) -> Optional[dict]:
        """Extract company data from a single HTML element."""
        name = ""
        website = ""
        email = ""
        city = ""

        # Try to find company name
        for tag in ["h2", "h3", "h4", "h5", ".name", ".title", ".company-name", "strong", "b"]:
            name_el = el.select_one(tag) if hasattr(el, 'select_one') else None
            if name_el:
                name = name_el.get_text(strip=True)
                break

        if not name:
            text = el.get_text(" ", strip=True) if hasattr(el, 'get_text') else ""
            name = text.split("\n")[0][:100]

        # Try to find website
        for a in el.find_all("a", href=True) if hasattr(el, 'find_all') else []:
            href = a["href"]
            if href.startswith("http") and "azubica.de" not in href:
                website = href
                break

        # Try to find email
        text = el.get_text(" ", strip=True) if hasattr(el, 'get_text') else ""
        emails = extract_emails_from_html(str(el))
        if emails:
            email = emails[0]

        # Try to find city
        m = POSTAL_CITY_RE.search(text)
        if m:
            city = m.group(1).strip()

        if name and len(name) > 2:
            return {
                "name": name,
                "website": website,
                "email": email,
                "city": city,
                "title": "",
                "phone": self._extract_phone(text),
            }
        return None

    def _extract_companies_from_links(self, soup) -> List[dict]:
        """Fallback: extract companies from all external links."""
        companies = []
        seen = set()

        excluded = ("azubica.de", "facebook.com", "instagram.com", "linkedin.com",
                    "tiktok.com", "youtube.com", "twitter.com", "x.com", "google.com",
                    "bing.com", "yahoo.com", "wikipedia.org", "amazon.", "ebay.")

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)

            if not href.startswith("http") or any(d in href for d in excluded):
                continue

            domain = href.split("/")[2].replace("www.", "").split(".")[0]
            name = text if text and len(text) > 2 else domain.replace("-", " ").title()

            if name.lower() in seen:
                continue
            seen.add(name.lower())

            companies.append({
                "name": name,
                "website": href,
                "email": "",
                "city": "",
                "title": "",
                "phone": "",
            })

        return companies

    async def scrape(self) -> List[dict]:
        """Main scrape loop for Azubica regional atlases."""
        self.log("info", "=== Azubica Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Max results: {self.max_results}")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")
        self.log("info", "NOTE: Azubica is a regional Ausbildungsatlas (PDF magazine), not a job board.")

        atlas_urls = self._get_atlas_urls()
        self.log("info", f"Will scrape {len(atlas_urls)} atlas page(s): {atlas_urls}")

        for url in atlas_urls:
            if len(self.companies) >= self.max_results:
                break

            self.log("info", f"Fetching Azubica atlas: {url}")

            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(None, self._fetch_with_selenium, url)

            if not html:
                self.log("error", f"Failed to fetch {url}")
                continue

            companies = self._parse_companies_from_atlas(html)
            self.log("info", f"Found {len(companies)} potential companies on page")

            for job in companies:
                if len(self.companies) >= self.max_results:
                    break

                if not job["name"]:
                    continue

                dedup = self._dedup_key(job["name"], job["city"])
                if dedup in self.seen_companies:
                    self.log("info", f"Skipping duplicate: {job['name']}")
                    continue
                self.seen_companies.add(dedup)

                email = job["email"]

                # Try website if no email on page
                if not email and job["website"]:
                    self.log("info", f"No email on page for '{job['name']}', checking website...")
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

                self.log("info", f"KEPT '{job['name']}': email='{email}'")

                self.companies.append({
                    "company_name": job["name"],
                    "email": email,
                    "city": job["city"],
                    "website": job["website"],
                    "phone": job["phone"],
                    "job_title": job["title"] or self.profession,
                    "field": self.profession,
                    "source": "azubica",
                })

            self.log("info", f"Current companies with email: {len(self.companies)}")

        self.log("info", "=== Azubica Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)}")
        return self.get_results()