from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, field_validator

from app.services import sheets_client

router = APIRouter()

# Doit matcher les packs affichés sur la page Pricing.
PACK_DURATIONS = {
    "الباقة المميزة": 60,
    "برو الشهري": 30,
    "باقة 15 يوم": 15,
    "البداية المجانية": 1,
}


class SubmitLeadBody(BaseModel):
    pack: str
    full_name: str
    email: EmailStr
    whatsapp: str

    @field_validator("full_name", "whatsapp")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Champ requis.")
        return v


@router.post("/leads/submit")
async def submit_lead(body: SubmitLeadBody):
    """Enregistre un lead 'pending' suite au choix d'un pack sur la page pricing.
    Ne crée JAMAIS de session ni d'accès : l'activation est manuelle (admin),
    après confirmation du paiement par WhatsApp.
    """
    duration_days = PACK_DURATIONS.get(body.pack)
    if duration_days is None:
        raise HTTPException(status_code=400, detail="Pack inconnu.")

    try:
        result = await sheets_client.submit_lead(
            pack=body.pack,
            duration_days=duration_days,
            full_name=body.full_name,
            email=body.email,
            whatsapp=body.whatsapp,
        )
    except sheets_client.SheetsClientError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "status": "pending",
        "message": "Merci ! Nous vous contacterons très bientôt sur WhatsApp pour confirmer votre paiement.",
    }