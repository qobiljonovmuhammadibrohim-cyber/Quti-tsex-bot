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