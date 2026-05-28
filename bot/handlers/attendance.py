"""
bot/handlers/attendance.py — Davomat tizimi
Ishchi: kasallik, ta'til, sababli/sababsiz ketish
Admin/Nazoratchi: tasdiqlash, hisobot
"""
import logging
from datetime import date, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database.models import UserRole, Attendance, AttendanceType, User
from database.queries import get_user, get_users_by_role, get_user_by_id

logger = logging.getLogger(__name__)
router = Router()

ATTENDANCE_LABELS = {
    AttendanceType.kasallik: "🤒 Kasallik",
    AttendanceType.tatil:    "🏖 Ta'til",
    AttendanceType.sababli:  "📝 Sababli",
    AttendanceType.sababsiz: "❌ Sababsiz",
}

ATTENDANCE_ICONS = {
    AttendanceType.ish:      "✅",
    AttendanceType.kasallik: "🤒",
    AttendanceType.tatil:    "🏖",
    AttendanceType.sababli:  "📝",
    AttendanceType.sababsiz: "❌",
}


class AttState(StatesGroup):
    reason  = State()
    izoh    = State()
    confirm = State()
    # Admin
    adm_review = State()


# ═══ ISHCHI TOMONIDAN ══════════════════════════════════════════════════════════

@router.message(F.text == "📋 Davomat")
async def att_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user:
        await message.answer("Foydalanuvchi topilmadi."); return

    today = date.today()

    # Bugungi davomat bormi?
    existing = (await db.execute(
        select(Attendance).where(
            Attendance.worker_id == user.id,
            Attendance.sana == today,
        ).limit(1)
    )).scalar_one_or_none()

    if existing:
        icon = ATTENDANCE_ICONS.get(existing.tur, "?")
        label = ATTENDANCE_LABELS.get(existing.tur, existing.tur.value)
        await message.answer(
            f"📋 Bugungi davomat ({today.strftime('%d.%m.%Y')}):\n"
            f"{icon} {label}\n"
            f"{('📝 Izoh: ' + existing.izoh) if existing.izoh else ''}\n"
            f"{'✅ Tasdiqlangan' if existing.tasdiq else '⏳ Kutmoqda'}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✏️ O'zgartirish",
                    callback_data=f"att_edit_{existing.id}",
                )],
            ]) if not existing.tasdiq else None,
        )
        return

    await state.update_data(worker_id=user.id)
    await message.answer(
        f"📋 Bugungi davomat ({today.strftime('%d.%m.%Y')})\n\n"
        f"Bugun nima sababdan kelmadingiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤒 Kasallik",  callback_data="att_type_kasallik")],
            [InlineKeyboardButton(text="🏖 Ta'til",    callback_data="att_type_tatil")],
            [InlineKeyboardButton(text="📝 Sababli",   callback_data="att_type_sababli")],
            [InlineKeyboardButton(text="❌ Bekor",     callback_data="att_cancel")],
        ]),
    )
    await state.set_state(AttState.reason)


@router.callback_query(F.data.startswith("att_type_"), AttState.reason)
async def att_type(cb: CallbackQuery, state: FSMContext):
    tur = cb.data.replace("att_type_", "")
    await state.update_data(att_tur=tur)
    label = ATTENDANCE_LABELS.get(AttendanceType(tur), tur)
    await cb.message.answer(
        f"{label} — izoh kiriting\n(ixtiyoriy, «-» o'tkazish uchun):",
    )
    await state.set_state(AttState.izoh)
    await cb.answer()


@router.message(AttState.izoh)
async def att_izoh(m: Message, state: FSMContext, db: AsyncSession):
    izoh = None if m.text.strip() == "-" else m.text.strip()
    data = await state.get_data()
    tur  = data["att_tur"]
    label = ATTENDANCE_LABELS.get(AttendanceType(tur), tur)

    # Saqlash
    att = Attendance(
        worker_id=data["worker_id"],
        sana=date.today(),
        tur=AttendanceType(tur),
        izoh=izoh,
        tasdiq=False,
    )
    db.add(att)
    await db.commit()
    await state.clear()

    # Admin/Nazoratchi ga xabar
    user = await get_user_by_id(db, data["worker_id"])
    await _notify_admins_attendance(m.bot, db, user, att, label, izoh)

    await m.answer(
        f"✅ Davomat qayd etildi!\n\n"
        f"{label}\n"
        f"{('📝 ' + izoh) if izoh else ''}\n\n"
        f"⏳ Admin/nazoratchi tasdiqlashini kuting.",
    )


async def _notify_admins_attendance(bot, db, worker, att, label, izoh):
    """Admin va nazoratchilarni xabardor qilish."""
    admins = await get_users_by_role(db, UserRole.admin)
    supers = await get_users_by_role(db, UserRole.superadmin)
    nazors = await get_users_by_role(db, UserRole.nazoratchi)

    text = (
        f"📋 Davomat!\n\n"
        f"👤 {worker.full_name if worker else '?'}\n"
        f"📅 {att.sana.strftime('%d.%m.%Y')}\n"
        f"Sabab: {label}\n"
        + (f"📝 {izoh}\n" if izoh else "")
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"attadm_ok_{att.id}",
            ),
            InlineKeyboardButton(
                text="❌ Sababsiz",
                callback_data=f"attadm_no_{att.id}",
            ),
        ],
    ])
    seen = set()
    for u in admins + supers + nazors:
        if u.telegram_id in seen:
            continue
        seen.add(u.telegram_id)
        try:
            await bot.send_message(u.telegram_id, text, reply_markup=kb)
        except Exception as e:
            logger.warning("Davomat xabari yuborilmadi (%s): %s", u.telegram_id, e)


# ═══ ADMIN TASDIQLASH ═════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("attadm_"))
async def attadm_action(cb: CallbackQuery, db: AsyncSession):
    parts  = cb.data.split("_")
    action = parts[1]  # ok yoki no
    att_id = int(parts[2])

    att = await db.get(Attendance, att_id)
    if not att:
        await cb.answer("Topilmadi"); return

    if action == "ok":
        att.tasdiq  = True
        att.admin_id = (await get_user(db, cb.from_user.id)).id
    else:
        att.tur     = AttendanceType.sababsiz
        att.tasdiq  = True
        att.admin_id = (await get_user(db, cb.from_user.id)).id

    await db.commit()

    worker = await get_user_by_id(db, att.worker_id)
    icon   = "✅ Tasdiqlandi" if action == "ok" else "❌ Sababsiz deb belgilandi"

    try:
        await cb.message.edit_text(
            cb.message.text + f"\n\n{icon}",
            reply_markup=None,
        )
    except Exception:
        pass

    # Ishchiga xabar
    if worker:
        label = ATTENDANCE_LABELS.get(att.tur, att.tur.value)
        try:
            await cb.bot.send_message(
                worker.telegram_id,
                f"📋 Davomatingiz tasdiqlandi!\n"
                f"{label}\n"
                f"{'✅ Tasdiqlandi' if action == 'ok' else '❌ Sababsiz deb belgilandi'}",
            )
        except Exception:
            pass

    await cb.answer(icon)


# ═══ DAVOMAT HISOBOTI ═════════════════════════════════════════════════════════

@router.message(F.text == "📊 Davomat hisoboti")
async def att_report(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    allowed = (UserRole.admin, UserRole.superadmin, UserRole.nazoratchi)
    if not user or user.role not in allowed:
        await message.answer("Ruxsat yo'q."); return

    today      = date.today()
    month_start = today.replace(day=1)

    r = await db.execute(
        select(
            User.full_name,
            Attendance.tur,
            func.count(Attendance.id).label("cnt"),
        )
        .join(User, User.id == Attendance.worker_id)
        .where(
            Attendance.sana >= month_start,
            Attendance.sana <= today,
        )
        .group_by(User.full_name, Attendance.tur)
        .order_by(User.full_name)
    )
    rows = r.all()

    if not rows:
        await message.answer(f"📋 {today.strftime('%B %Y')} — davomat ma'lumoti yo'q.")
        return

    # Ishchi bo'yicha guruhlash
    by_worker = {}
    for name, tur, cnt in rows:
        if name not in by_worker:
            by_worker[name] = {}
        by_worker[name][tur] = cnt

    text = f"📋 <b>Davomat hisoboti — {today.strftime('%B %Y')}</b>\n\n"
    for name, turs in by_worker.items():
        total_days = sum(turs.values())
        kas  = turs.get(AttendanceType.kasallik, 0)
        tat  = turs.get(AttendanceType.tatil, 0)
        sab  = turs.get(AttendanceType.sababli, 0)
        nsab = turs.get(AttendanceType.sababsiz, 0)
        text += f"👤 <b>{name}</b>\n"
        if kas:  text += f"  🤒 Kasallik: {kas} kun\n"
        if tat:  text += f"  🏖 Ta'til: {tat} kun\n"
        if sab:  text += f"  📝 Sababli: {sab} kun\n"
        if nsab: text += f"  ❌ Sababsiz: {nsab} kun\n"
        text += "\n"

    await message.answer(text, parse_mode="HTML")


# ═══ ISHCHI — O'Z DAVOMATI ════════════════════════════════════════════════════

@router.message(F.text == "📅 Mening davomatim")
async def my_attendance(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user:
        return

    today       = date.today()
    month_start = today.replace(day=1)

    r = await db.execute(
        select(Attendance)
        .where(
            Attendance.worker_id == user.id,
            Attendance.sana >= month_start,
        )
        .order_by(Attendance.sana.desc())
    )
    records = r.scalars().all()

    if not records:
        await message.answer(f"📅 {today.strftime('%B %Y')} — davomat yozuvlari yo'q.")
        return

    text = f"📅 <b>Mening davomatim — {today.strftime('%B %Y')}</b>\n\n"
    for rec in records:
        icon  = ATTENDANCE_ICONS.get(rec.tur, "?")
        label = ATTENDANCE_LABELS.get(rec.tur, rec.tur.value)
        conf  = "✅" if rec.tasdiq else "⏳"
        text += f"{icon} {rec.sana.strftime('%d.%m')} — {label} {conf}\n"
        if rec.izoh:
            text += f"   📝 {rec.izoh}\n"

    # Statistika
    kas  = sum(1 for r in records if r.tur == AttendanceType.kasallik)
    tat  = sum(1 for r in records if r.tur == AttendanceType.tatil)
    nsab = sum(1 for r in records if r.tur == AttendanceType.sababsiz)
    text += f"\n<b>Jami:</b> Kasallik: {kas} | Ta'til: {tat} | Sababsiz: {nsab}"

    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "att_cancel")
async def att_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        pass
    await cb.answer()
