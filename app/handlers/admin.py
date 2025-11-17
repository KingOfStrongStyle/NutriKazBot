from datetime import datetime
from typing import Optional
import logging
from zoneinfo import ZoneInfo

from aiogram import F, Bot, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload


from app.database.state import AdminState  
from app.database.models import LeadSource, User
from app.database.crud_admin import (
    # Источники лидов
    create_empty_lead_source,
    get_all_users_paginated,
    get_feedback_options,
    get_stage_text,
    send_broadcast_now,
    update_feedback_options,
    update_lead_description,
    get_lead_sources,
    delete_lead_source,
    get_lead_source_by_name,

    
    # Пользователи
    get_all_users,
    get_users_by_lead_source,
    
    # Персональные сообщения
    add_message_schedule,
    get_pending_messages,
    delete_message_schedule,
    
    # Массовая рассылка
    add_broadcast,
    get_unsent_broadcasts,
    delete_broadcast,
    update_stage_text,
)

from app.kbds.kbds import (
    DynamicKeyboards,
    AdminKeyboards,
    ReplyKeyboards
)

from app.utils.filters import IsAdmin
from app.utils.paginator import validate_lead_name, paginate 

logger = logging.getLogger(__name__)
admin_router = Router()
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())

# =============================================================================
# ОСНОВНОЕ АДМИН МЕНЮ
# =============================================================================

ADMIN_MAIN_KB = ReplyKeyboards.admin_main()

@admin_router.message(Command("admin"))
async def admin_main_menu(message: Message):
    """Вход в админ-панель."""
    await message.answer(
        "🔐 <b>Административная панель</b>\n\n"
        "Выберите раздел для управления:",
        reply_markup=ADMIN_MAIN_KB,
        parse_mode="HTML"
    )

# =============================================================================
# 1. УПРАВЛЕНИЕ ИСТОЧНИКАМИ ЛИДОВ
# =============================================================================

LEAD_SOURCE_MENU_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ Создать источник", callback_data="create_lead_source")],
    [InlineKeyboardButton(text="📋 Посмотреть все", callback_data="view_leads")],
    [InlineKeyboardButton(text="🗑 Удалить источник", callback_data="delete_lead_menu")],
    [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
])

@admin_router.message(F.text == "📋 Источники лидов")
async def lead_source_menu(message: Message, state: FSMContext):
    """Меню управления источниками лидов."""
    await state.set_state(AdminState.lead_source_menu)
    await message.answer(
        "📋 <b>Управление источниками лидов</b>\n\n"
        "Выберите действие:",
        reply_markup=LEAD_SOURCE_MENU_KB,
        parse_mode="HTML"
    )


@admin_router.callback_query(AdminState.lead_source_menu, F.data == "create_lead_source")
async def create_lead_source_start(callback: CallbackQuery, state: FSMContext):
    """Начало создания источника лидов."""
    await callback.message.answer(
        "➕ <b>Создание источника лидов</b>\n\n"
        "Введите название:\n"
        "Примеры: 'вебинар', 'челлендж', 'лид-магнит':",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_lead_source_name)
    await callback.answer()


@admin_router.message(AdminState.add_lead_source_name)
async def create_lead_source_name(message: Message, state: FSMContext, session: AsyncSession):
    """Шаг 1: Название источника лидов."""
    name = message.text.strip()
    
    if not validate_lead_name(name):
        await message.answer(
            "❌ Название должно быть от 3 до 50 символов,\n"
            "только буквы и цифры (без пробелов)"
        )
        return
    
    name_lower = name.lower().replace("вебинар", "webinar") \
                           .replace("челлендж", "challenge") \
                           .replace("лид-магнит", "lead_magnet")
    
    try:
        lead = await create_empty_lead_source(session, name_lower)  
        await state.update_data(lead_id=lead.id)
        
        await message.answer(
            f"✅ Источник лидов '<b>{name}</b>' создан\n\n"
            "📝 Введите описание (можно пропустить):",
            parse_mode="HTML"
        )
        await state.set_state(AdminState.add_lead_source_description)
        
    except IntegrityError:
        await message.answer(f"❌ Источник лидов '<b>{name}</b>' уже существует")


@admin_router.message(AdminState.add_lead_source_description)
async def create_lead_source_description(message: Message, state: FSMContext, session: AsyncSession):
    """Шаг 2: Описание источника лидов."""
    description = message.text.strip()
    data = await state.get_data()
    
    await update_lead_description(session, data['lead_id'], description)
    
    lead = await session.get(LeadSource, data['lead_id'])
    
    await message.answer(
        f"✅ <b>Источник лидов успешно создан</b>\n\n"
        f"📋 <b>Название:</b> {lead.name}\n"
        f"📝 <b>Описание:</b> {lead.description or 'Не указано'}\n"
        f"🆔 <b>ID:</b> <code>{lead.id}</code>",
        reply_markup=ADMIN_MAIN_KB,
        parse_mode="HTML"
    )
    await state.clear()


@admin_router.callback_query(AdminState.lead_source_menu, F.data == "view_leads")
async def view_lead_sources(callback: CallbackQuery, session: AsyncSession):
    """Просмотр всех источников лидов с пагинацией."""
    result = await session.execute(
        select(LeadSource).options(joinedload(LeadSource.users))
    )
    leads = result.scalars().unique().all()
    
    if not leads:
        await callback.message.answer("📭 Источники лидов не найдены")
        await callback.answer()
        return
    
    page = 1
    paginated = paginate(leads, page, per_page=5)
    
    text = "📋 <b>Источники лидов</b>\n\n"
    for i, lead in enumerate(paginated['items'], 1):
        users_count = len(lead.users)  
        text += f"{i}. <b>{lead.name}</b>\n"
        text += f"   Описание: {lead.description or '—'}\n"
        text += f"   Пользователей: <code>{users_count}</code>\n\n"
    
    # Клавиатура пагинации
    kb = DynamicKeyboards.pagination(page, paginated['pages'])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")
    ])
    
    await callback.message.answer(
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

# =============================================================================
# 2. ПЕРСОНАЛЬНЫЕ СООБЩЕНИЯ 
# =============================================================================

MESSAGE_MENU_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📨 Отправить сообщение", callback_data="send_message")],
    [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
])

@admin_router.message(F.text == "📨 Персональные сообщения")
async def message_schedule_menu(message: Message, state: FSMContext):
    await state.set_state(AdminState.message_schedule_menu)
    await message.answer(
        "📨 <b>Персональные сообщения</b>\n\nВыберите действие:",
        reply_markup=MESSAGE_MENU_KB,
        parse_mode="HTML"
    )


@admin_router.callback_query(AdminState.message_schedule_menu, F.data == "send_message")
async def send_message_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Старт — показать всех пользователей."""
    users, total = await get_all_users_paginated(session, page=1)
    
    if not users:
        await callback.message.answer("📭 Пользователи не найдены")
        await callback.answer()
        return
    
    await show_users_paginated(callback, users, total, page=1, state=state)
    await state.set_state(AdminState.message_users_page)
    await callback.answer()


async def show_users_paginated(callback: CallbackQuery, users: list[User], total: int, page: int, state: FSMContext):
    """Показать страницу пользователей."""
    per_page = 10
    total_pages = (total + per_page - 1) // per_page
    
    text = f"👥 <b>Выберите пользователя (страница {page}/{total_pages})</b>\n\n"
    inline_keyboard = []
    
    for i, user in enumerate(users, (page - 1) * per_page + 1):
        lead_name = user.lead_source.name if user.lead_source else "—"
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"ID {user.user_id}"
        text += f"{i}. <code>{user.user_id}</code> — {name}\n"
        text += f"   Источник: <b>{lead_name}</b>\n\n"
        
        button_text = f"📨 {name[:20]}"
        inline_keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_user_{user.id}"
            )
        ])
    
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(
            text="◀️", 
            callback_data=f"users_page_{page-1}"
        ))
    nav_row.append(InlineKeyboardButton(
        text=f"{page}/{total_pages}", 
        callback_data="empty"
    ))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(
            text="▶️", 
            callback_data=f"users_page_{page+1}"
        ))
    
    if nav_row:
        inline_keyboard.append(nav_row)
    
    inline_keyboard.append([
        InlineKeyboardButton(
            text="🔙 Назад", 
            callback_data="admin_main"
        )
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    
    await callback.message.answer(
        text, 
        reply_markup=kb, 
        parse_mode="HTML"
    )
    
# --- ПАГИНАЦИЯ ---
@admin_router.callback_query(F.data.startswith("page_leads_"))
async def leads_pagination(callback: CallbackQuery, session: AsyncSession):
    """Переход по страницам источников лидов."""
    page = int(callback.data.split("_")[-1])
    result = await session.execute(
        select(LeadSource).options(joinedload(LeadSource.users))
    )
    leads = result.scalars().unique().all()
    
    if not leads:
        await callback.message.answer("📭 Источники лидов не найдены")
        await callback.answer()
        return
    
    paginated = paginate(leads, page, per_page=5)
    text = "📋 <b>Источники лидов</b>\n\n"
    for i, lead in enumerate(paginated['items'], 1):
        users_count = len(lead.users) if lead.users else 0
        text += f"{i}. <b>{lead.name}</b>\n"
        text += f"   Описание: {lead.description or '—'}\n"
        text += f"   Пользователей: <code>{users_count}</code>\n\n"
    
    kb = DynamicKeyboards.pagination(page, paginated['pages'])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")
    ])
    
    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()    
    
    
@admin_router.callback_query(AdminState.message_users_page, F.data.startswith("users_page_"))
async def users_pagination(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Переход по страницам пользователей."""
    page = int(callback.data.split("_")[-1])
    users, total = await get_all_users_paginated(session, page)
    await show_users_paginated(callback, users, total, page, state)
    await callback.answer()

# --- ВЫБОР ПОЛЬЗОВАТЕЛЯ ---
@admin_router.callback_query(F.data.startswith("select_user_"))
async def select_user_for_message(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Выбор → выбор типа сообщения."""
    db_user_id = int(callback.data.split("_")[-1])
    user = await session.get(User, db_user_id)
    
    if not user:
        await callback.answer("❌ Пользователь не найден")
        return
    
    if not user.user_id:
        await callback.answer("❌ Нет Telegram ID")
        return
    
    await state.update_data(
        selected_user_id=user.user_id,  
        selected_user_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or str(user.user_id)
    )
    
    await callback.message.answer(
        f"👤 <b>Выбран:</b> <code>{user.user_id}</code> — {user.first_name or 'Без имени'}\n\n"
        "📢 <b>Выберите тип сообщения:</b>",
        reply_markup=AdminKeyboards.personal_message(),  
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_message_type)  
    await callback.answer()

# --- ВЫБОР ТИПА → СОДЕРЖИМОЕ ---
@admin_router.callback_query(AdminState.add_message_type, F.data == "message_text")
async def message_text_start(callback: CallbackQuery, state: FSMContext):
    """Текст → ввод текста."""
    await callback.message.answer("📝 <b>Введите текст сообщения:</b>")
    await state.set_state(AdminState.add_message_text)
    await callback.answer()


@admin_router.callback_query(AdminState.add_message_type, F.data == "message_image")
async def message_image_start(callback: CallbackQuery, state: FSMContext):
    """Картинка → отправка фото."""
    await callback.message.answer("🖼️ <b>Отправьте картинку:</b>")
    await state.set_state(AdminState.add_message_image)
    await callback.answer()


@admin_router.callback_query(AdminState.add_message_type, F.data == "message_file")
async def message_file_start(callback: CallbackQuery, state: FSMContext):
    """Файл → отправка файла."""
    await callback.message.answer("📎 <b>Отправьте файл:</b>")
    await state.set_state(AdminState.add_message_file)
    await callback.answer()


@admin_router.callback_query(AdminState.add_message_type, F.data == "message_video")
async def message_video_start(callback: CallbackQuery, state: FSMContext):
    """Видео → отправка видео."""
    await callback.message.answer("🎥 <b>Отправьте видео:</b>\n\n<i>Макс. 50 МБ, форматы: MP4</i>")
    await state.set_state(AdminState.add_message_video)  
    await callback.answer()

# --- ОБРАБОТКА КОНТЕНТА ---
@admin_router.message(AdminState.add_message_text)
async def create_message_text(message: Message, state: FSMContext):
    """Текст → отправка."""
    await state.update_data(content=message.text)
    await send_message_final(message, state, message.bot)


@admin_router.message(AdminState.add_message_image)
async def create_message_image(message: Message, state: FSMContext, bot: Bot):
    """Картинка → отправка."""
    if not message.photo:
        await message.answer("❌ Отправьте картинку!")
        return
    
    file_id = message.photo[-1].file_id
    await state.update_data(file_id=file_id, content_type="image")
    await send_message_final(message, state, bot)


@admin_router.message(AdminState.add_message_file)
async def create_message_file(message: Message, state: FSMContext, bot: Bot):
    """Файл → отправка."""
    if not message.document:
        await message.answer("❌ Отправьте файл!")
        return
    
    file_id = message.document.file_id
    await state.update_data(
        file_id=file_id, 
        content_type="file",
        file_name=message.document.file_name
    )
    await send_message_final(message, state, bot)

@admin_router.message(AdminState.add_message_video)
async def create_message_video(message: Message, state: FSMContext, bot: Bot):
    """Видео → отправка."""
    if not message.video:
        await message.answer("❌ Отправьте видео!")
        return
    
    file_id = message.video.file_id
    await state.update_data(
        file_id=file_id,
        content_type="video",
        file_name=message.video.file_name or "video.mp4"
    )
    await send_message_final(message, state, bot)


async def send_message_final(message: Message, state: FSMContext, bot: Bot):
    """Общая логика отправки."""
    data = await state.get_data()
    telegram_user_id = data['selected_user_id']
    user_name = data['selected_user_name']
    content = data.get('content', '')
    file_id = data.get('file_id')
    content_type = data.get('content_type', 'text')
    
    try:
        if content_type == "text":
            await bot.send_message(chat_id=telegram_user_id, text=content)
        elif content_type == "image":
            await bot.send_photo(chat_id=telegram_user_id, photo=file_id)
        elif content_type == "file":
            await bot.send_document(chat_id=telegram_user_id, document=file_id)
        elif content_type == "video":
            await bot.send_video(chat_id=telegram_user_id, video=file_id)
        
        await message.answer(
            f"✅ <b>Сообщение ОТПРАВЛЕНО!</b>\n\n"
            f"👤 <b>{user_name}</b>\n"
            f"🆔 <code>{telegram_user_id}</code>\n"
            f"📢 <b>Тип:</b> {content_type}\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            reply_markup=ADMIN_MAIN_KB,
            parse_mode="HTML"
        )
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка отправки {telegram_user_id}: {e}")
        await message.answer(f"❌ Ошибка отправки: {e}")
        
# =============================================================================
# 3. МАССОВАЯ РАССЫЛКА
# =============================================================================

BROADCAST_MENU_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ Создать рассылку", callback_data="create_broadcast")],
    [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
])

@admin_router.message(F.text == "📢 Массовая рассылка")
async def broadcast_menu(message: Message, state: FSMContext):
    """Меню массовой рассылки."""
    await state.set_state(AdminState.broadcast_menu)
    await message.answer(
        "📢 <b>Массовая рассылка</b>\n\n"
        "Выберите действие:",
        reply_markup=BROADCAST_MENU_KB,
        parse_mode="HTML"
    )

@admin_router.callback_query(AdminState.broadcast_menu, F.data == "create_broadcast")
async def create_broadcast_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Шаг 1: Выбор аудитории."""
    leads = await get_lead_sources(session)
    
    inline_keyboard = []
    for lead in leads:
        inline_keyboard.append([InlineKeyboardButton(text=lead.name, callback_data=f"select_lead_{lead.id}")])
    inline_keyboard.extend([
        [InlineKeyboardButton(text="📢 Всем пользователям", callback_data="broadcast_all")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_main")]
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    
    await callback.message.answer(
        "📢 <b>Создать массовую рассылку</b>\n\n"
        "Выберите аудиторию:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_broadcast_lead_source)
    await callback.answer()

# --- ВЫБОР АУДИТОРИИ ---
@admin_router.callback_query(AdminState.add_broadcast_lead_source, F.data.startswith("select_lead_"))
async def create_broadcast_select_lead(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор сегмента → тип контента."""
    lead_id = int(callback.data.split("_")[-1])
    lead = await session.get(LeadSource, lead_id)
    
    if lead:
        await state.update_data(target_lead_id=lead_id, target_name=lead.name)
        await callback.message.answer(
            f"✅ <b>Выбран сегмент:</b> <code>{lead.name}</code>\n\n"
            "📢 <b>Выберите тип рассылки:</b>",
            reply_markup=AdminKeyboards.broadcast_type_menu()  
        )
    await state.set_state(AdminState.add_broadcast_type)
    await callback.answer()


@admin_router.callback_query(AdminState.add_broadcast_lead_source, F.data == "broadcast_all")
async def create_broadcast_all(callback: CallbackQuery, state: FSMContext):
    """Всем → тип контента."""
    await state.update_data(target_name="Всем пользователям")
    await callback.message.answer(
        "✅ <b>Аудитория:</b> Всем пользователям\n\n"
        "📢 <b>Выберите тип рассылки:</b>",
        reply_markup=AdminKeyboards.broadcast_type_menu()  
    )
    await state.set_state(AdminState.add_broadcast_type)
    await callback.answer()


@admin_router.callback_query(AdminState.add_broadcast_type, F.data == "broadcast_text")
async def broadcast_text_start(callback: CallbackQuery, state: FSMContext):
    """Текст → ввод текста."""
    await callback.message.answer("📝 <b>Введите текст рассылки:</b>")
    await state.set_state(AdminState.add_broadcast_text)
    await callback.answer()


@admin_router.callback_query(AdminState.add_broadcast_type, F.data == "broadcast_image")
async def broadcast_image_start(callback: CallbackQuery, state: FSMContext):
    """Картинка → отправка фото."""
    await callback.message.answer("🖼️ <b>Отправьте картинку:</b>")
    await state.set_state(AdminState.add_broadcast_image)
    await callback.answer()


@admin_router.callback_query(AdminState.add_broadcast_type, F.data == "broadcast_file")
async def broadcast_file_start(callback: CallbackQuery, state: FSMContext):
    """Файл → отправка файла."""
    await callback.message.answer("📎 <b>Отправьте файл:</b>")
    await state.set_state(AdminState.add_broadcast_file)
    await callback.answer()


@admin_router.callback_query(AdminState.add_broadcast_type, F.data == "broadcast_video")
async def broadcast_video_start(callback: CallbackQuery, state: FSMContext):
    """Видео → отправка видео."""
    await callback.message.answer("🎥 <b>Отправьте видео:</b>\n\n<i>Макс. 50 МБ, форматы: MP4</i>")
    await state.set_state(AdminState.add_broadcast_video)  
    await callback.answer()


@admin_router.message(AdminState.add_broadcast_text)
async def create_broadcast_text(message: Message, state: FSMContext):
    """Текст → время."""
    await state.update_data(content=message.text, content_type="text")
    
    await message.answer(
        "⏰ <b>Время отправки:</b>\n"
        "• <code>2025-10-25 12:00</code>\n",
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_broadcast_time)


@admin_router.message(AdminState.add_broadcast_image)
async def create_broadcast_image(message: Message, state: FSMContext):
    """Картинка → время."""
    if not message.photo:
        await message.answer("❌ Отправьте картинку!")
        return
    
    file_id = message.photo[-1].file_id
    await state.update_data(file_id=file_id, content_type="image")
    
    await message.answer(
        "✅ Картинка сохранена!\n\n"
        "⏰ <b>Время отправки:</b>\n"
        "• <code>2025-10-25 12:00</code>\n",
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_broadcast_time)


@admin_router.message(AdminState.add_broadcast_file)
async def create_broadcast_file(message: Message, state: FSMContext):
    """Файл → время."""
    if not message.document:
        await message.answer("❌ Отправьте файл!")
        return
    
    file_id = message.document.file_id
    await state.update_data(
        file_id=file_id, 
        content_type="file",
        file_name=message.document.file_name
    )
    
    await message.answer(
        f"✅ Файл <b>{message.document.file_name}</b> сохранен!\n\n"
        "⏰ <b>Время отправки:</b>\n"
        "• <code>2025-10-25 12:00</code>\n",
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_broadcast_time)


@admin_router.message(AdminState.add_broadcast_video)
async def create_broadcast_video(message: Message, state: FSMContext):
    """Видео → время."""
    if not message.video:
        await message.answer("❌ Отправьте видео!")
        return
    
    file_id = message.video.file_id
    await state.update_data(
        file_id=file_id,
        content_type="video",
        file_name=message.video.file_name or "video.mp4"
    )
    
    await message.answer(
        f"✅ Видео <b>{message.video.file_name or 'video.mp4'}</b> сохранено!\n\n"
        "⏰ <b>Время отправки:</b>\n"
        "• <code>2025-10-25 12:00</code>\n",
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_broadcast_time)


@admin_router.message(AdminState.add_broadcast_time)
async def create_broadcast_time(message: Message, state: FSMContext, session: AsyncSession):
    """Завершение рассылки."""
    data = await state.get_data()
    
    scheduled_at = None
    if message.text.strip():
        try:
            scheduled_at = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
        except ValueError:
            await message.answer("❌ Неверный формат. Отправка <b>немедленно</b>")
    
    lead_id = data.get('target_lead_id')
    
    broadcast = await add_broadcast(
        session,
        title=f"Рассылка {datetime.now().strftime('%d.%m.%Y')}",
        content=data.get('content', ''),
        file_id=data.get('file_id'),
        file_type=data.get('content_type'),
        scheduled_at=scheduled_at,
        lead_source_id=lead_id
    )
    
    if not scheduled_at:
        await send_broadcast_now(session, message.bot, broadcast.id)
        await session.refresh(broadcast)
        status = f"🚀 <b>ОТПРАВЛЕНО</b> ({broadcast.sent_count} пользователей)"
    else:
        status = "⏰ Запланировано"
    
    lead_name = data.get('target_name', 'Всем')
    content_type = data.get('content_type', 'text')
    
    type_names = {
        "text": "📝 Текст",
        "image": "🖼️ Картинка",
        "file": f"📎 {data.get('file_name', 'Файл')}",
        "video": f"🎥 {data.get('file_name', 'Видео')}"
    }
    
    await message.answer(
        f"✅ <b>Рассылка создана #{broadcast.id}</b>\n\n"
        f"📢 <b>Тип:</b> {type_names[content_type]}\n"
        f"👥 <b>Кому:</b> {lead_name}\n"
        f"{status}\n"
        f"🆔 <code>{broadcast.id}</code>",
        reply_markup=ADMIN_MAIN_KB,
        parse_mode="HTML"
    )
    await state.clear()
    
    
# =============================================================================
# 4. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ
# =============================================================================

USERS_MENU_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="👥 Все пользователи", callback_data="users_all")],
    [InlineKeyboardButton(text="📋 По источнику лидов", callback_data="users_by_lead")],
    [InlineKeyboardButton(text="🔙 В меню", callback_data="admin_main")]
])


@admin_router.message(F.text == "👥 Пользователи")
async def users_menu(message: Message, session: AsyncSession, state: FSMContext):
    """Меню просмотра пользователей."""
    await state.set_state(AdminState.user_menu)
    
    all_users = await get_all_users(session)
    text = f"👥 <b>Пользователи системы</b>\n\n"
    text += f"<b>Всего пользователей:</b> <code>{len(all_users)}</code>\n\n"
    text += "Выберите фильтр:"
    
    await message.answer(text, reply_markup=USERS_MENU_KB, parse_mode="HTML")


@admin_router.callback_query(F.data == "users_all")
async def show_all_users(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Показать всех пользователей с пагинацией."""
    users = await get_all_users(session)
    if not users:
        await callback.message.answer("📭 Пользователи не найдены")
        await callback.answer()
        return
    
    page = 1
    per_page = 10
    total_pages = (len(users) + per_page - 1) // per_page
    paginated_users = users[(page - 1) * per_page:page * per_page]
    
    text = "👥 <b>Все пользователи</b>\n\n"
    for i, user in enumerate(paginated_users, 1):
        lead_name = user.lead_source.name if user.lead_source else "Не указан"
        text += f"{i}. <code>{user.user_id}</code>\n"
        text += f"   {user.first_name or ''} {user.last_name or ''}\n"
        text += f"   Источник: <b>{lead_name}</b>\n"
        text += f"   Дата: {user.registered_at.strftime('%d.%m.%Y %H:%M')}\n\n"
    
    builder = InlineKeyboardBuilder()
    
    nav_row = []
    if page > 1:
        builder.button(text="◀️", callback_data=f"users_page_{page-1}")
    builder.button(text=f"{page}/{total_pages}", callback_data="empty")
    if page < total_pages:
        builder.button(text="▶️", callback_data=f"users_page_{page+1}")
    builder.adjust(3)
    
    builder.button(text="🔙 Назад", callback_data="admin_main")
    
    await state.set_state(AdminState.message_users_page)  
    await callback.message.answer(
        text, 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )
    await callback.answer()


@admin_router.callback_query(F.data == "users_by_lead")
async def users_by_lead_menu(callback: CallbackQuery, session: AsyncSession):
    """Выбор источника лидов для фильтрации пользователей."""
    leads = await get_lead_sources(session)
    if not leads:
        await callback.message.answer("📭 Источники лидов не найдены")
        return
    
    inline_keyboard = []
    for lead in leads:
        inline_keyboard.append([InlineKeyboardButton(text=lead.name, callback_data=f"filter_users_{lead.id}")])
    inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    
    await callback.message.answer(
        "📋 <b>Выберите источник лидов:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("filter_users_"))
async def filter_users_by_lead(callback: CallbackQuery, session: AsyncSession):
    """Выводит список пользователей, относящихся к выбранному источнику лида."""
    lead_id = int(callback.data.split("_")[-1])
    

    lead_source = await session.get(LeadSource, lead_id)
    if not lead_source:
        await callback.message.answer("❌ Источник лида не найден.")
        return
    

    users = await get_users_by_lead_source(session, lead_id)
    
    if not users:
        await callback.message.answer(f"👤 Пользователи для источника <b>{lead_source.name}</b> не найдены.", parse_mode="HTML")
        return
    

    text_lines = [f"<b>Пользователи из источника:</b> {lead_source.name}\n"]
    for user in users:
        username = f"@{user.username}" if user.username else "(без username)"
        text_lines.append(
            f"🆔 {user.user_id} — {username}\n"
            f"👤 {user.first_name or ''} {user.last_name or ''}\n"
            f"📱 {user.phone or '—'}\n"
            f"📅 {user.registered_at.strftime('%d.%m.%Y %H:%M') if user.registered_at else '—'}"
        )
        text_lines.append("────────────")

    text = "\n".join(text_lines)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="admin_main")]
    ])
    
    await callback.message.answer(text, parse_mode='HTML', reply_markup=kb)
    await callback.answer()
# =============================================================================
# ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ FSM — БЕЗ StateFilter
# =============================================================================

@admin_router.message(Command("отмена"))
@admin_router.message(F.text == "отмена")
async def cancel_admin_action(message: Message, state: FSMContext):
    """Отмена любого действия в админке."""
    current_state = await state.get_state()
    if current_state and current_state.startswith("AdminState"):
        await state.clear()
    await message.answer("❌ Действие отменено", reply_markup=ADMIN_MAIN_KB)

@admin_router.callback_query(F.data == "admin_main")
async def back_to_admin_main(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню админки."""
    await state.clear()
    await callback.message.answer(
        "🔐 <b>Административная панель</b>",
        reply_markup=ADMIN_MAIN_KB,
        parse_mode="HTML"
    )
    await callback.answer()

@admin_router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    """Команда отмены."""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    await message.answer("❌ Действие отменено", reply_markup=ADMIN_MAIN_KB)

# =============================================================================
# УДАЛЕНИЕ ИСТОЧНИКА ЛИДОВ
# =============================================================================

@admin_router.callback_query(AdminState.lead_source_menu, F.data == "delete_lead_menu")
async def delete_lead_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Меню удаления источников."""
    leads = await get_lead_sources(session)
    if not leads:
        await callback.message.answer("📭 Источники не найдены")
        return
    
    inline_keyboard = []
    for lead in leads:
        inline_keyboard.append([InlineKeyboardButton(text=f"🗑 {lead.name}", callback_data=f"delete_lead_{lead.id}")])
    inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    
    await callback.message.answer("🗑 Выберите источник для удаления:", reply_markup=kb)
    await state.set_state(AdminState.delete_lead_source_select)
    await callback.answer()



@admin_router.callback_query(F.data.startswith("delete_lead_"))
async def delete_lead_source_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Подтверждение удаления источника лидов."""
    lead_id = int(callback.data.split("_")[-1])

    result = await session.execute(
        select(LeadSource)
        .options(selectinload(LeadSource.users))
        .where(LeadSource.id == lead_id)
    )
    lead = result.scalar_one_or_none()

    if not lead:
        await callback.answer("❌ Источник не найден")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Удалить", callback_data=f"confirm_delete_lead_{lead_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_main")]
    ])

    users_count = len(lead.users) if lead.users else 0

    await callback.message.answer(
        f"⚠️ <b>Удалить источник лидов?</b>\n\n"
        f"<b>{lead.name}</b>\n"
        f"{lead.description or ''}\n\n"
        f"Пользователей: <code>{users_count}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("confirm_delete_lead_"))
async def delete_lead_source_exec(callback: CallbackQuery, session: AsyncSession):
    """Выполнение удаления источника лидов."""
    lead_id = int(callback.data.split("_")[-1])
    await delete_lead_source(session, lead_id)
    
    await callback.message.answer("✅ Источник лидов удалён")
    await callback.answer("Удалено")
    

@admin_router.message(F.text == "🛠 Изменить тексты")
async def edit_texts_menu(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Этап 1: Вебинар", callback_data="edit_stage1")],
        [InlineKeyboardButton(text="Этап 2: Челлендж", callback_data="edit_stage2")],
        [InlineKeyboardButton(text="Этап 3: Урок + Отзыв", callback_data="edit_stage3")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_main")]
    ])
    await message.answer("Выберите:", reply_markup=kb)
    await state.set_state(AdminState.edit_stage_select)


@admin_router.callback_query(F.data.startswith("edit_stage"))
async def edit_stage(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    stage = callback.data.split("edit_")[-1]
    st = await get_stage_text(session, stage)
    fb = await get_feedback_options(session) if stage == "stage3" else None

    text = f"<b>Этап {stage}</b>\n\n"
    text += f"<b>Приветствие:</b>\n{st.welcome_text}\n\n"
    text += f"<b>Текст меню:</b>\n{st.main_menu_text}\n"
    if fb:
        text += f"\n<b>Варианты отзыва:</b>\n1. {fb.option_1}\n2. {fb.option_2}\n3. {fb.option_3}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Приветствие", callback_data=f"edit_welcome_{stage}")],
        [InlineKeyboardButton(text="Текст меню", callback_data=f"edit_menu_{stage}")],
    ])
    if fb:
        kb.inline_keyboard.append([InlineKeyboardButton(text="Варианты отзыва", callback_data="edit_feedback")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="Назад", callback_data="admin_main")])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(edit_stage=stage)


@admin_router.callback_query(F.data.startswith("edit_welcome_") | F.data.startswith("edit_menu_"))
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = "welcome_text" if "welcome" in callback.data else "main_menu_text"
    stage = callback.data.split("_")[-1]
    await state.update_data(edit_field=field, edit_stage=stage)
    await callback.message.answer(
        f"Новый текст для <b>{'приветствия' if field == 'welcome_text' else 'меню'}</b>:",
        parse_mode="HTML"
    )
    await state.set_state(AdminState.edit_text_input)


@admin_router.callback_query(F.data == "edit_feedback")
async def edit_feedback_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    fb = await get_feedback_options(session)
    text = (
        f"Текущие варианты:\n"
        f"1. {fb.option_1}\n"
        f"2. {fb.option_2}\n"
        f"3. {fb.option_3}\n\n"
        "Введите новые (по одному в строке):"
    )
    await callback.message.answer(text)
    await state.set_state(AdminState.edit_feedback_input)


@admin_router.message(AdminState.edit_feedback_input)
async def save_feedback(message: Message, session: AsyncSession, state: FSMContext):
    lines = [l.strip() for l in message.text.split("\n") if l.strip()]
    if len(lines) != 3:
        await message.answer("Нужно 3 строки!")
        return
    await update_feedback_options(session, "stage3", *lines)
    await message.answer("Варианты обновлены!", reply_markup=ADMIN_MAIN_KB)
    await state.clear()


@admin_router.message(AdminState.edit_text_input)
async def save_text(message: Message, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    await update_stage_text(
        session,
        stage=data["edit_stage"],
        welcome_text=message.text if data["edit_field"] == "welcome_text" else None,
        main_menu_text=message.text if data["edit_field"] == "main_menu_text" else None
    )
    await message.answer("Текст сохранён!", reply_markup=ADMIN_MAIN_KB)
    await state.clear()

