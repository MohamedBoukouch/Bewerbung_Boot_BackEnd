"""
Client Google Sheets pour gérer les leads, codes d'accès et sessions.
Communique avec l'Apps Script via HTTP POST.
"""
import os
import httpx

APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "").strip()
APPS_SCRIPT_API_KEY = os.getenv("APPS_SCRIPT_API_KEY", "").strip()


class SheetsClientError(Exception):
    pass


async def _call_script(action: str, payload: dict) -> dict:
    """Appelle l'Apps Script avec l'action et les données."""
    if not APPS_SCRIPT_URL:
        raise SheetsClientError("APPS_SCRIPT_URL non configuré dans .env")

    body = {
        "action": action,
        "apiKey": APPS_SCRIPT_API_KEY,
        **payload,
    }

    try:
        # CRITICAL FIX: follow_redirects=True to handle 302 from Apps Script
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(APPS_SCRIPT_URL, json=body)
    except Exception as e:
        raise SheetsClientError(f"Erreur réseau vers Apps Script: {e}")

    if resp.status_code != 200:
        raise SheetsClientError(
            f"Apps Script a retourné HTTP {resp.status_code}: {resp.text[:500]}"
        )

    try:
        data = resp.json()
    except Exception as e:
        raise SheetsClientError(f"Réponse JSON invalide: {e} — Contenu: {resp.text[:500]}")

    if not data.get("success"):
        raise SheetsClientError(data.get("error", "Erreur Apps Script inconnue"))

    return data


async def submit_lead(pack: str, duration_days: int, full_name: str, email: str, whatsapp: str) -> dict:
    """Enregistre un lead dans la feuille Leads."""
    return await _call_script("submitLead", {
        "pack": pack,
        "durationDays": duration_days,
        "fullName": full_name,
        "email": email,
        "whatsapp": whatsapp,
    })


async def validate_code(code: str) -> dict:
    """Vérifie si un code existe et retourne son statut."""
    return await _call_script("validateCode", {"code": code})


async def activate_code(code: str, email: str) -> dict:
    """Lie un code à un email Google et marque comme utilisé."""
    return await _call_script("activateCode", {"code": code, "email": email})