"""
inspector.py — v11 TUZATILGAN
TUZATISHLAR:
  1. _do_reject_with_reason: target Message/CallbackQuery ikkala holat ham to'g'ri ishlaydi
  2. apply_penalty: pen_type "jarima" holati o'tkazib yuborilgan edi — qo'shildi
  3. do_approve_with_quality: db.commit() qo'shildi
  4. do_adjust: db.commit() qo'shildi
  5. do_penalty: db.commit() qo'shildi
  6. edit_ok / edit_no: db.commit() qo'shildi
  7. tekshiruv_start: worker_filter None bo'lganda get_pending_works to'g'ri chaqiriladi
  8. _show_next: edit_requested holati uchun to'g'ri ko'rsatiladi
"""
import logging
from datetime import date, datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract, case as sa_case
import sqlalchemy.sql.functions as sf

from database.models import (
    UserRole, WorkStatus, PenaltyType, WorkEntry,
    QualityGrade, WorkSession, Penalty, WarehouseProduct,
)
from database.queries import (
    get_user, get_user_by_id, get_pending_works,
    approve_work, adjust_work, reject_work,
    create_penalty, confirm_penalty,
    get_users_by_role, apply_worker_edit,
    calculate_and_save_salary,
)
from bot.keyboards.main_keyboards import (
    get_inspector_work_keyboard, get_penalty_type_keyboard,
    get_worker_confirmed_keyboard, get_quality_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()

ALLOWED = (UserRole.nazoratchi, UserRole.admin, UserRole.superadmin)

QUALITY_LABELS = {
    QualityGrade.grade_1: "A — to'liq",
    QualityGrade.grade_2: "B — 80%",
    QualityGrade.grade_3: "C — 60%",
}

QUICK_RAD_SABABLAR = [
    "Sifat past",
    "Miqdor noto'g'ri",
    "Material noto'g'ri",
    "Ish tugallanmagan",
    "Ikki marta kiritilgan",
    "Boshqa sabab",
]

CAT_NAMES_OMBOR = {
    "rulon":            "🌀 Rulonlar",
    "gofra":            "📋 Gofralar",
    "gofra_zagatovka":  "✂️ Zagatovka",
    "xromazes":         "🖨️ Xromazeslar",
    "laminat_xromazes": "✨ Laminat",
    "yarim_tayyor":     "⚙️ Yarim tayyor",
    "qolip":            "🔲 Qoliplar",
    "tayyor_mahsulot":  "📦 Tayyor",
    "adyol_zapchast":   "🧩 Adyol zapchast",
    "uskuna_zapchast":  "🔧 Uskuna zapchast",
}


class I(StatesGroup):
    select_worker  = State()
    checking       = State()
    quality_select = State()
    adjust_amount  = State()
    reject_reason  = State()
    reject_custom  = State()
    penalty_amount = State()


async def _safe_send(bot, tg_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(tg_id, text, **kwargs)
        return True
    except TelegramForbiddenError:
        logger.warning("Bot bloklangan: %s", tg_id)
    except Exception as e:
        logger.error("Xabar xatosi (%s): %s", tg_id, e)
    return False


async def _get_smena_status(db, worker_id: int):
    r = await db.execute(
        select(WorkSession)
        .where(WorkSession.worker_id == worker_id, WorkSession.closed_at == None)
        .limit(1)
    )
    return r.scalar_one_or_none()


# ═══ TEKSHIRUV BOSHLASH ═══════════════════════════════════════════════════════

@router.message(F.text == "Tekshiruv boshlash")
async def tekshiruv_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("Ruxsat yo'q."); return

    await state.update_data(inspector_id=user.id, work_index=0, worker_filter=None)
    pending = await get_pending_works(db)
    if not pending:
        await message.answer("✅ Bugun tekshiriladigan ish yo'q!"); return

    # Ishchilar bo'yicha guruhlash
    worker_counts: dict = {}
    for w in pending:
        worker_counts[w.worker_id] = worker_counts.get(w.worker_id, 0) + 1

    buttons = []
    for wid, cnt in worker_counts.items():
        worker = await get_user_by_id(db, wid)
        if worker:
            smena = await _get_smena_status(db, wid)
            icon  = "🟢" if smena else "⚪"
            buttons.append([InlineKeyboardButton(
                text=f"{icon} {worker.full_name} ({cnt} ish)",
                callback_data=f"chkw_{wid}",
            )])

    # Har bir ishchi uchun "Hammasini tasdiqlash" tugmasi
    bulk_buttons = []
    for wid, cnt in worker_counts.items():
        bulk_buttons.append([InlineKeyboardButton(
            text=f"⚡ Hammasini tasdiqlash ({cnt})",
            callback_data=f"bulk_approve_{wid}",
        )])
    buttons.extend(bulk_buttons)
    buttons.append([InlineKeyboardButton(
        text="👥 Hammani tekshir", callback_data="chkw_all"
    )])

    p_cnt = len([p for p in pending if p.status == WorkStatus.pending])
    e_cnt = len([p for p in pending if p.status == WorkStatus.edit_requested])

    await message.answer(
        f"📋 Bugungi holat\n"
        f"⏳ Tekshirilmagan: {p_cnt}\n"
        f"✏️ O'zgartirish so'rovi: {e_cnt}\n\n"
        f"Xodimni tanlang yoki hammani tekshiring:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(I.select_worker)


@router.callback_query(F.data.startswith("chkw_"), I.select_worker)
async def chk_worker_selected(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    val = cb.data[5:]
    await state.update_data(
        worker_filter=None if val == "all" else int(val),
        work_index=0,
    )
    await _show_next(cb.message, state, db)
    await cb.answer()

@router.callback_query(F.data.startswith("bulk_approve_"), I.select_worker)
async def bulk_approve_worker(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """
    1 ishchining barcha pending ishlarini A-sifat bilan birdan tasdiqlash.
    """
    inspector = await get_user(db, cb.from_user.id)
    if not inspector or inspector.role not in ALLOWED:
        await cb.answer("Ruxsat yo'q"); return

    worker_id = int(cb.data.split("_")[2])
    pending   = await get_pending_works(db, worker_id=worker_id)

    if not pending:
        await cb.answer("Tasdiqlanadigan ish yo'q"); return

    worker = await get_user_by_id(db, worker_id)
    confirmed = 0
    total_sum  = 0.0

    for work in pending:
        try:
            approved = await approve_work(
                db, work.id, inspector.id,
                quality_grade=QualityGrade.grade_1,
            )
            total_sum += approved.jami_summa or 0
            confirmed += 1
        except Exception as e:
            logger.warning("Bulk approve xato (work_id=%s): %s", work.id, e)

    await db.commit()

    worker_name = worker.full_name if worker else f"ID={worker_id}"
    await cb.message.answer(
        f"⚡ Bulk tasdiqlash yakunlandi!\n\n"
        f"👷 {worker_name}\n"
        f"✅ Tasdiqlandi: {confirmed} ta ish\n"
        f"💰 Jami summa: {total_sum:,.0f} soum\n"
        f"⭐ Sifat: A (100%)"
    )

    # Ishchiga xabar
    if worker:
        try:
            await cb.bot.send_message(
                worker.telegram_id,
                f"✅ Sizning {confirmed} ta ishingiz tasdiqlandi!\n💰 Jami: {total_sum:,.0f} soum"
            )
        except Exception:
            pass

    await state.clear()
    await cb.answer(f"✅ {confirmed} ta ish tasdiqlandi!")




async def _show_next(message: Message, state: FSMContext, db: AsyncSession):
    data    = await state.get_data()
    index   = data.get("work_index", 0)
    # TUZATILDI: worker_filter None bo'lsa ham to'g'ri chaqiriladi
    pending = await get_pending_works(db, worker_id=data.get("worker_filter"))

    if not pending or index >= len(pending):
        await message.answer("✅ Barcha ishlar tekshirildi!")
        await state.clear(); return

    work   = pending[index]
    worker = await get_user_by_id(db, work.worker_id)
    await state.update_data(
        current_work_id=work.id,
        current_worker_id=work.worker_id,
    )

    # O'zgartirish so'rovi
    if work.status == WorkStatus.edit_requested:
        text = (
            f"✏️ O'zgartirish so'rovi  [{index+1}/{len(pending)}]\n\n"
            f"👷 {worker.full_name if worker else '?'}\n"
            f"🔧 {work.work_type.value.replace('_', ' ').title()}\n"
        )
        if work.mahsulot_nomi: text += f"📦 {work.mahsulot_nomi}\n"
        if work.razmer:        text += f"📐 {work.razmer}\n"
        text += (
            f"🔢 Soni: {work.soni}  💰 {(work.jami_summa or 0):,.0f} soum\n\n"
            f"📝 Ishchi izohi: {work.worker_edit_note or '—'}"
        )
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ruxsat berish", callback_data=f"editok_{work.id}")],
            [InlineKeyboardButton(text="❌ Rad etish",     callback_data=f"editno_{work.id}")],
            [InlineKeyboardButton(text="⏭ Keyingisi",     callback_data=f"inspect_next_{work.id}")],
        ]))
        await state.set_state(I.checking)
        return

    # Oddiy ish
    text = (
        f"🔍 Ish tekshiruvi  [{index+1}/{len(pending)}]\n\n"
        f"👷 {worker.full_name if worker else '?'}\n"
        f"🔧 {work.work_type.value.replace('_', ' ').title()}\n"
    )
    if work.mahsulot_nomi: text += f"📦 Mahsulot: {work.mahsulot_nomi}\n"
    if work.razmer:        text += f"📐 Razmer: {work.razmer}\n"
    if work.tur:           text += f"🏷 Tur: {work.tur}\n"
    text += (
        f"🔢 Miqdor: {work.soni}\n"
        f"💲 Narx: {(work.birlik_narx or 0):,.0f} soum\n"
        f"💰 Summa: {(work.jami_summa or 0):,.0f} soum"
    )
    await message.answer(text, reply_markup=get_inspector_work_keyboard(work.id))
    await state.set_state(I.checking)


# ═══ O'ZGARTIRISH SO'ROVI ═════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("editok_"))
async def edit_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    work_id = int(cb.data.split("_")[1])
    data    = await state.get_data()
    entry   = await apply_worker_edit(db, work_id, data["inspector_id"], approved=True)
    await db.commit()  # TUZATILDI
    worker  = await get_user_by_id(db, entry.worker_id)
    if worker:
        await _safe_send(cb.bot, worker.telegram_id,
            f"✅ O'zgartirish so'rovi qabul qilindi!\n"
            f"🔧 {entry.work_type.value.replace('_', ' ').title()}")
    await cb.message.answer("✅ Ruxsat berildi.")
    await _next(cb, state, db)
    await cb.answer()


@router.callback_query(F.data.startswith("editno_"))
async def edit_no(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    work_id = int(cb.data.split("_")[1])
    data    = await state.get_data()
    entry   = await apply_worker_edit(db, work_id, data["inspector_id"], approved=False)
    await db.commit()  # TUZATILDI
    worker  = await get_user_by_id(db, entry.worker_id)
    if worker:
        await _safe_send(cb.bot, worker.telegram_id,
            f"❌ O'zgartirish so'rovi rad etildi.\n"
            f"🔧 {entry.work_type.value.replace('_', ' ').title()}")
    await cb.message.answer("❌ Rad etildi.")
    await _next(cb, state, db)
    await cb.answer()


# ═══ TASDIQLASH ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("inspect_approve_"))
async def do_approve_start(cb: CallbackQuery, state: FSMContext):
    work_id = int(cb.data.split("_")[2])
    await state.update_data(approving_work_id=work_id)
    await cb.message.answer(
        "Sifat darajasini tanlang:",
        reply_markup=get_quality_keyboard(work_id),
    )
    await state.set_state(I.quality_select)
    await cb.answer()


@router.callback_query(F.data.startswith("qc_"), I.quality_select)
async def do_approve_with_quality(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    parts   = cb.data.split("_")
    grade   = parts[1]
    work_id = int(parts[2])
    data    = await state.get_data()
    quality = QualityGrade(grade)
    work    = await approve_work(db, work_id, data["inspector_id"], quality_grade=quality)
    await db.commit()  # TUZATILDI
    worker  = await get_user_by_id(db, work.worker_id)
    label   = QUALITY_LABELS.get(quality, "")
    if worker:
        await _safe_send(cb.bot, worker.telegram_id,
            f"✅ Ishingiz tasdiqlandi!\n"
            f"🔧 {work.work_type.value.replace('_', ' ').title()}\n"
            f"⭐ Sifat: {label}\n"
            f"💰 {(work.jami_summa or 0):,.0f} soum")
    await cb.message.answer(f"✅ Tasdiqlandi! Sifat: {label}")
    await _next(cb, state, db)
    await cb.answer()


# ═══ TUZATISH ═════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("inspect_adjust_"))
async def do_adjust_start(cb: CallbackQuery, state: FSMContext):
    await state.update_data(adjusting_work_id=int(cb.data.split("_")[2]))
    await cb.message.answer("To'g'ri miqdorni kiriting:")
    await state.set_state(I.adjust_amount)
    await cb.answer()


@router.message(I.adjust_amount)
async def do_adjust(message: Message, state: FSMContext, db: AsyncSession):
    try:
        new_soni = float(message.text.strip())
        if new_soni <= 0: raise ValueError
    except ValueError:
        await message.answer("Musbat son kiriting:"); return

    data   = await state.get_data()
    work   = await adjust_work(db, data["adjusting_work_id"], data["inspector_id"], new_soni)
    await db.commit()  # TUZATILDI
    worker = await get_user_by_id(db, work.worker_id)
    if worker:
        await _safe_send(message.bot, worker.telegram_id,
            f"✏️ Ishingiz tuzatildi!\n"
            f"🔧 {work.work_type.value.replace('_', ' ').title()}\n"
            f"🔢 {work.original_soni} → {new_soni}\n"
            f"💰 {(work.jami_summa or 0):,.0f} soum")
    await message.answer(f"✅ Tuzatildi! 💰 {(work.jami_summa or 0):,.0f} soum")
    await _next_msg(message, state, db)


# ═══ RAD ETISH ════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("inspect_reject_"))
async def do_reject_start(cb: CallbackQuery, state: FSMContext):
    work_id = int(cb.data.split("_")[2])
    await state.update_data(rejecting_work_id=work_id)

    buttons = []
    for i, sabab in enumerate(QUICK_RAD_SABABLAR):
        buttons.append([InlineKeyboardButton(
            text=sabab,
            callback_data=f"qrad_{i}_{work_id}",
        )])
    buttons.append([InlineKeyboardButton(text="Bekor", callback_data="cancel")])

    await cb.message.answer(
        "Rad etish sababini tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(I.reject_reason)
    await cb.answer()


@router.callback_query(F.data.startswith("qrad_"), I.reject_reason)
async def quick_rad_selected(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    parts   = cb.data.split("_")
    idx     = int(parts[1])
    work_id = int(parts[2])

    if idx == len(QUICK_RAD_SABABLAR) - 1:
        # "Boshqa sabab" — qo'lda yozish
        await state.update_data(rejecting_work_id=work_id)
        await cb.message.answer("Sababni yozing (kamida 3 harf):")
        await state.set_state(I.reject_custom)
        await cb.answer()
        return

    sabab = QUICK_RAD_SABABLAR[idx]
    await _do_reject_with_reason(cb, state, db, work_id, sabab)
    await cb.answer()


@router.message(I.reject_custom)
async def reject_custom_reason(message: Message, state: FSMContext, db: AsyncSession):
    sabab = message.text.strip()
    if len(sabab) < 3:
        await message.answer("Kamida 3 harf yozing:"); return
    data    = await state.get_data()
    work_id = data.get("rejecting_work_id")
    if not work_id:
        await message.answer("❌ Ish topilmadi. Qaytadan boshlang.")
        await state.clear(); return
    await _do_reject_with_reason(message, state, db, work_id, sabab)


async def _do_reject_with_reason(target, state, db, work_id, sabab):
    data = await state.get_data()
    work = await reject_work(db, work_id, data["inspector_id"], sabab)
    await db.commit()  # TUZATILDI
    await state.update_data(
        reject_sabab=sabab,
        rejected_work_id=work.id,
        rejected_worker_id=work.worker_id,
    )
    worker = await get_user_by_id(db, work.worker_id)

    # TUZATILDI: Message va CallbackQuery ikkala holatni to'g'ri handle qilish
    if isinstance(target, CallbackQuery):
        send_fn = target.message.answer
    else:
        send_fn = target.answer

    await send_fn(
        f"❌ Rad etildi: {worker.full_name if worker else '?'}\n"
        f"📝 Sabab: {sabab}\n\n"
        f"Jarima turini tanlang:",
        reply_markup=get_penalty_type_keyboard(work.id),
    )
    # State reject_reason yoki reject_custom dan penalty_amount ga yo'naltirish
    # (pen_ callbacki I.checking dan ham ishlashi uchun state o'zgartirmaymiz)


# ═══ JARIMA ═══════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("pen_"))
async def apply_penalty(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    parts     = cb.data.split("_")
    pen_type  = parts[1]
    work_id   = int(parts[2])
    data      = await state.get_data()
    sabab     = data.get("reject_sabab", "—")
    worker_id = data.get("rejected_worker_id") or data.get("current_worker_id")
    worker    = await get_user_by_id(db, worker_id)

    if pen_type == "none":
        # Faqat rad etish, jarima yo'q
        if worker:
            await _safe_send(cb.bot, worker.telegram_id,
                f"❌ Ishingiz rad etildi\n📝 Sabab: {sabab}")
        await cb.message.answer("Faqat rad etildi.")
        await _next(cb, state, db)

    elif pen_type in ("xaypsan1", "xaypsan2"):
        pt  = PenaltyType.xaypsan1 if pen_type == "xaypsan1" else PenaltyType.xaypsan2
        pen = await create_penalty(
            db, worker_id, data["inspector_id"], pt, sabab,
            work_entry_id=work_id,
        )
        await db.commit()  # TUZATILDI
        lbl = "1-xaypsan" if pen_type == "xaypsan1" else "2-xaypsan"
        if worker:
            await _safe_send(cb.bot, worker.telegram_id,
                f"⚠️ Sizga {lbl} berildi!\n📝 Sabab: {sabab}",
                reply_markup=get_worker_confirmed_keyboard(pen.id))
        await cb.message.answer(f"⚠️ {lbl} berildi!")
        await _next(cb, state, db)

    elif pen_type == "jarima":
        # TUZATILDI: "jarima" holati ham handle qilinadi
        await state.update_data(
            penalty_work_id=work_id,
            penalty_worker_id=worker_id,
        )
        await cb.message.answer("💰 Jarima summasini kiriting (soum):")
        await state.set_state(I.penalty_amount)

    else:
        # Noma'lum pen_type — xavfsiz fallback
        logger.warning("Noma'lum pen_type: %s", pen_type)
        await _next(cb, state, db)

    await cb.answer()


@router.message(I.penalty_amount)
async def do_penalty(message: Message, state: FSMContext, db: AsyncSession):
    try:
        summa = float(message.text.replace(",", "").replace(" ", ""))
        if summa <= 0: raise ValueError
    except ValueError:
        await message.answer("Musbat summa kiriting:"); return

    data      = await state.get_data()
    worker_id = data.get("penalty_worker_id")
    work_id   = data.get("penalty_work_id")
    sabab     = data.get("reject_sabab", "—")

    if not worker_id:
        await message.answer("❌ Ishchi topilmadi.")
        await state.clear(); return

    pen    = await create_penalty(
        db, worker_id, data["inspector_id"],
        PenaltyType.jarima, sabab,
        summa, work_entry_id=work_id,
    )
    await db.commit()  # TUZATILDI
    worker = await get_user_by_id(db, worker_id)
    if worker:
        await _safe_send(message.bot, worker.telegram_id,
            f"💸 {summa:,.0f} soum jarima!\n📝 Sabab: {sabab}",
            reply_markup=get_worker_confirmed_keyboard(pen.id))
    await message.answer(f"✅ {summa:,.0f} soum jarima belgilandi!")
    await _next_msg(message, state, db)


@router.callback_query(F.data.startswith("confirm_penalty_"))
async def worker_confirm_penalty(cb: CallbackQuery, db: AsyncSession):
    pen_id = int(cb.data.split("_")[2])
    await confirm_penalty(db, pen_id)
    await db.commit()
    try:
        await cb.message.edit_text(cb.message.text + "\n\n✅ Ko'rdim va tushundim!")
    except TelegramBadRequest:
        pass
    await cb.answer("✅ Tasdiqlandi!")


@router.callback_query(F.data.startswith("inspect_next_"))
async def do_next(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _next(cb, state, db)
    await cb.answer()


async def _next(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    await state.update_data(work_index=data.get("work_index", 0) + 1)
    await _show_next(cb.message, state, db)


async def _next_msg(message: Message, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    await state.update_data(work_index=data.get("work_index", 0) + 1)
    await _show_next(message, state, db)


# ═══ BUGUNGI HOLAT ════════════════════════════════════════════════════════════

@router.message(F.text == "Bugungi holat")
async def bugungi_holat(message: Message, db: AsyncSession):
    r = await db.execute(
        select(WorkEntry.status, func.count(WorkEntry.id))
        .where(WorkEntry.work_date == date.today())
        .group_by(WorkEntry.status)
    )
    stats = {
        (row[0].value if hasattr(row[0], "value") else str(row[0])): row[1]
        for row in r.all()
    }
    await message.answer(
        f"📊 Bugungi holat — {date.today().strftime('%d.%m.%Y')}\n\n"
        f"⏳ Tekshirilmagan:     {stats.get(WorkStatus.pending.value, 0)}\n"
        f"✏️ O'zgartirish so'rovi: {stats.get(WorkStatus.edit_requested.value, 0)}\n"
        f"✅ Tasdiqlangan:       {stats.get(WorkStatus.approved.value, 0)}\n"
        f"~  Tuzatilgan:         {stats.get(WorkStatus.adjusted.value, 0)}\n"
        f"❌ Rad etilgan:        {stats.get(WorkStatus.rejected.value, 0)}"
    )


# ═══ ISHCHILAR HOLATI ═════════════════════════════════════════════════════════

@router.message(F.text == "Ishchilar holati")
async def ishchilar_holati(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("Ruxsat yo'q."); return

    workers = await get_users_by_role(db, UserRole.ishchi)
    if not workers:
        await message.answer("Ishchilar topilmadi."); return

    text = f"👷 Ishchilar holati — {date.today().strftime('%d.%m.%Y')}\n\n"

    for w in workers:
        smena_r    = await db.execute(
            select(WorkSession)
            .where(WorkSession.worker_id == w.id, WorkSession.closed_at == None)
            .limit(1)
        )
        smena_open = smena_r.scalar_one_or_none()
        smena_icon = "🟢" if smena_open else "⚪"

        r = await db.execute(
            select(
                WorkEntry.status,
                func.count(WorkEntry.id),
                func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            )
            .where(WorkEntry.worker_id == w.id, WorkEntry.work_date == date.today())
            .group_by(WorkEntry.status)
        )
        jami_ish = 0; tasdiqlangan = 0; kutmoqda = 0; rad = 0; summa = 0.0
        for status, cnt, s in r.all():
            sv = status.value if hasattr(status, "value") else str(status)
            jami_ish += cnt
            if sv in ("approved", "adjusted"):
                tasdiqlangan += cnt
                summa += float(s)
            elif sv == "pending":
                kutmoqda += cnt
            elif sv == "rejected":
                rad += cnt

        text += (
            f"{smena_icon} {w.full_name}\n"
            f"   📋 Jami: {jami_ish}  ✅ {tasdiqlangan}  "
            f"⏳ {kutmoqda}  ❌ {rad}\n"
            f"   💰 Tasdiqlangan: {summa:,.0f} soum\n\n"
        )

    workers_kb = []
    for w in workers[:8]:
        workers_kb.append([InlineKeyboardButton(
            text=f"🔍 {w.full_name}",
            callback_data=f"wstat_{w.id}",
        )])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=workers_kb),
    )


@router.callback_query(F.data.startswith("wstat_"))
async def worker_stat_detail(cb: CallbackQuery, db: AsyncSession):
    wid    = int(cb.data[6:])
    worker = await get_user_by_id(db, wid)
    if not worker:
        await cb.answer("Topilmadi"); return

    r = await db.execute(
        select(WorkEntry)
        .where(WorkEntry.worker_id == wid, WorkEntry.work_date == date.today())
        .order_by(WorkEntry.created_at.desc())
    )
    works = r.scalars().all()

    if not works:
        await cb.message.answer(
            f"{worker.full_name}\nBugun hech qanday ish kiritilmagan."
        )
        await cb.answer(); return

    STATUS_ICONS = {
        WorkStatus.pending:        "⏳",
        WorkStatus.approved:       "✅",
        WorkStatus.adjusted:       "~",
        WorkStatus.rejected:       "❌",
        WorkStatus.edit_requested: "✏️",
    }

    text  = f"📋 {worker.full_name} — bugungi ishlar\n\n"
    total = 0.0
    for i, w in enumerate(works, 1):
        icon  = STATUS_ICONS.get(w.status, "?")
        text += f"{i}. {icon} {w.work_type.value.replace('_', ' ').title()}\n"
        if w.mahsulot_nomi: text += f"   📦 {w.mahsulot_nomi}\n"
        if w.razmer:        text += f"   📐 {w.razmer}\n"
        text += f"   🔢 {w.soni}  💰 {(w.jami_summa or 0):,.0f} soum\n"
        if w.status == WorkStatus.rejected and w.rad_sababi:
            text += f"   ❌ Sabab: {w.rad_sababi}\n"
        text += "\n"
        if w.status in (WorkStatus.approved, WorkStatus.adjusted):
            total += w.jami_summa or 0

    text += f"💰 Tasdiqlangan jami: {total:,.0f} soum"

    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await cb.message.answer(chunk)
    await cb.answer()


# ═══ OMBOR HOLATI ═════════════════════════════════════════════════════════════

@router.message(F.text == "Ombor holati")
async def nazoratchi_ombor_holati(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("Ruxsat yo'q."); return

    products = (await db.execute(
        select(WarehouseProduct)
        .where(WarehouseProduct.is_active == True)
        .order_by(WarehouseProduct.category, WarehouseProduct.name)
    )).scalars().all()

    if not products:
        await message.answer("Ombor bo'sh."); return

    cats: dict = {}
    for p in products:
        cv = p.category.value if hasattr(p.category, "value") else str(p.category)
        cats.setdefault(cv, []).append(p)

    kam_qolgan = []
    for cv, prods in cats.items():
        for p in prods:
            m = float(p.miqdor)
            if m <= float(p.min_threshold):
                kam_qolgan.append(f"🔴 {p.name}: {p.miqdor} {p.birlik}")
            elif m <= float(p.yellow_threshold):
                kam_qolgan.append(f"🟡 {p.name}: {p.miqdor} {p.birlik}")

    text = f"🏭 Ombor holati — {date.today().strftime('%d.%m.%Y')}\n\n"

    if kam_qolgan:
        text += f"⚠️ Diqqat talab etadi ({len(kam_qolgan)} ta):\n"
        text += "\n".join(kam_qolgan[:20])
        if len(kam_qolgan) > 20:
            text += f"\n... va yana {len(kam_qolgan) - 20} ta"
    else:
        text += "✅ Barcha materiallar yetarli!\n"

    text += "\n\n📊 Kategoriyalar:\n"
    for cv, prods in cats.items():
        yetarli = sum(
            1 for p in prods
            if float(p.miqdor) > float(p.yellow_threshold)
        )
        jami = len(prods)
        icon = "🟢" if yetarli == jami else ("🔴" if yetarli == 0 else "🟡")
        text += f"{icon} {CAT_NAMES_OMBOR.get(cv, cv)}: {yetarli}/{jami}\n"

    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await message.answer(chunk)


# ═══ QOLGAN HANDLERLAR ════════════════════════════════════════════════════════

@router.message(F.text == "Tekshiruv hisoboti")
async def tekshiruv_hisoboti(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("Ruxsat yo'q."); return
    r = await db.execute(
        select(WorkEntry.status, func.count(WorkEntry.id))
        .where(WorkEntry.work_date == date.today())
        .group_by(WorkEntry.status)
    )
    stats = {
        (row[0].value if hasattr(row[0], "value") else str(row[0])): row[1]
        for row in r.all()
    }
    jami = sum(stats.values())
    await message.answer(
        f"📊 Bugungi tekshiruv hisoboti\n\n"
        f"📋 Jami: {jami}\n"
        f"✅ OK: {stats.get(WorkStatus.approved.value, 0)}\n"
        f"~ Tuzatilgan: {stats.get(WorkStatus.adjusted.value, 0)}\n"
        f"⏳ Kutmoqda: {stats.get(WorkStatus.pending.value, 0)}\n"
        f"❌ Rad: {stats.get(WorkStatus.rejected.value, 0)}"
    )


@router.message(F.text == "Jarimalar")
async def jarimalar(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("Ruxsat yo'q."); return
    now = datetime.now()
    r   = await db.execute(
        select(Penalty)
        .where(
            extract("month", Penalty.created_at) == now.month,
            extract("year",  Penalty.created_at) == now.year,
        )
        .order_by(Penalty.created_at.desc())
    )
    penalties = r.scalars().all()
    if not penalties:
        await message.answer("Bu oyda jarima yo'q."); return
    text  = f"⚠️ Jarimalar — {now.month}/{now.year}\n\n"
    total = 0.0
    for pen in penalties:
        worker = await get_user_by_id(db, pen.worker_id)
        conf   = "✅" if pen.worker_confirmed else "⏳"
        text  += (
            f"{conf} {worker.full_name if worker else '?'}\n"
            f"   📝 {pen.sabab}\n"
            f"   💰 {(pen.summa or 0):,.0f} soum\n\n"
        )
        total += pen.summa or 0
    text += f"💰 Jami: {total:,.0f} soum"
    await message.answer(text)


@router.message(F.text.in_(["Smena holati", "Reyting", "Sifat hisoboti"]))
async def inspector_extra(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("Ruxsat yo'q."); return
    await message.answer("Bu funksiya veb-panelda mavjud: /web/")


@router.callback_query(F.data == "cancel")
async def cancel_inspector(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Bekor qilindi.")
    await cb.answer()

# ═══ INSPECTOR DASHBOARD ═════════════════════════════════════════════════════

def _fmt(n):
    try: return f"{int(float(n)):,}".replace(",", " ")
    except: return str(n)

def _bar(pct, length=10):
    f = int(max(0, min(100, pct)) / 100 * length)
    return "█" * f + "░" * (length - f)


@router.message(F.text == "📊 Dashboard")
async def inspector_dashboard(message: Message, db: AsyncSession):
    """Nazoratchi uchun dashboard — tekshirish kerak bo'lganlar."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.nazoratchi:
        return

    today       = date.today()
    yesterday   = today - timedelta(days=1)
    week_ago    = today - timedelta(days=7)

    # Kutilayotgan ishlar
    r_pend = await db.execute(
        select(func.count(WorkEntry.id)).where(WorkEntry.status == WorkStatus.pending)
    )
    pending_n = int(r_pend.scalar() or 0)

    # Bugun tekshirilganlar
    r_today = await db.execute(
        select(
            func.count(WorkEntry.id),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
        ).where(
            WorkEntry.inspector_id == user.id,
            func.date(WorkEntry.finished_at) == today,
        )
    )
    t = r_today.one()
    t_total, t_ok, t_rej = int(t[0] or 0), int(t[1] or 0), int(t[2] or 0)

    # Bu hafta
    r_week = await db.execute(
        select(
            func.count(WorkEntry.id),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
        ).where(
            WorkEntry.inspector_id == user.id,
            WorkEntry.finished_at >= week_ago,
        )
    )
    w = r_week.one()
    w_total, w_ok, w_rej = int(w[0] or 0), int(w[1] or 0), int(w[2] or 0)
    w_rate = (w_rej / w_total * 100) if w_total > 0 else 0

    # Eng ko'p rad etilgan ishchilar (bu hafta)
    r_bad = await db.execute(
        select(
            User.full_name,
            func.count(WorkEntry.id),
        )
        .join(WorkEntry, WorkEntry.worker_id == User.id)
        .where(
            WorkEntry.work_date >= week_ago,
            WorkEntry.status == WorkStatus.rejected,
        )
        .group_by(User.id, User.full_name)
        .order_by(func.count(WorkEntry.id).desc())
        .limit(5)
    )
    bad_workers = r_bad.all()

    # Eng ko'p sabab
    r_reasons = await db.execute(
        select(
            WorkEntry.rad_sababi,
            func.count(WorkEntry.id),
        ).where(
            WorkEntry.work_date >= week_ago,
            WorkEntry.status == WorkStatus.rejected,
            WorkEntry.rad_sababi.is_not(None),
        )
        .group_by(WorkEntry.rad_sababi)
        .order_by(func.count(WorkEntry.id).desc())
        .limit(5)
    )
    top_reasons = r_reasons.all()

    qa_pct = (w_ok / w_total * 100) if w_total > 0 else 100
    qa_emoji = "✅" if qa_pct >= 95 else ("⚠️" if qa_pct >= 85 else "❌")

    txt = (
        f"📊 <b>NAZORATCHI DASHBOARD</b>\n"
        f"<i>{today.strftime('%d.%m.%Y')}</i>  "
        f"<i>{datetime.now().strftime('%H:%M')}</i>\n"
        f"{'─' * 24}\n\n"
        f"<b>⏳ KUTILMOQDA</b>\n"
        f"📋 <b>{pending_n}</b> ta ish tekshirish kerak\n\n"
        f"<b>📅 BUGUN TEKSHIRDIM</b>\n"
        f"📝 Jami: <b>{t_total}</b>  ✅ {t_ok}  ❌ {t_rej}\n\n"
        f"<b>📊 BU HAFTA</b>\n"
        f"📝 Jami: <b>{w_total}</b>  ✅ {w_ok}  ❌ {w_rej}\n"
        f"❌ Rad etish: {w_rate:.1f}%\n\n"
        f"<b>{qa_emoji} ZAVOD SIFATI</b>\n"
        f"<code>{_bar(qa_pct)}</code> {qa_pct:.1f}%\n"
    )

    if bad_workers:
        txt += f"\n<b>⚠️ Ko'p rad olganlar (hafta)</b>\n"
        for name, n in bad_workers:
            txt += f"• {name}: {n} ta rad\n"

    if top_reasons:
        txt += f"\n<b>🔍 Top rad sabablari</b>\n"
        for reason, n in top_reasons:
            short = (reason[:35] + "...") if len(reason) > 35 else reason
            txt += f"• {short}: {n}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="insp_dash_refresh"),
            InlineKeyboardButton(text="⚡ Batch",      callback_data="insp_batch_start"),
        ],
        [
            InlineKeyboardButton(text="📋 Kutayotgan ishlar", callback_data="insp_pending_list"),
        ],
    ])
    await message.answer(txt, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "insp_dash_refresh")
async def insp_dash_refresh(cb: CallbackQuery, db: AsyncSession):
    await cb.message.delete()
    fake = cb.message
    fake.from_user = cb.from_user
    await inspector_dashboard(fake, db)
    await cb.answer("✅")


# ═══ BATCH TASDIQLASH ════════════════════════════════════════════════════════

@router.message(F.text == "⚡ Batch tasdiqlash")
@router.callback_query(F.data == "insp_batch_start")
async def batch_start(target, db: AsyncSession):
    """Bir vaqtda ko'p ishni tasdiqlash."""
    is_cb = hasattr(target, "data")
    user_id = (target.from_user.id) if is_cb else target.from_user.id
    user = await get_user(db, user_id)
    if not user or user.role != UserRole.nazoratchi:
        return

    r = await db.execute(
        select(WorkEntry, User)
        .join(User, User.id == WorkEntry.worker_id)
        .where(WorkEntry.status == WorkStatus.pending)
        .order_by(WorkEntry.created_at.asc())
        .limit(20)
    )
    rows = r.all()

    if not rows:
        msg = "🎉 Tekshirish kerak bo'lgan ish yo'q!"
        if is_cb:
            await target.message.answer(msg)
            await target.answer()
        else:
            await target.answer(msg)
        return

    # Ishchilarga guruhlash
    groups = {}
    for we, u in rows:
        groups.setdefault(u.id, {"name": u.full_name, "items": []})["items"].append(we)

    txt = f"⚡ <b>BATCH TASDIQLASH</b>\n"
    txt += f"<i>{len(rows)} ta ish kutilmoqda</i>\n{'─' * 24}\n\n"

    buttons = []
    for uid, g in groups.items():
        items = g["items"]
        total_inc = sum(float(w.jami_summa or 0) for w in items)
        txt += f"👷 <b>{g['name']}</b> — {len(items)} ta ({_fmt(total_inc)})\n"
        for w in items[:5]:
            wt = (w.work_type.value if w.work_type else "?").replace("_", " ")
            txt += f"  • {wt} | {w.soni:.0f} | {_fmt(w.jami_summa)}\n"
        if len(items) > 5:
            txt += f"  ...va yana {len(items) - 5} ta\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ {g['name']} — Hammasi OK ({len(items)})",
                callback_data=f"batch_approve_user_{uid}",
            )
        ])
        txt += "\n"

    buttons.append([
        InlineKeyboardButton(text="✅✅ HAMMASINI tasdiqlash", callback_data="batch_approve_all"),
    ])
    buttons.append([
        InlineKeyboardButton(text="❌ Bekor", callback_data="cancel"),
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_cb:
        await target.message.answer(txt, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(txt, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "batch_approve_all")
async def batch_approve_all(cb: CallbackQuery, db: AsyncSession):
    """Barcha kutilayotgan ishlarni tasdiqlash."""
    user = await get_user(db, cb.from_user.id)
    if not user or user.role != UserRole.nazoratchi:
        await cb.answer("Ruxsat yo'q"); return

    r = await db.execute(
        select(WorkEntry).where(WorkEntry.status == WorkStatus.pending)
    )
    works = r.scalars().all()

    now = datetime.now()
    count = 0
    for w in works:
        w.status     = WorkStatus.approved
        w.inspector_id = user.id
        w.finished_at = now
        count += 1

    await db.commit()
    await cb.message.edit_text(
        f"✅ <b>{count} ta ish tasdiqlandi!</b>\n\nBatch tasdiqlash muvaffaqiyatli yakunlandi.",
        parse_mode="HTML",
    )
    await cb.answer(f"✅ {count} ta tasdiqlandi")


@router.callback_query(F.data.startswith("batch_approve_user_"))
async def batch_approve_user(cb: CallbackQuery, db: AsyncSession):
    """Bitta ishchining barcha ishlarini tasdiqlash."""
    user = await get_user(db, cb.from_user.id)
    if not user or user.role != UserRole.nazoratchi:
        await cb.answer("Ruxsat yo'q"); return

    worker_id = int(cb.data.split("_")[3])
    r = await db.execute(
        select(WorkEntry).where(
            WorkEntry.status == WorkStatus.pending,
            WorkEntry.worker_id == worker_id,
        )
    )
    works = r.scalars().all()

    now = datetime.now()
    count = 0
    for w in works:
        w.status     = WorkStatus.approved
        w.inspector_id = user.id
        w.finished_at = now
        count += 1

    await db.commit()

    # Ishchi nomini olish
    w_user = await db.get(User, worker_id)
    worker_name = w_user.full_name if w_user else "?"

    await cb.message.answer(
        f"✅ <b>{worker_name}</b> ishchining {count} ta ishi tasdiqlandi!",
        parse_mode="HTML",
    )
    await cb.answer(f"✅ {count} ta")


@router.callback_query(F.data == "insp_pending_list")
async def insp_pending_list(cb: CallbackQuery, db: AsyncSession):
    """Barcha kutayotgan ishlar ro'yxati."""
    r = await db.execute(
        select(WorkEntry, User)
        .join(User, User.id == WorkEntry.worker_id)
        .where(WorkEntry.status == WorkStatus.pending)
        .order_by(WorkEntry.created_at.asc())
    )
    rows = r.all()

    if not rows:
        await cb.message.answer("🎉 Tekshirish kerak bo'lgan ish yo'q!")
        await cb.answer(); return

    txt = f"📋 <b>Kutilayotgan ishlar ({len(rows)})</b>\n{'─' * 24}\n\n"
    for i, (w, u) in enumerate(rows[:30], 1):
        wt = (w.work_type.value if w.work_type else "?").replace("_", " ")
        sana = w.work_date.strftime('%d.%m') if w.work_date else "—"
        txt += f"{i}. {u.full_name} | {wt} | {w.soni:.0f} | {_fmt(w.jami_summa)} | {sana}\n"

    if len(rows) > 30:
        txt += f"\n<i>... va yana {len(rows) - 30} ta</i>"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()

@router.message(F.text == "🌐 Web panel")
async def inspektor_web_panel(message: Message, db: AsyncSession):
    """Inspektor uchun shaxsiy web panel havolasi."""
    user = await get_user(db, message.from_user.id)
    if not user:
        return
    from utils.web_link import get_or_create_web_link
    link = await get_or_create_web_link(db, user)
    await message.answer(
        f"🌐 <b>Nazoratchi Web paneli</b>\n\n"
        f"{link}\n\n"
        f"⚠️ Shaxsiy havola — boshqalarga bermang.\n"
        f"Telefon yoki kompyuterda oching — parol kerak emas.",
        parse_mode="HTML",
    )

