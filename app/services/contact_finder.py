"""
contact_finder.py
==================
Shared helper used by scrapers whose source sites (AUBI-plus, Azubiyo, ...)
do NOT publish company emails directly on job listings/details.

Logic:
    1. Visit the company's own website (not the job portal).
    2. Try to find an email directly on the homepage (mailto: links or
       plain-text email addresses).
    3. If none found, look for a link to "Impressum" / "Kontakt" / "Contact"
       (German law requires an Impressum with contact details for any
       commercial website), follow it, and extract an email there.

This is intentionally conservative: it only follows links that are already
present on the pages it visits (no guessing of URLs), and it never emails
or contacts anyone -- it only reads publicly published contact info.
"""
import re
from typing import List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

CONTACT_KEYWORDS = ["impressum", "kontakt", "contact", "imprint", "about-us", "ueber-uns"]

# Emails that are technically valid but useless for outreach purposes
JUNK_PREFIXES = ("noreply", "no-reply", "donotreply", "webmaster", "postmaster", "abuse")

# Common asset/tracker domains that sometimes leak fake "emails" via regex false positives
JUNK_DOMAIN_HINTS = ("sentry.io", "wixpress.com", "example.com", "domain.com")


def _is_junk_email(email: str) -> bool:
    lower = email.lower()
    if any(lower.startswith(p) for p in JUNK_PREFIXES):
        return True
    if any(hint in lower for hint in JUNK_DOMAIN_HINTS):
        return True
    return False


def extract_emails_from_html(html: str) -> List[str]:
    """Pull every plausible email out of a page: mailto: links first (most reliable), then plain text."""
    soup = BeautifulSoup(html, "html.parser")
    emails: List[str] = []
    seen = set()

    # 1. mailto: links (highest confidence)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            addr = href.split(":", 1)[1].split("?")[0].strip()
            if "@" in addr and addr.lower() not in seen and not _is_junk_email(addr):
                seen.add(addr.lower())
                emails.append(addr)

    if emails:
        return emails

    # 2. plain-text email pattern anywhere on the page (fallback)
    text = soup.get_text(" ", strip=True)
    for match in EMAIL_RE.findall(text):
        if match.lower() not in seen and not _is_junk_email(match):
            seen.add(match.lower())
            emails.append(match)

    return emails


def _find_contact_link(html: str, base_url: str) -> Optional[str]:
    """Find a link on the page that looks like it leads to Impressum/Kontakt/Contact."""
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        link_text = a.get_text(strip=True).lower()
        if any(k in href for k in CONTACT_KEYWORDS) or any(k in link_text for k in CONTACT_KEYWORDS):
            return urljoin(base_url, a["href"])
    return None


async def find_email_on_company_website(
    client: httpx.AsyncClient,
    website_url: str,
    headers: dict,
    log=None,
    timeout: float = 8.0,
) -> str:
    """
    Visit a company's own website, then (if needed) its Impressum/Kontakt page,
    and return the first plausible email found. Returns "" if nothing found
    or the site is unreachable.
    """
    if not website_url:
        return ""

    website_url = website_url.strip()
    if not website_url.startswith("http"):
        website_url = "https://" + website_url.lstrip("/")

    # Step 1: homepage
    try:
        resp = await client.get(website_url, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        final_url = str(resp.url)
    except Exception as e:
        if log:
            log("info", f"Could not reach company website '{website_url}': {e}")
        return ""

    emails = extract_emails_from_html(html)
    if emails:
        if log:
            log("info", f"Email found on homepage of {final_url}: {emails[0]}")
        return emails[0]

    # Step 2: follow Impressum/Kontakt link
    contact_url = _find_contact_link(html, final_url)
    if not contact_url:
        if log:
            log("info", f"No Impressum/Kontakt link found on {final_url}")
        return ""

    try:
        resp2 = await client.get(contact_url, headers=headers, timeout=timeout, follow_redirects=True)
        resp2.raise_for_status()
        emails2 = extract_emails_from_html(resp2.text)
        if emails2:
            if log:
                log("info", f"Email found on contact page {contact_url}: {emails2[0]}")
            return emails2[0]
        if log:
            log("info", f"No email found on contact page {contact_url}")
    except Exception as e:
        if log:
            log("info", f"Could not reach contact page '{contact_url}': {e}")

    return ""