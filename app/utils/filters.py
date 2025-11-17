import os
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

# Читаем из .env
ADMIN_IDS = [int(uid) for uid in os.getenv("ADMIN_IDS", "").split(",") if uid.strip()]


class IsAdmin(BaseFilter):
    """Фильтр админа — проверка по ID из .env"""
    
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        return user_id in ADMIN_IDS


async def get_my_user_id(message: Message):
    """Команда /id — показывает Telegram ID"""
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n\n"
        "Если вы админ — используйте /admin",
        parse_mode="HTML"
    )