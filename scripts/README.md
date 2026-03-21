---

### `scripts/download_public_data.py` — Модели и stock AiZynthFinder (USPTO)

Скачивает с Zenodo / figshare ONNX-модели политик (expansion, filter, ringbreaker), шаблоны реакций в `.csv.gz` и сток `zinc_stock.hdf5`, затем генерирует **`config.yml`** с абсолютными путями — минимальный конфиг для AiZynthFinder.

**По умолчанию** файлы пишутся в **`data/aizynthfinder`** (относительно текущей директории).

```bash
# из корня репозитория
uv run python scripts/download_public_data.py

# другой каталог
uv run python scripts/download_public_data.py /path/to/dir
```

Зависимости: `requests`, `tqdm`. Подробнее: [docs/data-aizynthfinder.md](../docs/data-aizynthfinder.md).

---

### `scripts/get-data-project-procrustes.sh` — Синхронизация данных RetroCast с CDN

Скачивает файлы по манифесту `SHA256SUMS` с `files.ischemist.com`, проверяет SHA-256, умеет докачивать только недостающее или повреждённое.

**Примеры:**

```bash
# всё (~554 MiB), в data/retrocast
bash scripts/get-data-project-procrustes.sh all

# без скачивания — только список
bash scripts/get-data-project-procrustes.sh all --dry-run

# другой каталог
bash scripts/get-data-project-procrustes.sh benchmarks --dir=/tmp/retrocast
```

Цели: `all`, `benchmarks`, `definitions`, `stocks`, `raw`, `processed`, `scored`, `results`, а также `mkt-lin-500`, `mkt-cnv-160`, `ref-lin-600`, `ref-cnv-400`, `ref-lng-84`. Каталог по умолчанию переопределяется переменной `RETROCAST_DATA_DIR`.

Полная документация: [docs/data-retrocast.md](../docs/data-retrocast.md).

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