import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"

load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# пароль для полной очистки опроса (кнопка «Удалить весь опрос» в админке)
WIPE_PASSWORD = os.getenv("WIPE_PASSWORD", "").strip()

try:
    SUPERADMIN_ID = int(os.getenv("SUPERADMIN_ID", "0"))
except ValueError:
    SUPERADMIN_ID = 0

DB_PATH = os.getenv("DB_PATH", "survey.db").strip()
if not os.path.isabs(DB_PATH):
    DB_PATH = str(BASE_DIR / DB_PATH)

DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"


def validate() -> None:
    problems = []
    if not BOT_TOKEN or "PUT_YOUR_TOKEN_HERE" in BOT_TOKEN:
        problems.append("BOT_TOKEN не задан — впишите токен от @BotFather в файл .env")
    if SUPERADMIN_ID <= 0:
        problems.append("SUPERADMIN_ID не задан — впишите свой Telegram ID в файл .env")
    if problems:
        raise SystemExit("Ошибка конфигурации:\n  - " + "\n  - ".join(problems))
