import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.crud_user import get_user_by_id
from app.database.crud_admin import add_message_schedule, add_lead_magnet_stat
from app.kbds.kbds import InlineKeyboards

from app.database.state import LeadMagnetState

logger = logging.getLogger(__name__)
lead_magnet_router = Router()

# =============================================================================
# КОНФИГУРАЦИЯ — РЕАЛЬНЫЕ ДАТЫ (14–17 НОЯБРЯ)
# =============================================================================
ALMATY_TZ = ZoneInfo("Asia/Almaty")
NOW = datetime.now(ALMATY_TZ)

LESSON_START = NOW.replace(year=2025, month=11, day=14, hour=10, minute=0, second=0, microsecond=0)
LESSON_END = NOW.replace(year=2025, month=11, day=17, hour=23, minute=59, second=0, microsecond=0)
COURSE_START_DATE = "17 ноября"

COURSE_LINK = "https://www.nutrikaz.kz/#rec1462578793"
LESSON_LINK = "https://drive.google.com/drive/folders/1kR_CjWykuQuE4yk1L9PWUVpiYp2MCgZA"

# =============================================================================
# СООБЩЕНИЯ — ОБНОВЛЁННЫЕ ТЕКСТЫ С ЭМОДЗИ
# =============================================================================
LEAD_MAGNET_TEXTS = {
    "welcome": (
        "🎬 <b>Ваш бесплатный урок «Причины переедания» готов!</b>\n\n"
        "📚 Это фрагмент проекта <b>«Наука тела»</b> — система устойчивого снижения веса.\n"
        "⏰ Доступ открыт с <b>14 ноября, 10:00</b>\n\n"
        "💡 За 20 минут вы узнаете:\n"
        "• Почему вы переедаете и как с этим справляться\n"
        "• Почему 90% диет терпят крах\n"
        "• 1-й принцип научного похудения\n"
        "• Ваш старт к стройности\n\n"
        f"🎥 <a href='{LESSON_LINK}'>Смотреть урок</a>\n"
        f"💰 <a href='{COURSE_LINK}'>Купить полный доступ</a>\n\n"
        f"🗓 Полная программа стартует {COURSE_START_DATE}."
    ),

    "reminder": (
        "⏰ <b>Успели посмотреть бесплатный урок?</b>\n\n"
        f"🎥 <a href='{LESSON_LINK}'>Перейти к просмотру</a>\n\n"
        "💬 Что было самым полезным?\n"
        "1️⃣ Причины провала диет\n"
        "2️⃣ Роль гормонов\n"
        "3️⃣ Психология питания\n\n"
        "<i>Ответьте нажав кнопку 💬 Оставить отзыв — поделитесь впечатлением!</i>"
    ),

    "feedback_thanks": (
        "🙏 <b>Спасибо за обратную связь!</b>\n\n"
        "🚀 <b>Готовы начать путь к снижению веса?</b>\n"
        f"Проект <b>«Наука тела»</b> стартует {COURSE_START_DATE}\n"
        f"💰 <a href='{COURSE_LINK}'>Купить доступ</a>\n\n"
        "💫 <b>Проект «Наука тела» — системное похудение без стресса</b>\n"
        "🚀 30 дней = результат 3–7 кг\n"
        f"🗓 Старт: {COURSE_START_DATE}\n\n"
        "💰 <b>Тарифы:</b>\n"
        "🔹 <b>Поддержка — 17 000 ₸</b>\n"
        "• 7 уроков + 2 групповых созвона\n"
        "• Рабочая тетрадь, рецепты, трекеры\n"
        "• Чат 24/7\n"
        "• Доступ 3 месяца\n\n"
        "🔥 <b>Глубина — 37 000 ₸</b>\n"
        "• Всё из тарифа «Поддержка»\n"
        "• +3 бонусных модуля\n"
        "• 4 созвона в мини-группе\n"
        "• Индивидуальная обратная связь\n"
        "• Доступ 6 месяцев"
    ),
}

# =============================================================================
# ПЛАНИРОВАНИЕ СООБЩЕНИЙ
# =============================================================================
async def schedule_lead_magnet_messages(session: AsyncSession, user: User, state: FSMContext):
    try:
        now = datetime.now(ALMATY_TZ)
        lesson_time = now + timedelta(minutes=1)
        reminder_time = now + timedelta(days=2)

        reminders = [
            (lesson_time, "welcome"),
            (reminder_time, "reminder"),
        ]

        for scheduled_at, text_key in reminders:
            if scheduled_at > now:
                text = LEAD_MAGNET_TEXTS.get(text_key, f"[ОШИБКА: нет текста {text_key}]")
                await add_message_schedule(
                    session=session,
                    user_id=user.id,
                    message_text=text,
                    scheduled_at=scheduled_at.replace(tzinfo=ALMATY_TZ)
                )

        await session.commit()
        logger.info(f"Лид-магнит запланирован (этап 3): user {user.user_id} | урок: {lesson_time.strftime('%d.%m %H:%M')}")
    except Exception as e:
        await session.rollback()
        logger.error(f"Ошибка планирования лид-магнита: {e}")

# =============================================================================
# СТАТИСТИКА
# =============================================================================
async def _track_lead_magnet_stat(session: AsyncSession, user_id: int, stage: str, **kwargs):
    try:
        await add_lead_magnet_stat(
            session=session,
            user_id=user_id,
            template_version="a",
            stage=stage,
            viewed=kwargs.get("viewed", False),
            feedback_type=kwargs.get("feedback_type")
        )
    except Exception as e:
        logger.error(f"Ошибка записи статистики: {e}")

# =============================================================================
# ХЕНДЛЕРЫ
# =============================================================================
@lead_magnet_router.callback_query(F.data == "get_free_lesson")
async def lead_magnet_registration(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    user = await get_user_by_id(session, callback.from_user.id)
    if not user:
        await callback.answer("Ошибка: пользователь не найден.")
        return

    await _track_lead_magnet_stat(session, user.user_id, "welcome", viewed=False)
    await session.commit()

    await schedule_lead_magnet_messages(session, user, state)

    await callback.message.answer(
        "🎬 Бесплатный урок активирован!\nОн придёт через несколько минут ⏰",
        reply_markup=InlineKeyboards.lead_magnet_lesson()
    )
    await callback.answer("Готово!")

@lead_magnet_router.callback_query(F.data == "lead_feedback")
async def lead_feedback_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(LeadMagnetState.feedback)
    await callback.message.answer(
        LEAD_MAGNET_TEXTS["reminder"],
        parse_mode="HTML",
        reply_markup=InlineKeyboards.lead_magnet_feedback()
    )
    await callback.answer()

@lead_magnet_router.callback_query(LeadMagnetState.feedback, F.data.startswith("feedback_"))
async def process_feedback(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        feedback_type = callback.data.split("_")[1]
        user = await get_user_by_id(session, callback.from_user.id)

        await _track_lead_magnet_stat(
            session, user.user_id, "feedback",
            feedback_type=feedback_type, viewed=True
        )
        await session.commit()

        await callback.message.answer(
            LEAD_MAGNET_TEXTS["feedback_thanks"],
            parse_mode="HTML",
            reply_markup=InlineKeyboards.lead_magnet_lesson()
        )
    finally:
        await state.clear()
    await callback.answer("Спасибо!")

# =============================================================================
# РЕГИСТРАЦИЯ ХЕНДЛЕРОВ
# =============================================================================
def register_lead_magnet_handlers(router: Router):
    router.include_router(lead_magnet_router)
    return router
