import asyncio
import os
from datetime import datetime, timedelta
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from dotenv import load_dotenv, find_dotenv
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message

from app.middlewares.db import DataBaseSession
from app.database.models import async_session_maker, engine, Base, User, LeadSource
from app.database.crud_admin import send_scheduled_broadcasts
from sqlalchemy import select

from app.handlers.common import common_router
from app.handlers.admin import admin_router
from app.handlers.webinar import webinar_router
from app.handlers.challenge import challenge_router, register_challenge  
from app.handlers.lead_magnet import lead_magnet_router

from app.utils.filters import get_my_user_id

logging. basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv(find_dotenv())

# === ОЖИДАНИЕ БД ===
async def wait_for_db():
    import asyncpg
    db_url = os.getenv("SQLALCHEMY_URL").replace("+asyncpg", "")
    max_attempts = 30
    for i in range(max_attempts):
        try:
            conn = await asyncpg.connect(db_url)
            await conn.close()
            logger.info("БД доступна!")
            return
        except Exception as e:
            logger.warning(f"Ожидание БД... ({i+1}/{max_attempts}) | Ошибка: {e}")
            await asyncio.sleep(2)
    raise Exception("БД не стала доступной")

async def create_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("База данных инициализирована")

# === ВОССТАНОВЛЕНИЕ ЧЕЛЛЕНДЖА ДЛЯ ВСЕХ С lead_source = challenge ===
async def restore_challenge_for_current_users():
    await asyncio.sleep(10)  
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(User).join(LeadSource).where(LeadSource.name == "challenge")
            )
            users = result.scalars().all()

            if not users:
                logger.info("Участников челленджа не найдено (lead_source=challenge)")
                return

            logger.info(f"Начинаем восстановление челленджа для {len(users)} участников...")
            restored = 0
            for user in users:
                await register_challenge(session, user)
                restored += 1
                if restored % 5 == 0:
                    logger.info(f"Восстановлено: {restored}/{len(users)}...")

            await session.commit()
            logger.info(f"ГОТОВО! Челлендж восстановлен для {len(users)} участников. "
                        f"Завтра в 10:00 все получат сообщение!")

    except Exception as e:
        logger.error(f"Ошибка восстановления челленджа: {e}", exc_info=True)

# === ПЛАНИРОВЩИК (Алматы +05) ===
async def scheduled_broadcast():
    while True:
        try:
            now = datetime.now(ZoneInfo("Asia/Almaty"))
            next_check = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            sleep_time = (next_check - now).total_seconds()
            logger.info(f"Следующая проверка рассылок: {next_check.strftime('%H:%M:%S')} (Алматы +05)")
            await asyncio.sleep(sleep_time)

            async with async_session_maker() as session:
                await send_scheduled_broadcasts(session, bot)

        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}", exc_info=True)
            await asyncio.sleep(60)

async def main():
    global bot  
    bot = Bot(token=os.getenv("BOT_TOKEN"), default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    # Middleware
    dp.message.middleware(DataBaseSession(async_session_maker))
    dp.callback_query.middleware(DataBaseSession(async_session_maker))

    # Роутеры
    dp.include_router(admin_router)
    dp.include_router(common_router)
    dp.include_router(webinar_router)
    dp.include_router(challenge_router)
    dp.include_router(lead_magnet_router)

    @dp.message(F.text == "/myid")
    async def my_id_handler(message: Message):
        await get_my_user_id(message)

    await wait_for_db()
    dp.startup.register(create_db)
    
    asyncio.create_task(scheduled_broadcast())

    asyncio.create_task(restore_challenge_for_current_users())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())