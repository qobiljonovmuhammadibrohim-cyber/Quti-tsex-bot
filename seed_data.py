"""
seed_data.py — Boshlang'ich mahsulotlarni DB ga kiritish
Faqat bir marta ishga tushiring: python seed_data.py
Allaqachon mavjud mahsulotlarni qayta qo'shmaydi.
"""
import asyncio
from database.db import AsyncSessionLocal, init_db
from database.models import WarehouseProduct, ProductCategory


# ── BARCHA BOSHLANG'ICH MAHSULOTLAR ─────────────────────────────────────────
SEED_PRODUCTS = [

    # ── ADYOL ZAPCHASTLAR ────────────────────────────────────────────────────
    {"category": "adyol_zapchast", "name": "Quluf tepa qismi",         "birlik": "dona", "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Quluf past qismi",         "birlik": "dona", "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Quluflar (to'liq)",        "birlik": "dona", "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Ruchka",                   "birlik": "dona", "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Ruchka ilgagi",            "birlik": "dona", "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Katta piston tepa",        "birlik": "qop",  "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Katta piston past",        "birlik": "qop",  "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Kapalak piston tepa",      "birlik": "qop",  "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Kapalak piston past",      "birlik": "qop",  "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Remen pistoni",            "birlik": "pachka","miqdor": 0},
    {"category": "adyol_zapchast", "name": "Tesma",  "rang": "Qora",   "birlik": "dona", "miqdor": 0},
    {"category": "adyol_zapchast", "name": "Tesma",  "rang": "Qaymoq", "birlik": "dona", "miqdor": 0},
    {"category": "adyol_zapchast", "name": "IP",     "rang": "Qora",   "birlik": "pachka","miqdor": 0},
    {"category": "adyol_zapchast", "name": "IP",     "rang": "Qaymoq", "birlik": "pachka","miqdor": 0},

    # ── XROMAZESLAR ──────────────────────────────────────────────────────────
    {"category": "xromazes", "name": "Xromazes Adyol/Pastel",   "birlik": "dona", "miqdor": 0},
    {"category": "xromazes", "name": "Xromazes Poyabzal",       "birlik": "dona", "miqdor": 0},
    {"category": "xromazes", "name": "Xromazes Shirinlik",      "birlik": "dona", "miqdor": 0},
    {"category": "xromazes", "name": "Xromazes Fast food",      "birlik": "dona", "miqdor": 0},
    {"category": "xromazes", "name": "Xromazes Boshqa",         "birlik": "dona", "miqdor": 0},

    # ── LAMINAT XROMAZESLAR ──────────────────────────────────────────────────
    {"category": "laminat_xromazes", "name": "Laminat Xromazes Adyol/Pastel", "birlik": "dona", "miqdor": 0},
    {"category": "laminat_xromazes", "name": "Laminat Xromazes Poyabzal",     "birlik": "dona", "miqdor": 0},
    {"category": "laminat_xromazes", "name": "Laminat Xromazes Shirinlik",    "birlik": "dona", "miqdor": 0},
    {"category": "laminat_xromazes", "name": "Laminat Xromazes Fast food",    "birlik": "dona", "miqdor": 0},
    {"category": "laminat_xromazes", "name": "Laminat Xromazes Boshqa",       "birlik": "dona", "miqdor": 0},

    # ── QOLIPLAR ─────────────────────────────────────────────────────────────
    {"category": "qolip", "name": "Qolip Adyol/Pastel",  "birlik": "dona", "miqdor": 0},
    {"category": "qolip", "name": "Qolip Poyabzal",      "birlik": "dona", "miqdor": 0},
    {"category": "qolip", "name": "Qolip Shirinlik",     "birlik": "dona", "miqdor": 0},
    {"category": "qolip", "name": "Qolip Fast food",     "birlik": "dona", "miqdor": 0},
    {"category": "qolip", "name": "Qolip Boshqa",        "birlik": "dona", "miqdor": 0},

    # ── USKUNA ZAPCHASTLAR ────────────────────────────────────────────────────
    {"category": "uskuna_zapchast", "name": "Motor",       "birlik": "dona", "miqdor": 0},
    {"category": "uskuna_zapchast", "name": "Tasma",       "birlik": "dona", "miqdor": 0},
    {"category": "uskuna_zapchast", "name": "Podshipnik",  "birlik": "dona", "miqdor": 0},
    {"category": "uskuna_zapchast", "name": "Kamar",       "birlik": "dona", "miqdor": 0},
    {"category": "uskuna_zapchast", "name": "Boshqa ehtiyot qism", "birlik": "dona", "miqdor": 0},

    # ── TAYYOR MAHSULOTLAR ────────────────────────────────────────────────────
    {"category": "tayyor_mahsulot", "name": "Tayyor Adyol karobka", "birlik": "dona", "miqdor": 0},
    {"category": "tayyor_mahsulot", "name": "Tayyor Pastel karobka","birlik": "dona", "miqdor": 0},
    {"category": "tayyor_mahsulot", "name": "Tayyor Poyabzal quti", "birlik": "dona", "miqdor": 0},
    {"category": "tayyor_mahsulot", "name": "Tayyor Shirinlik quti","birlik": "dona", "miqdor": 0},
    {"category": "tayyor_mahsulot", "name": "Tayyor Fast food quti","birlik": "dona", "miqdor": 0},

    # ── YARIM TAYYOR ─────────────────────────────────────────────────────────
    {"category": "yarim_tayyor", "name": "Tiger kesish uchun material", "tur": "tiger_uchun",         "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Gofra kley uchun material",   "tur": "gofra_kley_zagatovka",    "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Stepler uchun material",      "tur": "stepler_uchun",       "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Salafan uchun material",      "tur": "salafan_uchun",       "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Yopish uchun material",       "tur": "yopish_uchun",        "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Adyol tikish uchun material", "tur": "adyol_tikish_uchun",  "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Pastel tikish uchun material","tur": "pastel_tikish_uchun", "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Adyol qoqish uchun tikilgan","tur": "adyol_qoqish_uchun",  "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Pastel qoqish uchun tikilgan","tur": "pastel_qoqish_uchun", "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Xom komple adyol",            "tur": "xom_komple",          "birlik": "dona", "miqdor": 0},
    {"category": "yarim_tayyor", "name": "Kapalak adyol",               "tur": "kapalak",             "birlik": "dona", "miqdor": 0},
]


async def seed():
    await init_db()
    added = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        for item in SEED_PRODUCTS:
            cat = ProductCategory(item["category"])

            # Mavjudligini tekshirish
            q = select(WarehouseProduct).where(
                WarehouseProduct.category == cat,
                WarehouseProduct.name == item["name"],
                WarehouseProduct.is_active == True,
            )
            if item.get("rang"):
                q = q.where(WarehouseProduct.rang == item["rang"])
            if item.get("tur"):
                q = q.where(WarehouseProduct.tur == item["tur"])
            if item.get("razmer"):
                q = q.where(WarehouseProduct.razmer == item["razmer"])

            existing = (await db.execute(q.limit(1))).scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            # Yangi mahsulot qo'shish
            product = WarehouseProduct(
                category=cat,
                name=item["name"],
                birlik=item.get("birlik", "dona"),
                miqdor=item.get("miqdor", 0),
                rang=item.get("rang"),
                tur=item.get("tur"),
                razmer=item.get("razmer"),
                min_threshold=2,
                yellow_threshold=5,
            )
            db.add(product)
            added += 1

        await db.commit()
    print(f"\n✅ Seed yakunlandi!")
    print(f"   Qo'shildi:  {added} ta mahsulot")
    print(f"   Mavjud edi: {skipped} ta (o'tkazib yuborildi)")
    print(f"\nEndi botni ishga tushiring.")


# 1-xatoni tuzatish:
if __name__ == "__main__":
    asyncio.run(seed())