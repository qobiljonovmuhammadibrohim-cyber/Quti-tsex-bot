"""
orders.py — Buyurtmalar tizimi
Mijozlar, buyurtmalar, ishlab chiqarish progress
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
    User, UserRole, Customer, Order, OrderItem, OrderStatus,
)
from database.queries import get_user

logger = logging.getLogger(__name__)
router = Router()


def fmt(n):
    try: return f"{int(float(n)):,}".replace(",", " ")
    except: return str(n)


STATUS_EMOJI = {
    "yangi":         "🆕",
    "qabul_qilindi": "✅",
    "ishlab":        "🔨",
    "tayyor":        "📦",
    "yetkazildi":    "🚚",
    "bekor":         "❌",
}

PRIORITY_EMOJI = {1: "🔥", 2: "⚡", 3: "📋", 4: "📄", 5: "📝"}


class O(StatesGroup):
    new_cust_name    = State()
    new_cust_phone   = State()
    new_cust_company = State()
    new_order_cust   = State()
    new_order_title  = State()
    new_order_desc   = State()
    new_order_deadl  = State()
    new_order_amount = State()


# ═══ ASOSIY MENYU ════════════════════════════════════════════════════════════

@router.message(F.text == "📋 Buyurtmalar")
async def orders_menu(message: Message, db: AsyncSession):
    """Buyurtmalar bosh menyusi."""
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in (UserRole.admin, UserRole.superadmin):
        return

    # Statistika
    r = await db.execute(
        select(
            sf.sum(func.cast(Order.status == OrderStatus.yangi, type_=type(Order.id.type))),
            func.count(Order.id).filter(Order.status == OrderStatus.yangi),
            func.count(Order.id).filter(Order.status == OrderStatus.ishlab),
            func.count(Order.id).filter(Order.status == OrderStatus.tayyor),
        )
    )
    yangi, ishlab, tayyor = 0, 0, 0
    try:
        r2 = await db.execute(select(Order.status, func.count(Order.id)).group_by(Order.status))
        for stat, n in r2.all():
            if stat == OrderStatus.yangi: yangi = n
            elif stat == OrderStatus.ishlab: ishlab = n
            elif stat == OrderStatus.tayyor: tayyor = n
    except Exception as e:
        logger.warning("Order stats: %s", e)

    txt = (
        f"📋 <b>BUYURTMALAR BOSHQARUVI</b>\n{'─' * 24}\n\n"
        f"🆕 Yangi: <b>{yangi}</b>\n"
        f"🔨 Ishlab chiqarilmoqda: <b>{ishlab}</b>\n"
        f"📦 Tayyor: <b>{tayyor}</b>\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Yangi buyurtma", callback_data="ord_new"),
            InlineKeyboardButton(text="👥 Mijozlar",       callback_data="ord_customers"),
        ],
        [
            InlineKeyboardButton(text="🆕 Yangi buyurtmalar",   callback_data="ord_list_yangi"),
            InlineKeyboardButton(text="🔨 Ishlab chiqarilayotgan", callback_data="ord_list_ishlab"),
        ],
        [
            InlineKeyboardButton(text="📦 Tayyor", callback_data="ord_list_tayyor"),
            InlineKeyboardButton(text="🗂 Hammasi", callback_data="ord_list_all"),
        ],
    ])
    await message.answer(txt, parse_mode="HTML", reply_markup=kb)


# ═══ BUYURTMA RO'YXATLARI ════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ord_list_"))
async def order_list(cb: CallbackQuery, db: AsyncSession):
    """Buyurtmalar ro'yxati."""
    status_key = cb.data[9:]  # "ord_list_" = 9
    q = select(Order, Customer).join(Customer, Customer.id == Order.customer_id)

    if status_key != "all":
        try:
            status = OrderStatus(status_key)
            q = q.where(Order.status == status)
        except ValueError:
            pass

    q = q.order_by(Order.priority.asc(), Order.created_at.desc()).limit(20)
    r = await db.execute(q)
    rows = r.all()

    title_map = {
        "yangi": "🆕 Yangi buyurtmalar",
        "ishlab": "🔨 Ishlab chiqarilayotganlar",
        "tayyor": "📦 Tayyor buyurtmalar",
        "all": "🗂 Barcha buyurtmalar",
    }
    title = title_map.get(status_key, "Buyurtmalar")

    txt = f"{title}\n{'─' * 24}\n\n"
    if not rows:
        txt += "<i>Buyurtmalar yo'q</i>"
    else:
        for ord_, cust in rows:
            em       = STATUS_EMOJI.get(ord_.status.value if ord_.status else "yangi", "📋")
            pri_em   = PRIORITY_EMOJI.get(ord_.priority or 3, "📋")
            deadline = f" | ⏰ {ord_.deadline.strftime('%d.%m')}" if ord_.deadline else ""
            txt += (
                f"{em} <b>{ord_.order_number}</b> {pri_em}\n"
                f"👤 {cust.full_name} | 💰 {fmt(ord_.total_amount)}{deadline}\n"
                f"📝 {ord_.title[:50]}\n\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Ortga", callback_data="ord_menu_back")],
    ])
    await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "ord_menu_back")
async def ord_menu_back(cb: CallbackQuery, db: AsyncSession):
    fake = cb.message
    fake.from_user = cb.from_user
    await orders_menu(fake, db)
    await cb.answer()


# ═══ MIJOZLAR ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "ord_customers")
async def list_customers(cb: CallbackQuery, db: AsyncSession):
    """Mijozlar ro'yxati."""
    r = await db.execute(
        select(Customer).where(Customer.is_active == True).order_by(Customer.full_name).limit(30)
    )
    customers = r.scalars().all()

    txt = f"👥 <b>MIJOZLAR ({len(customers)})</b>\n{'─' * 24}\n\n"
    if not customers:
        txt += "<i>Mijozlar yo'q</i>"
    else:
        for c in customers:
            company = f" — {c.company}" if c.company else ""
            phone   = f"\n📞 {c.phone}" if c.phone else ""
            txt += f"👤 <b>{c.full_name}</b>{company}{phone}\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi mijoz", callback_data="cust_new")],
        [InlineKeyboardButton(text="◀️ Ortga",     callback_data="ord_menu_back")],
    ])
    await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "cust_new")
async def new_customer_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("👤 Mijozning to'liq ismi:")
    await state.set_state(O.new_cust_name)
    await cb.answer()


@router.message(O.new_cust_name)
async def new_customer_name(m: Message, state: FSMContext):
    name = m.text.strip()
    if len(name) < 2:
        await m.answer("Kamida 2 harf:"); return
    await state.update_data(cust_name=name)
    await m.answer("📞 Telefon raqami (yoki '-' o'tkazib yuborish):")
    await state.set_state(O.new_cust_phone)


@router.message(O.new_cust_phone)
async def new_customer_phone(m: Message, state: FSMContext):
    phone = m.text.strip() if m.text.strip() != "-" else None
    await state.update_data(cust_phone=phone)
    await m.answer("🏢 Kompaniya nomi (yoki '-' shaxsiy):")
    await state.set_state(O.new_cust_company)


@router.message(O.new_cust_company)
async def new_customer_save(m: Message, state: FSMContext, db: AsyncSession):
    company = m.text.strip() if m.text.strip() != "-" else None
    data = await state.get_data()

    c = Customer(
        full_name=data["cust_name"],
        phone=data.get("cust_phone"),
        company=company,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)

    await m.answer(
        f"✅ Mijoz qo'shildi!\n\n"
        f"👤 {c.full_name}\n"
        f"📞 {c.phone or '—'}\n"
        f"🏢 {c.company or '—'}\n\n"
        f"ID: {c.id}",
    )
    await state.clear()


# ═══ YANGI BUYURTMA ══════════════════════════════════════════════════════════

@router.callback_query(F.data == "ord_new")
async def new_order_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    """Yangi buyurtma — avval mijozni tanlash."""
    r = await db.execute(
        select(Customer).where(Customer.is_active == True)
        .order_by(Customer.full_name).limit(20)
    )
    customers = r.scalars().all()

    if not customers:
        await cb.message.answer(
            "❌ Avval mijoz qo'shish kerak.\n\n"
            "👥 Mijozlar → ➕ Yangi mijoz",
        )
        await cb.answer(); return

    buttons = [
        [InlineKeyboardButton(text=f"👤 {c.full_name[:30]}", callback_data=f"order_cust_{c.id}")]
        for c in customers
    ]
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel")])

    await cb.message.answer(
        "👤 Mijozni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(O.new_order_cust)
    await cb.answer()


@router.callback_query(F.data.startswith("order_cust_"), O.new_order_cust)
async def order_select_customer(cb: CallbackQuery, state: FSMContext):
    cid = int(cb.data[11:])
    await state.update_data(order_cust_id=cid)
    await cb.message.answer("📝 Buyurtma nomi/tavsifi:")
    await state.set_state(O.new_order_title)
    await cb.answer()


@router.message(O.new_order_title)
async def order_title(m: Message, state: FSMContext):
    if len(m.text.strip()) < 3:
        await m.answer("Kamida 3 harf:"); return
    await state.update_data(order_title=m.text.strip())
    await m.answer("📄 Batafsil tavsif (yoki '-' o'tkazish):")
    await state.set_state(O.new_order_desc)


@router.message(O.new_order_desc)
async def order_desc(m: Message, state: FSMContext):
    desc = m.text.strip() if m.text.strip() != "-" else None
    await state.update_data(order_desc=desc)
    await m.answer(
        "📅 Tugatish muddati (DD.MM.YYYY formatda):\n"
        "Masalan: 25.06.2026\n"
        "Yoki '-' (muddat yo'q):",
    )
    await state.set_state(O.new_order_deadl)


@router.message(O.new_order_deadl)
async def order_deadline(m: Message, state: FSMContext):
    txt = m.text.strip()
    deadline = None
    if txt and txt != "-":
        try:
            deadline = datetime.strptime(txt, "%d.%m.%Y").date()
        except ValueError:
            await m.answer("❌ Noto'g'ri format. DD.MM.YYYY kiriting:"); return
    await state.update_data(order_deadline=deadline.isoformat() if deadline else None)
    await m.answer("💰 Umumiy summa (so'mda):")
    await state.set_state(O.new_order_amount)


@router.message(O.new_order_amount)
async def order_amount_save(m: Message, state: FSMContext, db: AsyncSession):
    try:
        amount = float(m.text.replace(",", "").replace(" ", ""))
    except ValueError:
        await m.answer("Noto'g'ri summa. Faqat raqamlar:"); return

    data = await state.get_data()

    # Buyurtma raqami
    r = await db.execute(select(func.count(Order.id)))
    n = int(r.scalar() or 0) + 1
    order_num = f"ORD-{date.today().year}-{n:04d}"

    deadline_iso = data.get("order_deadline")
    deadline = date.fromisoformat(deadline_iso) if deadline_iso else None

    user = await get_user(db, m.from_user.id)

    new_order = Order(
        order_number=order_num,
        customer_id=data["order_cust_id"],
        title=data["order_title"],
        description=data.get("order_desc"),
        total_amount=amount,
        deadline=deadline,
        created_by=user.id if user else None,
    )
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order)

    # Mijoz nomini olish
    cust = await db.get(Customer, data["order_cust_id"])

    await m.answer(
        f"✅ <b>Buyurtma qo'shildi!</b>\n\n"
        f"📋 № <b>{order_num}</b>\n"
        f"👤 {cust.full_name if cust else '—'}\n"
        f"📝 {data['order_title']}\n"
        f"💰 {fmt(amount)} so'm\n"
        f"📅 {deadline.strftime('%d.%m.%Y') if deadline else '—'}\n",
        parse_mode="HTML",
    )
    await state.clear()
