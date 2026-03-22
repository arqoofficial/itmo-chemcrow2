<p align="center">
  <img src="frontend/public/assets/images/itmo%2Bchemcrow2.png" alt="ChemCrow2 × ITMO" width="480" />
</p>

<h1 align="center">ChemCrow2</h1>

<p align="center">
  Интеллектуальный AI-ассистент для химиков — хакатон <strong>ITMO 2026</strong>
</p>

<p align="center">
  <a href="./CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.10.0-blue" alt="Version" /></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python" />
  <img src="https://img.shields.io/badge/react-19-61dafb" alt="React" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
</p>

---

ChemCrow2 объединяет современные LLM с профессиональными инструментами хемоинформатики. Учёные и специалисты решают сложные химические задачи прямо в диалоге — от поиска молекул и прогнозирования свойств до полноценного ретросинтетического анализа.

## Возможности

| Категория | Что умеет |
|-----------|-----------|
| **Поиск и конвертация** | Молекулы по SMILES, IUPAC-именам, CAS-номерам; взаимопреобразование форматов |
| **Анализ свойств** | Молекулярная масса, функциональные группы, сходство Таниmoto (RDKit) |
| **ADMET** | ML-предсказание абсорбции, распределения, метаболизма, экскреции и токсичности |
| **Ретросинтез** | Многоступенчатый ретросинтетический анализ через AiZynthFinder + RetroCast |
| **Реакции** | Предсказание продуктов и условий реакций |
| **Безопасность** | Проверка на контролируемые и взрывчатые вещества, GHS-предупреждения |
| **Литература и патенты** | Поиск статей (Semantic Scholar), патентная база (molbloom) |
| **Реагенты** | Цены и наличие в ChemSpace (опционально) |
| **Протоколы** | Обзор и генерация лабораторных протоколов |
| **Редактор молекул** | Встроенный визуальный редактор структур Ketcher |

## Архитектура

```
Frontend (React 19)
    │  SSE / REST
    ▼
Backend (FastAPI)          ← PostgreSQL + Alembic
    │  Celery task queue
    ▼
Celery Worker
    │  HTTP stream
    ▼
AI Agent (LangGraph ReAct) ← Langfuse (LLM tracing)
    ├── RDKit / PubChem / ADMET / Semantic Scholar
    ├── Safety / Patent / ChemSpace
    └── Retrosynthesis Service (AiZynthFinder)
```

**Монорепо — микросервисная структура:**

```
itmo_fatsapi/
├── backend/           # FastAPI + SQLModel + Alembic + Celery
├── frontend/          # React 19 + Vite + TanStack Router + shadcn/ui
├── services/
│   ├── ai-agent/      # LangGraph ReAct агент с хим. инструментами
│   ├── retrosynthesis/ # AiZynthFinder API
│   └── langfuse/      # Self-hosted LLM tracing (Docker стек)
├── scripts/           # Утилиты: загрузка данных, генерация клиента
├── data/              # Модели AiZynthFinder, данные RetroCast
├── notebooks/         # Jupyter: RAG, ADMET-исследования
└── docs/              # Документация по внешним данным
```

## Стек технологий

| Слой | Технологии |
|------|-----------|
| **Backend** | FastAPI, SQLModel, Alembic, PostgreSQL 17, Redis 7, Celery |
| **AI / LLM** | LangChain, LangGraph (ReAct граф), OpenAI GPT-4 / Anthropic Claude |
| **Хемоинформатика** | RDKit, AiZynthFinder, RetroCast, molbloom, Ketcher |
| **Мониторинг** | Langfuse (self-hosted), Sentry |
| **Frontend** | React 19, TypeScript, TanStack Router, Tailwind CSS, shadcn/ui, Vite |
| **Инфраструктура** | Docker, Docker Compose, Traefik, nginx, uv (Python workspace), Bun |
| **Тесты** | pytest (backend), Playwright (e2e) |

## Быстрый старт

### Пререквизиты

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose
- API-ключ OpenAI или Anthropic

### 1. Клонирование и настройка окружения

```bash
git clone https://github.com/arqoofficial/itmo-chemcrow2.git
cd itmo-chemcrow2

# Создать .env из примера
cp .env.example .env
```

Минимально необходимые переменные в `.env`:

```env
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_urlsafe(32))">
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=changeme
POSTGRES_PASSWORD=changeme
OPENAI_API_KEY=sk-...        # или ANTHROPIC_API_KEY
```

### 2. Запуск

```bash
docker compose up --build -d
```

Docker поднимет все сервисы автоматически.

### 3. Открыть в браузере

| Сервис | URL |
|--------|-----|
| **Приложение** | http://localhost:5173 |
| **Swagger UI** | http://localhost:8000/docs |
| **Adminer (БД)** | http://localhost:8080 |
| **Langfuse (трассировка)** | http://localhost:3000 |
| **Mailcatcher** | http://localhost:1080 |

Войдите с `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` из `.env`.

> **Подробнее:** варианты запуска, production-деплой, частые проблемы — в **[SETUP.md](./SETUP.md)**.

## Langfuse — трассировка LLM

[Langfuse](https://langfuse.com/) — self-hosted наблюдаемость для агента: в UI видны трассы диалогов с вложенными вызовами модели и инструментов (LangGraph ReAct интегрирован через `CallbackHandler` из SDK).

**Интерфейс:** http://localhost:3000 (после `docker compose up`).

**Как включить отправку трассов в Langfuse:**

1. Зайдите в Langfuse → создайте проект → **API Keys** → сгенерируйте пару ключей.
2. Пропишите в `.env` (см. [`.env.example`](./.env.example)):

   ```env
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_HOST=http://langfuse-server:3000
   ```

   Для агента в Docker `LANGFUSE_HOST` должен указывать на сервис `langfuse-server` (как в примере). Локальный запуск без Docker — на ваш публичный URL Langfuse (например `http://localhost:3000`).

3. Перезапустите воркеры, подхватывающие конфиг: `docker compose restart worker ai-agent`.

Если `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` не заданы, агент работает как обычно, трассировка просто отключена.

Полный список переменных стека Langfuse (БД, ClickHouse, секреты NextAuth и т.д.) и production-замечания — в **[SETUP.md § Langfuse](./SETUP.md#langfuse--трассировка-llm-вызовов)**.

## Внешние данные (опционально)

Для работы ретросинтеза нужны большие наборы данных, которые не входят в репозиторий:

```bash
# AiZynthFinder: ONNX-модели и шаблоны USPTO (~1.5 GB)
uv run python scripts/download_public_data.py

# RetroCast / Project Procrustes (~554 MB)
bash scripts/get-data-project-procrustes.sh all
```

Данные сохраняются в `data/aizynthfinder/` и `data/retrocast/` соответственно.  
Подробнее: [docs/data-aizynthfinder.md](./docs/data-aizynthfinder.md), [docs/data-retrocast.md](./docs/data-retrocast.md).

## API

После запуска полная интерактивная документация доступна на http://localhost:8000/docs.

Основные группы эндпоинтов (`/api/v1/`):

| Группа | Эндпоинты |
|--------|-----------|
| **Auth** | `POST /login/access-token` |
| **Users** | CRUD пользователей, смена пароля |
| **Conversations** | Создание/управление диалогами, история сообщений |
| **Events (SSE)** | Стриминг токенов агента в реальном времени |
| **Retrosynthesis** | Запуск многоступенчатого ретросинтеза |
| **Tasks** | Фоновые задачи: статус, отмена |

## AI-инструменты агента

Агент работает на основе LangGraph (ReAct граф) и подключает инструменты в зависимости от наличия API-ключей:

<details>
<summary>Полный список инструментов</summary>

| Инструмент | Описание |
|-----------|---------|
| `query2smiles` | Название / запрос → SMILES (PubChem) |
| `query2cas` | Название → CAS-номер |
| `smiles2name` | SMILES → IUPAC-название |
| `smiles2weight` | Молекулярная масса (RDKit) |
| `mol_similarity` | Сходство Танимото между двумя молекулами |
| `func_groups` | Функциональные группы |
| `smiles_to_admet` | ADMET-предсказание |
| `control_chem_check` | Проверка контролируемых веществ |
| `similar_control_chem_check` | Структурные аналоги запрещённых веществ |
| `explosive_check` | Оценка взрывчатых свойств |
| `patent_check` | Патентная база (molbloom) |
| `literature_search` | Поиск статей (Semantic Scholar) |
| `web_search` | Веб-поиск через SerpAPI *(опциональный)* |
| `protocol_review` | Обзор лабораторного протокола |
| `reaction_predict` | Предсказание продуктов реакции |
| `reaction_retrosynthesis` | Ретросинтез через AiZynthFinder |
| `get_molecule_price` | Цена реагента в ChemSpace *(опциональный)* |

После каждого ответа автоматически запускается **Hazard Checker** — GHS-предупреждения о токсичных и опасных соединениях передаются через SSE-стрим.

</details>

## Переменные окружения

Полный список переменных — в [`.env.example`](./.env.example).

**Обязательные:**

| Переменная | Описание |
|-----------|---------|
| `SECRET_KEY` | JWT-ключ (`secrets.token_urlsafe(32)`) |
| `FIRST_SUPERUSER` | Email первого администратора |
| `FIRST_SUPERUSER_PASSWORD` | Пароль администратора |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL |
| `OPENAI_API_KEY` или `ANTHROPIC_API_KEY` | LLM-провайдер |

**Опциональные:**

| Переменная | Описание |
|-----------|---------|
| `ANTHROPIC_API_KEY` | Альтернативный LLM-провайдер |
| `SERP_API_KEY` | Веб-поиск (SerpAPI) |
| `CHEMSPACE_API_KEY` | Цены на реагенты |
| `SEMANTIC_SCHOLAR_API_KEY` | Поиск по литературе |
| `SENTRY_DSN` | Мониторинг ошибок |
| `LANGFUSE_SECRET_KEY` | Трассировка агента в Langfuse (см. раздел выше) |
| `LANGFUSE_PUBLIC_KEY` | Публичный ключ Langfuse |
| `LANGFUSE_HOST` | URL Langfuse (`http://langfuse-server:3000` в Docker Compose) |

## Разработка

```bash
# Генерация TypeScript-клиента из OpenAPI-схемы
bash scripts/generate-client.sh

# Тесты (Docker)
bash scripts/test.sh

# Тесты (локально)
bash scripts/test-local.sh
```

Для локальной разработки без Docker смотрите раздел **[Вариант B](./SETUP.md#вариант-b-локально-без-docker)** в SETUP.md.

## Changelog

История изменений — в [CHANGELOG.md](./CHANGELOG.md).

## Лицензия

[MIT](./LICENSE)
