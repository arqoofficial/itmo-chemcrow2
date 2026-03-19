# CONTRIBUTING (Hackathon Team Guide)

Короткий гайд по работе с Git для команды из 5 человек.

Цель: быстро интегрировать фичи и не ломать `main`.

## Базовые правила

- В `main` не пушим напрямую.
- Каждая задача делается в отдельной ветке.
- Любое изменение попадает в `main` только через Pull Request (через веб-интерфейс).
- PR маленькие и частые (лучше несколько небольших, чем один огромный).
- Перед merge автор обязан обновить ветку от актуального `main` и проверить проект локально.

## Именование веток

Используйте единый формат:

- `feature/<name>-<short-task>`
- `fix/<name>-<short-task>`
- `hotfix/<name>-<short-task>`
- `chore/<name>-<short-task>`

Примеры:

- `feature/alex-auth-endpoint`
- `fix/anna-molecule-parser`
- `hotfix/ivan-prod-timeout`

## Ежедневный workflow

### 1) Начало работы

```bash
git checkout main
git pull origin main
git checkout -b feature/<name>-<task>
```

### 2) Работа в ветке

```bash
git add .
git commit -m "feat: add molecule search endpoint"
```

Делайте осмысленные маленькие коммиты.

### 3) Перед созданием PR

```bash
git fetch origin
git rebase origin/main
```

Если rebase некомфортен команде, можно использовать:

```bash
git merge origin/main
```

После этого прогоните локальные проверки (что есть в проекте):

```bash
# пример
pytest
# и/или
npm run lint
```

### 4) Публикация ветки и PR

```bash
git push -u origin feature/<name>-<task>
```

Дальше создайте PR в веб-интерфейсе:

- `base`: `main`
- `compare`: ваша ветка
- добавьте краткое описание "что сделано" и "как проверить"
- назначьте минимум 1 ревьюера

## Правила Pull Request

- Один PR = одна логическая задача.
- Не смешивайте рефакторинг и новую фичу в одном PR.
- В описании PR добавьте:
  - Что изменено
  - Почему изменено
  - Как проверить
  - Возможные риски/ограничения
- Если PR большой, откройте его как Draft рано, чтобы команда видела прогресс.

## Быстрый шаблон описания PR

```md
## Что сделано
- ...

## Почему
- ...

## Как проверить
- [ ] Шаг 1
- [ ] Шаг 2

## Чек перед merge
- [ ] Ветка обновлена от main
- [ ] Локальные тесты/линтер пройдены
- [ ] Нет конфликтов
```

## Разруливание конфликтов

```bash
git fetch origin
git rebase origin/main
# решить конфликты в файлах
git add <resolved-files>
git rebase --continue
```

Если хотите отменить rebase:

```bash
git rebase --abort
```

## Hotfix-процесс

Если срочно чините критичный баг:

```bash
git checkout main
git pull origin main
git checkout -b hotfix/<name>-<task>
```

Дальше обычный короткий цикл: commit -> push -> PR -> review -> merge.

## Релизы стабильных версий (теги + GitHub UI)

Используем SemVer: `vMAJOR.MINOR.PATCH` (например, `v0.4.0`).

- `PATCH` - багфиксы без изменения API.
- `MINOR` - новые возможности с обратной совместимостью.
- `MAJOR` - несовместимые изменения.

### Когда делаем релиз

- В `main` уже влиты проверенные изменения.
- Проект запускается, базовые проверки проходят.
- Команда согласовала, что версия стабильна для демо/выдачи.

### Шаги релиза через тег

1) Обновить локальный `main`:

```bash
git checkout main
git pull origin main
```

2) Создать аннотированный тег:

```bash
git tag -a v0.4.0 -m "Release v0.4.0: Redis + Celery integration"
```

3) Отправить тег в удаленный репозиторий:

```bash
git push origin v0.4.0
```

Альтернатива (отправить все локальные теги):

```bash
git push origin --tags
```

### Оформление Release через GitHub веб-интерфейс

1) Откройте `Releases` -> `Draft a new release`.
2) Выберите или введите тег (например, `v0.4.0`).
3) Укажите target branch: `main`.
4) Заполните title: `v0.4.0`.
5) Добавьте release notes (соберите автоматически через гитхаб):
   - ключевые изменения;
   - исправленные баги;
   - возможные breaking changes;
   - как быстро проверить релиз.
6) Нажмите `Publish release`.

### Мини-шаблон release notes

```md
## Highlights
- ...

## Fixes
- ...

## Breaking changes
- None

## Quick check
- [ ] Backend starts
- [ ] Frontend starts
- [ ] Core user flow works
```

### Проверка релиза

```bash
git fetch --tags
git tag --list
git show v0.4.0
```

### Если ошиблись с тегом (до активного использования)

```bash
# удалить локально
git tag -d v0.4.0

# удалить на origin
git push origin :refs/tags/v0.4.0
```

После удаления создайте новый корректный тег (например, `v0.4.1`).

## Что НЕ делаем

- Не работаем в одной общей feature-ветке всей командой.
- Не держим долгоживущие ветки без синхронизации с `main`.
- Не пушим несобирающийся код "потом починим".
- Не делаем force-push в `main`.

## Рекомендация перед демо

За 1-2 часа до дедлайна вводим freeze:

- только багфиксы и стабилизация;
- новые фичи не вливаем;
- каждый merge проверяется минимум одним человеком.
