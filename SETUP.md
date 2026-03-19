# ChemCrow2 — Инструкция по запуску

## Содержание

- [Пререквизиты](#пререквизиты)
- [Настройка окружения](#настройка-окружения)
- [Вариант A: Локально с Docker](#вариант-a-локально-с-docker)
- [Вариант B: Локально без Docker](#вариант-b-локально-без-docker)
- [Вариант C: Production (сервер)](#вариант-c-production-сервер)
- [Полезные ссылки после запуска](#полезные-ссылки-после-запуска)
- [Перезапуск конкретного сервиса](#перезапуск-конкретного-сервиса)
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
cd itmo_fatsapi

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

### 4. Просмотр логов

```bash
docker compose -f compose.production.yml logs -f
```

### 5. Обновление

```bash
git pull
docker compose -f compose.production.yml up -d --build
```

### Доступные сервисы

| Сервис | URL |
|---|---|
| Frontend + API | http://<IP_СЕРВЕРА> |
| Swagger UI | http://<IP_СЕРВЕРА>/docs |
| Adminer (БД) | http://<IP_СЕРВЕРА>:8080 |

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
