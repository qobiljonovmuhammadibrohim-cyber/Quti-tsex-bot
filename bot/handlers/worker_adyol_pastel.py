"""
bot/handlers/worker_adyol_pastel.py — Adyol/Pastel tikish va qoqish v3
YANGI TIZIM:
  Har ishchi o'z qismini mustaqil kiritadi — komple majburiy emas.
  Ishchi A → 2 yon tikadi
  Ishchi B → tepa tikadi
  Ishchi C → past tikadi
"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import (
    UserRole, WorkEntry, WorkStatus, WorkType,
    ProductCategory, WarehouseProduct,
)
from database.queries import get_user, get_price, get_users_by_role
from utils.warehouse_ops import run_warehouse_ops

logger = logging.getLogger(__name__)
router = Router()


class AP(StatesGroup):
    at_src  = State()
    at_soni = State()
    at_ok   = State()
    dt_src  = State()
    dt_soni = State()
    dt_ok   = State()
    aq_tur  = State()
    aq_src  = State()
    aq_soni = State()
    aq_dest = State()
    aq_ok   = State()
    pq_tur  = State()
    pq_src  = State()
    pq_soni = State()
    pq_dest = State()
    pq_ok   = State()


def _icon(p):
    m = float(p.miqdor)
    if m <= float(p.min_threshold):    return "\U0001f534"
    if m <= float(p.yellow_threshold): return "\U0001f7e1"
    return "\U0001f7e2"


def _label(p):
    from constants import QISM_ICONS
    qism_icon = QISM_ICONS.get(p.qism or "", "")
    qism_text = f"{qism_icon} {(p.qism or '').upper()}: " if p.qism else ""
    parts = [p.name]
    if p.razmer_tur: parts.append(p.razmer_tur)
    if p.razmer:     parts.append(f"({p.razmer})")
    return f"{qism_text}{_icon(p)} {' | '.join(parts)} — {p.miqdor:.0f} {p.birlik}"


async def _show_tur_materials(target, db, tur, title, prefix):
    q = (
        select(WarehouseProduct)
        .where(
            WarehouseProduct.category == ProductCategory.yarim_tayyor,
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor   >  0,
            WarehouseProduct.tur      == tur,
        )
        .order_by(WarehouseProduct.qism, WarehouseProduct.name, WarehouseProduct.razmer_tur)
    )
    products = (await db.execute(q)).scalars().all()
    if not products:
        return False
    buttons = [
        [InlineKeyboardButton(text=_label(p), callback_data=f"{prefix}_{p.id}")]
        for p in products
    ]
    buttons.append([InlineKeyboardButton(text="\u274c Bekor", callback_data="ap_cancel")])
    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    return True


async def _show_tur_qoqish(cb, db, tur_key, title, prefix):
    q = (
        select(WarehouseProduct)
        .where(
            WarehouseProduct.category == ProductCategory.yarim_tayyor,
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor   >  0,
            WarehouseProduct.tur      == tur_key,
        )
        .order_by(WarehouseProduct.name)
    )
    products = (await db.execute(q)).scalars().all()
    if not products:
        return False
    buttons = [
        [InlineKeyboardButton(text=_label(p), callback_data=f"{prefix}_{p.id}")]
        for p in products
    ]
    buttons.append([InlineKeyboardButton(text="\u25b6\ufe0f Omborsiz davom", callback_data=f"{prefix}_skip")])
    buttons.append([InlineKeyboardButton(text="\u274c Bekor", callback_data="ap_cancel")])
    await cb.message.answer(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    return True



async def _show_grouped_sets(cb_or_msg, state: FSMContext, db, tur_key: str,
                              title: str, prefix: str) -> bool:
    """
    Kapalak/Yigish uchun mahsulotlarni SETLAR bo'yicha guruhlangan holda ko'rsatish.
    Masalan: Istanbul adyol Katta (98x62.5) → YON: 48 | TEPA: 50 | PAST: 47
    Max komple = eng kam qismdan hisoblanadi.
    """
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == ProductCategory.yarim_tayyor,
        WarehouseProduct.is_active == True,
        WarehouseProduct.miqdor   >  0,
        WarehouseProduct.tur      == tur_key,
    ).order_by(WarehouseProduct.razmer, WarehouseProduct.razmer_tur, WarehouseProduct.name)
    products = (await db.execute(q)).scalars().all()
    if not products:
        return False

    # Razmer bo'yicha guruhlash (aniq razmer = bitta set)
    groups: dict = {}
    for p in products:
        key = (p.razmer or "norazmer", p.razmer_tur or "")
        if key not in groups:
            groups[key] = {
                "razmer":     p.razmer,
                "razmer_tur": p.razmer_tur,
                "pieces":     [],
            }
        groups[key]["pieces"].append(p)

    # Setlarni FSM ga saqlash (ID lar ro'yxati) — callback limitdan oshmasin
    group_map = {}
    for idx, (key, gdata) in enumerate(groups.items()):
        group_map[str(idx)] = {
            "ids":        [p.id for p in gdata["pieces"]],
            "razmer":     gdata["razmer"],
            "razmer_tur": gdata["razmer_tur"],
        }
    await state.update_data(kapalak_groups=group_map)

    msg = cb_or_msg.message if isinstance(cb_or_msg, CallbackQuery) else cb_or_msg
    await msg.answer(title)

    # Har set uchun alohida xabar (yaxshi ko'rinish)
    for idx, (key, gdata) in enumerate(groups.items()):
        pieces    = gdata["pieces"]
        razmer    = gdata["razmer"] or "—"
        razmer_tur= gdata["razmer_tur"] or ""

        # Qism nomlari va miqdorlari
        piece_lines = ""
        min_count   = float("inf")
        warn_pieces = []

        for p in pieces:
            m = float(p.miqdor)
            if m < min_count:
                min_count = m
            icon = "✅" if m > 0 else "❌"
            piece_lines += f"  {icon} {p.name}: <b>{m:.0f}</b> {p.birlik}\n"

        max_komple = int(min_count)

        # Yetishmayotgan qismlarni aniqlash
        max_all  = max(float(p.miqdor) for p in pieces)
        for p in pieces:
            if float(p.miqdor) < max_all * 0.5:
                warn_pieces.append(f"{p.name}: {p.miqdor:.0f} ta")

        warn_text = ""
        if warn_pieces:
            warn_text = f"\n⚠️ Kamchilik: {', '.join(warn_pieces)}"

        card = (
            f"{'─'*30}\n"
            f"📦 <b>{razmer_tur} ({razmer})</b>\n"
            f"{piece_lines}"
            f"▶️ Maksimal: <b>{max_komple} ta komple</b>"
            f"{warn_text}"
        )
        await msg.answer(
            card,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"✅ Bu setdan kapalak qilish ({max_komple} ta max)",
                    callback_data=f"{prefix}_g{idx}",
                )]
            ]),
        )

    await msg.answer(
        "Yoki:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Omborsiz davom", callback_data=f"{prefix}_skip")],
            [InlineKeyboardButton(text="❌ Bekor",           callback_data="ap_cancel")],
        ]),
    )
    return True


async def _ensure_worker_id(state, db, tg_id):
    data = await state.get_data()
    wid  = data.get("worker_id")
    if not wid:
        user = await get_user(db, tg_id)
        if user:
            wid = user.id
            await state.update_data(worker_id=wid)
    return wid or 0


def _confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\u2705 Tasdiqlash",   callback_data="ap_confirm"),
        InlineKeyboardButton(text="\u274c Bekor qilish", callback_data="ap_cancel"),
    ]])


def _dest_kb(prefix):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4e6 XOM yarim tayyor",   callback_data=f"{prefix}_xom")],
        [InlineKeyboardButton(text="\U0001f98b KAPALAK yarim tayyor", callback_data=f"{prefix}_kapalak")],
        [InlineKeyboardButton(text="\u2705 TAYYOR mahsulot",          callback_data=f"{prefix}_tayyor")],
    ])


async def _save(cb, state, db, work_type):
    data = await state.get_data()
    entry = WorkEntry(
        worker_id    = data["worker_id"],
        work_type    = work_type,
        mahsulot_nomi= data.get("mahsulot_nomi"),
        razmer       = data.get("razmer"),
        rang         = data.get("rang"),
        tur          = data.get("tur"),
        soni         = data["soni"],
        birlik_narx  = data.get("birlik_narx", 0),
        jami_summa   = data.get("jami_summa", 0),
        status       = WorkStatus.pending,
        started_at   = data.get("started_at") or datetime.now(),
    )
    db.add(entry)
    try:
        await db.flush()
    except Exception as e:
        await db.rollback()
        logger.error("WorkEntry flush xatosi: %s", e)
        await cb.message.answer("\u274c Saqlashda xato. Qayta urinib ko\u2019ring.")
        await state.clear(); await cb.answer(); return

    warns = []
    try:
        data["work_type"] = work_type.value
        warns = await run_warehouse_ops(
            bot=cb.bot, db=db, work_type=work_type.value,
            data=data, user_id=data["worker_id"], work_entry_id=entry.id,
        )
    except Exception as e:
        logger.warning("warehouse_ops xatosi: %s", e)
        warns = [f"Ombor yangilanmadi: {e}"]

    await db.commit()
    await state.clear()
    jami      = data.get("jami_summa", 0)
    warn_text = ("\n\u26a0\ufe0f " + "\n\u26a0\ufe0f ".join(warns)) if warns else ""
    await cb.message.answer(
        f"\u2705 Ish saqlandi!\n\U0001f4b0 {jami:,.0f} soum{warn_text}\n\nNazoratchi tekshirishini kuting..."
    )
    await cb.answer()
    try:
        user   = await get_user(db, cb.from_user.id)
        nazors = await get_users_by_role(db, UserRole.nazoratchi)
        for n in nazors:
            try:
                await cb.bot.send_message(
                    n.telegram_id,
                    f"\U0001f4cb Yangi ish!\n\U0001f477 {user.full_name if user else '?'}\n"
                    f"\U0001f527 {work_type.value.replace('_',' ').title()}\n"
                    f"\U0001f4b0 {jami:,.0f} soum",
                )
            except Exception:
                pass
    except Exception:
        pass


# ═══ 11. ADYOL TIKISH ═══

@router.callback_query(F.data == "work_adyol_tikish")
async def at_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    wid = await _ensure_worker_id(state, db, cb.from_user.id)
    if not wid: await cb.answer("Foydalanuvchi topilmadi"); return
    await state.update_data(work_type=WorkType.adyol_tikish.value, worker_id=wid, started_at=datetime.now())
    has = await _show_tur_materials(
        cb, db, "adyol_tikish_uchun",
        "🧵 <b>Adyol tikish</b>\n\nQaysi qismni tikmoqchisiz?\n<i>Katta/O'rta/Kichik bilan</i>",
        "at_src",
    )
    if not has:
        await cb.message.answer("⚠️ adyol_tikish_uchun bo'limida material yo'q.")
        await state.clear()
    else:
        await state.set_state(AP.at_src)
    await cb.answer()


@router.callback_query(F.data.startswith("at_src_"), AP.at_src)
async def at_src(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data[7:])
    p   = await db.get(WarehouseProduct, pid)
    if not p: await cb.answer("Topilmadi"); return
    narx = (await get_price(db, WorkType.adyol_tikish, p.razmer_tur)) or 0
    await state.update_data(
        src_product_id=pid, mahsulot_nomi=p.name,
        razmer=p.razmer or "", rang=p.rang or "",
        tur="adyol_qoqish_uchun", birlik_narx=narx,
    )
    await cb.message.answer(
        f"📦 <b>{p.name}</b>\n"
        f"📐 {p.razmer_tur or '—'} | {p.razmer or '—'}\n"
        f"💰 Narx: {narx:,.0f} soum/dona\n\nNechta tiktingiz?",
        parse_mode="HTML",
    )
    await state.set_state(AP.at_soni)
    await cb.answer()


@router.message(AP.at_soni)
async def at_soni(m: Message, state: FSMContext):
    try:
        soni = int(m.text.strip()); assert soni > 0
    except Exception:
        await m.answer("Musbat son kiriting:"); return
    data = await state.get_data()
    narx = data.get("birlik_narx", 0); jami = narx * soni
    await state.update_data(soni=soni, jami_summa=jami)
    await m.answer(
        f"✅ Tasdiqlaysizmi?\n🧵 Adyol tikish\n📦 {data.get('mahsulot_nomi','')}\n"
        f"Soni: {soni} dona\n💰 {narx:,.0f} × {soni} = {jami:,.0f} soum",
        reply_markup=_confirm_kb(),
    )
    await state.set_state(AP.at_ok)


@router.callback_query(F.data == "ap_confirm", AP.at_ok)
async def at_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save(cb, state, db, WorkType.adyol_tikish)


# ═══ 12. PASTEL TIKISH ═══

@router.callback_query(F.data == "work_diplomat_tikish")
async def dt_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    wid = await _ensure_worker_id(state, db, cb.from_user.id)
    if not wid: await cb.answer("Foydalanuvchi topilmadi"); return
    await state.update_data(work_type=WorkType.diplomat_tikish.value, worker_id=wid, started_at=datetime.now())
    has = await _show_tur_materials(
        cb, db, "pastel_tikish_uchun",
        "💼 <b>Pastel tikish</b>\n\nQaysi qismni tikmoqchisiz?\n<i>Katta/O'rta/Kichik bilan</i>",
        "dt_src",
    )
    if not has:
        await cb.message.answer("⚠️ pastel_tikish_uchun bo'limida material yo'q.")
        await state.clear()
    else:
        await state.set_state(AP.dt_src)
    await cb.answer()


@router.callback_query(F.data.startswith("dt_src_"), AP.dt_src)
async def dt_src(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data[7:])
    p   = await db.get(WarehouseProduct, pid)
    if not p: await cb.answer("Topilmadi"); return
    narx = (await get_price(db, WorkType.diplomat_tikish, p.razmer_tur)) or 0
    await state.update_data(
        src_product_id=pid, mahsulot_nomi=p.name,
        razmer=p.razmer or "", rang=p.rang or "",
        tur="pastel_qoqish_uchun", birlik_narx=narx,
    )
    await cb.message.answer(
        f"📦 <b>{p.name}</b>\n📐 {p.razmer_tur or '—'} | {p.razmer or '—'}\n"
        f"💰 Narx: {narx:,.0f} soum/dona\n\nNechta tiktingiz?",
        parse_mode="HTML",
    )
    await state.set_state(AP.dt_soni)
    await cb.answer()


@router.message(AP.dt_soni)
async def dt_soni(m: Message, state: FSMContext):
    try:
        soni = int(m.text.strip()); assert soni > 0
    except Exception:
        await m.answer("Musbat son kiriting:"); return
    data = await state.get_data()
    narx = data.get("birlik_narx", 0); jami = narx * soni
    await state.update_data(soni=soni, jami_summa=jami)
    await m.answer(
        f"✅ Tasdiqlaysizmi?\n💼 Pastel tikish\n📦 {data.get('mahsulot_nomi','')}\n"
        f"Soni: {soni} | 💰 {jami:,.0f} soum",
        reply_markup=_confirm_kb(),
    )
    await state.set_state(AP.dt_ok)


@router.callback_query(F.data == "ap_confirm", AP.dt_ok)
async def dt_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _save(cb, state, db, WorkType.diplomat_tikish)


# ═══ 13. ADYOL QOQISH ═══

@router.callback_query(F.data == "work_adyol_qoqish")
async def aq_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    wid = await _ensure_worker_id(state, db, cb.from_user.id)
    if not wid: await cb.answer("Foydalanuvchi topilmadi"); return
    await state.update_data(work_type=WorkType.adyol_qoqish.value, worker_id=wid, started_at=datetime.now())
    await cb.message.answer(
        "🛏 <b>Adyol karobka qoqish</b>\n\nQoqish turini tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔧 XOM qoqish",      callback_data="aqtur_xom")],
            [InlineKeyboardButton(text="🦋 KAPALAK qilish",  callback_data="aqtur_kapalak")],
            [InlineKeyboardButton(text="✅ YIGISH",          callback_data="aqtur_yigish")],
            [InlineKeyboardButton(text="❌ Bekor",           callback_data="ap_cancel")],
        ]),
    )
    await state.set_state(AP.aq_tur)
    await cb.answer()


@router.callback_query(F.data == "aqtur_xom", AP.aq_tur)
async def aq_xom(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    narx = (await get_price(db, WorkType.adyol_qoqish, "xom")) or 0
    await state.update_data(tur="xom_komple", birlik_narx=narx, dest_tur="xom_komple")
    has = await _show_tur_qoqish(cb, db, "adyol_qoqish_uchun", "🔧 XOM qoqish\nQaysi tikilgan qismdan?", "aq_src")
    if not has:
        await state.update_data(src_product_id=None, mahsulot_nomi="Adyol")
        await cb.message.answer(f"⚠️ adyol_qoqish_uchun bo'sh.\nNechta qoqdingiz?")
        await state.set_state(AP.aq_soni)
    else:
        await state.set_state(AP.aq_src)
    await cb.answer()


@router.callback_query(F.data == "aqtur_kapalak", AP.aq_tur)
async def aq_kapalak(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    narx = (await get_price(db, WorkType.adyol_qoqish, "kapalak")) or 0
    await state.update_data(tur="kapalak", birlik_narx=narx, dest_tur="kapalak")
    has = await _show_grouped_sets(
        cb, state, db, "xom_komple",
        "🦋 <b>Adyol KAPALAK</b>\n\n"
        "Setlar bo'yicha 4 qism (YON×2, TEPA, PAST) ko'rsatilgan.\n"
        "⚠️ Yetishmayotgan qism ogohlantirish bilan belgilanadi:",
        "aq_grp",
    )
    if not has:
        await state.update_data(src_product_id=None, mahsulot_nomi="Adyol")
        await cb.message.answer("⚠️ xom_komple bo'sh.\nNechta kapalak qildingiz?")
        await state.set_state(AP.aq_soni)
    else:
        await state.set_state(AP.aq_src)
    await cb.answer()


@router.callback_query(F.data.startswith("aq_grp_"), AP.aq_src)
async def aq_grp_select(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    raw = cb.data[7:]
    if raw == "skip":
        await state.update_data(src_product_id=None, mahsulot_nomi="Adyol", group_ids=[])
        data = await state.get_data()
        await cb.message.answer(f"⚠️ Omborsiz davom.\nNechta kapalak qildingiz?")
        await state.set_state(AP.aq_soni)
        await cb.answer(); return

    idx   = raw[1:]
    data  = await state.get_data()
    group = data.get("kapalak_groups", {}).get(idx)
    if not group:
        await cb.answer("Set topilmadi"); return

    await state.update_data(
        group_ids=group["ids"],
        mahsulot_nomi=f"Adyol {group['razmer_tur'] or ''} ({group['razmer'] or '?'})".strip(),
        razmer=group["razmer"],
        razmer_tur=group["razmer_tur"],
        src_product_id=group["ids"][0] if group["ids"] else None,
    )
    pieces     = [p for pid in group["ids"] if (p := await db.get(WarehouseProduct, pid))]
    max_komple = int(min(float(p.miqdor) for p in pieces)) if pieces else 0
    narx       = data.get("birlik_narx", 0)
    piece_info = "\n".join(f"  • {p.name}: {p.miqdor:.0f} ta" for p in pieces)

    await cb.message.answer(
        f"✅ Set tanlandi:\n{piece_info}\n\n"
        f"▶️ Maksimal: <b>{max_komple} ta komple</b>\n"
        f"💰 Narx: {narx:,.0f} soum/komple\n\n"
        f"Nechta kapalak qilmoqchisiz? (max {max_komple})",
        parse_mode="HTML",
    )
    await state.set_state(AP.aq_soni)
    await cb.answer()


@router.callback_query(F.data == "aqtur_yigish", AP.aq_tur)
async def aq_yigish(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    narx = (await get_price(db, WorkType.adyol_qoqish, "yigish")) or 0
    await state.update_data(tur="yigish", birlik_narx=narx, dest_tur=None, is_tayyor=True)
    has = await _show_grouped_sets(
        cb, state, db, "kapalak",
        "✅ <b>Adyol YIGISH</b>\n\nKapalak setlarini tanlang:",
        "aq_grp",
    )
    if not has:
        await state.update_data(src_product_id=None, mahsulot_nomi="Adyol")
        await cb.message.answer("⚠️ kapalak bo'sh.\nNechta yigdingiz?")
        await state.set_state(AP.aq_soni)
    else:
        await state.set_state(AP.aq_src)
    await cb.answer()


@router.callback_query(F.data.startswith("aq_src_"), AP.aq_src)
async def aq_src(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    raw = cb.data[7:]
    if raw != "skip":
        try:
            p = await db.get(WarehouseProduct, int(raw))
            if p:
                await state.update_data(src_product_id=p.id, mahsulot_nomi=p.name,
                                        razmer=p.razmer or "", rang=p.rang or "")
                await cb.message.answer(f"📦 {_label(p)}")
        except (ValueError, Exception):
            await cb.answer("Xato"); return
    else:
        await state.update_data(src_product_id=None)
    data = await state.get_data()
    narx = data.get("birlik_narx", 0)
    tur  = data.get("tur", "xom_komple")
    labels = {"xom_komple": "XOM qoqish", "kapalak": "KAPALAK", "yigish": "YIGISH"}
    await cb.message.answer(f"🔧 {labels.get(tur, tur)}\n💰 {narx:,.0f} soum/dona\n\nNechta qildingiz?")
    await state.set_state(AP.aq_soni)
    await cb.answer()


@router.message(AP.aq_soni)
async def aq_soni(m: Message, state: FSMContext, db: AsyncSession):
    try:
        soni = int(m.text.strip()); assert soni > 0
    except Exception:
        await m.answer("Musbat son kiriting:"); return

    data   = await state.get_data()
    narx   = data.get("birlik_narx", 0)
    jami   = narx * soni
    tur    = data.get("tur", "xom_komple")

    # Grouped set bo'lsa — yetishmovchilik ogohlantirishi
    group_ids = data.get("group_ids", [])
    warns     = []
    if group_ids:
        for pid in group_ids:
            p = await db.get(WarehouseProduct, pid)
            if p and float(p.miqdor) < soni:
                deficit = soni - int(float(p.miqdor))
                warns.append(f"⚠️ {p.name}: {p.miqdor:.0f} ta bor, {deficit} ta yetishmaydi!")

    if warns:
        warn_text = "\n".join(warns)
        await m.answer(
            f"{warn_text}\n\n"
            f"Shunga qaramay davom etasizmi? ({soni} ta)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="▶️ Ha, davom", callback_data=f"aq_soni_ok_{soni}"),
                    InlineKeyboardButton(text="✏️ O'zgartirish", callback_data="aq_soni_edit"),
                ],
            ]),
        )
        await state.update_data(soni_pending=soni, jami_pending=jami)
        return

    await state.update_data(soni=soni, jami_summa=jami)
    if tur == "yigish":
        await m.answer(
            f"✅ Adyol YIGISH\nSoni: {soni} | 💰 {jami:,.0f} soum\n→ Tayyor mahsulotlarga",
            reply_markup=_confirm_kb(),
        )
        await state.set_state(AP.aq_ok)
    else:
        dest_q = "XOM yoki Tayyor?" if tur == "xom_komple" else "KAPALAK yoki Tayyor?"
        await m.answer(f"Soni: {soni} | {jami:,.0f} soum\n\n{dest_q}", reply_markup=_dest_kb("aqdest"))
        await state.set_state(AP.aq_dest)


@router.callback_query(F.data.startswith("aqdest_"), AP.aq_dest)
async def aq_dest(cb: CallbackQuery, state: FSMContext):
    dest = cb.data[7:]
    dmap = {"xom": "xom_komple", "kapalak": "kapalak", "tayyor": None}
    dlbl = {"xom": "📦 XOM", "kapalak": "🦋 KAPALAK", "tayyor": "✅ TAYYOR"}
    await state.update_data(dest_tur=dmap.get(dest), is_tayyor=(dest == "tayyor"))
    data = await state.get_data()
    await cb.message.answer(
        f"✅ Tasdiqlaysizmi?\n🛏 Adyol qoqish\n📦 {data.get('mahsulot_nomi','')}\n"
        f"Soni: {data['soni']} | 💰 {data.get('jami_summa',0):,.0f} soum\nQaerga: {dlbl.get(dest,dest)}",
        reply_markup=_confirm_kb(),
    )
    await state.set_state(AP.aq_ok)
    await cb.answer()


@router.callback_query(F.data == "ap_confirm", AP.aq_ok)
async def aq_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    if data.get("dest_tur"):
        await state.update_data(tur=data["dest_tur"])
    await _save(cb, state, db, WorkType.adyol_qoqish)


# ═══ 14. PASTEL QOQISH ═══

@router.callback_query(F.data == "work_pastel_qoqish")
async def pq_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    wid = await _ensure_worker_id(state, db, cb.from_user.id)
    if not wid: await cb.answer("Foydalanuvchi topilmadi"); return
    await state.update_data(work_type=WorkType.pastel_qoqish.value, worker_id=wid, started_at=datetime.now())
    await cb.message.answer(
        "💼 <b>Pastel karobka qoqish</b>\n\nQoqish turini tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔧 XOM qoqish",     callback_data="pqtur_xom")],
            [InlineKeyboardButton(text="🦋 KAPALAK qilish", callback_data="pqtur_kapalak")],
            [InlineKeyboardButton(text="✅ YIGISH",         callback_data="pqtur_yigish")],
            [InlineKeyboardButton(text="❌ Bekor",          callback_data="ap_cancel")],
        ]),
    )
    await state.set_state(AP.pq_tur)
    await cb.answer()


@router.callback_query(F.data == "pqtur_xom", AP.pq_tur)
async def pq_xom(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    narx = (await get_price(db, WorkType.pastel_qoqish, "xom")) or 0
    await state.update_data(tur="xom_komple", birlik_narx=narx, dest_tur="xom_komple")
    has = await _show_tur_qoqish(cb, db, "pastel_qoqish_uchun", "🔧 Pastel XOM\nQaysi tikilgan qismdan?", "pq_src")
    if not has:
        await state.update_data(src_product_id=None, mahsulot_nomi="Pastel")
        await cb.message.answer("⚠️ pastel_qoqish_uchun bo'sh.\nNechta qoqdingiz?")
        await state.set_state(AP.pq_soni)
    else:
        await state.set_state(AP.pq_src)
    await cb.answer()


@router.callback_query(F.data == "pqtur_kapalak", AP.pq_tur)
async def pq_kapalak(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    narx = (await get_price(db, WorkType.pastel_qoqish, "kapalak")) or 0
    await state.update_data(tur="kapalak", birlik_narx=narx, dest_tur="kapalak")
    has = await _show_grouped_sets(
        cb, state, db, "xom_komple",
        "🦋 <b>Pastel KAPALAK</b>\n\n"
        "Setlar bo'yicha qismlar ko'rsatilgan:",
        "pq_grp",
    )
    if not has:
        await state.update_data(src_product_id=None, mahsulot_nomi="Pastel")
        await cb.message.answer("⚠️ xom_komple bo'sh.\nNechta kapalak qildingiz?")
        await state.set_state(AP.pq_soni)
    else:
        await state.set_state(AP.pq_src)
    await cb.answer()


@router.callback_query(F.data.startswith("pq_grp_"), AP.pq_src)
async def pq_grp_select(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    raw = cb.data[7:]
    if raw == "skip":
        await state.update_data(src_product_id=None, mahsulot_nomi="Pastel", group_ids=[])
        data = await state.get_data()
        await cb.message.answer(f"⚠️ Omborsiz.\nNechta kapalak qildingiz?")
        await state.set_state(AP.pq_soni)
        await cb.answer(); return

    idx   = raw[1:]
    data  = await state.get_data()
    group = data.get("kapalak_groups", {}).get(idx)
    if not group:
        await cb.answer("Set topilmadi"); return

    await state.update_data(
        group_ids=group["ids"],
        mahsulot_nomi=f"Pastel {group['razmer_tur'] or ''} ({group['razmer'] or '?'})".strip(),
        razmer=group["razmer"],
        razmer_tur=group["razmer_tur"],
        src_product_id=group["ids"][0] if group["ids"] else None,
    )
    pieces = [p for pid in group["ids"] if (p := await db.get(WarehouseProduct, pid))]
    max_komple = int(min(float(p.miqdor) for p in pieces)) if pieces else 0
    narx = data.get("birlik_narx", 0)
    piece_info = "\n".join(f"  • {p.name}: {p.miqdor:.0f} ta" for p in pieces)
    await cb.message.answer(
        f"✅ Set tanlandi:\n{piece_info}\n\n"
        f"▶️ Maksimal: <b>{max_komple} ta komple</b>\n"
        f"💰 Narx: {narx:,.0f} soum/komple\n\n"
        f"Nechta kapalak qilmoqchisiz? (max {max_komple})",
        parse_mode="HTML",
    )
    await state.set_state(AP.pq_soni)
    await cb.answer()


@router.callback_query(F.data == "pqtur_yigish", AP.pq_tur)
async def pq_yigish(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    narx = (await get_price(db, WorkType.pastel_qoqish, "yigish")) or 0
    await state.update_data(tur="yigish", birlik_narx=narx, dest_tur=None, is_tayyor=True)
    # Yigish ham grouped — kapalak bo'limidan
    has = await _show_grouped_sets(
        cb, state, db, "kapalak",
        "✅ <b>Pastel YIGISH</b>\n\nKapalak setlarini tanlang:",
        "pq_grp",
    )
    if not has:
        await state.update_data(src_product_id=None, mahsulot_nomi="Pastel")
        await cb.message.answer("⚠️ kapalak bo'sh.\nNechta yigdingiz?")
        await state.set_state(AP.pq_soni)
    else:
        await state.set_state(AP.pq_src)
    await cb.answer()


@router.callback_query(F.data.startswith("pq_src_"), AP.pq_src)
async def pq_src(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    raw = cb.data[7:]
    if raw != "skip":
        try:
            p = await db.get(WarehouseProduct, int(raw))
            if p:
                await state.update_data(src_product_id=p.id, mahsulot_nomi=p.name,
                                        razmer=p.razmer or "", rang=p.rang or "")
                await cb.message.answer(f"📦 {_label(p)}")
        except (ValueError, Exception):
            await cb.answer("Xato"); return
    else:
        await state.update_data(src_product_id=None)
    data = await state.get_data()
    narx = data.get("birlik_narx", 0)
    tur  = data.get("tur", "xom_komple")
    labels = {"xom_komple": "XOM", "kapalak": "KAPALAK", "yigish": "YIGISH"}
    await cb.message.answer(f"💼 Pastel {labels.get(tur,tur)}\n💰 {narx:,.0f} soum/dona\n\nNechta qildingiz?")
    await state.set_state(AP.pq_soni)
    await cb.answer()


@router.message(AP.pq_soni)
async def pq_soni(m: Message, state: FSMContext, db: AsyncSession):
    try:
        soni = int(m.text.strip()); assert soni > 0
    except Exception:
        await m.answer("Musbat son kiriting:"); return

    data      = await state.get_data()
    narx      = data.get("birlik_narx", 0)
    jami      = narx * soni
    tur       = data.get("tur", "xom_komple")
    group_ids = data.get("group_ids", [])

    # Pastel 2 qismli (tepa + past) — yetishmovchilik tekshiruvi
    warns = []
    if group_ids:
        for pid in group_ids:
            p = await db.get(WarehouseProduct, pid)
            if p and float(p.miqdor) < soni:
                deficit = soni - int(float(p.miqdor))
                warns.append(f"⚠️ {p.name}: {p.miqdor:.0f} ta bor, {deficit} ta yetishmaydi!")

    if warns:
        warn_text = "\n".join(warns)
        await m.answer(
            f"{warn_text}\n\n"
            f"Shunga qaramay {soni} ta davom etasizmi?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="▶️ Ha, davom",     callback_data=f"pq_soni_ok_{soni}"),
                    InlineKeyboardButton(text="✏️ O'zgartirish",  callback_data="pq_soni_edit"),
                ],
            ]),
        )
        await state.update_data(soni_pending=soni, jami_pending=jami)
        return

    await state.update_data(soni=soni, jami_summa=jami)
    if tur == "yigish":
        await m.answer(
            f"✅ Pastel YIGISH\nSoni: {soni} | 💰 {jami:,.0f} soum\n→ Tayyor mahsulotlarga",
            reply_markup=_confirm_kb(),
        )
        await state.set_state(AP.pq_ok)
    else:
        dest_q = "XOM yoki Tayyor?" if tur == "xom_komple" else "KAPALAK yoki Tayyor?"
        await m.answer(f"Soni: {soni} | {jami:,.0f} soum\n\n{dest_q}", reply_markup=_dest_kb("pqdest"))
        await state.set_state(AP.pq_dest)


@router.callback_query(F.data.startswith("pqdest_"), AP.pq_dest)
async def pq_dest(cb: CallbackQuery, state: FSMContext):
    dest = cb.data[7:]
    dmap = {"xom": "xom_komple", "kapalak": "kapalak", "tayyor": None}
    dlbl = {"xom": "📦 XOM", "kapalak": "🦋 KAPALAK", "tayyor": "✅ TAYYOR"}
    await state.update_data(dest_tur=dmap.get(dest), is_tayyor=(dest == "tayyor"))
    data = await state.get_data()
    await cb.message.answer(
        f"✅ Tasdiqlaysizmi?\n💼 Pastel qoqish\n📦 {data.get('mahsulot_nomi','')}\n"
        f"Soni: {data['soni']} | 💰 {data.get('jami_summa',0):,.0f} soum\nQaerga: {dlbl.get(dest,dest)}",
        reply_markup=_confirm_kb(),
    )
    await state.set_state(AP.pq_ok)
    await cb.answer()


@router.callback_query(F.data == "ap_confirm", AP.pq_ok)
async def pq_ok(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    if data.get("dest_tur"):
        await state.update_data(tur=data["dest_tur"])
    await _save(cb, state, db, WorkType.pastel_qoqish)


# ═══ BEKOR ═══

@router.callback_query(F.data == "ap_cancel")
async def ap_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        await cb.message.answer("❌ Bekor qilindi.")
    await cb.answer()

@router.callback_query(F.data.startswith("aq_soni_ok_"))
async def aq_soni_ok_cb(cb: CallbackQuery, state: FSMContext):
    """Ogohlantirish bilan davom etishni tasdiqlash."""
    soni = int(cb.data.split("_")[-1])
    data = await state.get_data()
    jami = data.get("jami_pending", 0) or soni * data.get("birlik_narx", 0)
    await state.update_data(soni=soni, jami_summa=jami)
    tur = data.get("tur", "xom_komple")
    if tur == "yigish":
        await cb.message.answer(
            f"✅ Adyol YIGISH\nSoni: {soni} | 💰 {jami:,.0f} soum\n→ Tayyor mahsulotlarga",
            reply_markup=_confirm_kb(),
        )
        await state.set_state(AP.aq_ok)
    else:
        dest_q = "XOM yoki Tayyor?" if tur == "xom_komple" else "KAPALAK yoki Tayyor?"
        await cb.message.answer(f"Soni: {soni} | {jami:,.0f} soum\n\n{dest_q}", reply_markup=_dest_kb("aqdest"))
        await state.set_state(AP.aq_dest)
    await cb.answer()


@router.callback_query(F.data == "aq_soni_edit")
async def aq_soni_edit(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    group_ids = data.get("group_ids", [])
    if group_ids:
        from sqlalchemy import select as _sel
        # max ko'rsatish
        pass
    await cb.message.answer("Yangi miqdor kiriting:")
    await cb.answer()

@router.callback_query(F.data.startswith("pq_soni_ok_"))
async def pq_soni_ok_cb(cb: CallbackQuery, state: FSMContext):
    soni = int(cb.data.split("_")[-1])
    data = await state.get_data()
    jami = data.get("jami_pending", 0) or soni * data.get("birlik_narx", 0)
    await state.update_data(soni=soni, jami_summa=jami)
    tur  = data.get("tur", "xom_komple")
    if tur == "yigish":
        await cb.message.answer(
            f"✅ Pastel YIGISH\nSoni: {soni} | 💰 {jami:,.0f} soum\n→ Tayyor mahsulotlarga",
            reply_markup=_confirm_kb(),
        )
        await state.set_state(AP.pq_ok)
    else:
        dest_q = "XOM yoki Tayyor?" if tur == "xom_komple" else "KAPALAK yoki Tayyor?"
        await cb.message.answer(
            f"Soni: {soni} | {jami:,.0f} soum\n\n{dest_q}",
            reply_markup=_dest_kb("pqdest"),
        )
        await state.set_state(AP.pq_dest)
    await cb.answer()


@router.callback_query(F.data == "pq_soni_edit")
async def pq_soni_edit(cb: CallbackQuery):
    await cb.message.answer("Yangi miqdor kiriting:")
    await cb.answer()

