"""
warehouse_ops.py — v10 TUZATILGAN
TUZATISHLAR:
  1. Barcha ops: soni int() o'rniga float() — list_qogoz kg qabul qiladi
  2. gofra_ishlab_ops: rulon razmerini aniqroq olish
  3. list_qogoz_ops: rulon_soni data["soni"] bilan bir xil emas —
     rulon miqdori alohida saqlanadi (rulon_soni key bo'lishi shart)
     Agar rulon_soni yo'q bo'lsa, 1 dona rulon deb hisoblanadi
  4. rulon_orash_ops: output miqdori soni*2 emas, soni (rulon bo'lib chiqmaydi)
  5. _notify_admins: low stock threshold tekshiruvi to'g'rilandi
  6. adyol_tikish_ops va pastel_qoqish_ops:
     warehouse_ops_adyol moduliga delegate qilish to'g'ri
  7. _chiqim: actual == 0 tekshiruvi yanada aniq
  8. _kirim: birlik parametri xavfsiz uzatiladi
"""
import logging
from sqlalchemy import select
from database.models import (
    WarehouseProduct, WarehouseLog, ProductCategory, UserRole
)
from database.queries import (
    get_product_by_id, update_product_miqdor, get_users_by_role
)

logger = logging.getLogger(__name__)


# ═══ YORDAMCHI FUNKSIYALAR ════════════════════════════════════════════════════

async def _chiqim(
    db, product_id, miqdor, user_id, izoh, work_entry_id=None
) -> str | None:
    """Ombordan chiqim. Warn qaytaradi yoki None."""
    if not product_id:
        return "Mahsulot tanlanmagan — ombor ayirilmadi"

    p = await get_product_by_id(db, product_id)
    if not p:
        return f"Mahsulot topilmadi (id={product_id})"

    actual = float(p.miqdor)
    miqdor = float(miqdor)

    if actual <= 0:
        return f"{p.name}: omborda mahsulot qolmagan (0 {p.birlik})"

    if actual < miqdor:
        warn = (
            f"⚠️ {p.name}: so'ralgan {miqdor:.1f} {p.birlik}, "
            f"omborda faqat {actual:.1f} {p.birlik} — mavjud miqdor chiqildi."
        )
        logger.warning(
            "Ombor yetarli emas: %s (mavjud=%.1f, so'ralgan=%.1f)",
            p.name, actual, miqdor,
        )
        await update_product_miqdor(db, product_id, -actual, user_id, izoh, work_entry_id)
        return warn

    await update_product_miqdor(db, product_id, -miqdor, user_id, izoh, work_entry_id)
    return None


async def _kirim(
    db, category, name, miqdor, user_id, izoh,
    razmer=None, rang=None, tur=None, qalinlik=None,
    birlik="dona", yonalish=None, work_entry_id=None,
) -> None:
    """Omborga kirim. Mavjud bo'lsa yangilaydi, yo'q bo'lsa yaratadi."""
    razmer = _normalize_razmer(razmer)  # normallashtirish
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == category,
        WarehouseProduct.name == name,
        WarehouseProduct.is_active == True,
    )
    if razmer is not None: q = q.where(WarehouseProduct.razmer == razmer)
    if rang is not None:   q = q.where(WarehouseProduct.rang == rang)
    if tur is not None:    q = q.where(WarehouseProduct.tur == tur)

    r       = await db.execute(q.limit(1))
    product = r.scalar_one_or_none()

    if product:
        await update_product_miqdor(
            db, product.id, float(miqdor), user_id, izoh, work_entry_id
        )
    else:
        product = WarehouseProduct(
            category=category,
            name=name,
            razmer=razmer,
            rang=rang,
            tur=tur,
            miqdor=float(miqdor),
            birlik=birlik,
            yonalish=yonalish,
        )
        if qalinlik is not None:
            product.qalinlik = qalinlik
        db.add(product)
        await db.flush()
        log = WarehouseLog(
            product_id=product.id,
            user_id=user_id,
            amal="kirim",
            miqdor=float(miqdor),
            oldin=0.0,
            keyin=float(miqdor),
            izoh=izoh,
            work_entry_id=work_entry_id,
        )
        db.add(log)
        await db.flush()


async def _notify_admins(bot, db, text: str) -> None:
    """Admin va omborchilarga xabar yuborish."""
    try:
        targets = []
        for role in (UserRole.admin, UserRole.superadmin, UserRole.omborchi):
            targets.extend(await get_users_by_role(db, role))
        seen = set()
        for u in targets:
            if u.telegram_id in seen:
                continue
            seen.add(u.telegram_id)
            try:
                await bot.send_message(u.telegram_id, text)
            except Exception as e:
                logger.warning("Notify xatosi (tg_id=%s): %s", u.telegram_id, e)
    except Exception as e:
        logger.error("_notify_admins: %s", e)


def _str_or_none(val) -> str | None:
    if val is None or str(val).strip() == "":
        return None
    return str(val).strip()


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _normalize_razmer(val) -> str | None:
    """
    Razmer normalizatsiyasi:
    "90 x 110" → "90x110"
    " 90X110 " → "90x110"
    None → None
    """
    if val is None:
        return None
    s = str(val).strip().lower()
    if not s:
        return None
    # x atrofidagi bo'shliqlarni olib tashlash
    import re
    s = re.sub(r'\s*[xх×]\s*', 'x', s)  # har xil x belgilari → 'x'
    s = re.sub(r'\s+', ' ', s).strip()
    return s



# ═══ OPS FUNKSIYALARI ═════════════════════════════════════════════════════════

async def gofra_ishlab_ops(bot, db, data, user_id, work_entry_id):
    warns    = []
    soni     = _safe_int(data.get("soni", 0))
    tur      = _str_or_none(data.get("tur")) or "Yirik"
    razmer   = _str_or_none(data.get("razmer"))
    rulon_ops = data.get("rulon_ops") or []

    if not rulon_ops:
        warns.append("Go'fra ishlab: hech qanday rulon kiritilmadi!")

    for op in rulon_ops:
        pid = op.get("product_id")
        miq = _safe_int(op.get("miqdor", 0))
        if not pid or miq <= 0:
            continue
        # Razmer rulondan olish (agar hali olinmagan bo'lsa)
        if razmer is None:
            p = await get_product_by_id(db, pid)
            if p and p.razmer:
                razmer = p.razmer
        w = await _chiqim(
            db, pid, miq, user_id,
            f"Go'fra ishlab: {tur}, {miq} ta rulon",
            work_entry_id,
        )
        if w:
            warns.append(w)

    if soni > 0:
        gofra_nomi = f"Go'fra {tur.lower()}"
        if razmer:
            gofra_nomi += f" {razmer}"
        # TUZATILDI: gofra_ishlab → ProductCategory.gofra (katta varaqlar)
        # Zagatovkachi keyinchalik bularni kesadi → gofra_zagatovka bo'ladi
        await _kirim(
            db,
            category=ProductCategory.gofra,
            name=gofra_nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Go'fra ishlab: {tur}, {soni} top, razmer={razmer or '?'}",
            razmer=razmer,
            tur=tur,
            birlik="top",
            work_entry_id=work_entry_id,
        )
    return warns


async def laminatsiya_ops(bot, db, data, user_id, work_entry_id):
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    razmer = _str_or_none(data.get("razmer"))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Laminat mahsulot"
    dest   = _str_or_none(data.get("laminat_dest")) or "tiger"
    xrom_id = data.get("xromazes_product_id")

    if xrom_id:
        w = await _chiqim(
            db, xrom_id, soni, user_id,
            f"Laminatsiya: {nomi} {razmer or ''}, {soni} dona",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        await _notify_admins(bot, db, "⚠️ Laminatsiya uchun xromazes tanlanmadi!")
        warns.append("Xromazes tanlanmadi — ombor ayirilmadi")

    dest_tur_map = {
        "tiger": "tiger_uchun",
        "gofra": "gofra_kley_uchun",
        "boshqa": None,  # yarim_tayyor, tur=None (boshqa)
    }
    dest_tur   = dest_tur_map.get(dest, "tiger_uchun")
    dest_label = {"tiger": "Tiger kesish uchun", "gofra": "Go'fra kley uchun"}.get(dest, "Boshqa")

    # dest bo'yicha: boshqa → laminat omboriga, tiger/gofra → yarim_tayyor
    # Laminat xromazesga yonalish ham saqlanadi
    dest_yonalish = {
        "tiger": "tiger",
        "gofra": "zagatovka",
        "boshqa": None,
    }.get(dest)

    if dest == "boshqa":
        await _kirim(
            db,
            category=ProductCategory.laminat_xromazes,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Laminatsiya → laminat_xromazes ombori: {razmer or '?'}",
            razmer=razmer,
            yonalish=dest_yonalish,
            work_entry_id=work_entry_id,
        )
    elif dest == "tiger":
        # Tiger uchun: yarim_tayyor (tiger_uchun) ga
        await _kirim(
            db,
            category=ProductCategory.yarim_tayyor,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Laminatsiya → Tiger: {razmer or '?'}",
            razmer=razmer,
            tur="tiger_uchun",
            yonalish="tiger",
            work_entry_id=work_entry_id,
        )
    else:
        # Zagatovka uchun: laminat_xromazes ga yonalish=zagatovka bilan
        await _kirim(
            db,
            category=ProductCategory.laminat_xromazes,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Laminatsiya → Zagatovka chain: {razmer or '?'}",
            razmer=razmer,
            tur=dest_tur,
            yonalish="zagatovka",
            work_entry_id=work_entry_id,
        )
    return warns


async def zagatovka_ops(bot, db, data, user_id, work_entry_id):
    warns    = []
    soni     = _safe_int(data.get("soni", 0))
    nomi     = _str_or_none(data.get("mahsulot_nomi")) or "Zagatovka"
    razmer   = _str_or_none(data.get("razmer"))
    tur      = _str_or_none(data.get("tur")) or ""
    gofra_top = _safe_int(data.get("gofra_top_soni", 0)) or soni
    gofra_id  = data.get("gofra_product_id")

    if gofra_id:
        w = await _chiqim(
            db, gofra_id, gofra_top, user_id,
            f"Zagatovka kesish: {nomi} {razmer or ''} ({tur}), {gofra_top} top go'fra",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Go'fra tanlanmadi — ombor ayirilmadi")

    # TUZATILDI: zagatovka → ProductCategory.gofra_zagatovka
    # Nom va razmer xromazesdan olinadi (worker.py da saqlanadi)
    zag_nomi = nomi  # xromazes nomi (masalan: "Istanbul adyol tepa 60x40")
    if not nomi or nomi == "Zagatovka":
        zag_nomi = f"Zagatovka {razmer or ''} ({tur})"

    await _kirim(
        db,
        category=ProductCategory.gofra_zagatovka,
        name=zag_nomi,
        miqdor=soni,
        user_id=user_id,
        izoh=f"Zagatovka kesildi → Gofra kley uchun: {razmer or '?'}, {tur}",
        razmer=razmer,
        tur=tur,   # Yirik yoki Mayin — qaysi gofradan kesilganligini ko'rsatadi
        work_entry_id=work_entry_id,
    )
    return warns


async def gofra_kiley_ops(bot, db, data, user_id, work_entry_id):
    warns     = []
    soni      = _safe_int(data.get("soni", 0))
    razmer    = _str_or_none(data.get("razmer"))
    nomi      = _str_or_none(data.get("mahsulot_nomi")) or "Go'fra kley"
    sloy      = str(data.get("sloy", "3"))
    xrom_id   = data.get("xromazes_product_id")
    xrom_soni = _safe_int(data.get("xromazes_soni", 0)) or soni

    if xrom_id:
        w = await _chiqim(
            db, xrom_id, xrom_soni, user_id,
            f"Go'fra kiley xromazes: {nomi} {razmer or ''} {sloy}sloy",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Xromazes tanlanmadi — ombor ayirilmadi")

    zag_ops = data.get("zagatovka_ops") or []
    if not zag_ops:
        old_id = data.get("zagatovka_product_id")
        if old_id:
            zag_ops = [{"product_id": int(old_id), "miqdor": soni}]
    if not zag_ops:
        warns.append("Zagatovka tanlanmadi — ombor ayirilmadi")

    for op in zag_ops:
        pid = op.get("product_id")
        miq = _safe_int(op.get("miqdor", 0))
        if not pid or miq <= 0:
            continue
        w = await _chiqim(
            db, pid, miq, user_id,
            f"Go'fra kiley zagatovka: {nomi} {razmer or ''} {sloy}sloy",
            work_entry_id,
        )
        if w:
            warns.append(w)

    mahsulot_nomi = f"{nomi}"
    if razmer:
        mahsulot_nomi += f" {razmer}"
    mahsulot_nomi += f" {sloy}sloy"

    await _kirim(
        db,
        category=ProductCategory.yarim_tayyor,
        name=mahsulot_nomi,
        miqdor=soni,
        user_id=user_id,
        izoh=f"Go'fra kiley tayyor → Tiger: {razmer or '?'}, {sloy}sloy",
        razmer=razmer,
        tur="tiger_uchun",
        work_entry_id=work_entry_id,
    )
    return warns


async def tiger_kesish_ops(bot, db, data, user_id, work_entry_id):
    """
    Tiger kesish:
      - dest == "tayyor_mahsulot" → to'g'ridan tayyor_mahsulot ga
      - boshqa dest             → yarim_tayyor (tur=dest) ga
    """
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    razmer = _str_or_none(data.get("razmer"))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Kesilgan mahsulot"
    dest   = _str_or_none(data.get("dest_tur")) or "adyol_tikish_uchun"
    src_id = data.get("src_product_id")

    if src_id:
        w = await _chiqim(
            db, src_id, soni, user_id,
            f"Tiger kesish: {nomi} {razmer or ''}, {soni} dona",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Tiger kesish: material tanlanmadi — ombor ayirilmadi")

    if dest == "tayyor_mahsulot":
        # To'g'ridan tayyor mahsulotga (qisqa zanjir)
        await _kirim(
            db,
            category=ProductCategory.tayyor_mahsulot,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Tiger kesish → Tayyor mahsulot: {razmer or '?'}, {soni} dona",
            razmer=razmer,
            work_entry_id=work_entry_id,
        )
    else:
        # Yarim tayyor bo'limiga (tikish, stepler, yopish uchun)
        await _kirim(
            db,
            category=ProductCategory.yarim_tayyor,
            name=nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"Tiger kesishdan: {razmer or '?'} → {dest}",
            razmer=razmer,
            tur=dest,
            work_entry_id=work_entry_id,
        )
    return warns


async def list_qogoz_ops(bot, db, data, user_id, work_entry_id):
    warns    = []
    # TUZATILDI: list_qogoz kg da to'lanadi — float ishlatish
    soni     = _safe_float(data.get("soni", 0))
    razmer   = _str_or_none(data.get("razmer"))
    dest_tur = _str_or_none(data.get("dest_tur")) or "tiger_uchun"

    rulon_id = data.get("rulon_product_id")
    if rulon_id:
        # TUZATILDI: rulon_soni — 1 dona rulon chiqariladi (bo'linmaydi)
        rulon_miq = _safe_int(data.get("rulon_soni", 1))
        if rulon_miq <= 0:
            rulon_miq = 1
        w = await _chiqim(
            db, rulon_id, rulon_miq, user_id,
            f"List qog'oz kesish: {razmer or '?'}, {soni}kg",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("List kesish: rulon tanlanmadi — ombor ayirilmadi")

    list_nomi = f"List {razmer or ''}".strip()

    # Destinatsiyaga qarab omborga qo'shish
    if dest_tur == "xromazes":
        await _kirim(
            db,
            category=ProductCategory.xromazes,
            name=list_nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"List kesdi → Xromazes ombori: {razmer or '?'} {soni}kg",
            razmer=razmer,
            birlik="kg",
            work_entry_id=work_entry_id,
        )
    elif dest_tur == "tayyor_mahsulot":
        await _kirim(
            db,
            category=ProductCategory.tayyor_mahsulot,
            name=list_nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"List kesdi → Tayyor mahsulotlar: {razmer or '?'} {soni}kg",
            razmer=razmer,
            birlik="kg",
            work_entry_id=work_entry_id,
        )
    else:
        # Yarim tayyor: tiger_uchun, yopish_uchun, adyol_tikish_uchun, pastel_tikish_uchun
        await _kirim(
            db,
            category=ProductCategory.yarim_tayyor,
            name=list_nomi,
            miqdor=soni,
            user_id=user_id,
            izoh=f"List kesdi: {razmer or '?'} {soni}kg → {dest_tur}",
            razmer=razmer,
            tur=dest_tur,
            birlik="kg",
            work_entry_id=work_entry_id,
        )
    return warns


async def stepler_tikish_ops(bot, db, data, user_id, work_entry_id):
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    razmer = _str_or_none(data.get("razmer"))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Stepler mahsulot"
    src_id = data.get("src_product_id")

    chiqim_soni = soni * 2  # 2 qism birga tikiladi → 1 tayyor mahsulot
    if src_id:
        w = await _chiqim(
            db, src_id, chiqim_soni, user_id,
            f"Stepler tikish: {nomi} {razmer or ''}, {soni} dona ({chiqim_soni} qism)",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Stepler tikish: material tanlanmadi — ombor ayirilmadi")

    await _kirim(
        db,
        category=ProductCategory.tayyor_mahsulot,
        name=nomi,
        miqdor=soni,
        user_id=user_id,
        izoh=f"Stepler tikish tayyor: {razmer or '?'}, {soni} dona",
        razmer=razmer,
        work_entry_id=work_entry_id,
    )
    return warns


async def rulon_orash_ops(bot, db, data, user_id, work_entry_id):
    warns    = []
    soni     = _safe_int(data.get("soni", 0))
    razmer   = _str_or_none(data.get("razmer"))
    nomi     = _str_or_none(data.get("mahsulot_nomi")) or "Rulon"
    rulon_id = data.get("rulon_product_id")

    if rulon_id:
        w = await _chiqim(
            db, rulon_id, soni, user_id,
            f"Rulon o'rash: {razmer or '?'}, {soni} rulon",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Rulon o'rash: rulon tanlanmadi — ombor ayirilmadi")

    # TUZATILDI: 1 rulon → 2 bo'lak (half-rulon)
    oralgan_soni = soni * 2
    oralgan_nomi = f"{nomi} (o'ralgan)"
    if razmer:
        oralgan_nomi = f"Rulon {razmer} (o'ralgan)"

    await _kirim(
        db,
        category=ProductCategory.rulon,
        name=oralgan_nomi,
        miqdor=oralgan_soni,
        user_id=user_id,
        izoh=f"Rulon o'rash: {soni} rulon → {oralgan_soni} bo'lak",
        razmer=razmer,
        tur="oralgan",
        birlik="rulon",
        work_entry_id=work_entry_id,
    )
    return warns


async def rulonga_salafan_ops(bot, db, data, user_id, work_entry_id):
    warns      = []
    soni       = _safe_int(data.get("soni", 0))
    razmer     = _str_or_none(data.get("razmer"))
    rang       = _str_or_none(data.get("rang"))
    rulon_id   = data.get("rulon_product_id")
    salafan_id = data.get("salafan_product_id")
    nomi       = _str_or_none(data.get("mahsulot_nomi")) or "Rulon"

    if rulon_id:
        w = await _chiqim(
            db, rulon_id, soni, user_id,
            f"Rulonga salafan: rulon {razmer or '?'}, {soni} dona",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Rulonga salafan: rulon tanlanmadi")

    if salafan_id:
        w = await _chiqim(
            db, salafan_id, soni, user_id,
            f"Rulonga salafan: salafan {rang or '?'}, {soni} dona",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Rulonga salafan: salafan tanlanmadi")

    salafanli_nomi = f"Rulon {razmer or ''} (salafanli)".strip()

    await _kirim(
        db,
        category=ProductCategory.rulon,
        name=salafanli_nomi,
        miqdor=soni,
        user_id=user_id,
        izoh=f"Salafan o'ralgan rulon: {rang or '?'}, {razmer or '?'}",
        razmer=razmer,
        rang=rang,
        tur="salafanli",
        birlik="rulon",
        work_entry_id=work_entry_id,
    )
    return warns


async def yopishtirma_ops(bot, db, data, user_id, work_entry_id):
    warns  = []
    soni   = _safe_int(data.get("soni", 0))
    razmer = _str_or_none(data.get("razmer"))
    nomi   = _str_or_none(data.get("mahsulot_nomi")) or "Yopishtirilgan"
    src_id = data.get("src_product_id")

    chiqim_soni = soni * 2  # 2 qism birga yopishtiriladi → 1 tayyor mahsulot
    if src_id:
        w = await _chiqim(
            db, src_id, chiqim_soni, user_id,
            f"Yopishtirma: {nomi} {razmer or ''}, {soni} dona ({chiqim_soni} qism)",
            work_entry_id,
        )
        if w:
            warns.append(w)
    else:
        warns.append("Yopishtirma: material tanlanmadi — ombor ayirilmadi")

    await _kirim(
        db,
        category=ProductCategory.tayyor_mahsulot,
        name=nomi,
        miqdor=soni,
        user_id=user_id,
        izoh=f"Yopishtirma tayyor: {razmer or '?'}, {soni} dona",
        razmer=razmer,
        work_entry_id=work_entry_id,
    )
    return warns


# ═══ ADYOL/PASTEL — warehouse_ops_adyol.py ga delegate ════════════════════════

async def adyol_tikish_ops(bot, db, data, user_id, work_entry_id):
    try:
        from utils.warehouse_ops_adyol import adyol_tikish_ops as _fn
        return await _fn(bot, db, data, user_id, work_entry_id)
    except ImportError as e:
        logger.error("warehouse_ops_adyol import xatosi: %s", e)
        return [f"Adyol tikish ombor operatsiyasi bajarilmadi: {e}"]


async def diplomat_tikish_ops(bot, db, data, user_id, work_entry_id):
    try:
        from utils.warehouse_ops_adyol import diplomat_tikish_ops as _fn
        return await _fn(bot, db, data, user_id, work_entry_id)
    except ImportError as e:
        logger.error("warehouse_ops_adyol import xatosi: %s", e)
        return [f"Diplomat tikish ombor operatsiyasi bajarilmadi: {e}"]


async def adyol_qoqish_ops(bot, db, data, user_id, work_entry_id):
    try:
        from utils.warehouse_ops_adyol import adyol_qoqish_ops as _fn
        return await _fn(bot, db, data, user_id, work_entry_id)
    except ImportError as e:
        logger.error("warehouse_ops_adyol import xatosi: %s", e)
        return [f"Adyol qoqish ombor operatsiyasi bajarilmadi: {e}"]


async def pastel_qoqish_ops(bot, db, data, user_id, work_entry_id):
    try:
        from utils.warehouse_ops_adyol import pastel_qoqish_ops as _fn
        return await _fn(bot, db, data, user_id, work_entry_id)
    except ImportError as e:
        logger.error("warehouse_ops_adyol import xatosi: %s", e)
        return [f"Pastel qoqish ombor operatsiyasi bajarilmadi: {e}"]


# ═══ DISPATCHER ═══════════════════════════════════════════════════════════════

OPS_MAP = {
    "tiger_kesish":    tiger_kesish_ops,
    "gofra_kiley":     gofra_kiley_ops,
    "gofra_ishlab":    gofra_ishlab_ops,
    "list_qogoz":      list_qogoz_ops,
    "laminatsiya":     laminatsiya_ops,
    "zagatovka":       zagatovka_ops,
    "stepler_tikish":  stepler_tikish_ops,
    "rulon_orash":     rulon_orash_ops,
    "rulonga_salafan": rulonga_salafan_ops,
    "yopishtirma":     yopishtirma_ops,
    "adyol_tikish":    adyol_tikish_ops,
    "diplomat_tikish": diplomat_tikish_ops,
    "adyol_qoqish":    adyol_qoqish_ops,
    "pastel_qoqish":   pastel_qoqish_ops,
}


async def run_warehouse_ops(
    bot, db, work_type: str, data: dict, user_id: int, work_entry_id: int
) -> list:
    fn = OPS_MAP.get(work_type)
    if not fn:
        logger.warning("Noma'lum work_type: %s", work_type)
        return []
    try:
        result = await fn(bot, db, data, user_id, work_entry_id)
        return result or []
    except Exception as e:
        logger.error(
            "Ombor ops xato (work_type=%s): %s", work_type, e, exc_info=True
        )
        return [f"Ombor operatsiyasida xato: {e}"]
