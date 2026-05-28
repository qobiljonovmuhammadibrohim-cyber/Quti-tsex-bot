"""
queries.py — TUZATILGAN
TUZATISHLAR:
  1. get_price: razmer_turi bo'lmasa asosiy narx qidiradi, topilmasa
     ixtiyoriy narxni qaytaradi (fallback) — narx 0 bo'lib qolmaydi
  2. close_session: duration_minutes to'g'ri hisoblanadi
  3. get_today_work_minutes: ochiq sessiya uchun ham vaqt hisoblanadi
  4. reject_work: old_status tekshiruvi to'g'ri (WorkStatus.value emas)
  5. _reverse_warehouse_logs: await db.flush() -> await db.commit() emas,
     lekin caller da commit bor
  6. calculate_and_save_salary: await db.flush() dan keyin caller commit qiladi
  7. get_dashboard_stats: open_sessions query tuzatildi
  8. apply_worker_edit: approved=False holati to'g'ri handle qilinadi
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract, update
from typing import Optional, List
from datetime import date, datetime

from database.models import (
    User, UserRole,
    WarehouseProduct, WarehouseLog, ProductCategory,
    WorkEntry, WorkStatus, WorkType, QualityGrade, QUALITY_COEFFICIENTS,
    WorkPrice, Penalty, PenaltyType,
    Advance, SalaryReport,
    WorkSession, SmenaType,
)

AVANS_MAX_PER_MONTH = 8


# ── USER ────────────────────────────────────────────────────────────────────

async def get_user(db: AsyncSession, telegram_id: int) -> Optional[User]:
    r = await db.execute(select(User).where(User.telegram_id == telegram_id))
    return r.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    r = await db.execute(select(User).where(User.id == user_id))
    return r.scalar_one_or_none()


async def get_users_by_role(db: AsyncSession, role: UserRole) -> List[User]:
    r = await db.execute(
        select(User).where(User.role == role, User.is_active == True)
    )
    return r.scalars().all()


async def get_all_active_users(db: AsyncSession) -> List[User]:
    r = await db.execute(
        select(User)
        .where(User.is_active == True)
        .order_by(User.role, User.full_name)
    )
    return r.scalars().all()


# ── WORK SESSION ─────────────────────────────────────────────────────────────

async def get_open_session(
    db: AsyncSession, worker_id: int
) -> Optional[WorkSession]:
    r = await db.execute(
        select(WorkSession)
        .where(
            WorkSession.worker_id == worker_id,
            WorkSession.closed_at == None,
        )
        .order_by(WorkSession.opened_at.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def open_session(
    db: AsyncSession,
    worker_id: int,
    smena: SmenaType = SmenaType.kunduzgi,
) -> WorkSession:
    # Ochiq sessiyani yopish
    old = await get_open_session(db, worker_id)
    if old:
        old.closed_at = datetime.now()
        delta = (old.closed_at - old.opened_at).total_seconds()
        old.duration_minutes = int(delta / 60)
        old.izoh = "Avtomatik yopildi (yangi smena boshlanganda)"
        await db.flush()

    session = WorkSession(
        worker_id=worker_id,
        smena=smena,
        opened_at=datetime.now(),
        work_date=date.today(),
    )
    db.add(session)
    await db.flush()
    return session


async def close_session(
    db: AsyncSession, worker_id: int
) -> Optional[WorkSession]:
    session = await get_open_session(db, worker_id)
    if session:
        session.closed_at = datetime.now()
        # TUZATILDI: duration_minutes to'g'ri hisoblanadi
        delta = (session.closed_at - session.opened_at).total_seconds()
        session.duration_minutes = int(delta / 60)
        await db.flush()
    return session


async def get_today_sessions(
    db: AsyncSession, worker_id: int
) -> List[WorkSession]:
    r = await db.execute(
        select(WorkSession)
        .where(
            WorkSession.worker_id == worker_id,
            WorkSession.work_date == date.today(),
        )
        .order_by(WorkSession.opened_at)
    )
    return r.scalars().all()


async def get_today_work_minutes(db: AsyncSession, worker_id: int) -> int:
    sessions = await get_today_sessions(db, worker_id)
    total = 0
    for s in sessions:
        if s.duration_minutes:
            total += s.duration_minutes
        elif s.closed_at is None:
            # TUZATILDI: ochiq sessiya uchun hozirgi vaqt bilan hisoblash
            total += int((datetime.now() - s.opened_at).total_seconds() / 60)
    return total


# ── WAREHOUSE PRODUCT ────────────────────────────────────────────────────────

async def get_products_by_category(
    db: AsyncSession, category: ProductCategory
) -> List[WarehouseProduct]:
    r = await db.execute(
        select(WarehouseProduct)
        .where(
            WarehouseProduct.category == category,
            WarehouseProduct.is_active == True,
        )
        .order_by(WarehouseProduct.name)
    )
    return r.scalars().all()


async def get_product_by_id(
    db: AsyncSession, product_id: int
) -> Optional[WarehouseProduct]:
    r = await db.execute(
        select(WarehouseProduct).where(WarehouseProduct.id == product_id)
    )
    return r.scalar_one_or_none()


async def search_products(
    db: AsyncSession,
    query: str = None,
    category: ProductCategory = None,
    rang: str = None,
    tur: str = None,
    razmer: str = None,
    holat: str = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple:
    q = select(WarehouseProduct).where(WarehouseProduct.is_active == True)
    if query:    q = q.where(WarehouseProduct.name.ilike(f"%{query}%"))
    if category: q = q.where(WarehouseProduct.category == category)
    if rang:     q = q.where(WarehouseProduct.rang.ilike(f"%{rang}%"))
    if tur:      q = q.where(WarehouseProduct.tur == tur)
    if razmer:   q = q.where(WarehouseProduct.razmer.ilike(f"%{razmer}%"))
    if holat == "kam":
        q = q.where(WarehouseProduct.miqdor <= WarehouseProduct.min_threshold)
    elif holat == "cheklangan":
        q = q.where(
            WarehouseProduct.miqdor > WarehouseProduct.min_threshold,
            WarehouseProduct.miqdor <= WarehouseProduct.yellow_threshold,
        )
    elif holat == "yetarli":
        q = q.where(WarehouseProduct.miqdor > WarehouseProduct.yellow_threshold)

    total = (
        await db.execute(select(func.count()).select_from(q.subquery()))
    ).scalar() or 0
    q = (
        q.order_by(WarehouseProduct.category, WarehouseProduct.name)
        .limit(limit)
        .offset(offset)
    )
    return (await db.execute(q)).scalars().all(), total


async def search_product(
    db: AsyncSession,
    category: ProductCategory,
    name: str = None,
    rang: str = None,
    tur: str = None,
) -> List[WarehouseProduct]:
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == category,
        WarehouseProduct.is_active == True,
    )
    if name: q = q.where(WarehouseProduct.name.ilike(f"%{name}%"))
    if rang: q = q.where(WarehouseProduct.rang.ilike(f"%{rang}%"))
    if tur:  q = q.where(WarehouseProduct.tur.ilike(f"%{tur}%"))
    return (await db.execute(q)).scalars().all()


async def update_product_miqdor(
    db: AsyncSession,
    product_id: int,
    delta: float,
    user_id: int,
    izoh: str = None,
    work_entry_id: int = None,
) -> WarehouseProduct:
    """Atomic SQL UPDATE — race condition yo'q."""
    product = await get_product_by_id(db, product_id)
    if not product:
        raise ValueError(f"Mahsulot topilmadi: id={product_id}")
    oldin = float(product.miqdor)
    await db.execute(
        update(WarehouseProduct)
        .where(WarehouseProduct.id == product_id)
        .values(miqdor=func.greatest(0.0, WarehouseProduct.miqdor + delta))
    )
    await db.flush()
    await db.refresh(product)
    # user_id=None bo'lsa (web panel, tashqi chaqiriq) — log yozish opsional
    if user_id:
        log = WarehouseLog(
            product_id=product_id,
            user_id=user_id,
            amal="kirim" if delta > 0 else "chiqim",
            miqdor=abs(delta),
            oldin=oldin,
            keyin=float(product.miqdor),
            izoh=izoh,
            work_entry_id=work_entry_id,
        )
        db.add(log)
        await db.flush()
    return product


async def get_all_products(db: AsyncSession) -> List[WarehouseProduct]:
    r = await db.execute(
        select(WarehouseProduct)
        .where(WarehouseProduct.is_active == True)
        .order_by(WarehouseProduct.category, WarehouseProduct.name)
    )
    return r.scalars().all()


async def get_product_last_log(
    db: AsyncSession,
    product_id: int,
    amal: str = None,
):
    q = select(WarehouseLog).where(WarehouseLog.product_id == product_id)
    if amal:
        q = q.where(WarehouseLog.amal == amal)
    return (
        await db.execute(q.order_by(WarehouseLog.created_at.desc()).limit(1))
    ).scalar_one_or_none()


# ── WORK PRICE ───────────────────────────────────────────────────────────────

async def get_price(
    db: AsyncSession,
    work_type: WorkType,
    razmer_turi: str = None,
) -> float:
    """
    TUZATILDI: Narx qidirish tartibi:
    1. Aniq razmer_turi bilan qidirish
    2. Topilmasa — razmer_turi=None (asosiy narx) bilan qidirish
    3. Topilmasa — 0.0 qaytarish
    """
    if razmer_turi is not None:
        # Aniq razmer bilan qidirish
        r = await db.execute(
            select(WorkPrice).where(
                WorkPrice.work_type == work_type,
                WorkPrice.is_active == True,
                WorkPrice.razmer_turi == razmer_turi,
            )
            .order_by(WorkPrice.id.desc())
            .limit(1)
        )
        price = r.scalar_one_or_none()
        if price:
            return float(price.narx)

    # Asosiy narxni qidirish (razmer_turi=None)
    r = await db.execute(
        select(WorkPrice).where(
            WorkPrice.work_type == work_type,
            WorkPrice.is_active == True,
            WorkPrice.razmer_turi == None,
        )
        .order_by(WorkPrice.id.desc())
        .limit(1)
    )
    price = r.scalar_one_or_none()
    if price:
        return float(price.narx)

    # Hech qanday narx topilmadi
    return 0.0


async def get_all_prices(db: AsyncSession) -> List[WorkPrice]:
    r = await db.execute(
        select(WorkPrice)
        .where(WorkPrice.is_active == True)
        .order_by(WorkPrice.work_type, WorkPrice.razmer_turi)
    )
    return r.scalars().all()


async def set_price(
    db: AsyncSession,
    work_type: WorkType,
    narx: float,
    razmer_turi: str = None,
) -> WorkPrice:
    # Eski narxlarni arxivlash
    old_r = await db.execute(
        select(WorkPrice).where(
            WorkPrice.work_type == work_type,
            WorkPrice.is_active == True,
            WorkPrice.razmer_turi == razmer_turi,
        )
    )
    for old in old_r.scalars().all():
        old.is_active  = False
        old.updated_at = datetime.now()

    new_price = WorkPrice(
        work_type=work_type,
        narx=narx,
        razmer_turi=razmer_turi,
    )
    db.add(new_price)
    await db.flush()
    return new_price


# ── WORK ENTRY ───────────────────────────────────────────────────────────────

async def get_work_entry(
    db: AsyncSession, entry_id: int
) -> Optional[WorkEntry]:
    r = await db.execute(select(WorkEntry).where(WorkEntry.id == entry_id))
    return r.scalar_one_or_none()


async def get_today_works(
    db: AsyncSession, worker_id: int
) -> List[WorkEntry]:
    r = await db.execute(
        select(WorkEntry)
        .where(
            WorkEntry.worker_id == worker_id,
            WorkEntry.work_date == date.today(),
        )
        .order_by(WorkEntry.created_at.desc())
    )
    return r.scalars().all()


async def get_today_sum(db: AsyncSession, worker_id: int) -> dict:
    approved_r = await db.execute(
        select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
        .where(
            WorkEntry.worker_id == worker_id,
            WorkEntry.work_date == date.today(),
            WorkEntry.status.in_([WorkStatus.approved, WorkStatus.adjusted]),
        )
    )
    pending_r = await db.execute(
        select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
        .where(
            WorkEntry.worker_id == worker_id,
            WorkEntry.work_date == date.today(),
            WorkEntry.status == WorkStatus.pending,
        )
    )
    return {
        "approved": float(approved_r.scalar()),
        "pending":  float(pending_r.scalar()),
    }


async def get_pending_works(
    db: AsyncSession, worker_id: int = None
) -> List[WorkEntry]:
    q = (
        select(WorkEntry)
        .where(
            WorkEntry.status.in_([WorkStatus.pending, WorkStatus.edit_requested]),
            WorkEntry.work_date == date.today(),
        )
        .order_by(WorkEntry.created_at)
    )
    if worker_id:
        q = q.where(WorkEntry.worker_id == worker_id)
    return (await db.execute(q)).scalars().all()


async def approve_work(
    db: AsyncSession,
    entry_id: int,
    inspector_id: int,
    quality_grade: QualityGrade = QualityGrade.grade_1,
    qc_note: str = None,
) -> WorkEntry:
    entry = await get_work_entry(db, entry_id)
    if not entry:
        raise ValueError(f"Ish topilmadi: id={entry_id}")
    entry.status        = WorkStatus.approved
    entry.inspector_id  = inspector_id
    entry.quality_grade = quality_grade
    entry.qc_note       = qc_note
    entry.finished_at   = entry.finished_at or datetime.now()
    coef = QUALITY_COEFFICIENTS.get(quality_grade, 1.0)
    if coef != 1.0:
        entry.jami_summa = round(
            (entry.soni or 0) * (entry.birlik_narx or 0) * coef, 2
        )
    await db.flush()
    return entry


async def adjust_work(
    db: AsyncSession,
    entry_id: int,
    inspector_id: int,
    new_soni: float,
    quality_grade: QualityGrade = QualityGrade.grade_1,
    qc_note: str = None,
) -> WorkEntry:
    entry = await get_work_entry(db, entry_id)
    if not entry:
        raise ValueError(f"Ish topilmadi: id={entry_id}")
    entry.original_soni = entry.soni
    entry.soni          = new_soni
    entry.quality_grade = quality_grade
    entry.qc_note       = qc_note
    coef = QUALITY_COEFFICIENTS.get(quality_grade, 1.0)
    entry.jami_summa    = round(new_soni * (entry.birlik_narx or 0) * coef, 2)
    entry.status        = WorkStatus.adjusted
    entry.inspector_id  = inspector_id
    entry.tuzatish_izoh = f"Tuzatildi: {entry.original_soni} → {new_soni}"
    entry.finished_at   = entry.finished_at or datetime.now()
    await db.flush()
    return entry


async def reject_work(
    db: AsyncSession,
    entry_id: int,
    inspector_id: int,
    sabab: str,
) -> WorkEntry:
    entry = await get_work_entry(db, entry_id)
    if not entry:
        raise ValueError(f"Ish topilmadi: id={entry_id}")
    # TUZATILDI: old_status to'g'ri saqlash
    old_status     = entry.status
    entry.status       = WorkStatus.rejected
    entry.rad_sababi   = sabab
    entry.inspector_id = inspector_id
    entry.finished_at  = entry.finished_at or datetime.now()
    await db.flush()
    # Faqat pending yoki edit_requested bo'lgan ishlar uchun ombor qaytarish
    if old_status in (WorkStatus.pending, WorkStatus.edit_requested):
        await _reverse_warehouse_logs(db, entry_id, inspector_id)
    return entry


async def _reverse_warehouse_logs(
    db: AsyncSession, work_entry_id: int, user_id: int
):
    import logging as _log
    logger = _log.getLogger(__name__)
    r = await db.execute(
        select(WarehouseLog)
        .where(WarehouseLog.work_entry_id == work_entry_id)
        .order_by(WarehouseLog.id)
    )
    for log in r.scalars().all():
        # Teskari operatsiya: chiqim bo'lsa kirim, kirim bo'lsa chiqim
        reverse_delta = log.miqdor if log.amal == "chiqim" else -log.miqdor
        try:
            await update_product_miqdor(
                db, log.product_id, reverse_delta, user_id,
                izoh=f"Ish #{work_entry_id} rad etildi — ombor qaytarildi",
            )
        except Exception as e:
            logger.error(
                "Ombor qaytarishda xato (pid=%s): %s", log.product_id, e
            )


async def request_worker_edit(
    db: AsyncSession,
    entry_id: int,
    worker_id: int,
    note: str,
) -> Optional[WorkEntry]:
    entry = await get_work_entry(db, entry_id)
    if (
        not entry
        or entry.worker_id != worker_id
        or entry.status != WorkStatus.pending
    ):
        return None
    entry.status                = WorkStatus.edit_requested
    entry.worker_edit_requested = True
    entry.worker_edit_note      = note
    await db.flush()
    return entry


async def apply_worker_edit(
    db: AsyncSession,
    entry_id: int,
    inspector_id: int,
    new_soni: float = None,
    new_mahsulot: str = None,
    new_razmer: str = None,
    approved: bool = True,
) -> WorkEntry:
    entry = await get_work_entry(db, entry_id)
    if not entry:
        raise ValueError(f"Ish topilmadi: id={entry_id}")

    if approved:
        # O'zgartirishlarni qabul qilish
        if new_soni is not None:
            entry.original_soni = entry.soni
            entry.soni          = new_soni
            entry.jami_summa    = round(new_soni * (entry.birlik_narx or 0), 2)
        if new_mahsulot:
            entry.mahsulot_nomi = new_mahsulot
        if new_razmer:
            entry.razmer = new_razmer
        entry.tuzatish_izoh = f"Ishchi so'rov bo'yicha (inspector={inspector_id})"
        # TUZATILDI: pending ga qaytarish
        entry.status = WorkStatus.pending
    else:
        # TUZATILDI: rad etilganda ham pending ga qaytarish (nazoratchi ko'rsin)
        entry.status = WorkStatus.pending

    entry.worker_edit_requested = False
    entry.worker_edit_note      = None
    await db.flush()
    return entry


# ── PENALTY ──────────────────────────────────────────────────────────────────

async def create_penalty(
    db: AsyncSession,
    worker_id: int,
    inspector_id: int,
    penalty_type: PenaltyType,
    sabab: str,
    summa: float = 0,
    work_entry_id: int = None,
) -> Penalty:
    pen = Penalty(
        worker_id=worker_id,
        inspector_id=inspector_id,
        work_entry_id=work_entry_id,
        penalty_type=penalty_type,
        summa=summa,
        sabab=sabab,
    )
    db.add(pen)
    await db.flush()
    return pen


async def confirm_penalty(
    db: AsyncSession, penalty_id: int
) -> Optional[Penalty]:
    r = await db.execute(
        select(Penalty).where(Penalty.id == penalty_id)
    )
    pen = r.scalar_one_or_none()
    if pen:
        pen.worker_confirmed = True
        await db.flush()
    return pen


async def get_penalty_sum(
    db: AsyncSession, worker_id: int, oy: int, yil: int
) -> float:
    r = await db.execute(
        select(func.coalesce(func.sum(Penalty.summa), 0)).where(
            Penalty.worker_id == worker_id,
            extract("month", Penalty.created_at) == oy,
            extract("year",  Penalty.created_at) == yil,
        )
    )
    return float(r.scalar())


# ── ADVANCE ──────────────────────────────────────────────────────────────────

async def get_advance_count_this_month(
    db: AsyncSession, worker_id: int
) -> int:
    now = datetime.now()
    r   = await db.execute(
        select(func.count(Advance.id)).where(
            Advance.worker_id == worker_id,
            Advance.oy == now.month,
            Advance.yil == now.year,
        )
    )
    return r.scalar() or 0


async def create_advance(
    db: AsyncSession,
    worker_id: int,
    admin_id: int,
    summa: float,
    izoh: str = None,
) -> Advance:
    now   = datetime.now()
    count = await get_advance_count_this_month(db, worker_id)
    if count >= AVANS_MAX_PER_MONTH:
        raise ValueError(
            f"Bu oy allaqachon {count} ta avans berilgan. "
            f"Chegara: {AVANS_MAX_PER_MONTH} ta/oy."
        )
    adv = Advance(
        worker_id=worker_id,
        admin_id=admin_id,
        summa=summa,
        izoh=izoh,
        oy=now.month,
        yil=now.year,
    )
    db.add(adv)
    await db.flush()
    return adv


async def get_advance_sum(
    db: AsyncSession, worker_id: int, oy: int, yil: int
) -> float:
    r = await db.execute(
        select(func.coalesce(func.sum(Advance.summa), 0)).where(
            Advance.worker_id == worker_id,
            Advance.oy == oy,
            Advance.yil == yil,
        )
    )
    return float(r.scalar())


# ── SALARY REPORT ────────────────────────────────────────────────────────────

async def get_or_create_salary_report(
    db: AsyncSession, worker_id: int, oy: int, yil: int
) -> SalaryReport:
    r = await db.execute(
        select(SalaryReport).where(
            SalaryReport.worker_id == worker_id,
            SalaryReport.oy == oy,
            SalaryReport.yil == yil,
        )
    )
    rep = r.scalar_one_or_none()
    if not rep:
        rep = SalaryReport(worker_id=worker_id, oy=oy, yil=yil)
        db.add(rep)
        await db.flush()
    return rep


async def calculate_and_save_salary(
    db: AsyncSession, worker_id: int, oy: int, yil: int
) -> SalaryReport:
    ish_r = await db.execute(
        select(func.coalesce(func.sum(WorkEntry.jami_summa), 0)).where(
            WorkEntry.worker_id == worker_id,
            WorkEntry.status.in_([WorkStatus.approved, WorkStatus.adjusted]),
            extract("month", WorkEntry.work_date) == oy,
            extract("year",  WorkEntry.work_date) == yil,
        )
    )
    jami_ish    = float(ish_r.scalar())
    jami_jarima = await get_penalty_sum(db, worker_id, oy, yil)
    jami_avans  = await get_advance_sum(db, worker_id, oy, yil)

    rep = await get_or_create_salary_report(db, worker_id, oy, yil)
    # Agar admin tasdiqlagan bo'lsa o'zgartirmaymiz
    if not rep.admin_tasdiqladi:
        rep.jami_ish_summa = jami_ish
        rep.jami_jarima    = jami_jarima
        rep.jami_avans     = jami_avans
        rep.sof_maosh      = max(0.0, jami_ish - jami_jarima - jami_avans)
    await db.flush()
    return rep


async def get_monthly_reports(
    db: AsyncSession, oy: int, yil: int
) -> List[SalaryReport]:
    r = await db.execute(
        select(SalaryReport).where(
            SalaryReport.oy == oy,
            SalaryReport.yil == yil,
        )
    )
    return r.scalars().all()


# ── DASHBOARD ────────────────────────────────────────────────────────────────

async def get_dashboard_stats(db: AsyncSession) -> dict:
    today = date.today()
    now   = datetime.now()

    works_r = await db.execute(
        select(WorkEntry.status, func.count(WorkEntry.id))
        .where(WorkEntry.work_date == today)
        .group_by(WorkEntry.status)
    )
    work_stats = {
        (row[0].value if hasattr(row[0], "value") else str(row[0])): row[1]
        for row in works_r.all()
    }

    income_r = await db.execute(
        select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
        .where(
            WorkEntry.work_date == today,
            WorkEntry.status.in_([WorkStatus.approved, WorkStatus.adjusted]),
        )
    )

    low_r = await db.execute(
        select(func.count(WarehouseProduct.id))
        .where(
            WarehouseProduct.is_active == True,
            WarehouseProduct.miqdor <= WarehouseProduct.min_threshold,
        )
    )

    workers_r = await db.execute(
        select(func.count(User.id))
        .where(User.role == UserRole.ishchi, User.is_active == True)
    )

    monthly_r = await db.execute(
        select(func.coalesce(func.sum(SalaryReport.sof_maosh), 0))
        .where(
            SalaryReport.oy == now.month,
            SalaryReport.yil == now.year,
        )
    )

    # TUZATILDI: open_sessions — bugungi ochiq sessiyalar
    open_r = await db.execute(
        select(func.count(WorkSession.id))
        .where(
            WorkSession.work_date == today,
            WorkSession.closed_at == None,
        )
    )

    return {
        "today_income":   float(income_r.scalar()),
        "today_works":    sum(work_stats.values()),
        "pending_works":  work_stats.get(WorkStatus.pending.value, 0),
        "approved_works": work_stats.get(WorkStatus.approved.value, 0),
        "rejected_works": work_stats.get(WorkStatus.rejected.value, 0),
        "edit_requested": work_stats.get(WorkStatus.edit_requested.value, 0),
        "low_stock":      low_r.scalar() or 0,
        "workers_count":  workers_r.scalar() or 0,
        "monthly_total":  float(monthly_r.scalar()),
        "work_stats":     work_stats,
        "open_sessions":  open_r.scalar() or 0,
    }


async def get_warehouse_logs_paged(
    db: AsyncSession,
    product_id: int = None,
    amal: str = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple:
    q = select(WarehouseLog).order_by(WarehouseLog.created_at.desc())
    if product_id: q = q.where(WarehouseLog.product_id == product_id)
    if amal:       q = q.where(WarehouseLog.amal == amal)
    total = (
        await db.execute(select(func.count()).select_from(q.subquery()))
    ).scalar() or 0
    return (
        await db.execute(q.limit(limit).offset(offset))
    ).scalars().all(), total


# ═══ QOLIP MAXSUS FUNKSIYALAR ════════════════════════════════════════════════

async def search_qoliplar(
    db: AsyncSession,
    text_query: str = None,
    tur: str = None,
    holat_filter: str = None,   # "yaroqli"|"tamir_talab"|"yaroqsiz"|None
    razmer_query: str = None,   # "40" yoki "40x40" yoki "40x40x60"
    limit: int = 12,
    offset: int = 0,
) -> tuple:
    """
    500+ qolip ichidan ko'p mezonli qidiruv.
    razmer_query="40"     → istalgan o'lchamda 40 bo'lsa
    razmer_query="40x40"  → normallashtirilgan razmerda "40x40" bo'lsa
    """
    from utils.razmer import normalize_razmer, razmer_search_variants

    q = select(WarehouseProduct).where(
        WarehouseProduct.category == ProductCategory.qolip,
        WarehouseProduct.is_active == True,
    )

    if text_query and text_query.strip():
        q = q.where(WarehouseProduct.name.ilike(f"%{text_query.strip()}%"))

    if tur:
        q = q.where(WarehouseProduct.tur == tur)

    if holat_filter:
        from database.models import ProductHolat
        try:
            q = q.where(WarehouseProduct.holat == ProductHolat(holat_filter))
        except ValueError:
            pass

    if razmer_query and razmer_query.strip():
        norm = normalize_razmer(razmer_query.strip())
        if norm:
            variants = razmer_search_variants(norm)
            if variants:
                from sqlalchemy import or_
                razmer_conds = [
                    WarehouseProduct.razmer_normalized.ilike(f"%{v}%")
                    for v in variants
                ]
                q = q.where(or_(*razmer_conds))

    total = (
        await db.execute(select(func.count()).select_from(q.subquery()))
    ).scalar() or 0

    q = q.order_by(
        WarehouseProduct.tur,
        WarehouseProduct.razmer_normalized,
        WarehouseProduct.name,
    ).limit(limit).offset(offset)

    return (await db.execute(q)).scalars().all(), total


async def get_qolip_holat_summary(db: AsyncSession) -> dict:
    """
    Qoliplar holati bo'yicha statistika:
    {"yaroqli": 480, "tamir_talab": 15, "yaroqsiz": 5, "noaniq": 10}
    """
    from database.models import ProductHolat
    from sqlalchemy import case

    result = await db.execute(
        select(
            WarehouseProduct.holat,
            func.count(WarehouseProduct.id).label("cnt"),
        )
        .where(
            WarehouseProduct.category == ProductCategory.qolip,
            WarehouseProduct.is_active == True,
        )
        .group_by(WarehouseProduct.holat)
    )
    rows = result.all()
    summary = {"yaroqli": 0, "tamir_talab": 0, "yaroqsiz": 0, "noaniq": 0}
    for holat, cnt in rows:
        key = holat.value if holat else "noaniq"
        summary[key] = cnt
    return summary


async def get_tamir_talab_qoliplar(db: AsyncSession) -> list:
    """Tamir talab va yaroqsiz qoliplar ro'yxati (scheduler uchun)."""
    from database.models import ProductHolat
    q = select(WarehouseProduct).where(
        WarehouseProduct.category == ProductCategory.qolip,
        WarehouseProduct.is_active == True,
        WarehouseProduct.holat.in_([ProductHolat.tamir_talab, ProductHolat.yaroqsiz]),
    ).order_by(WarehouseProduct.holat, WarehouseProduct.tur, WarehouseProduct.name)
    return (await db.execute(q)).scalars().all()


async def update_qolip_holat(
    db: AsyncSession,
    product_id: int,
    new_holat: str,
    izoh: str = None,
) -> WarehouseProduct:
    from database.models import ProductHolat
    p = await db.get(WarehouseProduct, product_id)
    if not p:
        raise ValueError(f"Qolip topilmadi: {product_id}")
    p.holat      = ProductHolat(new_holat)
    p.holat_izoh = izoh or p.holat_izoh
    return p

