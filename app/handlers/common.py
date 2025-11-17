import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.crud_user import add_user, get_user_by_id
from app.database.crud_admin import (
    get_lead_source_by_name,
    assign_user_to_lead_source,
    get_stage_text
)

# Импорт функций для обработки воронок
from app.handlers.webinar import RECORD_LINK, WEBINAR_DATETIME, WEBINAR_TEXTS, schedule_webinar_reminders
from app.handlers.challenge import register_challenge
from app.handlers.lead_magnet import schedule_lead_magnet_messages

from app.kbds.kbds import InlineKeyboards, ReplyKeyboards

# =============================================================================
# НАСТРОЙКИ
# =============================================================================
logger = logging.getLogger(__name__)
common_router = Router()
ALMATY_TZ = ZoneInfo("Asia/Almaty")

# =============================================================================
# ОПРЕДЕЛЕНИЕ ТЕКУЩЕГО ЭТАПА ПО РЕАЛЬНЫМ ДАТАМ
# =============================================================================
def get_current_stage() -> str:
    """
    ДАТЫ ПО ТЗ:
    - stage1: с 29 октября → вебинар (6 ноября)
    - stage2: 7–10 ноября → мини-челлендж
    - stage3: 14–17 ноября → бесплатный урок
    """
    now = datetime.now(ALMATY_TZ)

    # stage1: с 29 октября до 7 ноября (до начала stage2)
    if datetime(2025, 10, 29, 0, 0, tzinfo=ALMATY_TZ) <= now < datetime(2025, 11, 7, 0, 0, tzinfo=ALMATY_TZ):
        return "stage1"

    # stage2: 7–12 ноября
    elif datetime(2025, 11, 7, 0, 0, tzinfo=ALMATY_TZ) <= now < datetime(2025, 11, 13, 0, 0, tzinfo=ALMATY_TZ):
        return "stage2"

    # stage3: 14–17 ноября
    elif datetime(2025, 11, 14, 0, 0, tzinfo=ALMATY_TZ) <= now < datetime(2025, 11, 18, 0, 0, tzinfo=ALMATY_TZ):
        return "stage3"


# =============================================================================
# ОБРАБОТЧИК КОМАНДЫ /START
# =============================================================================

@common_router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext):
    """
    Обрабатывает команду /start с поддержкой deep link.
    Пример: /start lead_magnet → сразу запускает лид-магнит.
    """
    try:
        # Парсинг deep link
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        lead_source_name = args[0].lower() if args else None
        
        # Валидация источника
        valid_sources = ["webinar", "lead_magnet", "challenge"]
        if lead_source_name and lead_source_name not in valid_sources:
            lead_source_name = None
        
        # Регистрация пользователя
        user = await add_user(
            session=session,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            lead_source_id=None
        )
        
        # Обработка deep link
        if lead_source_name:
            await _handle_deep_link_flow(message, session, state, user, lead_source_name)
            return
        
        # Показываем главное меню
        await _show_main_menu_by_stage(message, session)
        
        logger.info(f"Пользователь {user.user_id} открыл главное меню")
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_start: {e}")
        await message.answer(
            "Ошибка регистрации. Попробуйте /start еще раз.",
            reply_markup=ReplyKeyboards.back_to_menu()
        )


async def _handle_deep_link_flow(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    user,
    lead_source_name: str
):
    """
    Обрабатывает deep link:
    - Привязывает пользователя к воронке
    - Показывает приветствие
    - Запускает соответствующую рассылку
    """
    lead_source = await get_lead_source_by_name(session, lead_source_name)
    if not lead_source:
        await message.answer("Источник не найден")
        return
    
    await assign_user_to_lead_source(session, user.user_id, lead_source_name)
    await session.commit()
    
    # Приветствие из БД
    stage_map = {"webinar": "stage1", "challenge": "stage2", "lead_magnet": "stage3"}
    stage_text = await get_stage_text(session, stage_map[lead_source_name])
    welcome_text = stage_text.welcome_text if stage_text else "Добро пожаловать!"

    await message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=ReplyKeyboards.back_to_menu()
    )
    
    # Запуск воронки
    if lead_source_name == "webinar":
        await schedule_webinar_reminders(session, user, state)
    elif lead_source_name == "lead_magnet":
        await schedule_lead_magnet_messages(session, user, state)
    elif lead_source_name == "challenge":
        await register_challenge(session, user)
    
    logger.info(f"Пользователь {user.user_id} начал воронку {lead_source_name}")


async def _show_main_menu_by_stage(message: Message, session: AsyncSession):
    """
    Показывает главное меню с баннером и кнопками,
    соответствующими текущему этапу (stage1/stage2/stage3).
    """
    stage = get_current_stage()
    stage_text = await get_stage_text(session, stage)
    
    if not stage_text:
        await message.answer("Ошибка загрузки меню.")
        return

    caption = stage_text.welcome_text
    banner_path = Path("media/main_banner.jpg")
    main_menu_inline = InlineKeyboards.main_menu(stage)

    if banner_path.exists():
        await message.answer_photo(
            photo=FSInputFile(banner_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=main_menu_inline
        )
    else:
        await message.answer(
            caption,
            parse_mode="HTML",
            reply_markup=main_menu_inline
        )


# =============================================================================
# ОБРАБОТЧИКИ КНОПОК МЕНЮ
# =============================================================================

@common_router.callback_query(F.data == "want_participate")
async def webinar_from_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Кнопка «Хочу на вебинар» — только на stage1"""
    user = await get_user_by_id(session, callback.from_user.id)
    await assign_user_to_lead_source(session, user.user_id, "webinar")
    await session.commit()

    now = datetime.now(ALMATY_TZ)
    after_webinar = now >= WEBINAR_DATETIME + timedelta(hours=1, minutes=30)

    await schedule_webinar_reminders(session, user, state)

    await callback.message.answer(
        WEBINAR_TEXTS["welcome_after_reg"],
        parse_mode="HTML",
        reply_markup=InlineKeyboards.post_webinar_keyboard(
            after_webinar=after_webinar,
            record_link=RECORD_LINK if after_webinar else None
        )
    )
    await callback.answer("Зарегистрированы на вебинар!")


@common_router.callback_query(F.data == "get_free_lesson")
async def lead_magnet_from_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Кнопка «Бесплатный урок» — только на stage3"""
    user = await get_user_by_id(session, callback.from_user.id)
    await assign_user_to_lead_source(session, user.user_id, "lead_magnet")
    await session.commit()
    
    stage_text = await get_stage_text(session, "stage3")
    welcome_text = (
        stage_text.welcome_text 
        if stage_text and stage_text.welcome_text 
        else "Бесплатный урок активирован!\nПридёт через несколько минут"
    )

    try:
        await schedule_lead_magnet_messages(session, user, state)
    except Exception as e:
        logger.error(f"Ошибка планирования лид-магнита: {e}")
        welcome_text = "Ошибка. Попробуйте позже."

    await callback.message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboards.lead_magnet_lesson()
    )
    await callback.answer("Готово!")


@common_router.callback_query(F.data == "join_challenge")
async def challenge_from_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Кнопка «Челлендж» — только на stage2"""
    user_id = callback.from_user.id
    user = await get_user_by_id(session, user_id)
    if not user:
        user = await add_user(
            session=session,
            user_id=user_id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            lead_source_id=None
        )
        await session.commit()
    else:
        await session.refresh(user)

    await assign_user_to_lead_source(session, user.user_id, "challenge")
    await session.commit()

    text = (
        "🎉 <b>Добро пожаловать в мини-челлендж «Наука тела»!</b>\n\n"
        "🍎 3 дня для тебя и твоего тела\n"
        "📅 10–12 ноября\n\n"
        "💡 Что вас ждёт:\n"
        "• Простые рецепты на каждый день\n"
        "• Питание без подсчёта калорий\n"
        "• Результаты уже через 3 дня\n\n"
        "👥 Присоединяйтесь к чату участников — там мы делимся рецептами и поддерживаем друг друга!\n\n"
        "⏰ <b>Старт — 10 ноября, 9:00</b>"
    )

    await register_challenge(session, user)

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboards.challenge_menu()
    )
    await callback.answer("Вы зарегистрированы на мини-челлендж!")


# =============================================================================
# ЕДИНЫЙ ОФФЕР — КУПИТЬ КУРС
# =============================================================================

@common_router.callback_query(F.data == "buy_course")
async def handle_buy_course(callback: CallbackQuery):
    """Единый оффер — покупка курса (доступен на всех этапах)"""
    course_info = (
    "🎓 <b>ЕДИНЫЙ ОФФЕР — КУРС «НАУКА ТЕЛА»</b>\n\n"
    "🌿 <i>Системное похудение без стресса и ограничений</i>\n"
    "📆 <b>Старт: 17 ноября</b>\n"
    "💪 30 дней = результат <b>−3…7 кг</b>\n\n"
    "📦 <b>Тарифы:</b>\n\n"
    "💠 <b>Поддержка — 17 000 ₸</b>\n"
    "• 7 уроков + 2 групповых созвона\n"
    "• Рабочая тетрадь, рецепты, трекеры\n"
    "• Чат 24/7\n"
    "• Доступ 3 месяца\n\n"
    "💎 <b>Глубина — 37 000 ₸</b>\n"
    "• Всё из тарифа «Поддержка»\n"
    "• +3 бонусных модуля\n"
    "• 4 созвона в мини-группе\n"
    "• Индивидуальная обратная связь\n"
    "• Доступ 6 месяцев\n\n"
    "🚀 <b>Оформить участие:</b>\n"
    "👉 <a href='https://www.nutrikaz.kz/#rec1462578793'>Перейти к оплате курса</a>"
    )

    
    await callback.message.answer(
        text=course_info,
        parse_mode="HTML",
        reply_markup=ReplyKeyboards.back_to_menu()
    )
    await callback.answer("Переходим к покупке!")


# =============================================================================
# ВОЗВРАТ В ГЛАВНОЕ МЕНЮ
# =============================================================================

@common_router.callback_query(F.data == "main_menu")
@common_router.message(F.text.contains("Главное меню"))
async def back_to_main_menu(event, session: AsyncSession):
    """Возврат в главное меню — с актуальным этапом"""
    stage = get_current_stage()
    stage_text = await get_stage_text(session, stage)
    
    if not stage_text:
        method = event.answer if isinstance(event, Message) else event.message.answer
        await method(
            "Ошибка загрузки меню.",
            reply_markup=ReplyKeyboards.back_to_menu()
        )
        return

    caption = stage_text.main_menu_text
    banner_path = Path("media/main_banner.jpg")
    main_menu_inline = InlineKeyboards.main_menu(stage)

    if banner_path.exists():
        method = event.answer_photo if isinstance(event, Message) else event.message.answer_photo
        await method(
            photo=FSInputFile(banner_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=main_menu_inline
        )
    else:
        method = event.answer if isinstance(event, Message) else event.message.answer
        await method(
            caption,
            parse_mode="HTML",
            reply_markup=main_menu_inline
        )
    
    if isinstance(event, CallbackQuery):
        await event.answer("Вернулись в меню")

# =============================================================================
# ПОМОЩЬ И НЕИЗВЕСТНЫЕ СООБЩЕНИЯ
# =============================================================================

@common_router.message(Command("help"))
@common_router.message(F.text.in_({"помощь", "/help"}))
async def help_command(message: Message):
    """Команда помощи"""
    await message.answer(
        "<b>Помощь</b>\n\n"
        "• /start — начать\n"
        "• Главное меню — выбрать воронку\n"
        "• Купить курс — оплатить\n\n"
        "Поддержка: @support_nutri",
        parse_mode="HTML",
        reply_markup=ReplyKeyboards.back_to_menu()
    )


@common_router.message()
async def unknown_message(message: Message, session: AsyncSession):
    """Любое неизвестное сообщение"""
    stage = get_current_stage()
    main_menu_inline = InlineKeyboards.main_menu(stage)
    await message.answer(
        "Не понял команду.\nВыберите действие:",
        reply_markup=main_menu_inline
    )