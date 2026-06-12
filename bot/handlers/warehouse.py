"""warehouse.py — v10 TO'LIQ TUZATILGAN
TUZATISHLAR:
  1. Yarim tayyor kategoriyasi uchun tur tanlash oqimi to'liq ulandi
  2. chiqim_confirm_yes da db.commit() qo'shildi
  3. Ombor qoldig'ida yarim tayyor turlari bo'yicha filtr ko'rsatiladi
  4. Inventarizatsiya threshold birlikka moslashtirildi (dona/top uchun 5, kg uchun 10)
  5. kirim_confirm_yes da tur noto'g'ri o'chirilishi tuzatildi
  6. Yangi mahsulot kirimida log yozuvi to'g'ri saqlanadi
"""
import logging
from datetime import date, datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case as sa_case

from database.models import UserRole, WarehouseProduct, ProductCategory, WarehouseLog, YARIM_TAYYOR_TURLAR as _YT
from constants import CAT_BROWSER_CONFIG, ADMIN_OMBOR_CATS
from database.queries import (
    get_user, get_products_by_category, get_product_by_id,
    update_product_miqdor, get_all_products, get_users_by_role,
)
from bot.keyboards.main_keyboards import get_cancel_keyboard, get_confirm_keyboard

logger = logging.getLogger(__name__)
router = Router()
ALLOWED_ROLES = (UserRole.omborchi, UserRole.admin, UserRole.superadmin)

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

# Yarim tayyor turlarining to'liq ro'yxati va ko'rsatilishi
YARIM_TAYYOR_TURLAR = {
    "tiger_uchun":            "Tiger kesish uchun",
    "gofra_kley_zagatovka":   "Gofra kley — zagatovka",
    "gofra_kley_xromazes":    "Gofra kley — xromazes",
    "gofra_uchun_rulon":      "Gofra uchun rulon",
    "list_qogoz_uchun_rulon": "List qog'oz uchun rulon",
    "zagatovka_uchun_gofra":  "Zagatovka uchun gofra",
    "stepler_uchun":          "Stepler tikish uchun",
    "salafan_uchun":          "Rulonga salafan uchun",
    "yopish_uchun":           "Yopishtirish uchun",
    "adyol_tikish_uchun":     "Adyol tikish uchun",
    "pastel_tikish_uchun":    "Pastel tikish uchun",
    "adyol_qoqish_uchun":     "Adyol qoqish uchun",
    "pastel_qoqish_uchun":    "Pastel qoqish uchun",
    "xom_komple":             "Xom komple",
    "kapalak":                "Kapalak",
    "boshqa":                 "Boshqa",
}

# Kategoriyalar uchun standart birlik
CAT_DEFAULT_BIRLIK = {
    "rulon":           "rulon",
    "gofra":           "top",
    "gofra_zagatovka": "top",
    "xromazes":        "dona",
    "laminat_xromazes":"dona",
    "yarim_tayyor":    "dona",
    "qolip":           "dona",
    "tayyor_mahsulot": "dona",
    "adyol_zapchast":  "dona",
    "uskuna_zapchast": "dona",
}

BIRLIKLAR = {
    "dona":  "Dona",
    "kg":    "Kilogram",
    "top":   "Top",
    "rulon": "Rulon",
    "m":     "Metr",
    "m2":    "Metr kvadrat",
    "litr":  "Litr",
}

# Yarim tayyor bo'lmagan kategoriyalar (tur tanlash shart emas)
CATS_WITHOUT_TUR = {
    "rulon", "gofra", "gofra_zagatovka",
    "xromazes", "laminat_xromazes",
    "qolip", "adyol_zapchast", "uskuna_zapchast",
}


def _stock_icon(p) -> str:
    m = float(p.miqdor)
    if m <= float(p.min_threshold):    return "🔴"
    if m <= float(p.yellow_threshold): return "🟡"
    return "🟢"


def _inv_threshold(birlik: str) -> float:
    """Birlikka qarab inventarizatsiya ogohlantirish chegarasi"""
    if birlik in ("kg", "litr", "m", "m2"):
        return 10.0
    return 5.0


# ═══ FSM HOLATLARI ════════════════════════════════════════════════════════════

class WH(StatesGroup):
    # Kirim
    kirim_category = State()
    kirim_tur      = State()   # faqat yarim_tayyor uchun
    kirim_mahsulot = State()
    kirim_nomi     = State()
    kirim_razmer   = State()   # aniq razmer: 98×62.5
    kirim_razmer_t = State()   # o'lcham: Katta/O'rta/Kichik (xromazes uchun)
    kirim_qism     = State()   # qism: tepa/past/yon/paddo (adyol/pastel uchun)
    kirim_yonalish = State()   # yo'nalish: tiger/zagatovka (xromazes uchun)
    kirim_rang     = State()
    kirim_birlik   = State()
    kirim_miqdor   = State()
    kirim_confirm  = State()

    # Chiqim
    chiqim_category = State()
    chiqim_mahsulot = State()
    chiqim_miqdor   = State()
    chiqim_confirm  = State()

    # Inventarizatsiya
    inv_category = State()
    inv_mahsulot = State()
    inv_haqiqiy  = State()
    inv_confirm  = State()


# ═══ KLAVIATURALAR ════════════════════════════════════════════════════════════

def _category_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    cats = list(CAT_NAMES.items())
    for i in range(0, len(cats), 2):
        row = []
        for cat_val, cat_name in cats[i:i+2]:
            row.append(InlineKeyboardButton(
                text=cat_name, callback_data=f"wh_cat_{cat_val}"
            ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _tur_keyboard() -> InlineKeyboardMarkup:
    """Yarim tayyor uchun tur tanlash klaviaturasi"""
    buttons = []
    items = list(YARIM_TAYYOR_TURLAR.items())
    for i in range(0, len(items), 2):
        row = []
        for tur_val, tur_name in items[i:i+2]:
            row.append(InlineKeyboardButton(
                text=tur_name, callback_data=f"wh_tur_{tur_val}"
            ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _birlik_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    items = list(BIRLIKLAR.items())
    for i in range(0, len(items), 2):
        row = []
        for kod, nom in items[i:i+2]:
            row.append(InlineKeyboardButton(
                text=nom, callback_data=f"wh_birlik_{kod}"
            ))
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _products_keyboard(
    db, category: str, tur: str = None
) -> tuple[InlineKeyboardMarkup, list]:
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == ProductCategory(category),
        WarehouseProduct.is_active == True,
    )
    if tur and tur not in ("yangi", "boshqa", None):
        q = q.where(WarehouseProduct.tur == tur)
    products = (await db.execute(q.order_by(WarehouseProduct.name))).scalars().all()
    buttons = []
    for p in products:
        label = f"{_stock_icon(p)} {p.name}"
        if p.razmer: label += f" | {p.razmer}"
        if p.rang:   label += f" | {p.rang}"
        if p.tur:    label += f" [{YARIM_TAYYOR_TURLAR.get(p.tur, p.tur)}]"
        label += f" — {p.miqdor:.1f} {p.birlik}"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"wh_prod_{p.id}"
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ Yangi mahsulot kiritish", callback_data="wh_prod_new"
    )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons), products


# ═══ KIRIM ════════════════════════════════════════════════════════════════════

@router.message(F.text == "Kirim")
async def kirim_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await state.update_data(amal="kirim", user_id=user.id)
    await message.answer(
        "📥 Kirim\n\nQaysi kategoriyaga kirim qilasiz?",
        reply_markup=_category_keyboard(),
    )
    await state.set_state(WH.kirim_category)


@router.callback_query(F.data.startswith("wh_cat_"), WH.kirim_category)
async def kirim_category(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    cat = cb.data[7:]
    await state.update_data(category=cat, tur=None)
    cat_name = CAT_NAMES.get(cat, cat)

    # Yarim tayyor uchun tur tanlash majburiy
    if cat == "yarim_tayyor":
        await cb.message.edit_text(
            f"📥 Kirim → {cat_name}\n\nQaysi maqsad uchun? (tur tanlang):",
            reply_markup=_tur_keyboard(),
        )
        await state.set_state(WH.kirim_tur)
    # Tayyor mahsulot uchun ham tur bor (adyol/pastel)
    elif cat == "tayyor_mahsulot":
        await cb.message.edit_text(
            f"📥 Kirim → {cat_name}\n\nMahsulot turini tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛏 Adyol karobka",  callback_data="wh_tur_adyol")],
                [InlineKeyboardButton(text="💼 Pastel karobka", callback_data="wh_tur_pastel")],
                [InlineKeyboardButton(text="📦 Boshqa tayyor",  callback_data="wh_tur_boshqa_tayyor")],
                [InlineKeyboardButton(text="❌ Bekor",          callback_data="wh_cancel")],
            ]),
        )
        await state.set_state(WH.kirim_tur)
    else:
        # Har kategoriyaga mos turlarni ko'rsatish
        from constants import (
            RULON_TURLAR, GOFRA_TURLAR, ZAGATOVKA_TURLAR,
            XROMAZES_TURLAR, LAMINAT_XROMAZES_TURLAR,
            ADYOL_ZAPCHAST_TURLAR, USKUNA_ZAPCHAST_TURLAR,
        )
        from database.models import QOLIP_TURLAR
        cat_turlar = {
            "rulon":            RULON_TURLAR,
            "gofra":            GOFRA_TURLAR,
            "gofra_zagatovka":  ZAGATOVKA_TURLAR,
            "xromazes":         XROMAZES_TURLAR,
            "laminat_xromazes": LAMINAT_XROMAZES_TURLAR,
            "qolip":            QOLIP_TURLAR,
            "adyol_zapchast":   ADYOL_ZAPCHAST_TURLAR,
            "uskuna_zapchast":  USKUNA_ZAPCHAST_TURLAR,
        }
        turlar = cat_turlar.get(cat)
        if turlar:
            buttons = [
                [InlineKeyboardButton(text=label, callback_data=f"wh_tur_{key}")]
                for key, label in turlar.items()
            ]
            buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")])
            await cb.message.edit_text(
                f"📥 Kirim → {cat_name}\n\nTurini tanlang:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
            await state.set_state(WH.kirim_tur)
        else:
            kb, products = await _products_keyboard(db, cat)
            await cb.message.edit_text(
                f"📥 Kirim → {cat_name}\nMavjud mahsulotlar ({len(products)} ta):",
                reply_markup=kb,
            )
            await state.set_state(WH.kirim_mahsulot)
    await cb.answer()


@router.callback_query(F.data.startswith("wh_tur_"), WH.kirim_tur)
async def kirim_tur_selected(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    tur      = cb.data[7:]
    data     = await state.get_data()
    cat      = data.get("category", "yarim_tayyor")
    cat_name = CAT_NAMES.get(cat, cat)

    # Har kategoriya uchun tur nomini topish
    from constants import (
        RULON_TURLAR, GOFRA_TURLAR, ZAGATOVKA_TURLAR,
        XROMAZES_TURLAR, LAMINAT_XROMAZES_TURLAR,
        ADYOL_ZAPCHAST_TURLAR, USKUNA_ZAPCHAST_TURLAR,
    )
    from database.models import QOLIP_TURLAR, YARIM_TAYYOR_TURLAR as _YTT
    all_turlar = {
        **_YTT,
        **RULON_TURLAR, **GOFRA_TURLAR, **ZAGATOVKA_TURLAR,
        **XROMAZES_TURLAR, **LAMINAT_XROMAZES_TURLAR,
        **QOLIP_TURLAR, **ADYOL_ZAPCHAST_TURLAR, **USKUNA_ZAPCHAST_TURLAR,
    }
    tur_name = all_turlar.get(tur, tur)

    await state.update_data(tur=tur)

    # Gofra uchun haqiqiy razmer va rang so'rash
    if cat == "gofra":
        await cb.message.answer(
            f"📋 Gofra kirim → {tur_name}\n\n"
            f"📐 Haqiqiy razmerini kiriting (sm bilan):\n"
            f"Masalan: 125sm  yoki  105sm  yoki  150sm",
        )
        await state.set_state(WH.kirim_razmer)
        await cb.answer(); return

    kb, products = await _products_keyboard(db, cat, tur=tur)
    await cb.message.edit_text(
        f"📥 Kirim → {cat_name} → {tur_name}\n"
        f"Mavjud mahsulotlar ({len(products)} ta):",
        reply_markup=kb,
    )
    await state.set_state(WH.kirim_mahsulot)
    await cb.answer()


@router.callback_query(F.data == "wh_prod_new", WH.kirim_mahsulot)
async def kirim_new_product(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Yangi mahsulot nomini kiriting:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")]
        ]),
    )
    await state.set_state(WH.kirim_nomi)
    await cb.answer()


@router.callback_query(F.data.startswith("wh_prod_"), WH.kirim_mahsulot)
async def kirim_select_product(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data[8:])
    p   = await get_product_by_id(db, pid)
    if not p:
        await cb.answer("Topilmadi"); return
    await state.update_data(
        product_id=pid,
        product_name=p.name,
        product_birlik=p.birlik,
        product_miqdor=float(p.miqdor),
        is_new=False,
    )
    await cb.message.edit_text(
        f"📦 {p.name}"
        f"{f' | {p.razmer}' if p.razmer else ''}"
        f"{f' | {p.rang}' if p.rang else ''}\n"
        f"Joriy qoldiq: {p.miqdor} {p.birlik}\n\n"
        f"Nechta kirim qilyapsiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")]
        ]),
    )
    await state.set_state(WH.kirim_miqdor)
    await cb.answer()


@router.message(WH.kirim_nomi)
async def kirim_nomi(m: Message, state: FSMContext):
    nomi = m.text.strip()
    if len(nomi) < 2:
        await m.answer("Iltimos to'liq nom kiriting (kamida 2 harf):"); return
    await state.update_data(product_name=nomi, is_new=True, product_id=None)
    data = await state.get_data()
    cat  = data.get("category", "")
    tur  = data.get("tur", "")
    xrm_cats = ("xromazes", "laminat_xromazes")

    # Adyol/Pastel qismlari uchun qism so'rash
    from constants import ADYOL_QISM_TURLAR, PASTEL_QISM_TURLAR
    need_qism = (
        (cat in xrm_cats and tur in ("adyol", "pastel")) or
        (cat == "gofra_zagatovka" and tur in ("adyol", "pastel")) or
        (cat == "yarim_tayyor" and tur in (
            "adyol_tikish_uchun", "pastel_tikish_uchun",
            "adyol_qoqish_uchun", "pastel_qoqish_uchun",
            "xom_komple", "kapalak",
            "gofra_kley_zagatovka", "gofra_kley_xromazes", "tiger_uchun",
        ))
    )

    if need_qism:
        is_pastel = "pastel" in tur or tur in ("paddo",)
        qism_turlar = PASTEL_QISM_TURLAR if is_pastel else ADYOL_QISM_TURLAR
        buttons = [
            [InlineKeyboardButton(text=label, callback_data=f"wh_qism_{key}")]
            for key, label in qism_turlar.items()
        ]
        buttons.append([InlineKeyboardButton(text="— Qism yo'q", callback_data="wh_qism_none")])
        await m.answer(
            f"📦 Qaysi qism?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        await state.set_state(WH.kirim_qism)
    elif cat in xrm_cats:
        # Xromazeslar uchun: avval YO'NALISH so'rash
        await m.answer(
            "🔀 Bu xromazes qayerga yo'naltiriladi?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✂️ Tiger kesish uchun (bevosita)",
                    callback_data="wh_yon_tiger",
                )],
                [InlineKeyboardButton(
                    text="📦 Zagatovka → Gofra kley → Tiger",
                    callback_data="wh_yon_zagatovka",
                )],
            ]),
        )
        await state.set_state(WH.kirim_yonalish)
    else:
        await m.answer(
            "Razmer kiriting yoki tugma tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Katta",  callback_data="wh_razmer_Katta"),
                    InlineKeyboardButton(text="O'rta",  callback_data="wh_razmer_Orta"),
                    InlineKeyboardButton(text="Kichik", callback_data="wh_razmer_Kichik"),
                ],
                [InlineKeyboardButton(text="Razmer yo'q", callback_data="wh_razmer_none")],
            ]),
        )
        await state.set_state(WH.kirim_razmer)






@router.callback_query(F.data.startswith("wh_yon_"), WH.kirim_yonalish)
async def kirim_yonalish_sel(cb: CallbackQuery, state: FSMContext):
    """Xromazes yo'nalishi: tiger yoki zagatovka."""
    yon = cb.data[7:]  # "wh_yon_" = 7 harf → "tiger" yoki "zagatovka"
    await state.update_data(yonalish=yon)
    data = await state.get_data()
    cat  = data.get("category", "")
    xrm_cats = ("xromazes", "laminat_xromazes")

    if yon == "zagatovka" and cat in xrm_cats:
        # Zagatovka uchun: aniq razmer kerak (sinxronizatsiya)
        await cb.message.answer(
            "📐 Aniq razmerini kiriting (raqamlar bilan):\n"
            "Masalan: 98×62.5  yoki  60×40  yoki  120×85.5",
        )
        await state.set_state(WH.kirim_razmer)
    else:
        # Tiger uchun: faqat Katta/O'rta/Kichik (aniq razmer shart emas)
        await cb.message.answer(
            "📦 O'lcham kategoriyasini tanlang\n"
            "(Tiger kesish narxi shunga qarab belgilanadi):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔵 Katta",  callback_data="wh_rt_Katta"),
                    InlineKeyboardButton(text="🟡 O'rta",  callback_data="wh_rt_Orta"),
                    InlineKeyboardButton(text="🔴 Kichik", callback_data="wh_rt_Kichik"),
                ],
                [InlineKeyboardButton(text="— O'lcham yo'q", callback_data="wh_rt_none")],
            ]),
        )
        await state.set_state(WH.kirim_razmer_t)
    await cb.answer()

@router.callback_query(F.data.startswith("wh_qism_"), WH.kirim_qism)
async def kirim_qism_selected(cb: CallbackQuery, state: FSMContext):
    """Qism tanlash (tepa/past/yon/paddo)."""
    val = cb.data[8:]  # "wh_qism_" = 8 harf
    qism = None if val == "none" else val
    await state.update_data(qism=qism)
    data = await state.get_data()
    cat  = data.get("category", "")
    xrm_cats = ("xromazes", "laminat_xromazes")

    if cat in xrm_cats:
        await cb.message.answer(
            "📐 Aniq razmerini kiriting:\n"
            "Masalan: 98×62.5  yoki  60×40",
        )
        await state.set_state(WH.kirim_razmer)
    else:
        await cb.message.answer(
            "Razmer kiriting yoki tugma tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Katta",  callback_data="wh_razmer_Katta"),
                    InlineKeyboardButton(text="O'rta",  callback_data="wh_razmer_Orta"),
                    InlineKeyboardButton(text="Kichik", callback_data="wh_razmer_Kichik"),
                ],
                [InlineKeyboardButton(text="Razmer yo'q", callback_data="wh_razmer_none")],
            ]),
        )
        await state.set_state(WH.kirim_razmer)
    await cb.answer()

@router.callback_query(F.data.startswith("wh_razmer_"), WH.kirim_razmer)
async def kirim_razmer_cb(cb: CallbackQuery, state: FSMContext):
    val = cb.data[10:]
    await state.update_data(razmer=None if val == "none" else val)
    await cb.message.answer(
        "Rang kiriting yoki tugma tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Oq",    callback_data="wh_rang_Oq"),
                InlineKeyboardButton(text="Qora",  callback_data="wh_rang_Qora"),
                InlineKeyboardButton(text="Sariq", callback_data="wh_rang_Sariq"),
                InlineKeyboardButton(text="Ko'k",  callback_data="wh_rang_Kok"),
            ],
            [InlineKeyboardButton(text="Rang yo'q", callback_data="wh_rang_none")],
        ]),
    )
    await state.set_state(WH.kirim_rang)
    await cb.answer()


@router.message(WH.kirim_razmer)
async def kirim_razmer_msg(m: Message, state: FSMContext):
    from utils.razmer import normalize_razmer
    raw  = None if m.text.strip() == "-" else m.text.strip()
    norm = normalize_razmer(raw) if raw else None
    await state.update_data(razmer=raw, razmer_normalized=norm)

    data = await state.get_data()
    cat  = data.get("category", "")
    xrm_cats = ("xromazes", "laminat_xromazes")

    if cat in xrm_cats and raw:
        # Xromazeslar uchun: keyin o'lcham (Katta/O'rta/Kichik) so'rash
        await m.answer(
            f"✅ Aniq razmer: <b>{raw}</b>\n\n"
            f"📦 O'lcham kategoriyasini tanlang\n"
            f"(Tiger kesish narxi shunga qarab belgilanadi):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔵 Katta",  callback_data="wh_rt_Katta"),
                    InlineKeyboardButton(text="🟡 O'rta",  callback_data="wh_rt_Orta"),
                    InlineKeyboardButton(text="🔴 Kichik", callback_data="wh_rt_Kichik"),
                ],
                [InlineKeyboardButton(text="— O'lcham yo'q", callback_data="wh_rt_none")],
            ]),
        )
        await state.set_state(WH.kirim_razmer_t)
    elif cat == "gofra":
        # Gofra uchun: razmer kiritildi → Katta/O'rta/Kichik so'rash
        await m.answer(
            f"✅ Razmer: <b>{raw or '—'}</b>\n\n"
            f"📦 O'lcham kategoriyasi:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔵 Katta",  callback_data="wh_rt_Katta"),
                    InlineKeyboardButton(text="🟡 O'rta",  callback_data="wh_rt_Orta"),
                    InlineKeyboardButton(text="🔴 Kichik", callback_data="wh_rt_Kichik"),
                ],
            ]),
        )
        await state.set_state(WH.kirim_razmer_t)
    else:
        await m.answer(
            "Rang kiriting (yoki - rang yo'q):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Oq",    callback_data="wh_rang_Oq"),
                    InlineKeyboardButton(text="Qora",  callback_data="wh_rang_Qora"),
                    InlineKeyboardButton(text="Sariq", callback_data="wh_rang_Sariq"),
                ],
                [InlineKeyboardButton(text="Rang yo'q", callback_data="wh_rang_none")],
            ]),
        )
        await state.set_state(WH.kirim_rang)


@router.callback_query(F.data.startswith("wh_rt_"), WH.kirim_razmer_t)
async def kirim_razmer_tur(cb: CallbackQuery, state: FSMContext):
    """Xromazes uchun o'lcham (Katta/O'rta/Kichik) tanlash."""
    val = cb.data[6:]  # "wh_rt_" → Katta / Orta / Kichik / none
    if val == "none":
        razmer_tur = None
    elif val == "Orta":
        razmer_tur = "O'rta"
    else:
        razmer_tur = val  # Katta yoki Kichik

    await state.update_data(razmer_tur=razmer_tur)
    await cb.message.answer(
        "✅ Olcham: " + (razmer_tur or '') + "\n\n" + " + razmer_tur if razmer_tur else '— O'lcham belgilanmadi'}\n\n"
        f"Rang kiriting:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Oq",    callback_data="wh_rang_Oq"),
                InlineKeyboardButton(text="Qora",  callback_data="wh_rang_Qora"),
                InlineKeyboardButton(text="Sariq", callback_data="wh_rang_Sariq"),
                InlineKeyboardButton(text="Ko'k",  callback_data="wh_rang_Kok"),
            ],
            [InlineKeyboardButton(text="Rang yo'q", callback_data="wh_rang_none")],
        ]),
    )
    await state.set_state(WH.kirim_rang)
    await cb.answer()


@router.callback_query(F.data.startswith("wh_rang_"), WH.kirim_rang)
async def kirim_rang_cb(cb: CallbackQuery, state: FSMContext):
    val    = cb.data[8:]
    data   = await state.get_data()
    cat    = data.get("category", "")
    birlik = CAT_DEFAULT_BIRLIK.get(cat, "dona")
    await state.update_data(rang=None if val == "none" else val, product_birlik=birlik)
    await cb.message.answer(
        f"Birligini tanlang (standart: {BIRLIKLAR.get(birlik, birlik)}):",
        reply_markup=_birlik_keyboard(),
    )
    await state.set_state(WH.kirim_birlik)
    await cb.answer()


@router.message(WH.kirim_rang)
async def kirim_rang_msg(m: Message, state: FSMContext):
    data   = await state.get_data()
    cat    = data.get("category", "")
    birlik = CAT_DEFAULT_BIRLIK.get(cat, "dona")
    await state.update_data(
        rang=None if m.text.strip() == "-" else m.text.strip(),
        product_birlik=birlik,
    )
    await m.answer(
        f"Birligini tanlang (standart: {BIRLIKLAR.get(birlik, birlik)}):",
        reply_markup=_birlik_keyboard(),
    )
    await state.set_state(WH.kirim_birlik)


@router.callback_query(F.data.startswith("wh_birlik_"), WH.kirim_birlik)
async def kirim_birlik(cb: CallbackQuery, state: FSMContext):
    birlik = cb.data[10:]
    await state.update_data(product_birlik=birlik)
    await cb.message.edit_text(
        f"Nechta kirim qilyapsiz? ({BIRLIKLAR.get(birlik, birlik)} da):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")]
        ]),
    )
    await state.set_state(WH.kirim_miqdor)
    await cb.answer()


@router.message(WH.kirim_miqdor)
async def kirim_miqdor(m: Message, state: FSMContext):
    try:
        miqdor = float(m.text.strip().replace(",", "."))
        if miqdor <= 0: raise ValueError
    except ValueError:
        await m.answer("Musbat son kiriting (masalan: 10 yoki 3.5):"); return

    await state.update_data(miqdor=miqdor)
    data     = await state.get_data()
    cat_name = CAT_NAMES.get(data.get("category", ""), "")
    birlik   = data.get("product_birlik", "dona")
    is_new   = data.get("is_new", False)
    tur      = data.get("tur")
    tur_name = YARIM_TAYYOR_TURLAR.get(tur, tur) if tur else ""

    text = f"Tasdiqlaysizmi?\n\n📥 KIRIM\n{cat_name}\n"
    if tur_name:             text += f"Tur: {tur_name}\n"
    text += f"Mahsulot: {data.get('product_name', '')}\n"
    if data.get("razmer"):   text += f"Razmer: {data['razmer']}\n"
    if data.get("rang"):     text += f"Rang: {data['rang']}\n"
    text += f"Miqdor: {miqdor} {birlik}\n"
    text += "✨ Yangi mahsulot yaratiladi" if is_new else "📦 Mavjud mahsulot yangilanadi"

    await m.answer(text, reply_markup=get_confirm_keyboard())
    await state.set_state(WH.kirim_confirm)


@router.callback_query(F.data == "confirm_yes", WH.kirim_confirm)
async def kirim_confirm_yes(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data   = await state.get_data()
    is_new = data.get("is_new", False)
    miqdor = data.get("miqdor", 0)
    try:
        cat_val = data.get("category", "rulon")
        # Tur qiymatini tozalash — None yoki haqiqiy tur qiymati
        tur = data.get("tur") or None

        if is_new:
            product = WarehouseProduct(
                category=ProductCategory(cat_val),
                name=data.get("product_name", "Noma'lum"),
                razmer=data.get("razmer") or None,
                razmer_tur=data.get("razmer_tur") or None,
                qism=data.get("qism") or None,
                yonalish=data.get("yonalish") or None,
                rang=data.get("rang") or None,
                tur=tur,
                birlik=data.get("product_birlik", "dona"),
                miqdor=miqdor,
            )
            db.add(product)
            await db.flush()
            # Kirim logi
            log = WarehouseLog(
                product_id=product.id,
                user_id=data["user_id"],
                amal="kirim",
                miqdor=miqdor,
                oldin=0.0,
                keyin=float(miqdor),
                izoh="Bot orqali kirim (yangi mahsulot)",
            )
            db.add(log)
            await db.commit()
            await cb.message.edit_text(
                f"✅ Yangi mahsulot yaratildi!\n"
                f"📦 {product.name}"
                f"{f' | {product.razmer}' if product.razmer else ''}"
                f"{f' | {YARIM_TAYYOR_TURLAR.get(product.tur, product.tur)}' if product.tur else ''}\n"
                f"Qoldiq: {product.miqdor} {product.birlik}"
            )
        else:
            product = await update_product_miqdor(
                db, data["product_id"], miqdor, data["user_id"],
                izoh="Bot orqali kirim",
            )
            await db.commit()
            await cb.message.edit_text(
                f"✅ Kirim saqlandi!\n"
                f"📦 {product.name}\n"
                f"Yangi qoldiq: {product.miqdor} {product.birlik}"
            )
        await state.clear()
    except Exception as e:
        logger.error("Kirim xatosi: %s", e)
        await cb.message.edit_text(f"❌ Xato yuz berdi: {e}")
        await state.clear()
    await cb.answer()


# ═══ CHIQIM ═══════════════════════════════════════════════════════════════════

@router.message(F.text == "Chiqim")
async def chiqim_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await state.update_data(amal="chiqim", user_id=user.id)
    await message.answer(
        "📤 Chiqim\n\nQaysi kategoriyadan chiqim qilasiz?",
        reply_markup=_category_keyboard(),
    )
    await state.set_state(WH.chiqim_category)


@router.callback_query(F.data.startswith("wh_cat_"), WH.chiqim_category)
async def chiqim_category(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    cat = cb.data[7:]
    await state.update_data(category=cat)
    # Faqat qoldig'i bor mahsulotlar
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == ProductCategory(cat),
        WarehouseProduct.is_active == True,
        WarehouseProduct.miqdor > 0,
    )
    products = (await db.execute(q.order_by(WarehouseProduct.name))).scalars().all()
    if not products:
        await cb.message.edit_text(
            f"{CAT_NAMES.get(cat, cat)} da mahsulot yo'q yoki hammasi tugagan."
        )
        await state.clear(); await cb.answer(); return

    buttons = []
    for p in products:
        label = f"{_stock_icon(p)} {p.name}"
        if p.razmer: label += f" | {p.razmer}"
        if p.rang:   label += f" | {p.rang}"
        if p.tur:    label += f" [{YARIM_TAYYOR_TURLAR.get(p.tur, p.tur)}]"
        label += f" — {p.miqdor:.1f} {p.birlik}"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"wh_cprod_{p.id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")])

    await cb.message.edit_text(
        f"📤 Chiqim → {CAT_NAMES.get(cat, cat)}\n"
        f"Mahsulotni tanlang ({len(products)} ta):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(WH.chiqim_mahsulot)
    await cb.answer()


@router.callback_query(F.data.startswith("wh_cprod_"), WH.chiqim_mahsulot)
async def chiqim_select_product(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data[9:])
    p   = await get_product_by_id(db, pid)
    if not p:
        await cb.answer("Topilmadi"); return
    await state.update_data(
        product_id=pid,
        product_name=p.name,
        product_birlik=p.birlik,
        product_miqdor=float(p.miqdor),
    )
    await cb.message.edit_text(
        f"📦 {p.name}"
        f"{f' | {p.razmer}' if p.razmer else ''}"
        f"{f' | {p.rang}' if p.rang else ''}"
        f"{f' [{YARIM_TAYYOR_TURLAR.get(p.tur, p.tur)}]' if p.tur else ''}\n"
        f"Joriy qoldiq: {p.miqdor} {p.birlik}\n\n"
        f"Nechta chiqim qilyapsiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")]
        ]),
    )
    await state.set_state(WH.chiqim_miqdor)
    await cb.answer()


@router.message(WH.chiqim_miqdor)
async def chiqim_miqdor(m: Message, state: FSMContext):
    try:
        miqdor = float(m.text.strip().replace(",", "."))
        if miqdor <= 0: raise ValueError
    except ValueError:
        await m.answer("Musbat son kiriting:"); return

    data    = await state.get_data()
    current = data.get("product_miqdor", 0)
    birlik  = data.get("product_birlik", "dona")

    if miqdor > current:
        await m.answer(
            f"❌ Yetarli mahsulot yo'q!\n\n"
            f"So'ralgan:  {miqdor} {birlik}\n"
            f"Omborda:    {current} {birlik}\n\n"
            f"Iltimos, {current} dan kam miqdor kiriting:"
        )
        return

    await state.update_data(miqdor=miqdor)
    await m.answer(
        f"Tasdiqlaysizmi?\n\n"
        f"📤 CHIQIM\n"
        f"Mahsulot: {data.get('product_name', '')}\n"
        f"Miqdor: {miqdor} {birlik}\n"
        f"Qoladi: {current - miqdor:.2f} {birlik}",
        reply_markup=get_confirm_keyboard(),
    )
    await state.set_state(WH.chiqim_confirm)


@router.callback_query(F.data == "confirm_yes", WH.chiqim_confirm)
async def chiqim_confirm_yes(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data   = await state.get_data()
    miqdor = data.get("miqdor", 0)
    try:
        # Race condition himoyasi — DB dan yangi qoldiqni tekshirish
        fresh = await get_product_by_id(db, data["product_id"])
        if not fresh:
            await cb.message.edit_text("❌ Mahsulot topilmadi!")
            await state.clear(); await cb.answer(); return

        if float(fresh.miqdor) < miqdor:
            await cb.message.edit_text(
                f"❌ Yetarli mahsulot yo'q!\n"
                f"Omborda: {fresh.miqdor} {fresh.birlik}\n"
                f"So'ralgan: {miqdor}"
            )
            await state.clear(); await cb.answer(); return

        product = await update_product_miqdor(
            db, data["product_id"], -miqdor, data["user_id"],
            izoh="Bot orqali chiqim",
        )
        await db.commit()  # ← TUZATILDI: commit qo'shildi

        await cb.message.edit_text(
            f"✅ Chiqim saqlandi!\n"
            f"📦 {product.name}\n"
            f"Yangi qoldiq: {product.miqdor} {product.birlik}"
        )
        await state.clear()

        # Kam qolgan bo'lsa ogohlantirish
        if float(product.miqdor) <= float(product.min_threshold):
            managers = await get_users_by_role(db, UserRole.omborchi)
            admins   = await get_users_by_role(db, UserRole.admin)
            text = (
                f"🔴 OMBOR OGOHLANTIRISHI!\n"
                f"📦 {product.name}"
                f"{f' | {product.razmer}' if product.razmer else ''}\n"
                f"Qoldiq: {product.miqdor} {product.birlik}\n"
                f"Min chegara: {product.min_threshold}"
            )
            for u in set(managers + admins):
                try:
                    await cb.bot.send_message(u.telegram_id, text)
                except Exception:
                    pass

    except Exception as e:
        logger.error("Chiqim xatosi: %s", e)
        await cb.message.edit_text(f"❌ Xato: {e}")
        await state.clear()
    await cb.answer()


# ═══ OMBOR QOLDIG'I ═══════════════════════════════════════════════════════════

@router.message(F.text == "Ombor qoldighi")
async def ombor_qoldighi(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await message.answer(
        "📊 Ombor qoldig'i\n\nQaysi bo'limni ko'rmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Barchasi",              callback_data="oq_cat_all")],
            [
                InlineKeyboardButton(text="🧻 Rulonlar",           callback_data="oq_cat_rulon"),
                InlineKeyboardButton(text="📐 Gofralar",           callback_data="oq_cat_gofra"),
            ],
            [
                InlineKeyboardButton(text="📄 Zagatovkalar",       callback_data="oq_cat_gofra_zagatovka"),
                InlineKeyboardButton(text="🖨 Xromazeslar",        callback_data="oq_cat_xromazes"),
            ],
            [
                InlineKeyboardButton(text="✨ Laminat",            callback_data="oq_cat_laminat_xromazes"),
                InlineKeyboardButton(text="🔧 Adyol zapchast",     callback_data="oq_cat_adyol_zapchast"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Uskuna zapchast",   callback_data="oq_cat_uskuna_zapchast"),
                InlineKeyboardButton(text="🏭 Tayyor mahsulotlar", callback_data="oq_cat_tayyor_mahsulot"),
            ],
            [InlineKeyboardButton(text="⚙️ Yarim tayyor →", callback_data="oq_yarim_turlar")],
            [InlineKeyboardButton(text="🔴 Faqat kam qolganlar",    callback_data="oq_kam")],
        ]),
    )


@router.callback_query(F.data == "oq_yarim_turlar")
async def oq_yarim_turlar(cb: CallbackQuery, db: AsyncSession):
    """Yarim tayyor tur tanlash — har turda nechta mahsulot va umumiy holat"""
    from sqlalchemy import select, func
    from database.models import ProductCategory, WarehouseProduct

    # Har tur uchun son va qizil/sariqlar hisoblash
    rows = (await db.execute(
        select(
            WarehouseProduct.tur,
            func.count(WarehouseProduct.id).label("cnt"),
            func.sum(
                func.cast(WarehouseProduct.miqdor <= WarehouseProduct.min_threshold, Integer)
            ).label("red_cnt"),
        )
        .where(
            WarehouseProduct.category == ProductCategory.yarim_tayyor,
            WarehouseProduct.is_active == True,
        )
        .group_by(WarehouseProduct.tur)
    )).all()

    counts  = {r.tur: r.cnt      for r in rows}
    red_cnt = {r.tur: r.red_cnt  for r in rows}

    buttons = []
    items = list(YARIM_TAYYOR_TURLAR.items())
    for tur_val, tur_name in items:
        cnt = counts.get(tur_val, 0)
        if cnt == 0:
            continue
        red = red_cnt.get(tur_val, 0) or 0
        alert = " 🔴" if red > 0 else ""
        btn_text = f"{tur_name}  ({cnt} ta){alert}"
        buttons.append([InlineKeyboardButton(
            text=btn_text, callback_data=f"oq_tur_{tur_val}"
        )])

    # Bo'sh bo'lsayam barcha turlarni ko'rsatish
    if not buttons:
        for tur_val, tur_name in items:
            buttons.append([InlineKeyboardButton(
                text=f"{tur_name}  (0 ta)", callback_data=f"oq_tur_{tur_val}"
            )])

    buttons.append([
        InlineKeyboardButton(text="📦 Barchasi", callback_data="oq_cat_yarim_tayyor"),
        InlineKeyboardButton(text="🔙 Orqaga",   callback_data="oq_back"),
    ])

    total = sum(counts.values())
    total_red = sum((r or 0) for r in red_cnt.values())
    header = f"⚙️ Yarim tayyor mahsulotlar\nJami: {total} ta"
    if total_red:
        header += f" | 🔴 {total_red} ta kam qolgan"

    try:
        await cb.message.edit_text(
            header,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception:
        await cb.message.answer(
            header,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    await cb.answer()


@router.callback_query(F.data == "oq_back")
async def oq_back(cb: CallbackQuery, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    await cb.message.delete()
    await cb.answer()


@router.callback_query(F.data.startswith("oq_"))
async def ombor_qoldiq_filter(cb: CallbackQuery, db: AsyncSession):
    action = cb.data[3:]

    if action == "kam":
        products = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True,
                WarehouseProduct.miqdor <= WarehouseProduct.yellow_threshold,
            ).order_by(WarehouseProduct.miqdor)
        )).scalars().all()
        title = "🔴 Kam qolgan mahsulotlar"

    elif action.startswith("tur_"):
        tur      = action[4:]
        tur_name = YARIM_TAYYOR_TURLAR.get(tur, tur)
        products = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True,
                WarehouseProduct.tur == tur,
            ).order_by(WarehouseProduct.name)
        )).scalars().all()
        title = f"🔩 Yarim tayyor → {tur_name}"

    elif action == "cat_all":
        products = (await db.execute(
            select(WarehouseProduct)
            .where(WarehouseProduct.is_active == True)
            .order_by(WarehouseProduct.category, WarehouseProduct.name)
        )).scalars().all()
        title = "📦 Barcha mahsulotlar"

    elif action.startswith("cat_"):
        cat_val = action[4:]
        try:
            cat_enum = ProductCategory(cat_val)
        except ValueError:
            await cb.answer("Noto'g'ri kategoriya"); return
        products = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True,
                WarehouseProduct.category == cat_enum,
            ).order_by(WarehouseProduct.tur, WarehouseProduct.name)
        )).scalars().all()
        title = CAT_NAMES.get(cat_val, cat_val)

    elif action in ("yarim_turlar", "back"):
        return  # boshqa handler qayta ishlaydi

    else:
        await cb.answer(); return

    if not products:
        await cb.message.edit_text(f"{title}\n\nMahsulot topilmadi.")
        await cb.answer(); return

    text        = f"{title} ({len(products)} ta)\n\n"
    current_cat = None
    current_tur = None

    for p in products:
        cat_val = p.category.value if hasattr(p.category, 'value') else str(p.category)

        # Kategoriya sarlavhasi
        if cat_val != current_cat:
            current_cat = cat_val
            current_tur = None
            text += f"\n📂 {CAT_NAMES.get(cat_val, cat_val)}\n"

        # Yarim tayyor uchun tur sarlavhasi
        if cat_val == "yarim_tayyor" and p.tur != current_tur:
            current_tur = p.tur
            tur_label   = YARIM_TAYYOR_TURLAR.get(p.tur, p.tur) if p.tur else "Tur ko'rsatilmagan"
            text += f"  └─ {tur_label}\n"

        icon = _stock_icon(p)
        line = f"    {icon} {p.name}"
        if p.razmer: line += f" ({p.razmer})"
        if p.rang:   line += f" — {p.rang}"
        line += f": {p.miqdor} {p.birlik}"
        if float(p.miqdor) <= float(p.min_threshold):
            line += " ⚠️"
        text += line + "\n"

    text += "\n🔴 Juda kam  🟡 Cheklangan  🟢 Yetarli"

    # Uzun matnni bo'lib yuborish
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for idx, chunk in enumerate(chunks):
        if idx == 0:
            try:
                await cb.message.edit_text(chunk)
            except Exception:
                await cb.message.answer(chunk)
        else:
            await cb.message.answer(chunk)
    await cb.answer()


# ═══ OMBOR HISOBOTI ═══════════════════════════════════════════════════════════

@router.message(F.text == "Ombor hisoboti")
async def ombor_hisoboti(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return

    today = date.today()
    r = await db.execute(
        select(
            WarehouseLog.amal,
            func.count(WarehouseLog.id),
            func.coalesce(func.sum(WarehouseLog.miqdor), 0),
        )
        .where(func.date(WarehouseLog.created_at) == today)
        .group_by(WarehouseLog.amal)
    )
    stats  = {row[0]: (row[1], float(row[2])) for row in r.all()}
    kirim  = stats.get("kirim",  (0, 0.0))
    chiqim = stats.get("chiqim", (0, 0.0))

    r2 = await db.execute(
        select(WarehouseProduct).where(
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor <= WarehouseProduct.yellow_threshold,
        ).order_by(WarehouseProduct.miqdor)
    )
    kam = r2.scalars().all()

    text = (
        f"📊 Ombor hisoboti — {today.strftime('%d.%m.%Y')}\n\n"
        f"📥 Bugungi kirim:  {kirim[0]} ta amal, {kirim[1]:,.1f} birlik\n"
        f"📤 Bugungi chiqim: {chiqim[0]} ta amal, {chiqim[1]:,.1f} birlik\n"
    )
    if kam:
        text += f"\n⚠️ Diqqat talab etadi ({len(kam)} ta):\n"
        for p in kam[:15]:
            icon = _stock_icon(p)
            text += f"  {icon} {p.name}"
            if p.razmer: text += f" ({p.razmer})"
            text += f": {p.miqdor} {p.birlik}\n"
        if len(kam) > 15:
            text += f"  ... va yana {len(kam) - 15} ta\n"
    else:
        text += "\n✅ Barcha mahsulotlar yetarli."

    await message.answer(text)


# ═══ INVENTARIZATSIYA ═════════════════════════════════════════════════════════

@router.message(F.text == "Inventarizatsiya")
async def inv_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await state.update_data(user_id=user.id)
    await message.answer(
        "🔍 Inventarizatsiya\n\nQaysi kategoriyadan?",
        reply_markup=_category_keyboard(),
    )
    await state.set_state(WH.inv_category)


@router.callback_query(F.data.startswith("wh_cat_"), WH.inv_category)
async def inv_category(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    cat = cb.data[7:]
    await state.update_data(category=cat)
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == ProductCategory(cat),
        WarehouseProduct.is_active == True,
    )
    products = (await db.execute(q.order_by(WarehouseProduct.tur, WarehouseProduct.name))).scalars().all()
    if not products:
        await cb.message.edit_text("Mahsulot topilmadi.")
        await state.clear(); await cb.answer(); return

    buttons = []
    for p in products:
        label = f"{_stock_icon(p)} {p.name}"
        if p.razmer: label += f" | {p.razmer}"
        if p.tur:    label += f" [{YARIM_TAYYOR_TURLAR.get(p.tur, p.tur)}]"
        label += f" — botda: {p.miqdor} {p.birlik}"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"wh_iprod_{p.id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")])

    await cb.message.edit_text(
        "Tekshiriladigan mahsulotni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(WH.inv_mahsulot)
    await cb.answer()


@router.callback_query(F.data.startswith("wh_iprod_"), WH.inv_mahsulot)
async def inv_product_select(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid     = int(cb.data[9:])
    product = await get_product_by_id(db, pid)
    if not product:
        await cb.answer("Topilmadi"); return
    await state.update_data(
        inv_product_id=pid,
        inv_bot_miqdor=float(product.miqdor),
        inv_birlik=product.birlik,
    )
    await cb.message.edit_text(
        f"🔍 {product.name}"
        f"{f' | {product.razmer}' if product.razmer else ''}\n"
        f"Birlik: {product.birlik}\n"
        f"Bot hisobidagi qoldiq: {product.miqdor} {product.birlik}\n\n"
        f"Haqiqiy (sanab chiqqan) miqdorni kiriting:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="wh_cancel")]
        ]),
    )
    await state.set_state(WH.inv_haqiqiy)
    await cb.answer()


@router.message(WH.inv_haqiqiy)
async def inv_haqiqiy(m: Message, state: FSMContext, db: AsyncSession):
    try:
        haqiqiy = float(m.text.strip().replace(",", "."))
        if haqiqiy < 0: raise ValueError
    except ValueError:
        await m.answer("Musbat son yoki 0 kiriting:"); return

    data    = await state.get_data()
    bot_miq = data.get("inv_bot_miqdor", 0)
    birlik  = data.get("inv_birlik", "dona")
    pid     = data.get("inv_product_id")
    product = await get_product_by_id(db, pid)
    farq    = haqiqiy - bot_miq

    if farq > 0:
        farq_text = f"+{farq:.2f} (oshiqcha)"
    elif farq < 0:
        farq_text = f"{farq:.2f} (kamomad)"
    else:
        farq_text = "0 (mos)"

    await state.update_data(inv_haqiqiy=haqiqiy)
    await m.answer(
        f"🔍 Inventarizatsiya natijasi\n\n"
        f"📦 {product.name if product else '?'}\n"
        f"Bot hisobida: {bot_miq} {birlik}\n"
        f"Haqiqiy:      {haqiqiy} {birlik}\n"
        f"Farq:         {farq_text}\n\n"
        f"{'✅ Mos keladi, o\'zgartirish shart emas.' if farq == 0 else '⚠️ Tasdiqlasangiz, bot qoldig\'i yangilanadi.'}\n\n"
        f"Tasdiqlaysizmi?",
        reply_markup=get_confirm_keyboard(),
    )
    await state.set_state(WH.inv_confirm)


@router.callback_query(F.data == "confirm_yes", WH.inv_confirm)
async def inv_confirm_yes(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data    = await state.get_data()
    pid     = data.get("inv_product_id")
    bot_miq = data.get("inv_bot_miqdor", 0)
    haqiqiy = data.get("inv_haqiqiy", 0)
    birlik  = data.get("inv_birlik", "dona")
    farq    = haqiqiy - bot_miq

    if farq == 0:
        await cb.message.edit_text("✅ Miqdor mos keladi, hech narsa o'zgarmadi.")
        await state.clear(); await cb.answer(); return

    try:
        product = await update_product_miqdor(
            db, pid, farq, data["user_id"],
            izoh=f"Inventarizatsiya: bot={bot_miq} → haqiqiy={haqiqiy} (farq={farq:+.2f})",
        )
        await db.commit()
        await cb.message.edit_text(
            f"✅ Inventarizatsiya saqlandi!\n"
            f"📦 {product.name}\n"
            f"Farq: {farq:+.2f} {birlik}\n"
            f"Yangi qoldiq: {product.miqdor} {product.birlik}"
        )

        # Birlikka mos threshold bo'yicha adminga xabar
        threshold = _inv_threshold(birlik)
        if abs(farq) > threshold:
            admins = await get_users_by_role(db, UserRole.admin)
            text = (
                f"📋 Inventarizatsiya amalga oshirildi!\n"
                f"📦 {product.name}\n"
                f"Bot: {bot_miq} → Haqiqiy: {haqiqiy} {birlik}\n"
                f"Farq: {farq:+.2f} {birlik}"
            )
            for admin in admins:
                try:
                    await cb.bot.send_message(admin.telegram_id, text)
                except Exception:
                    pass

    except Exception as e:
        logger.error("Inventarizatsiya xatosi: %s", e)
        await cb.message.edit_text(f"❌ Xato: {e}")
    await state.clear()
    await cb.answer()


# ═══ BUYURTMA RO'YXATI ════════════════════════════════════════════════════════

@router.message(F.text == "Buyurtma royxati")
async def buyurtma_royxati(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return

    r = await db.execute(
        select(WarehouseProduct).where(
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor <= WarehouseProduct.yellow_threshold,
        ).order_by(WarehouseProduct.miqdor)
    )
    products = r.scalars().all()

    if not products:
        await message.answer("✅ Ombor holati yaxshi! Hamma mahsulotlar yetarli.")
        return

    text   = "📋 Buyurtma ro'yxati\n(Kam qolgan va tugagan mahsulotlar)\n\n"
    kritik = []
    ogoh   = []

    for p in products:
        cat_name = CAT_NAMES.get(
            p.category.value if hasattr(p.category, 'value') else str(p.category), ''
        )
        tur_name = f" [{YARIM_TAYYOR_TURLAR.get(p.tur, p.tur)}]" if p.tur else ""
        line = f"• {p.name}"
        if p.razmer: line += f" ({p.razmer})"
        line += tur_name
        line += f"\n  {cat_name}: {p.miqdor} {p.birlik} (min: {p.min_threshold})\n"

        if float(p.miqdor) <= float(p.min_threshold):
            kritik.append(line)
        else:
            ogoh.append(line)

    if kritik:
        text += f"🔴 TUGAY DEYAPTI ({len(kritik)} ta):\n" + "\n".join(kritik) + "\n"
    if ogoh:
        text += f"\n🟡 OGOHLANTIRISH ({len(ogoh)} ta):\n" + "\n".join(ogoh)

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📨 Adminga yuborish", callback_data="send_order_to_admin")]
        ]),
    )


@router.callback_query(F.data == "send_order_to_admin")
async def send_order_to_admin(cb: CallbackQuery, db: AsyncSession):
    admins = await get_users_by_role(db, UserRole.admin)
    supers = await get_users_by_role(db, UserRole.superadmin)
    targets = list({u.id: u for u in admins + supers}.values())
    if not targets:
        await cb.answer("Admin topilmadi"); return

    r = await db.execute(
        select(WarehouseProduct).where(
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor <= WarehouseProduct.yellow_threshold,
        ).order_by(WarehouseProduct.miqdor)
    )
    products = r.scalars().all()

    text = f"📋 BUYURTMA KERAK!\n{datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    for p in products:
        icon = "🔴" if float(p.miqdor) <= float(p.min_threshold) else "🟡"
        text += f"{icon} {p.name}"
        if p.razmer: text += f" ({p.razmer})"
        if p.tur:    text += f" [{YARIM_TAYYOR_TURLAR.get(p.tur, p.tur)}]"
        text += f": {p.miqdor} {p.birlik}\n"

    sent = 0
    for admin in targets:
        try:
            await cb.bot.send_message(admin.telegram_id, text)
            sent += 1
        except Exception as e:
            logger.warning("Admin ga yuborib bo'lmadi: %s", e)
    await cb.answer(f"✅ {sent} ta adminga yuborildi!")


# ═══ MAHSULOT TARIXI ══════════════════════════════════════════════════════════

@router.message(F.text == "Mahsulot tarixi")
async def mahsulot_tarixi(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await message.answer(
        "📜 Mahsulot tarixi uchun veb-paneldan foydalaning:\n"
        "/web/warehouse/logs"
    )


# ═══ MAHSULOT TAHRIRLASH ══════════════════════════════════════════════════════

@router.message(F.text == "Mahsulot tahrirlash")
async def mahsulot_tahrirlash(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yo'q."); return
    await message.answer(
        "✏️ Mahsulot tahrirlash uchun veb-paneldan foydalaning:\n"
        "/web/warehouse"
    )


# ═══ BEKOR ════════════════════════════════════════════════════════════════════


# ═══ YARIM TAYYOR BO'LIM BROWSER ════════════════════════════════════════════
# "🧩 Yarim tayyor" tugmasi → tur tugmalari → mahsulotlar ro'yxati

YT_PER_PAGE = 10

# Tur ikonlari
YT_ICONS = {
    "tiger_uchun":            "✂️",
    "gofra_kley_zagatovka":   "🔨",
    "gofra_kley_xromazes":    "🖨️",
    "gofra_uchun_rulon":      "🌀",
    "list_qogoz_uchun_rulon": "📄",
    "zagatovka_uchun_gofra":  "✂️",
    "stepler_uchun":       "📌",
    "salafan_uchun":       "🎁",
    "yopish_uchun":        "🔗",
    "adyol_tikish_uchun":  "🧵",
    "pastel_tikish_uchun": "💼",
    "adyol_qoqish_uchun":  "📫",
    "pastel_qoqish_uchun": "📬",
    "xom_komple":          "📦",
    "kapalak":             "🦋",
    "boshqa":              "📝",
}


@router.message(F.text == "🧩 Yarim tayyor")
async def yt_start(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (
        UserRole.omborchi, UserRole.admin, UserRole.superadmin
    ):
        await message.answer("❌ Ruxsat yo'q"); return

    # Har tur uchun qoldiq sonini hisoblash
    from sqlalchemy import select, func
    counts = {}
    for tur_key in YARIM_TAYYOR_TURLAR:
        r = await db.execute(
            select(func.count(WarehouseProduct.id), func.coalesce(func.sum(WarehouseProduct.miqdor), 0))
            .where(
                WarehouseProduct.category == ProductCategory.yarim_tayyor,
                WarehouseProduct.is_active == True,
                WarehouseProduct.tur == tur_key,
            )
        )
        row = r.one()
        counts[tur_key] = {"items": row[0], "total": int(row[1])}

    # Tur tugmalari
    buttons = []
    for tur_key, tur_name in YARIM_TAYYOR_TURLAR.items():
        cnt  = counts.get(tur_key, {})
        icon = YT_ICONS.get(tur_key, "📦")
        n    = cnt.get("items", 0)
        qty  = cnt.get("total", 0)
        # Agar bo'sh bo'lsa ham ko'rsatish (qo'shish uchun)
        label = f"{icon} {tur_name}  ({n} xil, {qty} dona)"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"yt_tur_{tur_key}_0",
        )])

    await message.answer(
        "🧩 <b>Yarim tayyor mahsulotlar</b>\n\nBo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("yt_tur_"))
async def yt_tur(cb: CallbackQuery, db: AsyncSession):
    # yt_tur_{key}_{page}
    parts = cb.data.split("_")
    # key qismida _ bo'lishi mumkin, shuning uchun oxirgi element page
    page    = int(parts[-1])
    tur_key = "_".join(parts[2:-1])

    from sqlalchemy import select
    q = (
        select(WarehouseProduct)
        .where(
            WarehouseProduct.category == ProductCategory.yarim_tayyor,
            WarehouseProduct.is_active == True,
            WarehouseProduct.tur == tur_key,
        )
        .order_by(WarehouseProduct.name, WarehouseProduct.razmer)
    )
    from sqlalchemy import func
    total = (await db.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar() or 0

    products = (await db.execute(
        q.limit(YT_PER_PAGE).offset(page * YT_PER_PAGE)
    )).scalars().all()

    tur_name = YARIM_TAYYOR_TURLAR.get(tur_key, tur_key)
    icon     = YT_ICONS.get(tur_key, "📦")

    if not products and page == 0:
        await cb.message.answer(
            f"{icon} <b>{tur_name}</b>\n\n📭 Hozircha mahsulot yo'q.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Orqaga", callback_data="yt_back")]
            ]),
        )
        await cb.answer(); return

    # Mahsulotlar ro'yxati
    lines = []
    for p in products:
        # Holat belgisi
        m = float(p.miqdor)
        if m <= float(p.min_threshold):
            status = "🔴"
        elif m <= float(p.yellow_threshold):
            status = "🟡"
        else:
            status = "🟢"

        line = f"{status} <b>{p.name}</b>"
        if p.razmer: line += f" <code>[{p.razmer}]</code>"
        if p.rang:   line += f" — {p.rang}"
        line += f"\n   📦 {p.miqdor:.0f} {p.birlik}"
        lines.append(line)

    pages_total = (total - 1) // YT_PER_PAGE + 1
    header = (
        f"{icon} <b>{tur_name}</b>\n"
        f"Jami: <b>{total}</b> xil mahsulot"
    )
    if pages_total > 1:
        header += f"  |  Sahifa {page+1}/{pages_total}"

    text = header + "\n\n" + "\n\n".join(lines)

    # Navigatsiya
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️ Oldingi", callback_data=f"yt_tur_{tur_key}_{page-1}",
        ))
    if (page + 1) * YT_PER_PAGE < total:
        nav.append(InlineKeyboardButton(
            text="Keyingisi ▶️", callback_data=f"yt_tur_{tur_key}_{page+1}",
        ))

    inline = []
    if nav: inline.append(nav)
    inline.append([InlineKeyboardButton(text="↩️ Turlar ro'yxati", callback_data="yt_back")])

    try:
        await cb.message.edit_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline),
        )
    except Exception:
        await cb.message.answer(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline),
        )
    await cb.answer()


@router.callback_query(F.data == "yt_back")
async def yt_back(cb: CallbackQuery, db: AsyncSession):
    """Turlar ro'yxatiga qaytish."""
    from sqlalchemy import select, func

    counts = {}
    for tur_key in YARIM_TAYYOR_TURLAR:
        r = await db.execute(
            select(func.count(WarehouseProduct.id), func.coalesce(func.sum(WarehouseProduct.miqdor), 0))
            .where(
                WarehouseProduct.category == ProductCategory.yarim_tayyor,
                WarehouseProduct.is_active == True,
                WarehouseProduct.tur == tur_key,
            )
        )
        row = r.one()
        counts[tur_key] = {"items": row[0], "total": int(row[1])}

    buttons = []
    for tur_key, tur_name in YARIM_TAYYOR_TURLAR.items():
        cnt  = counts.get(tur_key, {})
        icon = YT_ICONS.get(tur_key, "📦")
        n    = cnt.get("items", 0)
        qty  = cnt.get("total", 0)
        label = f"{icon} {tur_name}  ({n} xil, {qty} dona)"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"yt_tur_{tur_key}_0",
        )])

    try:
        await cb.message.edit_text(
            "🧩 <b>Yarim tayyor mahsulotlar</b>\n\nBo'limni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception:
        await cb.message.answer(
            "🧩 <b>Yarim tayyor mahsulotlar</b>\n\nBo'limni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    await cb.answer()



# ═══ UMUMIY KATEGORIYA BROWSER ════════════════════════════════════════════════
# gofra_zagatovka, xromazes, laminat_xromazes, adyol_zapchast, uskuna_zapchast
# Bir xil kod — constants.py dagi CAT_BROWSER_CONFIG orqali boshqariladi

CAT_BROWSE_PER_PAGE = 10


async def _cat_browser_menu(target, db: AsyncSession, cat_key: str):
    """Kategoriya asosiy menyusi — tur tugmalari bilan."""
    from sqlalchemy import select, func as sqlfunc
    cfg = CAT_BROWSER_CONFIG[cat_key]
    cat_enum = ProductCategory(cat_key)

    # Har tur uchun sonini hisoblash
    counts = {}
    for tur_key in cfg["turlar"]:
        r = await db.execute(
            select(sqlfunc.count(WarehouseProduct.id),
                   sqlfunc.coalesce(sqlfunc.sum(WarehouseProduct.miqdor), 0))
            .where(
                WarehouseProduct.category == cat_enum,
                WarehouseProduct.is_active == True,
                WarehouseProduct.tur == tur_key,
            )
        )
        row = r.one()
        counts[tur_key] = {"items": row[0], "total": float(row[1])}

    # Tur belgilanmagan mahsulotlar (tur=None)
    r_none = await db.execute(
        select(sqlfunc.count(WarehouseProduct.id),
               sqlfunc.coalesce(sqlfunc.sum(WarehouseProduct.miqdor), 0))
        .where(
            WarehouseProduct.category == cat_enum,
            WarehouseProduct.is_active == True,
            WarehouseProduct.tur == None,
        )
    )
    row_none = r_none.one()
    counts["__none__"] = {"items": row_none[0], "total": float(row_none[1])}

    total_items = sum(v["items"] for v in counts.values())

    # Tur tugmalari
    buttons = []
    for tur_key, tur_label in cfg["turlar"].items():
        cnt = counts.get(tur_key, {})
        n   = cnt.get("items", 0)
        qty = cnt.get("total", 0.0)
        birlik = "dona"
        buttons.append([InlineKeyboardButton(
            text=f"{tur_label}  ({n} xil, {qty:.0f} {birlik})",
            callback_data=f"cb_{cfg['prefix']}_{tur_key}_0",
        )])

    # Tur belgilanmaganlar
    n_none = counts["__none__"]["items"]
    if n_none > 0:
        buttons.append([InlineKeyboardButton(
            text=f"❓ Tur belgilanmagan  ({n_none} ta)",
            callback_data=f"cb_{cfg['prefix']}___none___0",
        )])

    buttons.append([InlineKeyboardButton(
        text="↩️ Yopish", callback_data=f"cb_{cfg['prefix']}_close",
    )])

    text = f"{cfg['title']}\n\nJami: <b>{total_items}</b> xil mahsulot\n\nBo'limni tanlang:"
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(
                text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
        else:
            await msg.answer(
                text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
    except Exception:
        await msg.answer(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )


async def _cat_browser_list(target, db: AsyncSession, cat_key: str, tur_key: str, page: int):
    """Tanlangan tur mahsulotlari ro'yxati."""
    from sqlalchemy import select, func as sqlfunc
    cfg      = CAT_BROWSER_CONFIG[cat_key]
    cat_enum = ProductCategory(cat_key)
    prefix   = cfg["prefix"]

    real_tur = None if tur_key == "__none__" else tur_key

    q = select(WarehouseProduct).where(
        WarehouseProduct.category == cat_enum,
        WarehouseProduct.is_active == True,
        WarehouseProduct.tur == real_tur,
    ).order_by(WarehouseProduct.name, WarehouseProduct.razmer)

    total = (await db.execute(
        select(sqlfunc.count()).select_from(q.subquery())
    )).scalar() or 0

    products = (await db.execute(
        q.limit(CAT_BROWSE_PER_PAGE).offset(page * CAT_BROWSE_PER_PAGE)
    )).scalars().all()

    tur_label = cfg["turlar"].get(tur_key, "❓ Tur belgilanmagan")

    if not products and page == 0:
        msg = target.message if isinstance(target, CallbackQuery) else target
        await msg.answer(
            f"{cfg['title']}\n<b>{tur_label}</b>\n\n📭 Mahsulot yo'q.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Orqaga", callback_data=f"cb_{prefix}_back")]
            ]),
        )
        return

    show_rang  = cfg.get("show_rang", False)
    show_gramm = cfg.get("show_gramm", False)

    lines = []
    for p in products:
        m = float(p.miqdor)
        if m <= float(p.min_threshold):      st = "🔴"
        elif m <= float(p.yellow_threshold): st = "🟡"
        else:                                st = "🟢"

        line = f"{st} <b>{p.name}</b>"
        if show_gramm and p.razmer:
            line += f"  <code>{p.razmer}</code>"      # gramm (80gr, 120gr)
        elif p.razmer:
            line += f" <code>[{p.razmer}]</code>"
        if p.rang:
            rang_icon = "🎨"
            line += f"  {rang_icon} {p.rang}"
        if p.qalinlik:
            line += f"  📐 {p.qalinlik}m³"
        line += f"\n   📦 {p.miqdor:.0f} {p.birlik}"
        lines.append(line)

    pages_total = max(1, (total - 1) // CAT_BROWSE_PER_PAGE + 1)
    header = (
        f"{cfg['title']}\n"
        f"<b>{tur_label}</b>\n"
        f"Jami: <b>{total}</b> ta"
    )
    if pages_total > 1:
        header += f"  |  Sahifa {page+1}/{pages_total}"

    text = header + "\n\n" + "\n\n".join(lines)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◀️ Oldingi", callback_data=f"cb_{prefix}_{tur_key}_{page-1}",
        ))
    if (page + 1) * CAT_BROWSE_PER_PAGE < total:
        nav.append(InlineKeyboardButton(
            text="Keyingisi ▶️", callback_data=f"cb_{prefix}_{tur_key}_{page+1}",
        ))

    inline = []
    if nav: inline.append(nav)
    inline.append([InlineKeyboardButton(text="↩️ Turlar ro'yxati", callback_data=f"cb_{prefix}_back")])

    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(
                text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=inline),
            )
        else:
            await msg.answer(
                text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=inline),
            )
    except Exception:
        await msg.answer(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline),
        )


# ── Tugma → menyu ─────────────────────────────────────────────────────────────

BUTTON_TO_CAT = {
    "🌀 Rulonlar":         "rulon",
    "📋 Gofralar":         "gofra",
    "✂️ Zagatovka":        "gofra_zagatovka",
    "🖨️ Xromazeslar":      "xromazes",
    "✨ Laminat xromazes": "laminat_xromazes",
    "🧩 Adyol zapchast":   "adyol_zapchast",
    "🔧 Stanok ehtiyot":   "uskuna_zapchast",
}


@router.message(F.text.in_(list(BUTTON_TO_CAT.keys())))
async def cat_browser_start(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (
        UserRole.omborchi, UserRole.admin, UserRole.superadmin
    ):
        await message.answer("❌ Ruxsat yo'q"); return
    cat_key = BUTTON_TO_CAT[message.text]
    await _cat_browser_menu(message, db, cat_key)


# ── Callback dispatcher ────────────────────────────────────────────────────────
# cb_{prefix}_{tur_key}_{page}   yoki
# cb_{prefix}_back               yoki
# cb_{prefix}_close

@router.callback_query(F.data.startswith("cb_"))
async def cat_browser_cb(cb: CallbackQuery, db: AsyncSession):
    parts  = cb.data.split("_")
    # cb_{prefix}_{...}
    prefix = parts[1]

    # prefix → cat_key
    prefix_to_cat = {cfg["prefix"]: k for k, cfg in CAT_BROWSER_CONFIG.items()}
    cat_key = prefix_to_cat.get(prefix)
    if not cat_key:
        await cb.answer("Noto'g'ri so'rov"); return

    # Oxirgi ikki qism: action va page
    last = parts[-1]
    second_last = parts[-2] if len(parts) > 2 else ""

    if last == "back":
        await _cat_browser_menu(cb, db, cat_key)
    elif last == "close":
        try:
            await cb.message.delete()
        except Exception:
            pass
    else:
        # cb_{prefix}_{tur_key}_{page}
        # tur_key da _ bo'lishi mumkin → oxirgi element page, qolganlari tur_key
        try:
            page    = int(last)
            tur_key = "_".join(parts[2:-1])
            await _cat_browser_list(cb, db, cat_key, tur_key, page)
        except (ValueError, IndexError):
            await cb.answer("Xato so'rov")

    await cb.answer()


@router.callback_query(F.data == "wh_cancel")
async def wh_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        await cb.message.answer("❌ Bekor qilindi.")
    await cb.answer()


@router.callback_query(F.data == "confirm_no")
async def wh_confirm_no(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        await cb.message.answer("❌ Bekor qilindi.")
    await cb.answer()


# ═══ ADMIN / OMBORCHI — UMUMIY OMBOR KO'RINISHI ══════════════════════════════

@router.message(F.text == "Ombor")
async def admin_ombor(message: Message, db: AsyncSession):
    """Admin uchun ombor — omborchi bilan bir xil ko'rinish."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (
        UserRole.admin, UserRole.superadmin
    ):
        await message.answer("❌ Ruxsat yo'q"); return

    from sqlalchemy import select, func as sqlfunc

    # Har kategoriya uchun jami soni + kam qolganlar
    buttons = []
    warn_total = 0

    for label, cat_key in ADMIN_OMBOR_CATS:
        from database.models import ProductCategory as PC
        try:
            cat_enum = PC(cat_key)
        except ValueError:
            continue

        r = await db.execute(
            select(
                sqlfunc.count(WarehouseProduct.id),
                sqlfunc.sum(
                    sa_case(
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
        warn = row[1] or 0
        warn_total += warn

        btn_text = f"{label}  ({cnt} ta"
        if warn:
            btn_text += f", ⚠️ {warn} kam"
        btn_text += ")"

        # cat_key ga mos tugma prefixni topish
        cat_cb = f"admin_ombor_cat_{cat_key}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cat_cb)])

    header = "🏭 <b>Ombor holati</b>\n"
    if warn_total:
        header += f"⚠️ Jami <b>{warn_total}</b> ta kam qolgan mahsulot!\n"
    header += "\nKategoriya tanlang:"

    await message.answer(
        header, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("admin_ombor_cat_"))
async def admin_ombor_cat(cb: CallbackQuery, db: AsyncSession):
    cat_key = cb.data.replace("admin_ombor_cat_", "")

    if cat_key == "yarim_tayyor":
        # Yarim tayyor — alohida tur browser
        await _yt_menu(cb, db)
    elif cat_key == "tayyor_mahsulot":
        # Tayyor mahsulotlar — oddiy ro'yxat
        await _simple_cat_list(cb, db, cat_key)
    elif cat_key in CAT_BROWSER_CONFIG:
        await _cat_browser_menu(cb, db, cat_key)
    elif cat_key == "qolip":
        # Qolip — qolip handler ga yo'naltirish (inline)
        await _qolip_overview_inline(cb, db)
    else:
        await _simple_cat_list(cb, db, cat_key)
    await cb.answer()


async def _yt_menu(target, db):
    """Yarim tayyor turlar menyusi (admin uchun ham)."""
    from sqlalchemy import select, func as sqlfunc
    counts = {}
    for tur_key in _YT:
        r = await db.execute(
            select(sqlfunc.count(WarehouseProduct.id),
                   sqlfunc.coalesce(sqlfunc.sum(WarehouseProduct.miqdor), 0))
            .where(
                WarehouseProduct.category == ProductCategory.yarim_tayyor,
                WarehouseProduct.is_active == True,
                WarehouseProduct.tur == tur_key,
            )
        )
        row = r.one()
        counts[tur_key] = {"items": row[0], "total": int(row[1])}

    YT_ICONS = {
        "tiger_uchun":"✂️","gofra_kley_zagatovka":"🔨","gofra_kley_xromazes":"🖨️",
        "gofra_uchun_rulon":"🌀","list_qogoz_uchun_rulon":"📄","zagatovka_uchun_gofra":"✂️",
        "stepler_uchun":"📌","salafan_uchun":"🎁",
        "yopish_uchun":"🔗","adyol_tikish_uchun":"🧵","pastel_tikish_uchun":"💼",
        "adyol_qoqish_uchun":"📫","pastel_qoqish_uchun":"📬","xom_komple":"📦",
        "kapalak":"🦋","boshqa":"📝",
    }
    buttons = []
    for tur_key, tur_name in _YT.items():
        cnt  = counts.get(tur_key, {})
        icon = YT_ICONS.get(tur_key, "📦")
        n    = cnt.get("items", 0)
        qty  = cnt.get("total", 0)
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {tur_name}  ({n} xil, {qty} dona)",
            callback_data=f"yt_tur_{tur_key}_0",
        )])
    buttons.append([InlineKeyboardButton(text="↩️ Orqaga", callback_data="admin_ombor_back")])
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(
                "🧩 <b>Yarim tayyor</b>\n\nBo'limni tanlang:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
        else:
            await msg.answer(
                "🧩 <b>Yarim tayyor</b>\n\nBo'limni tanlang:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
    except Exception:
        await msg.answer(
            "🧩 <b>Yarim tayyor</b>\n\nBo'limni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )


async def _simple_cat_list(target, db, cat_key):
    """Tur bo'lmagan kategoriyalar uchun oddiy ro'yxat."""
    from sqlalchemy import select
    from database.models import ProductCategory as PC
    cat_enum = PC(cat_key)
    products = (await db.execute(
        select(WarehouseProduct)
        .where(WarehouseProduct.category == cat_enum, WarehouseProduct.is_active == True)
        .order_by(WarehouseProduct.name)
        .limit(30)
    )).scalars().all()

    if not products:
        msg = target.message if isinstance(target, CallbackQuery) else target
        await msg.answer("📭 Mahsulot yo'q.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Orqaga", callback_data="admin_ombor_back")]
            ]))
        return

    lines = []
    for p in products:
        m = float(p.miqdor)
        st = "🔴" if m <= float(p.min_threshold) else ("🟡" if m <= float(p.yellow_threshold) else "🟢")
        line = f"{st} <b>{p.name}</b>"
        if p.razmer: line += f" <code>[{p.razmer}]</code>"
        if p.rang:   line += f" — {p.rang}"
        line += f"\n   {p.miqdor:.0f} {p.birlik}"
        lines.append(line)

    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(
                "\n\n".join(lines), parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Orqaga", callback_data="admin_ombor_back")]
                ]),
            )
        else:
            await msg.answer(
                "\n\n".join(lines), parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Orqaga", callback_data="admin_ombor_back")]
                ]),
            )
    except Exception:
        await msg.answer("\n\n".join(lines[:15]), parse_mode="HTML")


async def _qolip_overview_inline(target, db):
    """Qolip turlari inline ko'rinishi."""
    from constants import QOLIP_TURLAR as QT
    from sqlalchemy import select, func as sqlfunc
    buttons = []
    for tur_key, tur_label in QT.items():
        r = await db.execute(
            select(sqlfunc.count(WarehouseProduct.id))
            .where(
                WarehouseProduct.category == ProductCategory.qolip,
                WarehouseProduct.is_active == True,
                WarehouseProduct.tur == tur_key,
            )
        )
        cnt = r.scalar() or 0
        buttons.append([InlineKeyboardButton(
            text=f"{tur_label}  ({cnt} ta)",
            callback_data=f"cb_qolip_tur_{tur_key}_0",
        )])
    buttons.append([InlineKeyboardButton(text="↩️ Orqaga", callback_data="admin_ombor_back")])
    msg = target.message if isinstance(target, CallbackQuery) else target
    try:
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(
                "🔲 <b>Qoliplar</b>\n\nTurni tanlang:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
        else:
            await msg.answer(
                "🔲 <b>Qoliplar</b>\n\nTurni tanlang:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
    except Exception:
        await msg.answer("🔲 <b>Qoliplar</b>\n\nTurni tanlang:", parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "admin_ombor_back")
async def admin_ombor_back(cb: CallbackQuery, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user: await cb.answer(); return
    from sqlalchemy import select, func as sqlfunc
    from database.models import ProductCategory as PC

    buttons = []
    warn_total = 0
    for label, cat_key in ADMIN_OMBOR_CATS:
        try:
            cat_enum = PC(cat_key)
        except ValueError:
            continue
        r = await db.execute(
            select(
                sqlfunc.count(WarehouseProduct.id),
                sqlfunc.sum(
                    sa_case(
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
        warn = row[1] or 0
        warn_total += warn
        btn_text = f"{label}  ({cnt} ta"
        if warn: btn_text += f", ⚠️ {warn} kam"
        btn_text += ")"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_ombor_cat_{cat_key}")])

    header = "🏭 <b>Ombor holati</b>\n"
    if warn_total:
        header += f"⚠️ <b>{warn_total}</b> ta kam qolgan!\n"
    header += "\nKategoriya tanlang:"

    try:
        await cb.message.edit_text(
            header, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception:
        await cb.message.answer(
            header, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    await cb.answer()

@router.message(F.text == "🌐 Web panel")
async def omborchi_web_panel(message: Message, db: AsyncSession):
    """Omborchi uchun shaxsiy web panel havolasi."""
    user = await get_user(db, message.from_user.id)
    if not user:
        return
    from utils.web_link import get_or_create_web_link
    link = await get_or_create_web_link(db, user)
    await message.answer(
        f"🌐 <b>Ombor Web paneli</b>\n\n"
        f"{link}\n\n"
        f"⚠️ Shaxsiy havola — boshqalarga bermang.\n"
        f"Telefon yoki kompyuterda oching — parol kerak emas.",
        parse_mode="HTML",
    )

