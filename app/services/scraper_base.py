"""Base scraper with email/phone/website extraction."""
import re
from typing import List, Optional, Callable

try:
    from app.services.extract_progress import emit_log, set_progress
    _HAVE_PROGRESS = True
except Exception:
    _HAVE_PROGRESS = False


class BaseScraper:
    def __init__(self, profession: str, location: str = "", max_results: int = 50,
                 field_tags: List[str] = None, log_callback: Optional[Callable] = None,
                 already_extracted_emails: List[str] = None):
        self.profession = profession
        self.location = location
        self.max_results = max_results
        self.field_tags = field_tags or []
        self.log_callback = log_callback
        self.companies = []
        self.seen_companies = set()
        self.source_label = ""
        self.current_company = ""
        self.current_logo_url = ""
        self.pages_fetched = 0
        self.already_extracted_emails = set(e.lower() for e in (already_extracted_emails or []) if e)

    def log(self, type_: str, message: str):
        if self.log_callback:
            self.log_callback(type_, message)
        if _HAVE_PROGRESS:
            emit_log(type_, message)
        else:
            print(f"[{type_.upper()}] {message}")

    def _progress(self):
        """Push live progress (current company, logo, email count) as SSE."""
        if not _HAVE_PROGRESS:
            return
        set_progress(
            running=True,
            source_label=self.source_label,
            current_company=self.current_company,
            current_logo_url=self.current_logo_url,
            emails_found=len(self.companies),
            pages_fetched=self.pages_fetched,
            status="running",
        )

    def _dedup_key(self, name: str, city: str) -> str:
        return f"{name.strip().lower()}|{city.strip().lower()}"

    def _is_already_extracted(self, email: str) -> bool:
        if not email or not self.already_extracted_emails:
            return False
        return email.lower() in self.already_extracted_emails

    def _favicon_url(self, website: str) -> str:
        """Best-effort: derive a favicon URL from the company website."""
        if not website:
            return ""
        site = website.split("?")[0].rstrip("/")
        if site.startswith("http"):
            return f"{site}/favicon.ico"
        return ""

    def _extract_email(self, text: str) -> str:
        if not text:
            return ""
        # Match email patterns
        pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        matches = re.findall(pattern, text)
        return matches[0] if matches else ""

    def _extract_phone(self, text: str) -> str:
        if not text:
            return ""
        # German phone patterns
        patterns = [
            r'(?:\+49|0)[\s\-]?\d{2,4}[\s\-]?\d{3,}[\s\-]?\d{3,}',  # +49 or 0 prefix
            r'\d{3,4}[\s\-/]\d{3,}[\s\-/]\d{3,}',  # general pattern
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[0].strip()
        return ""

    def _extract_website(self, text: str) -> str:
        if not text:
            return ""
        # Match URLs
        pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        matches = re.findall(pattern, text)
        if matches:
            return matches[0]
        # Match www. domains
        pattern2 = r'www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        matches2 = re.findall(pattern2, text)
        if matches2:
            return "https://" + matches2[0]
        return ""

    def _set_current(self, name: str, website: str = ""):
        """Call before processing each company so the frontend can show
        its name + logo while scraping."""
        self.current_company = name or ""
        self.current_logo_url = self._favicon_url(website)
        self._progress()

    def _add_company(self, name: str, email: str, city: str, website: str, phone: str, job_title: str):
        """Add company to results. ONLY if email is present and not already extracted."""
        name = name.strip()
        email = (email or "").strip()

        if not name:
            self.log("info", "Skipping: empty company name")
            return

        # ✅ FILTER: Only keep companies WITH email
        if not email:
            self.log("info", f"Skipping '{name}': no email found")
            return

        # ✅ FILTER: Skip already extracted emails
        if self._is_already_extracted(email):
            self.log("info", f"Skipping '{name}': email '{email}' already extracted previously")
            return

        # Field tags as comma-separated string
        field = ", ".join(self.field_tags) if self.field_tags else self.profession

        company = {
            "name": name,
            "email": email,
            "city": city or "",
            "field": field,
            "website": website or "",
            "phone": phone or "",
            "jobTitle": job_title or "",
            "logoUrl": self._favicon_url(website),
        }

        self.companies.append(company)
        self.log("success", f"Added company: {name} ({email})")
        self._progress()

    def get_results(self) -> List[dict]:
        return self.companies
