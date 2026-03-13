# Content Gap Analyzer MVP

MVP веб-сервис на FastAPI для анализа контентного разрыва между:
- ожидаемым ответом по поисковому запросу (`query`)
- фактическим содержимым страницы (`url`)

Сервис принимает запрос, строит AI overview, извлекает сущности и факты, анализирует gaps и возвращает рекомендации по улучшению страницы.

## Что делает сервис

Pipeline `POST /analyze`:
1. Получает `AI Overview` по `query` (через OpenAI LLM).
2. Парсит основной текст страницы по `url`.
3. Извлекает `entities/facts/concepts`.
4. Сравнивает `AI overview` и `page content`, определяет gaps: `missing`, `weak`, `covered`.
5. Генерирует 5-10 рекомендаций, привязанных к gaps.
6. Сохраняет run в SQLite (`analysis_runs`).

Если AI overview недоступен (например, нет `OPENAI_API_KEY` или ошибка модели), run сохраняется со статусом `no_ai_overview`.

## Стек

- Python 3.11
- FastAPI
- SQLAlchemy
- SQLite
- Pydantic
- httpx
- trafilatura + BeautifulSoup4
- OpenAI API (через HTTP API)

## Архитектура проекта

```text
app/
  main.py
  api/
    routes.py
  services/
    ai_overview.py
    page_parser.py
    analyzer.py
  db/
    database.py
    models.py
    schemas.py
  core/
    config.py
tests/
  test_gap_detection.py
  test_api.py
README.md
requirements.txt
Dockerfile
.env.example
```

## API

### `POST /analyze`

Request:

```json
{
  "query": "best productivity tools",
  "url": "https://example.com/article"
}
```

Response:

```json
{
  "run_id": 1,
  "query": "best productivity tools",
  "url": "https://example.com/article",
  "status": "completed",
  "ai_overview_text": "...",
  "entities": [
    {"text": "automation", "type": "concept"}
  ],
  "gaps": [
    {
      "item": "pricing tiers",
      "status": "missing",
      "evidence_from_ai_overview": "...",
      "evidence_from_page": "..."
    }
  ],
  "recommendations": [
    "Add a dedicated pricing section because AI overview includes it while page content does not."
  ],
  "timestamp": "2026-03-12T10:00:00.000000"
}
```

### `GET /health`

Response:

```json
{"status":"ok"}
```

### `GET /runs`

Возвращает список запусков (по убыванию времени).

### `GET /runs/{id}`

Возвращает детальный результат конкретного запуска.

## База данных

Таблица `analysis_runs` содержит:
- `query`
- `url`
- `timestamp`
- `status`
- `ai_overview_text`
- `entities` (JSON string)
- `gaps` (JSON string)
- `recommendations` (JSON string)
- `error_message`

## Устойчивость

Реализовано:
- таймауты HTTP запросов
- ретраи (экспоненциальный backoff)
- обработка ошибок на каждом этапе pipeline
- fallback-эвристики для извлечения и gap detection, если LLM недоступен

## AI Overview

Прямое получение AI Overview из Google не используется. Вместо этого сервис формирует AI overview через OpenAI модель по поисковому запросу.

## Ограничения MVP

- Качество анализа зависит от полноты распарсенного текста страницы.
- JSON поля в SQLite хранятся как `TEXT`.
- При отсутствии `OPENAI_API_KEY` сервис продолжит работу, но run может иметь статус `no_ai_overview`.
- Эвристический fallback проще LLM-анализа и дает менее точные результаты.

## Локальный запуск

1. Установка зависимостей:

```bash
pip install -r requirements.txt
```

2. Переменные окружения:

```bash
cp .env.example .env
```

3. Запуск:

```bash
uvicorn app.main:app --reload
```

Документация будет на `http://127.0.0.1:8000/docs`.

## Тесты

```bash
pytest -q
```

## Docker

Сборка:

```bash
docker build -t content-gap-analyzer .
```

Запуск:

```bash
docker run --rm -p 8000:8000 --env-file .env content-gap-analyzer
```

## Deploy (Railway / Render / Fly.io)

Проект готов к деплою как containerized FastAPI сервис:
- `Dockerfile` поддерживает переменную `PORT`
- Обязательная переменная окружения: `OPENAI_API_KEY`
- Хранилище: локальный SQLite файл (`app.db`) внутри контейнера (для production рекомендуется внешний DB)

### Вариант 1: Render (самый быстрый путь)

В репозитории есть `render.yaml`, поэтому деплой делается почти без ручной настройки.

1. Запушить проект в GitHub.
2. В Render: `New +` -> `Blueprint`.
3. Выбрать репозиторий.
4. В Environment variables указать:
   - `OPENAI_API_KEY=...`
5. Запустить deploy.
6. После деплоя проверить:
   - `GET https://<your-service>.onrender.com/health`
   - `POST https://<your-service>.onrender.com/analyze`

### Вариант 2: Railway

В репозитории есть `railway.json` + `Dockerfile`.

1. Создать новый проект Railway из GitHub-репозитория.
2. Railway сам соберет контейнер через Dockerfile.
3. Добавить переменную:
   - `OPENAI_API_KEY=...`
4. Дождаться статуса `Deployed`.
5. Проверить:
   - `GET https://<your-app>.up.railway.app/health`
   - `POST https://<your-app>.up.railway.app/analyze`

### Smoke test публичного URL

```bash
curl -X POST "https://<your-domain>/analyze" \
  -H "Content-Type: application/json" \
  -d '{"query":"best productivity tools","url":"https://zapier.com/blog/best-productivity-apps/"}'
```
