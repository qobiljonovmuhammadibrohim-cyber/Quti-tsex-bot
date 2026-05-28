"""
bot/handlers/month_reset.py — Oylik reset va Telegram guruh integratsiyasi

Oylik reset:
  - Oylik maoshlar tasdiqlangach ishchilar yana noldan boshlaydi
  - Jarimalar, avanslar, ish yozuvlari tarixda qoladi
  - Scheduler: har oyning 1-kuni ogohlantirish

Telegram guruh:
  - Admin guruhini ro'yxatdan o'tkazadi /setgroup {tur} orqali
  - Yangi ish, maosh tasdiq, ombor ogohlantirish guruhlarga boradi
"""
import logging
from datetime import date, datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case as sa_case

from database.models import (
    UserRole, User, SalaryReport, WorkEntry, WorkStatus,
    MonthReset, TelegramGroup, GroupType,
)
from database.queries import get_user, get_users_by_role

logger = logging.getLogger(__name__)
router = Router()

MONTHS_UZ = [
    "", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
    "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr",
]


class ResetState(StatesGroup):
    confirm = State()


# ═══ OYLIK RESET ══════════════════════════════════════════════════════════════

@router.message(F.text == "🔄 Yangi oy boshlash")
async def month_reset_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        await message.answer("❌ Faqat admin uchun."); return

    today = date.today()
    oy    = today.month
    yil   = today.year

    # Joriy oy statistikasi
    r = await db.execute(
        select(
            func.count(SalaryReport.id),
            func.sum(sa_case((SalaryReport.admin_tasdiqladi == True, 1), else_=0)),
            func.coalesce(func.sum(SalaryReport.sof_maosh), 0),
        ).where(
            SalaryReport.oy == oy,
            SalaryReport.yil == yil,
        )
    )
    row = r.one()
    total_rep, confirmed, total_sum = row[0] or 0, row[1] or 0, float(row[2])

    # Kutayotgan ishlar
    r_pend = await db.execute(
        select(func.count(WorkEntry.id))
        .where(WorkEntry.status == WorkStatus.pending)
    )
    pending = r_pend.scalar() or 0

    await state.update_data(
        reset_admin_id=user.id,
        reset_oy=oy,
        reset_yil=yil,
    )

    warn = ""
    if pending > 0:
        warn = f"\n⚠️ {pending} ta tasdiqlanmagan ish bor!"
    if confirmed < total_rep:
        warn += f"\n⚠️ {total_rep - confirmed} ta maosh tasdiqlanmagan!"

    await message.answer(
        f"🔄 <b>{MONTHS_UZ[oy]} {yil} — Oyni yakunlash</b>\n\n"
        f"📊 Maosh hisobotlari: {confirmed}/{total_rep} ta tasdiqlangan\n"
        f"💰 Jami maosh: {total_sum:,.0f} so'm"
        f"{warn}\n\n"
        f"Yangi oy boshlashni tasdiqlaysizmi?\n"
        f"(Barcha ma'lumotlar tarixda saqlanib qoladi)",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yangi oy boshlash", callback_data="reset_confirm"),
                InlineKeyboardButton(text="❌ Bekor",             callback_data="reset_cancel"),
            ],
        ]),
    )
    await state.set_state(ResetState.confirm)


@router.callback_query(F.data == "reset_confirm", ResetState.confirm)
async def month_reset_confirm(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    oy   = data["reset_oy"]
    yil  = data["reset_yil"]
    adm  = data["reset_admin_id"]

    # MonthReset yozuvi saqlash
    reset = MonthReset(
        oy=oy, yil=yil,
        admin_id=adm,
        holat="yakunlandi",
        izoh=f"{MONTHS_UZ[oy]} {yil} oyi yakunlandi",
    )
    db.add(reset)
    await db.commit()
    await state.clear()

    # Keyingi oy
    next_oy  = oy % 12 + 1
    next_yil = yil + (1 if next_oy == 1 else 0)

    # Barcha ishchilarga xabar
    workers = await get_users_by_role(db, UserRole.ishchi)
    notified = 0
    for w in workers:
        try:
            await cb.bot.send_message(
                w.telegram_id,
                f"🎉 {MONTHS_UZ[oy]} {yil} oyi yakunlandi!\n\n"
                f"Yangi oy: <b>{MONTHS_UZ[next_oy]} {next_yil}</b>\n"
                f"Ish hisobingiz yangi oyda noldan boshlanadi.\n"
                f"Omad! 💪",
                parse_mode="HTML",
            )
            notified += 1
        except Exception as e:
            logger.warning("Reset xabari yuborilmadi (%s): %s", w.telegram_id, e)

    # Guruhlarga xabar
    await send_to_groups(
        cb.bot, db, GroupType.admin,
        f"🔄 <b>{MONTHS_UZ[oy]} {yil} oyi yakunlandi!</b>\n"
        f"Yangi oy: {MONTHS_UZ[next_oy]} {next_yil}\n"
        f"{notified} ta ishchiga xabar yuborildi.",
    )

    await cb.message.answer(
        f"✅ <b>{MONTHS_UZ[oy]} {yil} yakunlandi!</b>\n\n"
        f"📨 {notified} ta ishchiga xabar yuborildi.\n"
        f"🗓 Yangi oy: {MONTHS_UZ[next_oy]} {next_yil}",
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "reset_cancel")
async def month_reset_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("❌ Bekor qilindi.")
    await cb.answer()


# ═══ TELEGRAM GURUH INTEGRATSIYASI ════════════════════════════════════════════

@router.message(Command("setgroup"))
async def set_group(message: Message, db: AsyncSession):
    """
    Guruhda /setgroup {tur} deb yoziladi.
    Tur: inspector | admin | ishchi | hisobot
    """
    # Faqat guruhda ishlaydi
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Bu buyruq faqat guruhda ishlaydi!"); return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "Format: /setgroup {tur}\n"
            "Turlar: inspector | admin | ishchi | hisobot"
        ); return

    tur_str = args[1].lower()
    try:
        group_type = GroupType(tur_str)
    except ValueError:
        await message.answer(
            f"Noto'g'ri tur: {tur_str}\n"
            "To'g'ri turlar: inspector | admin | ishchi | hisobot"
        ); return

    # Foydalanuvchi adminmi?
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        await message.answer("❌ Faqat admin ro'yxatga olishi mumkin."); return

    # Guruhni saqlash
    group_id   = message.chat.id
    group_name = message.chat.title or str(group_id)

    existing = (await db.execute(
        select(TelegramGroup).where(TelegramGroup.group_id == group_id)
    )).scalar_one_or_none()

    if existing:
        existing.group_type = group_type
        existing.group_name = group_name
        existing.is_active  = True
    else:
        db.add(TelegramGroup(
            group_id=group_id,
            group_name=group_name,
            group_type=group_type,
            added_by=user.id,
        ))

    await db.commit()
    type_labels = {
        GroupType.inspector: "Nazoratchilar",
        GroupType.admin:     "Admin",
        GroupType.ishchi:    "Ishchilar",
        GroupType.hisobot:   "Hisobotlar",
    }
    await message.answer(
        f"✅ <b>{group_name}</b> guruhi ro'yxatga olindi!\n"
        f"Tur: {type_labels[group_type]}",
        parse_mode="HTML",
    )


@router.message(Command("removegroup"))
async def remove_group(message: Message, db: AsyncSession):
    """Guruhni ro'yxatdan o'chirish."""
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Bu buyruq faqat guruhda ishlaydi."); return

    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        await message.answer("❌ Faqat admin."); return

    existing = (await db.execute(
        select(TelegramGroup).where(TelegramGroup.group_id == message.chat.id)
    )).scalar_one_or_none()

    if existing:
        existing.is_active = False
        await db.commit()
        await message.answer("✅ Guruh o'chirildi.")
    else:
        await message.answer("Bu guruh ro'yxatda yo'q.")


@router.message(Command("groups"))
async def list_groups(message: Message, db: AsyncSession):
    """Ro'yxatdagi guruhlarni ko'rish (admin uchun)."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        await message.answer("❌ Ruxsat yo'q."); return

    groups = (await db.execute(
        select(TelegramGroup).where(TelegramGroup.is_active == True)
    )).scalars().all()

    if not groups:
        await message.answer("Hech qanday guruh ro'yxatga olinmagan.\n\nGuruhlarda /setgroup {tur} buyrug'ini yuboring.")
        return

    type_labels = {
        GroupType.inspector: "🔍 Nazoratchilar",
        GroupType.admin:     "👑 Admin",
        GroupType.ishchi:    "👷 Ishchilar",
        GroupType.hisobot:   "📊 Hisobotlar",
    }
    text = "📋 <b>Ro'yxatdagi guruhlar:</b>\n\n"
    for g in groups:
        text += f"{type_labels.get(g.group_type, g.group_type.value)}: <b>{g.group_name}</b> ({g.group_id})\n"

    await message.answer(text, parse_mode="HTML")


# ═══ GURUHGA XABAR YUBORISH YORDAMCHI ══════════════════════════════════════════

async def send_to_groups(
    bot,
    db: AsyncSession,
    group_type: GroupType,
    text: str,
    **kwargs,
) -> int:
    """
    Berilgan turdagi guruhlarga xabar yuborish.
    Qaytaradi: yuborilgan guruhlar soni.
    """
    try:
        groups = (await db.execute(
            select(TelegramGroup).where(
                TelegramGroup.group_type == group_type,
                TelegramGroup.is_active  == True,
            )
        )).scalars().all()

        sent = 0
        for g in groups:
            try:
                await bot.send_message(g.group_id, text, parse_mode="HTML", **kwargs)
                sent += 1
            except Exception as e:
                logger.warning("Guruhlarga yuborishda xato (%s): %s", g.group_id, e)
        return sent
    except Exception as e:
        logger.error("send_to_groups xatosi: %s", e)
        return 0


async def notify_new_work(bot, db: AsyncSession, worker_name: str, work_type: str, summa: float):
    """Yangi ish kiritilganda nazoratchi guruhiga xabar."""
    await send_to_groups(
        bot, db, GroupType.inspector,
        f"📋 Yangi ish!\n"
        f"👷 {worker_name}\n"
        f"🔧 {work_type}\n"
        f"💰 {summa:,.0f} so'm",
    )


async def notify_low_stock(bot, db: AsyncSession, products: list):
    """Kam qolgan mahsulotlar haqida admin guruhiga."""
    if not products:
        return
    text = "⚠️ <b>Omborda kam qolgan mahsulotlar:</b>\n\n"
    for p in products[:15]:
        text += f"🔴 {p.name}: {p.miqdor:.0f} {p.birlik}\n"
    if len(products) > 15:
        text += f"... va yana {len(products) - 15} ta\n"
    await send_to_groups(bot, db, GroupType.admin, text)


async def notify_salary_paid(bot, db: AsyncSession, worker_name: str, summa: float, oy: int, yil: int):
    """Maosh tasdiqlanganda ishchilar guruhiga."""
    await send_to_groups(
        bot, db, GroupType.hisobot,
        f"💰 Maosh tasdiqlandi!\n"
        f"👤 {worker_name}\n"
        f"📅 {MONTHS_UZ[oy]} {yil}\n"
        f"💵 {summa:,.0f} so'm",
    )
