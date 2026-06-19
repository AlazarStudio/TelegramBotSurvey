from aiogram import Router

from bot.handlers import admin, user


def get_root_router() -> Router:
    router = Router()
    # admin сначала: его callback'и с префиксом adm:
    router.include_router(admin.router)
    router.include_router(user.router)
    return router
