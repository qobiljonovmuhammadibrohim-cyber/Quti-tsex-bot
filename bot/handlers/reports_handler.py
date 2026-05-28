"""
reports_handler.py — TUZATILGAN
TUZATISHLAR:
  1. Import: utils.scheduler_full → utils.scheduler (to'g'ri modul nomi)
  2. generate_daily_excel: report_date=date.today() aniq uzatiladi
"""
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime

from database.models import UserRole
from database.queries import get_user
from utils.reports import (
    generate_daily_excel,
    generate_weekly_excel,
    generate_monthly_excel,
)

router = Router()

ALLOWED = (UserRole.admin, UserRole.superadmin, UserRole.nazoratchi)
ADMIN_ONLY = (UserRole.admin, UserRole.superadmin)


@router.message(F.text == "Hisobotlar")
async def hisobotlar(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("❌ Ruxsat yo'q."); return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Kunlik (bugun)",   callback_data="rep_daily")],
        [InlineKeyboardButton(text="📆 Haftalik",         callback_data="rep_weekly")],
        [InlineKeyboardButton(text="🗓 Oylik",            callback_data="rep_monthly")],
        [InlineKeyboardButton(text="📤 Adminga yuborish", callback_data="rep_send_menu")],
    ])
    await message.answer("📊 Qaysi hisobot?", reply_markup=kb)


# ═══ YUKLAB OLISH ═════════════════════════════════════════════════════════════

@router.callback_query(F.data == "rep_daily")
async def rep_daily(cb: CallbackQuery, db: AsyncSession):
    await cb.message.answer("⏳ Tayyorlanmoqda...")
    today = date.today()
    # TUZATILDI: report_date aniq uzatiladi
    data  = await generate_daily_excel(db, report_date=today)
    await cb.message.answer_document(
        BufferedInputFile(data.read(), filename=f"kunlik_{today}.xlsx"),
        caption=f"📊 Kunlik hisobot — {today.strftime('%d.%m.%Y')}",
    )
    await cb.answer()


@router.callback_query(F.data == "rep_weekly")
async def rep_weekly(cb: CallbackQuery, db: AsyncSession):
    await cb.message.answer("⏳ Tayyorlanmoqda...")
    today = date.today()
    data  = await generate_weekly_excel(db)
    await cb.message.answer_document(
        BufferedInputFile(data.read(), filename=f"haftalik_{today}.xlsx"),
        caption=f"📆 Haftalik hisobot — {today.strftime('%d.%m.%Y')}",
    )
    await cb.answer()


@router.callback_query(F.data == "rep_monthly")
async def rep_monthly(cb: CallbackQuery, db: AsyncSession):
    await cb.message.answer("⏳ Tayyorlanmoqda...")
    now  = datetime.now()
    data = await generate_monthly_excel(db, now.month, now.year)
    await cb.message.answer_document(
        BufferedInputFile(data.read(), filename=f"oylik_{now.month}_{now.year}.xlsx"),
        caption=f"🗓 Oylik hisobot — {now.month}/{now.year}",
    )
    await cb.answer()


# ═══ QO'LDA YUBORISH MENYUSI ══════════════════════════════════════════════════

@router.callback_query(F.data == "rep_send_menu")
async def rep_send_menu(cb: CallbackQuery, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user or user.role not in ADMIN_ONLY:
        await cb.answer("Faqat admin uchun", show_alert=True); return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kunlik → Adminga",   callback_data="rep_send_daily")],
        [InlineKeyboardButton(text="📆 Haftalik → Adminga", callback_data="rep_send_weekly")],
        [InlineKeyboardButton(text="💰 Oylik → Adminga",    callback_data="rep_send_monthly")],
        [InlineKeyboardButton(text="🏭 Ombor eslatma",      callback_data="rep_send_warehouse")],
        [InlineKeyboardButton(text="❌ Bekor",               callback_data="rep_cancel")],
    ])
    await cb.message.answer("📤 Qaysi hisobotni hozir yuborasiz?", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("rep_send_"))
async def rep_send_now(cb: CallbackQuery, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user or user.role not in ADMIN_ONLY:
        await cb.answer("Faqat admin uchun", show_alert=True); return

    report_type = cb.data.replace("rep_send_", "")

    # "rep_send_menu" callbacki bu handlerga ham tushib qolmasligi uchun
    if report_type == "menu":
        await cb.answer(); return

    type_labels = {
        "daily":     "📊 Kunlik hisobot",
        "weekly":    "📆 Haftalik hisobot",
        "monthly":   "💰 Oylik hisobot",
        "warehouse": "🏭 Ombor eslatma",
    }
    label = type_labels.get(report_type, report_type)

    await cb.message.answer(f"⏳ {label} yuborilmoqda...")

    # TUZATILDI: to'g'ri modul nomi — scheduler_full emas, scheduler
    try:
        from utils.scheduler import send_report_now
        ok = await send_report_now(cb.bot, report_type)
    except ImportError:
        ok = False

    if ok:
        await cb.message.answer(f"✅ {label} muvaffaqiyatli yuborildi!")
    else:
        await cb.message.answer(f"❌ Yuborishda xato yuz berdi.")

    await cb.answer()


@router.callback_query(F.data == "rep_cancel")
async def rep_cancel(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer("Bekor qilindi")
