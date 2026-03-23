# query_mas.py

CLI-скрипт для прямого запроса к MAS через API ai-agent (без UI).

Скрипт отправляет `POST` на endpoint чата (по умолчанию `http://127.0.0.1:8100/api/v1/chat`) с payload:

```json
{
  "messages": [{ "role": "user", "content": "<ваш вопрос>" }],
  "provider": "openai"
}
```

Если endpoint локальный (`localhost`, `127.0.0.1`, `0.0.0.0`), скрипт по умолчанию пытается автоматически поднять ai-agent через `uvicorn`, затем ждёт `/health`.

## Где запускать

Из директории `services/ai-agent`:

```bash
uv run python scripts/query_mas.py "Синтез ибупрофена"
```

## Источник переменных окружения

Перед запуском скрипт загружает переменные из корневого `.env` репозитория (если файл существует). Это позволяет использовать общие настройки провайдера и endpoint-ов без ручного экспорта переменных.

По умолчанию URL берётся из:

- `AI_AGENT_CHAT_URL`, если задана
- иначе `http://127.0.0.1:8100/api/v1/chat`

## Аргументы

- `question` (позиционный, опциональный): вопрос для MAS.
  - Если не передан, скрипт попросит ввести вопрос интерактивно.
- `--agent-url`: URL endpoint чата.
- `--provider`: override провайдера LLM (`openai` | `anthropic`).
- `--timeout-seconds`: HTTP timeout в секундах (по умолчанию `120`).
- `--json`: вывести полный JSON-ответ.
- `--no-auto-start-agent`: не пытаться автостартовать локальный ai-agent.
- `--startup-wait-seconds`: сколько ждать health-check после автостарта (по умолчанию `25`).

## Примеры

Базовый запуск:

```bash
uv run python scripts/query_mas.py "Предложи ретросинтетический путь для аспирина"
```

Явно указать provider:

```bash
uv run python scripts/query_mas.py \
  "Сгенерируй план синтеза парацетамола" \
  --provider openai
```

Запрос к удалённому инстансу без автостарта:

```bash
uv run python scripts/query_mas.py \
  "Оцени реалистичность маршрута" \
  --agent-url http://my-agent-host:8100/api/v1/chat \
  --no-auto-start-agent
```

Получить полный JSON:

```bash
uv run python scripts/query_mas.py \
  "Подбери условия реакции" \
  --json
```

## Что выводится

- По умолчанию: только поле `content` из ответа API.
- Если в ответе есть `tool_calls`, скрипт дополнительно печатает список вызовов инструментов.
- С флагом `--json`: весь ответ API в формате JSON.

## Типичные проблемы

`MAS request failed: ...` при локальном URL:

- Убедитесь, что установлен `uv` и зависимости проекта доступны.
- Запустите сервер вручную:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8100
```

`MAS request failed with HTTP ...`:

- Проверьте `--agent-url`.
- Проверьте, что endpoint действительно принимает формат `POST /api/v1/chat`.
- При необходимости включите `--json` для более подробной диагностики ответа.
