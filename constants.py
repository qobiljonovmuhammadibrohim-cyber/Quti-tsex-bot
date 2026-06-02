"""
constants.py — Barcha kategoriyalar, turlar, birliklar.
"""

CAT_NAMES = {
    "rulon":            "🌀 Rulonlar",
    "gofra":            "📋 Gofra",
    "gofra_zagatovka":  "✂️ Zagatovka gofralari",
    "xromazes":         "🖨️ Xromazeslar",
    "laminat_xromazes": "✨ Laminat Xromazeslar",
    "yarim_tayyor":     "⚙️ Yarim tayyor",
    "qolip":            "🔲 Qoliplar",
    "tayyor_mahsulot":  "📦 Tayyor mahsulotlar",
    "adyol_zapchast":   "🧩 Adyol zapchastlari",
    "uskuna_zapchast":  "🔧 Stanok ehtiyot qismlari",
}

CATEGORY_TURLAR = {
    "yarim_tayyor": {
        "tiger_uchun":         "✂️ Tiger kesish uchun",
        "gofra_kley_uchun":    "🔨 Gofra kley uchun",
        "xromazes_laminat":    "✨ Laminatsiya uchun xromazeslar",
        "xromazes_gofra":      "🖨️ Gofra kley uchun xromazeslar",
        "stepler_uchun":       "📌 Stepler tikish uchun",
        "salafan_uchun":       "🎁 Rulonga salafan uchun",
        "yopish_uchun":        "🔗 Yopishtirish uchun",
        "adyol_tikish_uchun":  "🧵 Adyol tikish uchun",
        "pastel_tikish_uchun": "💼 Pastel tikish uchun",
        "adyol_qoqish_uchun":  "📫 Adyol qoqish uchun",
        "pastel_qoqish_uchun": "📬 Pastel qoqish uchun",
        "xom_komple":          "📦 Xom komple",
        "kapalak":             "🦋 Kapalak",
        "boshqa":              "📝 Boshqa",
    },
    "gofra": {
        "Yirik": "🔵 Yirik gofra",
        "Mayin": "🟢 Mayin gofra",
    },
    "gofra_zagatovka": {
        "Yirik": "🔵 Yirik gofradan kesilgan",
        "Mayin": "🟢 Mayin gofradan kesilgan",
    },
    "rulon": {
        "yangi":     "🆕 Yangi rulon",
        "oralgan":   "🔄 O'ralgan rulon",
        "salafanli": "🎁 Salafanli rulon",
    },
    "xromazes":         None,
    "laminat_xromazes": None,
    "qolip":            None,
    "tayyor_mahsulot":  None,
    "adyol_zapchast":   None,
    "uskuna_zapchast":  None,
}

BIRLIKLAR = {
    "dona":  "🔢 Dona",
    "kg":    "⚖️ Kilogram",
    "top":   "📦 Top",
    "rulon": "🌀 Rulon",
    "m":     "📏 Metr",
    "m2":    "📐 Metr kvadrat",
    "litr":  "🧪 Litr",
}

TRANSFER_ALLOWED = {
    "tiger_uchun": ["stepler_uchun", "adyol_tikish_uchun", "pastel_tikish_uchun", "yopish_uchun"],
    "gofra_kley_uchun":    ["tiger_uchun"],
    "adyol_tikish_uchun":  ["adyol_qoqish_uchun"],
    "pastel_tikish_uchun": ["pastel_qoqish_uchun"],
    "adyol_qoqish_uchun":  ["xom_komple", "kapalak"],
    "pastel_qoqish_uchun": ["xom_komple", "kapalak"],
    "xom_komple":          ["kapalak"],
    "kapalak":             ["xom_komple"],
}


# ═══ KATEGORIYA TURLARI (Browser tizimi uchun) ════════════════════════════════

# Rulonlar turlari (rang va gramm alohida ko'rsatiladi)
RULON_TURLAR = {
    "yangi":     "🆕 Yangi rulon",
    "oralgan":   "🔄 O'ralgan rulon",
    "salafanli": "🎁 Salafanli rulon",
}

# Gofra turlari
GOFRA_TURLAR = {
    "Yirik": "🔵 Yirik gofra",
    "Mayin": "🟢 Mayin gofra",
}


# Zagatovka gofralar turlari
ZAGATOVKA_TURLAR = {
    "adyol":      "🛏 Adyol uchun",
    "pastel":     "💼 Pastel uchun",
    "poyabzal":   "👟 Poyabzal uchun",
    "shirinlik":  "🍰 Shirinlik uchun",
    "fast_food":  "🍔 Fast food uchun",
    "boshqa":     "📝 Boshqa",
}

# Xromazeslar turlari
XROMAZES_TURLAR = {
    "adyol_pastel": "🛏 Adyol / Pastel",
    "poyabzal":     "👟 Poyabzal",
    "shirinlik":    "🍰 Shirinlik",
    "fast_food":    "🍔 Fast food",
    "boshqa":       "📝 Boshqa",
}

# Laminat xromazeslar — xromazeslar bilan bir xil
LAMINAT_XROMAZES_TURLAR = {
    "adyol_pastel": "🛏 Adyol / Pastel (laminat)",
    "poyabzal":     "👟 Poyabzal (laminat)",
    "shirinlik":    "🍰 Shirinlik (laminat)",
    "fast_food":    "🍔 Fast food (laminat)",
    "boshqa":       "📝 Boshqa",
}

# Adyol zapchastlari turlari
ADYOL_ZAPCHAST_TURLAR = {
    "quluf":      "🔒 Qulflar (tepa/past)",
    "ruchka":     "🖐 Ruchka va ilgaklar",
    "piston":     "⚙️ Pistonlar (katta/kapalak/remen)",
    "ip_tesma":   "🧵 IP va tesmalar",
    "boshqa":     "📝 Boshqa",
}

# Uskuna (stanok) ehtiyot qismlari turlari
USKUNA_ZAPCHAST_TURLAR = {
    "motor":        "⚡ Motorlar",
    "tasma_kamar":  "🔄 Tasma va kamarlar",
    "podshipnik":   "🔩 Podshipniklar",
    "boshqa":       "📝 Boshqa ehtiyot qismlar",
}

# Qoliplar turlarida "boshqa" allaqachon bor (models.py da)

# Barcha kategoriya browser konfiguratsiyasi
CAT_BROWSER_CONFIG = {
    "gofra_zagatovka":  {
        "title":  "✂️ Zagatovka gofralar",
        "button": "✂️ Zagatovka",
        "turlar": ZAGATOVKA_TURLAR,
        "prefix": "zag",
    },
    "xromazes": {
        "title":  "🖨️ Xromazeslar",
        "button": "🖨️ Xromazeslar",
        "turlar": XROMAZES_TURLAR,
        "prefix": "xrm",
    },
    "laminat_xromazes": {
        "title":  "✨ Laminat xromazeslar",
        "button": "✨ Laminat xromazes",
        "turlar": LAMINAT_XROMAZES_TURLAR,
        "prefix": "lxr",
    },
    "adyol_zapchast": {
        "title":  "🧩 Adyol zapchastlari",
        "button": "🧩 Adyol zapchast",
        "turlar": ADYOL_ZAPCHAST_TURLAR,
        "prefix": "azp",
    },
    "uskuna_zapchast": {
        "title":  "🔧 Stanok ehtiyot qismlari",
        "button": "🔧 Stanok ehtiyot",
        "turlar": USKUNA_ZAPCHAST_TURLAR,
        "prefix": "uzp",
    },
    "rulon": {
        "title":  "🌀 Rulonlar",
        "button": "🌀 Rulonlar",
        "turlar": RULON_TURLAR,
        "prefix": "rln",
        "show_rang": True,
        "show_gramm": True,   # razmer field = gramm (80gr, 120gr...)
    },
    "gofra": {
        "title":  "📋 Gofralar",
        "button": "📋 Gofralar",
        "turlar": GOFRA_TURLAR,
        "prefix": "gfr",
    },
}

# Admin ombor overview uchun barcha kategoriyalar
ADMIN_OMBOR_CATS = [
    ("🌀 Rulonlar",           "rulon"),
    ("📋 Gofralar",           "gofra"),
    ("✂️ Zagatovka",          "gofra_zagatovka"),
    ("🖨️ Xromazeslar",        "xromazes"),
    ("✨ Laminat xromazes",   "laminat_xromazes"),
    ("🧩 Yarim tayyor",       "yarim_tayyor"),
    ("🔲 Qoliplar",           "qolip"),
    ("📦 Tayyor mahsulotlar", "tayyor_mahsulot"),
    ("🧩 Adyol zapchast",     "adyol_zapchast"),
    ("🔧 Stanok ehtiyot",     "uskuna_zapchast"),
]

# ═══ QISM TURLARI (Adyol/Pastel qismlari) ════════════════════════════════════

ADYOL_QISM_TURLAR = {
    "tepa":  "⬆️ Tepa qism",
    "past":  "⬇️ Past qism",
    "yon":   "↔️ Yon qism (×2)",
}

PASTEL_QISM_TURLAR = {
    "tepa":  "⬆️ Tepa qism",
    "past":  "⬇️ Past qism",
    "paddo": "🔲 Paddo (ichki qism)",
}

# Qism ikonlari
QISM_ICONS = {
    "tepa":  "⬆️",
    "past":  "⬇️",
    "yon":   "↔️",
    "paddo": "🔲",
}

# ═══ NARX VARIANTLARI ════════════════════════════════════════════════════════
# Har bir ish turi uchun qanday narx variantlari borligini belgilaydi.
# razmer_turi maydoniga shu qiymatlar yoziladi.

PRICE_VARIANTS = {
    # 3 xil — razmer bo'yicha (Katta / O'rta / Kichik)
    "tiger_kesish":    ["Katta", "O'rta", "Kichik"],
    "laminatsiya":     ["Katta", "O'rta", "Kichik"],
    "zagatovka":       ["Katta", "O'rta", "Kichik"],
    "stepler_tikish":  ["Katta", "O'rta", "Kichik"],
    "yopishtirma":     ["Katta", "O'rta", "Kichik"],

    # 6 xil — razmer × sloy (gofra kley)
    "gofra_kiley":     ["Katta 3sloy", "O'rta 3sloy", "Kichik 3sloy",
                        "Katta 5sloy", "O'rta 5sloy", "Kichik 5sloy"],

    # 1 xil — o'zgarmaydi
    "gofra_ishlab":    ["Standart"],
    "list_qogoz":      ["Standart"],
    "rulon_orash":     ["Standart"],
    "rulonga_salafan": ["Standart"],
    "rulon_ishlab":    ["Standart"],   # rulon ishlab chiqarish
    "diplomat_tikish": ["Standart"],  # faqat tepa tikiladi

    # Adyol tikish — 3 qism (tepa / past / yon)
    "adyol_tikish":    ["Tepa", "Past", "Yon"],

    # Adyol qoqish — 3 xom + kapalak + yig'ish
    "adyol_qoqish":    ["Tepa xom", "Past xom", "Yon xom", "Kapalak", "Yig'ish"],

    # Pastel qoqish — 2 xom + kapalak + yig'ish
    "pastel_qoqish":   ["Tepa xom", "Past xom", "Kapalak", "Yig'ish"],
}

# Ish turi nomlari (chiroyli ko'rsatish uchun)
WORK_TYPE_NAMES = {
    "tiger_kesish":    "✂️ Tiger kesish",
    "laminatsiya":     "✨ Laminatsiya",
    "zagatovka":       "📦 Zagatovka",
    "stepler_tikish":  "📌 Stepler tikish",
    "yopishtirma":     "🔗 Yopishtirma",
    "gofra_kiley":     "🔨 Gofra kley",
    "gofra_ishlab":    "📐 Gofra ishlab chiqarish",
    "list_qogoz":      "📄 List qog'oz kesish",
    "rulon_orash":     "🌀 Rulon o'rash",
    "rulonga_salafan": "🎁 Rulonga salafan",
    "rulon_ishlab":    "🌀 Rulon ishlab chiqarish",
    "diplomat_tikish": "💼 Diplomat/Pastel tikish",
    "adyol_tikish":    "🧵 Adyol tikish",
    "adyol_qoqish":    "🛏 Adyol qoqish",
    "pastel_qoqish":   "📫 Pastel qoqish",
}


def get_variants(work_type_value: str) -> list:
    """Ish turi uchun narx variantlarini qaytaradi."""
    return PRICE_VARIANTS.get(work_type_value, ["Standart"])


def get_work_name(work_type_value: str) -> str:
    """Ish turi nomini qaytaradi."""
    return WORK_TYPE_NAMES.get(work_type_value, work_type_value.replace("_", " ").title())
