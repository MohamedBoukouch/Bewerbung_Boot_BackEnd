"""
Discover how Azubiyo loads its search results.

Run:
    python test_azubiyo.py
"""

import asyncio
import re
import httpx
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


URLS = [
    "https://www.azubiyo.de/",
    "https://www.azubiyo.de/suche/?search=Softwareentwickler&location=Berlin",
    "https://www.azubiyo.de/ausbildung/berlin/",
    "https://www.azubiyo.de/ausbildungsplatz/softwareentwickler/",
]


async def inspect_url(client, url):
    print("\n" + "=" * 80)
    print(url)
    print("=" * 80)

    try:
        r = await client.get(
            url,
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
        )

        print("Status:", r.status_code)
        print("Final URL:", str(r.url))

        html = r.text

        filename = (
            url.replace("https://", "")
            .replace("/", "_")
            .replace("?", "_")
            .replace("&", "_")
            .replace("=", "_")
            + ".html"
        )

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)

        print("Saved:", filename)

        soup = BeautifulSoup(html, "html.parser")

        print("Title:", soup.title.string if soup.title else "NO TITLE")

        scripts = soup.find_all("script")
        print("Scripts:", len(scripts))

        if "__NEXT_DATA__" in html:
            print("✓ Next.js detected")

        if "__NUXT__" in html:
            print("✓ Nuxt detected")

        if '"jobs"' in html.lower():
            print('✓ Found "jobs"')

        if '"stellen"' in html.lower():
            print('✓ Found "stellen"')

        if '"company"' in html.lower():
            print('✓ Found "company"')

        cards = soup.find_all(
            lambda tag: (
                tag.has_attr("class")
                and any(
                    re.search(
                        r"(job|card|offer|result|listing|stelle|ausbildung)",
                        c,
                        re.I,
                    )
                    for c in tag["class"]
                )
            )
        )

        print("Possible cards:", len(cards))

        if cards:
            print("\nFirst card preview:\n")
            print(cards[0].get_text(" ", strip=True)[:800])

        print("\nLinks containing 'job':")

        count = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]

            if any(
                x in href.lower()
                for x in [
                    "job",
                    "stelle",
                    "ausbildung",
                    "angebot",
                ]
            ):
                print(href)
                count += 1

                if count >= 20:
                    break

    except Exception as e:
        print("ERROR:", e)


async def main():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for url in URLS:
            await inspect_url(client, url)


if __name__ == "__main__":
    asyncio.run(main())