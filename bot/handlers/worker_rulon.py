"""
worker_rulon.py — RULON ISHLAB CHIQARISH (zanjir boshi).
Ishchi gramaj, razmer, rang, soni kiritadi.
Natija: WorkEntry (maosh uchun) + omborga yangi rulon QO'SHILADI.
"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    WorkEntry, WorkStatus, WorkType, WarehouseProduct, ProductCategory,
    User, UserRole, WarehouseLog,
)
from database.queries import get_user, get_price, get_users_by_role

logger = logging.getLogger(__name__)
router = Router()


class RulonIshlab(StatesGroup):
    gramaj = State()
    razmer = State()
    rang   = State()
    soni   = State()
    tasdiq = State()


def _parse_num(txt):
    try:
        return float((txt or "").strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


# ─── Boshlash ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "work_rulon_ishlab")
async def rulon_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    user = await get_user(db, cb.from_user.id)
    if not user:
        await cb.answer("Foydalanuvchi topilmadi", show_alert=True)
        return
    await state.clear()
    await state.update_data(worker_id=user.id, work_type=WorkType.rulon_ishlab.value)
    await state.set_state(RulonIshlab.gramaj)
    await cb.message.answer("🌀 <b>Rulon ishlab chiqarish</b>\n\nGramajni kiriting (masalan 120):", parse_mode="HTML")
    await cb.answer()


@router.message(RulonIshlab.gramaj)
async def rulon_gramaj(message: Message, state: FSMContext):
    g = _parse_num(message.text)
    if g is None or g <= 0:
        await message.answer("Gramajni son ko'rinishida kiriting (masalan 120):")
        return
    await state.update_data(gramaj=g)
    await state.set_state(RulonIshlab.razmer)
    await message.answer("📐 Razmer (kenglik)ni kiriting (masalan 100sm):")


@router.message(RulonIshlab.razmer)
async def rulon_razmer(message: Message, state: FSMContext):
    razmer = (message.text or "").strip()
    if not razmer:
        await message.answer("Razmerni kiriting:")
        return
    await state.update_data(razmer=razmer)
    await state.set_state(RulonIshlab.rang)
    await message.answer("🎨 Rangni kiriting (masalan oq):")


@router.message(RulonIshlab.rang)
async def rulon_rang(message: Message, state: FSMContext):
    rang = (message.text or "").strip()
    if not rang:
        await message.answer("Rangni kiriting:")
        return
    await state.update_data(rang=rang)
    await state.set_state(RulonIshlab.soni)
    await message.answer("🔢 Nechta rulon ishlab chiqardingiz?")


@router.message(RulonIshlab.soni)
async def rulon_soni(message: Message, state: FSMContext, db: AsyncSession):
    soni = _parse_num(message.text)
    if soni is None or soni <= 0:
        await message.answer("Musbat son kiriting:")
        return
    await state.update_data(soni=soni)
    data = await state.get_data()

    narx = await get_price(db, WorkType.rulon_ishlab, None) or 0
    jami = round(soni * float(narx))
    await state.update_data(birlik_narx=narx, jami_summa=jami)

    text = (
        f"🌀 <b>Rulon ishlab chiqarish</b>\n\n"
        f"⚖️ Gramaj: {data['gramaj']:.0f}\n"
        f"📐 Razmer: {data['razmer']}\n"
        f"🎨 Rang: {data['rang']}\n"
        f"🔢 Soni: {soni:.0f} dona\n"
        f"💰 Narx: {narx:,.0f} × {soni:.0f} = {jami:,.0f} so'm\n\n"
        f"Tasdiqlaysizmi?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="rulon_tasdiq")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="rulon_bekor")],
    ])
    await state.set_state(RulonIshlab.tasdiq)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "rulon_bekor", RulonIshlab.tasdiq)
async def rulon_bekor(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("❌ Bekor qilindi.")
    await cb.answer()


@router.callback_query(F.data == "rulon_tasdiq", RulonIshlab.tasdiq)
async def rulon_tasdiq(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    gramaj = float(data["gramaj"])
    razmer = data["razmer"]
    rang = data["rang"]
    soni = float(data["soni"])
    narx = float(data.get("birlik_narx", 0))
    jami = float(data.get("jami_summa", 0))
    worker_id = data["worker_id"]

    # 1. WorkEntry (maosh + nazoratchi)
    entry = WorkEntry(
        worker_id=worker_id,
        work_type=WorkType.rulon_ishlab,
        mahsulot_nomi=f"Rulon {gramaj:.0f}g {razmer} {rang}",
        razmer=razmer,
        rang=rang,
        soni=soni,
        birlik_narx=narx,
        jami_summa=jami,
        status=WorkStatus.pending,
        started_at=datetime.now(),
    )
    db.add(entry)
    await db.flush()

    # 2. Omborga rulon QO'SHISH (mavjudini topib yoki yangi yaratib)
    existing = (await db.execute(
        select(WarehouseProduct).where(
            WarehouseProduct.is_active == True,
            WarehouseProduct.category == ProductCategory.rulon,
            WarehouseProduct.qalinlik == gramaj,
            WarehouseProduct.razmer == razmer,
            WarehouseProduct.rang == rang,
        )
    )).scalars().first()

    if existing:
        oldin = float(existing.miqdor or 0)
        existing.miqdor = oldin + soni
        keyin = existing.miqdor
        prod_id = existing.id
    else:
        prod = WarehouseProduct(
            category=ProductCategory.rulon,
            name=f"Rulon {gramaj:.0f}g {razmer} {rang}",
            razmer=razmer,
            rang=rang,
            qalinlik=gramaj,
            birlik="dona",
            miqdor=soni,
            min_threshold=2,
            yellow_threshold=5,
            is_active=True,
        )
        db.add(prod)
        await db.flush()
        oldin = 0.0
        keyin = soni
        prod_id = prod.id

    # Ombor log
    db.add(WarehouseLog(
        product_id=prod_id, user_id=worker_id, amal="kirim",
        miqdor=soni, oldin=oldin, keyin=keyin,
        izoh="Rulon ishlab chiqarildi", work_entry_id=entry.id,
    ))
    await db.commit()
    await state.clear()

    await cb.message.answer(
        f"✅ <b>Rulon ishlab chiqarildi!</b>\n"
        f"🌀 {gramaj:.0f}g · {razmer} · {rang}\n"
        f"📦 {soni:.0f} dona omborga qo'shildi\n"
        f"💰 {jami:,.0f} so'm\n\n"
        f"Nazoratchi tekshirishini kuting...",
        parse_mode="HTML",
    )
    await cb.answer()

    # Nazoratchiga xabar
    user = await get_user(db, cb.from_user.id)
    inspectors = await get_users_by_role(db, UserRole.nazoratchi)
    for ins in inspectors:
        try:
            await cb.bot.send_message(
                ins.telegram_id,
                f"📋 Yangi ish — Rulon ishlab chiqarish!\n"
                f"👷 {user.full_name if user else '?'}\n"
                f"🌀 {gramaj:.0f}g {razmer} {rang}\n"
                f"📦 {soni:.0f} dona · 💰 {jami:,.0f} so'm",
            )
        except Exception:
            pass
