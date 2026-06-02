"""
web_link.py — Foydalanuvchi uchun shaxsiy web panel havolasini yaratish.
"""
import secrets
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from config.settings import WEB_URL, WEB_HOST, WEB_PORT

logger = logging.getLogger(__name__)


async def get_or_create_web_link(db: AsyncSession, user: User) -> str:
    """Foydalanuvchi uchun shaxsiy web havola qaytaradi.
    Token bo'lmasa — yangi yaratadi."""
    if not user.web_token:
        # Noyob token yaratish
        token = secrets.token_urlsafe(24)
        user.web_token = token
        await db.commit()
    else:
        token = user.web_token

    base = WEB_URL if WEB_URL else f"http://{WEB_HOST}:{WEB_PORT}"
    return f"{base}/w/{token}"


async def reset_web_link(db: AsyncSession, user: User) -> str:
    """Tokenni yangilash (eski havola ishlamay qoladi)."""
    token = secrets.token_urlsafe(24)
    user.web_token = token
    await db.commit()
    base = WEB_URL if WEB_URL else f"http://{WEB_HOST}:{WEB_PORT}"
    return f"{base}/w/{token}"
