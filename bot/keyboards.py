from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# подписи постоянного нижнего меню (reply-кнопки над клавиатурой)
BTN_START = "▶️ Начать опрос"
BTN_RESULT = "🎯 Мой результат"
# админские разделы — теперь тоже reply-кнопки, а не inline-панель
BTN_PARTICIPANTS = "👥 Участники"
BTN_WINNER = "🎲 Выбрать победителя"
BTN_EXPORT = "📊 Выгрузить в Excel"
BTN_MYTESTS = "🧪 Мои тестовые прохождения"
BTN_WIPE = "🗑 Удалить весь опрос"
BTN_BACK = "⬅️ Назад"


def main_menu_keyboard(is_admin: bool, done: bool) -> ReplyKeyboardMarkup:
    """Постоянное меню у поля ввода: разные кнопки в зависимости от роли/статуса."""
    if is_admin:
        rows = [
            [KeyboardButton(text=BTN_START), KeyboardButton(text=BTN_RESULT)],
            [
                KeyboardButton(text=BTN_PARTICIPANTS),
                KeyboardButton(text=BTN_WIPE),
            ],
            [
                KeyboardButton(text=BTN_EXPORT),
                KeyboardButton(text=BTN_MYTESTS),
            ],
            [KeyboardButton(text=BTN_WINNER)],
        ]
    elif done:
        rows = [[KeyboardButton(text=BTN_RESULT)]]
    else:
        rows = [[KeyboardButton(text=BTN_START)]]
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True, is_persistent=True
    )


def question_keyboard(answers, show_back: bool = False) -> ReplyKeyboardMarkup:
    # reply-клавиатура: её кнопки переносят длинный текст на несколько строк
    # и не обрезаются троеточием (в отличие от inline-кнопок)
    rows = [[KeyboardButton(text=ans.text)] for ans in answers]
    if show_back:
        rows.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите вариант кнопкой ниже",
    )


def back_button(callback_data: str, text: str = "⬅️ Назад") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)
