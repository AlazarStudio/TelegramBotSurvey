"""Локальная проверка без запуска бота: импорт модулей, init БД, seed,
подсчёт баллов и генерация картинки. Использует временную БД."""

import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ.setdefault("SUPERADMIN_ID", "111")
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name


async def run() -> None:
    from sqlalchemy import select

    from bot.database import get_session, init_db
    from bot.image import build_breakdown, generate_result_image
    from bot.models import Answer, Direction, Question
    from bot.scoring import compute_scores, resolve_top
    from bot.seed import seed_if_empty

    await init_db()
    await seed_if_empty()

    async with get_session() as session:
        dirs = list(await session.scalars(select(Direction)))
        questions = list(
            await session.scalars(select(Question).order_by(Question.position))
        )
        answers = list(await session.scalars(select(Answer).order_by(Answer.id)))
        print(f"directions={len(dirs)} questions={len(questions)} answers={len(answers)}")

        # по варианту на каждый вопрос (имитируем разброс выбора)
        by_q: dict[int, list] = {}
        for a in answers:
            by_q.setdefault(a.question_id, []).append(a)
        for q in by_q:
            by_q[q].sort(key=lambda a: a.position)
        picks = [0, 1, 0, 2, 0, 3]
        picked = [
            by_q[q.id][picks[i] % len(by_q[q.id])].id
            for i, q in enumerate(questions)
        ]
        scores = await compute_scores(session, picked)
        top = await resolve_top(session, scores, picked)
        name_by_id = {d.id: d.name for d in dirs}
        emoji_by_name = {d.name: d.emoji for d in dirs}
        scores_by_name = {name_by_id[k]: v for k, v in scores.items()}
        print("scores:", scores_by_name, "top:", name_by_id.get(top))

        breakdown = build_breakdown(scores_by_name, emoji_by_name, name_by_id.get(top))
        img = generate_result_image(
            name_by_id.get(top, "—"),
            emoji_by_name.get(name_by_id.get(top), ""),
            "Тестовое описание направления для проверки переноса строк в картинке.",
            breakdown,
        )
        out = "test_result.png"
        with open(out, "wb") as f:
            f.write(img.read())
        print(f"image written: {out} ({os.path.getsize(out)} bytes)")

    print("SMOKE_OK")


if __name__ == "__main__":
    asyncio.run(run())
