"""
Azubica Scraper v3 - Fixed to reach exact target limit

Azubica.de is a regional Ausbildungsatlas platform.
Strategy: Scrape regional atlas pages, then find emails via company websites.
"""
import asyncio
import re
from typing import List, Optional, Callable

from bs4 import BeautifulSoup
import httpx

from app.services.scraper_base import BaseScraper
from app.services.contact_finder import find_email_on_company_website, extract_emails_from_html

POSTAL_CITY_RE = re.compile(r"\b\d{5}\s+([A-ZÄÖÜ][a-zA-ZäöüÄÖÜß\-\. ]{1,40})")


class AzubicaScraper(BaseScraper):
    BASE_URL = "https://www.azubica.de"

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

    def _headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url, headers=self._headers(), timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            self.log("error", f"Fetch error for {url}: {str(e)}")
            return ""

    def _get_atlas_urls(self) -> List[str]:
        urls = []

        if self.location:
            loc = self.location.strip().lower()
            if loc in self.REGION_MAP:
                slug = self.REGION_MAP[loc]
                urls.append(f"{self.BASE_URL}/{slug}/")
            else:
                # Try partial match
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
        soup = BeautifulSoup(html, "html.parser")
        companies = []

        # Try multiple selectors
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

        # Fallback: extract from all links
        if not companies:
            self.log("info", "No structured data found, trying link extraction...")
            companies = self._extract_companies_from_links(soup)

        return companies

    def _extract_company_from_element(self, el) -> Optional[dict]:
        name = ""
        website = ""
        email = ""
        city = ""

        for tag in ["h2", "h3", "h4", "h5", ".name", ".title", ".company-name", "strong", "b"]:
            name_el = el.select_one(tag) if hasattr(el, 'select_one') else None
            if name_el:
                name = name_el.get_text(strip=True)
                break

        if not name:
            text = el.get_text(" ", strip=True) if hasattr(el, 'get_text') else ""
            name = text.split("\n")[0][:100] if text else ""

        for a in el.find_all("a", href=True) if hasattr(el, 'find_all') else []:
            href = a["href"]
            if href.startswith("http") and "azubica.de" not in href:
                website = href
                break

        text = el.get_text(" ", strip=True) if hasattr(el, 'get_text') else ""
        emails = extract_emails_from_html(str(el))
        if emails:
            email = emails[0]

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

    async def _lookup_email(self, client: httpx.AsyncClient, website: str) -> str:
        try:
            return await asyncio.wait_for(
                find_email_on_company_website(
                    client, website,
                    {"User-Agent": "Mozilla/5.0"}, log=self.log
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            return ""
        except Exception:
            return ""

    async def scrape(self) -> List[dict]:
        self.log("info", "=== Azubica Scraping Start ===")
        self.log("info", f"Profession: '{self.profession}'")
        self.log("info", f"Location: '{self.location or 'Germany-wide'}'")
        self.log("info", f"Target: {self.target_max} companies with email")
        self.log("info", "Email is REQUIRED. Offers without email are DISCARDED.")
        self.log("info", "NOTE: Azubica is a regional Ausbildungsatlas. Results depend on location.")

        atlas_urls = self._get_atlas_urls()
        self.log("info", f"Will scrape {len(atlas_urls)} atlas page(s): {atlas_urls}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            all_companies: List[dict] = []

            for url in atlas_urls:
                if self._should_stop():
                    break

                self.log("info", f"Fetching Azubica atlas: {url}")

                try:
                    html = await asyncio.wait_for(
                        self._fetch(client, url),
                        timeout=20.0,
                    )
                except asyncio.TimeoutError:
                    self.log("error", f"Timeout fetching {url}")
                    continue

                if not html:
                    self.log("error", f"Failed to fetch {url}")
                    continue

                companies = self._parse_companies_from_atlas(html)
                self.log("info", f"Found {len(companies)} potential companies on page")
                all_companies.extend(companies)

            if not all_companies:
                self.log("info", "No companies found. Scraping complete.")
                return self.get_results()

            self.log("info", f"Total potential companies: {len(all_companies)}. Looking up emails...")
            self.log("info", f"Current progress: {len(self.companies)}/{self.target_max} companies")

            # Process companies one by one
            for job in all_companies:
                if self._should_stop():
                    self.log("info", f"Reached target limit ({self.target_max}). Stopping.")
                    break

                if not job["name"]:
                    continue

                self._set_current(job["name"], job["website"])

                email = job["email"]

                if not email and job["website"]:
                    email = await self._lookup_email(client, job["website"])

                if not email:
                    self.log("info", f"DISCARDED '{job['name']}': no email found")
                    continue

                self._add_company(job["name"], email, job["city"], job["website"], job["phone"], job["title"] or self.profession)
                self.log("info", f"Progress: {len(self.companies)}/{self.target_max} companies")

                await asyncio.sleep(0.1)

        self.log("info", "=== Azubica Scraping Complete ===")
        self.log("info", f"Total companies with email: {len(self.companies)} (target was {self.target_max})")
        return self.get_results()