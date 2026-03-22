# Changelog

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/). Версии соответствуют git-тегам `v*`.

## [Unreleased]

### Исправлено

- Лицензия (hotfix после v0.10.0).
- `.gitignore` (hotfix после v0.10.0).

## [0.10.0] — 2026-03-22

### Добавлено

- Интеграция **Langfuse**: зависимость, настройки, хелперы трассировки, callback в эндпоинтах агента.
- Самохост Langfuse в Docker Compose (стек v3: PostgreSQL, ClickHouse с embedded Keeper, worker, отдельный Redis), сервисы по умолчанию без профиля.
- Документация по Langfuse: спецификация, план внедрения, переменные в `.env.example`.
- Повторные запросы к LLM: `max_retries=3` с экспоненциальным backoff.

### Изменено

- Compose: корректные URL БД/ClickHouse, вынос конфигурации Langfuse в `.env`, упрощение интерполяции.
- Redis для Langfuse: `REDIS_HOST` / `REDIS_PORT` / `REDIS_AUTH` вместо `REDIS_CONNECTION_STRING`.
- `.env.example`, `compose.yml`, lock-файлы под новый стек.

### Исправлено

- Миграции, сеть Docker Langfuse, Redis, nginx на сервере, экспорт порта Langfuse (3000), трассировка Langfuse.
- Удаление пустых `LANGFUSE_INIT_*` из compose (пустые значения ломали Zod).
- Обязательные переменные Langfuse с dev-дефолтами (`NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY`).
- `PGDATA` для `langfuse-db`, `env_file` для согласованной загрузки `.env`.
- Игнор `__pycache__` в `.gitignore`.

## [0.9.0] — 2026-03-21

### Добавлено

- Доработка **ADMET** и начальная конфигурация **Langfuse**.
- Инструмент **protocol review**; синхронизация обновлений `ushenin_admet`.
- RAG MVP: ноутбук и зависимости.

### Исправлено

- Ключ PubChem для SMILES, таймауты HTTP-запросов.
- Миграции БД.
- `docker compose` и `compose.production.yml`.

## [0.8.0] / [0.8.1] — 2026-03-21

Теги `v0.8.0` и `v0.8.1` указывают на **один и тот же коммит**.

### Добавлено

- Инструмент предсказания **ADMET**.
- **AiZynthFinder** API (первая версия), конфиг, данные AZF и RetroCast.

### Исправлено

- Сборка ретросинтеза (retro build).

## [0.7.2] — 2026-03-21

### Добавлено

- Меню копирования SMILES, статус копирования.

### Исправлено

- Кнопки в чате.

## [0.7.1] — 2026-03-20

### Исправлено

- Отображение вызовов инструментов (пробелы) в чате.

## [0.7.0] — 2026-03-20

### Добавлено

- Предсказание условий реакции.
- Предупреждения по **опасным веществам**.

## [0.6.0] — 2026-03-20

### Добавлено

- **AI-агент**: реестр инструментов, RDKit (масса, сходство, ФГ), безопасность (контролируемые и взрывчатые вещества), конвертеры (name↔SMILES, mol↔CAS), поиск (патенты, веб, Semantic Scholar), ChemSpace (цены), реакционные инструменты (Docker), расширенный системный промпт по безопасности.
- Данные: `chem_wep_smi.csv` и др.
- Простой **чат** на фронтенде, подсветка Markdown в стриминге, задержки/стриминг чата.
- E2E-тесты (Playwright) для чата и химических инструментов, `data-testid` в компонентах.
- Зависимости: `rdkit`, `molbloom`, `pandas` и др.; Docker/compose под реакционные сервисы.

### Изменено

- Таймауты задач чата настраиваются; retry с backoff для Semantic Scholar.
- Обновление зависимостей и Docker Compose.

### Исправлено

- Чат и Markdown-стриминг на фронтенде.
- Dockerfile AI-агента.

## [0.5.0] — 2026-03-19

### Добавлено

- Phase 1 API (в т.ч. задачи 1.3–1.4, модели).
- `contrib.md`, правила релизов, обновление README.

### Исправлено

- Контрибьютинг и план (`*.plan.md`).

## [0.4.0] — 2026-03-19

### Добавлено

- **Redis** и **Celery**.
- Архитектурный план.

## [0.3.0] — 2026-03-19

### Добавлено

- Обновление главной страницы и логотипа, `setup.md`.

### Исправлено

- Ссылка на GitHub, вёрстка главной.

## [0.2.0] — 2026-03-19

### Добавлено

- Поддержка **Ketcher**.

## [0.1.1] — 2026-03-19

### Добавлено

- Ссылка на репозиторий, `.cursorignore`, инструкции по новому серверу, обновление `setup.md`.

### Исправлено

- Аутентификация, скрытие Adminer в production, переименование chemcrow2, структура файлов.

## [0.1.0] — 2026-03-18

Первый помеченный релиз (слияние в основную линию разработки).

[Unreleased]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.7.2...v0.8.0
[0.8.1]: https://github.com/arqoofficial/itmo-chemcrow2/releases/tag/v0.8.1
[0.7.2]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/arqoofficial/itmo-chemcrow2/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/arqoofficial/itmo-chemcrow2/releases/tag/v0.1.0
