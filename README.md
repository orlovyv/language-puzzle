# Language Puzzle MVP

Рабочий локальный прототип сервиса анализа английского текста по ТЗ.

Backend переписан на Python + FastAPI + spaCy + PostgreSQL.

## Запуск

```powershell
C:\Users\Yuri\AppData\Local\Programs\Python\Python311\python.exe -m uvicorn app:app --host 0.0.0.0 --port 3000
```

Откройте `http://localhost:3000`.

Также можно запустить файл:

```powershell
.\start server.bat
```

## PostgreSQL

Создайте файл `.env` по образцу `.env.example`:

```env
DATABASE_URL=postgresql://postgres:ВАШ_ПАРОЛЬ@localhost:5432/language_puzzle
HOST=0.0.0.0
PORT=3000
APP_SECRET=change-me-local-secret
```

Если пользователя из `DATABASE_URL` можно подключить к базе `postgres`, приложение попробует создать `language_puzzle` само. Схема накатывается миграциями из `migrations/*.sql` при старте (см. ниже).

Демо-аккаунт (можно переопределить через `DEMO_EMAIL` / `DEMO_PASSWORD` в `.env`):

- email: `demo@local.ru`
- password: `123`

## Что реализовано

- регистрация, вход, сессия;
- страницы `/dashboard`, `/upload`, `/document/:id`, `/document/:id/analysis`, `/learn`, `/words`, `/settings`;
- загрузка текста и `.srt`;
- очистка субтитров, токенизация, лемматизация на правилах, определение простых POS;
- определение частых фразовых глаголов;
- определение MVP-грамматики: Past Simple, Present Perfect, will, be going to, used to, modals, continuous, questions, negatives;
- расчет unique coverage и frequency coverage;
- отметка статусов слов;
- приоритетный список слов для изучения;
- карточки повторения;
- подсветка текста по статусам слов.

## Python-зависимости

Пакеты:

```powershell
C:\Users\Yuri\AppData\Local\Programs\Python\Python311\python.exe -m pip install -r requirements.txt
```

В текущем окружении уже проверены:

- FastAPI
- uvicorn
- spaCy
- `en_core_web_lg`
- `psycopg[binary]`

## Офлайн-переводы

Используется MUSE bilingual dictionary `data/dictionaries/muse-en-ru.txt`.
При первом старте приложение загружает его в PostgreSQL-таблицу `muse_translations`, затем новые слова получают русский перевод из этой таблицы.

## Архитектура

Код разбит на слои (зависимости направлены сверху вниз):

```
app/
├── core/            инфраструктура: пул соединений (database.py), запуск миграций (migrations.py)
├── repositories/    доступ к БД — весь SQL живёт здесь, по одному модулю на агрегат
├── services/        бизнес-логика:
│   ├── text_processing.py   единственный экземпляр spaCy + очистка/токенизация текста
│   ├── translation.py       цепочка переводов MUSE → Google → WordNet + IPA-транскрипция
│   ├── vocabulary.py        системные термины, словарь фраз, детектор фраз
│   ├── analysis.py          разбор документа, покрытие, пересчёт при смене статусов
│   ├── knowledge_graph.py   Knowledge Graph mode (semantic + frequency)
│   ├── learn.py             Learn-блоки и экспорт в Anki
│   ├── auth_service.py      сессии, верификация e-mail, register/login
│   ├── documents.py         валидация загрузки, сборка текста для чтения
│   └── scoring.py           чистые эвристики ранжирования
├── routes/          тонкие контроллеры FastAPI (по ресурсам)
├── models/          pydantic-модели публичных структур
├── schemas/         pydantic-схемы тел запросов
└── startup.py       bootstrap: создать БД, миграции, сид демо-аккаунта, импорт словарей
```

Соединения берутся из пула `psycopg_pool` (см. `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE`).

### Миграции

SQL-файлы в `migrations/` применяются по порядку имени один раз и фиксируются в таблице
`schema_migrations`. Файлы идемпотентны (`IF NOT EXISTS` / `ON CONFLICT`), поэтому безопасны
для уже существующих баз.

## Тесты

```powershell
C:\Users\Yuri\AppData\Local\Programs\Python\Python311\python.exe -m pytest
```

Юнит-тесты в `tests/` покрывают чистую логику (scoring, очистка текста, Learn-блоки,
модели, AI-обогащение и подписку) и не требуют PostgreSQL.

## Premium-подписка и ИИ

Платная подписка (Premium) включает улучшение качества через ИИ. Без ключей всё
работает в бесплатном режиме (MUSE/Google/частотный Knowledge Graph) — ИИ и оплата
деградируют молча.

**ИИ через OpenRouter** (единый OpenAI-совместимый API). Premium-функции:

- контекстные переводы слов/фраз (с учётом части речи и предложения);
- сгенерированные примеры предложений с переводом;
- AI-подбор тематической лексики в Knowledge Graph;
- обогащённые Anki-карточки (мнемоники, синонимы, контекст).

Все ответы ИИ кэшируются в таблице `ai_cache` (не платим за повторы), действуют
дневные лимиты (`AI_DAILY_LIMIT_*`). Включается флагом `USE_AI_FEATURES=1` и ключом
`OPENROUTER_API_KEY`.

**Оплата.** Провайдер выбирается флагом `PAYMENT_PROVIDER` (`robokassa` по умолчанию,
либо `yookassa`). Эндпоинты `/api/billing/checkout`, `/api/billing/status`,
`/api/billing/cancel`. Подписка активируется **только** по верифицированному
серверному колбэку, а не по клиентскому редиректу. Оба пути идемпотентны.

- **Robokassa** (активна по умолчанию): чекаут отдаёт подписанный redirect-URL
  (`md5(login:OutSum:InvId:Password1)`); Result URL `/api/billing/robokassa-result`
  проверяет подпись `md5(OutSum:InvId:Password2)` и отвечает `OK{InvId}`. Ключи:
  `ROBOKASSA_MERCHANT_LOGIN`, `ROBOKASSA_PASSWORD1`, `ROBOKASSA_PASSWORD2`,
  `ROBOKASSA_IS_TEST`.
- **ЮKassa** (оставлена, но неактивна): эндпоинт `/api/billing/webhook` обрабатывается
  только при `PAYMENT_PROVIDER=yookassa`; подписка активируется по вебхуку
  `payment.succeeded` с повторной выборкой платежа. Ключи: `YOOKASSA_SHOP_ID`,
  `YOOKASSA_SECRET_KEY`.

Цена/период — `SUBSCRIPTION_PRICE_RUB` / `SUBSCRIPTION_PERIOD_DAYS`. Без ключей
активного провайдера чекаут отвечает 503.

Все ключи и флаги — в `.env` (см. `.env.example`).

## Регистрация и пароли

- **Капча «я не робот»** при регистрации — Cloudflare Turnstile. Включается
  `USE_TURNSTILE=1` + ключи `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`. Cloudflare
  даёт тестовые ключи, работающие без домена. Без ключей проверка пропускается.
- **Подтверждение email 6-значным кодом** (`EMAIL_VERIFICATION_ENABLED=1`): пользователь
  создаётся **только** после ввода верного кода (TTL 15 мин, 5 попыток).
- **Восстановление пароля** (`/reset`): на почту отправляется временный пароль; после
  входа им выставляется флаг `must_change_password`, и пользователю предлагается
  сменить пароль в настройках. Эндпоинт всегда отвечает 200 (не раскрывает наличие аккаунта).
- **Смена пароля** в настройках (`/api/password/change`): проверяет текущий пароль,
  затем инвалидирует остальные сессии.

Почта настраивается через `SMTP_*` в `.env`. Если `SMTP_HOST` пуст, коды и временные
пароли печатаются в консоль (удобно для локальной разработки без почтового сервера).
