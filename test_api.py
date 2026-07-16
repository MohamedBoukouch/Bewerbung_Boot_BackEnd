"""
Test script for Arbeitsagentur API - V3
"""
import asyncio
import httpx
import json

API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
API_KEY = "jobboerse-jobsuche"

async def test_search():
    print("="*60)
    print("TEST: Search Jobs")
    print("="*60)

    url = f"{API_BASE}/pc/v6/jobs"
    params = {
        "was": "Softwareentwickler",
        "wo": "Berlin",
        "angebotsart": 1,
        "page": 1,
        "size": 5,
    }
    headers = {
        "X-API-Key": API_KEY,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(follow_redirects=True) as client:
        print(f"\nURL: {url}")
        print(f"Params: {params}")

        resp = await client.get(url, params=params, headers=headers, timeout=30.0)
        print(f"\nStatus: {resp.status_code}")

        data = resp.json()
        print(f"Top-level keys: {list(data.keys())}")

        if "maxErgebnisse" in data:
            print(f"maxErgebnisse: {data['maxErgebnisse']}")
        if "page" in data:
            print(f"page: {data['page']}, size: {data.get('size', 'N/A')}")

        jobs = data.get("ergebnisliste", [])
        print(f"\nJobs found: {len(jobs)}")

        if jobs:
            print(f"\nFirst job keys: {list(jobs[0].keys())}")
            print(f"\nFirst job sample:")
            first = jobs[0]
            print(f"  arbeitgeber: {first.get('arbeitgeber', 'N/A')}")
            print(f"  stellenangebotsTitel: {first.get('stellenangebotsTitel', 'N/A')}")
            print(f"  refnr: {first.get('refnr', 'N/A')}")

            # City
            locs = first.get("stellenlokationen", [])
            if locs:
                city = locs[0].get("adresse", {}).get("ort", "N/A")
                print(f"  city (from stellenlokationen[0].adresse.ort): {city}")

            # Try details
            refnr = first.get("refnr", "")
            if refnr:
                print(f"\n{'='*60}")
                print("TEST: Job Details")
                print("="*60)
                await test_details(client, refnr)
        else:
            print("\nNo jobs found.")
            print(f"Full response: {json.dumps(data, indent=2)[:1000]}")

async def test_details(client, refnr):
    import base64
    encoded = base64.b64encode(refnr.encode()).decode()
    url = f"{API_BASE}/pc/v4/jobdetails/{encoded}"
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}

    print(f"\nrefnr: {refnr}")
    print(f"encoded: {encoded}")

    try:
        resp = await client.get(url, headers=headers, timeout=30.0)
        print(f"Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            print(f"Details keys: {list(data.keys())}")

            # Check description
            desc = data.get("stellenangebotsBeschreibung", "") or data.get("stellenbeschreibung", "")
            print(f"Description found: {bool(desc)}")
            if desc:
                print(f"Description preview: {desc[:300]}")

            # Check employer
            ag = data.get("arbeitgeber", {})
            if isinstance(ag, dict):
                print(f"Employer name: {ag.get('name', 'N/A')}")
                print(f"Employer homepage: {ag.get('homepage', 'N/A')}")
            elif isinstance(ag, str):
                print(f"Employer (string): {ag}")
        else:
            print(f"Error: {resp.text[:200]}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_search())