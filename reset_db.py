# reset_db.py
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from config.settings import DATABASE_URL

async def reset():
    print(f"Ulanish: {DATABASE_URL}")
    
    if "sqlite" in DATABASE_URL:
        import os
        db_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"✅ {db_path} o'chirildi")
        else:
            print(f"❌ Fayl topilmadi: {db_path}")
    
    elif "postgresql" in DATABASE_URL:
        from sqlalchemy import text
        engine = create_async_engine(DATABASE_URL, echo=True)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            print("✅ PostgreSQL tozalandi!")
        await engine.dispose()
    
    print("Database tozalandi! Endi botni qayta ishga tushiring.")

if __name__ == "__main__":
    asyncio.run(reset())
