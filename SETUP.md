# ChemCrow2 — Инструкция по запуску

## Содержание

- [Пререквизиты](#пререквизиты)
- [Настройка окружения](#настройка-окружения)
- [Вариант A: Локально с Docker](#вариант-a-локально-с-docker)
- [Вариант A1: Легковесный локальный запуск (compose.lite.yml)](#вариант-a1-легковесный-локальный-запуск-composeliteyml)
- [Сборка Docker без кэша](#сборка-образов-без-кэша)
- [Вариант B: Локально без Docker](#вариант-b-локально-без-docker)
- [Вариант C: Production (сервер)](#вариант-c-production-сервер)
- [Полезные ссылки после запуска](#полезные-ссылки-после-запуска)
- [Перезапуск конкретного сервиса](#перезапуск-конкретного-сервиса)
- [Langfuse — трассировка LLM-вызовов](#langfuse--трассировка-llm-вызовов)
- [Данные RetroCast и AiZynthFinder](#данные-retrocast-и-aizynthfinder)
- [Частые проблемы](#частые-проблемы)

---

## Пререквизиты

| Инструмент | Вариант A (Docker) | Вариант B (без Docker) | Вариант C (Production) |
|---|---|---|---|
| Git | да | да | да |
| Docker + Docker Compose | да | нет (опционально для БД) | да |
| Python 3.10+ | нет | да | нет |
| uv (Python package manager) | нет | да | нет |
| Bun (JS runtime) | нет | да | нет |
| PostgreSQL 17 | нет (в Docker) | да (локально или в Docker) | нет (в Docker) |

Установка инструментов:

```bash
# uv (менеджер пакетов Python)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Bun (JS runtime)
curl -fsSL https://bun.sh/install | bash
```

---

## Настройка окружения

Одинаково для всех вариантов:

```bash
git clone <URL_РЕПОЗИТОРИЯ>
cd itmo-chemcrow2

# Создать .env из примера
cp .env.example .env
```

Откройте `.env` и при необходимости поменяйте значения. Для локальной разработки всё работает из коробки — достаточно сменить пароли.

---

## Вариант A: Локально с Docker

Самый простой способ — всё поднимается одной командой.

### Запуск

```bash
docker compose up --build -d
```

Docker соберёт и запустит: PostgreSQL, backend (с hot reload), frontend (nginx), Adminer, Mailcatcher.

## Вариант A1: Легковесный локальный запуск (compose.lite.yml)

Если нужен более быстрый и менее ресурсоемкий старт, используйте облегченный стек:

```bash
docker compose -f compose.lite.yml up --build -d
```

В `compose.lite.yml` отключено:

- весь стек Langfuse (`langfuse-db`, `langfuse-zookeeper`, `langfuse-clickhouse`, `langfuse-minio`, `langfuse-cache`, `langfuse-server`, `langfuse-worker`);
- отправка Langfuse-трейсов из `ai-agent` (в lite-конфиге принудительно пустые `LANGFUSE_PUBLIC_KEY` и `LANGFUSE_SECRET_KEY`).

> В lite-режиме URL `http://localhost:3000` (Langfuse) недоступен по определению.

### Управление контейнерами

```bash
# Остановить (данные БД сохраняются)
docker compose stop

# Запустить снова
docker compose start

# Пересобрать после изменений кода (без предварительного stop/down)
docker compose up --build -d
```

> **Не используйте `docker compose down` в повседневной разработке.**
> `down` удаляет контейнеры и сети. При следующем `up` PostgreSQL может не принять пароль,
> потому что volume с данными БД остаётся, а пароль применяется только при первой инициализации.
>
> Для обычной работы достаточно `docker compose stop` / `start` или просто
> `docker compose up --build -d` — Docker Compose сам пересоздаст только изменившиеся контейнеры.

### Сборка образов без кэша

Обычно **не нужно**: `docker compose up --build -d` переиспользует слои и собирает быстрее.

**Имеет смысл собрать без кэша** (`--no-cache`), если:

- меняли **Dockerfile** или шаги установки зависимостей, а в контейнере всё ещё старые пакеты;
- обновили **базовый образ** (`FROM ...`) и хотите гарантированно перетянуть свежие слои;
- после `git pull` сборка «ломается странно» — часто помогает чистая пересборка;
- отлаживаете CI/образ и нужно исключить влияние локального build cache.

**Все сервисы с пересборкой без кэша:**

```bash
docker compose build --no-cache
docker compose up -d
```

**Один сервис** (остальные не трогаются):

```bash
docker compose build --no-cache backend
docker compose up -d backend
```

То же для frontend или любого другого сервиса из `compose.yml`, у которого есть `build:`.

### Перезапуск конкретного сервиса

Если нужно пересобрать и перезапустить только один сервис (например, frontend), не трогая остальные:

```bash
# Пересобрать и перезапустить только frontend
docker compose up --build -d frontend
```

Docker Compose пересоберёт образ и пересоздаст контейнер только для указанного сервиса. Остальные контейнеры продолжат работать без перерыва.

Другие примеры:

```bash
# Только backend
docker compose up --build -d backend

# Только базу данных (пересборка не нужна — образ из Docker Hub)
docker compose up -d db

# Несколько сервисов сразу
docker compose up --build -d frontend backend
```

Просмотр логов конкретного сервиса:

```bash
docker compose logs -f frontend
```

Перезапуск без пересборки (если код не менялся, а нужно просто рестартнуть контейнер):

```bash
docker compose restart frontend
```

### Полный сброс окружения

Если всё-таки нужен полный сброс окружения (включая данные БД):

```bash
docker compose down -v
docker compose up --build -d
```

### Доступные сервисы

| Сервис | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Adminer (БД) | http://localhost:8080 |
| Langfuse (LLM tracing) | http://localhost:3000 |
| Mailcatcher | http://localhost:1080 |

### Hot reload

Backend автоматически перезапускается при изменении кода в `backend/`. Если меняете зависимости (`pyproject.toml`), контейнер пересоберётся.

---

## Вариант B: Локально без Docker

Подходит, если хочется быстрее итерироваться и не ждать пересборки контейнеров.

### 1. База данных

**Вариант 1 — PostgreSQL в Docker (рекомендуется):**

```bash
docker run -d \
  --name chemcrow-db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=change_me \
  -e POSTGRES_DB=app \
  -p 5432:5432 \
  postgres:17
```

**Вариант 2 — PostgreSQL установлен локально:**

Убедитесь, что PostgreSQL запущен и создана база `app`:

```bash
createdb -U postgres app
```

### 2. Backend

```bash
cd backend

# Установить зависимости
uv sync

# Применить миграции и создать суперпользователя
uv run python app/backend_pre_start.py
uv run alembic upgrade head
uv run python app/initial_data.py

# Запустить сервер с hot reload
uv run fastapi dev app/main.py
```

Backend доступен на http://localhost:8000.

### 3. Frontend

В новом терминале:

```bash
cd frontend

# Установить зависимости
bun install

# Запустить dev server
bun dev
```

Frontend доступен на http://localhost:5173. Vite проксирует API-запросы на backend (настроено в `frontend/.env`).

### Доступные сервисы

| Сервис | URL |
|---|---|
| Frontend (Vite dev) | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |

---

## Вариант C: Production (сервер)

Для деплоя на VPS/облачный сервер с доступом по IP.

### 1. Подготовка сервера

Установите Docker и Docker Compose на сервер:

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# Перелогиньтесь, чтобы применить группу
```

### 2. Клонирование и настройка

```bash
git clone <URL_РЕПОЗИТОРИЯ>
cd itmo_fatsapi
cp .env.example .env
```

Отредактируйте `.env` для production:

```env
DOMAIN=<IP_СЕРВЕРА>
FRONTEND_HOST=http://<IP_СЕРВЕРА>
ENVIRONMENT=production
BACKEND_CORS_ORIGINS="http://<IP_СЕРВЕРА>"
SECRET_KEY=<сгенерируй_надёжный_ключ>
FIRST_SUPERUSER_PASSWORD=<надёжный_пароль>
POSTGRES_PASSWORD=<надёжный_пароль>
```

Сгенерировать SECRET_KEY:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Запуск

```bash
docker compose -f compose.production.yml up -d --build
```

Или через готовый скрипт:

```bash
bash scripts/up-server-ip.sh
```

**Легковесный production** (`compose.production.lite.yml`) — тот же стек, что и `compose.production.yml`, но без Langfuse и без отправки трейсов из `ai-agent` (пустые `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`). Удобно для VPS с ограниченными ресурсами:

```bash
docker compose -f compose.production.lite.yml up -d --build
```

Скрипт `scripts/up-server-ip.sh` по умолчанию использует полный `compose.production.yml`; для lite-версии вызывайте `docker compose` с `-f compose.production.lite.yml` вручную.

### 4. Просмотр логов

```bash
docker compose -f compose.production.yml logs -f
```

### 5. Обновление

```bash
git pull
docker compose -f compose.production.yml up -d --build
```

Если после обновления на сервере образы ведут себя некорректно (зависимости, Dockerfile), пересоберите **без кэша** и поднимите стек:

```bash
docker compose -f compose.production.yml build --no-cache
docker compose -f compose.production.yml up -d
```

Смысл тот же, что в [сборке без кэша для локального Docker](#сборка-образов-без-кэша): принудительно выполнить все шаги Dockerfile заново, не опираясь на старые слои.

### Доступные сервисы

| Сервис | URL |
|---|---|
| Frontend + API | http://<IP_СЕРВЕРА> |
| Swagger UI | http://<IP_СЕРВЕРА>/docs |
| Adminer (БД) | http://<IP_СЕРВЕРА>:8080 |

---

## Langfuse — трассировка LLM-вызовов

[Langfuse](https://langfuse.com/) поднимается автоматически вместе с остальными сервисами в `compose.yml`. После запуска откройте http://localhost:3000 и создайте аккаунт.

### Первоначальная настройка

1. Откройте http://localhost:3000 → зарегистрируйтесь (первый пользователь становится администратором).
2. Создайте организацию и проект.
3. В настройках проекта перейдите в **API Keys** → сгенерируйте пару ключей.
4. Скопируйте ключи в `.env`:

```env
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=http://langfuse-server:3000
```

5. Перезапустите сервисы, чтобы применить ключи:

```bash
docker compose restart worker ai-agent
```

### Переменные Langfuse

В `.env` предусмотрены dev-дефолты для обязательных переменных. Для production замените их на криптостойкие значения:

```bash
# Сгенерировать NEXTAUTH_SECRET, SALT, ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Переменная | Описание |
|-----------|---------|
| `NEXTAUTH_SECRET` | Секрет NextAuth (≥32 символов) |
| `SALT` | Соль хэширования (≥32 символов) |
| `ENCRYPTION_KEY` | Ключ шифрования (≥32 символов) |
| `LANGFUSE_SECRET_KEY` | Серверный ключ (из UI после регистрации) |
| `LANGFUSE_PUBLIC_KEY` | Публичный ключ (из UI после регистрации) |
| `LANGFUSE_HOST` | URL Langfuse (`http://langfuse-server:3000` внутри Docker) |

> Если трассировка не нужна, Langfuse можно не настраивать — агент будет работать без неё.

---

## Данные RetroCast и AiZynthFinder

Большие наборы для бенчмарков/ретросинтеза (не в git) скачиваются отдельно.

**RetroCast (Project Procrustes)** — **[docs/data-retrocast.md](./docs/data-retrocast.md)**. Кратко:

```bash
bash scripts/get-data-project-procrustes.sh all
```

**AiZynthFinder (USPTO: модели, шаблоны, ZINC stock)** — **[docs/data-aizynthfinder.md](./docs/data-aizynthfinder.md)**. Кратко:

```bash
uv run python scripts/download_public_data.py
```

Файлы по умолчанию: `data/retrocast` и `data/aizynthfinder` соответственно.

---

## Полезные ссылки после запуска

- **Swagger UI** — интерактивная документация API: `/docs`
- **ReDoc** — альтернативная документация: `/redoc`
- **Adminer** — веб-интерфейс для БД (логин: `postgres`, пароль из `.env`)

Суперпользователь для входа в приложение — email и пароль из `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` в `.env`.

---

## Частые проблемы

### Docker: `port is already allocated`

Остановите процесс, занимающий порт, или поменяйте порт в `compose.yml`:

```bash
# Найти, кто занял порт 5432
lsof -i :5432
```

### Backend не подключается к БД

- С Docker: `POSTGRES_SERVER` переопределяется на `db` автоматически в compose.
- Без Docker: убедитесь, что в `.env` стоит `POSTGRES_SERVER=localhost` и PostgreSQL запущен.

### Frontend не видит backend (CORS ошибки)

Проверьте, что `BACKEND_CORS_ORIGINS` в `.env` включает URL, с которого открыт фронтенд.

### Миграции не применились

```bash
# Docker
docker compose exec backend alembic upgrade head

# Без Docker
cd backend && uv run alembic upgrade head
```
