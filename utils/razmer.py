"""
utils/razmer.py — Razmer normalizatsiyasi va qidiruv yordamchilari

normalize_razmer("40 x 40 x 60") → "40x40x60"
normalize_razmer("90 X 110")     → "90x110"
razmer_search_variants("40")     → ["40"] (har qanday o'lchamda 40 bo'lsa)
razmer_search_variants("40x40")  → ["40x40"]
"""
import re
from typing import List, Optional


def normalize_razmer(val) -> Optional[str]:
    """
    Razmerни normallashtirish:
      "40 x 40 x 60"  → "40x40x60"
      "90 X 110"       → "90x110"
      "40х40"          (kirill x) → "40x40"
      " 90x110 "       → "90x110"
      None / ""        → None
    """
    if val is None:
        return None
    s = str(val).strip().lower()
    if not s:
        return None
    # Kirill "х", unicode × ham qabul qilinadi
    s = re.sub(r'\s*[xхX×]\s*', 'x', s)
    # Ko'p bo'shliqlarni tozalash
    s = re.sub(r'\s+', '', s).strip()
    return s if s else None


def razmer_search_variants(query: str) -> List[str]:
    """
    Qidiruv so'zidan razmer variantlari hosil qilish.

    "40x40x60" → ["40x40x60"]          (aniq moslik)
    "40x40"    → ["40x40"]             (2 o'lchamli)
    "40"       → ["40x", "x40x", "x40"]  (istalgan joyda 40 bo'lsa)

    Qaytarilgan qiymatlar ILIKE "%variant%" sifatida ishlatiladi.
    """
    if not query:
        return []

    norm = normalize_razmer(query)
    if not norm:
        return []

    parts = norm.split('x')

    if len(parts) == 1:
        # Bitta raqam — har qanday o'lchamda bo'lishi mumkin
        n = parts[0].strip()
        if not n:
            return []
        return [
            f"{n}x",    # boshida: "40x..."
            f"x{n}x",   # o'rtada: "...x40x..."
            f"x{n}",    # oxirida: "...x40"
        ]
    else:
        # Ko'p qismli razmer — aniq qidirish
        return [norm]


def razmer_contains_dimension(razmer_normalized: str, dim: str) -> bool:
    """
    razmer_normalized ichida dim o'lchami bor-yo'qligini tekshiradi.
    razmer_contains_dimension("40x40x60", "40") → True
    razmer_contains_dimension("40x40x60", "60") → True
    razmer_contains_dimension("40x40x60", "50") → False
    """
    if not razmer_normalized or not dim:
        return False
    parts = normalize_razmer(razmer_normalized)
    if not parts:
        return False
    return dim in parts.split('x')
