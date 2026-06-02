"""
migrate.py — Yangi ustunlarni bazaga qo'shish
Ishlatish: python migrate.py

Qo'shilayotgan ustunlar:
  warehouse_products:
    - razmer_tur        VARCHAR(20)   -- Katta/O'rta/Kichik
    - holat             VARCHAR(20)   -- qoliplar uchun
    - holat_izoh        TEXT
    - razmer_normalized VARCHAR(200)

  Yangi jadvallar:
    - attendance
    - month_resets
    - telegram_groups
"""
import asyncio
import sys
import os

# Loyiha papkasiga yo'l
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import DATABASE_URL
import asyncpg


async def migrate():
    print("🔄 Migration boshlanmoqda...")

    # asyncpg to'g'ridan ulanish (SQLAlchemy emas)
    url = DATABASE_URL
    # postgresql+asyncpg:// → postgresql://
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    conn = await asyncpg.connect(url)

    migrations = [
        # ── warehouse_products yangi ustunlar ──────────────────────────────
        (
            "razmer_tur",
            """
            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS razmer_tur VARCHAR(20);
            """,
        ),
        (
            "yonalish (tiger/zagatovka/laminat)",
            """
            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS yonalish VARCHAR(20);
            """,
        ),
        (
            "qism (tepa/past/yon/paddo)",
            """
            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS qism VARCHAR(20);
            """,
        ),
        (
            "yonalish (tiger/zagatovka)",
            """
            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS yonalish VARCHAR(20);
            """,
        ),
        (
            "web_token",
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS web_token VARCHAR(80);
            """,
        ),
        (
            "zero_notified",
            """
            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS zero_notified BOOLEAN DEFAULT FALSE;
            """,
        ),
        (
            "customers jadvali",
            """
            CREATE TABLE IF NOT EXISTS customers (
                id          SERIAL PRIMARY KEY,
                full_name   VARCHAR(150) NOT NULL,
                phone       VARCHAR(30),
                address     TEXT,
                company     VARCHAR(150),
                notes       TEXT,
                is_active   BOOLEAN DEFAULT TRUE,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
        ),
        (
            "orders jadvali",
            """
            CREATE TABLE IF NOT EXISTS orders (
                id              SERIAL PRIMARY KEY,
                order_number    VARCHAR(30) UNIQUE NOT NULL,
                customer_id     INTEGER NOT NULL REFERENCES customers(id),
                title           VARCHAR(200) NOT NULL,
                description     TEXT,
                status          VARCHAR(30) DEFAULT 'yangi',
                priority        INTEGER DEFAULT 3,
                total_amount    DOUBLE PRECISION DEFAULT 0,
                paid_amount     DOUBLE PRECISION DEFAULT 0,
                deadline        DATE,
                created_by      INTEGER REFERENCES users(id),
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at    TIMESTAMP
            );
            """,
        ),
        (
            "goals jadvali",
            """
            CREATE TABLE IF NOT EXISTS goals (
                id            SERIAL PRIMARY KEY,
                worker_id     INTEGER NOT NULL REFERENCES users(id),
                period_type   VARCHAR(20) NOT NULL,
                period_date   DATE NOT NULL,
                target_amount DOUBLE PRECISION NOT NULL,
                target_count  INTEGER DEFAULT 0,
                set_by        INTEGER REFERENCES users(id),
                is_active     BOOLEAN DEFAULT TRUE,
                notes         TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
        ),
        (
            "order_items jadvali",
            """
            CREATE TABLE IF NOT EXISTS order_items (
                id              SERIAL PRIMARY KEY,
                order_id        INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_name    VARCHAR(200) NOT NULL,
                razmer          VARCHAR(50),
                rang            VARCHAR(50),
                quantity        DOUBLE PRECISION NOT NULL,
                unit            VARCHAR(20) DEFAULT 'dona',
                price_per_unit  DOUBLE PRECISION DEFAULT 0,
                subtotal        DOUBLE PRECISION DEFAULT 0,
                produced_qty    DOUBLE PRECISION DEFAULT 0,
                notes           TEXT
            );
            """,
        ),
        (
            "holat (ProductHolat enum)",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'productholat') THEN
                    CREATE TYPE productholat AS ENUM ('yaroqli', 'tamir_talab', 'yaroqsiz');
                END IF;
            END$$;

            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS holat productholat;
            """,
        ),
        (
            "holat_izoh",
            """
            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS holat_izoh TEXT;
            """,
        ),
        (
            "razmer_normalized",
            """
            ALTER TABLE warehouse_products
            ADD COLUMN IF NOT EXISTS razmer_normalized VARCHAR(200);
            """,
        ),

        # ── attendance jadvali ──────────────────────────────────────────────
        (
            "attendance table",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'attendancetype') THEN
                    CREATE TYPE attendancetype AS ENUM
                        ('ish', 'kasallik', 'tatil', 'sababli', 'sababsiz');
                END IF;
            END$$;

            CREATE TABLE IF NOT EXISTS attendance (
                id         SERIAL PRIMARY KEY,
                worker_id  INTEGER NOT NULL REFERENCES users(id),
                sana       DATE NOT NULL DEFAULT CURRENT_DATE,
                tur        attendancetype NOT NULL DEFAULT 'ish',
                izoh       TEXT,
                admin_id   INTEGER REFERENCES users(id),
                tasdiq     BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """,
        ),

        # ── month_resets jadvali ────────────────────────────────────────────
        (
            "month_resets table",
            """
            CREATE TABLE IF NOT EXISTS month_resets (
                id         SERIAL PRIMARY KEY,
                oy         INTEGER NOT NULL,
                yil        INTEGER NOT NULL,
                admin_id   INTEGER NOT NULL REFERENCES users(id),
                holat      VARCHAR(20) DEFAULT 'yakunlandi',
                izoh       TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """,
        ),

        # ── telegram_groups jadvali ─────────────────────────────────────────
        (
            "telegram_groups table",
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'grouptype') THEN
                    CREATE TYPE grouptype AS ENUM
                        ('inspector', 'admin', 'ishchi', 'hisobot');
                END IF;
            END$$;

            CREATE TABLE IF NOT EXISTS telegram_groups (
                id         SERIAL PRIMARY KEY,
                group_id   BIGINT UNIQUE NOT NULL,
                group_name VARCHAR(200),
                group_type grouptype NOT NULL,
                is_active  BOOLEAN DEFAULT TRUE,
                added_by   INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT NOW()
            );
            """,
        ),
    ]

    ok = 0
    fail = 0
    for name, sql in migrations:
        try:
            await conn.execute(sql)
            print(f"  ✅ {name}")
            ok += 1
        except Exception as e:
            # Ustun allaqachon mavjud bo'lsa OK
            if "already exists" in str(e).lower():
                print(f"  ⏭  {name} (allaqachon bor)")
                ok += 1
            else:
                print(f"  ❌ {name}: {e}")
                fail += 1

    await conn.close()
    print(f"\n{'✅ Migration muvaffaqiyatli!' if fail == 0 else '⚠️ Ayrim migratsiyalar bajarilmadi'}")
    print(f"   OK: {ok} | Xato: {fail}")


if __name__ == "__main__":
    asyncio.run(migrate())
