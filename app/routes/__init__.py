# app/routes/__init__.py
from app.routes.extract import router as extract_router
from app.routes.email import router as email_router
from app.routes.access import router as access_router

__all__ = ["extract_router", "email_router", "access_router"]