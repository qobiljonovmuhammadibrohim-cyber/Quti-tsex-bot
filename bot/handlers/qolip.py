"""
bot/handlers/qolip.py — Qoliplar bo'limi v2
500+ qolipni boshqarish: qidiruv, filterlash, pagination, holat ogohlantirishlari
"""
import logging
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    UserRole, WarehouseProduct, ProductCategory, ProductHolat,
    QOLIP_TURLAR,
)
from database.queries import (
    get_user, search_qoliplar, get_qolip_holat_summary,
    get_tamir_talab_qoliplar, update_qolip_holat, get_product_by_id,
)
from utils.razmer import normalize_razmer

logger = logging.getLogger(__name__)
router = Router()

ALLOWED = (UserRole.omborchi, UserRole.admin, UserRole.superadmin)
PER_PAGE = 12

HOLAT_ICON = {
    "yaroqli": "✅", "tamir_talab": "🔧", "yaroqsiz": "❌", None: "❓",
}
HOLAT_LABEL = {
    "yaroqli": "✅ Yaroqli", "tamir_talab": "🔧 Tamir talab", "yaroqsiz": "❌ Yaroqsiz",
}


class QolipS(StatesGroup):
    main = State()
    search_input = State()
    add_tur = State()
    add_nom = State()
    add_razmer = State()
    add_holat = State()
    add_izoh = State()
    edit_search = State()
    edit_select = State()
    edit_holat = State()
    edit_izoh = State()


def _qolip_label(p):
    icon = HOLAT_ICON.get(p.holat.value if p.holat else None, "❓")
    label = f"{icon} {p.name}"
    if p.razmer:
        label += f" [{p.razmer}]"
    return label


def _qolip_detail(p):
    icon  = HOLAT_ICON.get(p.holat.value if p.holat else None, "❓")
    tur   = QOLIP_TURLAR.get(p.tur or "", p.tur or "—")
    holat = HOLAT_LABEL.get(p.holat.value if p.holat else None, "❓ Noaniq")
    text  = (
        f"{icon} <b>{p.name}</b>\n"
        f"📐 Razmer: <code>{p.razmer or '—'}</code>\n"
        f"🏷 Tur: {tur}\n"
        f"Holat: {holat}\n"
    )
    if p.holat_izoh:
        text += f"📝 Izoh: {p.holat_izoh}\n"
    return text


def _tur_keyboard(prefix):
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"{prefix}_{key}")]
        for key, label in QOLIP_TURLAR.items()
    ]
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="qolip_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _holat_keyboard(prefix, pid=0):
    s = f"_{pid}" if pid else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yaroqli",     callback_data=f"{prefix}_yaroqli{s}")],
        [InlineKeyboardButton(text="🔧 Tamir talab", callback_data=f"{prefix}_tamir_talab{s}")],
        [InlineKeyboardButton(text="❌ Yaroqsiz",    callback_data=f"{prefix}_yaroqsiz{s}")],
        [InlineKeyboardButton(text="↩️ Bekor",       callback_data="qolip_cancel")],
    ])


async def _main_menu(target, db, uid=None):
    from sqlalchemy import select, func as sqlfunc
    summary  = await get_qolip_holat_summary(db)
    total    = sum(summary.values())
    tamir    = summary.get("tamir_talab", 0)
    yaroqsiz = summary.get("yaroqsiz", 0)
    warn = ""
    if tamir:    warn += f"\n🔧 Tamir talab: <b>{tamir}</b> ta"
    if yaroqsiz: warn += f"\n❌ Yaroqsiz:    <b>{yaroqsiz}</b> ta"

    text = (
        f"🔲 <b>Qoliplar bo'limi</b>\n"
        f"Jami: <b>{total}</b> ta qolip"
        f"{warn}\n\nTurni tanlang:"
    )

    # Har tur uchun sonini hisoblash
    tur_counts = {}
    for tur_key in QOLIP_TURLAR:
        r = await db.execute(
            select(sqlfunc.count(WarehouseProduct.id))
            .where(
                WarehouseProduct.category == ProductCategory.qolip,
                WarehouseProduct.is_active == True,
                WarehouseProduct.tur == tur_key,
            )
        )
        tur_counts[tur_key] = r.scalar() or 0

    # Tur tugmalari (har qatorda 1 ta — yaxshi o'qilsin)
    buttons = []
    if tamir or yaroqsiz:
        buttons.append([InlineKeyboardButton(
            text=f"⚠️ {tamir+yaroqsiz} ta diqqat talab",
            callback_data="qolip_tamir",
        )])

    for tur_key, tur_label in QOLIP_TURLAR.items():
        cnt = tur_counts.get(tur_key, 0)
        buttons.append([InlineKeyboardButton(
            text=f"{tur_label}  ({cnt} ta)",
            callback_data=f"qsrch_tur_{tur_key}",
        )])

    # Pastda amallar
    buttons.append([
        InlineKeyboardButton(text="🔍 Qidirish",       callback_data="qolip_search"),
        InlineKeyboardButton(text="➕ Yangi qolip",    callback_data="qolip_add"),
    ])
    buttons.append([
        InlineKeyboardButton(text="✏️ Holat o'zgartirish", callback_data="qolip_edit_start"),
        InlineKeyboardButton(text="🔧 Tamir talab",         callback_data="qolip_tamir"),
    ])

    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


async def _show_results(target, state, db, page=0):
    data     = await state.get_data()
    text_q   = data.get("srch_text")
    razmer_q = data.get("srch_razmer")
    holat_f  = data.get("srch_holat")
    tur_f    = data.get("srch_tur")

    products, total = await search_qoliplar(
        db, text_query=text_q, tur=tur_f, holat_filter=holat_f,
        razmer_query=razmer_q, limit=PER_PAGE, offset=page*PER_PAGE,
    )
    await state.update_data(srch_page=page)

    if not products and page == 0:
        msg = target.message if isinstance(target, CallbackQuery) else target
        await msg.answer(
            "🔍 Hech narsa topilmadi. Boshqa so'z bilan qidiring:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Orqaga", callback_data="qolip_main")]
            ])
        )
        return

    fi = []
    if tur_f:    fi.append(QOLIP_TURLAR.get(tur_f, tur_f))
    if holat_f:  fi.append(HOLAT_LABEL.get(holat_f, holat_f))
    if text_q:   fi.append(f'"{text_q}"')
    if razmer_q: fi.append(f"razmer: {razmer_q}")

    header = f"🔍 Natija: <b>{total}</b> ta"
    if fi: header += f" — {', '.join(fi)}"

    prod_buttons = []
    for i in range(0, len(products), 2):
        row = []
        for p in products[i:i+2]:
            row.append(InlineKeyboardButton(
                text=_qolip_label(p), callback_data=f"qolip_detail_{p.id}",
            ))
        prod_buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"qolip_page_{page-1}"))
    if (page+1)*PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="Keyingisi ▶️", callback_data=f"qolip_page_{page+1}"))
    if nav: prod_buttons.append(nav)
    prod_buttons.append([
        InlineKeyboardButton(text="🔍 Yangi qidiruv", callback_data="qolip_search"),
        InlineKeyboardButton(text="↩️ Menyu",         callback_data="qolip_main"),
    ])

    pages_info = f"  |  Sahifa {page+1}/{(total-1)//PER_PAGE+1}" if total > PER_PAGE else ""
    full_text = header + pages_info

    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(
                full_text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=prod_buttons),
            )
        else:
            await msg.answer(
                full_text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=prod_buttons),
            )
    except Exception:
        await msg.answer(
            full_text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=prod_buttons),
        )


# ─── HANDLERLAR ──────────────────────────────────────────────────────────────

@router.message(F.text == "🔲 Qoliplar")
async def qolip_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED:
        await message.answer("❌ Ruxsat yo'q"); return
    await state.update_data(user_id=user.id)
    await state.set_state(QolipS.main)
    await _show_tur_screen(message, db)


async def _show_tur_screen(target, db: AsyncSession):
    """
    Birinchi ekran: har tur uchun tugma + nechtaligi + holat belgisi.
    Bu qoliplar uchun asosiy navigatsiya.
    """
    from sqlalchemy import select, func
    from database.models import ProductCategory, ProductHolat

    # Har tur uchun: jami son, tamir_talab soni
    rows = (await db.execute(
        select(
            WarehouseProduct.tur,
            func.count(WarehouseProduct.id).label("cnt"),
        )
        .where(
            WarehouseProduct.category == ProductCategory.qolip,
            WarehouseProduct.is_active == True,
        )
        .group_by(WarehouseProduct.tur)
    )).all()

    tamir_rows = (await db.execute(
        select(
            WarehouseProduct.tur,
            func.count(WarehouseProduct.id).label("cnt"),
        )
        .where(
            WarehouseProduct.category == ProductCategory.qolip,
            WarehouseProduct.is_active == True,
            WarehouseProduct.holat == ProductHolat.tamir_talab,
        )
        .group_by(WarehouseProduct.tur)
    )).all()

    counts      = {r.tur: r.cnt for r in rows}
    tamir_counts = {r.tur: r.cnt for r in tamir_rows}

    total        = sum(counts.values())
    total_tamir  = sum(tamir_counts.values())

    buttons = []
    for key, label in QOLIP_TURLAR.items():
        cnt   = counts.get(key, 0)
        tamir = tamir_counts.get(key, 0)
        if cnt == 0:
            continue
        alert    = f" 🔧{tamir}" if tamir > 0 else ""
        btn_text = f"{label}  ({cnt} ta){alert}"
        buttons.append([InlineKeyboardButton(
            text=btn_text, callback_data=f"qsrch_tur_{key}",
        )])

    # Agar hech narsa yo'q bo'lsa — barcha turlar
    if not buttons:
        for key, label in QOLIP_TURLAR.items():
            buttons.append([InlineKeyboardButton(
                text=f"{label}  (0 ta)", callback_data=f"qsrch_tur_{key}",
            )])

    # Qo'shimcha amallar
    warn_btn = []
    if total_tamir > 0:
        warn_btn = [InlineKeyboardButton(
            text=f"🔧 Tamir talab ({total_tamir} ta)",
            callback_data="qolip_tamir",
        )]

    buttons.append([
        InlineKeyboardButton(text="🔍 Qidirish",    callback_data="qolip_search"),
        InlineKeyboardButton(text="➕ Qo'shish",   callback_data="qolip_add"),
    ])
    if warn_btn:
        buttons.append(warn_btn)
    buttons.append([
        InlineKeyboardButton(text="✏️ Holat o'zgartirish", callback_data="qolip_edit_start"),
        InlineKeyboardButton(text="⚙️ Menyu",               callback_data="qolip_main"),
    ])

    header = f"🔲 <b>Qoliplar</b>\nJami: <b>{total}</b> ta"
    if total_tamir:
        header += f"  |  🔧 <b>{total_tamir}</b> ta tamir talab"
    header += "\n\nTur tanlang:"

    msg = target.message if isinstance(target, CallbackQuery) else target
    await msg.answer(
        header, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data == "qolip_main")
async def qolip_back_main(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.set_state(QolipS.main)
    await _show_tur_screen(cb, db)
    await cb.answer()


@router.callback_query(F.data == "qolip_search")
async def qolip_search_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(QolipS.search_input)
    await cb.message.answer(
        "🔍 <b>Qolip qidirish</b>\n\n"
        "So'z kiriting:\n"
        "• <code>40x40x60</code> — aniq razmer\n"
        "• <code>40</code> — istalgan o'lchamda 40\n"
        "• <code>pizza</code> — nom bo'yicha\n"
        "• <code>tamir</code> — tamir talab qoliplar\n\n"
        "Yoki tugmalar orqali filterlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔧 Tamir talab",  callback_data="qsrch_holat_tamir_talab"),
                InlineKeyboardButton(text="❌ Yaroqsizlar",  callback_data="qsrch_holat_yaroqsiz"),
            ],
            [InlineKeyboardButton(text="📋 Tur tanlash",    callback_data="qsrch_tur_menu")],
            [InlineKeyboardButton(text="↩️ Orqaga",         callback_data="qolip_main")],
        ])
    )
    await cb.answer()


@router.message(QolipS.search_input)
async def qolip_search_query(message: Message, state: FSMContext, db: AsyncSession):
    query = message.text.strip()
    holat_f = razmer_q = text_q = None
    ql = query.lower()
    if ql in ("tamir", "tamir talab", "tamir_talab"):
        holat_f = "tamir_talab"
    elif ql == "yaroqsiz":
        holat_f = "yaroqsiz"
    elif any(c.isdigit() for c in query):
        razmer_q = query; text_q = query
    else:
        text_q = query
    await state.update_data(
        srch_text=text_q, srch_razmer=razmer_q,
        srch_holat=holat_f, srch_tur=None, srch_page=0,
    )
    await _show_results(message, state, db, page=0)


@router.callback_query(F.data.startswith("qsrch_holat_"))
async def qolip_search_holat(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    holat = cb.data.replace("qsrch_holat_", "")
    await state.update_data(srch_text=None, srch_razmer=None, srch_holat=holat, srch_tur=None, srch_page=0)
    await _show_results(cb.message, state, db, page=0)
    await cb.answer()


@router.callback_query(F.data == "qsrch_tur_menu")
async def qolip_search_tur_menu(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("Tur tanlang:", reply_markup=_tur_keyboard("qsrch_tur"))
    await cb.answer()


@router.callback_query(F.data.startswith("qsrch_tur_"))
async def qolip_search_tur(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    tur = cb.data.replace("qsrch_tur_", "")
    await state.update_data(srch_text=None, srch_razmer=None, srch_holat=None, srch_tur=tur, srch_page=0)
    await _show_results(cb.message, state, db, page=0)
    await cb.answer()


@router.callback_query(F.data.startswith("qolip_page_"))
async def qolip_page(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    page = int(cb.data.split("_")[-1])
    await _show_results(cb, state, db, page=page)
    await cb.answer()


@router.callback_query(F.data.startswith("qolip_detail_"))
async def qolip_detail(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[-1])
    p   = await get_product_by_id(db, pid)
    if not p: await cb.answer("Topilmadi"); return
    text = _qolip_detail(p)
    if p.holat and p.holat.value == "tamir_talab":
        text = "⚠️ <b>DIQQAT: TAMIR KERAK!</b>\n\n" + text
    elif p.holat and p.holat.value == "yaroqsiz":
        text = "🚫 <b>YAROQSIZ — ISHLATIB BO'LMAYDI</b>\n\n" + text
    await cb.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Holat o'zgartirish", callback_data=f"qolip_editholat_{pid}")],
            [InlineKeyboardButton(text="↩️ Natijalarga",         callback_data="qolip_back_results")],
        ])
    )
    await cb.answer()


@router.callback_query(F.data == "qolip_back_results")
async def qolip_back_results(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    await _show_results(cb, state, db, page=data.get("srch_page", 0))
    await cb.answer()


@router.callback_query(F.data == "qolip_bytur")
async def qolip_bytur(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    summary = await get_qolip_holat_summary(db)
    total   = sum(summary.values())
    buttons = []
    for key, label in QOLIP_TURLAR.items():
        _, cnt = await search_qoliplar(db, tur=key, limit=1)
        if cnt > 0:
            buttons.append([InlineKeyboardButton(
                text=f"{label}  ({cnt} ta)", callback_data=f"qsrch_tur_{key}",
            )])
    buttons.append([InlineKeyboardButton(text="↩️ Orqaga", callback_data="qolip_main")])
    await cb.message.answer(
        f"📋 <b>Turlar bo'yicha</b>\nJami: {total} ta\n\nTur tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.update_data(srch_text=None, srch_razmer=None, srch_holat=None, srch_tur=None)
    await cb.answer()


@router.callback_query(F.data == "qolip_tamir")
async def qolip_tamir(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    products = await get_tamir_talab_qoliplar(db)
    if not products:
        await cb.answer("✅ Tamir talab qolip yo'q!", show_alert=True); return
    tamir    = [p for p in products if p.holat and p.holat.value == "tamir_talab"]
    yaroqsiz = [p for p in products if p.holat and p.holat.value == "yaroqsiz"]
    text = "⚠️ <b>Diqqat talab qoliplar</b>\n\n"
    if tamir:
        text += f"🔧 <b>Tamir talab ({len(tamir)} ta):</b>\n"
        for p in tamir[:20]:
            tur = QOLIP_TURLAR.get(p.tur or "", "")
            text += f"  • {p.name}"
            if p.razmer:      text += f" [{p.razmer}]"
            if tur:           text += f" — {tur}"
            if p.holat_izoh:  text += f"\n    📝 {p.holat_izoh}"
            text += "\n"
        if len(tamir) > 20: text += f"  ... va yana {len(tamir)-20} ta\n"
        text += "\n"
    if yaroqsiz:
        text += f"❌ <b>Yaroqsiz ({len(yaroqsiz)} ta):</b>\n"
        for p in yaroqsiz[:10]:
            text += f"  • {p.name}"
            if p.razmer: text += f" [{p.razmer}]"
            text += "\n"
        if len(yaroqsiz) > 10: text += f"  ... va yana {len(yaroqsiz)-10} ta\n"
    await cb.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Holat o'zgartirish", callback_data="qolip_edit_start")],
            [InlineKeyboardButton(text="↩️ Orqaga",              callback_data="qolip_main")],
        ])
    )
    await cb.answer()


@router.callback_query(F.data == "qolip_edit_start")
async def qolip_edit_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(QolipS.edit_search)
    await cb.message.answer(
        "✏️ <b>Holat o'zgartirish</b>\n\nQolipni topish uchun nom yoki razmerini kiriting:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Bekor", callback_data="qolip_main")]
        ])
    )
    await cb.answer()


@router.message(QolipS.edit_search)
async def qolip_edit_search(message: Message, state: FSMContext, db: AsyncSession):
    query = message.text.strip()
    is_razmer = any(c.isdigit() for c in query)
    products, total = await search_qoliplar(
        db,
        text_query=None if is_razmer else query,
        razmer_query=query if is_razmer else None,
        limit=15,
    )
    if not products:
        await message.answer("Topilmadi. Boshqacha kiriting:"); return
    buttons = [
        [InlineKeyboardButton(text=_qolip_label(p), callback_data=f"qolip_editholat_{p.id}")]
        for p in products
    ]
    buttons.append([InlineKeyboardButton(text="↩️ Bekor", callback_data="qolip_main")])
    await message.answer(
        f"<b>{total}</b> ta topildi. Qaysinisini o'zgartirish?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(QolipS.edit_select)


@router.callback_query(F.data.startswith("qolip_editholat_"))
async def qolip_editholat(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[-1])
    p   = await get_product_by_id(db, pid)
    if not p: await cb.answer("Topilmadi"); return
    await state.update_data(edit_pid=pid)
    await state.set_state(QolipS.edit_holat)
    holat_now = HOLAT_LABEL.get(p.holat.value if p.holat else None, "❓ Noaniq")
    await cb.message.answer(
        f"✏️ <b>{p.name}</b>\n📐 {p.razmer or '—'}\nHozirgi: {holat_now}\n\nYangi holat:",
        parse_mode="HTML",
        reply_markup=_holat_keyboard("qedit"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("qedit_"))
async def qolip_edit_holat_chosen(cb: CallbackQuery, state: FSMContext):
    new_holat = cb.data.replace("qedit_", "")
    await state.update_data(edit_new_holat=new_holat)
    await state.set_state(QolipS.edit_izoh)
    label = HOLAT_LABEL.get(new_holat, new_holat)
    prompt = "Izoh (ixtiyoriy, «-» o'tkazish):"
    if new_holat == "tamir_talab": prompt = "⚠️ Tamir izohini yozing (nima buzilgan?):"
    elif new_holat == "yaroqsiz":  prompt = "❌ Yaroqsizlik sababini yozing:"
    await cb.message.answer(
        f"Holat: {label}\n\n{prompt}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="— O'tkazib yuborish", callback_data="qedit_izoh_skip")]
        ])
    )
    await cb.answer()


@router.message(QolipS.edit_izoh)
async def qolip_edit_izoh(message: Message, state: FSMContext, db: AsyncSession):
    izoh = None if message.text.strip() == "-" else message.text.strip()
    await _finish_edit(message, state, db, izoh)


@router.callback_query(F.data == "qedit_izoh_skip")
async def qolip_edit_izoh_skip(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _finish_edit(cb.message, state, db, None)
    await cb.answer()


async def _finish_edit(target, state, db, izoh):
    data = await state.get_data()
    p    = await update_qolip_holat(db, data["edit_pid"], data["edit_new_holat"], izoh)
    await db.commit()
    label = HOLAT_LABEL.get(data["edit_new_holat"], data["edit_new_holat"])
    warn  = ""
    if data["edit_new_holat"] == "tamir_talab": warn = "\n\n⚠️ Tamir talab sifatida belgilandi!"
    elif data["edit_new_holat"] == "yaroqsiz":  warn = "\n\n🚫 Yaroqsiz — ishlatmang!"
    await target.answer(
        f"✅ Holat yangilandi!\n\n<b>{p.name}</b>\n📐 {p.razmer or '—'}\nYangi holat: {label}{warn}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Menyu", callback_data="qolip_main")]
        ])
    )
    await state.set_state(QolipS.main)


@router.callback_query(F.data == "qolip_add")
async def qolip_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(QolipS.add_tur)
    await cb.message.answer(
        "➕ <b>Yangi qolip</b>\n\nQolip turini tanlang:",
        parse_mode="HTML",
        reply_markup=_tur_keyboard("qadd_tur"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("qadd_tur_"))
async def qolip_add_tur(cb: CallbackQuery, state: FSMContext):
    tur = cb.data.replace("qadd_tur_", "")
    await state.update_data(add_tur=tur)
    await state.set_state(QolipS.add_nom)
    await cb.message.answer(
        f"Tur: <b>{QOLIP_TURLAR.get(tur, tur)}</b>\n\nQolip nomini kiriting:\n"
        f"<i>Masalan: Pizza qolip, Tort qolip katta...</i>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(QolipS.add_nom)
async def qolip_add_nom(message: Message, state: FSMContext):
    await state.update_data(add_nom=message.text.strip())
    await message.answer(
        "📐 Razmerini kiriting:\n"
        "<i>Format: 40x40x60 yoki 90x110</i>\n«-» agar yo'q bo'lsa",
        parse_mode="HTML",
    )
    await state.set_state(QolipS.add_razmer)


@router.message(QolipS.add_razmer)
async def qolip_add_razmer(message: Message, state: FSMContext):
    raw    = message.text.strip()
    razmer = None if raw == "-" else raw
    norm   = normalize_razmer(razmer) if razmer else None
    await state.update_data(add_razmer=razmer, add_razmer_norm=norm)
    await message.answer(
        f"Razmer: <code>{razmer or '—'}</code>\n\nHolatini tanlang:",
        parse_mode="HTML",
        reply_markup=_holat_keyboard("qadd_holat"),
    )
    await state.set_state(QolipS.add_holat)


@router.callback_query(F.data.startswith("qadd_holat_"))
async def qolip_add_holat(cb: CallbackQuery, state: FSMContext):
    holat = cb.data.replace("qadd_holat_", "")
    await state.update_data(add_holat=holat)
    await state.set_state(QolipS.add_izoh)
    label  = HOLAT_LABEL.get(holat, holat)
    prompt = "Izoh (ixtiyoriy, «-» o'tkazish):"
    if holat == "tamir_talab": prompt = "⚠️ Tamir izohini yozing:"
    elif holat == "yaroqsiz":  prompt = "❌ Yaroqsizlik sababini yozing:"
    await cb.message.answer(
        f"Holat: {label}\n\n{prompt}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="— O'tkazib yuborish", callback_data="qadd_izoh_skip")]
        ])
    )
    await cb.answer()


@router.message(QolipS.add_izoh)
async def qolip_add_izoh(message: Message, state: FSMContext, db: AsyncSession):
    izoh = None if message.text.strip() == "-" else message.text.strip()
    await _finish_add(message, state, db, izoh)


@router.callback_query(F.data == "qadd_izoh_skip")
async def qolip_add_izoh_skip(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await _finish_add(cb.message, state, db, None)
    await cb.answer()


async def _finish_add(target, state, db, izoh):
    data   = await state.get_data()
    holat  = data.get("add_holat", "yaroqli")
    product = WarehouseProduct(
        category=ProductCategory.qolip,
        name=data["add_nom"],
        tur=data["add_tur"],
        razmer=data.get("add_razmer"),
        razmer_normalized=data.get("add_razmer_norm"),
        holat=ProductHolat(holat),
        holat_izoh=izoh,
        birlik="dona", miqdor=1, min_threshold=1, yellow_threshold=2,
    )
    db.add(product)
    await db.commit()
    tur_label   = QOLIP_TURLAR.get(data["add_tur"], data["add_tur"])
    holat_label = HOLAT_LABEL.get(holat, holat)
    warn = ""
    if holat == "tamir_talab": warn = "\n\n⚠️ Tamir talab sifatida qo'shildi!"
    elif holat == "yaroqsiz":  warn = "\n\n🚫 Yaroqsiz sifatida qo'shildi!"
    await target.answer(
        f"✅ Qolip qo'shildi!\n\n"
        f"🏷 <b>{data['add_nom']}</b>\n"
        f"📐 Razmer: <code>{data.get('add_razmer') or '—'}</code>\n"
        f"Tur: {tur_label}\nHolat: {holat_label}{warn}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Yana qo'shish", callback_data="qolip_add"),
                InlineKeyboardButton(text="↩️ Menyu",          callback_data="qolip_main"),
            ]
        ])
    )
    await state.set_state(QolipS.main)


@router.callback_query(F.data == "qolip_cancel")
async def qolip_cancel(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    await state.set_state(QolipS.main)
    await _main_menu(cb, db)
    await cb.answer("Bekor qilindi")
