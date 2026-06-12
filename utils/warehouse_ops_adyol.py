"""
utils/warehouse_ops_adyol.py — Adyol/Pastel ombor operatsiyalari
MANTIQ:
  11. adyol_tikish:
      - CHIQIM: yarim_tayyor (adyol_tikish_uchun) ← tiger kesishdan kelgan qog'ozlar
      - KIRIM:  yarim_tayyor (adyol_qoqish_uchun) ← tikilgan adyol karobkalar

  12. diplomat_tikish:
      - CHIQIM: yarim_tayyor (pastel_tikish_uchun) ← tiger kesishdan kelgan qog'ozlar
      - KIRIM:  yarim_tayyor (pastel_qoqish_uchun) ← tikilgan pastel karobkalar

  13. adyol_qoqish — 3 tur:
      XOM:
        - CHIQIM: yarim_tayyor (adyol_qoqish_uchun) ← tikilgan karobkalar
        - KIRIM:  yarim_tayyor (xom_komple) ← qoqilgan lekin yakunlanmagan

      KAPALAK:
        - CHIQIM: yarim_tayyor (xom_komple yoki adyol_qoqish_uchun) ← src
        - KIRIM:  yarim_tayyor (kapalak) yoki tayyor_mahsulot ← qaerga ketishiga qarab

      YIGISH:
        - CHIQIM: yarim_tayyor (kapalak) ← kapalaklar
        - KIRIM:  tayyor_mahsulot ← tugallangan tayyor mahsulot

  14. pastel_qoqish — xuddi adyol_qoqish kabi, lekin remen qismi yo'q
"""
import logging
from sqlalchemy import select
from database.models import WarehouseProduct, WarehouseLog, ProductCategory
from database.queries import get_product_by_id, update_product_miqdor

logger = logging.getLogger(__name__)


# ── YORDAMCHI ────────────────────────────────────────────────────────────────

def _safe_int(val, default=0) -> int:
    try:   return max(0, int(float(val)))
    except: return default


def _safe_float(val, default=0.0) -> float:
    try:   return max(0.0, float(val))
    except: return default


def _str_or_none(val):
    if val is None or str(val).strip() == "": return None
    return str(val).strip()


def _normalize_razmer(val) -> str | None:
    """
    Razmer normalizatsiyasi: "90 x 110" → "90x110"
    """
    if val is None:
        return None
    s = str(val).strip().lower()
    if not s:
        return None
    import re
    s = re.sub(r'\s*[xх×]\s*', 'x', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s



async def _chiqim(db, product_id, miqdor, user_id, izoh, work_entry_id=None):
    """Ombordan chiqim. Warn (str) yoki None qaytaradi."""
    if not product_id:
        return "Material tanlanmadi — ombor ayirilmadi"
    p = await get_product_by_id(db, product_id)
    if not p:
        return f"Mahsulot topilmadi (id={product_id})"
    actual = float(p.miqdor)
    miqdor = float(miqdor)
    if actual <= 0:
        return f"{p.name}: omborda mahsulot qolmagan"
    if actual < miqdor:
        warn = (
            f"⚠️ {p.name}: so'ralgan {miqdor:.1f}, "
            f"omborda {actual:.1f} {p.birlik} — mavjud miqdor chiqildi."
        )
        logger.warning("Ombor yetarli emas: %s (mavjud=%.1f, so'ralgan=%.1f)", p.name, actual, miqdor)
        await update_product_miqdor(db, product_id, -actual, user_id, izoh, work_entry_id)
        return warn
    await update_product_miqdor(db, product_id, -miqdor, user_id, izoh, work_entry_id)
    return None


async def _kirim(db, category, name, miqdor, user_id, izoh,
                 razmer=None, rang=None, tur=None, qism=None, birlik="dona", work_entry_id=None):
    """Omborga kirim. Mavjud bo'lsa yangilaydi, yo'q bo'lsa yaratadi."""
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == category,
        WarehouseProduct.name == name,
        WarehouseProduct.is_active == True,
    )
    razmer = _normalize_razmer(razmer)
    if razmer: q = q.where(WarehouseProduct.razmer == razmer)
    if rang:   q = q.where(WarehouseProduct.rang == rang)
    if tur:    q = q.where(WarehouseProduct.tur == tur)
    if qism:   q = q.where(WarehouseProduct.qism == qism)
    r = await db.execute(q.limit(1))
    product = r.scalar_one_or_none()
    if product:
        await update_product_miqdor(db, product.id, float(miqdor), user_id, izoh, work_entry_id)
    else:
        product = WarehouseProduct(
            category=category, name=name,
            razmer=razmer, rang=rang, tur=tur, qism=qism,
            miqdor=float(miqdor), birlik=birlik,
        )
        db.add(product)
        await db.flush()
        log = WarehouseLog(
            product_id=product.id, user_id=user_id,
            amal="kirim", miqdor=float(miqdor),
            oldin=0.0, keyin=float(miqdor),
            izoh=izoh, work_entry_id=work_entry_id,
        )
        db.add(log)
        await db.flush()


# ── 11. ADYOL KAROBKA TIKISH ══════════════════════════════════════════════════
# Ishchi: tiger kesishdan kelgan qog'ozlarni adyol karobka shaklida tikadi
# Chiqim: yarim_tayyor (adyol_tikish_uchun)
# Kirim:  yarim_tayyor (adyol_qoqish_uchun) — qoqishga tayyor tikilgan karobkalar

async def adyol_tikish_ops(bot, db, data, user_id, work_entry_id):
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Adyol karobka"
    razmer = _str_or_none(data.get("razmer"))
    rang   = _str_or_none(data.get("rang"))
    src_id = data.get("src_product_id")

    src_qism = None
    if src_id:
        _sp = await db.get(WarehouseProduct, src_id)
        if _sp:
            src_qism = _sp.qism
            if _sp.name:   nomi   = _sp.name
            if _sp.razmer: razmer = _sp.razmer
            if _sp.rang:   rang   = _sp.rang
        # Yarim tayyordan (adyol_tikish_uchun) ayirish
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Adyol tikish: {nomi} {(src_qism or '').upper()} {razmer or ''}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Adyol tikish: material tanlanmadi (adyol_tikish_uchun)")

    # Tikilganlarni qoqish uchun yarim tayyorga — qism/razmer/rang SAQLANADI
    if soni > 0:
        await _kirim(
            db,
            category=ProductCategory.yarim_tayyor,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Adyol tikish tayyor → Qoqish uchun: {(src_qism or '').upper()} {razmer or '?'}",
            razmer=razmer,
            rang=rang,
            qism=src_qism,
            tur="adyol_qoqish_uchun",
            work_entry_id=work_entry_id,
        )
    return warns


# ── 12. DIPLOMAT PASTEL TIKISH ════════════════════════════════════════════════
# Ishchi: tiger kesishdan kelgan qog'ozlarni pastel karobka shaklida tikadi
# Chiqim: yarim_tayyor (pastel_tikish_uchun)
# Kirim:  yarim_tayyor (pastel_qoqish_uchun) — qoqishga tayyor tikilgan karobkalar

async def diplomat_tikish_ops(bot, db, data, user_id, work_entry_id):
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Pastel karobka"
    rang   = _str_or_none(data.get("rang"))
    razmer = _str_or_none(data.get("razmer"))
    src_id = data.get("src_product_id")

    src_qism = None
    if src_id:
        _sp = await db.get(WarehouseProduct, src_id)
        if _sp:
            src_qism = _sp.qism
            if _sp.name:   nomi   = _sp.name
            if _sp.razmer: razmer = _sp.razmer
            if getattr(_sp, "rang", None): rang = _sp.rang
    if src_id:
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Diplomat tikish: {nomi}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Diplomat tikish: material tanlanmadi (pastel_tikish_uchun)")

    if soni > 0:
        await _kirim(
            db,
            category=ProductCategory.yarim_tayyor,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Diplomat tikish tayyor → Qoqish uchun",
            rang=rang,
            qism=src_qism,
            tur="pastel_qoqish_uchun",
            work_entry_id=work_entry_id,
        )
    return warns


# ── 13. ADYOL KAROBKA QOQISH ══════════════════════════════════════════════════

async def adyol_qoqish_ops(bot, db, data, user_id, work_entry_id):
    """
    3 tur:
    - xom_komple: tikilgan karobkalarni qismlab qoqish (yon x2, tepa, past, remen)
    - kapalak:    xom komplelarni kapalak shaklida birlashtirish
    - yigish:     kapalakni yakunlash (tayyor mahsulot)
    """
    tur = _str_or_none(data.get("tur")) or "xom_komple"

    if tur == "xom_komple":
        return await _adyol_qoqish_xom(db, data, user_id, work_entry_id)
    elif tur == "kapalak":
        return await _adyol_qoqish_kapalak(db, data, user_id, work_entry_id)
    elif tur == "yigish":
        return await _adyol_qoqish_yigish(db, data, user_id, work_entry_id)
    else:
        logger.warning("Noma'lum adyol_qoqish tur: %s", tur)
        return [f"Noma'lum adyol qoqish turi: {tur}"]


async def _adyol_qoqish_xom(db, data, user_id, work_entry_id):
    """
    XOM qoqish: tikilgan karobkalarni (adyol_qoqish_uchun) qismlab qoqish.
    Chiqim: yarim_tayyor (adyol_qoqish_uchun) — tanlangan QISM
    Kirim:  yarim_tayyor (xom_komple) — XUDDI O'SHA qism/razmer/rang/nom bilan,
            shunda xom_komple ham ramka (qismli) ko'rinishda turadi.
    """
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Adyol xom komple"
    src_id = data.get("src_product_id")

    src_qism = src_razmer = src_rang = None
    if src_id:
        src = await db.get(WarehouseProduct, src_id)
        if src:
            # Natijaga manbaning xususiyatlarini ko'chiramiz
            nomi       = src.name or nomi
            src_qism   = src.qism
            src_razmer = src.razmer
            src_rang   = src.rang
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Adyol XOM qoqish: {nomi} {(src_qism or '').upper()}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Adyol XOM qoqish: tikilgan karobka tanlanmadi")

    if soni > 0:
        await _kirim(
            db,
            category=ProductCategory.yarim_tayyor,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Adyol XOM qoqish → Xom komple: {(src_qism or '').upper()} {soni} dona",
            razmer=src_razmer,
            rang=src_rang,
            qism=src_qism,
            tur="xom_komple",
            work_entry_id=work_entry_id,
        )
    return warns


async def _adyol_qoqish_kapalak(db, data, user_id, work_entry_id):
    """
    KAPALAK: xom komplelarni kapalak shaklida birlashtirish
    Grouped set bo'lsa (group_ids): barcha qismlardan ayiriladi
    Chiqim: yarim_tayyor (xom_komple) — har qism
    Kirim:  yarim_tayyor (kapalak) yoki tayyor_mahsulot
    """
    warns     = []
    soni      = _safe_int(data.get("soni", 0))
    nomi      = _str_or_none(data.get("mahsulot_nomi")) or "Adyol kapalak"
    is_tayyor = bool(data.get("is_tayyor", False))
    src_id    = data.get("src_product_id")
    group_ids = data.get("group_ids", [])

    # Grouped set — barcha qismlardan ayirish (1 komple: tepa −1, past −1, YON −2)
    if group_ids:
        for pid in group_ids:
            p = await db.get(WarehouseProduct, pid)
            need = soni * (2 if (p and (p.qism or "").lower() == "yon") else 1)
            qlbl = ((p.qism or "") if p else "").upper()
            w = await _chiqim(
                db, pid, need, user_id,
                f"Adyol kapalak: {nomi} {qlbl}, {need} dona ({soni} komple)",
                work_entry_id,
            )
            if w: warns.append(w)
    elif src_id:
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Adyol kapalak: {nomi}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Adyol kapalak: manba tanlanmadi")

    rang = _str_or_none(data.get("rang"))
    if soni > 0:
        if is_tayyor:
            # To'g'ridan tayyor mahsulotga
            await _kirim(
                db,
                category=ProductCategory.tayyor_mahsulot,
                name=nomi,
                miqdor=soni,
                user_id=user_id,
                izoh=f"Adyol kapalak → Tayyor mahsulot: {soni} dona",
                rang=rang,
                tur="adyol",
                work_entry_id=work_entry_id,
            )
        else:
            # Yarim tayyor (kapalak)
            await _kirim(
                db,
                category=ProductCategory.yarim_tayyor,
                name=nomi,
                miqdor=soni,
                user_id=user_id,
                izoh=f"Adyol kapalak → Yarim tayyor (kapalak): {soni} dona",
                rang=rang,
                tur="kapalak",
                work_entry_id=work_entry_id,
            )
    return warns


async def _adyol_qoqish_yigish(db, data, user_id, work_entry_id):
    """
    YIGISH: kapalakni yakunlash
    Chiqim: yarim_tayyor (kapalak)
    Kirim:  tayyor_mahsulot
    """
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Tayyor adyol"
    src_id = data.get("src_product_id")

    if src_id:
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Adyol yigish: {nomi}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Adyol yigish: kapalak tanlanmadi")

    if soni > 0:
        await _kirim(
            db,
            category=ProductCategory.tayyor_mahsulot,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Adyol yigish → Tayyor mahsulot: {soni} dona",
            tur="adyol",
            work_entry_id=work_entry_id,
        )
    return warns


# ── 14. PASTEL KAROBKA QOQISH ══════════════════════════════════════════════════

async def pastel_qoqish_ops(bot, db, data, user_id, work_entry_id):
    """
    3 tur (adyol ga o'xshash, lekin remen qismi yo'q):
    - xom_komple: tepa + past qoqish
    - kapalak:    birlashtirish
    - yigish:     yakunlash → tayyor mahsulot
    """
    tur = _str_or_none(data.get("tur")) or "xom_komple"

    if tur == "xom_komple":
        return await _pastel_qoqish_xom(db, data, user_id, work_entry_id)
    elif tur == "kapalak":
        return await _pastel_qoqish_kapalak(db, data, user_id, work_entry_id)
    elif tur == "yigish":
        return await _pastel_qoqish_yigish(db, data, user_id, work_entry_id)
    else:
        logger.warning("Noma'lum pastel_qoqish tur: %s", tur)
        return [f"Noma'lum pastel qoqish turi: {tur}"]


async def _pastel_qoqish_xom(db, data, user_id, work_entry_id):
    """
    XOM qoqish: pastel qismlarini qoqish.
    Chiqim: yarim_tayyor (pastel_qoqish_uchun) — tanlangan QISM
    Kirim:  yarim_tayyor (xom_komple) — xuddi o'sha qism/razmer/rang/nom bilan.
    """
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Pastel xom komple"
    src_id = data.get("src_product_id")

    src_qism = src_razmer = src_rang = None
    if src_id:
        src = await db.get(WarehouseProduct, src_id)
        if src:
            nomi       = src.name or nomi
            src_qism   = src.qism
            src_razmer = src.razmer
            src_rang   = src.rang
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Pastel XOM qoqish: {nomi} {(src_qism or '').upper()}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Pastel XOM qoqish: tikilgan pastel tanlanmadi")

    if soni > 0:
        await _kirim(
            db,
            category=ProductCategory.yarim_tayyor,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Pastel XOM qoqish → Xom komple: {(src_qism or '').upper()} {soni} dona",
            razmer=src_razmer,
            rang=src_rang,
            qism=src_qism,
            tur="xom_komple",
            work_entry_id=work_entry_id,
        )
    return warns


async def _pastel_qoqish_kapalak(db, data, user_id, work_entry_id):
    warns     = []
    soni      = _safe_int(data.get("soni", 0))
    nomi      = _str_or_none(data.get("mahsulot_nomi")) or "Pastel kapalak"
    is_tayyor = bool(data.get("is_tayyor", False))
    src_id    = data.get("src_product_id")
    group_ids = data.get("group_ids", [])

    if group_ids:
        for pid in group_ids:
            p = await db.get(WarehouseProduct, pid)
            need = soni * (2 if (p and (p.qism or "").lower() == "yon") else 1)
            qlbl = ((p.qism or "") if p else "").upper()
            w = await _chiqim(
                db, pid, need, user_id,
                f"Pastel kapalak: {nomi} {qlbl}, {need} dona ({soni} komple)",
                work_entry_id)
            if w: warns.append(w)
    elif src_id:
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Pastel kapalak: {nomi}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Pastel kapalak: manba tanlanmadi")

    if soni > 0:
        if is_tayyor:
            await _kirim(
                db,
                category=ProductCategory.tayyor_mahsulot,
                name=nomi,
                miqdor=soni,
                user_id=user_id,
                izoh=f"Pastel kapalak → Tayyor mahsulot: {soni} dona",
                tur="pastel",
                work_entry_id=work_entry_id,
            )
        else:
            await _kirim(
                db,
                category=ProductCategory.yarim_tayyor,
                name=nomi,
                miqdor=soni,
                user_id=user_id,
                izoh=f"Pastel kapalak → Yarim tayyor (kapalak): {soni} dona",
                tur="kapalak",
                work_entry_id=work_entry_id,
            )
    return warns


async def _pastel_qoqish_yigish(db, data, user_id, work_entry_id):
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Tayyor pastel"
    src_id = data.get("src_product_id")

    if src_id:
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Pastel yigish: {nomi}, {soni} dona",
            work_entry_id,
        )
        if w: warns.append(w)
    else:
        warns.append("Pastel yigish: kapalak tanlanmadi")

    if soni > 0:
        await _kirim(
            db,
            category=ProductCategory.tayyor_mahsulot,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Pastel yigish → Tayyor mahsulot: {soni} dona",
            tur="pastel",
            work_entry_id=work_entry_id,
        )
    return warns
