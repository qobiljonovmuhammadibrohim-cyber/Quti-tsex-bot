"""
worker.py — v11 TO'LIQ TUZATILGAN
TUZATISHLAR:
  - Razmer logikasi har bir ish turi uchun alohida va to'g'ri:
      * Gofra ishlab, Rulon o'rash, Rulonga salafan — razmer rulon/mahsulotdan olinadi
      * List qog'oz — erkin matn razmer (25x30), kg bilan to'lanadi
      * Qolgan barchasi — Katta/O'rta/Kichik tanlanadi, narx shunga qarab
  - Har bir ish turida to'g'ri mahsulot kategoriyalari
  - FSM holatlari aniq va izchil
"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from database.models import (
    UserRole, WorkEntry, WorkStatus, WorkType,
    ProductCategory, WarehouseProduct, SmenaType, QualityGrade,
)
from database.queries import (
    get_user, get_price, get_today_works, get_today_sum,
    get_users_by_role, get_open_session, open_session,
    close_session, get_today_work_minutes, request_worker_edit,
)
from utils.warehouse_ops import run_warehouse_ops
from bot.keyboards.main_keyboards import (
    get_work_type_keyboard, get_gofra_type_keyboard,
    get_gofra_sloy_keyboard, get_confirm_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()

# Katta/O'rta/Kichik — narxga ta'sir qiluvchi razmer
SIZE_CHOICES = ["Katta", "O'rta", "Kichik"]

STATUS_ICONS = {
    WorkStatus.pending:        "⏳",
    WorkStatus.approved:       "✅",
    WorkStatus.adjusted:       "~",
    WorkStatus.rejected:       "❌",
    WorkStatus.edit_requested: "✏️",
}

OYLIK_MAQSAD = 2_000_000  # soum


# ═══ RAZMER KLAVIATURALARI ════════════════════════════════════════════════════

def _size_keyboard(prefix: str = "size") -> InlineKeyboardMarkup:
    """Katta/O'rta/Kichik tanlash klaviaturasi — narxga ta'sir qiluvchi ishlar uchun"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔵 Katta",  callback_data=f"{prefix}_Katta"),
            InlineKeyboardButton(text="🟡 O'rta",  callback_data=f"{prefix}_Orta"),
            InlineKeyboardButton(text="🔴 Kichik", callback_data=f"{prefix}_Kichik"),
        ],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")],
    ])


def _size_label(raw: str) -> str:
    """Razmer qiymatini chiroyli ko'rinishga o'tkazadi"""
    return {"Katta": "Katta", "Orta": "O'rta", "Kichik": "Kichik"}.get(raw, raw)


# ═══ STATES ═══════════════════════════════════════════════════════════════════

class W(StatesGroup):
    smena_select        = State()
    smena_close_confirm = State()
    edit_req_note       = State()
    select_type         = State()

    # 1. Gofra ishlab chiqarish
    gi_tur       = State()
    gi_rulonlar  = State()  # rulon tanlash + miqdor kiritish
    gi_rang      = State()  # rang tanlash (Oq/Qora)
    gi_soni      = State()
    gi_ok        = State()

    # 2. Laminatsiya
    lam_xromazes = State()
    lam_nomi     = State()
    lam_razmer   = State()  # Katta/O'rta/Kichik
    lam_soni     = State()
    lam_dest     = State()
    lam_ok       = State()

    # 3. Zagatovka kesish
    zag_xvar     = State()  # xromazes xili (nom+rang)
    zag_xpart    = State()  # xromazes qismi (nom uchun)
    zag_gofra    = State()
    zag_top_soni = State()
    zag_nomi     = State()
    zag_tur      = State()
    zag_razmer   = State()  # Katta/O'rta/Kichik
    zag_soni     = State()
    zag_ok       = State()

    # 4. Gofra kiley
    gk_yonalish    = State()
    gk_sloy        = State()
    gk_xrom_variety = State()
    gk_xromazes    = State()
    gk_xrom_soni = State()
    gk_zag_variety = State()
    gk_zag1      = State()
    gk_zag1_soni = State()
    gk_zag2      = State()
    gk_zag2_soni = State()
    gk_nomi      = State()
    gk_razmer    = State()  # Katta/O'rta/Kichik
    gk_soni      = State()
    gk_ok        = State()

    # 5. Tiger kesish
    tiger_src    = State()
    tiger_soni   = State()
    tiger_razmer = State()  # Katta/O'rta/Kichik
    tiger_dest   = State()
    tiger_ok     = State()

    # 6. List qog'oz kesish — razmer erkin matn (25x30), kg bilan to'lanadi
    list_rulon   = State()
    list_razmer  = State()  # erkin matn: "25x30" kabi
    list_kilosi  = State()  # kg (soni sifatida saqlanadi)
    list_dest    = State()
    list_ok      = State()

    # 7. Stepler tikish
    stpl_src    = State()
    stpl_razmer = State()  # Katta/O'rta/Kichik
    stpl_ombor  = State()  # ombordan nechta olindi
    stpl_soni   = State()  # nechta tikildi
    stpl_ok     = State()

    # 8. Rulon o'rash — razmer mahsulotdan olinadi
    ro_rulon = State()
    ro_soni  = State()
    ro_ok    = State()

    # 9. Rulonga salafan — razmer rulon mahsulotdan olinadi
    rs_rulon   = State()
    rs_salafan = State()
    rs_rang    = State()
    rs_soni    = State()
    rs_ok      = State()

    # 10. Yopishtirma
    yop_src    = State()
    yop_razmer = State()  # Katta/O'rta/Kichik
    yop_ombor  = State()  # ombordan nechta olindi
    yop_soni   = State()  # nechta yopishtirdi
    yop_ok     = State()

    # 11-14: adyol/pastel tikish/qoqish — worker_adyol_pastel.py da

    # Tezkor kiritish
    quick_soni = State()
    quick_ok   = State()


# ═══ YORDAMCHI FUNKSIYALAR ════════════════════════════════════════════════════

async def _safe_send(bot, tg_id: int, text: str, **kwargs):
    try:
        await bot.send_message(tg_id, text, **kwargs)
    except Exception as e:
        logger.warning("Xabar yuborib bo'lmadi (tg_id=%s): %s", tg_id, e)


def _parse_pos_int(text: str):
    try:
        val = int(str(text).strip())
        return val if val > 0 else None
    except Exception:
        return None


def _parse_pos_float(text: str):
    try:
        val = float(str(text).strip().replace(",", "."))
        return val if val > 0 else None
    except Exception:
        return None


async def _show_products(
    target, db, category: ProductCategory,
    tur=None, rang=None, razmer=None, name=None,
    title="Mahsulot tanlang:",
    callback_prefix="sel",
    only_positive=True,
    extra_cats: list = None,
    label_mode: str = "full",   # "full" | "razmer" | "razmer_tur"
    yonalish: str = None,       # "tiger" | "zagatovka" | None (hammasi)
) -> bool:
    from sqlalchemy import or_
    cats = [category]
    if extra_cats:
        cats.extend(extra_cats)

    q = select(WarehouseProduct).where(
        WarehouseProduct.category.in_(cats),
        WarehouseProduct.is_active == True,
    )
    if only_positive:
        q = q.where(WarehouseProduct.miqdor > 0)
    if tur is not None:
        q = q.where(WarehouseProduct.tur == tur)
    if name is not None:
        q = q.where(WarehouseProduct.name == name)
    if rang is not None:
        q = q.where(WarehouseProduct.rang == rang)
    if yonalish is not None:
        q = q.where(WarehouseProduct.yonalish == yonalish)
    if razmer is not None:
        # Razmer bo'yicha qidirish — normalized va raw ikkalasida
        from utils.razmer import normalize_razmer
        norm = normalize_razmer(razmer)
        if norm:
            q = q.where(or_(
                WarehouseProduct.razmer_normalized.ilike(f"%{norm}%"),
                WarehouseProduct.razmer.ilike(f"%{razmer}%"),
            ))
    products = (await db.execute(q.order_by(WarehouseProduct.name))).scalars().all()
    if not products:
        return False

    def icon(p):
        m = float(p.miqdor)
        if m <= float(p.min_threshold):    return "🔴"
        if m <= float(p.yellow_threshold): return "🟡"
        return "🟢"

    buttons = []
    for p in products:
        label = f"{icon(p)} {p.name}"
        if label_mode == "razmer":
            # Zagatovka uchun: faqat aniq o'lcham (98×62.5)
            if p.razmer: label += f" | {p.razmer}"
        elif label_mode == "razmer_tur":
            # Gofra kley va tiger uchun: faqat Katta/O'rta/Kichik
            if p.razmer_tur: label += f" | {p.razmer_tur}"
            elif p.razmer:   label += f" | {p.razmer}"  # fallback
        else:
            # full — barcha ma'lumotlar (laminatsiya, omborchi)
            if p.razmer_tur: label += f" [{p.razmer_tur}]"
            if p.razmer:     label += f" {p.razmer}"
            if p.rang:       label += f" | {p.rang}"
        # Qism — har doim ko'rsatish (tepa/past/yon/paddo)
        if p.qism:
            from constants import QISM_ICONS
            qicon = QISM_ICONS.get(p.qism, "")
            label = f"{qicon} {p.qism.upper()}: " + label
        label += f"  ({p.miqdor:.0f} {p.birlik})"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"{callback_prefix}_{p.id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])

    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    return True


async def _confirm_screen(
    target, state, work_type, label,
    extra_lines, soni, narx, summa, ok_state,
):
    await state.update_data(
        soni=soni, birlik_narx=narx, jami_summa=summa, work_type=work_type
    )
    extra = ("\n".join(extra_lines) + "\n") if extra_lines else ""
    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(
        f"✅ Tasdiqlaysizmi?\n\n"
        f"🔧 {label}\n"
        f"{extra}"
        f"📦 Miqdor: {soni}\n"
        f"💰 Narx: {narx:,.0f} soum\n"
        f"💵 Jami: {summa:,.0f} soum",
        reply_markup=get_confirm_keyboard(),
    )
    await state.set_state(ok_state)


async def _save_work_and_ops(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    entry = WorkEntry(
        worker_id=data["worker_id"],
        work_type=WorkType(data["work_type"]),
        mahsulot_nomi=data.get("mahsulot_nomi"),
        razmer=data.get("razmer"),
        rang=data.get("rang"),
        tur=data.get("tur"),
        sloy=data.get("sloy"),
        soni=data.get("soni", 0),
        birlik_narx=data.get("birlik_narx", 0),
        jami_summa=data.get("jami_summa", 0),
        status=WorkStatus.pending,
        started_at=datetime.now(),
    )
    db.add(entry)
    await db.flush()
    await db.commit()

    warns = await run_warehouse_ops(
        bot=cb.bot, db=db,
        work_type=data["work_type"],
        data=data,
        user_id=data["worker_id"],
        work_entry_id=entry.id,
    )
    await state.clear()

    warn_text = ("\n⚠️ " + "\n⚠️ ".join(warns)) if warns else ""
    await cb.message.answer(
        f"✅ Ish saqlandi!\n"
        f"💰 {data.get('jami_summa', 0):,.0f} soum"
        f"{warn_text}\n\n"
        f"Nazoratchi tekshirishini kuting..."
    )
    await cb.answer()

    inspectors = await get_users_by_role(db, UserRole.nazoratchi)
    user = await get_user(db, cb.from_user.id)
    for ins in inspectors:
        await _safe_send(
            cb.bot, ins.telegram_id,
            f"📋 Yangi ish!\n"
            f"👷 {user.full_name if user else '?'}\n"
            f"🔧 {data['work_type'].replace('_', ' ').title()}\n"
            f"📏 {data.get('razmer', '-')}  📦 {data.get('soni', '?')}\n"
            f"💰 {data.get('jami_summa', 0):,.0f} soum",
        )


# ═══ SMENA ════════════════════════════════════════════════════════════════════

@router.message(F.text == "Smena boshlash")
async def smena_start_btn(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.ishchi:
        await message.answer("Ruxsat yo'q."); return

    existing = await get_open_session(db, user.id)
    if existing:
        elapsed = int((datetime.now() - existing.opened_at).total_seconds() / 60)
        await message.answer(
            f"⚠️ Ochiq smena mavjud!\n"
            f"🕐 Boshlangan: {existing.opened_at.strftime('%H:%M')}\n"
            f"⏱ O'tgan: {elapsed} daqiqa\n\n"
            f"Avval 'Smena tugatish' ni bosing."
        )
        return

    await state.update_data(worker_id=user.id)
    await message.answer(
        "Qaysi smenani boshlaysiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌞 Kunduzgi (08-20)", callback_data="smena_kunduzgi")],
            [InlineKeyboardButton(text="🌙 Kechki (20-08)",   callback_data="smena_kechki")],
            [InlineKeyboardButton(text="❌ Bekor",            callback_data="cancel")],
        ]),
    )
    await state.set_state(W.smena_select)


@router.callback_query(F.data.startswith("smena_"), W.smena_select)
async def smena_type_selected(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    smena = SmenaType.kunduzgi if "kunduzgi" in cb.data else SmenaType.kechki
    data  = await state.get_data()
    sess  = await open_session(db, data["worker_id"], smena)
    await db.commit()
    await state.clear()
    await cb.message.answer(
        f"✅ Smena boshlandi!\n"
        f"🕐 {sess.opened_at.strftime('%H:%M')}\n"
        f"📅 {sess.work_date.strftime('%d.%m.%Y')}\n\n"
        f"Muvaffaqiyatli ish! 💪"
    )
    await cb.answer()


@router.message(F.text == "Smena tugatish")
async def smena_close_btn(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.ishchi:
        await message.answer("Ruxsat yo'q."); return

    session = await get_open_session(db, user.id)
    if not session:
        await message.answer("Ochiq smena topilmadi."); return

    elapsed  = int((datetime.now() - session.opened_at).total_seconds() / 60)
    works    = await get_today_works(db, user.id)
    approved = sum(1 for w in works if w.status in (WorkStatus.approved, WorkStatus.adjusted))
    pending  = sum(1 for w in works if w.status == WorkStatus.pending)

    await state.update_data(worker_id=user.id)
    await message.answer(
        f"Smenani tugatmoqchimisiz?\n\n"
        f"🕐 Boshlangan: {session.opened_at.strftime('%H:%M')}\n"
        f"⏱ Ishlagan: {elapsed // 60}s {elapsed % 60}d\n"
        f"✅ Tasdiqlangan: {approved} ta\n"
        f"⏳ Kutmoqda: {pending} ta",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, tugatish",      callback_data="smena_close_yes")],
            [InlineKeyboardButton(text="🔙 Yo'q, davom etish", callback_data="cancel")],
        ]),
    )
    await state.set_state(W.smena_close_confirm)


@router.callback_query(F.data == "smena_close_yes", W.smena_close_confirm)
async def smena_close_confirm(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data    = await state.get_data()
    session = await close_session(db, data["worker_id"])
    await db.commit()
    await state.clear()

    if not session:
        await cb.message.answer("Smena topilmadi.")
        await cb.answer(); return

    total_min = session.duration_minutes or 0
    sums  = await get_today_sum(db, data["worker_id"])
    works = await get_today_works(db, data["worker_id"])

    wt_count: dict = {}
    for w in works:
        if w.status in (WorkStatus.approved, WorkStatus.adjusted):
            lbl = w.work_type.value.replace("_", " ").title()
            wt_count[lbl] = wt_count.get(lbl, 0) + 1

    wt_text = ""
    for lbl, cnt in list(wt_count.items())[:5]:
        wt_text += f"  • {lbl}: {cnt} ta\n"

    await cb.message.answer(
        f"✅ Smena yopildi!\n\n"
        f"🕐 {session.opened_at.strftime('%H:%M')} → {session.closed_at.strftime('%H:%M')}\n"
        f"⏱ Ishlagan vaqt: {total_min // 60}s {total_min % 60}d\n\n"
        f"📊 BUGUNGI NATIJA:\n"
        f"✅ Tasdiqlangan: {sums['approved']:,.0f} soum\n"
        f"⏳ Kutmoqda:     {sums['pending']:,.0f} soum\n"
        f"💰 Jami:         {sums['approved'] + sums['pending']:,.0f} soum\n\n"
        f"🔧 Ish turlari:\n"
        f"{wt_text if wt_text else '  — ish kiritilmagan'}\n"
        f"Yaxshi ish! 👏"
    )
    await cb.answer()


# ═══ TEZKOR ISH KIRITISH ══════════════════════════════════════════════════════

@router.message(F.text == "⚡ Tez kiritish")
async def quick_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.ishchi:
        await message.answer("Ruxsat yo'q."); return

    session = await get_open_session(db, user.id)
    if not session:
        await message.answer("Smena boshlanmagan! Avval 'Smena boshlash' ni bosing.")
        return

    r = await db.execute(
        select(WorkEntry)
        .where(
            WorkEntry.worker_id == user.id,
            WorkEntry.status.in_([WorkStatus.approved, WorkStatus.adjusted]),
        )
        .order_by(desc(WorkEntry.created_at))
        .limit(3)
    )
    last_works = r.scalars().all()

    if not last_works:
        await message.answer(
            "Hali tasdiqlangan ishingiz yo'q.\n"
            "'Ish kiritish' tugmasidan foydalaning."
        )
        return

    await state.update_data(worker_id=user.id)

    buttons = []
    for w in last_works:
        label = f"🔧 {w.work_type.value.replace('_', ' ').title()}"
        if w.mahsulot_nomi: label += f" — {w.mahsulot_nomi}"
        if w.razmer:        label += f" ({w.razmer})"
        label += f" | {w.birlik_narx:,.0f} soum"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"quick_{w.id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])

    await message.answer(
        "⚡ Tezkor kiritish\n\nQaysi ishni qayta kiritmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("quick_"))
async def quick_select(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    wid = int(cb.data.split("_")[1])
    r   = await db.execute(select(WorkEntry).where(WorkEntry.id == wid))
    ref = r.scalar_one_or_none()
    if not ref:
        await cb.answer("Topilmadi"); return

    await state.update_data(
        work_type=ref.work_type.value,
        mahsulot_nomi=ref.mahsulot_nomi,
        razmer=ref.razmer,
        rang=ref.rang,
        tur=ref.tur,
        sloy=ref.sloy,
        birlik_narx=float(ref.birlik_narx or 0),
        src_product_id=None,
        rulon_product_id=None,
        rulon_ops=[],
    )

    label = ref.work_type.value.replace("_", " ").title()
    if ref.mahsulot_nomi: label += f" — {ref.mahsulot_nomi}"
    if ref.razmer:        label += f" ({ref.razmer})"

    await cb.message.answer(
        f"⚡ {label}\n"
        f"💰 Narx: {ref.birlik_narx:,.0f} soum\n\n"
        f"Nechta? (miqdorni kiriting):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")]
        ]),
    )
    await state.set_state(W.quick_soni)
    await cb.answer()


@router.message(W.quick_soni)
async def quick_soni(m: Message, state: FSMContext):
    soni = _parse_pos_float(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return

    data  = await state.get_data()
    narx  = float(data.get("birlik_narx", 0))
    jami  = soni * narx
    label = data.get("work_type", "").replace("_", " ").title()

    await state.update_data(soni=soni, jami_summa=jami)
    await m.answer(
        f"Tasdiqlaysizmi?\n\n"
        f"⚡ Tezkor: {label}\n"
        f"{data.get('mahsulot_nomi', '')}  {data.get('razmer', '')}\n"
        f"Miqdor: {soni}\n"
        f"Narx:   {narx:,.0f} soum\n"
        f"Jami:   {jami:,.0f} soum",
        reply_markup=get_confirm_keyboard(),
    )
    await state.set_state(W.quick_ok)


@router.callback_query(F.data == "confirm_yes", W.quick_ok)
async def quick_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ ISH O'ZGARTIRISH ════════════════════════════════════════════════════════

@router.message(F.text == "Ish ozgartirish")
async def edit_request_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.ishchi:
        await message.answer("Ruxsat yo'q."); return

    works   = await get_today_works(db, user.id)
    pending = [w for w in works if w.status == WorkStatus.pending]
    if not pending:
        await message.answer("Hozirda o'zgartirish mumkin bo'lgan ish yo'q."); return

    buttons = []
    for w in pending:
        label = f"⏳ {w.work_type.value.replace('_', ' ').title()}"
        if w.mahsulot_nomi: label += f" — {w.mahsulot_nomi}"
        if w.razmer:        label += f" ({w.razmer})"
        label += f" | {w.soni} | {(w.jami_summa or 0):,.0f} soum"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"editreq_{w.id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])

    await state.update_data(worker_id=user.id)
    await message.answer(
        "Qaysi ishni o'zgartirmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("editreq_"))
async def edit_request_selected(cb: CallbackQuery, state: FSMContext):
    wid = int(cb.data.split("_")[1])
    await state.update_data(edit_req_work_id=wid)
    await cb.message.answer(
        "Nima o'zgartirish xohlaysiz?\nQisqa izoh yozing (kamida 5 harf):"
    )
    await state.set_state(W.edit_req_note)
    await cb.answer()


@router.message(W.edit_req_note)
async def edit_request_note(message: Message, state: FSMContext, db: AsyncSession):
    note = message.text.strip()
    if len(note) < 5:
        await message.answer("Biroz batafsil yozing (kamida 5 harf):"); return

    data  = await state.get_data()
    user  = await get_user(db, message.from_user.id)
    entry = await request_worker_edit(db, data["edit_req_work_id"], user.id, note)
    await db.commit()
    await state.clear()

    if not entry:
        await message.answer("Bu ishni o'zgartirish mumkin emas."); return

    await message.answer(f"✅ So'rov yuborildi!\n📝 {note}\nNazoratchi ko'rib chiqadi.")
    inspectors = await get_users_by_role(db, UserRole.nazoratchi)
    for ins in inspectors:
        await _safe_send(
            message.bot, ins.telegram_id,
            f"✏️ Ishchi o'zgartirish so'radi!\n"
            f"👷 {user.full_name}\n"
            f"🔧 {entry.work_type.value.replace('_', ' ').title()}\n"
            f"📝 {note}",
        )


# ═══ ISH KIRITISH ════════════════════════════════════════════════════════════

@router.message(F.text == "Ish kiritish")
async def ish_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.ishchi:
        await message.answer("Ruxsat yo'q."); return

    session = await get_open_session(db, user.id)
    if not session:
        await message.answer("Smena boshlanmagan! Avval 'Smena boshlash' ni bosing.")
        return

    await state.update_data(worker_id=user.id)
    await message.answer("Ish turini tanlang:", reply_markup=get_work_type_keyboard())
    await state.set_state(W.select_type)


# ═══ 1. GOFRA ISHLAB CHIQARISH ════════════════════════════════════════════════
# Razmer: rulon mahsulotidan avtomatik olinadi (p.razmer)
# To'lov: top soni bo'yicha

@router.callback_query(F.data == "work_gofra_ishlab")
async def gi_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(
        work_type=WorkType.gofra_ishlab.value,
        rulon_ops=[],
        razmer=None,
    )
    await cb.message.answer(
        "Qanday turdagi gofra chiqarasiz?",
        reply_markup=get_gofra_type_keyboard(),
    )
    await state.set_state(W.gi_tur)
    await cb.answer()


@router.callback_query(F.data.startswith("gofra_"), W.gi_tur)
async def gi_tur(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    tur = "Yirik" if cb.data == "gofra_yirik" else "Mayin"
    await state.update_data(tur=tur)
    has = await _show_products(
        cb, db, ProductCategory.yarim_tayyor, tur="gofra_uchun_rulon",
        title="Birinchi rulonni tanlang (yarim tayyor):", callback_prefix="gi_rul",
    )
    if not has:
        await state.clear()
        await cb.message.answer("⚠️ Omborda rulon yo'q. Omborchiga murojaat qiling.")
    else:
        await state.set_state(W.gi_rulonlar)
    await cb.answer()


@router.callback_query(F.data.startswith("gi_rul_"), W.gi_rulonlar)
async def gi_rul_select(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    if not p:
        await cb.answer("Mahsulot topilmadi"); return
    data = await state.get_data()
    # Razmer rulondan olinadi — agar hali o'rnatilmagan bo'lsa
    if not data.get("razmer") and p.razmer:
        await state.update_data(cur_rulon_id=pid, razmer=p.razmer)
    else:
        await state.update_data(cur_rulon_id=pid)
    await cb.message.answer(
        f"📦 {p.name}"
        f"{f' | {p.razmer}' if p.razmer else ''}\n"
        f"Qoldiq: {p.miqdor:.1f} {p.birlik}\n\n"
        f"Nechta rulon ishlatdingiz?"
    )
    await cb.answer()


@router.message(W.gi_rulonlar)
async def gi_rul_miqdor(m: Message, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    if "cur_rulon_id" not in data:
        await m.answer("Avval yuqoridan rulon tanlang."); return
    miq = _parse_pos_int(m.text)
    if miq is None:
        await m.answer("Musbat son kiriting:"); return
    ops = data.get("rulon_ops", [])
    ops.append({"product_id": data["cur_rulon_id"], "miqdor": miq})
    sd = dict(data)
    sd.pop("cur_rulon_id", None)
    sd["rulon_ops"] = ops
    await state.set_data(sd)
    await m.answer(
        f"✅ {len(ops)} ta rulon kiritildi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yana rulon qo'shish", callback_data="gi_more")],
            [InlineKeyboardButton(text="✅ Tugatish",            callback_data="gi_done")],
        ]),
    )


@router.callback_query(F.data == "gi_more", W.gi_rulonlar)
async def gi_more(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    has = await _show_products(
        cb, db, ProductCategory.yarim_tayyor, tur="gofra_uchun_rulon",
        title="Yana rulon tanlang (yarim tayyor):", callback_prefix="gi_rul",
    )
    if not has:
        await cb.message.answer("Boshqa rulon yo'q.")
    await cb.answer()


@router.callback_query(F.data == "gi_done", W.gi_rulonlar)
async def gi_done(cb: CallbackQuery, state: FSMContext):
    """Rulonlar tanlandi — rang so'rash."""
    await cb.message.answer(
        "🎨 Gofra rangi:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⬜ Oq",     callback_data="gi_rang_Oq"),
                InlineKeyboardButton(text="⬛ Qora",   callback_data="gi_rang_Qora"),
                InlineKeyboardButton(text="🟡 Qaymoq", callback_data="gi_rang_Qaymoq"),
            ],
            [InlineKeyboardButton(text="🟤 Boshqa rang", callback_data="gi_rang_Boshqa")],
        ]),
    )
    await state.set_state(W.gi_rang)
    await cb.answer()


@router.callback_query(F.data.startswith("gi_rang_"), W.gi_rang)
async def gi_rang(cb: CallbackQuery, state: FSMContext):
    rang = cb.data[8:]  # Oq / Qora / Qaymoq / Boshqa
    await state.update_data(rang=rang)
    data = await state.get_data()

    # Rulon razmeri → gofra razmeri (avtomatik)
    rulon_ops = data.get("rulon_ops", [])
    if rulon_ops:
        # Birinchi tanlangan rulonning razmeri
        from database.models import WarehouseProduct
        # razmer allaqachon state da saqlanishi kerak
        razmer = data.get("razmer", "")
        await cb.message.answer(
            f"✅ Rang: <b>{rang}</b>\n"
            f"📐 Razmer (rulondan avtomatik): <b>{razmer or '—'}</b>\n\n"
            f"Jami nechta top gofra ishlab chiqardingiz?",
            parse_mode="HTML",
        )
    else:
        await cb.message.answer("Jami nechta top gofra ishlab chiqardingiz?")
    await state.set_state(W.gi_soni)
    await cb.answer()


@router.message(W.gi_soni)
async def gi_soni(m: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    data = await state.get_data()
    narx = await get_price(db, WorkType.gofra_ishlab, None)
    await _confirm_screen(
        m, state, WorkType.gofra_ishlab.value, "Gofra Ishlab Chiqarish",
        [
            f"Tur: {data.get('tur', '')}",
            f"Razmer: {data.get('razmer') or 'rulon razmeridan olinadi'}",
            f"{len(data.get('rulon_ops', []))} ta rulon ishlatiladi",
        ],
        soni, narx, soni * narx, W.gi_ok,
    )


@router.callback_query(F.data == "confirm_yes", W.gi_ok)
async def gi_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 2. LAMINATSIYA ══════════════════════════════════════════════════════════
# Razmer: Katta/O'rta/Kichik — narxga ta'sir qiladi
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_laminatsiya")
async def lam_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(work_type=WorkType.laminatsiya.value)
    has = await _show_products(
        cb, db, ProductCategory.xromazes,
        title="Laminat qilinadigan xromazesni tanlang:", callback_prefix="lam_xrom",
    )
    if not has:
        await state.update_data(xromazes_product_id=None)
        await cb.message.answer("Omborda xromazes yo'q. Mahsulot nomini kiriting:")
        await state.set_state(W.lam_nomi)
    else:
        await state.set_state(W.lam_xromazes)
    await cb.answer()


@router.callback_query(F.data.startswith("lam_xrom_"), W.lam_xromazes)
async def lam_xrom(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    if not p:
        await cb.answer("Mahsulot topilmadi"); return
    # Xromazes ma'lumotlarini AVTOMATIK olish — ishchidan qayta so'ramaymiz
    await state.update_data(
        xromazes_product_id=pid,
        mahsulot_nomi=p.name,
        razmer=p.razmer or "",
        rang=p.rang or "",
        razmer_tur=p.razmer_tur,   # laminat qilinganida ham saqlanadi
        xromazes_razmer=p.razmer,
    )
    await cb.message.answer(
        f"📦 <b>{p.name}</b>\n"
        f"📐 {p.razmer_tur or '—'}  |  Aniq: {p.razmer or '—'}"
        f"  🎨 {p.rang or '—'}\n"
        f"Qoldiq: {p.miqdor:.0f} {p.birlik}\n\n"
        f"Nechta laminat qildingiz?",
        parse_mode="HTML"
    )
    await state.set_state(W.lam_soni)
    await cb.answer()


@router.message(W.lam_nomi)
async def lam_nomi(m: Message, state: FSMContext):
    # Fallback: agar xromazes yo'q bo'lsa, qo'lda nom kiritiladi
    if not m.text.strip():
        await m.answer("Nom kiriting:"); return
    await state.update_data(mahsulot_nomi=m.text.strip())
    await m.answer(
        "Razmerini tanlang:",
        reply_markup=_size_keyboard("lam_size"),
    )
    await state.set_state(W.lam_razmer)


@router.callback_query(F.data.startswith("lam_size_"), W.lam_razmer)
async def lam_razmer(cb: CallbackQuery, state: FSMContext):
    razmer = cb.data[9:]
    await state.update_data(razmer=_size_label(razmer))
    await cb.message.answer("Nechta laminat qildingiz?")
    await state.set_state(W.lam_soni)
    await cb.answer()


@router.message(W.lam_soni)
async def lam_soni(m: Message, state: FSMContext):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    await state.update_data(soni=soni)
    await m.answer(
        "Laminat qilingan mahsulot qayerga ketadi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✂️ Tiger kesish uchun", callback_data="lamdest_tiger")],
            [InlineKeyboardButton(text="🔨 Gofra kley uchun",   callback_data="lamdest_gofra")],
            [InlineKeyboardButton(text="📦 Boshqa",             callback_data="lamdest_boshqa")],
        ]),
    )
    await state.set_state(W.lam_dest)


@router.callback_query(F.data.startswith("lamdest_"), W.lam_dest)
async def lam_dest(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    dest = cb.data.split("_")[1]
    await state.update_data(laminat_dest=dest)
    data   = await state.get_data()
    soni   = data["soni"]
    razmer = data.get("razmer", "")
    # Narx razmerga qarab olinadi
    narx   = await get_price(db, WorkType.laminatsiya, razmer if razmer else None)
    dest_labels = {
        "tiger":  "Tiger kesish uchun",
        "gofra":  "Gofra kley uchun",
        "boshqa": "Boshqa",
    }
    await _confirm_screen(
        cb, state, WorkType.laminatsiya.value, "Laminatsiya",
        [
            f"Mahsulot: {data.get('mahsulot_nomi', '')}",
            f"Razmer: {razmer}",
            f"→ {dest_labels.get(dest, dest)}",
        ],
        soni, narx, soni * narx, W.lam_ok,
    )
    await cb.answer()


@router.callback_query(F.data == "confirm_yes", W.lam_ok)
async def lam_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 3. ZAGATOVKA KESISH ═════════════════════════════════════════════════════
# Razmer: Katta/O'rta/Kichik — narxga ta'sir qiladi
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_zagatovka")
async def zag_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """Zagatovka: gofrani kesib, gofra_kley_zagatovka ga xromazes nomi bilan chiqaradi.
    1) Qaysi xromazesga mos (gofra_kley_xromazes, nom uchun) → 2) gofra (zagatovka_uchun_gofra, iste'mol)
    → 3) nechta → natija gofra_kley_zagatovka ga (xromazes nomi/razmeri/qismi bilan)."""
    await state.update_data(work_type=WorkType.zagatovka.value)
    await _zag_show_xrom_varieties(cb, state, db)
    await cb.answer()


async def _zag_show_xrom_varieties(cb, state, db):
    """1-bosqich: gofra_kley_xromazes XILLARINI ko'rsatish (moslash uchun)."""
    rows = (await db.execute(
        select(WarehouseProduct).where(
            WarehouseProduct.category == ProductCategory.yarim_tayyor,
            WarehouseProduct.tur == "gofra_kley_xromazes",
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor > 0,
        ).order_by(WarehouseProduct.name)
    )).scalars().all()
    if not rows:
        await cb.message.answer(
            "⚠️ Yarim tayyorda 'gofra kley uchun xromazes' yo'q.\n"
            "Zagatovkani moslash uchun avval xromazes bo'lishi kerak.\n"
            "Mahsulot nomini qo'lda kiriting:"
        )
        await state.update_data(qism=None, rang=None)
        await state.set_state(W.zag_nomi)
        return
    varieties, order = {}, []
    for p in rows:
        key = (p.name, p.rang or "")
        if key not in varieties:
            varieties[key] = []
            order.append(key)
        varieties[key].append(p)
    vlist = [{"name": k[0], "rang": k[1]} for k in order]
    await state.update_data(zag_xrom_varieties=vlist)
    buttons = []
    for i, k in enumerate(order):
        items = varieties[k]
        label = k[0] + (f" | {k[1]}" if k[1] else "") + f"  ({len(items)} qism)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"zag_xv_{i}")])
    buttons.append([InlineKeyboardButton(text="✍️ Qo'lda nom kiritish", callback_data="zag_manual")])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])
    await cb.message.answer(
        "✂️ Zagatovka — qaysi xromazesga mos? (nom uchun):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(W.zag_xvar)


@router.callback_query(F.data == "zag_manual", W.zag_xvar)
async def zag_manual(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(qism=None, rang=None)
    await cb.message.answer("Mahsulot nomini kiriting:")
    await state.set_state(W.zag_nomi)
    await cb.answer()


@router.callback_query(F.data.startswith("zag_xv_"), W.zag_xvar)
async def zag_xvar(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """Tanlangan xilning qismlarini ko'rsatish (nom/razmer/qism uchun)."""
    idx = int(cb.data.split("_")[2])
    data = await state.get_data()
    vlist = data.get("zag_xrom_varieties", [])
    if idx < 0 or idx >= len(vlist):
        await cb.answer("Topilmadi"); return
    v = vlist[idx]
    await _show_products(
        cb, db, ProductCategory.yarim_tayyor,
        tur="gofra_kley_xromazes",
        name=v["name"],
        rang=(v["rang"] or None),
        title=f"📦 {v['name']} — qaysi qismga mos?",
        callback_prefix="zag_xp",
        label_mode="razmer",
    )
    await state.set_state(W.zag_xpart)
    await cb.answer()


@router.callback_query(F.data.startswith("zag_xp_"), W.zag_xpart)
async def zag_xpart(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """Xromazes qismi tanlandi — nom/razmer/qism/rang saqlanadi (iste'mol YO'Q)."""
    pid = int(cb.data.split("_")[2])
    p = await db.get(WarehouseProduct, pid)
    if not p:
        await cb.answer("Topilmadi"); return
    await state.update_data(
        mahsulot_nomi=p.name, razmer=p.razmer or "",
        qism=p.qism, rang=p.rang or "",
    )
    qlbl = (p.qism or "").upper()
    await cb.message.answer(
        f"✅ Moslandi: <b>{p.name}</b> {qlbl} ({p.razmer or '—'})\n\n"
        f"Endi qaysi gofradan kesasiz?",
        parse_mode="HTML",
    )
    await _zag_show_gofra(cb, state, db)
    await cb.answer()


async def _zag_show_gofra(cb, state, db):
    """2-bosqich: zagatovka_uchun_gofra ni ko'rsatish (iste'mol uchun)."""
    has = await _show_products(
        cb, db, ProductCategory.yarim_tayyor,
        tur="zagatovka_uchun_gofra",
        title="✂️ Qaysi gofradan kesasiz? (yarim tayyor):",
        callback_prefix="zag_gof2",
    )
    if not has:
        await cb.message.answer("⚠️ Yarim tayyorda 'zagatovka uchun gofra' yo'q.")
        await state.update_data(gofra_product_id=None)
    await state.set_state(W.zag_top_soni)


@router.message(W.zag_nomi)
async def zag_nomi(m: Message, state: FSMContext, db: AsyncSession):
    """Qo'lda nom kiritilganda."""
    await state.update_data(mahsulot_nomi=m.text.strip())
    has = await _show_products(
        m, db, ProductCategory.yarim_tayyor,
        tur="zagatovka_uchun_gofra",
        title="✂️ Qaysi gofradan kesasiz? (yarim tayyor):",
        callback_prefix="zag_gof2",
    )
    if not has:
        await m.answer("⚠️ Yarim tayyorda 'zagatovka uchun gofra' yo'q.")
        await state.update_data(gofra_product_id=None)
    await state.set_state(W.zag_top_soni)


@router.callback_query(F.data.startswith("zag_gof2_"), W.zag_top_soni)
async def zag_gof2_sel(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    if not p:
        await cb.answer("Topilmadi"); return
    await state.update_data(gofra_product_id=pid)
    await cb.message.answer(
        f"📦 {p.name}\nQoldiq: {p.miqdor:.0f} {p.birlik}\n\n"
        f"Nechta zagatovka kesdingiz?"
    )
    await state.set_state(W.zag_soni)
    await cb.answer()


@router.message(W.zag_soni)
async def zag_soni(m: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    data   = await state.get_data()
    razmer = data.get("razmer", "")
    qism   = data.get("qism") or ""
    narx   = await get_price(db, WorkType.zagatovka, razmer if razmer else None)
    await _confirm_screen(
        m, state, WorkType.zagatovka.value, "Zagatovka Kesish",
        [
            f"Mahsulot: {data.get('mahsulot_nomi', '')}",
            f"Qism: {qism.upper()}" if qism else "Qism: —",
            f"Razmer: {razmer}",
            f"Natija → gofra kley uchun zagatovka",
        ],
        soni, narx, soni * narx, W.zag_ok,
    )


@router.callback_query(F.data == "confirm_yes", W.zag_ok)
async def zag_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)

    await _save_work_and_ops(cb, state, db)


# ═══ 4. GOFRA KILEY ══════════════════════════════════════════════════════════
# Razmer: Katta/O'rta/Kichik + sloy kombinatsiyasi — narxga ta'sir qiladi
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_gofra_kiley")
async def gk_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(
        work_type=WorkType.gofra_kiley.value,
        zagatovka_ops=[],
    )
    await cb.message.answer(
        "Gofra necha qavatli (sloy)?", reply_markup=get_gofra_sloy_keyboard()
    )
    await state.set_state(W.gk_sloy)
    await cb.answer()


@router.callback_query(F.data.startswith("sloy_"), W.gk_sloy)
async def gk_sloy(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    sloy = cb.data.split("_")[1]
    await state.update_data(sloy=sloy)
    await _gk_show_xrom_varieties(cb, state, db)
    await cb.answer()


async def _gk_show_xrom_varieties(cb, state, db):
    """1-bosqich: yarim tayyor / gofra_kley_xromazes turidan XILLARNI ko'rsatish."""
    rows = (await db.execute(
        select(WarehouseProduct).where(
            WarehouseProduct.category == ProductCategory.yarim_tayyor,
            WarehouseProduct.tur == "gofra_kley_xromazes",
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor > 0,
        ).order_by(WarehouseProduct.name)
    )).scalars().all()

    if not rows:
        await cb.message.answer(
            "⚠️ Yarim tayyorda 'gofra kley uchun xromazes' yo'q.\n"
            "Avval omborchi xromazes o'tkazishi yoki ishchi tayyorlashi kerak. Davom etiladi."
        )
        await state.update_data(xromazes_product_id=None, xromazes_soni=0)
        await _gk_show_zagatovka(cb.message, state, db)
        return

    varieties, order = {}, []
    for p in rows:
        key = (p.name, p.rang or "")
        if key not in varieties:
            varieties[key] = []
            order.append(key)
        varieties[key].append(p)

    vlist = [{"name": k[0], "rang": k[1]} for k in order]
    await state.update_data(gk_xrom_varieties=vlist, gk_xrom_cat="yarim_tayyor")

    buttons = []
    for i, k in enumerate(order):
        items = varieties[k]
        has_qism = any(x.qism for x in items)
        total = sum(float(x.miqdor or 0) for x in items)
        label = k[0]
        if k[1]:
            label += f" | {k[1]}"
        label += f"  ({len(items)} qism)" if has_qism else f"  ({total:.0f} dona)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"gk_xv_{i}")])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])

    await cb.message.answer(
        "🔨 Gofra kley — xromazes xilini tanlang (yarim tayyor):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(W.gk_xrom_variety)


@router.callback_query(F.data.startswith("gk_xv_"), W.gk_xrom_variety)
async def gk_xrom_variety(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """2-bosqich: tanlangan xilning QISMLARINI ko'rsatish."""
    idx = int(cb.data.split("_")[2])
    data = await state.get_data()
    vlist = data.get("gk_xrom_varieties", [])
    if idx < 0 or idx >= len(vlist):
        await cb.answer("Topilmadi"); return
    v = vlist[idx]
    await _show_products(
        cb, db, ProductCategory.yarim_tayyor,
        tur="gofra_kley_xromazes",
        name=v["name"],
        rang=(v["rang"] or None),
        title=f"📦 {v['name']} — qismni tanlang:",
        callback_prefix="gk_xrom",
        label_mode="razmer",
    )
    await state.set_state(W.gk_xromazes)
    await cb.answer()


@router.callback_query(F.data.startswith("gk_xrom_"), W.gk_xromazes)
async def gk_xrom(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    if not p:
        await cb.answer("Mahsulot topilmadi"); return
    # Xromazes ma'lumotlarini saqlab, keyin zagatovkani ko'rsatamiz
    await state.update_data(
        xromazes_product_id=pid,
        mahsulot_nomi=p.name,
        razmer=p.razmer_tur or p.razmer or "",   # gofra kley: razmer_tur (Katta)
        rang=p.rang or "",
        xromazes_razmer=p.razmer,   # sinxronizatsiya: aniq o'lcham (98×62.5)
        razmer_tur=p.razmer_tur,    # tiger uchun
    )
    await cb.message.answer(
        f"📦 <b>{p.name}</b>\n"
        f"📐 {p.razmer_tur or '—'}  ({p.razmer or '—'})  🎨 {p.rang or '—'}\n"
        f"Qoldiq: {p.miqdor:.0f} {p.birlik}\n\n"
        f"Nechta xromazes ishlatdingiz?",
        parse_mode="HTML"
    )
    await state.set_state(W.gk_xrom_soni)
    await cb.answer()


@router.message(W.gk_xrom_soni)
async def gk_xrom_soni(m: Message, state: FSMContext, db: AsyncSession):
    miq = _parse_pos_int(m.text)
    if miq is None:
        await m.answer("Musbat son kiriting:"); return
    await state.update_data(xromazes_soni=miq)
    await _gk_show_zagatovka(m, state, db)


async def _gk_show_zagatovka(target, state, db):
    """Yarim tayyor / gofra_kley_zagatovka turidan XILLARNI ko'rsatish (xil→qism)."""
    msg = target.message if isinstance(target, CallbackQuery) else target

    rows = (await db.execute(
        select(WarehouseProduct).where(
            WarehouseProduct.category == ProductCategory.yarim_tayyor,
            WarehouseProduct.tur == "gofra_kley_zagatovka",
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor > 0,
        ).order_by(WarehouseProduct.name)
    )).scalars().all()

    if not rows:
        await msg.answer(
            "⚠️ Yarim tayyorda 'gofra kley uchun zagatovka' yo'q.\n"
            "Mahsulot nomini kiriting:"
        )
        await state.update_data(zagatovka_ops=[])
        await state.set_state(W.gk_nomi)
        return

    varieties, order = {}, []
    for p in rows:
        key = (p.name, p.rang or "")
        if key not in varieties:
            varieties[key] = []
            order.append(key)
        varieties[key].append(p)

    vlist = [{"name": k[0], "rang": k[1]} for k in order]
    await state.update_data(gk_zag_varieties=vlist)

    buttons = []
    for i, k in enumerate(order):
        items = varieties[k]
        has_qism = any(x.qism for x in items)
        total = sum(float(x.miqdor or 0) for x in items)
        label = k[0]
        if k[1]:
            label += f" | {k[1]}"
        label += f"  ({len(items)} qism)" if has_qism else f"  ({total:.0f} dona)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"gk_zv_{i}")])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])

    await msg.answer(
        "🔨 Gofra kley — zagatovka xilini tanlang (yarim tayyor):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(W.gk_zag_variety)


@router.callback_query(F.data.startswith("gk_zv_"), W.gk_zag_variety)
async def gk_zag_variety(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """Tanlangan zagatovka xilining QISMLARINI ko'rsatish."""
    idx = int(cb.data.split("_")[2])
    data = await state.get_data()
    vlist = data.get("gk_zag_varieties", [])
    if idx < 0 or idx >= len(vlist):
        await cb.answer("Topilmadi"); return
    v = vlist[idx]
    await _show_products(
        cb, db, ProductCategory.yarim_tayyor,
        tur="gofra_kley_zagatovka",
        name=v["name"],
        rang=(v["rang"] or None),
        title=f"📦 {v['name']} — zagatovka qismini tanlang:",
        callback_prefix="gk_zag1",
        label_mode="razmer",
    )
    await state.set_state(W.gk_zag1)
    await cb.answer()


@router.callback_query(F.data.startswith("gk_zag1_"), W.gk_zag1)
async def gk_zag1_select(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    await state.update_data(gk_cur_zag_id=pid)
    await cb.message.answer(
        f"📦 {p.name if p else '?'}\nNechta oldingiz?"
    )
    await state.set_state(W.gk_zag1_soni)
    await cb.answer()


@router.message(W.gk_zag1_soni)
async def gk_zag1_soni(m: Message, state: FSMContext, db: AsyncSession):
    miq = _parse_pos_int(m.text)
    if miq is None:
        await m.answer("Musbat son kiriting:"); return
    data    = await state.get_data()
    zag_ops = data.get("zagatovka_ops", [])
    zag_ops.append({"product_id": data["gk_cur_zag_id"], "miqdor": miq})
    await state.update_data(zagatovka_ops=zag_ops)
    if str(data.get("sloy", "3")) == "5":
        has = await _show_products(
            m, db, ProductCategory.yarim_tayyor,
            tur="gofra_kley_zagatovka",
            title="2-chi zagatovkani tanlang (5-sloy, yarim tayyor):", callback_prefix="gk_zag2",
        )
        if has:
            await state.set_state(W.gk_zag2); return

    # Nom va razmer xromazesdan allaqachon olingan bo'lsa, to'g'ridan soni so'raymiz
    if data.get("mahsulot_nomi") and data.get("xromazes_product_id"):
        await m.answer("Jami nechta mahsulot yopishtirdingiz?")
        await state.set_state(W.gk_soni)
    else:
        await m.answer("Mahsulot nomini kiriting:")
        await state.set_state(W.gk_nomi)


@router.callback_query(F.data.startswith("gk_zag2_"), W.gk_zag2)
async def gk_zag2_select(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    await state.update_data(gk_cur_zag2_id=pid)
    await cb.message.answer(f"📦 {p.name if p else '?'}\nNechta oldingiz?")
    await state.set_state(W.gk_zag2_soni)
    await cb.answer()


@router.message(W.gk_zag2_soni)
async def gk_zag2_soni(m: Message, state: FSMContext):
    miq = _parse_pos_int(m.text)
    if miq is None:
        await m.answer("Musbat son kiriting:"); return
    data    = await state.get_data()
    zag_ops = data.get("zagatovka_ops", [])
    zag_ops.append({"product_id": data["gk_cur_zag2_id"], "miqdor": miq})
    await state.update_data(zagatovka_ops=zag_ops)
    await m.answer("Mahsulot nomini kiriting:")
    await state.set_state(W.gk_nomi)


@router.message(W.gk_nomi)
async def gk_nomi(m: Message, state: FSMContext):
    await state.update_data(mahsulot_nomi=m.text.strip())
    data = await state.get_data()
    # Razmer xromazesdan allaqachon olingan bo'lsa, soni so'raymiz
    if data.get("razmer"):
        await m.answer("Jami nechta mahsulot yopishtirdingiz?")
        await state.set_state(W.gk_soni)
    else:
        await m.answer(
            "Razmerini tanlang:",
            reply_markup=_size_keyboard("gk_size"),
        )
        await state.set_state(W.gk_razmer)


@router.callback_query(F.data.startswith("gk_size_"), W.gk_razmer)
async def gk_razmer(cb: CallbackQuery, state: FSMContext):
    razmer = cb.data[8:]
    await state.update_data(razmer=_size_label(razmer))
    await cb.message.answer("Jami nechta mahsulot yopishtirdingiz?")
    await state.set_state(W.gk_soni)
    await cb.answer()


@router.message(W.gk_soni)
async def gk_soni(m: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    data   = await state.get_data()
    sloy   = str(data.get("sloy", "3"))
    razmer = data.get("razmer", "")
    # Narx razmer + sloy kombinatsiyasi bo'yicha: "Katta 3sloy"
    variant = f"{razmer} {sloy}sloy" if razmer else f"{sloy}sloy"
    narx   = await get_price(db, WorkType.gofra_kiley, variant)
    if not narx:
        # Eski format bilan ham urinib ko'rish (orqaga moslik)
        narx = await get_price(db, WorkType.gofra_kiley, sloy)
    await _confirm_screen(
        m, state, WorkType.gofra_kiley.value, "Gofra Kiley",
        [
            f"Mahsulot: {data.get('mahsulot_nomi', '')}",
            f"Razmer: {razmer}",
            f"Sloy: {sloy}",
            f"{len(data.get('zagatovka_ops', []))} xil zagatovka",
        ],
        soni, narx, soni * narx, W.gk_ok,
    )


@router.callback_query(F.data == "confirm_yes", W.gk_ok)
async def gk_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 5. TIGER KESISH ═════════════════════════════════════════════════════════
# Razmer: Katta/O'rta/Kichik — narxga ta'sir qiladi
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_tiger_kesish")
async def tiger_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """
    Tiger uchun materiallar:
    1. yarim_tayyor (tur=tiger_uchun) — gofra kleydan o'tgan tayyor materiallar
    2. laminat_xromazes + xromazes — bevosita tiger kesish uchun
    Barchasi bitta ro'yxatda ko'rinadi.
    """
    await state.update_data(work_type=WorkType.tiger_kesish.value)

    # 1. tiger_uchun yarim tayyor materiallar
    has1 = await _show_products(
        cb, db, ProductCategory.yarim_tayyor, tur="tiger_uchun",
        title="✂️ Tiger kesish — gofra kleydan o'tgan materiallar:",
        callback_prefix="tiger_src",
        label_mode="razmer_tur",   # Tiger: Katta/O'rta/Kichik (narx uchun)
    )
    # 2. Bevosita tiger uchun xromazeslar
    has2 = await _show_products(
        cb, db, ProductCategory.laminat_xromazes,
        title="✨ Tiger uchun xromazeslar (bevosita):",
        callback_prefix="tiger_src",
        extra_cats=[ProductCategory.xromazes],
        label_mode="razmer_tur",
        yonalish="tiger",   # Faqat tiger yo'nalishlilar
    )

    if not has1 and not has2:
        await state.update_data(src_product_id=None)
        await cb.message.answer(
            "⚠️ Tiger uchun material yo'q.\n\n"
            "Razmerini tanlang:",
            reply_markup=_size_keyboard("tiger_size"),
        )
        await state.set_state(W.tiger_razmer)
        await cb.answer(); return

    await state.set_state(W.tiger_src)
    await cb.answer()


@router.callback_query(F.data.startswith("tiger_src_"), W.tiger_src)
async def tiger_src(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    await state.update_data(src_product_id=pid, mahsulot_nomi=p.name if p else "")
    await cb.message.answer(
        f"📦 {p.name if p else '?'}\n"
        f"Qoldiq: {p.miqdor if p else '?'}\n\n"
        f"Razmerini tanlang:\n(Narx razmerga qarab o'zgaradi)",
        reply_markup=_size_keyboard("tiger_size"),
    )
    await state.set_state(W.tiger_razmer)
    await cb.answer()


@router.callback_query(F.data.startswith("tiger_size_"), W.tiger_razmer)
async def tiger_razmer(cb: CallbackQuery, state: FSMContext):
    razmer = cb.data[11:]
    await state.update_data(razmer=_size_label(razmer))
    await cb.message.answer("Nechta kesdingiz?")
    await state.set_state(W.tiger_soni)
    await cb.answer()


@router.message(W.tiger_soni)
async def tiger_soni(m: Message, state: FSMContext):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    await state.update_data(soni=soni)
    await m.answer(
        "Kesilgan mahsulot qayerga ketadi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tayyor mahsulotlarga",  callback_data="tdest_tayyor_mahsulot")],
            [InlineKeyboardButton(text="🧵 Adyol tikish uchun",   callback_data="tdest_adyol_tikish_uchun")],
            [InlineKeyboardButton(text="💼 Pastel tikish uchun",  callback_data="tdest_pastel_tikish_uchun")],
            [InlineKeyboardButton(text="📌 Stepler tikish uchun", callback_data="tdest_stepler_uchun")],
            [InlineKeyboardButton(text="🔗 Yopishtirma uchun",    callback_data="tdest_yopish_uchun")],
            [InlineKeyboardButton(text="📝 Boshqa yarim tayyor",   callback_data="tdest_boshqa")],
        ]),
    )
    await state.set_state(W.tiger_dest)


@router.callback_query(F.data.startswith("tdest_"), W.tiger_dest)
async def tiger_dest(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    dest = cb.data[6:]
    await state.update_data(dest_tur=dest)
    data   = await state.get_data()
    soni   = data["soni"]
    razmer = data.get("razmer", "")
    narx   = await get_price(db, WorkType.tiger_kesish, razmer if razmer else None)
    dest_labels = {
        "tayyor_mahsulot":     "✅ Tayyor mahsulot",
        "adyol_tikish_uchun":  "Adyol tikish",
        "pastel_tikish_uchun": "Pastel tikish",
        "stepler_uchun":       "Stepler",
        "yopish_uchun":        "Yopishtirma",
        "boshqa":              "Boshqa yarim tayyor",
    }
    await _confirm_screen(
        cb, state, WorkType.tiger_kesish.value, "Tiger Kesish",
        [
            f"Material: {data.get('mahsulot_nomi', '-')}",
            f"Razmer: {razmer}",
            f"→ {dest_labels.get(dest, dest)}",
        ],
        soni, narx, soni * narx, W.tiger_ok,
    )
    await cb.answer()


@router.callback_query(F.data == "confirm_yes", W.tiger_ok)
async def tiger_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 6. LIST QOG'OZ KESISH ═══════════════════════════════════════════════════
# Razmer: ERKIN MATN (masalan: "25x30") — narxga ta'sir QILMAYDI
# To'lov: KILOGRAMM bo'yicha (narx/kg)

@router.callback_query(F.data == "work_list_qogoz")
async def list_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(work_type=WorkType.list_qogoz.value)
    has = await _show_products(
        cb, db, ProductCategory.yarim_tayyor, tur="list_qogoz_uchun_rulon",
        title="Qaysi rulondan foydalandingiz? (yarim tayyor)", callback_prefix="lst_rul",
    )
    if not has:
        await state.update_data(rulon_product_id=None)
        await cb.message.answer(
            "Omborda rulon yo'q.\n\n"
            "List razmerini kiriting (masalan: 25x30, 40x60):"
        )
        await state.set_state(W.list_razmer)
    else:
        await state.set_state(W.list_rulon)
    await cb.answer()


@router.callback_query(F.data.startswith("lst_rul_"), W.list_rulon)
async def list_rulon(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    await state.update_data(rulon_product_id=pid)
    await cb.message.answer(
        f"📦 {p.name if p else '?'}\n"
        f"Qoldiq: {p.miqdor if p else '?'} {p.birlik if p else ''}\n\n"
        f"List razmerini kiriting (masalan: 25x30, 40x60, 60x80):"
    )
    await state.set_state(W.list_razmer)
    await cb.answer()


@router.message(W.list_razmer)
async def list_razmer(m: Message, state: FSMContext):
    razmer = m.text.strip()
    if not razmer:
        await m.answer("Razmer kiriting (masalan: 25x30):"); return
    await state.update_data(razmer=razmer)
    await m.answer(
        f"Razmer: {razmer}\n\n"
        f"Kesgan listingiz kilosi qancha? (kg):\n"
        f"(To'lov kilogramm bo'yicha hisoblanadi)"
    )
    await state.set_state(W.list_kilosi)


@router.message(W.list_kilosi)
async def list_kilosi(m: Message, state: FSMContext):
    kg = _parse_pos_float(m.text)
    if kg is None:
        await m.answer("Musbat raqam kiriting (masalan: 15.5):"); return
    await state.update_data(soni=kg)
    await m.answer(
        "Kesilgan list qayerga ketadi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✂️ Tiger kesish uchun",   callback_data="ldest_tiger_uchun")],
            [InlineKeyboardButton(text="🔗 Yopishtirma uchun",    callback_data="ldest_yopish_uchun")],
            [InlineKeyboardButton(text="🖨️ Xromazeslar omboriga", callback_data="ldest_xromazes")],
            [InlineKeyboardButton(text="📦 Tayyor mahsulotlarga", callback_data="ldest_tayyor_mahsulot")],
        ]),
    )
    await state.set_state(W.list_dest)


@router.callback_query(F.data.startswith("ldest_"), W.list_dest)
async def list_dest(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    dest = cb.data[6:]
    await state.update_data(dest_tur=dest)
    data = await state.get_data()
    kg   = data["soni"]
    # Narx kg bo'yicha, razmer_turi ta'sir qilmaydi
    narx = await get_price(db, WorkType.list_qogoz, None)
    DEST_LABELS = {
        "tiger_uchun":         "Tiger kesish uchun",
        "yopish_uchun":        "Yopishtirma uchun",
        "adyol_tikish_uchun":  "Adyol tikish uchun",
        "pastel_tikish_uchun": "Pastel tikish uchun",
        "xromazes":            "Xromazeslar omboriga",
        "tayyor_mahsulot":     "Tayyor mahsulotlarga",
    }
    await _confirm_screen(
        cb, state, WorkType.list_qogoz.value, "List Qog'oz Kesish",
        [
            f"Razmer: {data.get('razmer', '')}",
            f"Miqdor: {kg} kg",
            f"→ {DEST_LABELS.get(dest, dest)}",
        ],
        kg, narx, kg * narx, W.list_ok,
    )
    await cb.answer()


@router.callback_query(F.data == "confirm_yes", W.list_ok)
async def list_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 7. STEPLER TIKISH ═══════════════════════════════════════════════════════
# Razmer: Katta/O'rta/Kichik — narxga ta'sir qiladi
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_stepler_tikish")
async def stpl_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(work_type=WorkType.stepler_tikish.value)
    has = await _show_products(
        cb, db, ProductCategory.yarim_tayyor, tur="stepler_uchun",
        title="Stepler tikish uchun material tanlang:", callback_prefix="stpl_src",
    )
    if not has:
        await state.update_data(src_product_id=None)
        await cb.message.answer(
            "Material yo'q.\n\n"
            "Razmerini tanlang:\n(Narx razmerga qarab o'zgaradi)",
            reply_markup=_size_keyboard("stpl_size"),
        )
        await state.set_state(W.stpl_razmer)
    else:
        await state.set_state(W.stpl_src)
    await cb.answer()


@router.callback_query(F.data.startswith("stpl_src_"), W.stpl_src)
async def stpl_src(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    await state.update_data(src_product_id=pid, mahsulot_nomi=p.name if p else "")
    await cb.message.answer(
        f"📦 {p.name if p else '?'}\n\n"
        f"Razmerini tanlang:\n(Narx razmerga qarab o'zgaradi)",
        reply_markup=_size_keyboard("stpl_size"),
    )
    await state.set_state(W.stpl_razmer)
    await cb.answer()


@router.callback_query(F.data.startswith("stpl_size_"), W.stpl_razmer)
async def stpl_razmer(cb: CallbackQuery, state: FSMContext):
    razmer = cb.data[10:]
    await state.update_data(razmer=_size_label(razmer))
    await cb.message.answer(
        "📦 Ombordan nechta material oldingiz?\n"
        "(Stepler tikish uchun ajratilgan miqdor)"
    )
    await state.set_state(W.stpl_ombor)
    await cb.answer()


@router.message(W.stpl_ombor)
async def stpl_ombor(m: Message, state: FSMContext):
    """Ombordan olingan miqdor."""
    ombor = _parse_pos_int(m.text)
    if ombor is None:
        await m.answer("Musbat son kiriting:"); return
    await state.update_data(ombor_soni=ombor)
    await m.answer("✅ Nechta tiktingiz?")
    await state.set_state(W.stpl_soni)


@router.message(W.stpl_soni)
async def stpl_soni(m: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    data   = await state.get_data()
    razmer = data.get("razmer", "")
    ombor  = data.get("ombor_soni", soni)
    narx   = await get_price(db, WorkType.stepler_tikish, razmer if razmer else None)
    await state.update_data(ombor_soni=ombor)
    await _confirm_screen(
        m, state, WorkType.stepler_tikish.value, "Stepler Tikish",
        [
            f"Material: {data.get('mahsulot_nomi', '-')}",
            f"Razmer: {razmer}",
            f"Ombordan olindi: {ombor} ta",
            f"Tikildi: {soni} ta",
        ],
        soni, narx, soni * narx, W.stpl_ok,
    )


@router.callback_query(F.data == "confirm_yes", W.stpl_ok)
async def stpl_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 8. RULON O'RASH ═════════════════════════════════════════════════════════
# Razmer: mahsulot (rulon) dan olinadi — avtomatik
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_rulon_orash")
async def ro_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(work_type=WorkType.rulon_orash.value)
    has = await _show_products(
        cb, db, ProductCategory.rulon,
        title="Qaysi rulonni o'raysiz?", callback_prefix="ro_rul",
    )
    if not has:
        await state.update_data(rulon_product_id=None)
        await cb.message.answer("Omborda rulon yo'q. Nechta rulon o'radingiz?")
        await state.set_state(W.ro_soni)
    else:
        await state.set_state(W.ro_rulon)
    await cb.answer()


@router.callback_query(F.data.startswith("ro_rul_"), W.ro_rulon)
async def ro_rul(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    # Razmer rulon mahsulotidan olinadi
    await state.update_data(
        rulon_product_id=pid,
        razmer=p.razmer if p else None,
        mahsulot_nomi=p.name if p else "",
    )
    await cb.message.answer(
        f"📦 {p.name if p else '?'}"
        f"{f' | {p.razmer}' if p and p.razmer else ''}\n"
        f"Qoldiq: {p.miqdor if p else '?'} {p.birlik if p else ''}\n\n"
        f"Nechta rulon o'radingiz?"
    )
    await state.set_state(W.ro_soni)
    await cb.answer()


@router.message(W.ro_soni)
async def ro_soni(m: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    data = await state.get_data()
    narx = await get_price(db, WorkType.rulon_orash, None)
    await _confirm_screen(
        m, state, WorkType.rulon_orash.value, "Rulon O'rash",
        [
            f"Rulon: {data.get('mahsulot_nomi', '-')}",
            f"Razmer: {data.get('razmer') or 'ko\'rsatilmagan'}",
            f"{soni} rulon → {soni * 2} bo'lak",
        ],
        soni, narx, soni * narx, W.ro_ok,
    )


@router.callback_query(F.data == "confirm_yes", W.ro_ok)
async def ro_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 9. RULONGA SALAFAN ══════════════════════════════════════════════════════
# Razmer: rulon mahsulotidan olinadi — avtomatik
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_rulonga_salafan")
async def rs_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(work_type=WorkType.rulonga_salafan.value)
    has = await _show_products(
        cb, db, ProductCategory.rulon,
        title="Qaysi rulonga salafan o'raysiz?", callback_prefix="rs_rul",
    )
    if not has:
        await state.update_data(rulon_product_id=None)
        await cb.message.answer(
            "Omborda rulon yo'q.\n\n"
            "Salafan rangini kiriting (masalan: Shaffof, Qora, Ko'k):"
        )
        await state.set_state(W.rs_rang)
    else:
        await state.set_state(W.rs_rulon)
    await cb.answer()


@router.callback_query(F.data.startswith("rs_rul_"), W.rs_rulon)
async def rs_rul(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    # Razmer rulon mahsulotidan olinadi
    await state.update_data(
        rulon_product_id=pid,
        razmer=p.razmer if p else None,
        mahsulot_nomi=p.name if p else "",
    )
    # Salafan rulon — rulon kategoriyasidan tur="salafanli"
    has = await _show_products(
        cb, db, ProductCategory.rulon, tur="salafanli",
        title="🎁 Qaysi salafan rulondan foydalanasiz?", callback_prefix="rs_sal",
    )
    if not has:
        # yarim_tayyor (salafan_uchun) dan ham qidirish
        has2 = await _show_products(
            cb, db, ProductCategory.yarim_tayyor, tur="salafan_uchun",
            title="Salafan materialini tanlang:", callback_prefix="rs_sal",
        )
        if not has2:
            await state.update_data(salafan_product_id=None)
            await cb.message.answer(
                f"📦 Rulon: {p.name if p else '?'}\n\n"
                f"Salafan yo'q. Rangini kiriting:"
            )
            await state.set_state(W.rs_rang)
            await cb.answer(); return
    await state.set_state(W.rs_salafan)
    await cb.answer()


@router.callback_query(F.data.startswith("rs_sal_"), W.rs_salafan)
async def rs_sal(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    await state.update_data(salafan_product_id=pid)
    await cb.message.answer(
        f"📦 Salafan: {p.name if p else '?'}\n\n"
        f"Salafan rangini kiriting (masalan: Shaffof, Qora):"
    )
    await state.set_state(W.rs_rang)
    await cb.answer()


@router.message(W.rs_rang)
async def rs_rang(m: Message, state: FSMContext):
    await state.update_data(rang=m.text.strip())
    await m.answer("Nechta rulonga salafan o'radingiz?")
    await state.set_state(W.rs_soni)


@router.message(W.rs_soni)
async def rs_soni(m: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    data = await state.get_data()
    narx = await get_price(db, WorkType.rulonga_salafan, None)
    await _confirm_screen(
        m, state, WorkType.rulonga_salafan.value, "Rulonga Salafan",
        [
            f"Rulon: {data.get('mahsulot_nomi', '-')}",
            f"Razmer: {data.get('razmer') or 'ko\'rsatilmagan'}",
            f"Rang: {data.get('rang', '')}",
        ],
        soni, narx, soni * narx, W.rs_ok,
    )


@router.callback_query(F.data == "confirm_yes", W.rs_ok)
async def rs_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ 10. YOPISHTIRMA ═════════════════════════════════════════════════════════
# Razmer: Katta/O'rta/Kichik — narxga ta'sir qiladi
# To'lov: dona soni bo'yicha

@router.callback_query(F.data == "work_yopishtirma")
async def yop_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.update_data(work_type=WorkType.yopishtirma.value)
    has = await _show_products(
        cb, db, ProductCategory.yarim_tayyor, tur="yopish_uchun",
        title="Yopishtirish uchun material tanlang:", callback_prefix="yop_src",
    )
    if not has:
        await state.update_data(src_product_id=None)
        await cb.message.answer(
            "Material yo'q.\n\n"
            "Razmerini tanlang:\n(Narx razmerga qarab o'zgaradi)",
            reply_markup=_size_keyboard("yop_size"),
        )
        await state.set_state(W.yop_razmer)
    else:
        await state.set_state(W.yop_src)
    await cb.answer()


@router.callback_query(F.data.startswith("yop_src_"), W.yop_src)
async def yop_src(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2])
    p   = await db.get(WarehouseProduct, pid)
    await state.update_data(src_product_id=pid, mahsulot_nomi=p.name if p else "")
    await cb.message.answer(
        f"📦 {p.name if p else '?'}\n\n"
        f"Razmerini tanlang:\n(Narx razmerga qarab o'zgaradi)",
        reply_markup=_size_keyboard("yop_size"),
    )
    await state.set_state(W.yop_razmer)
    await cb.answer()


@router.callback_query(F.data.startswith("yop_size_"), W.yop_razmer)
async def yop_razmer(cb: CallbackQuery, state: FSMContext):
    razmer = cb.data[9:]
    await state.update_data(razmer=_size_label(razmer))
    await cb.message.answer(
        "📦 Ombordan nechta material oldingiz?\n"
        "(Yopishtirish uchun ajratilgan miqdor)"
    )
    await state.set_state(W.yop_ombor)
    await cb.answer()


@router.message(W.yop_ombor)
async def yop_ombor(m: Message, state: FSMContext):
    """Ombordan olingan miqdor."""
    ombor = _parse_pos_int(m.text)
    if ombor is None:
        await m.answer("Musbat son kiriting:"); return
    await state.update_data(ombor_soni=ombor)
    await m.answer("✅ Nechta yopishtirdingiz?")
    await state.set_state(W.yop_soni)


@router.message(W.yop_soni)
async def yop_soni(m: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_pos_int(m.text)
    if soni is None:
        await m.answer("Musbat son kiriting:"); return
    data   = await state.get_data()
    razmer = data.get("razmer", "")
    ombor  = data.get("ombor_soni", soni)
    narx   = await get_price(db, WorkType.yopishtirma, razmer if razmer else None)
    await state.update_data(ombor_soni=ombor)
    await _confirm_screen(
        m, state, WorkType.yopishtirma.value, "Yopishtirma",
        [
            f"Material: {data.get('mahsulot_nomi', '-')}",
            f"Razmer: {razmer}",
            f"Ombordan olindi: {ombor} ta",
            f"Yopishtirdi: {soni} ta",
        ],
        soni, narx, soni * narx, W.yop_ok,
    )


@router.callback_query(F.data == "confirm_yes", W.yop_ok)
async def yop_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save_work_and_ops(cb, state, db)


# ═══ BEKOR ════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.in_(["confirm_no", "cancel"]))
async def cancel_action(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("❌ Bekor qilindi.")
    await cb.answer()


# ═══ ISHCHI SHAXSIY ══════════════════════════════════════════════════════════

@router.message(F.text == "Bugungi daromad")
async def bugungi_daromad(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user: return
    s       = await get_today_sum(db, user.id)
    minutes = await get_today_work_minutes(db, user.id)
    session = await get_open_session(db, user.id)
    smena_status = f"🟢 Ochiq — {session.smena.value}" if session else "🔴 Smena yopiq"
    await message.answer(
        f"💰 Bugungi daromad\n\n"
        f"✅ Tasdiqlangan: {s['approved']:,.0f} soum\n"
        f"⏳ Kutmoqda:     {s['pending']:,.0f} soum\n"
        f"📊 Jami:         {s['approved'] + s['pending']:,.0f} soum\n\n"
        f"⏱ Ishlagan: {minutes // 60}s {minutes % 60}d\n"
        f"{smena_status}"
    )


@router.message(F.text == "Bugungi ishlarim")
async def bugungi_ishlarim(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user: return
    entries = await get_today_works(db, user.id)
    if not entries:
        await message.answer("Bugun ish kiritilmagan."); return

    text  = "📋 Bugungi ishlarim\n\n"
    total = 0.0
    for e in entries:
        icon  = STATUS_ICONS.get(e.status, "?")
        text += f"{icon} {e.work_type.value.replace('_', ' ').title()}"
        if e.mahsulot_nomi: text += f" — {e.mahsulot_nomi}"
        if e.razmer:        text += f" ({e.razmer})"
        text += f"\n   🔢 {e.soni}  💰 {(e.jami_summa or 0):,.0f} soum\n"
        if e.status in (WorkStatus.approved, WorkStatus.adjusted):
            total += e.jami_summa or 0

    text += f"\n💰 Tasdiqlangan jami: {total:,.0f} soum"
    await message.answer(text)


@router.message(F.text == "Oylik maosh")
async def oylik_maosh(message: Message, db: AsyncSession):
    from database.queries import calculate_and_save_salary
    user = await get_user(db, message.from_user.id)
    if not user: return
    now = datetime.now()
    rep = await calculate_and_save_salary(db, user.id, now.month, now.year)
    await message.answer(
        f"💰 Oylik maosh — {now.month}/{now.year}\n\n"
        f"✅ Ish:    {rep.jami_ish_summa:,.0f} soum\n"
        f"❌ Jarima: -{rep.jami_jarima:,.0f} soum\n"
        f"💳 Avans:  -{rep.jami_avans:,.0f} soum\n"
        f"{'─' * 28}\n"
        f"💵 SOF:    {rep.sof_maosh:,.0f} soum\n\n"
        f"{'✅ Tasdiqlangan' if rep.admin_tasdiqladi else '⏳ Tasdiq kutilmoqda'}"
    )


@router.message(F.text == "Mening jarimalarim")
async def mening_jarimalarim(message: Message, db: AsyncSession):
    from sqlalchemy import extract
    from database.models import Penalty
    user = await get_user(db, message.from_user.id)
    if not user: return
    now = datetime.now()
    r   = await db.execute(
        select(Penalty).where(
            Penalty.worker_id == user.id,
            extract("month", Penalty.created_at) == now.month,
            extract("year",  Penalty.created_at) == now.year,
        ).order_by(Penalty.created_at.desc())
    )
    penalties = r.scalars().all()
    if not penalties:
        await message.answer("✅ Bu oyda jarimangiz yo'q!"); return

    text  = f"⚠️ Jarimalar — {now.month}/{now.year}\n\n"
    total = 0.0
    for pen in penalties:
        conf  = "✅" if pen.worker_confirmed else "⏳"
        text += f"{conf} {pen.penalty_type.value.title()}: {pen.sabab}\n"
        text += f"   💰 {pen.summa:,.0f} soum\n\n"
        total += pen.summa
    text += f"💸 Jami: {total:,.0f} soum"
    await message.answer(text)


@router.message(F.text == "Kabinet")
async def kabinet(message: Message, db: AsyncSession):
    from database.queries import calculate_and_save_salary
    user = await get_user(db, message.from_user.id)
    if not user: return
    now     = datetime.now()
    rep     = await calculate_and_save_salary(db, user.id, now.month, now.year)
    minutes = await get_today_work_minutes(db, user.id)
    session = await get_open_session(db, user.id)
    smena   = f"🟢 Ochiq: {session.smena.value}" if session else "🔴 Smena yopiq"

    foiz   = min(100, int((rep.jami_ish_summa / OYLIK_MAQSAD) * 100)) if OYLIK_MAQSAD > 0 else 0
    filled = foiz // 10
    bar    = "🟩" * filled + "⬜" * (10 - filled)

    if foiz >= 100:
        maqsad_text = "🎉 Maqsadga yetdingiz!"
    else:
        qoldi = max(0, OYLIK_MAQSAD - rep.jami_ish_summa)
        maqsad_text = f"Qoldi: {qoldi:,.0f} soum"

    await message.answer(
        f"👤 {user.full_name}\n"
        f"📞 {user.phone or '—'}\n"
        f"🏷 {user.role.value}\n\n"
        f"⏱ Bugun: {minutes // 60}s {minutes % 60}d  |  {smena}\n\n"
        f"📊 {now.month}/{now.year} oylik:\n"
        f"✅ Ish:    {rep.jami_ish_summa:,.0f} soum\n"
        f"❌ Jarima: -{rep.jami_jarima:,.0f} soum\n"
        f"💳 Avans:  -{rep.jami_avans:,.0f} soum\n"
        f"💵 SOF:    {rep.sof_maosh:,.0f} soum\n\n"
        f"🎯 Oylik maqsad: {OYLIK_MAQSAD:,.0f} soum\n"
        f"{bar} {foiz}%\n"
        f"{maqsad_text}"
    )
