"""Админ-панель (только для суперадминов).

Разделы вынесены в reply-кнопки нижнего меню: участники и их результаты,
случайный выбор победителя, выгрузка результатов в Excel, свои тестовые
прохождения. Drill-down (пагинация, карточка участника, перевыбор, удаление)
остаётся на inline-кнопках. Редактирование опроса через Telegram не ведётся.
"""

import json
import random

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from bot import config
from bot.database import get_session
from bot.export import build_results_xlsx
from bot.keyboards import (
    BTN_ADMINS,
    BTN_EXPORT,
    BTN_MYTESTS,
    BTN_PARTICIPANTS,
    BTN_WINNER,
    BTN_WIPE,
    main_menu_keyboard,
)
from bot.models import (
    Participation,
    ParticipationAnswer,
    Respondent,
    SuperAdmin,
)
from bot.permissions import is_superadmin
from bot.states import AdminStates

router = Router()

PAGE_SIZE = 8


class IsSuperAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and await is_superadmin(user.id)


router.callback_query.filter(IsSuperAdmin())
router.message.filter(IsSuperAdmin())


# ----------------------------- утилиты -----------------------------

async def safe_edit(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        # сообщение нельзя отредактировать (например, это фото) — шлём новое
        await callback.message.answer(text, reply_markup=markup)


def _truncate(text: str, limit: int = 40) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ----------------------------- участники -----------------------------

async def _participants_view(page: int) -> tuple[str, InlineKeyboardMarkup]:
    async with get_session() as session:
        total = (
            await session.scalar(
                select(func.count(Participation.id)).where(
                    Participation.is_test.is_(False)
                )
            )
            or 0
        )
        rows = list(
            await session.scalars(
                select(Participation)
                .where(Participation.is_test.is_(False))
                .options(
                    selectinload(Participation.respondent),
                    selectinload(Participation.top_direction),
                )
                .order_by(Participation.completed_at.desc())
                .offset(page * PAGE_SIZE)
                .limit(PAGE_SIZE)
            )
        )

    kb = InlineKeyboardBuilder()
    if not rows:
        text = "👥 <b>Участники</b>\n\nПока никто не прошёл опрос."
    else:
        text = f"👥 <b>Участники</b> (всего: {total})\n\nНажмите для подробностей:"
        for p in rows:
            r = p.respondent
            name = r.first_name or r.username or str(r.telegram_id)
            top = p.top_direction.name if p.top_direction else "—"
            kb.button(
                text=f"{_truncate(name, 22)} → {top}",
                callback_data=f"adm:part:{r.telegram_id}",
            )

    nav = []
    if page > 0:
        nav.append(("⬅️", f"adm:participants:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(("➡️", f"adm:participants:{page + 1}"))
    for text_btn, cb in nav:
        kb.button(text=text_btn, callback_data=cb)

    sizes = [1] * len(rows)
    if nav:
        sizes.append(len(nav))
    if sizes:
        kb.adjust(*sizes)
    return text, kb.as_markup()


@router.message(StateFilter(None), F.text == BTN_PARTICIPANTS)
async def participants_entry(message: Message) -> None:
    text, markup = await _participants_view(0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:participants:"))
async def participants_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[2])
    text, markup = await _participants_view(page)
    await safe_edit(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:part:"))
async def participant_detail(callback: CallbackQuery) -> None:
    tid = int(callback.data.split(":")[2])
    async with get_session() as session:
        p = await session.scalar(
            select(Participation)
            .where(
                Participation.respondent_id == tid,
                Participation.is_test.is_(False),
            )
            .order_by(Participation.completed_at.desc())
            .limit(1)
            .options(
                selectinload(Participation.respondent),
                selectinload(Participation.top_direction),
            )
        )
        if p is None:
            await callback.answer("Не найдено.", show_alert=True)
            return
        r = p.respondent
        scores = json.loads(p.scores_json or "{}")

    name = " ".join(filter(None, [r.first_name, r.last_name])) or "—"
    uname = f"@{r.username}" if r.username else "—"
    top = p.top_direction.name if p.top_direction else "—"
    lines = [
        f"👤 <b>{name}</b>",
        f"🎟️ Номерок: <b>{r.ticket or '—'}</b>",
        f"Username: {uname}",
        f"Telegram ID: <code>{r.telegram_id}</code>",
        f"Дата: {p.completed_at:%d.%m.%Y %H:%M}",
        f"\n🏆 Ведущее направление: <b>{top}</b>\n",
        "<b>Баллы по направлениям:</b>",
    ]
    for dname, pts in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  • {dname}: <b>{pts}</b>")

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ К списку участников", callback_data="adm:participants:0")
    await safe_edit(callback, "\n".join(lines), kb.as_markup())
    await callback.answer()


# ----------------------------- выгрузка в Excel -----------------------------

@router.message(StateFilter(None), F.text == BTN_EXPORT)
async def export_entry(message: Message) -> None:
    buf = await build_results_xlsx()
    await message.answer_document(
        BufferedInputFile(buf.read(), filename="results.xlsx"),
        caption="📊 Результаты опроса",
    )


# ----------------------------- выбор победителя -----------------------------

def _winner_card(r: Respondent, top: str) -> str:
    name = " ".join(filter(None, [r.first_name, r.last_name])) or "—"
    uname = f"@{r.username}" if r.username else "—"
    return (
        "🎲 <b>Победитель розыгрыша</b>\n\n"
        f"🏆 <b>{name}</b>\n"
        f"🎟️ Номерок: <b>{r.ticket or '—'}</b>\n"
        f"Username: {uname}\n"
        f"Telegram ID: <code>{r.telegram_id}</code>\n"
        f"Ведущее направление: <b>{top}</b>"
    )


async def _winner_view(bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
    async with get_session() as session:
        rows = list(
            await session.scalars(
                select(Participation)
                .where(Participation.is_test.is_(False))
                .options(
                    selectinload(Participation.respondent),
                    selectinload(Participation.top_direction),
                )
            )
        )

    # один участник = одно реальное прохождение, но на всякий случай дедуплицируем
    by_id = {p.respondent_id: p for p in rows if p.respondent is not None}
    candidates = list(by_id.values())

    if not candidates:
        return (
            "🎲 <b>Выбор победителя</b>\n\nПока никто не прошёл опрос — "
            "выбирать не из кого.",
            InlineKeyboardBuilder().as_markup(),
        )

    winner = random.choice(candidates)
    r = winner.respondent
    top = winner.top_direction.name if winner.top_direction else "—"

    # сразу пишем победителю автоматически, без отдельного подтверждения
    try:
        await bot.send_message(
            r.telegram_id,
            "🎉 <b>Поздравляем!</b>\n\n"
            "Вы стали победителем розыгрыша среди участников опроса. "
            "Организатор скоро свяжется с вами. 🥳",
        )
        sent = True
    except TelegramBadRequest:
        sent = False

    kb = InlineKeyboardBuilder()
    kb.button(text="🎲 Выбрать заново", callback_data="adm:winner")
    notice = (
        "✅ Сообщение победителю отправлено."
        if sent
        else "⚠️ Не удалось написать победителю — возможно, он не запускал "
        "бота или заблокировал его. Свяжитесь с ним другим способом."
    )
    text = (
        _winner_card(r, top)
        + f"\n\n<i>Всего участников: {len(candidates)}.</i>\n\n"
        + notice
    )
    return text, kb.as_markup()


@router.message(StateFilter(None), F.text == BTN_WINNER)
async def winner_entry(message: Message) -> None:
    text, markup = await _winner_view(message.bot)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:winner")
async def winner_repick(callback: CallbackQuery) -> None:
    text, markup = await _winner_view(callback.bot)
    await safe_edit(callback, text, markup)
    await callback.answer("🎉 Победитель выбран!")


# ----------------------------- мои тестовые прохождения -----------------------------

async def _mytests_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with get_session() as session:
        rows = list(
            await session.scalars(
                select(Participation)
                .where(Participation.respondent_id == user_id)
                .order_by(Participation.completed_at.desc())
                .options(selectinload(Participation.top_direction))
            )
        )

    kb = InlineKeyboardBuilder()
    if not rows:
        text = (
            "🧪 <b>Мои прохождения</b>\n\n"
            "У вас пока нет своих прохождений опроса.\n"
            "Пройдите опрос через «Начать опрос» — он сохранится как тестовый и "
            "не повлияет на общую статистику."
        )
    else:
        text = (
            "🧪 <b>Мои прохождения</b>\n\n"
            "Здесь только ваши прохождения. Они помечены как тестовые и не "
            "учитываются в статистике. Можно удалить любое."
        )
        for p in rows:
            top = p.top_direction.name if p.top_direction else "—"
            kb.button(
                text=f"🗑 {p.completed_at:%d.%m %H:%M} → {top}",
                callback_data=f"adm:mytest_del:{p.id}",
            )
        kb.button(text="🗑 Удалить все мои", callback_data="adm:mytests_delall")
        kb.adjust(1)
    return text, kb.as_markup()


@router.message(StateFilter(None), F.text == BTN_MYTESTS)
async def mytests_entry(message: Message) -> None:
    text, markup = await _mytests_view(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:mytest_del:"))
async def my_test_delete(callback: CallbackQuery) -> None:
    pid = int(callback.data.split(":")[2])
    async with get_session() as session:
        p = await session.get(Participation, pid)
        # удалять можно только своё прохождение
        if p is not None and p.respondent_id == callback.from_user.id:
            await session.delete(p)
            await session.commit()
            await callback.answer("Прохождение удалено.")
        else:
            await callback.answer("Это не ваше прохождение.", show_alert=True)
    text, markup = await _mytests_view(callback.from_user.id)
    await safe_edit(callback, text, markup)


@router.callback_query(F.data == "adm:mytests_delall")
async def my_tests_delall_confirm(callback: CallbackQuery) -> None:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить все мои", callback_data="adm:mytests_delall_yes")
    kb.button(text="⬅️ Отмена", callback_data="adm:mytests_back")
    kb.adjust(1)
    await safe_edit(
        callback,
        "⚠️ Удалить <b>все ваши</b> прохождения опроса?",
        kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:mytests_back")
async def my_tests_back(callback: CallbackQuery) -> None:
    text, markup = await _mytests_view(callback.from_user.id)
    await safe_edit(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data == "adm:mytests_delall_yes")
async def my_tests_delall(callback: CallbackQuery) -> None:
    async with get_session() as session:
        rows = list(
            await session.scalars(
                select(Participation).where(
                    Participation.respondent_id == callback.from_user.id
                )
            )
        )
        for p in rows:
            await session.delete(p)  # ORM-каскад удалит и сохранённые ответы
        await session.commit()
    await callback.answer("Удалено.")
    text, markup = await _mytests_view(callback.from_user.id)
    await safe_edit(callback, text, markup)


# ----------------------------- суперадмины -----------------------------

async def _admins_view() -> tuple[str, InlineKeyboardMarkup]:
    async with get_session() as session:
        rows = list(
            await session.scalars(
                select(SuperAdmin).order_by(SuperAdmin.added_at)
            )
        )

    text = (
        "👑 <b>Суперадмины</b>\n\n"
        "Им доступны все админ-разделы. Чтобы добавить — нажмите кнопку ниже и "
        "пришлите Telegram ID (узнать можно у @userinfobot).\n\n"
        "🔒 Главный суперадмин из настроек сервера (.env) не удаляется отсюда.\n\n"
        "<b>Список:</b>"
    )
    kb = InlineKeyboardBuilder()
    sizes = []
    for sa in rows:
        is_root = sa.telegram_id == config.SUPERADMIN_ID
        mark = " 🔒" if is_root else ""
        text += f"\n  • <code>{sa.telegram_id}</code>{mark}"
        if not is_root:
            kb.button(
                text=f"🗑 Удалить {sa.telegram_id}",
                callback_data=f"adm:admin_del:{sa.telegram_id}",
            )
            sizes.append(1)
    kb.button(text="➕ Добавить суперадмина", callback_data="adm:admin_add")
    sizes.append(1)
    kb.adjust(*sizes)
    return text, kb.as_markup()


@router.message(StateFilter(None), F.text == BTN_ADMINS)
async def admins_entry(message: Message) -> None:
    text, markup = await _admins_view()
    await message.answer(text, reply_markup=markup)


ADD_ADMIN_REQUEST_ID = 1
ADD_ADMIN_CANCEL = "⬅️ Отмена"


def _add_admin_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура шага добавления: нативный пикер + отмена."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📇 Выбрать из контактов",
                    request_users=KeyboardButtonRequestUsers(
                        request_id=ADD_ADMIN_REQUEST_ID,
                        max_quantity=1,
                    ),
                )
            ],
            [KeyboardButton(text=ADD_ADMIN_CANCEL)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Введите ID или выберите контакт",
    )


async def _promote_admin(new_id: int, adder_id: int) -> str:
    """Добавляет суперадмина (идемпотентно), возвращает текст-итог для админа."""
    async with get_session() as session:
        if await session.get(SuperAdmin, new_id) is not None:
            return f"ℹ️ Пользователь <code>{new_id}</code> уже суперадмин."
        session.add(SuperAdmin(telegram_id=new_id, added_by=adder_id))
        await session.commit()
    return (
        f"✅ Пользователь <code>{new_id}</code> добавлен в суперадмины.\n\n"
        "Ему нужно нажать /start, чтобы увидеть админское меню."
    )


async def _exit_add_admin(message: Message, state: FSMContext, result: str) -> None:
    await state.clear()
    # request_users-клавиатуру часть клиентов не заменяет обычной reply-кнопкой,
    # поэтому сначала явно убираем её, затем возвращаем постоянное меню админа.
    await message.answer(result, reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "👑 Меню админа ниже 👇", reply_markup=main_menu_keyboard(True, False)
    )


@router.callback_query(F.data == "adm:admin_add")
async def admin_add_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_admin_id)
    await callback.message.answer(
        "➕ <b>Добавление суперадмина</b>\n\n"
        "Два способа:\n"
        "📇 нажмите <b>«Выбрать из контактов»</b> и выберите человека — его ID "
        "подставится сам;\n"
        "✏️ или пришлите <b>Telegram ID</b> числом (узнать можно у @userinfobot).\n\n"
        "Для отмены — кнопка «Отмена» или /cancel.",
        reply_markup=_add_admin_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_admin_id, F.users_shared)
async def admin_add_shared(message: Message, state: FSMContext) -> None:
    shared = message.users_shared
    ids = [u.user_id for u in shared.users] if shared.users else list(
        shared.user_ids or []
    )
    if not ids:
        await _exit_add_admin(
            message, state, "⚠️ Не удалось получить пользователя — попробуйте ещё раз."
        )
        return
    result = await _promote_admin(ids[0], message.from_user.id)
    await _exit_add_admin(message, state, result)


@router.message(AdminStates.waiting_admin_id, F.text)
async def admin_add_id(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()

    if value in ("/cancel", ADD_ADMIN_CANCEL):
        await _exit_add_admin(message, state, "Отменено.")
        return

    if not value.isdigit():
        await message.answer(
            "🤔 ID состоит только из цифр. Пришлите числовой Telegram ID, "
            "выберите контакт кнопкой или отправьте /cancel."
        )
        return

    result = await _promote_admin(int(value), message.from_user.id)
    await _exit_add_admin(message, state, result)


@router.callback_query(F.data.startswith("adm:admin_del:"))
async def admin_delete(callback: CallbackQuery) -> None:
    target = int(callback.data.split(":")[2])
    if target == config.SUPERADMIN_ID:
        await callback.answer(
            "🔒 Это главный суперадмин из .env — его нельзя удалить отсюда.",
            show_alert=True,
        )
        return
    async with get_session() as session:
        sa = await session.get(SuperAdmin, target)
        if sa is not None:
            await session.delete(sa)
            await session.commit()
            await callback.answer("Суперадмин удалён.")
        else:
            await callback.answer("Уже удалён.")
    text, markup = await _admins_view()
    await safe_edit(callback, text, markup)


# ----------------------------- полная очистка опроса -----------------------------

@router.message(StateFilter(None), F.text == BTN_WIPE)
async def wipe_prompt(message: Message, state: FSMContext) -> None:
    if not config.WIPE_PASSWORD:
        await message.answer(
            "⚠️ Пароль для удаления не задан. Укажите WIPE_PASSWORD в файле .env "
            "и перезапустите бота."
        )
        return
    await state.set_state(AdminStates.waiting_wipe_password)
    await message.answer(
        "🗑 <b>Удаление всего опроса</b>\n\n"
        "Будут <b>безвозвратно</b> удалены все результаты, ответы и участники "
        "(их номерки освободятся). Вопросы и направления останутся.\n\n"
        "Чтобы подтвердить — введите <b>пароль</b>.\n"
        "Для отмены отправьте /cancel.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AdminStates.waiting_wipe_password, F.text)
async def wipe_confirm(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    admin_kb = main_menu_keyboard(True, False)

    if value == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_kb)
        return

    if value != config.WIPE_PASSWORD:
        await message.answer(
            "⛔️ Неверный пароль. Попробуйте ещё раз или отправьте /cancel."
        )
        return

    await state.clear()
    async with get_session() as session:
        # порядок важен из-за внешних ключей
        await session.execute(delete(ParticipationAnswer))
        await session.execute(delete(Participation))
        await session.execute(delete(Respondent))
        await session.commit()

    await message.answer(
        "✅ Опрос полностью очищен: результаты и участники удалены, "
        "номерки освобождены.",
        reply_markup=admin_kb,
    )
