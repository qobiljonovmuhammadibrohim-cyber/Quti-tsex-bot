"""
db_middleware.py — TUZATILGAN
ARXITEKTURA QAROR:
  Middleware SESSION ni ochib beradi va xatolik bo'lmasa commit qiladi.
  Handler ichida ham db.commit() chaqirish MUMKIN — ikki marta commit
  SQLAlchemy da xato bermaydi (ikkinchisi NO-OP bo'ladi).
  Rollback faqat exception da bo'ladi.

  Shuning uchun:
  - Muhim operatsiyalar (user yaratish, to'lov saqlash) uchun
    handler ichida ham db.commit() qo'llash tavsiya qilinadi
  - Oddiy o'qish so'rovlari uchun middleware commit yetarli
"""
import logging
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from database.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        async with AsyncSessionLocal() as session:
            data["db"] = session
            try:
                result = await handler(event, data)
                # Handler muvaffaqiyatli tugadi — commit qilamiz
                # (agar handler ichida allaqachon commit bo'lgan bo'lsa,
                # bu call NO-OP bo'ladi — xato bermaydi)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                logger.error("DB middleware rollback: %s", e)
                raise
