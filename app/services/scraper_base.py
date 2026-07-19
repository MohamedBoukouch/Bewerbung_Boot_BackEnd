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
                 field_tags: List[str] = None, log_callback: Optional[Callable] = None):
        self.profession = profession
        self.location = location
        self.max_results = max_results
        self.target_max = max_results  # EXACT target - never exceed this
        self.field_tags = field_tags or []
        self.log_callback = log_callback
        self.companies = []
        self.seen_companies = set()  # For dedup within current scrape only
        self.source_label = ""
        self.current_company = ""
        self.current_logo_url = ""
        self.pages_fetched = 0

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

    def _favicon_url(self, website: str) -> str:
        """Best-effort: derive a favicon URL from the company website."""
        if not website:
            return ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(website.split("?")[0].rstrip("/"))
            domain = parsed.netloc or parsed.path
            if domain:
                return f"https://www.google.com/s2/favicons?domain={domain}&sz=32"
        except Exception:
            pass
        return ""

    def _extract_email(self, text: str) -> str:
        if not text:
            return ""
        # Match email patterns - improved to avoid common false positives
        pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        matches = re.findall(pattern, text)
        # Filter out invalid/common false positives
        valid = []
        for m in matches:
            m_lower = m.lower()
            # Skip common image/template placeholders
            if any(bad in m_lower for bad in ['example.com', 'domain.com', 'yourdomain', 'test.com', 'sample.com', 'email@', 'mail@', 'info@example']):
                continue
            # Skip overly long emails (likely not real)
            if len(m) > 60:
                continue
            # Skip emails with no dots before @ (usually invalid)
            if '.' not in m.split('@')[0] and len(m.split('@')[0]) < 3:
                continue
            valid.append(m)
        return valid[0] if valid else ""

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

    def _should_stop(self) -> bool:
        """Check if we've reached the exact target limit or a stop was requested."""
        if len(self.companies) >= self.target_max:
            return True
        try:
            from app.services.extract_progress import get_stop_event
            return get_stop_event().is_set()
        except Exception:
            return False

    def _add_company(self, name: str, email: str, city: str, website: str, phone: str, job_title: str):
        """Add company to results. ONLY if email is present.
        NO "already extracted" check - we extract ALL emails even if duplicate.
        But we DO dedup within the current scrape to avoid exact duplicates."""

        # HARD STOP if we already reached exact limit
        if len(self.companies) >= self.target_max:
            return

        name = name.strip()
        email = (email or "").strip()

        if not name:
            self.log("info", "Skipping: empty company name")
            return

        # FILTER: Only keep companies WITH email
        if not email:
            self.log("info", f"Skipping '{name}': no email found")
            return

        # DEDUP: Skip only if EXACT same name+city in CURRENT scrape
        dedup_key = self._dedup_key(name, city)
        if dedup_key in self.seen_companies:
            self.log("info", f"Skipping duplicate in current scrape: {name} ({city})")
            return
        self.seen_companies.add(dedup_key)

        # Field tags as comma-separated string
        field = ", ".join(self.field_tags) if self.field_tags else self.profession

        company = {
            "company_name": name,  # Consistent key name for frontend
            "name": name,
            "email": email,
            "city": city or "",
            "field": field,
            "website": website or "",
            "phone": phone or "",
            "job_title": job_title or "",
            "jobTitle": job_title or "",
            "logoUrl": self._favicon_url(website),
            "source": getattr(self, 'source_label', ''),
        }

        self.companies.append(company)
        self.log("success", f"Added company: {name} ({email}) [{len(self.companies)}/{self.target_max}]")
        self._progress()

    def get_results(self) -> List[dict]:
        """Return results, strictly limited to target_max."""
        return self.companies[:self.target_max]