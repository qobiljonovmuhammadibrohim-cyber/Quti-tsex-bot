from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config.settings import DATABASE_URL as _DB_URL

# Railway postgresql:// → postgresql+asyncpg:// ga o'girish
DATABASE_URL = (
    _DB_URL
    .replace("postgres://", "postgresql+asyncpg://")
    .replace("postgresql://", "postgresql+asyncpg://")
)
from database.models import Base


def _make_engine():
    if DATABASE_URL.startswith("sqlite"):
        return create_async_engine(DATABASE_URL, echo=False)
    
    # PostgreSQL uchun - SSL ni butunlay o'chiramiz
    return create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={
            "ssl": False  # <-- BU YERDA: 'disable' emas, 'False'
        },
    )


engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_startup_migrations():
    """
    Startup'da ishlaydigan migration'lar (DATABASE_URL bu yerda aniq mavjud).
    Pre-Deploy migrate.py ishlamasa ham, ustunlar shu yerda qo'shiladi.
    Har biri xavfsiz: xato bo'lsa o'tkazib yuboriladi.
    """
    from sqlalchemy import text
    statements = [
        # topshiriqlar jadvali (agar yo'q bo'lsa)
        """CREATE TABLE IF NOT EXISTS topshiriqlar (
            id SERIAL PRIMARY KEY,
            worker_id INTEGER NOT NULL REFERENCES users(id),
            admin_id INTEGER REFERENCES users(id),
            work_type VARCHAR(50) NOT NULL,
            razmer_turi VARCHAR(100),
            target_soni FLOAT NOT NULL DEFAULT 0,
            narx FLOAT,
            done_soni FLOAT NOT NULL DEFAULT 0,
            product_id INTEGER REFERENCES warehouse_products(id),
            deadline DATE,
            status VARCHAR(20) NOT NULL DEFAULT 'tayinlangan',
            izoh TEXT,
            work_entry_id INTEGER REFERENCES work_entries(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP,
            completed_at TIMESTAMP
        );""",
        "ALTER TABLE topshiriqlar ADD COLUMN IF NOT EXISTS narx FLOAT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS web_token VARCHAR(80);",
        "ALTER TYPE worktype ADD VALUE IF NOT EXISTS 'rulon_ishlab';",
    ]
    import logging
    log = logging.getLogger(__name__)
    for sql in statements:
        try:
            # ALTER TYPE ADD VALUE tranzaksiyada ishlamaydi — autocommit kerak
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(text(sql))
        except Exception as e:
            log.info("Startup migration o'tkazildi (%s): %s", sql[:40], str(e)[:80])