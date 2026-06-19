from sqlalchemy import select

from bot.database import get_session
from bot.models import SuperAdmin


async def is_superadmin(telegram_id: int) -> bool:
    async with get_session() as session:
        return await session.get(SuperAdmin, telegram_id) is not None


async def list_superadmins() -> list[SuperAdmin]:
    async with get_session() as session:
        result = await session.scalars(
            select(SuperAdmin).order_by(SuperAdmin.added_at)
        )
        return list(result)
