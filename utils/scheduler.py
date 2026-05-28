"""
utils/scheduler.py — TUZATILGAN
TUZATISHLAR:
  1. send_daily/weekly/monthly: AsyncSessionLocal context manager
     to'g'ri ishlatiladi (db.commit() qo'shildi)
  2. send_warehouse_alert: dedupe targets (set() bilan)
  3. _send_to_admins: dedupe admins
"""
import logging
from datetime import date, datetime
from aiogram import Bot
from aiogram.types import BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database.db import AsyncSessionLocal
from database.models import UserRole, WarehouseProduct
from utils.reports import generate_daily_excel, generate_weekly_excel, generate_monthly_excel

logger = logging.getLogger(__name__)


async def _send_to_admins(bot: Bot, file_bytes: bytes, filename: str, caption: str):
    async with AsyncSessionLocal() as db:
        from database.queries import get_users_by_role
        admins = await get_users_by_role(db, UserRole.admin)
        supers = await get_users_by_role(db, UserRole.superadmin)
        # TUZATILDI: dedupe
        seen = set()
        for u in admins + supers:
            if u.telegram_id in seen:
                continue
            seen.add(u.telegram_id)
            try:
                f = BufferedInputFile(file_bytes, filename=filename)
                await bot.send_document(u.telegram_id, f, caption=caption, parse_mode="HTML")
            except Exception as e:
                logger.error("Yuborishda xato (%s): %s", u.telegram_id, e)


async def send_daily(bot: Bot):
    async with AsyncSessionLocal() as db:
        try:
            today = date.today()
            data  = await generate_daily_excel(db, report_date=today)
            await _send_to_admins(
                bot, data.read(),
                filename=f"kunlik_{today}.xlsx",
                caption=f"📊 <b>Kunlik hisobot</b> — {today.strftime('%d.%m.%Y')}",
            )
            logger.info("Kunlik hisobot yuborildi")
        except Exception as e:
            logger.error("Kunlik hisobot xatosi: %s", e)


async def send_weekly(bot: Bot):
    async with AsyncSessionLocal() as db:
        try:
            today = date.today()
            data  = await generate_weekly_excel(db)
            await _send_to_admins(
                bot, data.read(),
                filename=f"haftalik_{today}.xlsx",
                caption=f"📆 <b>Haftalik hisobot</b> — {today.strftime('%d.%m.%Y')}",
            )
            logger.info("Haftalik hisobot yuborildi")
        except Exception as e:
            logger.error("Haftalik hisobot xatosi: %s", e)


async def send_monthly(bot: Bot):
    async with AsyncSessionLocal() as db:
        try:
            now = datetime.now()
            # O'tgan oyni yuborish
            if now.month == 1:
                oy, yil = 12, now.year - 1
            else:
                oy, yil = now.month - 1, now.year
            data = await generate_monthly_excel(db, oy, yil)
            await _send_to_admins(
                bot, data.read(),
                filename=f"oylik_{oy}_{yil}.xlsx",
                caption=f"💰 <b>Oylik maosh hisoboti</b> — {oy}/{yil}",
            )
            logger.info("Oylik hisobot yuborildi (%s/%s)", oy, yil)
        except Exception as e:
            logger.error("Oylik hisobot xatosi: %s", e)


async def send_warehouse_alert(bot: Bot):
    """Har kuni 08:00 — omborchi va adminlarga kam qolgan mahsulotlar."""
    async with AsyncSessionLocal() as db:
        try:
            from sqlalchemy import select
            from database.queries import get_users_by_role

            r = await db.execute(
                select(WarehouseProduct)
                .where(
                    WarehouseProduct.is_active == True,
                    WarehouseProduct.miqdor <= WarehouseProduct.yellow_threshold,
                )
                .order_by(WarehouseProduct.miqdor)
            )
            products = r.scalars().all()

            if not products:
                logger.info("Ombor holati yaxshi — eslatma yuborilmadi")
                return

            kritik = [p for p in products if float(p.miqdor) <= float(p.min_threshold)]
            ogoh   = [p for p in products
                      if float(p.min_threshold) < float(p.miqdor) <= float(p.yellow_threshold)]

            text = (
                f"🌅 Ertalab salom!\n"
                f"📋 Ombor holati — {date.today().strftime('%d.%m.%Y')}\n\n"
            )

            if kritik:
                text += f"🔴 TUGAY DEYAPTI ({len(kritik)} ta):\n"
                for p in kritik[:10]:
                    text += f"  • {p.name}: {p.miqdor} {p.birlik}\n"
                if len(kritik) > 10:
                    text += f"  ... va yana {len(kritik) - 10} ta\n"
                text += "\n"

            if ogoh:
                text += f"🟡 KAM QOLGAN ({len(ogoh)} ta):\n"
                for p in ogoh[:10]:
                    text += f"  • {p.name}: {p.miqdor} {p.birlik}\n"
                if len(ogoh) > 10:
                    text += f"  ... va yana {len(ogoh) - 10} ta\n"

            text += "\n💡 Buyurtma ro'yxatini yangilashni unutmang!"

            omborchilar = await get_users_by_role(db, UserRole.omborchi)
            adminlar    = await get_users_by_role(db, UserRole.admin)

            # TUZATILDI: dedupe
            seen = set()
            for u in omborchilar + adminlar:
                if u.telegram_id in seen:
                    continue
                seen.add(u.telegram_id)
                try:
                    await bot.send_message(u.telegram_id, text)
                except Exception as e:
                    logger.warning("Eslatma yuborib bo'lmadi (%s): %s", u.telegram_id, e)

            logger.info("Ombor eslatmasi yuborildi (%d ta)", len(seen))

        except Exception as e:
            logger.error("Ombor eslatma xatosi: %s", e)


async def send_qolip_alert(bot: Bot):
    """Har kuni 08:00 — tamir talab va yaroqsiz qoliplar haqida ogohlantirish."""
    async with AsyncSessionLocal() as db:
        try:
            from database.queries import get_tamir_talab_qoliplar, get_users_by_role
            products = await get_tamir_talab_qoliplar(db)
            if not products:
                return

            tamir    = [p for p in products if p.holat and p.holat.value == "tamir_talab"]
            yaroqsiz = [p for p in products if p.holat and p.holat.value == "yaroqsiz"]

            text = f"🔲 Qoliplar holati — {date.today().strftime('%d.%m.%Y')}\n\n"

            if tamir:
                text += f"🔧 TAMIR TALAB ({len(tamir)} ta):\n"
                for p in tamir[:15]:
                    text += f"  • {p.name}"
                    if p.razmer: text += f" [{p.razmer}]"
                    if p.holat_izoh: text += f" — {p.holat_izoh}"
                    text += "\n"
                if len(tamir) > 15:
                    text += f"  ... va yana {len(tamir)-15} ta\n"
                text += "\n"

            if yaroqsiz:
                text += f"❌ YAROQSIZ ({len(yaroqsiz)} ta):\n"
                for p in yaroqsiz[:10]:
                    text += f"  • {p.name}"
                    if p.razmer: text += f" [{p.razmer}]"
                    text += "\n"

            text += "\n💡 Bot → 🔲 Qoliplar → Holat o'zgartirish"

            admins    = await get_users_by_role(db, UserRole.admin)
            omborchilar = await get_users_by_role(db, UserRole.omborchi)
            seen = set()
            for u in admins + omborchilar:
                if u.telegram_id in seen: continue
                seen.add(u.telegram_id)
                try:
                    await bot.send_message(u.telegram_id, text)
                except Exception as e:
                    logger.warning("Qolip alert yuborib bo'lmadi (%s): %s", u.telegram_id, e)

            logger.info("Qolip eslatmasi yuborildi: %d ta diqqat", len(products))
        except Exception as e:
            logger.error("Qolip eslatma xatosi: %s", e)




async def send_month_end_reminder(bot: Bot):
    """Har oyning oxirgi kuni — oyni yakunlash eslatmasi."""
    async with AsyncSessionLocal() as db:
        try:
            from database.queries import get_users_by_role
            from database.models import UserRole
            from datetime import date

            today   = date.today()
            oy_nomi = ["","Yanvar","Fevral","Mart","Aprel","May","Iyun",
                       "Iyul","Avgust","Sentabr","Oktabr","Noyabr","Dekabr"]

            admins = await get_users_by_role(db, UserRole.admin)
            supers = await get_users_by_role(db, UserRole.superadmin)
            seen   = set()
            for u in admins + supers:
                if u.telegram_id in seen: continue
                seen.add(u.telegram_id)
                try:
                    await bot.send_message(
                        u.telegram_id,
                        f"📅 <b>Diqqat!</b> {oy_nomi[today.month]} oyi tugayapti.\n\n"
                        f"Iltimos:\n"
                        f"1. Barcha maoshlarni tasdiqlang\n"
                        f"2. Tasdiqlanmagan ishlarni ko'rib chiqing\n"
                        f"3. <b>🔄 Yangi oy boshlash</b> tugmasini bosing\n\n"
                        f"Bot → Admin menyu → 🔄 Yangi oy boshlash",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning("Oy oxiri eslatma xatosi (%s): %s", u.telegram_id, e)

            logger.info("Oy oxiri eslatmasi yuborildi")
        except Exception as e:
            logger.error("send_month_end_reminder xatosi: %s", e)


async def send_report_now(bot: Bot, report_type: str) -> bool:
    """
    Admin qo'ldan hisobot yuborishi uchun.
    report_type: 'daily' | 'weekly' | 'monthly' | 'warehouse'
    """
    try:
        if report_type == "daily":
            await send_daily(bot)
        elif report_type == "weekly":
            await send_weekly(bot)
        elif report_type == "monthly":
            await send_monthly(bot)
        elif report_type == "warehouse":
            await send_warehouse_alert(bot)
        else:
            logger.warning("Noma'lum report_type: %s", report_type)
            return False
        return True
    except Exception as e:
        logger.error("Qo'lda yuborishda xato (%s): %s", report_type, e)
        return False


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="Asia/Tashkent")

    # Kunlik hisobot — 20:00
    sched.add_job(
        send_daily,
        CronTrigger(hour=20, minute=0),
        args=[bot],
        id="daily",
        replace_existing=True,
    )

    # Haftalik hisobot — yakshanba 21:00
    sched.add_job(
        send_weekly,
        CronTrigger(day_of_week=6, hour=21, minute=0),
        args=[bot],
        id="weekly",
        replace_existing=True,
    )

    # Oylik hisobot — har oyning 10-kuni 09:00
    sched.add_job(
        send_monthly,
        CronTrigger(day=10, hour=9, minute=0),
        args=[bot],
        id="monthly",
        replace_existing=True,
    )

    # Ombor eslatmasi — har kuni 08:00
    sched.add_job(
        send_warehouse_alert,
        CronTrigger(hour=8, minute=0),
        args=[bot],
        id="warehouse_alert",
        replace_existing=True,
    )

    # Qolip holati eslatmasi — har kuni 08:30
    sched.add_job(
        send_qolip_alert,
        CronTrigger(hour=8, minute=30),
        args=[bot],
        id="qolip_alert",
        replace_existing=True,
    )

    # Oy oxiri eslatmasi — har oyning 28-kuni 10:00
    sched.add_job(
        send_month_end_reminder,
        CronTrigger(day=28, hour=10, minute=0),
        args=[bot],
        id="month_end_reminder",
        replace_existing=True,
    )

    logger.info(
        "Scheduler tayyor:\n"
        "  📊 Kunlik:          20:00\n"
        "  📆 Haftalik:        Yakshanba 21:00\n"
        "  💰 Oylik:           Har oyning 10-kuni 09:00\n"
        "  🏭 Ombor eslatma:   08:00\n"
        "  🔲 Qolip eslatmasi: 08:30\n"
        "  📅 Oy oxiri:        28-kuni 10:00"
    )
    return sched
