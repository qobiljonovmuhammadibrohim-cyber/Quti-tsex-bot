"""
state_reset_middleware.py — FSM holatni avtomatik tozalash
Foydalanuvchi FSM holatda turganda (masalan raqam kutilayotganda)
asosiy menyu tugmasini bossa, holat avtomatik tozalanadi va
menyu buyrugi normal ishlaydi.
"""
import logging
from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.keyboards.main_keyboards import is_main_menu_button

logger = logging.getLogger(__name__)


class StateResetMiddleware(BaseMiddleware):
    """Asosiy menyu tugmasi bosilganda FSM holatni tozalaydi."""

    async def __call__(self, handler, event, data):
        # Faqat Message va text bo'lsa
        if isinstance(event, Message) and event.text:
            if is_main_menu_button(event.text):
                state: FSMContext = data.get("state")
                if state is not None:
                    current = await state.get_state()
                    if current is not None:
                        await state.clear()
                        logger.info(
                            "FSM holat tozalandi (menyu tugmasi: %s)",
                            event.text,
                        )
        return await handler(event, data)
