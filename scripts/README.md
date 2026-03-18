---

### `scripts/setup-dotenv-example.sh` — Создание `.env` файлов из `.env.example`

Рекурсивно ищет все файлы `.env.example` в проекте и создаёт из них `.env` (убирая суффикс `.example`). Если `.env` уже существует — пропускает, чтобы не затереть локальные настройки.

**Найденные `.env.example`:**
- `.env.example` → `.env` (корень проекта — настройки бэкенда, БД, SMTP и т.д.)
- `frontend/.env.example` → `frontend/.env` (настройки фронтенда)

**Запуск:**

```bash
bash scripts/setup-dotenv-example.sh
```

**Итого:** быстрая инициализация окружения после клонирования репозитория — одной командой создаёт все нужные `.env` файлы.

---

### `scripts/generate-client.sh` — Генерация фронтенд-клиента из OpenAPI

1. Заходит в `backend/` и запускает Python-приложение, чтобы извлечь OpenAPI-схему (`app.main.app.openapi()`) и сохранить её в `openapi.json`.
2. Перемещает `openapi.json` в папку `frontend/`.
3. Запускает `bun run --filter frontend generate-client` — генерирует TypeScript-клиент для фронтенда на основе OpenAPI-схемы.
4. Запускает `bun run lint` — линтинг сгенерированного кода.

**Итого:** автоматически синхронизирует типы и API-методы фронтенда с бэкендом.

---

### `scripts/test-local.sh` — Запуск тестов локально через Docker Compose (legacy-формат)

1. Останавливает и удаляет предыдущие контейнеры (`docker-compose down -v --remove-orphans`).
2. На Linux — чистит `__pycache__`.
3. Собирает образы (`docker-compose build`).
4. Поднимает стек (`docker-compose up -d`).
5. Выполняет тесты внутри контейнера `backend` через `scripts/tests-start.sh`.

**Итого:** полный цикл «поднять окружение → прогнать тесты» с docker-compose (использует старый формат `docker-compose`).

---

### `scripts/test.sh` — Запуск тестов через Docker Compose (новый формат)

1. Собирает образы (`docker compose build`).
2. Останавливает старые контейнеры (`docker compose down -v --remove-orphans`).
3. Поднимает стек (`docker compose up -d`).
4. Выполняет тесты внутри контейнера `backend` через `scripts/tests-start.sh`.
5. После тестов — останавливает и чистит контейнеры.

**Итого:** то же, что `test-local.sh`, но использует новый формат `docker compose` (без дефиса) и корректно чистит за собой после выполнения тестов.

---

Также есть `backend/scripts/test.sh` — это внутренний скрипт, который вызывается **внутри контейнера** и запускает `pytest` с `coverage` (покрытие кода тестами).