# Запуск на VPS (Ubuntu / Debian)

Инструкция для развёртывания бота на «чистом» Linux-сервере с автозапуском
через systemd. Команды даны для Ubuntu 22.04+ / Debian 12 (под root или через
`sudo`).

## 1. Установить системные пакеты

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version   # нужен Python 3.11+
```

> Если в системе Python старше 3.11 — поставьте новее (например, через
> `deadsnakes` PPA: `sudo add-apt-repository ppa:deadsnakes/ppa` →
> `sudo apt install python3.11 python3.11-venv`) и далее используйте
> `python3.11` вместо `python3`.

## 2. Скачать код

```bash
cd /opt
sudo git clone https://github.com/AlazarStudio/TelegramBotSurvey.git
sudo chown -R $USER:$USER TelegramBotSurvey
cd TelegramBotSurvey
```

## 3. Виртуальное окружение и зависимости

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 4. Настроить `.env`

```bash
cp .env.example .env
nano .env
```

Заполните значения (без кавычек):

```
BOT_TOKEN=токен_от_@BotFather
SUPERADMIN_ID=ваш_Telegram_ID         # узнать у @userinfobot
DB_PATH=survey.db                     # БД ляжет в корень проекта
WIPE_PASSWORD=надёжный_пароль_для_удаления_опроса
```

> `.env` и `survey.db` в репозиторий **не попадают** (см. `.gitignore`) —
> токен и пароль остаются только на сервере.

## 5. Проверить запуск вручную

```bash
.venv/bin/python -m bot.main
```

В логе должно появиться `Бот запущен: @<имя_бота>` и `Start polling`.
При первом запуске создаётся БД и заливается опрос. Остановить — `Ctrl+C`.

## 6. Автозапуск через systemd

Создайте сервис:

```bash
sudo nano /etc/systemd/system/survey-bot.service
```

Содержимое (поправьте `User` и пути, если каталог другой):

```ini
[Unit]
Description=Telegram Survey Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_LINUX_USER
WorkingDirectory=/opt/TelegramBotSurvey
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/TelegramBotSurvey/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Включить и запустить:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now survey-bot
sudo systemctl status survey-bot      # должно быть active (running)
```

## 7. Логи и управление

```bash
journalctl -u survey-bot -f           # смотреть логи в реальном времени
sudo systemctl restart survey-bot     # перезапуск
sudo systemctl stop survey-bot        # остановить
```

## 8. Обновление кода

```bash
cd /opt/TelegramBotSurvey
git pull
.venv/bin/pip install -r requirements.txt   # если менялись зависимости
sudo systemctl restart survey-bot
```

## 9. Резервная копия и сброс

- **Бэкап результатов:** скопируйте файл `survey.db`
  (`cp survey.db survey.db.bak`).
- **Полный сброс результатов** делается из бота кнопкой
  «🗑 Удалить весь опрос» (нужен `WIPE_PASSWORD`). Вопросы и направления
  при этом сохраняются.

## Частые проблемы

- **`TelegramNetworkError: Cannot connect to api.telegram.org`** — нет
  доступа в интернет или Telegram заблокирован у провайдера VPS. Проверьте
  `curl https://api.telegram.org`. На серверах в РФ может понадобиться VPS
  с зарубежным IP.
- **`BOT_TOKEN не задан` / `SUPERADMIN_ID не задан`** — не заполнен `.env`.
- **Конфликт `terminated by other getUpdates`** — бот запущен в двух местах
  одновременно (например, и локально, и на VPS). Оставьте только один.
