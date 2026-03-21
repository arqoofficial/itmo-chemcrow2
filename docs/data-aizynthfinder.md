# Данные AiZynthFinder (USPTO)

Публичные веса и шаблоны для [AiZynthFinder](https://github.com/MolecularAI/aizynthfinder) не хранятся в git. Их можно подтянуть скриптом [`scripts/download_public_data.py`](../scripts/download_public_data.py).

## Требования

- Python с пакетами `requests` и `tqdm` (в окружении проекта обычно уже есть через `uv` / backend).

## Запуск

Из **корня репозитория** (путь по умолчанию — `data/aizynthfinder`):

```bash
cd /path/to/itmo_fatsapi
uv run python scripts/download_public_data.py
```

Другой каталог:

```bash
uv run python scripts/download_public_data.py /tmp/my-aizynth-data
```

## Что скачивается

| Файл | Назначение |
|------|------------|
| `uspto_model.onnx` | политика расширения (MCTS), USPTO |
| `uspto_templates.csv.gz` | шаблоны для expansion |
| `uspto_ringbreaker_model.onnx` | ringbreaker, ONNX |
| `uspto_ringbreaker_templates.csv.gz` | шаблоны ringbreaker |
| `uspto_filter_model.onnx` | фильтр |
| `zinc_stock.hdf5` | сток реагентов (ZINC) |

После загрузки в том же каталоге создаётся **`config.yml`** с абсолютными путями к этим файлам.

Источники: записи Zenodo (модели/шаблоны) и figshare (stock) — URL зашиты в скрипте.

## Повторный запуск

Скрипт **перезаписывает** файлы при каждом запуске (докачки по хешу нет). При необходимости удалите каталог или отдельные файлы вручную.

См. также: бенчмарки RetroCast — [data-retrocast.md](./data-retrocast.md).
