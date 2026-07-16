"""Test script for Azubica scraper backend"""
import asyncio
import sys
import os

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.azubica import AzubicaScraper


async def test_azubica():
    """Test Azubica scraper with different locations."""

    test_cases = [
        {"profession": "ausbildung", "location": "berlin", "max_results": 5},
        {"profession": "pflege", "location": "hamburg", "max_results": 5},
        {"profession": "it", "location": "muenchen", "max_results": 5},
        {"profession": "ausbildung", "location": "", "max_results": 5},  # No location
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"TEST {i}: profession='{test['profession']}', location='{test['location']}'")
        print(f"{'='*60}")

        logs = []
        def log_callback(type_, message):
            logs.append({"type": type_, "message": message})
            print(f"[{type_.upper()}] {message}")

        scraper = AzubicaScraper(
            profession=test["profession"],
            location=test["location"],
            max_results=test["max_results"],
            log_callback=log_callback,
        )

        try:
            companies = await asyncio.wait_for(scraper.scrape(), timeout=120.0)
            print(f"\n✅ RESULT: {len(companies)} companies found")
            for c in companies:
                print(f"   - {c['company_name']} | {c['email']} | {c['city']}")
        except asyncio.TimeoutError:
            print(f"\n❌ TIMEOUT after 120 seconds")
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    print("Testing Azubica Scraper Backend...")
    print("This will test multiple locations to see if any work.")
    print("Note: Azubica is a PDF-based platform, results may be limited.\n")

    asyncio.run(test_azubica())