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

Если пользователя из `DATABASE_URL` можно подключить к базе `postgres`, приложение попробует создать `language_puzzle` само. Таблицы приложение создаст при старте.

Демо-аккаунт:

- email: `demo@local`
- password: `demo`

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
