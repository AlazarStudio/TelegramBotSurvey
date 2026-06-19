from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Direction(Base):
    """Направление работы, к которому можно быть склонным."""

    __tablename__ = "directions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    emoji: Mapped[str] = mapped_column(String(16), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    weights: Mapped[list["AnswerWeight"]] = relationship(
        back_populates="direction", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    answers: Mapped[list["Answer"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="Answer.position",
    )


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped["Question"] = relationship(back_populates="answers")
    weights: Mapped[list["AnswerWeight"]] = relationship(
        back_populates="answer", cascade="all, delete-orphan"
    )


class AnswerWeight(Base):
    """Сколько баллов вариант ответа даёт конкретному направлению."""

    __tablename__ = "answer_weights"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE")
    )
    direction_id: Mapped[int] = mapped_column(
        ForeignKey("directions.id", ondelete="CASCADE")
    )
    points: Mapped[int] = mapped_column(Integer, default=0)

    answer: Mapped["Answer"] = relationship(back_populates="weights")
    direction: Mapped["Direction"] = relationship(back_populates="weights")


class Respondent(Base):
    """Пользователь Telegram, прошедший (или начавший) опрос."""

    __tablename__ = "respondents"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    first_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[str] = mapped_column(String(255), default="")
    # выданный участнику номерок: уникальный, вводится один раз перед опросом
    ticket: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    participations: Mapped[list["Participation"]] = relationship(
        back_populates="respondent",
        cascade="all, delete-orphan",
    )


class Participation(Base):
    """Завершённое прохождение опроса: снимок результата."""

    __tablename__ = "participations"

    id: Mapped[int] = mapped_column(primary_key=True)
    respondent_id: Mapped[int] = mapped_column(
        ForeignKey("respondents.telegram_id", ondelete="CASCADE")
    )
    top_direction_id: Mapped[int | None] = mapped_column(
        ForeignKey("directions.id", ondelete="SET NULL"), nullable=True
    )
    # снимок баллов на момент завершения: {"Название направления": баллы}
    scores_json: Mapped[str] = mapped_column(Text, default="{}")
    # тестовое прохождение суперадмина — не учитывается в общей статистике
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    respondent: Mapped["Respondent"] = relationship(back_populates="participations")
    top_direction: Mapped["Direction | None"] = relationship()
    chosen: Mapped[list["ParticipationAnswer"]] = relationship(
        back_populates="participation", cascade="all, delete-orphan"
    )


class ParticipationAnswer(Base):
    """Сырой выбор пользователя: какой вариант он выбрал на каждый вопрос."""

    __tablename__ = "participation_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    participation_id: Mapped[int] = mapped_column(
        ForeignKey("participations.id", ondelete="CASCADE")
    )
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )
    answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL"), nullable=True
    )

    participation: Mapped["Participation"] = relationship(back_populates="chosen")


class SuperAdmin(Base):
    __tablename__ = "super_admins"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
