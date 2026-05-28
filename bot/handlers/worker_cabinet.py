"""
worker_cabinet.py — KUCHAYTIRILGAN
Ishchi shaxsiy kabineti: progress bar, yutuqlar, motivatsiya, taqqoslash
"""
import logging
from datetime import date, timedelta, datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case as sa_case
import sqlalchemy.sql.functions as sf

from database.models import (
    User, UserRole, WorkEntry, WorkStatus, WorkType,
    Penalty, Advance, Attendance, AttendanceType, WorkSession,
)
from database.queries import get_user, get_users_by_role

logger = logging.getLogger(__name__)
router = Router()


def fmt(n):
    try:
        return f"{int(float(n)):,}".replace(",", " ")
    except Exception:
        return str(n)


def bar(pct, length=10):
    """Progress bar."""
    f = int(max(0, min(100, pct)) / 100 * length)
    return "█" * f + "░" * (length - f)


# Daraja tizimi (gamification)
LEVELS = [
    (0,         "🥚 Yangi boshlovchi"),
    (500_000,   "🐣 O'rganuvchi"),
    (1_500_000, "🐤 Tajribali"),
    (3_000_000, "🦅 Mahoratli"),
    (5_000_000, "🏆 Usta"),
    (8_000_000, "💎 Eksperty"),
    (12_000_000, "👑 Master"),
    (20_000_000, "🌟 Afsona"),
]


def get_level(total_income):
    """Daraja va keyingi darajagacha foiz."""
    for i, (threshold, name) in enumerate(LEVELS):
        if total_income < threshold:
            prev_threshold, prev_name = LEVELS[i-1] if i > 0 else (0, name)
            next_threshold = threshold
            current_in_level = total_income - prev_threshold
            level_range = next_threshold - prev_threshold
            pct = (current_in_level / level_range * 100) if level_range > 0 else 0
            return prev_name, name, pct, next_threshold - total_income
    return LEVELS[-1][1], None, 100, 0


def get_achievements(total_works, total_income, days_worked, best_day_income):
    """Yutuqlar ro'yxati."""
    ach = []
    if total_works >= 10:
        ach.append("🎯 Birinchi 10 ish")
    if total_works >= 100:
        ach.append("💯 100 ish bajardim")
    if total_works >= 500:
        ach.append("🏅 500 ish to'pladim")
    if total_works >= 1000:
        ach.append("👑 1000 ish — usta")
    if total_income >= 1_000_000:
        ach.append("💵 1 mln so'm topdim")
    if total_income >= 5_000_000:
        ach.append("💰 5 mln so'm — boy")
    if total_income >= 10_000_000:
        ach.append("💎 10 mln so'm — VIP")
    if days_worked >= 30:
        ach.append("📅 30 kun ishladim")
    if days_worked >= 90:
        ach.append("🔥 90 kun — chempion")
    if best_day_income >= 500_000:
        ach.append("⚡ 1 kunda 500k+ topdim")
    if best_day_income >= 1_000_000:
        ach.append("🚀 1 kunda 1mln+ topdim")
    return ach


# ═══ ASOSIY KABINET ════════════════════════════════════════════════════════

@router.message(F.text == "👤 Mening kabinetim")
@router.message(F.text == "Mening kabinetim")
async def my_cabinet(message: Message, db: AsyncSession):
    """Ishchi shaxsiy kabineti."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.ishchi:
        await message.answer("Bu funksiya faqat ishchilar uchun.")
        return

    today = date.today()
    month_start = today.replace(day=1)

    # Bu oygi statistika
    r_m = await db.execute(
        select(
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.pending,  1), else_=0)),
        ).where(
            WorkEntry.worker_id == user.id,
            WorkEntry.work_date >= month_start,
        )
    )
    m = r_m.one()
    m_total, m_inc = int(m[0] or 0), float(m[1] or 0)
    m_ok, m_rej, m_pend = int(m[2] or 0), int(m[3] or 0), int(m[4] or 0)

    # Umumiy daromad (barcha vaqt)
    r_all = await db.execute(
        select(
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            func.count(WorkEntry.id),
        ).where(
            WorkEntry.worker_id == user.id,
            WorkEntry.status == WorkStatus.approved,
        )
    )
    all_row = r_all.one()
    total_income, total_works = float(all_row[0] or 0), int(all_row[1] or 0)

    # Bugun
    r_t = await db.execute(
        select(
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            func.count(WorkEntry.id),
        ).where(
            WorkEntry.worker_id == user.id,
            WorkEntry.work_date == today,
            WorkEntry.status == WorkStatus.approved,
        )
    )
    t = r_t.one()
    today_inc, today_works = float(t[0] or 0), int(t[1] or 0)

    # Eng yaxshi kun
    r_best = await db.execute(
        select(
            WorkEntry.work_date,
            func.coalesce(func.sum(WorkEntry.jami_summa), 0).label("inc"),
        ).where(
            WorkEntry.worker_id == user.id,
            WorkEntry.status == WorkStatus.approved,
        ).group_by(WorkEntry.work_date)
        .order_by(func.coalesce(func.sum(WorkEntry.jami_summa), 0).desc())
        .limit(1)
    )
    best_row = r_best.first()
    best_day_inc = float(best_row[1]) if best_row else 0
    best_day_date = best_row[0] if best_row else None

    # Ishlagan kunlar soni
    r_days = await db.execute(
        select(func.count(func.distinct(WorkEntry.work_date)))
        .where(
            WorkEntry.worker_id == user.id,
            WorkEntry.status == WorkStatus.approved,
        )
    )
    days_worked = int(r_days.scalar() or 0)

    # Jarima
    r_pen = await db.execute(
        select(func.coalesce(func.sum(Penalty.summa), 0))
        .where(
            Penalty.worker_id == user.id,
            func.extract('month', Penalty.created_at) == today.month,
            func.extract('year',  Penalty.created_at) == today.year,
        )
    )
    m_penalty = float(r_pen.scalar() or 0)

    # Avans
    r_adv = await db.execute(
        select(func.coalesce(func.sum(Advance.summa), 0))
        .where(Advance.worker_id == user.id, Advance.oy == today.month, Advance.yil == today.year)
    )
    m_advance = float(r_adv.scalar() or 0)

    # Sof maosh
    sof_maosh = m_inc - m_penalty - m_advance

    # Sifat foizi
    qa_total = m_ok + m_rej
    qa_pct = (m_ok / qa_total * 100) if qa_total > 0 else 100

    # Daraja
    prev_lvl, next_lvl, lvl_pct, lvl_left = get_level(total_income)

    # Smena holati
    r_sm = await db.execute(
        select(WorkSession).where(
            WorkSession.worker_id == user.id,
            WorkSession.end_time.is_(None),
        )
    )
    active_session = r_sm.scalar_one_or_none()
    sm_status = "🟢 Smenada" if active_session else "⚪ Smena yopiq"

    # Reyting — bu oyda joyim
    r_rank = await db.execute(
        select(
            User.id,
            func.coalesce(func.sum(WorkEntry.jami_summa), 0).label("inc"),
        )
        .join(WorkEntry, WorkEntry.worker_id == User.id)
        .where(
            WorkEntry.work_date >= month_start,
            WorkEntry.status == WorkStatus.approved,
            User.role == UserRole.ishchi,
        )
        .group_by(User.id)
        .order_by(func.coalesce(func.sum(WorkEntry.jami_summa), 0).desc())
    )
    ranks = r_rank.all()
    my_rank = next((i + 1 for i, (uid, _) in enumerate(ranks) if uid == user.id), len(ranks) + 1)
    total_ranked = len(ranks)

    # Yutuqlar
    achievements = get_achievements(total_works, total_income, days_worked, best_day_inc)

    # Bo'lim 1: Salom
    txt = (
        f"👋 <b>Salom, {user.full_name}!</b>\n"
        f"<i>{today.strftime('%d.%m.%Y')}  {datetime.now().strftime('%H:%M')}</i>\n"
        f"{sm_status}\n"
        f"{'─' * 24}\n\n"
    )

    # Bo'lim 2: Daraja
    txt += f"<b>{prev_lvl}</b>\n"
    if next_lvl:
        txt += f"<code>{bar(lvl_pct, 14)}</code> {lvl_pct:.0f}%\n"
        txt += f"➡️ {next_lvl} ({fmt(lvl_left)} so'm qoldi)\n\n"
    else:
        txt += f"🏆 Eng yuqori darajadasiz!\n\n"

    # Bo'lim 3: Bugun
    txt += (
        f"<b>📅 BUGUN</b>\n"
        f"💰 {fmt(today_inc)} so'm\n"
        f"📋 {today_works} ta ish\n\n"
    )

    # Bo'lim 4: Bu oy
    txt += (
        f"<b>📊 BU OY ({today.strftime('%B')})</b>\n"
        f"💵 Sof maosh: <b>{fmt(sof_maosh)}</b> so'm\n"
        f"💰 Daromad: {fmt(m_inc)}\n"
        f"⚠️ Jarima: -{fmt(m_penalty)}\n"
        f"💳 Avans: -{fmt(m_advance)}\n"
        f"📋 Ishlar: {m_total} ta\n"
        f"  ✅ {m_ok}  ⏳ {m_pend}  ❌ {m_rej}\n\n"
    )

    # Bo'lim 5: Sifat
    qa_emoji = "✅" if qa_pct >= 95 else ("⚠️" if qa_pct >= 85 else "❌")
    txt += (
        f"<b>{qa_emoji} SIFAT</b>\n"
        f"<code>{bar(qa_pct)}</code> {qa_pct:.1f}%\n\n"
    )

    # Bo'lim 6: Reyting
    if my_rank <= 3:
        rank_emoji = ["🥇", "🥈", "🥉"][my_rank - 1]
    elif my_rank <= 10:
        rank_emoji = "🏅"
    else:
        rank_emoji = "📊"
    txt += (
        f"<b>{rank_emoji} REYTING</b>\n"
        f"O'rin: <b>{my_rank}</b> / {total_ranked}\n\n"
    )

    # Bo'lim 7: Eng yaxshi rekordlar
    txt += (
        f"<b>🏆 REKORDLARIM</b>\n"
        f"💎 Jami daromad: {fmt(total_income)} so'm\n"
        f"📋 Jami ish: {total_works} ta\n"
        f"📅 Ish kunlari: {days_worked} kun\n"
    )
    if best_day_date:
        txt += f"⚡ Eng yaxshi kun: {fmt(best_day_inc)} ({best_day_date.strftime('%d.%m.%Y')})\n"
    txt += "\n"

    # Bo'lim 8: Yutuqlar
    if achievements:
        txt += f"<b>🎖 YUTUQLARIM ({len(achievements)})</b>\n"
        for a in achievements[:10]:
            txt += f"{a}\n"
        if len(achievements) > 10:
            txt += f"<i>... va yana {len(achievements) - 10} ta</i>\n"
    else:
        txt += "<i>Hali yutuqlar yo'q — ishlashda davom eting!</i>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📈 Tarix",       callback_data="kab_history"),
            InlineKeyboardButton(text="📊 Reyting",     callback_data="kab_leaderboard"),
        ],
        [
            InlineKeyboardButton(text="📅 Davomat",     callback_data="kab_attendance"),
            InlineKeyboardButton(text="💰 Maosh",       callback_data="kab_salary"),
        ],
        [
            InlineKeyboardButton(text="📄 PDF hisobot",  callback_data="kab_pdf"),
            InlineKeyboardButton(text="🔄 Yangilash",    callback_data="kab_refresh"),
        ],
    ])
    await message.answer(txt, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "kab_refresh")
async def kab_refresh(cb: CallbackQuery, db: AsyncSession):
    await cb.message.delete()
    fake = cb.message
    fake.from_user = cb.from_user
    await my_cabinet(fake, db)
    await cb.answer("✅ Yangilandi")


@router.callback_query(F.data == "kab_history")
async def kab_history(cb: CallbackQuery, db: AsyncSession):
    """So'nggi 30 kunlik tarix — grafik bilan."""
    user = await get_user(db, cb.from_user.id)
    if not user: return

    today = date.today()
    days = []
    max_inc = 0
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        r = await db.execute(
            select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
            .where(
                WorkEntry.worker_id == user.id,
                WorkEntry.work_date == d,
                WorkEntry.status == WorkStatus.approved,
            )
        )
        inc = float(r.scalar() or 0)
        days.append((d, inc))
        max_inc = max(max_inc, inc)

    txt = f"📈 <b>14 kunlik daromad tarixi</b>\n{'─' * 24}\n\n"
    for d, inc in days:
        if max_inc > 0:
            bar_len = int(inc / max_inc * 15)
            bar_str = "▓" * bar_len + "░" * (15 - bar_len)
        else:
            bar_str = "░" * 15

        wd = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"][d.weekday()]
        txt += f"<code>{d.strftime('%d.%m')} {wd} {bar_str}</code> {fmt(inc)}\n"

    total = sum(inc for _, inc in days)
    avg = total / len([d for d, inc in days if inc > 0]) if any(inc > 0 for _, inc in days) else 0
    txt += f"\n💰 Jami: <b>{fmt(total)}</b> so'm\n"
    txt += f"📊 O'rtacha: <b>{fmt(avg)}</b> so'm/kun\n"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "kab_leaderboard")
async def kab_leaderboard(cb: CallbackQuery, db: AsyncSession):
    """Bu oygi reyting."""
    user = await get_user(db, cb.from_user.id)
    if not user: return

    today = date.today()
    month_start = today.replace(day=1)

    r = await db.execute(
        select(
            User.id,
            User.full_name,
            func.coalesce(func.sum(WorkEntry.jami_summa), 0).label("inc"),
            func.count(WorkEntry.id).label("cnt"),
        )
        .join(WorkEntry, WorkEntry.worker_id == User.id)
        .where(
            WorkEntry.work_date >= month_start,
            WorkEntry.status == WorkStatus.approved,
            User.role == UserRole.ishchi,
        )
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(WorkEntry.jami_summa), 0).desc())
    )
    rows = r.all()

    txt = f"🏆 <b>BU OYGI REYTING</b>\n<i>{today.strftime('%B %Y')}</i>\n{'─' * 24}\n\n"

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, (uid, name, inc, cnt) in enumerate(rows[:20]):
        rank = i + 1
        em = medals.get(rank, "🏅" if rank <= 10 else "📊")
        marker = " ← <b>SIZ</b>" if uid == user.id else ""
        txt += f"{em} <b>{rank}.</b> {name} — {fmt(inc)}{marker}\n"

    # Agar foydalanuvchi top-20 da bo'lmasa
    my_rank = next((i + 1 for i, (uid, _, _, _) in enumerate(rows) if uid == user.id), None)
    if my_rank and my_rank > 20:
        txt += f"\n...\n📊 <b>{my_rank}.</b> {user.full_name} (siz)\n"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "kab_attendance")
async def kab_attendance(cb: CallbackQuery, db: AsyncSession):
    """Davomat — bu oy."""
    user = await get_user(db, cb.from_user.id)
    if not user: return

    today = date.today()
    r = await db.execute(
        select(Attendance.tur, func.count(Attendance.id))
        .where(
            Attendance.worker_id == user.id,
            func.extract('month', Attendance.sana) == today.month,
            func.extract('year',  Attendance.sana) == today.year,
        )
        .group_by(Attendance.tur)
    )
    rows = {(r[0].value if r[0] else "?"): r[1] for r in r.all()}

    txt = (
        f"📅 <b>DAVOMAT — {today.strftime('%B')}</b>\n{'─' * 24}\n\n"
        f"✅ Ish kunlari: <b>{rows.get('ish', 0)}</b>\n"
        f"🤒 Kasallik: <b>{rows.get('kasallik', 0)}</b>\n"
        f"🌴 Ta'til: <b>{rows.get('tatil', 0)}</b>\n"
        f"📝 Sababli: <b>{rows.get('sababli', 0)}</b>\n"
        f"⛔ Sababsiz: <b>{rows.get('sababsiz', 0)}</b>\n"
    )
    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "kab_salary")
async def kab_salary(cb: CallbackQuery, db: AsyncSession):
    """Maosh hisob-kitobi."""
    user = await get_user(db, cb.from_user.id)
    if not user: return

    today = date.today()
    month_start = today.replace(day=1)

    r_inc = await db.execute(
        select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
        .where(
            WorkEntry.worker_id == user.id,
            WorkEntry.work_date >= month_start,
            WorkEntry.status == WorkStatus.approved,
        )
    )
    inc = float(r_inc.scalar() or 0)

    r_pen = await db.execute(
        select(Penalty).where(
            Penalty.worker_id == user.id,
            func.extract('month', Penalty.created_at) == today.month,
            func.extract('year',  Penalty.created_at) == today.year,
        )
    )
    penalties = r_pen.scalars().all()

    r_adv = await db.execute(
        select(Advance).where(
            Advance.worker_id == user.id,
            Advance.oy == today.month, Advance.yil == today.year,
        )
    )
    advances = r_adv.scalars().all()

    pen_sum = sum(float(p.summa) for p in penalties)
    adv_sum = sum(float(a.summa) for a in advances)
    sof = inc - pen_sum - adv_sum

    txt = (
        f"💰 <b>MAOSH HISOB-KITOBI — {today.strftime('%B')}</b>\n{'─' * 24}\n\n"
        f"💵 Daromad:  <b>+{fmt(inc)}</b>\n"
        f"⚠️ Jarima:   <b>-{fmt(pen_sum)}</b>\n"
        f"💳 Avans:    <b>-{fmt(adv_sum)}</b>\n"
        f"{'─' * 24}\n"
        f"✅ Sof maosh: <b>{fmt(sof)} so'm</b>\n"
    )

    if penalties:
        txt += f"\n<b>⚠️ Jarimalar:</b>\n"
        for p in penalties[:5]:
            txt += f"• {p.sabab[:40]} — {fmt(p.summa)}\n"

    if advances:
        txt += f"\n<b>💳 Avanslar:</b>\n"
        for a in advances[:5]:
            d_str = a.created_at.strftime('%d.%m') if a.created_at else "—"
            txt += f"• {d_str}: {fmt(a.summa)}\n"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data == "kab_pdf")
async def kab_pdf(cb: CallbackQuery, db: AsyncSession):
    """Ishchi shaxsiy PDF hisobot."""
    user = await get_user(db, cb.from_user.id)
    if not user: return

    today = date.today()
    await cb.answer("⏳ Hisobot tayyorlanmoqda...")

    try:
        from utils.pdf_reports import generate_worker_report_pdf
        pdf_bytes = await generate_worker_report_pdf(db, user.id, today.year, today.month)

        from aiogram.types import BufferedInputFile
        await cb.message.answer_document(
            BufferedInputFile(
                pdf_bytes,
                filename=f"hisobot_{today.year}_{today.month:02d}.pdf",
            ),
            caption=f"📄 Sizning {today.strftime('%B %Y')} hisobotingiz",
        )
    except Exception as e:
        logger.error("PDF xato: %s", e)
        await cb.message.answer(f"❌ PDF yaratishda xato: {e}")
