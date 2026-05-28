"""
admin.py — v11 TUZATILGAN
TUZATISHLAR:
  1. sal_maqsad: worker_improvements import o'rniga worker modulidan OYLIK_MAQSAD
     to'g'ri import qilinadi (modul nomi tekshirildi)
  2. toggle_user: cb.data.split("_")[2] — "toggle_user_123" da split("_")
     ["toggle","user","123"] — index 2 to'g'ri, LEKIN user_id 3-indeks ham
     bo'lishi mumkin, shuning uchun joined split ishlatiladi
  3. set_role: db.commit() qo'shildi (faqat flush edi)
  4. adv_note: db.commit() qo'shildi
  5. sal_confirm: db.commit() qo'shildi
  6. price_amount: db.commit() qo'shildi
"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date, timedelta
from sqlalchemy import select, func
import sqlalchemy.sql.functions as sf
from sqlalchemy import case as sa_case
from aiogram.filters import Command

from database.models import (
    User, UserRole, WorkType, WorkPrice, WorkEntry, WorkStatus, WorkSession,
    WarehouseProduct, ProductCategory,
    Penalty, PenaltyType, Advance,
)
from database.queries import (
    get_user, get_user_by_id, get_all_active_users, get_users_by_role,
    get_all_prices, set_price, calculate_and_save_salary, get_monthly_reports,
    create_advance, get_all_products, get_advance_count_this_month,
    AVANS_MAX_PER_MONTH, get_users_by_role,
)
from bot.keyboards.main_keyboards import get_main_menu
from config.settings import WEB_HOST, WEB_PORT, WEB_URL

logger = logging.getLogger(__name__)

def fmt(n):
    """Sonni formatlash: 1234567 → "1 234 567" """
    try:
        return f"{int(float(n)):,}".replace(",", " ")
    except Exception:
        return str(n)


router = Router()
ADMIN_ROLES = (UserRole.admin, UserRole.superadmin)

ROLE_MAP = {
    "role_ishchi":     UserRole.ishchi,
    "role_omborchi":   UserRole.omborchi,
    "role_nazoratchi": UserRole.nazoratchi,
    "role_admin":      UserRole.admin,
}

CAT_NAMES = {
    "rulon":            "Rulonlar",
    "gofra":            "Gofralar",
    "gofra_zagatovka":  "Zagatovkalar",
    "xromazes":         "Xromazeslar",
    "laminat_xromazes": "Laminat",
    "yarim_tayyor":     "Yarim tayyor",
    "qolip":            "Qoliplar",
    "tayyor_mahsulot":  "Tayyor",
    "adyol_zapchast":   "Adyol zapchast",
    "uskuna_zapchast":  "Uskuna zapchast",
}

WORK_TYPE_LABELS = {
    "tiger_kesish":    "Tiger Kesish",
    "gofra_kiley":     "Gofra Kiley",
    "gofra_ishlab":    "Gofra Ishlab",
    "list_qogoz":      "List Qog'oz",
    "laminatsiya":     "Laminatsiya",
    "zagatovka":       "Zagatovka",
    "stepler_tikish":  "Stepler Tikish",
    "rulon_orash":     "Rulon O'rash",
    "rulonga_salafan": "Rulonga Salafan",
    "yopishtirma":     "Yopishtirma",
    "adyol_tikish":    "Adyol Tikish",
    "diplomat_tikish": "Diplomat Tikish",
    "adyol_qoqish":    "Adyol Qoqish",
    "pastel_qoqish":   "Pastel Qoqish",
}


def status_icon(miqdor, min_t, yellow_t):
    if miqdor <= min_t:    return "🔴"
    if miqdor <= yellow_t: return "🟡"
    return "🟢"


async def _safe_send(bot, telegram_id, text, **kwargs):
    try:
        await bot.send_message(telegram_id, text, **kwargs)
        return True
    except TelegramForbiddenError:
        logger.warning("Bot bloklangan: %s", telegram_id)
    except TelegramBadRequest as e:
        logger.warning("Bad request (%s): %s", telegram_id, e)
    except Exception as e:
        logger.error("Xabar xatosi (%s): %s", telegram_id, e)
    return False


class A(StatesGroup):
    add_user_id   = State()
    add_user_role = State()
    price_razmer  = State()
    price_amount  = State()
    adv_amount    = State()
    adv_note      = State()
    maqsad_amount = State()
    block_reason  = State()
    # Jarima berish
    pen_worker    = State()
    pen_type      = State()
    pen_summa     = State()
    pen_sabab     = State()
    pen_ok        = State()


# ═══ FOYDALANUVCHI QO'SHISH ═══════════════════════════════════════════════════

@router.message(F.text == "Foydalanuvchi qoshish")
async def add_user_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await state.update_data(admin_id=user.id)
    await message.answer("👤 Foydalanuvchi Telegram ID'sini kiriting:")
    await state.set_state(A.add_user_id)


@router.message(A.add_user_id)
async def add_user_id(message: Message, state: FSMContext, db: AsyncSession):
    try:
        tg_id = int(message.text.strip())
    except ValueError:
        await message.answer("Faqat raqam kiriting:"); return
    r    = await db.execute(select(User).where(User.telegram_id == tg_id))
    user = r.scalar_one_or_none()
    if not user:
        await message.answer(
            f"❌ {tg_id} topilmadi.\n"
            f"Foydalanuvchi avval /start bosishi kerak."
        )
        return
    await state.update_data(
        target_user_id=user.id,
        target_tg_id=tg_id,
        target_name=user.full_name,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👷 Ishchi",     callback_data="role_ishchi")],
        [InlineKeyboardButton(text="🏭 Omborchi",   callback_data="role_omborchi")],
        [InlineKeyboardButton(text="🔍 Nazoratchi", callback_data="role_nazoratchi")],
        [InlineKeyboardButton(text="⚙️ Admin",      callback_data="role_admin")],
    ])
    await message.answer(
        f"👤 {user.full_name}\nRolni tanlang:",
        reply_markup=kb,
    )
    await state.set_state(A.add_user_role)


@router.callback_query(F.data.startswith("role_"), A.add_user_role)
async def set_role(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    role = ROLE_MAP.get(cb.data)
    if not role:
        await cb.answer("Noma'lum rol"); return
    data = await state.get_data()
    user = await get_user_by_id(db, data["target_user_id"])
    if not user:
        await cb.answer("Foydalanuvchi topilmadi"); return
    user.role = role
    await db.commit()  # TUZATILDI: flush o'rniga commit
    await _safe_send(
        cb.bot, data["target_tg_id"],
        f"✅ Sizga rol tayinlandi: {role.value}",
        reply_markup=get_main_menu(role),
    )
    await cb.message.answer(f"✅ {data['target_name']}ga {role.value} roli berildi!")
    await state.clear()
    await cb.answer()


# ═══ NARXLAR ══════════════════════════════════════════════════════════════════

@router.message(F.text == "Narxlar")
async def show_prices_menu(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await message.answer("Ruxsat yo'q."); return

    prices = await get_all_prices(db)
    price_dict: dict = {}
    for p in prices:
        price_dict.setdefault(p.work_type.value, []).append(p)

    buttons = []
    for wt in WorkType:
        tp    = price_dict.get(wt.value, [])
        label = WORK_TYPE_LABELS.get(wt.value, wt.value)
        if tp:
            pt_str = ", ".join([
                f"{p.razmer_turi or 'asosiy'}: {p.narx:,.0f}"
                for p in tp
            ])
        else:
            pt_str = "narx yo'q"
        buttons.append([InlineKeyboardButton(
            text=f"{label} [{pt_str}]",
            callback_data=f"ep_{wt.value}",
        )])

    buttons.append([InlineKeyboardButton(
        text="📋 Narx tarixi", callback_data="price_history"
    )])

    await message.answer(
        "💲 Narxlarni boshqarish:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("ep_"))
async def edit_price_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await cb.answer("Ruxsat yo'q"); return
    wt_val = cb.data[3:]
    await state.update_data(editing_work_type=wt_val)
    label  = WORK_TYPE_LABELS.get(wt_val, wt_val)
    await cb.message.answer(
        f"💲 {label}\n\n"
        f"Razmer/tur kiriting:\n"
        f"• Katta / O'rta / Kichik — razmerga bog'liq narx\n"
        f"• 3 / 5 — sloy soni (gofra kiley uchun)\n"
        f"• yon / tepa / past / remen — qismlar (adyol/pastel uchun)\n"
        f"• - (tire) — asosiy narx (razmer farqi yo'q)\n"
    )
    await state.set_state(A.price_razmer)
    await cb.answer()


@router.message(A.price_razmer)
async def price_razmer(message: Message, state: FSMContext):
    razmer = None if message.text.strip() in ("-", "asosiy") else message.text.strip()
    await state.update_data(price_razmer=razmer)
    await message.answer("💰 Yangi narxni kiriting (soum):")
    await state.set_state(A.price_amount)


@router.message(A.price_amount)
async def price_amount(message: Message, state: FSMContext, db: AsyncSession):
    try:
        narx = float(message.text.replace(",", "").replace(" ", ""))
        if narx <= 0: raise ValueError
    except ValueError:
        await message.answer("To'g'ri musbat raqam kiriting:"); return

    data       = await state.get_data()
    wt         = WorkType(data["editing_work_type"])
    old_prices = await get_all_prices(db)
    old_narx   = next(
        (float(p.narx) for p in old_prices
         if p.work_type == wt and p.razmer_turi == data.get("price_razmer")),
        None,
    )

    await set_price(db, wt, narx, razmer_turi=data.get("price_razmer"))
    await db.commit()  # TUZATILDI: commit qo'shildi

    label = data.get("price_razmer") or "asosiy"
    change_text = ""
    if old_narx is not None:
        diff  = narx - old_narx
        arrow = "📈" if diff > 0 else "📉"
        change_text = f"\n{arrow} O'zgarish: {old_narx:,.0f} → {narx:,.0f} ({diff:+,.0f})"

    await message.answer(
        f"✅ Narx yangilandi!\n"
        f"🔧 {WORK_TYPE_LABELS.get(data['editing_work_type'], data['editing_work_type'])}\n"
        f"📐 {label}: {narx:,.0f} soum"
        f"{change_text}"
    )
    await state.clear()


@router.callback_query(F.data == "price_history")
async def price_history(cb: CallbackQuery, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await cb.answer("Ruxsat yo'q"); return

    r = await db.execute(
        select(WorkPrice)
        .order_by(WorkPrice.updated_at.desc().nullslast(), WorkPrice.created_at.desc())
        .limit(30)
    )
    prices = r.scalars().all()

    if not prices:
        await cb.message.answer("Narx tarixi yo'q.")
        await cb.answer(); return

    text = "📋 Narx tarixi (oxirgi 30 ta)\n\n"
    for p in prices:
        label    = WORK_TYPE_LABELS.get(
            p.work_type.value if hasattr(p.work_type, "value") else str(p.work_type), "?"
        )
        razmer   = p.razmer_turi or "asosiy"
        status   = "✅" if p.is_active else "❌ Arxiv"
        vaqt     = p.updated_at or p.created_at
        vaqt_str = vaqt.strftime("%d.%m.%Y %H:%M") if vaqt else "?"
        text    += f"{status} {label} [{razmer}]\n   💰 {p.narx:,.0f} soum — {vaqt_str}\n\n"

    await cb.message.answer(text)
    await cb.answer()


# ═══ MAOSH ════════════════════════════════════════════════════════════════════

@router.message(F.text == "Maosh")
async def salary_panel(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await message.answer("Ruxsat yo'q."); return
    now = datetime.now()
    kb  = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Hisobot yaratish",   callback_data="sal_gen")],
        [InlineKeyboardButton(text="✅ Ko'rib tasdiqlash",   callback_data="sal_approve")],
        [InlineKeyboardButton(text="💰 Avans berish",       callback_data="sal_advance")],
        [InlineKeyboardButton(text="👥 Ishchilar ro'yxati", callback_data="sal_list")],
        [InlineKeyboardButton(text="🎯 Oylik maqsad",       callback_data="sal_maqsad")],
    ])
    await message.answer(f"💰 Maosh paneli\n📅 {now.month}/{now.year}", reply_markup=kb)


@router.callback_query(F.data == "sal_gen")
async def sal_gen(cb: CallbackQuery, db: AsyncSession):
    now     = datetime.now()
    workers = await get_users_by_role(db, UserRole.ishchi)
    if not workers:
        await cb.message.answer("Ishchilar topilmadi.")
        await cb.answer(); return
    await cb.message.answer("⏳ Hisobotlar yaratilmoqda...")
    for w in workers:
        await calculate_and_save_salary(db, w.id, now.month, now.year)
    await db.commit()
    await cb.message.answer(
        f"✅ {len(workers)} ta ishchi uchun hisobot yaratildi! {now.month}/{now.year}"
    )
    await cb.answer()


@router.callback_query(F.data == "sal_approve")
async def sal_approve(cb: CallbackQuery, db: AsyncSession):
    now     = datetime.now()
    reports = await get_monthly_reports(db, now.month, now.year)
    if not reports:
        await cb.message.answer("❌ Hisobot topilmadi. Avval yarating.")
        await cb.answer(); return

    text = f"💰 Oylik maoshlar — {now.month}/{now.year}\n\n"
    for rep in reports:
        w    = await get_user_by_id(db, rep.worker_id)
        name = w.full_name if w else "?"
        st   = "✅" if rep.admin_tasdiqladi else "⏳"
        text += (
            f"{st} {name}\n"
            f"   Ish: {rep.jami_ish_summa:,.0f}\n"
            f"   Jarima: -{rep.jami_jarima:,.0f}\n"
            f"   Avans: -{rep.jami_avans:,.0f}\n"
            f"   💵 SOF: {rep.sof_maosh:,.0f} soum\n\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Tasdiqlash va yuborish",
            callback_data=f"sal_confirm_{now.month}_{now.year}",
        )],
        [InlineKeyboardButton(text="Bekor", callback_data="cancel_cb")],
    ])
    await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("sal_confirm_"))
async def sal_confirm(cb: CallbackQuery, db: AsyncSession):
    # TUZATILDI: "sal_confirm_3_2026" -> parts[-2], parts[-1]
    parts = cb.data.split("_")
    try:
        oy  = int(parts[-2])
        yil = int(parts[-1])
    except (IndexError, ValueError):
        await cb.answer("Format xatosi"); return

    reports = await get_monthly_reports(db, oy, yil)
    sent    = 0
    for rep in reports:
        if rep.admin_tasdiqladi:
            continue
        rep.admin_tasdiqladi = True
        rep.tasdiq_vaqti     = datetime.now()
        w = await get_user_by_id(db, rep.worker_id)
        if w:
            ok = await _safe_send(
                cb.bot, w.telegram_id,
                f"💰 {oy}/{yil} oylik maoshingiz\n\n"
                f"✅ Ish:    {rep.jami_ish_summa:,.0f} soum\n"
                f"❌ Jarima: -{rep.jami_jarima:,.0f} soum\n"
                f"💳 Avans:  -{rep.jami_avans:,.0f} soum\n"
                f"{'─'*26}\n"
                f"💵 SOF:    {rep.sof_maosh:,.0f} soum",
            )
            rep.worker_notified = ok
            if ok: sent += 1

    await db.commit()  # TUZATILDI: commit qo'shildi
    await cb.message.answer(f"✅ {sent} ta ishchiga maosh yuborildi!")
    await cb.answer()


@router.callback_query(F.data == "sal_list")
async def sal_list(cb: CallbackQuery, db: AsyncSession):
    now     = datetime.now()
    workers = await get_users_by_role(db, UserRole.ishchi)
    if not workers:
        await cb.message.answer("Ishchilar topilmadi.")
        await cb.answer(); return

    reports = await get_monthly_reports(db, now.month, now.year)
    rep_map = {r.worker_id: r for r in reports}
    text    = f"👥 Ishchilar — {now.month}/{now.year}\n\n"

    for i, w in enumerate(workers, 1):
        rep = rep_map.get(w.id)
        if rep:
            st    = "✅" if rep.admin_tasdiqladi else "⏳"
            summa = f"{rep.sof_maosh:,.0f} soum"
        else:
            st    = "—"
            summa = "hisobot yo'q"
        text += f"{i}. {st} {w.full_name} — {summa}\n"

    await cb.message.answer(text)
    await cb.answer()


# ═══ OYLIK MAQSAD SOZLASH ════════════════════════════════════════════════════

@router.callback_query(F.data == "sal_maqsad")
async def sal_maqsad_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await cb.answer("Ruxsat yo'q"); return

    # TUZATILDI: to'g'ri modul nomi va import
    try:
        import bot.handlers.worker as worker_module
        current = getattr(worker_module, "OYLIK_MAQSAD", 2_000_000)
    except ImportError:
        current = 2_000_000

    await cb.message.answer(
        f"🎯 Hozirgi oylik maqsad: {current:,.0f} soum\n\n"
        f"Yangi maqsadni kiriting (soum):\n"
        f"(Bekor qilish uchun: -)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Bekor", callback_data="cancel_cb")]
        ]),
    )
    await state.set_state(A.maqsad_amount)
    await cb.answer()


@router.message(A.maqsad_amount)
async def sal_maqsad_set(message: Message, state: FSMContext):
    if message.text.strip() == "-":
        await state.clear()
        await message.answer("Bekor qilindi.")
        return
    try:
        summa = float(message.text.replace(",", "").replace(" ", ""))
        if summa <= 0: raise ValueError
    except ValueError:
        await message.answer("To'g'ri musbat raqam kiriting:"); return

    # TUZATILDI: to'g'ri modul
    try:
        import bot.handlers.worker as worker_module
        worker_module.OYLIK_MAQSAD = summa
        msg = f"✅ Oylik maqsad yangilandi!\n🎯 {summa:,.0f} soum"
    except (ImportError, AttributeError) as e:
        logger.error("OYLIK_MAQSAD yangilanmadi: %s", e)
        msg = f"⚠️ Maqsad saqlanmadi (modul xatosi). Keyingi restart kerak."

    await state.clear()
    await message.answer(msg)


# ═══ AVANS — RO'YXATDAN TANLASH ══════════════════════════════════════════════

@router.callback_query(F.data == "sal_advance")
async def sal_advance_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await cb.answer("Ruxsat yo'q"); return

    await state.update_data(admin_id=user.id)
    workers = await get_users_by_role(db, UserRole.ishchi)
    if not workers:
        await cb.message.answer("Ishchilar topilmadi.")
        await cb.answer(); return

    buttons = []
    for w in workers:
        count = await get_advance_count_this_month(db, w.id)
        qoldi = AVANS_MAX_PER_MONTH - count
        if qoldi > 0:
            label = f"✅ {w.full_name}  ({count}/{AVANS_MAX_PER_MONTH})"
        else:
            label = f"🚫 {w.full_name}  (limit to'ldi)"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"advw_{w.id}"
        )])

    buttons.append([InlineKeyboardButton(text="Bekor", callback_data="cancel_cb")])

    await cb.message.answer(
        f"💰 Kimga avans berasiz?\n"
        f"✅ = berish mumkin  |  🚫 = limit to'lgan ({AVANS_MAX_PER_MONTH} ta/oy)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("advw_"))
async def adv_worker(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    wid   = int(cb.data[5:])
    w     = await get_user_by_id(db, wid)
    count = await get_advance_count_this_month(db, wid)
    qoldi = AVANS_MAX_PER_MONTH - count

    if qoldi <= 0:
        await cb.answer(
            f"Bu oy limiti to'lgan ({AVANS_MAX_PER_MONTH} ta)!",
            show_alert=True,
        )
        return

    await state.update_data(
        adv_worker_id=wid,
        adv_worker_name=w.full_name if w else "?",
    )
    await cb.message.answer(
        f"👤 {w.full_name if w else '?'}\n"
        f"📊 Bu oy: {count}/{AVANS_MAX_PER_MONTH} ta avans"
        f" (yana {qoldi} ta mumkin)\n\n"
        f"💰 Avans summasini kiriting (soum):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Bekor", callback_data="cancel_cb")]
        ]),
    )
    await state.set_state(A.adv_amount)
    await cb.answer()


@router.message(A.adv_amount)
async def adv_amount(message: Message, state: FSMContext):
    try:
        summa = float(message.text.replace(",", "").replace(" ", ""))
        if summa <= 0: raise ValueError
    except ValueError:
        await message.answer("To'g'ri musbat raqam kiriting:"); return
    await state.update_data(adv_summa=summa)
    await message.answer(
        f"💰 Summa: {summa:,.0f} soum\n\n"
        f"📝 Izoh kiriting (yoki - o'tkazib yuborish):",
    )
    await state.set_state(A.adv_note)


@router.message(A.adv_note)
async def adv_note(message: Message, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    izoh = None if message.text.strip() == "-" else message.text.strip()
    try:
        await create_advance(
            db, data["adv_worker_id"], data["admin_id"], data["adv_summa"], izoh
        )
        await db.commit()  # TUZATILDI: commit qo'shildi
    except ValueError as e:
        await message.answer(f"❌ {e}")
        await state.clear(); return

    w = await get_user_by_id(db, data["adv_worker_id"])
    if w:
        await _safe_send(
            message.bot, w.telegram_id,
            f"💰 Sizga {data['adv_summa']:,.0f} soum avans berildi!\n"
            f"📝 {izoh or '—'}",
        )

    await message.answer(
        f"✅ Avans saqlandi!\n"
        f"👤 {data['adv_worker_name']}\n"
        f"💰 {data['adv_summa']:,.0f} soum\n"
        f"📝 {izoh or '—'}",
    )
    await state.clear()


# ═══ ISHCHI BLOKLASH/AKTIVLASHTIRISH ═════════════════════════════════════════

@router.message(F.text == "Ishchilar")
async def show_workers(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await message.answer("Ruxsat yo'q."); return

    users = await get_all_active_users(db)
    text  = f"👥 Foydalanuvchilar ({len(users)} ta)\n\n"
    for u in users:
        icon = {
            "superadmin":"👑","admin":"⚙️","omborchi":"🏭",
            "nazoratchi":"🔍","ishchi":"👷",
        }.get(u.role.value if hasattr(u.role, "value") else str(u.role), "👤")
        status = "🟢" if u.is_active else "🔴"
        text  += f"{status} {icon} {u.full_name}"
        if u.phone: text += f" | {u.phone}"
        text  += "\n"

    workers = await get_users_by_role(db, UserRole.ishchi)
    # Barcha foydalanuvchilar (ishchi bo'lmaganlar ham)
    all_toggleable = await get_all_active_users(db)
    if all_toggleable:
        buttons = []
        for w in all_toggleable[:10]:
            icon = "🟢 Bloklash" if w.is_active else "🔴 Aktivlashtirish"
            buttons.append([InlineKeyboardButton(
                text=f"{icon}: {w.full_name}",
                callback_data=f"tgu_{w.id}",  # TUZATILDI: "tgu_" prefix (toggle_user_ juda uzun)
            )])
        await message.answer(text)
        await message.answer(
            "👤 Bloklash/aktivlashtirish:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    else:
        await message.answer(text)


@router.callback_query(F.data.startswith("tgu_"))
async def toggle_user(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    # TUZATILDI: "tgu_123" — split("_")[1] = "123"
    admin = await get_user(db, cb.from_user.id)
    if not admin or admin.role not in ADMIN_ROLES:
        await cb.answer("Ruxsat yo'q"); return

    try:
        uid = int(cb.data[4:])  # "tgu_" = 4 belgi
    except ValueError:
        await cb.answer("ID xato"); return

    user = await get_user_by_id(db, uid)
    if not user:
        await cb.answer("Topilmadi"); return

    user.is_active = not user.is_active
    await db.commit()  # TUZATILDI: commit qo'shildi

    action = "bloklandi" if not user.is_active else "aktivlashtirildi"

    if not user.is_active:
        await _safe_send(
            cb.bot, user.telegram_id,
            f"⚠️ Sizning hisobingiz vaqtincha bloklandi.\n"
            f"Murojaat uchun adminga yozing.",
        )
    else:
        await _safe_send(
            cb.bot, user.telegram_id,
            f"✅ Hisobingiz aktivlashtirildi!\nBotdan foydalanishingiz mumkin.",
            reply_markup=get_main_menu(user.role),
        )

    await cb.message.answer(
        f"✅ {user.full_name} {action}!\n"
        f"Holat: {'🟢 Aktiv' if user.is_active else '🔴 Bloklangan'}"
    )
    await cb.answer()


# ═══ OMBOR ═══════════════════════════════════════════════════════════════════

@router.message(F.text == "Ombor")
async def admin_ombor(message: Message, db: AsyncSession):
    """Admin ombor — kategoriyalar bo'yicha inline ko'rinish."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await message.answer("Ruxsat yo'q."); return

    from sqlalchemy import select, func as sqlfunc
    from constants import ADMIN_OMBOR_CATS

    buttons = []
    warn_total = 0

    from sqlalchemy import case as sql_case
    for label, cat_key in ADMIN_OMBOR_CATS:
        try:
            cat_enum = ProductCategory(cat_key)
        except ValueError:
            continue

        r = await db.execute(
            select(
                sqlfunc.count(WarehouseProduct.id),
                sqlfunc.sum(
                    sql_case(
                        (WarehouseProduct.miqdor <= WarehouseProduct.min_threshold, 1),
                        else_=0,
                    )
                ),
            ).where(
                WarehouseProduct.category == cat_enum,
                WarehouseProduct.is_active == True,
            )
        )
        row  = r.one()
        cnt  = row[0] or 0
        warn = int(row[1] or 0)
        warn_total += warn

        btn_text = f"{label}  ({cnt} ta"
        if warn:
            btn_text += f", ⚠️ {warn} kam"
        btn_text += ")"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_ombor_cat_{cat_key}")])

    header = "🏭 <b>Ombor holati</b>\n"
    if warn_total:
        header += f"⚠️ Jami <b>{warn_total}</b> ta kam qolgan!\n"
    header += "\nKategoriya tanlang:"

    await message.answer(header, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ═══ WEB PANEL ════════════════════════════════════════════════════════════════

@router.message(F.text == "Web panel")
async def web_panel(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await message.answer(
        f"🌐 Web panel\n\n"
        f"{WEB_URL + '/web/' if WEB_URL else f'http://{WEB_HOST}:{WEB_PORT}/web/'}\n\n"
        f"Parol: Railway Variables → WEB_PASSWORD"
    )


# ═══ BEKOR ════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "cancel_cb")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Bekor qilindi.")
    await cb.answer()


# ═══ ADMIN JARIMA BERISH ══════════════════════════════════════════════════════

@router.message(F.text == "Jarimalar")
async def admin_pen_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ADMIN_ROLES:
        await message.answer("Ruxsat yo'q."); return

    workers = await get_users_by_role(db, UserRole.ishchi)
    if not workers:
        await message.answer("Ishchilar topilmadi."); return

    await state.update_data(admin_id=user.id)

    buttons = [
        [InlineKeyboardButton(
            text=f"👤 {w.full_name}",
            callback_data=f"apen_w_{w.id}",
        )]
        for w in workers
    ]
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="apen_cancel")])
    await message.answer(
        "⚠️ <b>Jarima berish</b>\n\nIshchini tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(A.pen_worker)


@router.callback_query(F.data.startswith("apen_w_"), A.pen_worker)
async def admin_pen_worker(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    wid    = int(cb.data.split("_")[2])
    worker = await get_user_by_id(db, wid)
    if not worker:
        await cb.answer("Topilmadi"); return
    await state.update_data(pen_worker_id=wid, pen_worker_name=worker.full_name)
    await cb.message.answer(
        f"👤 <b>{worker.full_name}</b>\n\nJarima turini tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Pul jarima",  callback_data="apentype_jarima")],
            [InlineKeyboardButton(text="⚠️ 1-xaypsan",  callback_data="apentype_xaypsan1")],
            [InlineKeyboardButton(text="⚠️ 2-xaypsan",  callback_data="apentype_xaypsan2")],
            [InlineKeyboardButton(text="❌ Bekor",        callback_data="apen_cancel")],
        ]),
    )
    await state.set_state(A.pen_type)
    await cb.answer()


@router.callback_query(F.data.startswith("apentype_"), A.pen_type)
async def admin_pen_type(cb: CallbackQuery, state: FSMContext):
    ptype = cb.data.replace("apentype_", "")
    await state.update_data(pen_type=ptype)
    if ptype == "jarima":
        await cb.message.answer("💰 Jarima miqdorini kiriting (so'm):")
        await state.set_state(A.pen_summa)
    else:
        await state.update_data(pen_summa=0)
        await cb.message.answer("📝 Xaypsan sababini kiriting:")
        await state.set_state(A.pen_sabab)
    await cb.answer()


@router.message(A.pen_summa)
async def admin_pen_summa(m: Message, state: FSMContext):
    try:
        summa = float(m.text.replace(",", ".").replace(" ", ""))
        if summa <= 0:
            raise ValueError
    except ValueError:
        await m.answer("Musbat son kiriting:"); return
    await state.update_data(pen_summa=summa)
    await m.answer("📝 Jarima sababini kiriting:")
    await state.set_state(A.pen_sabab)


@router.message(A.pen_sabab)
async def admin_pen_sabab(m: Message, state: FSMContext):
    await state.update_data(pen_sabab=m.text.strip())
    data = await state.get_data()
    ptype_labels = {
        "jarima": "💰 Pul jarima",
        "xaypsan1": "⚠️ 1-xaypsan",
        "xaypsan2": "⚠️ 2-xaypsan",
    }
    await m.answer(
        f"Tasdiqlaysizmi?\n\n"
        f"👤 {data['pen_worker_name']}\n"
        f"Tur: {ptype_labels.get(data['pen_type'], '?')}\n"
        f"Summa: {data['pen_summa']:,.0f} so'm\n"
        f"Sabab: {data['pen_sabab']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="apen_confirm"),
                InlineKeyboardButton(text="❌ Bekor",      callback_data="apen_cancel"),
            ]
        ]),
    )
    await state.set_state(A.pen_ok)


@router.callback_query(F.data == "apen_confirm", A.pen_ok)
async def admin_pen_confirm(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    ptype_map = {
        "jarima": PenaltyType.jarima,
        "xaypsan1": PenaltyType.xaypsan1,
        "xaypsan2": PenaltyType.xaypsan2,
    }
    penalty = Penalty(
        worker_id    = data["pen_worker_id"],
        inspector_id = data["admin_id"],
        penalty_type = ptype_map[data["pen_type"]],
        summa        = data["pen_summa"],
        sabab        = data["pen_sabab"],
    )
    db.add(penalty)
    await db.commit()
    await state.clear()

    # Ishchiga xabar
    worker = await get_user_by_id(db, data["pen_worker_id"])
    if worker:
        from bot.keyboards.main_keyboards import get_worker_confirmed_keyboard
        try:
            await cb.bot.send_message(
                worker.telegram_id,
                f"⚠️ Sizga jarima berildi!\n\n"
                f"Tur: {data['pen_type']}\n"
                f"Summa: {data['pen_summa']:,.0f} so'm\n"
                f"Sabab: {data['pen_sabab']}",
                reply_markup=get_worker_confirmed_keyboard(penalty.id),
            )
        except Exception:
            pass

    await cb.message.answer(
        f"✅ Jarima berildi!\n\n"
        f"👤 {data['pen_worker_name']}\n"
        f"💰 {data['pen_summa']:,.0f} so'm\n"
        f"📝 {data['pen_sabab']}",
    )
    await cb.answer()


@router.callback_query(F.data == "apen_cancel")
async def admin_pen_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        await cb.message.answer("❌ Bekor qilindi.")
    await cb.answer()

# ═══ MAHSULOT 0 GA TUSHGANDA ═══════════════════════════════════════════════════

@router.callback_query(F.data.startswith("zero_keep_"))
async def zero_keep(cb: CallbackQuery, db: AsyncSession):
    """Admin: mahsulot kerak — saqlash."""
    pid = int(cb.data[10:])  # "zero_keep_" = 10 ta belgi
    p   = await db.get(WarehouseProduct, pid)
    if not p:
        await cb.answer("Topilmadi"); return
    # Allaqachon notified, kelajakda yana 0 ga tushganda qaytadan so'rashi mumkin
    p.zero_notified = False
    await db.commit()
    try:
        await cb.message.edit_text(
            f"✅ {p.name} omborda saqlanadi.\n"
            f"Keyinchalik qayta kirim qilishingiz mumkin."
        )
    except Exception:
        await cb.message.answer(f"✅ {p.name} saqlanadi.")
    await cb.answer()


@router.callback_query(F.data.startswith("zero_delete_"))
async def zero_delete(cb: CallbackQuery, db: AsyncSession):
    """Admin: mahsulot keraksiz — o'chirish."""
    pid = int(cb.data[12:])  # "zero_delete_" = 12 ta belgi
    p   = await db.get(WarehouseProduct, pid)
    if not p:
        await cb.answer("Topilmadi"); return
    p.is_active = False
    await db.commit()
    try:
        await cb.message.edit_text(
            f"❌ {p.name} ombordan butunlay o'chirildi.\n"
            f"Endi hisobotlarda ko'rinmaydi."
        )
    except Exception:
        await cb.message.answer(f"❌ {p.name} o'chirildi.")
    await cb.answer()

# ═══ KUCHAYTIRILGAN ADMIN DASHBOARD ══════════════════════════════════════════

@router.message(F.text == "📊 Dashboard")
@router.message(Command("dashboard"))
async def admin_dashboard(message: Message, db: AsyncSession):
    """Admin uchun real-time dashboard."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        return

    today       = date.today()
    yesterday   = today - timedelta(days=1)
    month_start = today.replace(day=1)

    # Bugungi
    r_today = await db.execute(
        select(
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.pending,  1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
        ).where(WorkEntry.work_date == today)
    )
    t = r_today.one()
    t_count, t_inc = int(t[0] or 0), float(t[1] or 0)
    t_ok, t_pend, t_rej = int(t[2] or 0), int(t[3] or 0), int(t[4] or 0)

    # Kechagi
    r_yest = await db.execute(
        select(
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        ).where(WorkEntry.work_date == yesterday, WorkEntry.status == WorkStatus.approved)
    )
    y = r_yest.one()
    y_count, y_inc = int(y[0] or 0), float(y[1] or 0)

    # Oylik
    r_month = await db.execute(
        select(
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        ).where(WorkEntry.work_date >= month_start, WorkEntry.status == WorkStatus.approved)
    )
    m = r_month.one()
    m_count, m_inc = int(m[0] or 0), float(m[1] or 0)

    # Faol smenalar
    r_act = await db.execute(
        select(func.count(WorkSession.id)).where(WorkSession.end_time.is_(None))
    )
    active_n = int(r_act.scalar() or 0)

    # Jami ishchilar
    r_wn = await db.execute(
        select(func.count(User.id)).where(User.role == UserRole.ishchi, User.is_active == True)
    )
    workers_n = int(r_wn.scalar() or 0)

    # Ombor — kam qolgan
    r_low = await db.execute(
        select(func.count(WarehouseProduct.id))
        .where(
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor <= WarehouseProduct.min_threshold,
        )
    )
    low_n = int(r_low.scalar() or 0)

    # Top 5 ishchi bugun
    r_top = await db.execute(
        select(
            User.full_name,
            func.coalesce(func.sum(WorkEntry.jami_summa), 0).label("inc"),
            func.count(WorkEntry.id).label("cnt"),
        )
        .join(WorkEntry, WorkEntry.worker_id == User.id)
        .where(WorkEntry.work_date == today, WorkEntry.status == WorkStatus.approved)
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(WorkEntry.jami_summa), 0).desc())
        .limit(5)
    )
    top5 = r_top.all()

    # Trend
    inc_arrow = "📈" if t_inc >= y_inc else "📉"
    inc_diff  = abs(t_inc - y_inc)
    inc_pct   = ((t_inc - y_inc) / y_inc * 100) if y_inc > 0 else 0
    cnt_arrow = "📈" if t_count >= y_count else "📉"
    cnt_diff  = abs(t_count - y_count)

    # Progress bar
    def bar(pct, length=10):
        f = int(max(0, min(100, pct)) / 100 * length)
        return "█" * f + "░" * (length - f)

    total_today = t_ok + t_rej
    qa_pct = (t_ok / total_today * 100) if total_today > 0 else 100
    qa_emoji = "✅" if qa_pct >= 95 else ("⚠️" if qa_pct >= 85 else "❌")

    smena_pct = (active_n / workers_n * 100) if workers_n > 0 else 0

    txt = (
        f"📊 <b>ADMIN DASHBOARD</b>\n"
        f"<i>{today.strftime('%d.%m.%Y')}</i> "
        f"<i>{datetime.now().strftime('%H:%M')}</i>\n"
        f"{'─' * 24}\n\n"
        f"<b>💰 BUGUNGI DAROMAD</b>\n"
        f"💵 <b>{fmt(t_inc)}</b> so'm\n"
        f"{inc_arrow} {('+' if t_inc >= y_inc else '-')}{fmt(inc_diff)} ({inc_pct:+.1f}%) vs kecha\n\n"
        f"<b>📋 ISHLAR</b>\n"
        f"📝 Bugun: <b>{t_count}</b> {cnt_arrow} ({'+' if t_count >= y_count else '-'}{cnt_diff})\n"
        f"✅ Qabul: <b>{t_ok}</b>  "
        f"⏳ Kutish: <b>{t_pend}</b>  "
        f"❌ Rad: <b>{t_rej}</b>\n\n"
        f"<b>{qa_emoji} SIFAT</b>\n"
        f"<code>{bar(qa_pct)}</code> {qa_pct:.1f}%\n\n"
        f"<b>📅 OYLIK XULOSA</b>\n"
        f"💰 {fmt(m_inc)} so'm\n"
        f"📋 {m_count} ta ish\n\n"
        f"<b>👥 SMENA</b>\n"
        f"<code>{bar(smena_pct)}</code> {active_n} / {workers_n} ishchi\n"
    )

    if low_n > 0:
        txt += f"\n⚠️ <b>OMBOR</b>\n🔴 {low_n} ta mahsulot kam qoldi!\n"

    if top5:
        txt += f"\n<b>🏆 BUGUNGI TOP-5</b>\n"
        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
        for i, row in enumerate(top5):
            name, inc, cnt = row[0], float(row[1] or 0), int(row[2] or 0)
            txt += f"{medals[i]} {name} — {fmt(inc)} ({cnt})\n"
    else:
        txt += "\n<i>Bugun hali ish kiritilmagan</i>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="dash_refresh"),
            InlineKeyboardButton(text="📋 Batafsil",  callback_data="dash_detail"),
        ],
        [
            InlineKeyboardButton(text="📦 Ombor",     callback_data="dash_ombor"),
            InlineKeyboardButton(text="👥 Ishchilar", callback_data="dash_workers"),
        ],
    ])
    await message.answer(txt, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "dash_refresh")
async def dash_refresh(cb: CallbackQuery, db: AsyncSession):
    """Dashboard yangilash."""
    await cb.message.delete()
    fake = cb.message
    fake.from_user = cb.from_user
    await admin_dashboard(fake, db)
    await cb.answer("✅ Yangilandi")


@router.callback_query(F.data == "dash_detail")
async def dash_detail(cb: CallbackQuery, db: AsyncSession):
    """Bugungi so'nggi 20 ish."""
    today = date.today()
    r = await db.execute(
        select(WorkEntry, User)
        .join(User, User.id == WorkEntry.worker_id)
        .where(WorkEntry.work_date == today)
        .order_by(WorkEntry.created_at.desc())
        .limit(20)
    )
    rows = r.all()

    txt = f"📋 <b>Bugungi so'nggi 20 ish</b>\n{'─' * 24}\n\n"
    if not rows:
        txt += "<i>Bugun ish yo'q</i>"
    else:
        em = {"approved": "✅", "pending": "⏳", "rejected": "❌", "edit_requested": "✏️"}
        for we, u in rows:
            sym = em.get(we.status.value if we.status else "", "?")
            wt  = (we.work_type.value if we.work_type else "?").replace("_", " ")
            txt += f"{sym} {u.full_name} | {wt} | {we.soni:.0f} | {fmt(we.jami_summa)}\n"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "dash_ombor")
async def dash_ombor(cb: CallbackQuery, db: AsyncSession):
    """Ombor kategoriyalar bo'yicha."""
    r = await db.execute(
        select(
            WarehouseProduct.category,
            func.count(WarehouseProduct.id),
            sf.sum(sa_case((WarehouseProduct.miqdor <= WarehouseProduct.min_threshold, 1), else_=0)),
        ).where(WarehouseProduct.is_active == True)
        .group_by(WarehouseProduct.category)
    )
    rows = r.all()

    txt = f"📦 <b>Ombor xulosa</b>\n{'─' * 24}\n\n"
    if not rows:
        txt += "<i>Ombor bo'sh</i>"
    else:
        for cat, total, low in rows:
            cname = cat.value if cat else "?"
            warn = f" ⚠️ <b>{int(low or 0)}</b> kam" if low else ""
            txt += f"📁 {cname}: <b>{total}</b> ta{warn}\n"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "dash_workers")
async def dash_workers(cb: CallbackQuery, db: AsyncSession):
    """Ishchilar va bugungi daromadlari."""
    today = date.today()
    r = await db.execute(
        select(User).where(User.role == UserRole.ishchi, User.is_active == True)
        .order_by(User.full_name)
    )
    workers = r.scalars().all()

    txt = f"👥 <b>Ishchilar ({len(workers)} ta)</b>\n{'─' * 24}\n\n"

    # Hammasini bir so'rovda olish — tezroq
    r_inc = await db.execute(
        select(
            WorkEntry.worker_id,
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        ).where(WorkEntry.work_date == today, WorkEntry.status == WorkStatus.approved)
        .group_by(WorkEntry.worker_id)
    )
    inc_map = {r[0]: float(r[1] or 0) for r in r_inc.all()}

    r_act = await db.execute(
        select(WorkSession.worker_id).where(WorkSession.end_time.is_(None))
    )
    active_set = {r[0] for r in r_act.all()}

    for w in workers[:30]:
        emoji = "🟢" if w.id in active_set else "⚪"
        inc   = inc_map.get(w.id, 0.0)
        txt += f"{emoji} {w.full_name} — {fmt(inc)}\n"

    if len(workers) > 30:
        txt += f"\n<i>... va yana {len(workers) - 30} ishchi</i>"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()

# ═══ PDF HISOBOTLAR ════════════════════════════════════════════════════════════

@router.message(F.text == "📄 PDF hisobotlar")
async def admin_pdf_menu(message: Message, db: AsyncSession):
    """Admin uchun PDF hisobotlar menyusi."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Bugungi hisobot",    callback_data="pdf_daily_today")],
        [InlineKeyboardButton(text="📅 Kechagi hisobot",    callback_data="pdf_daily_yesterday")],
        [InlineKeyboardButton(text="📆 Joriy oylik",        callback_data="pdf_monthly_this")],
        [InlineKeyboardButton(text="📆 O'tgan oylik",       callback_data="pdf_monthly_prev")],
        [InlineKeyboardButton(text="📦 Ombor hisoboti",     callback_data="pdf_warehouse")],
        [InlineKeyboardButton(text="❌ Bekor",              callback_data="cancel")],
    ])
    await message.answer("📄 <b>PDF hisobotlar</b>\n\nQaysi hisobot kerak?", parse_mode="HTML", reply_markup=kb)


async def _send_pdf(cb: CallbackQuery, db: AsyncSession, gen_fn, args, filename, caption):
    """PDF yaratish va yuborish."""
    await cb.answer("⏳ Tayyorlanmoqda...")
    try:
        pdf_bytes = await gen_fn(db, *args)
        from aiogram.types import BufferedInputFile
        await cb.message.answer_document(
            BufferedInputFile(pdf_bytes, filename=filename),
            caption=caption,
        )
    except Exception as e:
        logger.error("PDF xato: %s", e)
        await cb.message.answer(f"❌ Xato: {e}")


@router.callback_query(F.data == "pdf_daily_today")
async def pdf_daily_today(cb: CallbackQuery, db: AsyncSession):
    from utils.pdf_reports import generate_daily_report_pdf
    d = date.today()
    await _send_pdf(
        cb, db, generate_daily_report_pdf, (d,),
        f"kunlik_{d.strftime('%Y-%m-%d')}.pdf",
        f"📅 Bugungi hisobot ({d.strftime('%d.%m.%Y')})",
    )


@router.callback_query(F.data == "pdf_daily_yesterday")
async def pdf_daily_yesterday(cb: CallbackQuery, db: AsyncSession):
    from utils.pdf_reports import generate_daily_report_pdf
    d = date.today() - timedelta(days=1)
    await _send_pdf(
        cb, db, generate_daily_report_pdf, (d,),
        f"kunlik_{d.strftime('%Y-%m-%d')}.pdf",
        f"📅 Kechagi hisobot ({d.strftime('%d.%m.%Y')})",
    )


@router.callback_query(F.data == "pdf_monthly_this")
async def pdf_monthly_this(cb: CallbackQuery, db: AsyncSession):
    from utils.pdf_reports import generate_monthly_report_pdf
    today = date.today()
    await _send_pdf(
        cb, db, generate_monthly_report_pdf, (today.year, today.month),
        f"oylik_{today.year}-{today.month:02d}.pdf",
        f"📆 {today.strftime('%B %Y')} oylik hisoboti",
    )


@router.callback_query(F.data == "pdf_monthly_prev")
async def pdf_monthly_prev(cb: CallbackQuery, db: AsyncSession):
    from utils.pdf_reports import generate_monthly_report_pdf
    today = date.today()
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1
    from calendar import month_name
    await _send_pdf(
        cb, db, generate_monthly_report_pdf, (year, month),
        f"oylik_{year}-{month:02d}.pdf",
        f"📆 {month_name[month]} {year} oylik hisoboti",
    )


@router.callback_query(F.data == "pdf_warehouse")
async def pdf_warehouse_cb(cb: CallbackQuery, db: AsyncSession):
    from utils.pdf_reports import generate_warehouse_report_pdf
    await _send_pdf(
        cb, db, generate_warehouse_report_pdf, (),
        f"ombor_{date.today().strftime('%Y-%m-%d')}.pdf",
        f"📦 Ombor hisoboti ({date.today().strftime('%d.%m.%Y')})",
    )

# ═══ TIZIM SALOMATLIGI ═══════════════════════════════════════════════════════

@router.message(F.text == "🩺 Tizim holati")
async def system_health(message: Message, db: AsyncSession):
    """Tizim holati."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        return

    from utils.health_monitor import get_system_stats, format_uptime
    stats = await get_system_stats(db)

    db_stats = stats.get("database", {})
    cache_stats = stats.get("cache", {})
    sys_stats = stats.get("system", {})

    uptime = format_uptime(stats["uptime_sec"])

    db_status = db_stats.get("status", "?")
    db_emoji = {"ok": "🟢", "slow": "🟡", "error": "🔴"}.get(db_status, "⚪")

    txt = (
        f"🩺 <b>TIZIM HOLATI</b>\n"
        f"<i>{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</i>\n"
        f"{'─' * 24}\n\n"
        f"⏱ <b>Uptime:</b> {uptime}\n\n"
        f"{db_emoji} <b>Database</b>\n"
        f"  • Holati: {db_status}\n"
        f"  • Javob: {db_stats.get('response_ms', '?')} ms\n"
        f"  • Foydalanuvchilar: {db_stats.get('users', 0)}\n"
        f"  • Ish yozuvlari: {db_stats.get('work_entries', 0)}\n"
        f"  • Mahsulotlar: {db_stats.get('products', 0)}\n\n"
        f"💾 <b>Cache</b>\n"
        f"  • Hajmi: {cache_stats.get('size', 0)} ta yozuv\n"
        f"  • Hits: {cache_stats.get('hits', 0)}\n"
        f"  • Misses: {cache_stats.get('misses', 0)}\n"
        f"  • Hit rate: {cache_stats.get('hit_rate', '0%')}\n"
    )

    if sys_stats:
        txt += (
            f"\n💻 <b>Resurslar</b>\n"
            f"  • Xotira: {sys_stats.get('memory_mb', '?')} MB\n"
            f"  • CPU: {sys_stats.get('cpu_time', '?')}\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Yangilash",    callback_data="health_refresh"),
            InlineKeyboardButton(text="🗑 Cache tozalash", callback_data="health_clear_cache"),
        ],
    ])
    await message.answer(txt, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "health_refresh")
async def health_refresh(cb: CallbackQuery, db: AsyncSession):
    await cb.message.delete()
    fake = cb.message
    fake.from_user = cb.from_user
    await system_health(fake, db)
    await cb.answer("✅")


@router.callback_query(F.data == "health_clear_cache")
async def health_clear_cache(cb: CallbackQuery):
    from utils.cache import cache
    await cache.clear()
    await cb.answer("✅ Cache tozalandi", show_alert=True)
