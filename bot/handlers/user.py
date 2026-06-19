import json
import random

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message, ReplyKeyboardRemove
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from bot.database import get_session
from bot.image import build_breakdown, card_image_for_position
from bot.keyboards import (
    BTN_BACK,
    BTN_RESULT,
    BTN_START,
    main_menu_keyboard,
    question_keyboard,
)
from bot.models import (
    Direction,
    Participation,
    ParticipationAnswer,
    Question,
    Respondent,
)
from bot.permissions import is_superadmin
from bot.scoring import compute_scores, resolve_top
from bot.states import SurveyStates

router = Router()

INTRO_TEXT = (
    "👋 <b>Добро пожаловать в опрос!</b>\n\n"
    "Опрос поможет определить, к какому направлению работы вы больше склонны.\n"
    "Вам будет показано несколько вопросов — по одному, с вариантами ответа.\n\n"
    "⚠️ <b>Важно:</b> пройти опрос можно только <b>один раз</b>. "
    "Повторное прохождение недоступно, чтобы не искажать результаты. "
    "Отвечайте честно 🙂\n\n"
    "Когда будете готовы — нажмите кнопку меню ниже."
)

ASK_TICKET_TEXT = (
    "👋 <b>Добро пожаловать!</b>\n\n"
    "Рады видеть вас 🎉 Этот опрос определит, к какому направлению работы вы "
    "больше склонны, а ещё сделает вас участником <b>розыгрыша</b>.\n\n"
    "Для начала введите <b>номер вашего билетика</b> — тот номерок, который вам "
    "выдали. Он закрепится лично за вами и будет участвовать в розыгрыше.\n\n"
    "⚠️ Номерок вводится <b>только один раз</b> и не может повторяться у разных "
    "участников, поэтому проверьте цифры перед отправкой.\n\n"
    "✏️ Просто отправьте номер сообщением."
)

TICKET_TAKEN_TEXT = (
    "⛔️ Этот номерок уже закреплён за другим участником.\n\n"
    "Проверьте номер на своём билетике и отправьте его ещё раз."
)

TICKET_BAD_TEXT = (
    "🤔 Номерок состоит только из цифр. "
    "Отправьте номер с вашего билетика, например: <code>123</code>"
)

ALREADY_DONE_TEXT = (
    "✅ Вы уже проходили этот опрос.\n\n"
    "Повторное прохождение недоступно, чтобы не искажать результаты. "
    "Спасибо за участие!"
)

FINISH_TEXT = (
    "🎉 <b>Опрос успешно пройден!</b>\n\n"
    "Спасибо за участие 🙌 Ваш номерок уже в розыгрыше.\n\n"
    "Теперь остаётся дождаться <b>выбора победителя</b>. Если повезёт именно "
    "вам — бот пришлёт сообщение прямо сюда, в этот чат.\n\n"
    "📩 Поэтому заглядывайте сюда и проверяйте сообщения!"
)


async def _get_or_create_respondent(session, user) -> Respondent:
    respondent = await session.get(Respondent, user.id)
    if respondent is None:
        respondent = Respondent(telegram_id=user.id)
        session.add(respondent)
    respondent.username = user.username or ""
    respondent.first_name = user.first_name or ""
    respondent.last_name = user.last_name or ""
    return respondent


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    admin = await is_superadmin(message.from_user.id)

    async with get_session() as session:
        respondent = await _get_or_create_respondent(session, message.from_user)
        ticket = respondent.ticket
        done = await session.scalar(
            select(Participation).where(
                Participation.respondent_id == message.from_user.id
            )
        )
        await session.commit()

    # суперадмин: ticket не требуется, разделы админки — в нижнем меню (reply)
    if admin:
        intro = INTRO_TEXT + (
            "\n\n🧪 <i>Вы суперадмин: можете проходить опрос много раз, "
            "ваши результаты не учитываются в общей статистике.\n"
            "Разделы админки — в кнопках меню ниже.</i>"
        )
        await message.answer(
            intro, reply_markup=main_menu_keyboard(True, done is not None)
        )
        return

    if done is not None:
        await message.answer(
            ALREADY_DONE_TEXT, reply_markup=main_menu_keyboard(False, True)
        )
        return

    # номерок ещё не введён — просим его, опрос начнётся только после ввода
    if ticket is None:
        await state.set_state(SurveyStates.waiting_ticket)
        await message.answer(ASK_TICKET_TEXT, reply_markup=ReplyKeyboardRemove())
        return

    # номерок уже есть, но опрос не пройден — даём начать
    await message.answer(INTRO_TEXT, reply_markup=main_menu_keyboard(False, False))


@router.message(SurveyStates.waiting_ticket, F.text)
async def handle_ticket(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value.isdigit():
        await message.answer(TICKET_BAD_TEXT)
        return

    async with get_session() as session:
        taken = await session.scalar(
            select(Respondent).where(
                Respondent.ticket == value,
                Respondent.telegram_id != message.from_user.id,
            )
        )
        if taken is not None:
            await message.answer(TICKET_TAKEN_TEXT)
            return
        respondent = await session.get(Respondent, message.from_user.id)
        if respondent.ticket is None:
            respondent.ticket = value
            try:
                await session.commit()
            except IntegrityError:
                # гонка: тот же номерок успел занять кто-то другой
                await session.rollback()
                await message.answer(TICKET_TAKEN_TEXT)
                return

    await message.answer(
        f"✅ Номерок <b>{value}</b> закреплён за вами!\n\n"
        "Поехали — отвечайте честно 🙂"
    )
    await _begin_survey(message, state)


async def _begin_survey(message: Message, state: FSMContext) -> None:
    async with get_session() as session:
        questions = await session.scalars(
            select(Question)
            .where(Question.is_active.is_(True))
            .order_by(Question.position, Question.id)
        )
        question_ids = [q.id for q in questions]

    if not question_ids:
        await message.answer("Опрос пока не настроен.")
        return

    # перемешиваем порядок вопросов для каждого прохождения
    random.shuffle(question_ids)
    await state.set_state(SurveyStates.in_progress)
    await state.update_data(question_ids=question_ids, idx=0, answers={})
    await _show_question(message, question_ids[0], 0, len(question_ids))


@router.message(StateFilter(None), F.text == BTN_START)
async def start_survey(message: Message, state: FSMContext) -> None:
    admin = await is_superadmin(message.from_user.id)
    if not admin:
        async with get_session() as session:
            respondent = await session.get(Respondent, message.from_user.id)
            done = await session.scalar(
                select(Participation).where(
                    Participation.respondent_id == message.from_user.id
                )
            )
        if done is not None:
            await message.answer(
                ALREADY_DONE_TEXT, reply_markup=main_menu_keyboard(False, True)
            )
            return
        # без номерка опрос не начинаем — отправляем на его ввод
        if respondent is None or respondent.ticket is None:
            await state.set_state(SurveyStates.waiting_ticket)
            await message.answer(ASK_TICKET_TEXT, reply_markup=ReplyKeyboardRemove())
            return

    await _begin_survey(message, state)


async def _load_question(question_id: int):
    async with get_session() as session:
        question = await session.scalar(
            select(Question)
            .where(Question.id == question_id)
            .options(selectinload(Question.answers))
        )
    if question is None:
        return None, []
    # перемешиваем порядок вариантов ответа при каждом показе
    answers = list(question.answers)
    random.shuffle(answers)
    return question, answers


async def _show_question(message, question_id, idx, total) -> None:
    question, answers = await _load_question(question_id)
    if question is None:
        return
    text = f"<b>Вопрос {idx + 1} из {total}</b>\n\n{question.text}"
    await message.answer(
        text, reply_markup=question_keyboard(answers, show_back=idx > 0)
    )


@router.message(SurveyStates.in_progress, F.text)
async def handle_answer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    question_ids: list[int] = data.get("question_ids", [])
    idx: int = data.get("idx", 0)
    answers: dict = data.get("answers", {})

    if idx >= len(question_ids):
        return

    chosen = (message.text or "").strip()

    # «Назад»: вернуться к предыдущему вопросу и переответить (до первого нельзя).
    if chosen == BTN_BACK:
        if idx > 0:
            idx -= 1
            answers.pop(str(question_ids[idx]), None)
            await state.update_data(idx=idx, answers=answers)
            await _show_question(message, question_ids[idx], idx, len(question_ids))
        else:
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
        return

    qid = question_ids[idx]
    async with get_session() as session:
        question = await session.scalar(
            select(Question)
            .where(Question.id == qid)
            .options(selectinload(Question.answers))
        )
    if question is None:
        return
    match = next((a for a in question.answers if a.text.strip() == chosen), None)
    if match is None:
        # Быстрый повторный тап по уже сменившейся клавиатуре (ответ относится
        # к пройденному вопросу) или случайный текст. Молча убираем сообщение,
        # чтобы не плодить дубли и нотации в чате.
        try:
            await message.delete()
        except TelegramBadRequest:
            await message.answer("Пожалуйста, выберите вариант кнопкой ниже 👇")
        return

    answers[str(qid)] = match.id
    idx += 1
    total = len(question_ids)
    await state.update_data(idx=idx, answers=answers)

    if idx < total:
        await _show_question(message, question_ids[idx], idx, total)
    else:
        await _finish_survey(message, state, answers)


def _breakdown_text(breakdown, emoji_by_name) -> str:
    lines = []
    for item in breakdown:
        emoji = emoji_by_name.get(item.name, "")
        prefix = "👑 " if item.is_top else ""
        lines.append(f"{prefix}{emoji} {item.name} — {item.percent}%")
    return "\n".join(lines)


async def _send_result(
    message, top_id, scores_by_name, directions, header: str, reply_markup=None
) -> None:
    name_by_id = {d.id: d.name for d in directions}
    emoji_by_name = {d.name: d.emoji for d in directions}
    pos_by_id = {d.id: d.position for d in directions}

    top_name = name_by_id.get(top_id, "—") if top_id else "—"
    top_emoji = emoji_by_name.get(top_name, "")
    breakdown = build_breakdown(scores_by_name, emoji_by_name, top_name)
    caption = (
        f"{header}\n\n"
        f"Ваше ведущее направление — <b>{top_emoji} {top_name}</b>.\n\n"
        f"<b>Склонность по направлениям:</b>\n{_breakdown_text(breakdown, emoji_by_name)}"
    )

    card = card_image_for_position(pos_by_id.get(top_id)) if top_id else None
    if card is not None:
        await message.answer_photo(
            BufferedInputFile(card.read(), filename="result.png"),
            caption=caption,
            reply_markup=reply_markup,
        )
    else:
        await message.answer(caption, reply_markup=reply_markup)


async def _finish_survey(message: Message, state: FSMContext, answers: dict) -> None:
    answer_ids = [int(a) for a in answers.values()]
    admin = await is_superadmin(message.from_user.id)

    async with get_session() as session:
        if not admin:
            # повторная защита от гонок: вдруг успели завершить в другом сообщении
            existing = await session.scalar(
                select(Participation).where(
                    Participation.respondent_id == message.from_user.id
                )
            )
            if existing is not None:
                await state.clear()
                await message.answer(
                    ALREADY_DONE_TEXT,
                    reply_markup=main_menu_keyboard(admin, True),
                )
                return

        scores_by_id = await compute_scores(session, answer_ids)

        # тай-брейк решает последний вопрос по позиции (№6), а не порядок показа
        q_positions = {
            q.id: q.position
            for q in await session.scalars(
                select(Question).where(
                    Question.id.in_([int(k) for k in answers])
                )
            )
        }
        ordered_answer_ids = [
            aid
            for _, aid in sorted(
                answers.items(), key=lambda kv: q_positions.get(int(kv[0]), 0)
            )
        ]
        top_id = await resolve_top(session, scores_by_id, ordered_answer_ids)

        directions = list(await session.scalars(select(Direction)))
        name_by_id = {d.id: d.name for d in directions}
        scores_by_name = {
            name_by_id[did]: pts
            for did, pts in scores_by_id.items()
            if did in name_by_id
        }

        participation = Participation(
            respondent_id=message.from_user.id,
            top_direction_id=top_id,
            scores_json=json.dumps(scores_by_name, ensure_ascii=False),
            is_test=admin,
        )
        session.add(participation)
        await session.flush()
        for qid_str, aid in answers.items():
            session.add(
                ParticipationAnswer(
                    participation_id=participation.id,
                    question_id=int(qid_str),
                    answer_id=aid,
                )
            )
        await session.commit()

    await state.clear()
    await _send_result(
        message,
        top_id,
        scores_by_name,
        directions,
        "🎯 <b>Ваш результат</b>",
        reply_markup=main_menu_keyboard(admin, True),
    )
    # реальным участникам — поздравление + напоминание про розыгрыш
    if not admin:
        await message.answer(FINISH_TEXT)


@router.message(StateFilter(None), F.text == BTN_RESULT)
async def my_result(message: Message) -> None:
    admin = await is_superadmin(message.from_user.id)
    async with get_session() as session:
        participation = await session.scalar(
            select(Participation)
            .where(Participation.respondent_id == message.from_user.id)
            .order_by(Participation.completed_at.desc(), Participation.id.desc())
            .limit(1)
        )
        if participation is None:
            await message.answer(
                "Вы ещё не проходили опрос.",
                reply_markup=main_menu_keyboard(admin, False),
            )
            return
        directions = list(await session.scalars(select(Direction)))
        scores_by_name = json.loads(participation.scores_json or "{}")
        top_id = participation.top_direction_id

    await _send_result(
        message,
        top_id,
        scores_by_name,
        directions,
        "📋 <b>Ваш результат</b>",
        reply_markup=main_menu_keyboard(admin, True),
    )


