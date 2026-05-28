"""
goals.py — KPI va Maqsadlar tizimi
Admin: ishchilarga maqsad belgilash
Ishchi: o'z maqsadlarini ko'rish
"""
import logging
from datetime import date, datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
import sqlalchemy.sql.functions as sf
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    User, UserRole, WorkEntry, WorkStatus, Goal,
)
from database.queries import get_user, get_users_by_role

logger = logging.getLogger(__name__)
router = Router()


def fmt(n):
    try: return f"{int(float(n)):,}".replace(",", " ")
    except: return str(n)


def bar(pct, length=10):
    f = int(max(0, min(100, pct)) / 100 * length)
    return "█" * f + "░" * (length - f)


class G(StatesGroup):
    select_worker  = State()
    select_period  = State()
    enter_target   = State()


# ═══ ADMIN: MAQSAD BELGILASH ═════════════════════════════════════════════════

@router.message(F.text == "🎯 Maqsadlar")
async def goals_menu(message: Message, db: AsyncSession):
    """Maqsadlar boshqaruvi."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        return

    today = date.today()
    month_start = today.replace(day=1)

    # Joriy oy maqsadlari
    r = await db.execute(
        select(Goal, User)
        .join(User, User.id == Goal.worker_id)
        .where(
            Goal.period_type == "monthly",
            Goal.period_date == month_start,
            Goal.is_active == True,
        )
        .order_by(User.full_name)
    )
    rows = r.all()

    txt = f"🎯 <b>OYLIK MAQSADLAR ({today.strftime('%B')})</b>\n{'─' * 24}\n\n"

    if not rows:
        txt += "<i>Hozircha maqsadlar belgilanmagan</i>\n"
    else:
        for goal, u in rows:
            # Joriy daromad
            r_inc = await db.execute(
                select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
                .where(
                    WorkEntry.worker_id == u.id,
                    WorkEntry.work_date >= month_start,
                    WorkEntry.status == WorkStatus.approved,
                )
            )
            current = float(r_inc.scalar() or 0)
            pct = (current / goal.target_amount * 100) if goal.target_amount > 0 else 0
            emoji = "✅" if pct >= 100 else ("🟡" if pct >= 70 else "🔴")

            txt += (
                f"{emoji} <b>{u.full_name}</b>\n"
                f"<code>{bar(pct)}</code> {pct:.0f}%\n"
                f"💰 {fmt(current)} / {fmt(goal.target_amount)}\n\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Maqsad belgilash", callback_data="goal_new")],
        [InlineKeyboardButton(text="📊 Maqsadlar reytingi", callback_data="goal_leaderboard")],
    ])
    await message.answer(txt, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "goal_new")
async def goal_new(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """Yangi maqsad — ishchi tanlash."""
    workers = await get_users_by_role(db, UserRole.ishchi)
    if not workers:
        await cb.message.answer("Ishchilar yo'q")
        await cb.answer(); return

    buttons = [
        [InlineKeyboardButton(text=f"👤 {w.full_name}", callback_data=f"goal_w_{w.id}")]
        for w in workers[:30]
    ]
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])

    await cb.message.answer(
        "👤 Kimga maqsad belgilaysiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(G.select_worker)
    await cb.answer()


@router.callback_query(F.data.startswith("goal_w_"), G.select_worker)
async def goal_worker_selected(cb: CallbackQuery, state: FSMContext):
    wid = int(cb.data[7:])
    await state.update_data(worker_id=wid)
    await cb.message.answer(
        "📅 Davr turi:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Kunlik",  callback_data="goal_p_daily")],
            [InlineKeyboardButton(text="📆 Oylik",   callback_data="goal_p_monthly")],
        ]),
    )
    await state.set_state(G.select_period)
    await cb.answer()


@router.callback_query(F.data.startswith("goal_p_"), G.select_period)
async def goal_period(cb: CallbackQuery, state: FSMContext):
    period = cb.data[7:]  # daily | monthly
    await state.update_data(period_type=period)
    label = "kunlik" if period == "daily" else "oylik"
    await cb.message.answer(
        f"💰 {label.capitalize()} maqsadli summa (so'mda):\n"
        f"Masalan: 500000 (kunlik) yoki 15000000 (oylik)"
    )
    await state.set_state(G.enter_target)
    await cb.answer()


@router.message(G.enter_target)
async def goal_target_save(m: Message, state: FSMContext, db: AsyncSession):
    try:
        amount = float(m.text.replace(",", "").replace(" ", ""))
    except ValueError:
        await m.answer("Noto'g'ri summa:"); return

    data = await state.get_data()
    today = date.today()
    period_date = today if data["period_type"] == "daily" else today.replace(day=1)

    # Mavjud maqsadni o'chirib qo'yish
    r = await db.execute(
        select(Goal).where(
            Goal.worker_id == data["worker_id"],
            Goal.period_type == data["period_type"],
            Goal.period_date == period_date,
            Goal.is_active == True,
        )
    )
    existing = r.scalar_one_or_none()
    if existing:
        existing.is_active = False

    user = await get_user(db, m.from_user.id)
    worker = await db.get(User, data["worker_id"])

    new_goal = Goal(
        worker_id=data["worker_id"],
        period_type=data["period_type"],
        period_date=period_date,
        target_amount=amount,
        set_by=user.id if user else None,
    )
    db.add(new_goal)
    await db.commit()

    label = "kunlik" if data["period_type"] == "daily" else "oylik"
    await m.answer(
        f"✅ Maqsad belgilandi!\n\n"
        f"👤 {worker.full_name if worker else '—'}\n"
        f"📅 {label}\n"
        f"💰 {fmt(amount)} so'm\n",
    )
    await state.clear()


@router.callback_query(F.data == "goal_leaderboard")
async def goal_leaderboard(cb: CallbackQuery, db: AsyncSession):
    """Maqsad bajarish reytingi."""
    today = date.today()
    month_start = today.replace(day=1)

    r = await db.execute(
        select(Goal, User)
        .join(User, User.id == Goal.worker_id)
        .where(
            Goal.period_type == "monthly",
            Goal.period_date == month_start,
            Goal.is_active == True,
        )
    )
    rows = r.all()

    if not rows:
        await cb.message.answer("Maqsadlar yo'q")
        await cb.answer(); return

    # Har kim uchun progress hisoblash
    results = []
    for goal, u in rows:
        r_inc = await db.execute(
            select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
            .where(
                WorkEntry.worker_id == u.id,
                WorkEntry.work_date >= month_start,
                WorkEntry.status == WorkStatus.approved,
            )
        )
        current = float(r_inc.scalar() or 0)
        pct = (current / goal.target_amount * 100) if goal.target_amount > 0 else 0
        results.append((u.full_name, goal.target_amount, current, pct))

    # Foiz bo'yicha saralash
    results.sort(key=lambda x: x[3], reverse=True)

    txt = f"📊 <b>MAQSAD BAJARISH REYTINGI</b>\n<i>{today.strftime('%B %Y')}</i>\n{'─' * 24}\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    for i, (name, target, current, pct) in enumerate(results[:15]):
        em = medals[i] if i < len(medals) else "📊"
        txt += f"{em} <b>{name}</b> — {pct:.0f}%\n"
        txt += f"   {fmt(current)} / {fmt(target)}\n"

    await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()


# ═══ ISHCHI: MENING MAQSADIM ═════════════════════════════════════════════════

@router.message(F.text == "🎯 Maqsadim")
async def my_goal(message: Message, db: AsyncSession):
    """Ishchi o'z maqsadlarini ko'radi."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role != UserRole.ishchi:
        return

    today = date.today()
    month_start = today.replace(day=1)

    # Oylik maqsad
    r_m = await db.execute(
        select(Goal).where(
            Goal.worker_id == user.id,
            Goal.period_type == "monthly",
            Goal.period_date == month_start,
            Goal.is_active == True,
        )
    )
    monthly_goal = r_m.scalar_one_or_none()

    # Kunlik maqsad
    r_d = await db.execute(
        select(Goal).where(
            Goal.worker_id == user.id,
            Goal.period_type == "daily",
            Goal.period_date == today,
            Goal.is_active == True,
        )
    )
    daily_goal = r_d.scalar_one_or_none()

    # Joriy progress
    r_t = await db.execute(
        select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
        .where(
            WorkEntry.worker_id == user.id,
            WorkEntry.work_date == today,
            WorkEntry.status == WorkStatus.approved,
        )
    )
    today_inc = float(r_t.scalar() or 0)

    r_m2 = await db.execute(
        select(func.coalesce(func.sum(WorkEntry.jami_summa), 0))
        .where(
            WorkEntry.worker_id == user.id,
            WorkEntry.work_date >= month_start,
            WorkEntry.status == WorkStatus.approved,
        )
    )
    month_inc = float(r_m2.scalar() or 0)

    txt = f"🎯 <b>MENING MAQSADLARIM</b>\n{'─' * 24}\n\n"

    # Kunlik
    if daily_goal:
        pct = (today_inc / daily_goal.target_amount * 100) if daily_goal.target_amount > 0 else 0
        em = "✅" if pct >= 100 else ("🟡" if pct >= 70 else "🔴")
        left = max(0, daily_goal.target_amount - today_inc)
        txt += (
            f"<b>📅 KUNLIK MAQSAD</b>\n"
            f"{em} <code>{bar(pct, 14)}</code> {pct:.0f}%\n"
            f"💰 {fmt(today_inc)} / {fmt(daily_goal.target_amount)}\n"
        )
        if left > 0:
            txt += f"➡️ {fmt(left)} so'm qoldi\n"
        else:
            txt += f"🎉 Maqsadga yetdingiz!\n"
        txt += "\n"
    else:
        txt += "<i>Kunlik maqsad belgilanmagan</i>\n\n"

    # Oylik
    if monthly_goal:
        pct = (month_inc / monthly_goal.target_amount * 100) if monthly_goal.target_amount > 0 else 0
        em = "✅" if pct >= 100 else ("🟡" if pct >= 70 else "🔴")
        left = max(0, monthly_goal.target_amount - month_inc)
        days_left = (today.replace(day=28) - today).days
        daily_need = (left / max(days_left, 1)) if left > 0 else 0
        txt += (
            f"<b>📆 OYLIK MAQSAD</b>\n"
            f"{em} <code>{bar(pct, 14)}</code> {pct:.0f}%\n"
            f"💰 {fmt(month_inc)} / {fmt(monthly_goal.target_amount)}\n"
        )
        if left > 0:
            txt += f"➡️ {fmt(left)} so'm qoldi\n"
            if daily_need > 0:
                txt += f"📊 Kuniga: {fmt(daily_need)} so'm topish kerak\n"
        else:
            txt += f"🎉 Oylik maqsadga yetdingiz!\n"
    else:
        txt += "<i>Oylik maqsad belgilanmagan</i>\n"

    await message.answer(txt, parse_mode="HTML")
