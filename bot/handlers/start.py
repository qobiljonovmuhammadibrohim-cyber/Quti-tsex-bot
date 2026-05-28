"""
start.py — TUZATILGAN
TUZATISHLAR:
  1. process_phone: await db.flush() → await db.commit() (middleware ham commit qiladi,
     lekin user yaratilishi ishonchli bo'lishi uchun)
  2. newuser_accept/reject/spam: cb.data.split("_")[2] o'rniga xavfsiz split
     "newuser_accept_123" → split("_", 2)[-1] = "123"
  3. newuser_accept/reject/spam: db.commit() qo'shildi
  4. cmd_start: auto_role da db.commit() qo'shildi
"""
import logging
from aiogram import Router, F
from aiogram.types import (
    Message, ReplyKeyboardRemove, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from database.models import User, UserRole
from database.queries import get_user, get_users_by_role
from bot.keyboards.main_keyboards import get_main_menu, get_cancel_keyboard
from config.settings import SUPERADMIN_ID, ADMIN_IDS, OMBORCHI_IDS, NAZORATCHI_IDS

logger = logging.getLogger(__name__)
router = Router()


class RegisterStates(StatesGroup):
    waiting_name  = State()
    waiting_phone = State()


def _auto_role(telegram_id: int):
    if telegram_id == SUPERADMIN_ID:  return UserRole.superadmin
    if telegram_id in ADMIN_IDS:      return UserRole.admin
    if telegram_id in OMBORCHI_IDS:   return UserRole.omborchi
    if telegram_id in NAZORATCHI_IDS: return UserRole.nazoratchi
    return None


async def _safe_send(bot, telegram_id, text, **kwargs) -> bool:
    try:
        await bot.send_message(telegram_id, text, **kwargs)
        return True
    except Exception as e:
        logger.warning("Xabar yuborib bo'lmadi (%s): %s", telegram_id, e)
        return False


async def _notify_admins_new_user(bot, db, user):
    admins = await get_users_by_role(db, UserRole.admin)
    supers = await get_users_by_role(db, UserRole.superadmin)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"newuser_accept_{user.id}"),
            InlineKeyboardButton(text="❌ Rad etish",    callback_data=f"newuser_reject_{user.id}"),
        ],
        [InlineKeyboardButton(text="🚫 Spam",           callback_data=f"newuser_spam_{user.id}")],
    ])
    text = (
        f"👤 Yangi foydalanuvchi!\n\n"
        f"Ism:    {user.full_name}\n"
        f"ID:     {user.telegram_id}\n"
        f"Tel:    {user.phone or '—'}\n\n"
        f"Nima qilasiz?"
    )
    seen = set()
    for a in admins + supers:
        if a.telegram_id in seen:
            continue
        seen.add(a.telegram_id)
        await _safe_send(bot, a.telegram_id, text, reply_markup=kb)


# ═══ /START ═══════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: AsyncSession):
    await state.clear()
    tg_id = message.from_user.id
    user  = await get_user(db, tg_id)

    # Mavjud va faol foydalanuvchi
    if user and user.is_active:
        await message.answer(
            f"Xush kelibsiz, {user.full_name}!",
            reply_markup=get_main_menu(user.role),
        )
        return

    # Avtomatik rol tayinlash (admin, omborchi, nazoratchi)
    auto_role = _auto_role(tg_id)
    if auto_role:
        if user:
            user.role      = auto_role
            user.is_active = True
            if not user.full_name:
                user.full_name = message.from_user.full_name or "Noma'lum"
        else:
            user = User(
                telegram_id=tg_id,
                full_name=message.from_user.full_name or "Noma'lum",
                role=auto_role,
                is_active=True,
            )
            db.add(user)
        await db.commit()  # TUZATILDI: commit qo'shildi
        await message.answer(
            f"✅ Xush kelibsiz!\nRolingiz: {auto_role.value}",
            reply_markup=get_main_menu(auto_role),
        )
        return

    # Yangi foydalanuvchi — ro'yxatdan o'tish
    await message.answer(
        "Salom! Quti tsexiga xush kelibsiz.\n\n"
        "To'liq ismingizni kiriting (familiya va ism):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(RegisterStates.waiting_name)


@router.message(RegisterStates.waiting_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 5:
        await message.answer("Kamida 5 harf kiriting (familiya va ism):"); return
    await state.update_data(full_name=name)
    await message.answer(
        "Telefon raqamingizni kiriting:\n"
        "(Yoki - bosing agar raqam bo'lmasa)",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(RegisterStates.waiting_phone)


@router.message(RegisterStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext, db: AsyncSession):
    if message.text == "Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        return

    data  = await state.get_data()
    phone = None if message.text.strip() == "-" else message.text.strip()

    user = await get_user(db, message.from_user.id)
    if user:
        user.full_name = data["full_name"]
        user.phone     = phone
        user.is_active = False
    else:
        user = User(
            telegram_id=message.from_user.id,
            full_name=data["full_name"],
            phone=phone,
            role=UserRole.ishchi,
            is_active=False,
        )
        db.add(user)

    await db.flush()
    await db.commit()  # TUZATILDI: commit qo'shildi
    await state.clear()

    await message.answer(
        f"✅ Ma'lumotlaringiz qabul qilindi!\n\n"
        f"👤 {data['full_name']}\n"
        f"📞 {phone or '—'}\n\n"
        f"Admin ko'rib chiqadi, biroz kuting...",
        reply_markup=ReplyKeyboardRemove(),
    )
    await _notify_admins_new_user(message.bot, db, user)


# ═══ YANGI FOYDALANUVCHI TASDIQLASH ══════════════════════════════════════════

def _parse_newuser_id(callback_data: str) -> int | None:
    """
    "newuser_accept_123" → 123
    TUZATILDI: split("_", 2)[-1] — xavfsiz, ID qancha uzun bo'lsa ham ishlaydi
    """
    try:
        parts = callback_data.split("_", 2)  # max 3 qism
        return int(parts[2])
    except (IndexError, ValueError):
        return None


@router.callback_query(F.data.startswith("newuser_accept_"))
async def newuser_accept(cb: CallbackQuery, db: AsyncSession):
    admin = await get_user(db, cb.from_user.id)
    if not admin or admin.role not in (UserRole.admin, UserRole.superadmin):
        await cb.answer("Ruxsat yo'q"); return

    user_id = _parse_newuser_id(cb.data)
    if not user_id:
        await cb.answer("ID xato"); return

    r    = await db.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        await cb.answer("Topilmadi"); return

    user.role      = UserRole.ishchi
    user.is_active = True
    await db.commit()  # TUZATILDI

    await _safe_send(
        cb.bot, user.telegram_id,
        f"🎉 Tabriklaymiz, {user.full_name}!\n"
        f"Siz ishchi sifatida qabul qilindingiz.",
        reply_markup=get_main_menu(UserRole.ishchi),
    )
    try:
        await cb.message.edit_text(
            cb.message.text + f"\n\n✅ Qabul qilindi ({admin.full_name})",
            reply_markup=None,
        )
    except Exception:
        pass
    await cb.answer(f"✅ {user.full_name} qabul!")


@router.callback_query(F.data.startswith("newuser_reject_"))
async def newuser_reject(cb: CallbackQuery, db: AsyncSession):
    admin = await get_user(db, cb.from_user.id)
    if not admin or admin.role not in (UserRole.admin, UserRole.superadmin):
        await cb.answer("Ruxsat yo'q"); return

    user_id = _parse_newuser_id(cb.data)
    if not user_id:
        await cb.answer("ID xato"); return

    r    = await db.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        await cb.answer("Topilmadi"); return

    tg_id = user.telegram_id
    name  = user.full_name

    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()  # TUZATILDI

    await _safe_send(cb.bot, tg_id, "❌ Kechirasiz, arizangiz rad etildi.")
    try:
        await cb.message.edit_text(
            cb.message.text + f"\n\n❌ Rad etildi ({admin.full_name})",
            reply_markup=None,
        )
    except Exception:
        pass
    await cb.answer(f"❌ {name} rad!")


@router.callback_query(F.data.startswith("newuser_spam_"))
async def newuser_spam(cb: CallbackQuery, db: AsyncSession):
    admin = await get_user(db, cb.from_user.id)
    if not admin or admin.role not in (UserRole.admin, UserRole.superadmin):
        await cb.answer("Ruxsat yo'q"); return

    user_id = _parse_newuser_id(cb.data)
    if not user_id:
        await cb.answer("ID xato"); return

    r    = await db.execute(select(User).where(User.id == user_id))
    user = r.scalar_one_or_none()
    if not user:
        await cb.answer("Topilmadi"); return

    tg_id = user.telegram_id
    name  = user.full_name

    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()  # TUZATILDI

    await _safe_send(
        cb.bot, tg_id,
        "⛔ Siz bu botdan foydalanish huquqiga ega emassiz.",
    )
    try:
        await cb.message.edit_text(
            cb.message.text + f"\n\n🚫 Spam ({admin.full_name})",
            reply_markup=None,
        )
    except Exception:
        pass
    await cb.answer(f"🚫 {name} spam!")
