from asyncio.log import logger
from datetime import datetime
from typing import List, Optional
from aiogram import Bot
from sqlalchemy import func, or_, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from zoneinfo import ZoneInfo
import json
from sqlalchemy import text, update
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

from app.database.state import LeadMagnetState
from app.database.models import FeedbackOptions, LeadSource, StageText, User, MessageSchedule, Broadcast


# ==========================================================
# 1. LEAD SOURCE — управление источниками лидов (воронками)
# ==========================================================

async def create_empty_lead_source(session: AsyncSession, name: str) -> LeadSource:
    """
    Создаёт источник лида с именем (без описания, первый шаг FSM).
    """
    lead = LeadSource(name=name)
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return lead


async def update_lead_description(session: AsyncSession, lead_id: int, description: str) -> LeadSource:
    """
    Обновляет описание источника лида (второй шаг FSM).
    """
    query = update(LeadSource).where(LeadSource.id == lead_id).values(description=description)
    await session.execute(query)
    await session.commit()
    result = await session.execute(select(LeadSource).where(LeadSource.id == lead_id))
    return result.scalar_one()


async def get_lead_sources(session: AsyncSession) -> list[LeadSource]:
    """
    Возвращает список всех источников лидов.
    """
    result = await session.execute(select(LeadSource))
    return result.scalars().all()


async def delete_lead_source(session: AsyncSession, lead_id: int) -> None:
    """
    Удаляет источник лида по ID.
    """
    await session.execute(delete(LeadSource).where(LeadSource.id == lead_id))
    await session.commit()


async def add_lead_magnet_stat(
    session: AsyncSession,
    user_id: int,
    template_version: str,
    stage: str,
    viewed: bool = False,
    feedback_type: Optional[str] = None
):
    """Добавление статистики лид-магнита."""
    stat = LeadMagnetState(
        user_id=user_id,
        template_version=template_version,
        stage=stage,
        viewed=viewed,
        feedback_type=feedback_type
    )
    session.add(stat)
# ==========================================================
# 2. USER — управление пользователями Telegram
# ==========================================================

async def get_all_users(session: AsyncSession) -> list[User]:
    """
    Возвращает всех пользователей с их источниками.
    """
    result = await session.execute(
        select(User).options(joinedload(User.lead_source))
    )
    return result.scalars().unique().all()


async def get_users_by_lead_source(session: AsyncSession, lead_source_id: int) -> list[User]:
    """
    Возвращает всех пользователей, принадлежащих указанной воронке (по имени).
    """
    query = (
        select(User)
        .join(LeadSource)
        .where(LeadSource.id == lead_source_id)
        .options(joinedload(User.lead_source))
    )
    result = await session.execute(query)
    return result.scalars().all()


async def assign_user_to_lead_source(session: AsyncSession, user_tg_id: int, lead_source_name: str) -> None:
    """
    Привязывает пользователя к воронке по её имени.
    """
    lead = await session.execute(select(LeadSource).where(LeadSource.name == lead_source_name))
    lead_obj = lead.scalar_one_or_none()
    if not lead_obj:
        return

    await session.execute(
        update(User).where(User.user_id == user_tg_id).values(lead_source_id=lead_obj.id)
    )
    await session.commit()


async def delete_user(session: AsyncSession, user_tg_id: int) -> None:
    """
    Удаляет пользователя по его Telegram ID.
    """
    await session.execute(delete(User).where(User.user_id == user_tg_id))
    await session.commit()


# ==========================================================
# 3. MESSAGE SCHEDULE — индивидуальные сообщения
# ==========================================================
async def add_message_schedule(
    session: AsyncSession,
    user_id: int,
    message_text: str,
    scheduled_at: datetime,
    file_id: Optional[str] = None,
    file_type: Optional[str] = None
):
    """Создаёт запланированное сообщение. Картинка — ТОЛЬКО если передали file_id."""
    send_time = scheduled_at.replace(tzinfo=None)
    
    if file_id and file_type:
        payload = json.dumps({
            "text": message_text,
            "file_id": file_id,
            "file_type": file_type
        }, ensure_ascii=False)
    else:
        payload = message_text  

    schedule = MessageSchedule(
        user_id=user_id,
        message_text=payload,
        send_time=send_time,
        sent=False
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def get_pending_messages(session: AsyncSession) -> list[MessageSchedule]:
    """
    Возвращает все сообщения, которые ещё не отправлены.
    """
    result = await session.execute(
        select(MessageSchedule).where(MessageSchedule.sent.is_(False)).order_by(MessageSchedule.send_time)
    )
    return result.scalars().all()


async def mark_message_as_sent(session: AsyncSession, message_id: int) -> None:
    """
    Помечает сообщение как отправленное.
    """
    await session.execute(
        update(MessageSchedule).where(MessageSchedule.id == message_id).values(sent=True)
    )
    await session.commit()


async def delete_message_schedule(session: AsyncSession, message_id: int) -> None:
    """
    Удаляет запланированное сообщение.
    """
    await session.execute(delete(MessageSchedule).where(MessageSchedule.id == message_id))
    await session.commit()

async def get_all_users_paginated(session: AsyncSession, page: int = 1, per_page: int = 10) -> tuple[list[User], int]:
    """Все пользователи с пагинацией."""
    offset = (page - 1) * per_page
    result = await session.execute(
        select(User)
        .options(joinedload(User.lead_source))
        .order_by(User.registered_at.desc())
        .limit(per_page)
        .offset(offset)
    )
    users = result.scalars().unique().all()
    
    total_result = await session.execute(select(func.count()).select_from(User))
    total = total_result.scalar()
    
    return users, total

# ==========================================================
# 4. BROADCAST — массовые рассылки
# ==========================================================

async def add_broadcast(
    session: AsyncSession,
    title: str,
    content: str,
    file_id: str = None,  
    file_type: str = "text",
    scheduled_at: datetime = None,
    lead_source_id: int = None
):
    """Создание рассылки."""
    broadcast = Broadcast(
        title=title,
        content=content,
        file_id=file_id,  
        file_type=file_type,
        created_at=datetime.now(),
        scheduled_at=scheduled_at,
        is_sent=False,
        status="pending",
        sent_count=0,
        target_lead_id=lead_source_id
    )
    session.add(broadcast)
    await session.commit()
    await session.refresh(broadcast)
    return broadcast

async def get_unsent_broadcasts(session: AsyncSession) -> list[Broadcast]:
    """
    Возвращает все рассылки, которые ещё не были отправлены.
    """
    result = await session.execute(
        select(Broadcast).where(Broadcast.is_sent.is_(False))
    )
    return result.scalars().all()


async def mark_broadcast_as_sent(session: AsyncSession, broadcast_id: int) -> None:
    """
    Помечает рассылку как отправленную.
    """
    await session.execute(
        update(Broadcast).where(Broadcast.id == broadcast_id).values(is_sent=True)
    )
    await session.commit()


async def delete_broadcast(session: AsyncSession, broadcast_id: int) -> None:
    """
    Удаляет массовую рассылку.
    """
    await session.execute(delete(Broadcast).where(Broadcast.id == broadcast_id))
    await session.commit()


async def get_lead_source_by_name(session: AsyncSession, name: str) -> Optional[LeadSource]:
    query = select(LeadSource).where(LeadSource.name == name)
    result = await session.execute(query)
    return result.scalar_one_or_none()

        

async def get_lead_source_id_by_name(session: AsyncSession, name: str) -> Optional[int]:
    """Получить ID источника лидов по имени."""
    from app.database.models import LeadSource
    result = await session.execute(
        select(LeadSource.id).where(LeadSource.name == name)
    )
    return result.scalar_one_or_none()

async def assign_user_to_lead_source(
    session: AsyncSession, 
    user_id: int, 
    lead_source_name: str
):
    """Привязать пользователя к источнику лидов."""
    
    lead_source = await session.get(LeadSource, 
        (await get_lead_source_id_by_name(session, lead_source_name))
    )
    
    if not lead_source:
        logger.error(f"Lead source '{lead_source_name}' not found")
        return False

    stmt = update(User).where(
        User.user_id == user_id
    ).values(lead_source_id=lead_source.id)
    
    result = await session.execute(stmt)
    await session.commit()
    
    if result.rowcount > 0:
        logger.info(f"User {user_id} assigned to lead source: {lead_source_name}")
        return True
    else:
        logger.error(f"User {user_id} not found")
        return False
    
    
    
async def send_broadcast_now(session: AsyncSession, bot: Bot, broadcast_id: int):
    """Отправка рассылки."""
    broadcast = await session.get(Broadcast, broadcast_id)
    if not broadcast:
        return
    
    users = await get_users_by_lead_source(session, broadcast.target_lead_id) if broadcast.target_lead_id else await get_all_users(session)
    
    sent_count = 0
    for user in users:
        try:
            if broadcast.file_type == "text":
                await bot.send_message(user.user_id, broadcast.content)
            elif broadcast.file_type == "image":
                await bot.send_photo(user.user_id, broadcast.file_id)
            elif broadcast.file_type == "file":
                await bot.send_document(user.user_id, broadcast.file_id)
            elif broadcast.file_type == "video":
                await bot.send_video(user.user_id, broadcast.file_id)
            
            sent_count += 1
            logger.info(f"✅ Отправлено {user.user_id} (#{broadcast.id})")
            
        except Exception as e:
            logger.error(f"❌ Ошибка {user.user_id}: {e}")
    
    broadcast.status = "sent"
    broadcast.is_sent = True
    broadcast.sent_count = sent_count
    await session.commit()
    
    broadcast.status = "sent"
    broadcast.is_sent = True
    broadcast.sent_count = sent_count
    
    await session.commit()
    logger.info(f"✅ Рассылка #{broadcast.id} отправлена {sent_count} пользователям")
    
    
    
async def get_stage_text(session: AsyncSession, stage: str) -> Optional[StageText]:
    result = await session.execute(select(StageText).where(StageText.stage == stage))
    return result.scalar_one_or_none()


async def get_all_stage_texts(session: AsyncSession) -> List[StageText]:
    result = await session.execute(select(StageText))
    return result.scalars().all()


async def update_stage_text(
    session: AsyncSession,
    stage: str,
    welcome_text: Optional[str] = None,
    main_menu_caption: Optional[str] = None
) -> StageText:
    stmt = update(StageText).where(StageText.stage == stage)
    values = {}
    if welcome_text is not None:
        values["welcome_text"] = welcome_text
    if main_menu_caption is not None:
        values["main_menu_caption"] = main_menu_caption
    if values:
        stmt = stmt.values(**values)
        await session.execute(stmt)
        await session.commit()
    
    result = await session.execute(select(StageText).where(StageText.stage == stage))
    return result.scalar_one()    


# === StageText ===
async def get_stage_text(session: AsyncSession, stage: str) -> Optional[StageText]:
    result = await session.execute(select(StageText).where(StageText.stage == stage))
    return result.scalar_one_or_none()

async def update_stage_text(
    session: AsyncSession,
    stage: str,
    welcome_text: Optional[str] = None,
    main_menu_text: Optional[str] = None
) -> StageText:
    values = {}
    if welcome_text is not None:
        values["welcome_text"] = welcome_text
    if main_menu_text is not None:
        values["main_menu_text"] = main_menu_text
    if values:
        await session.execute(
            update(StageText).where(StageText.stage == stage).values(**values)
        )
        await session.commit()
    result = await session.execute(select(StageText).where(StageText.stage == stage))
    return result.scalar_one()


async def get_feedback_options(session: AsyncSession, stage: str = "stage3") -> Optional[FeedbackOptions]:
    result = await session.execute(select(FeedbackOptions).where(FeedbackOptions.stage == stage))
    return result.scalar_one_or_none()

async def update_feedback_options(
    session: AsyncSession,
    stage: str,
    option_1: Optional[str] = None,
    option_2: Optional[str] = None,
    option_3: Optional[str] = None
) -> FeedbackOptions:
    values = {}
    if option_1: values["option_1"] = option_1
    if option_2: values["option_2"] = option_2
    if option_3: values["option_3"] = option_3
    if values:
        await session.execute(
            update(FeedbackOptions).where(FeedbackOptions.stage == stage).values(**values)
        )
        await session.commit()
    result = await session.execute(select(FeedbackOptions).where(FeedbackOptions.stage == stage))
    return result.scalar_one()


logger = logging.getLogger(__name__)

async def send_scheduled_broadcasts(session, bot):
    
    now = datetime.now(ZoneInfo("Asia/Almaty")).replace(tzinfo=None)
    logger.info(f"Проверка рассылок: {now}")

    # ========================================
    # 1. ОТПРАВКА MessageSchedule (индивидуальные)
    # ========================================
    query_personal = text("""
        SELECT ms.id, ms.message_text, u.user_id as tg_id
        FROM message_schedule ms
        JOIN "user" u ON u.id = ms.user_id
        WHERE ms.send_time <= :now 
          AND ms.sent = false
    """)

    result = await session.execute(query_personal, {"now": now})
    rows = result.fetchall()

    for row in rows:
        try:
            await bot.send_message(
                chat_id=row.tg_id,
                text=row.message_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"Отправлено пользователю {row.tg_id}")
        except Exception as e:
            if "blocked" in str(e).lower():
                logger.warning(f"Пользователь {row.tg_id} заблокировал бота")
            else:
                logger.error(f"Ошибка отправки {row.tg_id}: {e}")

        await session.execute(
            text("UPDATE message_schedule SET sent = true WHERE id = :id"),
            {"id": row.id}
        )

    # ========================================
    # 2. ОТПРАВКА Broadcast (массовые)
    # ========================================
    query_broadcast = text("""
        SELECT id, title, content, file_id, file_type
        FROM broadcast
        WHERE scheduled_at <= :now
          AND (status IS NULL OR status = 'pending')
          AND is_sent = false
        LIMIT 1
    """)

    result = await session.execute(query_broadcast, {"now": now})
    broadcast = result.fetchone()

    if broadcast:
        logger.info(f"Начинаем массовую рассылку: {broadcast.title}")
        await session.execute(
            text("UPDATE broadcast SET status = 'sending' WHERE id = :id"),
            {"id": broadcast.id}
        )
        await session.commit()

        # Отправляем ВСЕМ активным пользователям
        users_query = text("SELECT user_id FROM \"user\" WHERE user_id IS NOT NULL")
        users = await session.execute(users_query)
        total = 0
        for user_row in users:
            try:
                if broadcast.file_id and broadcast.file_type:
                    await bot.send_document(
                        chat_id=user_row.user_id,
                        document=broadcast.file_id,
                        caption=broadcast.content,
                        parse_mode="HTML"
                    )
                else:
                    await bot.send_message(
                        chat_id=user_row.user_id,
                        text=broadcast.content or broadcast.title,
                        parse_mode="HTML"
                    )
                total += 1
            except Exception as e:
                if "blocked" not in str(e).lower():
                    logger.error(f"Не отправлено {user_row.user_id}: {e}")

        await session.execute(text("""
            UPDATE broadcast 
            SET is_sent = true, 
                status = 'sent', 
                sent_count = :total,
                updated = :now
            WHERE id = :id
        """), {"id": broadcast.id, "total": total, "now": now})
        logger.info(f"Рассылка завершена: {total} отправлено")

    if rows or broadcast:
        await session.commit()
        
        
