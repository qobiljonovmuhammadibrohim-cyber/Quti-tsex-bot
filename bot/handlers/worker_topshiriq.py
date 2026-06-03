"""
worker_topshiriq.py — Ishchi uchun topshiriqlar (bot).
Ishchi o'z topshiriqlarini ko'radi va "Bajarildi / Qisman" deb hisobot beradi.
Hisobot berilganda WorkEntry yaratiladi (nazoratchiga boradi) va material kamayadi.
"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Topshiriq, TopshiriqStatus, WorkEntry, WorkStatus, WorkType,
    User, UserRole,
)
from database.queries import get_user, get_price, get_users_by_role, update_product_miqdor

logger = logging.getLogger(__name__)
router = Router()


class TaskReport(StatesGroup):
    qisman_soni = State()   # qisman bajarganda — necha dona


def _work_name(wt_value: str) -> str:
    try:
        from constants import get_work_name
        return get_work_name(wt_value)
    except Exception:
        return (wt_value or "?").replace("_", " ").title()


# ─── Topshiriqlarni ko'rsatish ───────────────────────────────────────────
@router.message(F.text == "📌 Topshiriqlarim")
async def my_tasks(message: Message, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user:
        return
    rows = (await db.execute(
        select(Topshiriq).where(
            Topshiriq.worker_id == user.id,
            Topshiriq.status.in_([TopshiriqStatus.tayinlangan, TopshiriqStatus.qisman]),
        ).order_by(Topshiriq.created_at.asc())
    )).scalars().all()

    if not rows:
        await message.answer("📌 Sizda faol topshiriq yo'q.\n\nAgar ish qilsangiz, \"Ish kiritish\" orqali kiriting.")
        return

    await message.answer(f"📌 <b>Sizning topshiriqlaringiz</b> ({len(rows)} ta)", parse_mode="HTML")
    for tp in rows:
        wt = _work_name(tp.work_type.value if tp.work_type else "?")
        variant = ("\n📐 Razmer: " + tp.razmer_turi) if tp.razmer_turi else ""
        target = float(tp.target_soni or 0)
        done = float(tp.done_soni or 0)
        dl = ("\n📅 Muddat: " + tp.deadline.strftime("%d.%m.%Y")) if tp.deadline else ""
        izoh = ("\n📝 " + tp.izoh) if tp.izoh else ""
        qoldi = (f"\n✔️ Bajarilgan: {done:.0f}") if done > 0 else ""

        text = (
            f"🔹 <b>{wt}</b>{variant}\n"
            f"🎯 Reja: {target:.0f} dona{qoldi}{dl}{izoh}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Bajarildi (to'liq)", callback_data=f"task_done:{tp.id}")],
            [InlineKeyboardButton(text="🔸 Qisman bajardim", callback_data=f"task_partial:{tp.id}")],
        ])
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ─── To'liq bajarildi ────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("task_done:"))
async def task_done(cb: CallbackQuery, db: AsyncSession):
    tid = int(cb.data.split(":")[1])
    tp = await db.get(Topshiriq, tid)
    if not tp or tp.status not in (TopshiriqStatus.tayinlangan, TopshiriqStatus.qisman):
        await cb.answer("Topshiriq topilmadi yoki yakunlangan", show_alert=True)
        return
    target = float(tp.target_soni or 0)
    await _complete_task(cb, db, tp, target, full=True)


# ─── Qisman bajardim → miqdor so'raymiz ──────────────────────────────────
@router.callback_query(F.data.startswith("task_partial:"))
async def task_partial(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    tid = int(cb.data.split(":")[1])
    tp = await db.get(Topshiriq, tid)
    if not tp or tp.status not in (TopshiriqStatus.tayinlangan, TopshiriqStatus.qisman):
        await cb.answer("Topshiriq topilmadi", show_alert=True)
        return
    await state.update_data(task_id=tid)
    await state.set_state(TaskReport.qisman_soni)
    await cb.message.answer(
        f"🔸 Nechta dona bajardingiz?\n(Reja: {float(tp.target_soni or 0):.0f} dona)\n\nFaqat son kiriting:"
    )
    await cb.answer()


@router.message(TaskReport.qisman_soni)
async def task_partial_soni(message: Message, state: FSMContext, db: AsyncSession):
    txt = (message.text or "").strip().replace(",", ".")
    try:
        soni = float(txt)
    except ValueError:
        await message.answer("Faqat son kiriting:")
        return
    if soni <= 0:
        await message.answer("Musbat son kiriting:")
        return

    data = await state.get_data()
    tid = data.get("task_id")
    tp = await db.get(Topshiriq, tid)
    await state.clear()
    if not tp:
        await message.answer("Topshiriq topilmadi")
        return

    target = float(tp.target_soni or 0)
    if soni >= target:
        await _complete_task(message, db, tp, target, full=True)
    else:
        await _complete_task(message, db, tp, soni, full=False)


# ─── Topshiriqni yakunlash: WorkEntry + material + nazoratchi ────────────
async def _complete_task(event, db: AsyncSession, tp: Topshiriq, soni: float, full: bool):
    """WorkEntry yaratadi, material kamaytiradi, nazoratchiga yuboradi."""
    bot = event.bot
    # Narxni hisoblash (variant bo'yicha)
    # Narx: admin topshiriqda belgilagan narx (bo'lmasa — standart WorkPrice)
    narx = tp.narx if (tp.narx is not None and float(tp.narx) > 0) else (await get_price(db, tp.work_type, tp.razmer_turi) or 0)
    jami = round(soni * float(narx))

    # WorkEntry yaratish (nazoratchiga boradi)
    entry = WorkEntry(
        worker_id=tp.worker_id,
        work_type=tp.work_type,
        razmer=tp.razmer_turi,
        soni=soni,
        birlik_narx=narx,
        jami_summa=jami,
        status=WorkStatus.pending,
        started_at=datetime.now(),
    )
    db.add(entry)
    await db.flush()

    # Material kamaytirish (admin bog'lagan bo'lsa)
    mat_warn = ""
    if tp.product_id:
        try:
            await update_product_miqdor(
                db, tp.product_id, -soni, tp.worker_id,
                izoh=f"Topshiriq #{tp.id} bajarildi", work_entry_id=entry.id,
            )
        except Exception as e:
            logger.warning("Material kamaytirishda xato: %s", e)
            mat_warn = "\n⚠️ Material kamaytirishda muammo"

    # Topshiriq holatini yangilash
    tp.done_soni = soni
    tp.work_entry_id = entry.id
    if full:
        tp.status = TopshiriqStatus.bajarilgan
        tp.completed_at = datetime.now()
    else:
        tp.status = TopshiriqStatus.qisman   # admin qaror qiladi
    await db.commit()

    wt = _work_name(tp.work_type.value if tp.work_type else "?")
    if full:
        msg = (
            f"✅ <b>Topshiriq bajarildi!</b>\n"
            f"🔹 {wt}\n"
            f"📦 {soni:.0f} dona · 💰 {jami:,.0f} so'm{mat_warn}\n\n"
            f"Nazoratchi tekshirishini kuting..."
        )
    else:
        msg = (
            f"🔸 <b>Qisman bajarildi</b>\n"
            f"🔹 {wt}\n"
            f"📦 {soni:.0f} / {float(tp.target_soni or 0):.0f} dona · 💰 {jami:,.0f} so'm{mat_warn}\n\n"
            f"Qolgan miqdor bo'yicha admin qaror qiladi.\n"
            f"Nazoratchi tekshirishini kuting..."
        )
    await event.answer(msg, parse_mode="HTML")

    # Nazoratchilarga xabar
    user = await get_user(db, tp.worker_id) if hasattr(tp, "worker_id") else None
    try:
        worker_obj = await db.get(User, tp.worker_id)
        wname = worker_obj.full_name if worker_obj else "?"
    except Exception:
        wname = "?"
    inspectors = await get_users_by_role(db, UserRole.nazoratchi)
    for ins in inspectors:
        try:
            await bot.send_message(
                ins.telegram_id,
                f"📋 Topshiriq bajarildi (tekshirish kerak)!\n"
                f"👷 {wname}\n🔹 {wt}\n📦 {soni:.0f} dona · 💰 {jami:,.0f} so'm",
            )
        except Exception:
            pass

    # Adminlarga xabar (qisman bo'lsa qaror kerak)
    if not full:
        admins = await get_users_by_role(db, UserRole.admin)
        for adm in admins:
            try:
                await bot.send_message(
                    adm.telegram_id,
                    f"⚠️ Qisman bajarilgan topshiriq — qaror kerak!\n"
                    f"👷 {wname}\n🔹 {wt}\n"
                    f"📦 {soni:.0f} / {float(tp.target_soni or 0):.0f} dona\n\n"
                    f"Web panel → Topshiriqlar → Qaror kutmoqda",
                )
            except Exception:
                pass
