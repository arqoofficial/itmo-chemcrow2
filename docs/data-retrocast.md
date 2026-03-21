# Данные RetroCast (Project Procrustes)

Наборы бенчмарков и производных артефактов для ретросинтеза хранятся на CDN и синхронизируются скриптом [`scripts/get-data-project-procrustes.sh`](../scripts/get-data-project-procrustes.sh).

## Требования

- `curl`, `awk`
- контрольная сумма: `sha256sum` (Linux) или `shasum -a 256` (macOS)

## Скачать всё (~554 MiB)

Из корня репозитория:

```bash
bash scripts/get-data-project-procrustes.sh all
```

Файлы по умолчанию попадают в **`data/retrocast/`** (структура как в манифесте: `1-benchmarks/`, `2-raw/`, …).

Перед полной загрузкой можно посмотреть список файлов без скачивания:

```bash
bash scripts/get-data-project-procrustes.sh all --dry-run
```

## Каталог и переменная окружения

| Способ | Пример |
|--------|--------|
| По умолчанию | `data/retrocast` (относительно текущей директории при запуске) |
| Переменная | `RETROCAST_DATA_DIR=/path/to/data` |
| Флаг | `--dir=/path/to/data` |

Пример:

```bash
RETROCAST_DATA_DIR=~/retrocast-data bash scripts/get-data-project-procrustes.sh all
```

## Цели (targets)

Один аргумент — одна цель. Размеры ориентировочные (см. вывод скрипта без аргументов).

| Цель | Описание |
|------|----------|
| `all` | весь манифест |
| `benchmarks` | бенчмарки целиком |
| `definitions` | только `1-benchmarks/definitions` |
| `stocks` | только `1-benchmarks/stocks` |
| `raw` | `2-raw/*` |
| `processed` | `3-processed/*` |
| `scored` | `4-scored/*` |
| `results` | `5-results/*` |

Отдельные бандлы под конкретные бенчмарки (подтягивают нужные stock-файлы):

- `mkt-lin-500`, `mkt-cnv-160`
- `ref-lin-600`, `ref-cnv-400`, `ref-lng-84`

## Флаги и справка

| Флаг | Действие |
|------|----------|
| `--dry-run` | только список того, что было бы скачано |
| `--dir=PATH` | каталог назначения |
| `-h`, `--help` | краткая справка |
| `-V`, `--version` | версия скрипта |

Без аргументов скрипт печатает таблицу целей и размеров и завершает работу (код выхода 1 — как у `-h`).

## Повторный запуск

- Уже скачанные файлы с **совпадающим SHA-256** пропускаются (`[VERIFIED - LOCAL]`).
- При несовпадении хеша файл перекачивается.
- Источник: `https://files.ischemist.com/retrocast/data` (манифест `SHA256SUMS`).

## Запуск через pipe (как в подсказке скрипта)

Если скрипт получен по `curl`, передавайте аргументы после `bash -s --`:

```bash
curl -fsSL https://example.com/get-data-project-procrustes.sh | bash -s -- all --dry-run
```

(В репозитории используйте локальный путь `bash scripts/...`, как выше.)
