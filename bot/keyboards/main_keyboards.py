"""
main_keyboards.py — TUZATILGAN
TUZATISHLAR:
  1. Ishchi menyusiga "⚡ Tez kiritish" tugmasi qo'shildi
     (worker.py v11 da bu handler bor)
  2. Omborchi menyusiga "Transfer (zanjir)" tugmasi qo'shildi
  3. Nazoratchi menyusiga "Ombor holati" tugmasi qo'shildi
"""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from database.models import UserRole


def get_main_menu(role: UserRole) -> ReplyKeyboardMarkup:
    if role == UserRole.ishchi:
        buttons = [
            [KeyboardButton(text="Smena boshlash"),      KeyboardButton(text="Smena tugatish")],
            [KeyboardButton(text="Ish kiritish"),         KeyboardButton(text="⚡ Tez kiritish")],
            [KeyboardButton(text="Bugungi daromad"),      KeyboardButton(text="Bugungi ishlarim")],
            [KeyboardButton(text="Ish ozgartirish"),      KeyboardButton(text="Oylik maosh")],
            [KeyboardButton(text="📋 Davomat"),           KeyboardButton(text="📅 Mening davomatim")],
            [KeyboardButton(text="Mening jarimalarim"),   KeyboardButton(text="Kabinet")],
        ]
    elif role == UserRole.nazoratchi:
        buttons = [
            [KeyboardButton(text="📊 Dashboard"),        KeyboardButton(text="⚡ Batch tasdiqlash")],
            [KeyboardButton(text="Tekshiruv boshlash")],
            [KeyboardButton(text="Bugungi holat"),      KeyboardButton(text="Ishchilar holati")],
            [KeyboardButton(text="Ombor holati"),       KeyboardButton(text="Jarimalar")],
            [KeyboardButton(text="Tekshiruv hisoboti"), KeyboardButton(text="Smena holati")],
            [KeyboardButton(text="Reyting"),            KeyboardButton(text="Sifat hisoboti")],
            [KeyboardButton(text="📊 Davomat hisoboti")],
        ]
    elif role == UserRole.omborchi:
        buttons = [
            [KeyboardButton(text="Kirim"),                  KeyboardButton(text="Chiqim")],
            [KeyboardButton(text="Ombor qoldighi"),         KeyboardButton(text="Mahsulot qidirish")],
            [KeyboardButton(text="🌀 Rulonlar"),            KeyboardButton(text="📋 Gofralar")],
            [KeyboardButton(text="🧩 Yarim tayyor"),        KeyboardButton(text="🔲 Qoliplar")],
            [KeyboardButton(text="✂️ Zagatovka"),           KeyboardButton(text="🖨️ Xromazeslar")],
            [KeyboardButton(text="✨ Laminat xromazes"),    KeyboardButton(text="🧩 Adyol zapchast")],
            [KeyboardButton(text="🔧 Stanok ehtiyot"),      KeyboardButton(text="Transfer (zanjir)")],
            [KeyboardButton(text="Inventarizatsiya"),       KeyboardButton(text="Buyurtma royxati")],
            [KeyboardButton(text="Ombor hisoboti"),         KeyboardButton(text="Mahsulot tarixi")],
            [KeyboardButton(text="Mahsulot tahrirlash")],
        ]
    elif role in (UserRole.admin, UserRole.superadmin):
        buttons = [
            [KeyboardButton(text="📊 Dashboard")],
            [KeyboardButton(text="Ombor"),               KeyboardButton(text="Ishchilar")],
            [KeyboardButton(text="Hisobotlar"),          KeyboardButton(text="Maosh")],
            [KeyboardButton(text="Narxlar"),             KeyboardButton(text="Jarimalar")],
            [KeyboardButton(text="📊 Davomat hisoboti"), KeyboardButton(text="🔄 Yangi oy boshlash")],
            [KeyboardButton(text="📄 PDF hisobotlar"),   KeyboardButton(text="Web panel")],
            [KeyboardButton(text="📋 Buyurtmalar"),       KeyboardButton(text="🩺 Tizim holati")],
            [KeyboardButton(text="🎯 Maqsadlar"),         KeyboardButton(text="Foydalanuvchi qoshish")],
        ]
    else:
        buttons = [[KeyboardButton(text="Menyu")]]

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Bekor qilish")]],
        resize_keyboard=True,
    )


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash",   callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="confirm_no"),
        ],
    ])


def get_product_category_keyboard() -> InlineKeyboardMarkup:
    CAT_NAMES = {
        "rulon":           "Rulonlar",
        "gofra":           "Gofralar",
        "gofra_zagatovka": "Zagatovka gofralar",
        "xromazes":        "Xromazeslar",
        "laminat_xromazes":"Laminat xromazeslar",
        "yarim_tayyor":    "Yarim tayyor",
        "qolip":           "Qoliplar",
        "tayyor_mahsulot": "Tayyor mahsulot",
        "adyol_zapchast":  "Adyol zapchast",
        "uskuna_zapchast": "Uskuna zapchast",
    }
    buttons = []
    items = list(CAT_NAMES.items())
    for i in range(0, len(items), 2):
        row = []
        for cat_val, cat_name in items[i:i+2]:
            row.append(InlineKeyboardButton(
                text=cat_name, callback_data=f"cat_{cat_val}"
            ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Yangi mahsulot", callback_data="cat_yangi")])
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_work_type_keyboard() -> InlineKeyboardMarkup:
    """Ish turlari — 2 qator (keng ko'rinish)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✂️ Tiger kesish",           callback_data="work_tiger_kesish"),
            InlineKeyboardButton(text="🔨 Gofra kiley",            callback_data="work_gofra_kiley"),
        ],
        [
            InlineKeyboardButton(text="📐 Gofra ishlab",           callback_data="work_gofra_ishlab"),
            InlineKeyboardButton(text="📄 List kesish",            callback_data="work_list_qogoz"),
        ],
        [
            InlineKeyboardButton(text="✨ Laminatsiya",            callback_data="work_laminatsiya"),
            InlineKeyboardButton(text="📦 Zagatovka",              callback_data="work_zagatovka"),
        ],
        [
            InlineKeyboardButton(text="📌 Stepler tikish",         callback_data="work_stepler_tikish"),
            InlineKeyboardButton(text="🔗 Yopishtirma",            callback_data="work_yopishtirma"),
        ],
        [
            InlineKeyboardButton(text="🌀 Rulon o'rash",           callback_data="work_rulon_orash"),
            InlineKeyboardButton(text="🎁 Rulonga salafan",        callback_data="work_rulonga_salafan"),
        ],
        [
            InlineKeyboardButton(text="🧵 Adyol tikish",           callback_data="work_adyol_tikish"),
            InlineKeyboardButton(text="💼 Pastel tikish",          callback_data="work_diplomat_tikish"),
        ],
        [
            InlineKeyboardButton(text="🛏 Adyol qoqish",           callback_data="work_adyol_qoqish"),
            InlineKeyboardButton(text="📫 Pastel qoqish",          callback_data="work_pastel_qoqish"),
        ],
        [InlineKeyboardButton(text="❌ Bekor qilish",              callback_data="cancel")],
    ])


def get_gofra_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔵 Yirik gofra", callback_data="gofra_yirik"),
            InlineKeyboardButton(text="🟢 Mayin gofra", callback_data="gofra_mayin"),
        ],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")],
    ])


def get_gofra_sloy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3-sloy", callback_data="sloy_3"),
            InlineKeyboardButton(text="5-sloy", callback_data="sloy_5"),
        ],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")],
    ])


def get_size_keyboard() -> InlineKeyboardMarkup:
    """
    worker_adyol_pastel.py da ishlatiladi.
    SIZE_MAP = {"size_katta": "Katta", "size_orta": "O'rta", "size_kichik": "Kichik"}
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔵 Katta",  callback_data="size_katta"),
            InlineKeyboardButton(text="🟡 O'rta",  callback_data="size_orta"),
            InlineKeyboardButton(text="🔴 Kichik", callback_data="size_kichik"),
        ],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")],
    ])


def get_quality_keyboard(work_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐⭐⭐ A-sifat (100%)",    callback_data=f"qc_1_{work_id}")],
        [InlineKeyboardButton(text="⭐⭐  B-sifat (80%)",     callback_data=f"qc_2_{work_id}")],
        [InlineKeyboardButton(text="⭐    C-sifat / Brak (60%)", callback_data=f"qc_3_{work_id}")],
        [InlineKeyboardButton(text="⏭ Keyingisi (o'tkazib yuborish)", callback_data=f"inspect_next_{work_id}")],
    ])


def get_inspector_work_keyboard(work_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"inspect_approve_{work_id}"),
            InlineKeyboardButton(text="✏️ Tuzatish",   callback_data=f"inspect_adjust_{work_id}"),
        ],
        [InlineKeyboardButton(text="❌ Rad etish",   callback_data=f"inspect_reject_{work_id}")],
        [InlineKeyboardButton(text="⏭ Keyingisi",   callback_data=f"inspect_next_{work_id}")],
    ])


def get_penalty_type_keyboard(work_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Jarima berish",   callback_data=f"pen_jarima_{work_id}")],
        [InlineKeyboardButton(text="⚠️ 1-xaypsan",       callback_data=f"pen_xaypsan1_{work_id}")],
        [InlineKeyboardButton(text="⚠️ 2-xaypsan",       callback_data=f"pen_xaypsan2_{work_id}")],
        [InlineKeyboardButton(text="🚫 Faqat rad etish", callback_data=f"pen_none_{work_id}")],
    ])


def get_worker_confirmed_keyboard(penalty_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Ko'rdim va tushundim",
            callback_data=f"confirm_penalty_{penalty_id}",
        )]
    ])
