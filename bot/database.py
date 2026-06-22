from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import DB_URL
from bot.models import Base, Participation

engine = create_async_engine(DB_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)


def _migrate(connection) -> None:
    """Приводит существующую БД к актуальной схеме:

    1) добавляет колонку is_test в participations, если её нет;
    2) снимает старое ограничение UNIQUE(respondent_id), чтобы суперадмины
       могли проходить опрос несколько раз.

    Остаточная колонка ticket в старых БД безвредна (NULL у всех) и не трогается.
    """
    insp = inspect(connection)

    columns = {c["name"] for c in insp.get_columns("participations")}
    if "is_test" not in columns:
        connection.execute(
            text(
                "ALTER TABLE participations "
                "ADD COLUMN is_test BOOLEAN NOT NULL DEFAULT 0"
            )
        )

    has_unique_respondent = any(
        ix.get("unique") and ix.get("column_names") == ["respondent_id"]
        for ix in insp.get_indexes("participations")
    ) or any(
        uc.get("column_names") == ["respondent_id"]
        for uc in insp.get_unique_constraints("participations")
    )
    if has_unique_respondent:
        connection.execute(
            text("ALTER TABLE participations RENAME TO _participations_old")
        )
        Participation.__table__.create(connection)
        connection.execute(
            text(
                "INSERT INTO participations "
                "(id, respondent_id, top_direction_id, scores_json, is_test, completed_at) "
                "SELECT id, respondent_id, top_direction_id, scores_json, "
                "COALESCE(is_test, 0), completed_at FROM _participations_old"
            )
        )
        connection.execute(text("DROP TABLE _participations_old"))


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
