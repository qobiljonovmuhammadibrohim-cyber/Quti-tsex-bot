"""
clear_data.py — Tanlangan ma'lumotlarni tozalash
DIQQAT: Bu amal qaytarib bo'lmaydi!

O'CHIRILADI:
  - Ombor (mahsulotlar + loglar)
  - Jarimalar
  - Avanslar
  - Narxlar
  - Buyurtmalar (mijozlar + buyurtmalar)

SAQLANADI:
  - Ishchilar, admin
  - Ishlar (work entries)
  - Davomat, smenalar, maqsadlar

Ishlatish (Railway):
  1. Start Command: python clear_data.py
  2. Deploy → loglarni tekshiring
  3. Start Command ni qaytaring: python main.py
"""
import asyncio
import logging
from sqlalchemy import delete, func, select

from database.db import AsyncSessionLocal, init_db
from database.models import (
    WarehouseProduct, WarehouseLog,
    Penalty, Advance, WorkPrice,
    Order, OrderItem, Customer,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clear_data")


async def clear_data():
    """Tanlangan ma'lumotlarni o'chirish."""
    await init_db()

    async with AsyncSessionLocal() as db:
        # Sanash
        counts = {}
        for name, model in [
            ("Ombor loglari",  WarehouseLog),
            ("Mahsulotlar",    WarehouseProduct),
            ("Jarimalar",      Penalty),
            ("Avanslar",       Advance),
            ("Narxlar",        WorkPrice),
            ("Buyurtma item",  OrderItem),
            ("Buyurtmalar",    Order),
            ("Mijozlar",       Customer),
        ]:
            r = await db.execute(select(func.count(model.id)))
            counts[name] = int(r.scalar() or 0)

        logger.info("=" * 50)
        logger.info("MA'LUMOTLARNI TOZALASH BOSHLANDI")
        for name, cnt in counts.items():
            logger.info("  %s: %d ta", name, cnt)
        logger.info("=" * 50)

        # O'chirish tartibi (FK bog'liqliklarini hisobga olib)
        # 1. Ombor
        await db.execute(delete(WarehouseLog))
        await db.execute(delete(WarehouseProduct))
        logger.info("✅ Ombor tozalandi")

        # 2. Jarima va avans
        await db.execute(delete(Penalty))
        await db.execute(delete(Advance))
        logger.info("✅ Jarimalar va avanslar tozalandi")

        # 3. Narxlar
        await db.execute(delete(WorkPrice))
        logger.info("✅ Narxlar tozalandi")

        # 4. Buyurtmalar (avval item, keyin order, keyin customer)
        await db.execute(delete(OrderItem))
        await db.execute(delete(Order))
        await db.execute(delete(Customer))
        logger.info("✅ Buyurtmalar va mijozlar tozalandi")

        await db.commit()

        logger.info("=" * 50)
        logger.info("✅ HAMMASI TOZALANDI!")
        logger.info("Endi Start Command ni qaytaring: python main.py")
        logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(clear_data())
