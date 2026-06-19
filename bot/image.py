"""Генерация картинки с результатом опроса.

Дизайн ВСЕГДА одинаковый — меняются только название направления, описание и цифры.
Можно положить свои файлы в assets/, и они будут использованы автоматически:
  - assets/background.png  — фон 1080x1350 (если нет — рисуется градиент)
  - assets/font.ttf        — обычный шрифт (с поддержкой кириллицы)
  - assets/font-bold.ttf   — жирный шрифт
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from bot.config import ASSETS_DIR

WIDTH = 1080

# Палитра
BG_TOP = (37, 42, 74)
BG_BOTTOM = (18, 20, 38)
CARD = (255, 255, 255)
ACCENT = (108, 99, 255)
TEXT_DARK = (33, 37, 53)
TEXT_MUTED = (120, 126, 150)
BAR_BG = (232, 233, 245)

_FONT_CANDIDATES_REGULAR = [
    ASSETS_DIR / "font.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONT_CANDIDATES_BOLD = [
    ASSETS_DIR / "font-bold.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


@dataclass
class DirectionResult:
    name: str
    emoji: str
    points: int
    percent: int
    is_top: bool


def _load_font(candidates, size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient_background(height: int) -> Image.Image:
    bg_path = ASSETS_DIR / "background.png"
    if bg_path.exists():
        try:
            return Image.open(bg_path).convert("RGB").resize((WIDTH, height))
        except OSError:
            pass
    img = Image.new("RGB", (WIDTH, height), BG_TOP)
    top, bottom = BG_TOP, BG_BOTTOM
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    return img


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


MARGIN = 70           # горизонтальный отступ карточки от края
OUTER_V = 80          # вертикальный отступ карточки от края
PAD = 60              # внутренний отступ карточки
BAR_H = 40
ROW_GAP = 90          # шаг между строками разбивки


def generate_result_image(
    top_name: str,
    top_emoji: str,
    top_description: str,
    breakdown: list[DirectionResult],
) -> BytesIO:
    f_small = _load_font(_FONT_CANDIDATES_REGULAR, 30)
    f_label = _load_font(_FONT_CANDIDATES_BOLD, 34)
    f_desc = _load_font(_FONT_CANDIDATES_REGULAR, 34)
    f_title = _load_font(_FONT_CANDIDATES_BOLD, 72)
    f_header = _load_font(_FONT_CANDIDATES_BOLD, 44)
    f_pct = _load_font(_FONT_CANDIDATES_BOLD, 30)

    card_x0 = MARGIN
    card_x1 = WIDTH - MARGIN
    inner = card_x0 + PAD
    inner_right = card_x1 - PAD
    inner_w = inner_right - inner

    # Разметку текста считаем заранее, на временном холсте.
    measure = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title_lines = _wrap(measure, top_name, f_title, inner_w)
    desc_lines = _wrap(measure, top_description, f_desc, inner_w) if top_description else []

    def render(draw, card_y0: int) -> int:
        y = card_y0 + PAD
        # Шапка
        header = "Ваш результат"
        hw = draw.textlength(header, font=f_header)
        draw.text(((WIDTH - hw) / 2, y), header, font=f_header, fill=ACCENT)
        y += 44 + 50
        # Топ-направление (эмодзи не рисуем: системные шрифты дают «квадратики»)
        for line in title_lines:
            lw = draw.textlength(line, font=f_title)
            draw.text(((WIDTH - lw) / 2, y), line, font=f_title, fill=TEXT_DARK)
            y += 88
        y += 28
        # Описание
        for line in desc_lines:
            lw = draw.textlength(line, font=f_desc)
            draw.text(((WIDTH - lw) / 2, y), line, font=f_desc, fill=TEXT_MUTED)
            y += 48
        y += 46
        # Разбивка по направлениям
        draw.text((inner, y), "Склонность по направлениям", font=f_label, fill=TEXT_DARK)
        y += 64
        for idx, item in enumerate(breakdown):
            draw.text((inner, y), item.name, font=f_small, fill=TEXT_DARK)
            pct_text = f"{item.percent}%"
            pw = draw.textlength(pct_text, font=f_pct)
            draw.text(
                (inner_right - pw, y),
                pct_text,
                font=f_pct,
                fill=ACCENT if item.is_top else TEXT_MUTED,
            )
            bar_y = y + 42
            _rounded(
                draw, (inner, bar_y, inner_right, bar_y + BAR_H), BAR_H // 2, BAR_BG
            )
            fill_w = int(inner_w * item.percent / 100)
            if fill_w > BAR_H:
                color = ACCENT if item.is_top else (170, 165, 240)
                _rounded(
                    draw, (inner, bar_y, inner + fill_w, bar_y + BAR_H), BAR_H // 2, color
                )
            y = bar_y + BAR_H if idx == len(breakdown) - 1 else y + ROW_GAP
        return y

    # Замер итоговой высоты, затем отрисовка на холсте нужного размера.
    content_bottom = render(ImageDraw.Draw(Image.new("RGB", (WIDTH, 10))), OUTER_V)
    card_y1 = content_bottom + PAD
    height = card_y1 + OUTER_V

    img = _gradient_background(height)
    draw = ImageDraw.Draw(img)
    _rounded(draw, (card_x0, OUTER_V, card_x1, card_y1), 48, CARD)
    render(draw, OUTER_V)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# Карточки ролей: отдельные готовые картинки в assets/.
# Индекс совпадает с position направления (0 — первая роль в seed.py … 7 — последняя).
CARD_FILES = [
    "Консультант-эксперт.png",
    "Мерчендайзер.png",
    "Специалист по закупкам.png",
    "SMM - Маркетолог.png",
    "Логист.png",
    "Системный администратор.png",
    "Бухгалтер.png",
    "Электрик.png",
]


# Telegram сужает слишком «вытянутые» фото (упирается в лимит высоты) и оставляет
# тёмные поля по бокам. Приводим карточку к соотношению не выше 4:5 (h/w ≤ 1.25),
# дорисовывая белые поля по бокам — тогда фото показывается во всю ширину чата.
_MAX_RATIO = 1.25
_PAD_COLOR = (255, 255, 255)


def card_image_for_position(position: int) -> BytesIO | None:
    """Отдаёт карточку роли по её позиции из assets/, подогнанную под ширину чата."""
    if position is None or not (0 <= position < len(CARD_FILES)):
        return None
    path = ASSETS_DIR / CARD_FILES[position]
    if not path.exists():
        return None
    try:
        img = Image.open(path).convert("RGB")
    except OSError:
        return None

    w, h = img.size
    if h / w > _MAX_RATIO:
        target_w = math.ceil(h / _MAX_RATIO)
        canvas = Image.new("RGB", (target_w, h), _PAD_COLOR)
        canvas.paste(img, ((target_w - w) // 2, 0))
        img = canvas

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def build_breakdown(
    scores_by_name: dict[str, int],
    emoji_by_name: dict[str, str],
    top_name: str | None,
) -> list[DirectionResult]:
    total = sum(max(0, v) for v in scores_by_name.values())
    items: list[DirectionResult] = []
    for name, points in scores_by_name.items():
        pts = max(0, points)
        percent = round(pts * 100 / total) if total > 0 else 0
        items.append(
            DirectionResult(
                name=name,
                emoji=emoji_by_name.get(name, ""),
                points=points,
                percent=percent,
                is_top=(name == top_name),
            )
        )
    items.sort(key=lambda i: i.points, reverse=True)
    return items
