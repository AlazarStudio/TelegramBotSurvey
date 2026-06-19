import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from bot import config
from bot.database import init_db
from bot.handlers import get_root_router
from bot.seed import seed_if_empty


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    config.validate()

    await init_db()
    await seed_if_empty()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # events_isolation сериализует апдейты одного пользователя: пока обрабатывается
    # текущий (ответ → следующий вопрос), новые нажатия ждут. Это убирает гонку
    # двойного старта опроса и «варианты поменялись раньше, чем обработался ответ».
    dp = Dispatcher(
        storage=MemoryStorage(),
        events_isolation=SimpleEventIsolation(),
    )
    dp.include_router(get_root_router())

    me = await bot.get_me()
    logging.info("Бот запущен: @%s", me.username)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code:
            raise
        logging.info("Остановлено.")
