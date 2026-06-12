"""
transfer.py — Ombor transfer (zanjir) tizimi v10 TUZATILGAN
TUZATISHLAR:
  1. tr_confirm_yes: db.commit() qo'shildi (faqat flush edi)
  2. tr_confirm_yes: qalinlik attributi xavfsiz olish (hasattr tekshiruvi)
  3. tr_confirm_yes: actual miqdor 0 bo'lganda to'g'ri xabar
  4. tr_miqdor_partial: state holati to'g'ri o'rnatilmagan edi
  5. _tr_show_src_products: edit_text xatosi yaxshiroq handle qilinadi
  6. tr_src_category: tur_keyboard None bo'lganda to'g'ri o'tadi
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import UserRole, WarehouseProduct, WarehouseLog, ProductCategory
from database.queries import (
    get_user, get_product_by_id, update_product_miqdor, get_users_by_role
)
from constants import CATEGORY_TURLAR

logger = logging.getLogger(__name__)
router = Router()

ALLOWED_ROLES = (UserRole.omborchi, UserRole.nazoratchi, UserRole.admin, UserRole.superadmin)

CAT_NAMES = {
    "rulon":           "Rulonlar",
    "gofra":           "Gofralar",
    "gofra_zagatovka": "Zagatovka gofralar",
    "xromazes":        "Xromazeslar",
    "laminat_xromazes":"Laminat Xromazeslar",
    "yarim_tayyor":    "Yarim tayyor",
    "qolip":           "Qoliplar",
    "tayyor_mahsulot": "Tayyor mahsulotlar",
    "adyol_zapchast":  "Adyol zapchastlari",
    "uskuna_zapchast": "Stanok ehtiyot qismlari",
}

TUR_NAMES = {
    "tiger_uchun":            "Tiger kesish uchun",
    "gofra_kley_zagatovka":   "Gofra kley — zagatovka",
    "gofra_kley_xromazes":    "Gofra kley — xromazes",
    "gofra_uchun_rulon":      "Gofra uchun rulon",
    "list_qogoz_uchun_rulon": "List qog'oz uchun rulon",
    "zagatovka_uchun_gofra":  "Zagatovka uchun gofra",
    "stepler_uchun":       "Stepler tikish uchun",
    "salafan_uchun":       "Rulonga salafan uchun",
    "yopish_uchun":        "Yopishtirish uchun",
    "adyol_tikish_uchun":  "Adyol tikish uchun",
    "pastel_tikish_uchun": "Pastel tikish uchun",
    "adyol_qoqish_uchun":  "Adyol qoqish uchun",
    "pastel_qoqish_uchun": "Pastel qoqish uchun",
    "xom_komple":          "Xom komple",
    "kapalak":             "Kapalak",
    "oddiy":               "Oddiy",
    "oralgan":             "O'ralgan",
    "salafanli":           "Salafanli",
    "yirik":               "Yirik",
    "mayin":               "Mayin",
    "yangi":               "Yangi",
    "adyol":               "Adyol",
    "pastel":              "Pastel",
}


class TR(StatesGroup):
    src_category = State()
    src_tur      = State()
    src_product  = State()
    src_miqdor   = State()
    dst_category = State()
    dst_tur      = State()
    confirm      = State()


# ═══ KLAVIATURALAR ════════════════════════════════════════════════════════════

def _cat_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    cats = list(CAT_NAMES.items())
    for i in range(0, len(cats), 2):
        row = []
        for cv, cn in cats[i:i+2]:
            row.append(InlineKeyboardButton(
                text=cn, callback_data=f"{prefix}_{cv}"
            ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="tr_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _tur_keyboard(category: str, prefix: str):
    """CATEGORY_TURLAR constants.py dan olingan turlar"""
    turlar = CATEGORY_TURLAR.get(category)
    if not turlar:
        return None
    buttons = []
    for tk, tv in turlar.items():
        buttons.append([InlineKeyboardButton(
            text=tv, callback_data=f"{prefix}_{tk}"
        )])
    buttons.append([InlineKeyboardButton(
        text="Tur yo'q / boshqa", callback_data=f"{prefix}_none"
    )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="tr_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _product_keyboard(
    db, category: str, tur=None, prefix: str = "tr_prod"
) -> tuple[InlineKeyboardMarkup | None, list]:
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == ProductCategory(category),
        WarehouseProduct.is_active == True,
        WarehouseProduct.miqdor > 0,
    )
    if tur and tur != "none":
        q = q.where(WarehouseProduct.tur == tur)
    products = (await db.execute(q.order_by(WarehouseProduct.name))).scalars().all()
    if not products:
        return None, []

    def icon(p):
        m = float(p.miqdor)
        if m <= float(p.min_threshold):    return "🔴"
        if m <= float(p.yellow_threshold): return "🟡"
        return "🟢"

    buttons = []
    for p in products:
        lbl = f"{icon(p)} {p.name}"
        if p.razmer: lbl += f" | {p.razmer}"
        if p.rang:   lbl += f" | {p.rang}"
        if p.tur:    lbl += f" [{TUR_NAMES.get(p.tur, p.tur)}]"
        lbl += f" — {p.miqdor:.1f} {p.birlik}"
        buttons.append([InlineKeyboardButton(
            text=lbl, callback_data=f"{prefix}_{p.id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="tr_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons), products


# ═══ TRANSFER BOSHLASH ════════════════════════════════════════════════════════

@router.message(F.text == "Transfer (zanjir)")
async def tr_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await state.update_data(user_id=user.id, user_name=user.full_name)
    await message.answer(
        "🔄 Transfer (Zanjir)\n\n"
        "Mahsulotni bir bo'limdan boshqasiga ko'chirish.\n\n"
        "1-qadam: MANBA kategoriyasini tanlang:",
        reply_markup=_cat_keyboard("tr_src_cat"),
    )
    await state.set_state(TR.src_category)


@router.callback_query(F.data.startswith("tr_src_cat_"), TR.src_category)
async def tr_src_category(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    cat = cb.data[11:]
    await state.update_data(src_category=cat)
    kb = _tur_keyboard(cat, "tr_src_tur")
    if kb:
        await cb.message.edit_text(
            f"Manba: {CAT_NAMES.get(cat, cat)}\n\nQaysi bo'limdan?",
            reply_markup=kb,
        )
        await state.set_state(TR.src_tur)
    else:
        await state.update_data(src_tur=None)
        await _tr_show_src_products(cb, state, db)
    await cb.answer()


@router.callback_query(F.data.startswith("tr_src_tur_"), TR.src_tur)
async def tr_src_tur(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    tur = cb.data[11:]
    await state.update_data(src_tur=None if tur == "none" else tur)
    await _tr_show_src_products(cb, state, db)
    await cb.answer()


async def _tr_show_src_products(target, state, db):
    data = await state.get_data()
    cat  = data.get("src_category", "")
    tur  = data.get("src_tur")
    kb, products = await _product_keyboard(db, cat, tur, prefix="tr_prod")

    msg = target.message if isinstance(target, CallbackQuery) else target

    if not products:
        text = f"{CAT_NAMES.get(cat, cat)} — mahsulot topilmadi yoki hammasi tugagan."
        try:
            if isinstance(target, CallbackQuery):
                await target.message.edit_text(text)
            else:
                await msg.answer(text)
        except Exception:
            await msg.answer(text)
        await state.clear()
        return

    text = (
        f"Manba: {CAT_NAMES.get(cat, cat)}"
        f"{f' [{TUR_NAMES.get(tur, tur)}]' if tur and tur != 'none' else ''}\n\n"
        f"2-qadam: Mahsulotni tanlang ({len(products)} ta):"
    )
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=kb)
    except Exception:
        await msg.answer(text, reply_markup=kb)
    await state.set_state(TR.src_product)


@router.callback_query(F.data.startswith("tr_prod_"), TR.src_product)
async def tr_src_product(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid     = int(cb.data[8:])
    product = await get_product_by_id(db, pid)
    if not product:
        await cb.answer("Topilmadi"); return

    await state.update_data(
        src_product_id=pid,
        src_product_name=product.name,
        src_product_miqdor=float(product.miqdor),
        src_product_birlik=product.birlik,
        src_product_razmer=product.razmer,
        src_product_rang=product.rang,
        src_product_tur=product.tur,
        src_min_threshold=float(product.min_threshold),
        src_yellow_threshold=float(product.yellow_threshold),
    )

    await cb.message.edit_text(
        f"📦 {product.name}"
        f"{f' | {product.razmer}' if product.razmer else ''}"
        f"{f' | {product.rang}' if product.rang else ''}\n"
        f"Mavjud: {product.miqdor} {product.birlik}\n\n"
        f"3-qadam: Nechta ko'chirish?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"Hammasi ({product.miqdor} {product.birlik})",
                callback_data="tr_miqdor_all",
            )],
            [InlineKeyboardButton(
                text="Qisman (son kiriting)",
                callback_data="tr_miqdor_partial",
            )],
            [InlineKeyboardButton(text="❌ Bekor", callback_data="tr_cancel")],
        ]),
    )
    await state.set_state(TR.src_miqdor)
    await cb.answer()


@router.callback_query(F.data == "tr_miqdor_all", TR.src_miqdor)
async def tr_miqdor_all(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    await state.update_data(tr_miqdor=data["src_product_miqdor"])
    await _tr_ask_dst_category(cb, state)
    await cb.answer()


@router.callback_query(F.data == "tr_miqdor_partial", TR.src_miqdor)
async def tr_miqdor_partial(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await cb.message.edit_text(
        f"📦 {data['src_product_name']}\n"
        f"Mavjud: {data['src_product_miqdor']} {data['src_product_birlik']}\n\n"
        f"Nechta ko'chirasiz? (son kiriting):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="tr_cancel")]
        ]),
    )
    # TUZATILDI: state holati saqlanadi (TR.src_miqdor)
    await cb.answer()


@router.message(TR.src_miqdor)
async def tr_miqdor_input(m: Message, state: FSMContext):
    try:
        val = float(m.text.strip().replace(",", "."))
        if val <= 0: raise ValueError
    except ValueError:
        await m.answer("Musbat son kiriting:"); return

    data = await state.get_data()
    if val > data["src_product_miqdor"]:
        await m.answer(
            f"❌ Mavjud: {data['src_product_miqdor']} {data['src_product_birlik']}\n"
            f"Undan ko'p ko'chirish mumkin emas.\n\n"
            f"Qaytadan kiriting:"
        )
        return
    await state.update_data(tr_miqdor=val)
    await _tr_ask_dst_category(m, state)


async def _tr_ask_dst_category(target, state):
    msg  = target.message if isinstance(target, CallbackQuery) else target
    data = await state.get_data()
    text = (
        f"Ko'chiriladigan: {data.get('tr_miqdor', 0)} {data.get('src_product_birlik', '')}\n\n"
        f"4-qadam: MAQSAD kategoriyasini tanlang:"
    )
    try:
        if isinstance(target, CallbackQuery):
            await target.message.answer(text, reply_markup=_cat_keyboard("tr_dst_cat"))
        else:
            await msg.answer(text, reply_markup=_cat_keyboard("tr_dst_cat"))
    except Exception:
        await msg.answer(text, reply_markup=_cat_keyboard("tr_dst_cat"))
    await state.set_state(TR.dst_category)


@router.callback_query(F.data.startswith("tr_dst_cat_"), TR.dst_category)
async def tr_dst_category(cb: CallbackQuery, state: FSMContext):
    cat = cb.data[11:]
    await state.update_data(dst_category=cat)
    kb  = _tur_keyboard(cat, "tr_dst_tur")
    if kb:
        await cb.message.edit_text(
            f"Maqsad: {CAT_NAMES.get(cat, cat)}\n\n5-qadam: Qaysi bo'limga?",
            reply_markup=kb,
        )
        await state.set_state(TR.dst_tur)
    else:
        await state.update_data(dst_tur=None)
        await _tr_confirm(cb, state)
    await cb.answer()


@router.callback_query(F.data.startswith("tr_dst_tur_"), TR.dst_tur)
async def tr_dst_tur(cb: CallbackQuery, state: FSMContext):
    tur = cb.data[11:]
    await state.update_data(dst_tur=None if tur == "none" else tur)
    await _tr_confirm(cb, state)
    await cb.answer()


async def _tr_confirm(target, state):
    data      = await state.get_data()
    msg       = target.message if isinstance(target, CallbackQuery) else target
    src_cat   = data.get("src_category", "")
    src_tur   = data.get("src_tur")
    dst_cat   = data.get("dst_category", "")
    dst_tur   = data.get("dst_tur")
    miqdor    = data.get("tr_miqdor", 0)
    birlik    = data.get("src_product_birlik", "dona")
    prod_name = data.get("src_product_name", "")

    src_label = CAT_NAMES.get(src_cat, src_cat)
    dst_label = CAT_NAMES.get(dst_cat, dst_cat)
    if src_tur and src_tur != "none":
        src_label += f" [{TUR_NAMES.get(src_tur, src_tur)}]"
    if dst_tur and dst_tur != "none":
        dst_label += f" [{TUR_NAMES.get(dst_tur, dst_tur)}]"

    text = (
        f"✅ Transfer tasdiqlash\n\n"
        f"📦 {prod_name}\n"
        f"Ko'chiriladigan: {miqdor} {birlik}\n\n"
        f"📤 MANBA:  {src_label}\n"
        f"📥 MAQSAD: {dst_label}"
    )
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash",   callback_data="tr_confirm_yes"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="tr_cancel"),
        ],
    ])
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=confirm_kb)
        else:
            await msg.answer(text, reply_markup=confirm_kb)
    except Exception:
        await msg.answer(text, reply_markup=confirm_kb)
    await state.set_state(TR.confirm)


@router.callback_query(F.data == "tr_confirm_yes", TR.confirm)
async def tr_confirm_yes(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data      = await state.get_data()
    src_pid   = data.get("src_product_id")
    dst_cat   = data.get("dst_category", "")
    dst_tur   = data.get("dst_tur")
    miqdor    = float(data.get("tr_miqdor", 0))
    user_id   = data.get("user_id", 0)
    user_name = data.get("user_name", "?")

    src_product = await get_product_by_id(db, src_pid)
    if not src_product:
        await cb.message.answer("❌ Manba mahsulot topilmadi.")
        await state.clear(); await cb.answer(); return

    # TUZATILDI: actual miqdor tekshiruvi
    actual = float(src_product.miqdor)
    if actual <= 0:
        await cb.message.answer(
            f"❌ {src_product.name} omborda tugagan (0 {src_product.birlik})."
        )
        await state.clear(); await cb.answer(); return

    if miqdor > actual:
        miqdor = actual  # mavjud miqdorni chiqarish

    izoh_src = (
        f"Transfer → {CAT_NAMES.get(dst_cat, dst_cat)}"
        + (f" [{dst_tur}]" if dst_tur else "")
        + f" | {user_name}"
    )
    src_cat_name = (
        src_product.category.value
        if hasattr(src_product.category, "value")
        else str(src_product.category)
    )
    izoh_dst = (
        f"Transfer ← {CAT_NAMES.get(src_cat_name, src_cat_name)} | {user_name}"
    )

    try:
        # Manbadan chiqarish
        await update_product_miqdor(db, src_pid, -miqdor, user_id, izoh=izoh_src)

        # Maqsadda mavjud mahsulotni qidirish
        q = select(WarehouseProduct).where(
            WarehouseProduct.category == ProductCategory(dst_cat),
            WarehouseProduct.name == src_product.name,
            WarehouseProduct.is_active == True,
        )
        if src_product.razmer:
            q = q.where(WarehouseProduct.razmer == src_product.razmer)
        if src_product.rang:
            q = q.where(WarehouseProduct.rang == src_product.rang)
        if dst_tur:
            q = q.where(WarehouseProduct.tur == dst_tur)

        r           = await db.execute(q.limit(1))
        dst_product = r.scalar_one_or_none()

        if dst_product:
            await update_product_miqdor(db, dst_product.id, miqdor, user_id, izoh=izoh_dst)
        else:
            # TUZATILDI: qalinlik xavfsiz olish
            qalinlik = getattr(src_product, "qalinlik", None)
            new_p = WarehouseProduct(
                category=ProductCategory(dst_cat),
                name=src_product.name,
                razmer=src_product.razmer,
                rang=src_product.rang,
                tur=dst_tur,
                birlik=src_product.birlik,
                miqdor=miqdor,
                min_threshold=src_product.min_threshold,
                yellow_threshold=src_product.yellow_threshold,
            )
            if qalinlik is not None:
                new_p.qalinlik = qalinlik
            db.add(new_p)
            await db.flush()
            log = WarehouseLog(
                product_id=new_p.id,
                user_id=user_id,
                amal="kirim",
                miqdor=miqdor,
                oldin=0.0,
                keyin=miqdor,
                izoh=izoh_dst,
            )
            db.add(log)
            await db.flush()

        await db.commit()  # TUZATILDI: commit qo'shildi
        await state.clear()

        await cb.message.edit_text(
            f"✅ Transfer amalga oshirildi!\n\n"
            f"📦 {src_product.name}\n"
            f"Ko'chirildi: {miqdor} {src_product.birlik}\n"
            f"Bajaruvchi: {user_name}"
        )

        # Manba kam qolgan bo'lsa ogohlantirish
        await db.refresh(src_product)
        if float(src_product.miqdor) <= float(src_product.min_threshold):
            admins = await get_users_by_role(db, UserRole.admin)
            text = (
                f"⚠️ Transfer amalga oshirildi!\n"
                f"📦 {src_product.name}\n"
                f"Manba qoldig'i: {src_product.miqdor} — JUDA KAM!\n"
                f"Bajaruvchi: {user_name}"
            )
            for admin in admins:
                try:
                    await cb.bot.send_message(admin.telegram_id, text)
                except Exception:
                    pass

    except Exception as e:
        logger.error("Transfer xatosi: %s", e, exc_info=True)
        await cb.message.answer(f"❌ Xato yuz berdi: {e}")
        await state.clear()

    await cb.answer()


@router.callback_query(F.data == "tr_cancel")
async def tr_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ Transfer bekor qilindi.")
    except Exception:
        await cb.message.answer("❌ Transfer bekor qilindi.")
    await cb.answer()
