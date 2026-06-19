from sqlalchemy import select

from bot.models import AnswerWeight, Direction


async def compute_scores(
    session, answer_ids: list[int]
) -> dict[int, int]:
    """Суммирует баллы по направлениям для выбранных вариантов ответа.

    Возвращает {direction_id: суммарные_баллы} по ВСЕМ существующим направлениям
    (включая те, что набрали 0), чтобы результат показывал полную картину.
    """
    scores: dict[int, int] = {}
    directions = await session.scalars(select(Direction))
    for d in directions:
        scores[d.id] = 0

    if answer_ids:
        weights = await session.scalars(
            select(AnswerWeight).where(AnswerWeight.answer_id.in_(answer_ids))
        )
        for w in weights:
            if w.direction_id in scores:
                scores[w.direction_id] += w.points
    return scores


def top_direction_id(scores: dict[int, int]) -> int | None:
    if not scores:
        return None
    best = max(scores.values())
    if best <= 0:
        # никто не набрал баллов — берём первое направление по порядку id
        return min(scores.keys()) if scores else None
    for direction_id, value in scores.items():
        if value == best:
            return direction_id
    return None


async def resolve_top(
    session, scores: dict[int, int], ordered_answer_ids: list[int]
) -> int | None:
    """Определяет ведущее направление с учётом тай-брейка.

    При равенстве лидеров решающим считается ПОСЛЕДНИЙ отвеченный вопрос
    (в этом опросе — вопрос №6): берётся направление выбранного там варианта,
    если оно среди лидеров. Иначе — детерминированный запасной вариант.
    """
    if not scores:
        return None
    best = max(scores.values())
    tied = [did for did, value in scores.items() if value == best]
    if len(tied) == 1:
        return tied[0]

    if ordered_answer_ids:
        last_aid = ordered_answer_ids[-1]
        weights = await session.scalars(
            select(AnswerWeight).where(AnswerWeight.answer_id == last_aid)
        )
        last_dirs = {w.direction_id for w in weights}
        for did in tied:
            if did in last_dirs:
                return did

    return min(tied)
