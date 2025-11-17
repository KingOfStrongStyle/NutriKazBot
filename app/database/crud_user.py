from datetime import datetime
import math
import random
from typing import List, Optional
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database.models import LeadSource, User, MessageSchedule, Broadcast


# ----------------------------------------------------------
# Получение даты регистрации пользователя по Telegram ID
# ----------------------------------------------------------
async def get_user_registered_at(session: AsyncSession, tg_user_id: int) -> Optional[datetime]:
    """Возвращает дату регистрации пользователя или None, если пользователь не найден."""
    query = select(User.registered_at).where(User.user_id == tg_user_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


# ----------------------------------------------------------
# Получение текста сообщения для пользователя
# ----------------------------------------------------------
async def get_message_text(session: AsyncSession, tg_user_id: int) -> Optional[str]:
    """
    Возвращает текст сообщения, связанного с пользователем.
    Используется при формировании персонализированных уведомлений или рассылок.
    """
    query = select(MessageSchedule.message_text).where(MessageSchedule.user_id == tg_user_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


# ======================================================================
# Пользователи
# ======================================================================
async def add_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str],
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone: Optional[str] = None,
    lead_source_id: Optional[int] = None
) -> User:
    """
    Добавляет нового пользователя, если его нет в БД.
    Если пользователь уже существует — возвращает существующую запись.
    """
    query = select(User).where(User.user_id == user_id)
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if user:
        return user

    new_user = User(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        lead_source_id=lead_source_id,
    )

    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    return new_user


async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    """Возвращает объект пользователя по Telegram ID."""
    query = select(User).where(User.user_id == user_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_users_by_lead_source(session: AsyncSession, lead_source_id: int) -> List[User]:
    """Возвращает список пользователей, относящихся к указанному источнику лида."""
    query = select(User).where(User.lead_source_id == lead_source_id)
    result = await session.execute(query)
    return result.scalars().all()


async def update_user(session: AsyncSession, tg_user_id: int, **kwargs):
    query = update(User).where(User.user_id == tg_user_id).values(**kwargs)
    await session.execute(query)
    await session.commit()
