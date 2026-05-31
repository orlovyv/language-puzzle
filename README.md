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

**Оплата через ЮKassa.** Эндпоинты `/api/billing/checkout`, `/api/billing/webhook`,
`/api/billing/status`, `/api/billing/cancel`. Подписка активируется **только** по
верифицированному вебхуку `payment.succeeded` (повторная выборка платежа из ЮKassa,
идемпотентность по `payment.id`), а не по клиентскому редиректу. Ключи: `YOOKASSA_SHOP_ID`,
`YOOKASSA_SECRET_KEY`, цена/период — `SUBSCRIPTION_PRICE_RUB` / `SUBSCRIPTION_PERIOD_DAYS`.

Все ключи и флаги — в `.env` (см. `.env.example`).
