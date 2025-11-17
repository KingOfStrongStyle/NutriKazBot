from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.database.models import LeadSource
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.crud_admin import get_lead_sources


# =============================================================================
# INLINE KEYBOARD MARKUPS
# =============================================================================

class InlineKeyboards:
    @staticmethod
    def main_menu(stage: str = "stage1") -> InlineKeyboardMarkup:
        """ГЛАВНОЕ МЕНЮ — кнопки по этапу"""
        buttons = []

        if stage == "stage1":
            buttons.append([InlineKeyboardButton(text="🎥 Вебинар", callback_data="want_participate")])
        elif stage == "stage2":
            buttons.append([InlineKeyboardButton(text="🔥 Присоединиться к мини-челленджу", callback_data="join_challenge")])
        elif stage == "stage3":
            buttons.append([InlineKeyboardButton(text="🎓 Бесплатный урок", callback_data="get_free_lesson")])

        buttons.extend([
            [InlineKeyboardButton(text="💎 Купить курс", callback_data="buy_course")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def buy_course() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить курс", callback_data="buy_course")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])

    @staticmethod
    def admin_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Источники лидов", callback_data="lead_source_menu"),
                InlineKeyboardButton(text="📨 Сообщения", callback_data="message_menu")
            ],
            [
                InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast_menu"),
                InlineKeyboardButton(text="👥 Пользователи", callback_data="users_menu")
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])

    @staticmethod
    def lead_magnet_lesson() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить полный курс", callback_data="buy_course")],
            [InlineKeyboardButton(text="💬 Оставить отзыв", callback_data="lead_feedback")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])

    @staticmethod
    def lead_magnet_feedback() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1️⃣ Дефицит", callback_data="feedback_1")],
            [InlineKeyboardButton(text="2️⃣ Гормоны", callback_data="feedback_2")],
            [InlineKeyboardButton(text="3️⃣ Психология", callback_data="feedback_3")],
            [InlineKeyboardButton(text="💎 Купить курс", callback_data="buy_course")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])

    @staticmethod
    def post_webinar_keyboard(after_webinar: bool = False, record_link: str = None) -> InlineKeyboardMarkup:
        """Клавиатура после регистрации / вебинара"""
        buttons = []
        if after_webinar and record_link:
            buttons.append([InlineKeyboardButton(text="▶️ Смотреть запись", url=record_link)])

        buttons.extend([
            [InlineKeyboardButton(text="💎 Купить курс", callback_data="buy_course")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def challenge_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Чат участников", url="https://t.me/nutrikaz")],
            [InlineKeyboardButton(text="💎 Купить курс", callback_data="buy_course")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])


# =============================================================================
# REPLY KEYBOARD MARKUPS
# =============================================================================

class ReplyKeyboards:
    @staticmethod
    def get_keyboard(
        *btns: str,
        placeholder: Optional[str] = None,
        request_contact: Optional[int] = None,
        request_location: Optional[int] = None,
        sizes: tuple[int, ...] = (2,)
    ) -> ReplyKeyboardMarkup:
        kb = ReplyKeyboardBuilder()
        for i, text in enumerate(btns):
            if request_contact == i:
                kb.add(KeyboardButton(text=text, request_contact=True))
            elif request_location == i:
                kb.add(KeyboardButton(text=text, request_location=True))
            else:
                kb.add(KeyboardButton(text=text))
        return kb.adjust(*sizes).as_markup(resize_keyboard=True, input_field_placeholder=placeholder)

    @staticmethod
    def admin_main() -> ReplyKeyboardMarkup:
        return ReplyKeyboards.get_keyboard(
            "📋 Источники лидов",
            "📨 Персональные сообщения",
            "📢 Массовая рассылка",
            "👥 Пользователи",
            "🛠 Изменить тексты",
            placeholder="Выберите раздел",
            sizes=(2,)
        )

    @staticmethod
    def main_menu() -> ReplyKeyboardMarkup:
        return ReplyKeyboards.get_keyboard(
            "🎥 Вебинар",
            "🎓 Бесплатный урок",
            "🔥 Мини-челлендж",
            "💎 Купить курс",
            placeholder="Выберите действие",
            sizes=(2,)
        )

    @staticmethod
    def back_to_menu() -> ReplyKeyboardMarkup:
        return ReplyKeyboards.get_keyboard("🏠 Главное меню", placeholder="Вернуться", sizes=(1,))

    @staticmethod
    def phone_request() -> ReplyKeyboardMarkup:
        return ReplyKeyboards.get_keyboard(
            "📱 Отправить телефон",
            "❌ Отмена",
            request_contact=0,
            placeholder="Нажмите для отправки",
            sizes=(1,)
        )


# =============================================================================
# ДИНАМИЧЕСКИЕ КЛАВИАТУРЫ
# =============================================================================

class DynamicKeyboards:
    @staticmethod
    async def lead_sources(session: AsyncSession) -> InlineKeyboardMarkup:
        leads = await get_lead_sources(session)
        kb = []
        for lead in leads:
            kb.append([InlineKeyboardButton(text=f"📊 {lead.name}", callback_data=f"select_lead_{lead.id}")])
        kb.extend([
            [InlineKeyboardButton(text="📢 Всем пользователям", callback_data="broadcast_all")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="broadcast_menu")]
        ])
        return InlineKeyboardMarkup(inline_keyboard=kb)

    @staticmethod
    def pagination(page: int, total_pages: int) -> InlineKeyboardMarkup:
        kb = []
        if page > 1:
            kb.append([InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"page_leads_{page-1}")])
        kb.append([InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="current_page")])
        if page < total_pages:
            kb.append([InlineKeyboardButton(text="➡️ Следующая", callback_data=f"page_leads_{page+1}")])
        return InlineKeyboardMarkup(inline_keyboard=kb)

    @staticmethod
    def users_by_lead(leads: List[LeadSource]) -> InlineKeyboardMarkup:
        kb = []
        for lead in leads:
            kb.append([InlineKeyboardButton(text=f"📋 {lead.name}", callback_data=f"filter_users_{lead.id}")])
        kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="users_menu")])
        return InlineKeyboardMarkup(inline_keyboard=kb)


# =============================================================================
# АДМИН КЛАВИАТУРЫ — С ЭМОДЗИ
# =============================================================================

class AdminKeyboards:
    @staticmethod
    def lead_source_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать источник", callback_data="create_lead_source")],
            [InlineKeyboardButton(text="📋 Посмотреть все", callback_data="view_leads")],
            [InlineKeyboardButton(text="🗑 Удалить источник", callback_data="delete_lead_menu")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
        ])

    @staticmethod
    def message_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📨 Отправить сообщение", callback_data="send_message")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
        ])

    @staticmethod
    def broadcast_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Создать рассылку", callback_data="create_broadcast")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
        ])

    @staticmethod
    def users_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Все пользователи", callback_data="users_all")],
            [InlineKeyboardButton(text="📋 По источнику лидов", callback_data="users_by_lead")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
        ])

    @staticmethod
    def broadcast_type_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Текст", callback_data="broadcast_text"),
                InlineKeyboardButton(text="🖼️ Картинка", callback_data="broadcast_image")
            ],
            [
                InlineKeyboardButton(text="📎 Файл", callback_data="broadcast_file"),
                InlineKeyboardButton(text="🎥 Видео", callback_data="broadcast_video")
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="create_broadcast")]
        ])

    @staticmethod
    def personal_message() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Текст", callback_data="message_text"),
                InlineKeyboardButton(text="🖼️ Картинка", callback_data="message_image")
            ],
            [
                InlineKeyboardButton(text="📎 Файл", callback_data="message_file"),
                InlineKeyboardButton(text="🎥 Видео", callback_data="message_video")
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")]
        ])
