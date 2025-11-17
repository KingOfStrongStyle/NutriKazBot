from datetime import datetime
from sqlalchemy import (
    BigInteger, String, Integer, Text, ForeignKey, DateTime, Enum, Boolean, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from dotenv import load_dotenv
import enum
import os


# ---------------------------------------------------------------------
# Загрузка переменных окружения (.env)
# ---------------------------------------------------------------------
load_dotenv()

# URL для подключения к БД (формат postgresql+asyncpg)
DATABASE_URL = os.getenv("SQLALCHEMY_URL")

# ---------------------------------------------------------------------
# Инициализация асинхронного движка и пула сессий SQLAlchemy
# ---------------------------------------------------------------------
engine = create_async_engine(
    DATABASE_URL,
    echo=True  
)

# Пул асинхронных сессий для безопасной работы с БД
async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession
)


# =====================================================================
# Базовая модель
# ---------------------------------------------------------------------
# Все таблицы будут наследовать этот класс.
# Добавлены стандартные поля created / updated для аудита изменений.
# =====================================================================
class Base(DeclarativeBase):
    created: Mapped[datetime] = mapped_column(
        DateTime, default=func.now()
    )  

    updated: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )  


# =====================================================================
# Перечисление (Enum): тип источника лида
# ---------------------------------------------------------------------
# Используется для идентификации типа воронки (webinar, challenge и т.д.)
# =====================================================================
class LeadType(enum.Enum):
    WEBINAR = "webinar"
    LEAD_MAGNET = "lead_magnet"
    CHALLENGE = "challenge"


# =====================================================================
# Модель: LeadSource
# ---------------------------------------------------------------------
# Таблица источников лидов (воронок). Например:
#  - вебинар
#  - марафон
#  - лид-магнит
# Один источник может быть связан с несколькими пользователями.
# =====================================================================
class LeadSource(Base):
    __tablename__ = "lead_source"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship("User", back_populates="lead_source")


# =====================================================================
# Модель: User
# ---------------------------------------------------------------------
# Таблица пользователей Telegram.
# Содержит основную информацию и связь с источником лида.
# =====================================================================
class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    user_id: Mapped[int] = mapped_column(
        BigInteger, 
        unique=True, 
        index=True, 
        nullable=False  
    )
    
    username: Mapped[str] = mapped_column(String(150), nullable=True)
    first_name: Mapped[str] = mapped_column(String(150), nullable=True)
    last_name: Mapped[str] = mapped_column(String(150), nullable=True)
    phone: Mapped[str] = mapped_column(String(13), nullable=True)

    lead_source_id: Mapped[int] = mapped_column(
        ForeignKey("lead_source.id", ondelete="SET NULL"), nullable=True
    )

    registered_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    lead_source: Mapped["LeadSource"] = relationship("LeadSource", back_populates="users")
    schedules: Mapped[list["MessageSchedule"]] = relationship("MessageSchedule", back_populates="user")


# =====================================================================
# Модель: MessageSchedule
# ---------------------------------------------------------------------
# Таблица индивидуальных сообщений, запланированных для пользователя.
# Используется совместно с APScheduler для рассылки в заданное время.
# =====================================================================
class MessageSchedule(Base):
    __tablename__ = "message_schedule"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    send_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship("User", back_populates="schedules")

    def __repr__(self) -> str:
        return f"<MessageSchedule user={self.user_id} send_time={self.send_time}>"


# =====================================================================
# Модель: Broadcast
# ---------------------------------------------------------------------
# Таблица массовых рассылок — хранит текст, дату планирования и статус.
# Может фильтроваться по типу воронки (LeadSource).
# =====================================================================
class Broadcast(Base):
    __tablename__ = "broadcast"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, default='')
    file_path: Mapped[str] = mapped_column(String, nullable=True)
    file_type: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    file_id: Mapped[str] = mapped_column(String, nullable=True)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    target_lead_id: Mapped[int] = mapped_column(
        ForeignKey("lead_source.id", ondelete="SET NULL"), nullable=True
    )
    lead_source: Mapped["LeadSource"] = relationship("LeadSource")

    def __repr__(self) -> str:
        return f"<Broadcast '{self.title}' target_lead={self.target_lead_id}>"
    
    
class StageText(Base):
    __tablename__ = "stage_texts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  
    welcome_text: Mapped[str] = mapped_column(Text, nullable=False) 
    main_menu_text: Mapped[str] = mapped_column(Text, nullable=False) 
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class FeedbackOptions(Base):
    __tablename__ = "feedback_options"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)  
    option_1: Mapped[str] = mapped_column(String(100), nullable=False)
    option_2: Mapped[str] = mapped_column(String(100), nullable=False)
    option_3: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<FeedbackOptions stage={self.stage}>"