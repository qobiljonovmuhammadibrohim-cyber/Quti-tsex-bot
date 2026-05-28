"""
Barcha seed mahsulotlarini ketma-ketlikda o'chiradi:
1. warehouse_logs (bog'langan loglar)
2. warehouse_products (mahsulotlar)
"""
import asyncio
from database.db import AsyncSessionLocal, init_db
from database.models import WarehouseProduct
from sqlalchemy import delete, text


async def clear():
    await init_db()
    async with AsyncSessionLocal() as db:
        # 1. Avval loglarni o'chirish
        r1 = await db.execute(text("DELETE FROM warehouse_logs"))
        print(f"🗑 warehouse_logs: {r1.rowcount} ta o'chirildi")

        # 2. Keyin mahsulotlarni o'chirish
        r2 = await db.execute(delete(WarehouseProduct))
        print(f"🗑 warehouse_products: {r2.rowcount} ta o'chirildi")

        await db.commit()
        print(f"\n✅ Barchasi tozalandi!")


if __name__ == "__main__":
    asyncio.run(clear())