"""search.py — Omborchi uchun mahsulot qidiruvi"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import UserRole, WarehouseProduct, WarehouseLog, ProductCategory
from database.queries import get_user, get_product_by_id, search_products, update_product_miqdor

logger = logging.getLogger(__name__)
router = Router()

ALLOWED_ROLES = (UserRole.omborchi, UserRole.admin, UserRole.superadmin)

CAT_NAMES = {
    "rulon":"Rulonlar","gofra":"Gofralar","gofra_zagatovka":"Zagatovkalar",
    "xromazes":"Xromazeslar","laminat_xromazes":"Laminat","yarim_tayyor":"Yarim tayyor",
    "qolip":"Qoliplar","tayyor_mahsulot":"Tayyor","adyol_zapchast":"Adyol zapchast",
    "uskuna_zapchast":"Uskuna zapchast",
}

def status_icon(miqdor, min_t, yellow_t):
    if miqdor <= min_t:    return "🔴"
    if miqdor <= yellow_t: return "🟡"
    return "🟢"


class SearchStates(StatesGroup):
    waiting_query   = State()
    showing_results = State()
    kirim_miqdor    = State()
    chiqim_miqdor   = State()


@router.message(F.text == "Mahsulot qidirish")
async def search_start(message: Message, state: FSMContext, db: AsyncSession):
    user = await get_user(db, message.from_user.id)
    if not user or user.role not in ALLOWED_ROLES:
        await message.answer("Ruxsat yoq."); return
    await state.update_data(user_id=user.id)
    await message.answer(
        "Mahsulot qidirish\n\nQidiruv sozini kiriting:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Rulonlar",    callback_data="srch_cat_rulon"),
             InlineKeyboardButton(text="Gofralar",    callback_data="srch_cat_gofra")],
            [InlineKeyboardButton(text="Xromazeslar", callback_data="srch_cat_xromazes"),
             InlineKeyboardButton(text="Yarim tayyor",callback_data="srch_cat_yarim_tayyor")],
            [InlineKeyboardButton(text="Tayyor",      callback_data="srch_cat_tayyor_mahsulot"),
             InlineKeyboardButton(text="Kam qolgan",  callback_data="srch_holat_kam")],
            [InlineKeyboardButton(text="Barchasi",    callback_data="srch_all"),
             InlineKeyboardButton(text="Bekor",       callback_data="srch_cancel")],
        ]))
    await state.set_state(SearchStates.waiting_query)


@router.message(SearchStates.waiting_query)
async def search_query(message: Message, state: FSMContext, db: AsyncSession):
    if message.text == "Bekor qilish":
        await state.clear(); await message.answer("Bekor qilindi."); return
    await _show_search_results(message, state, db, query=message.text.strip())


@router.callback_query(F.data.startswith("srch_"), SearchStates.waiting_query)
async def search_by_category(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data_str = cb.data[5:]
    if data_str == "cancel":
        await state.clear(); await cb.message.answer("Bekor qilindi."); await cb.answer(); return
    if data_str == "all": await _show_search_results(cb.message, state, db)
    elif data_str.startswith("cat_"): await _show_search_results(cb.message, state, db, category=data_str[4:])
    elif data_str.startswith("holat_"): await _show_search_results(cb.message, state, db, holat=data_str[6:])
    await cb.answer()


async def _show_search_results(target, state, db, query=None, category=None, holat=None, page=1):
    per_page = 8; offset = (page-1)*per_page
    cat_enum = None
    if category:
        try: cat_enum = ProductCategory(category)
        except ValueError: pass
    products, total = await search_products(db, query=query, category=cat_enum, holat=holat, limit=per_page, offset=offset)
    if not products:
        text = "Mahsulot topilmadi."
        if isinstance(target, Message): await target.answer(text)
        else: await target.answer(text)
        return
    await state.update_data(srch_query=query, srch_category=category, srch_holat=holat, srch_page=page)
    text = f"Natijalar ({total} ta)\n\n"
    buttons = []
    for p in products:
        icon  = status_icon(p.miqdor, p.min_threshold, p.yellow_threshold)
        label = f"{icon} {p.name}"
        if p.razmer: label += f" | {p.razmer}"
        label += f" — {p.miqdor:.1f} {p.birlik}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"srch_prod_{p.id}")])
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton(text="Oldingi", callback_data=f"srch_page_{page-1}"))
    if total > offset+per_page: nav_row.append(InlineKeyboardButton(text="Keyingisi", callback_data=f"srch_page_{page+1}"))
    if nav_row: buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="Yangi qidiruv", callback_data="srch_new"),
                    InlineKeyboardButton(text="Yopish",         callback_data="srch_close")])
    if isinstance(target, Message):
        await target.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        try: await target.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception: await target.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("srch_page_"))
async def search_page(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    page = int(cb.data.split("_")[2]); data = await state.get_data()
    await _show_search_results(cb.message, state, db, query=data.get("srch_query"), category=data.get("srch_category"), holat=data.get("srch_holat"), page=page)
    await cb.answer()


@router.callback_query(F.data == "srch_new")
async def search_new(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("Yangi qidiruv:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Bekor", callback_data="srch_close")]]))
    await state.set_state(SearchStates.waiting_query); await cb.answer()


@router.callback_query(F.data == "srch_close")
async def search_close(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try: await cb.message.delete()
    except Exception: pass
    await cb.answer("Yopildi")


@router.callback_query(F.data.startswith("srch_prod_"))
async def search_product_detail(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid     = int(cb.data.split("_")[2])
    product = await get_product_by_id(db, pid)
    if not product: await cb.answer("Topilmadi"); return
    icon = status_icon(product.miqdor, product.min_threshold, product.yellow_threshold)
    cat_name = CAT_NAMES.get(product.category.value, product.category.value)
    r = await db.execute(select(WarehouseLog).where(WarehouseLog.product_id==pid).order_by(WarehouseLog.created_at.desc()).limit(3))
    logs = r.scalars().all()
    text = f"{product.name}\n{cat_name}\n"
    if product.razmer: text += f"Razmer: {product.razmer}\n"
    text += f"{icon} Qoldiq: {product.miqdor} {product.birlik}\n"
    if logs:
        text += "\nSo'nggi:\n"
        for log in logs:
            sign = "+" if log.amal=="kirim" else "-"
            text += f"  {sign}{log.miqdor} ({log.created_at.strftime('%d.%m %H:%M') if log.created_at else '-'})\n"
    await state.update_data(srch_detail_pid=pid)
    await cb.message.answer(text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Kirim",   callback_data=f"srch_kirim_{pid}"),
             InlineKeyboardButton(text="Chiqim",  callback_data=f"srch_chiqim_{pid}")],
            [InlineKeyboardButton(text="Orqaga",  callback_data="srch_back")],
        ]))
    await cb.answer()


@router.callback_query(F.data == "srch_back")
async def search_back(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    data = await state.get_data()
    await _show_search_results(cb.message, state, db, query=data.get("srch_query"), category=data.get("srch_category"), holat=data.get("srch_holat"), page=data.get("srch_page",1))
    await cb.answer()


@router.callback_query(F.data.startswith("srch_kirim_"))
async def srch_kirim_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2]); product = await get_product_by_id(db, pid)
    if not product: await cb.answer("Topilmadi"); return
    await state.update_data(srch_amal_pid=pid, srch_amal="kirim")
    await cb.message.answer(f"{product.name} kirim miqdori:\nJoriy: {product.miqdor} {product.birlik}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Bekor",callback_data="srch_amal_cancel")]]))
    await state.set_state(SearchStates.kirim_miqdor); await cb.answer()


@router.message(SearchStates.kirim_miqdor)
async def srch_kirim_miq(message: Message, state: FSMContext, db: AsyncSession):
    try: miq = float(message.text.replace(",",".")); assert miq > 0
    except: await message.answer("To'g'ri musbat son kiriting:"); return
    data    = await state.get_data()
    product = await update_product_miqdor(db, data["srch_amal_pid"], miq, data["user_id"], izoh="Bot qidiruv — kirim")
    await db.commit()
    await message.answer(f"Kirim saqlandi!\n{product.name}\nYangi qoldiq: {product.miqdor} {product.birlik}")
    await state.set_state(SearchStates.waiting_query)


@router.callback_query(F.data.startswith("srch_chiqim_"))
async def srch_chiqim_start(cb: CallbackQuery, state: FSMContext, db: AsyncSession):
    pid = int(cb.data.split("_")[2]); product = await get_product_by_id(db, pid)
    if not product: await cb.answer("Topilmadi"); return
    await state.update_data(srch_amal_pid=pid, srch_amal="chiqim")
    await cb.message.answer(f"{product.name} chiqim miqdori:\nJoriy: {product.miqdor} {product.birlik}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Bekor",callback_data="srch_amal_cancel")]]))
    await state.set_state(SearchStates.chiqim_miqdor); await cb.answer()


@router.message(SearchStates.chiqim_miqdor)
async def srch_chiqim_miq(message: Message, state: FSMContext, db: AsyncSession):
    try: miq = float(message.text.replace(",",".")); assert miq > 0
    except: await message.answer("To'g'ri musbat son kiriting:"); return
    data    = await state.get_data()
    product = await get_product_by_id(db, data["srch_amal_pid"])
    if not product:
        await message.answer("Mahsulot topilmadi!"); await state.set_state(SearchStates.waiting_query); return
    if float(product.miqdor) < miq:
        await message.answer(
            f"Yetarli mahsulot yo'q!\n\n"
            f"Omborda: {product.miqdor} {product.birlik}\n"
            f"Soralgan: {miq}\n\n"
            f"Iltimos, {product.miqdor} dan kam miqdor kiriting:"); return
    product = await update_product_miqdor(db, data["srch_amal_pid"], -miq, data["user_id"], izoh="Bot qidiruv — chiqim")
    await db.commit()
    await message.answer(f"Chiqim saqlandi!\n{product.name}\nYangi qoldiq: {product.miqdor} {product.birlik}")
    await state.set_state(SearchStates.waiting_query)


@router.callback_query(F.data == "srch_amal_cancel")
async def srch_amal_cancel(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_query); await cb.message.answer("Bekor qilindi."); await cb.answer()
