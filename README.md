# AutoDev

Задачи с телефона → Claude Code пишет код → изменение само доезжает до stage.

```
задача (канбан / Telegram)
  → триаж: в каком репо делать (бэк, фронт или оба)
  → Claude Code в чистом чекауте: план, код, тесты, self-review, коммит
  → PR в stage → CI → авто-merge
  → stage-деплой (CI целевого репо) → проверка, что коммит реально на stage
  → QA: headless-браузер открывает изменённые страницы, ловит ошибки, делает скриншоты
  → уведомление «✅ на stage» со ссылкой и скриншотом
  → кнопка «Release» → PR stage → main → прод
```

Человек нужен в двух местах: поставить задачу и нажать «Release».

## Как пользоваться с телефона

1. Открой https://autodev.zinchenkomig.com и добавь на главный экран (Safari → «Поделиться» → «На экран Домой»).
2. Кнопка **＋ Задача** — пишешь или диктуешь клавиатурой. Первая строка станет заголовком, остальное — подробностями.
   Для проекта с бэком и фронтом репозиторий можно не выбирать: агент решит сам и при необходимости разобьёт задачу.
3. Дальше всё само. В Telegram придёт «✅ на stage» со ссылкой и скриншотом. Если что-то не так, придёт «❌» с причиной.
4. В карточке задачи видно ход работы в реальном времени. Кнопка «Правки» отправляет агенту доработку (тот же PR или новая задача).
5. На странице проекта кнопка **Выкатить в прод** открывает PR stage → main и мержит его после зелёных проверок.
6. Новый проект можно начать с нуля: **Проекты → ＋ Проект → Создать с нуля**. AutoDev создаст репозиторий на GitHub
   (с ветками stage и прода), а описание «Что строим» станет первой задачей — агент выберет стек и заложит каркас:
   код, тесты, CI на PR, CLAUDE.md.
   Без owner в имени репозиторий создаётся в организации проектов (`AUTODEV_PROJECTS_ORG`), и деплой там уже есть:
   кластер разворачивает каждый её репо с `deploy/values.yaml` одним общим чартом — ветка stage на
   `https://<repo>.stage.<AUTODEV_APPS_DOMAIN>`, main на `https://<repo>.prod.<AUTODEV_APPS_DOMAIN>`
   (hetzner-gitops: `charts/project`, `argocd/appset-projects.yaml`). AutoDev кладёт в репо workflow сборки образа,
   сам заполняет URL stage и `/version`, а каркасная задача выполняет контракт деплоя.
   Токену `GITHUB_TOKEN` нужно право создавать репозитории (scope `repo`, для организации — её доступ).

То же самое умеет бот: обычное сообщение создаёт задачу в текущем проекте, а ещё есть команды `/project`, `/tasks`, `/stage`, `/release`.

## Как это устроено

- **API** (FastAPI): задачи, проекты, релизы, Telegram-вебхук. Работает в k8s.
- **Воркер**: N слотов разработчика и цикл доставки. Работает на хосте под systemd с полными правами.
  Агент сам ставит зависимости, запускает тесты, docker и браузер. От явно разрушительных команд
  (остановка k3s, `kubectl delete` в чужих namespace, `rm -rf /` …) защищает PreToolUse-гард.
- **Раннер**: [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview). Одна сессия на раунд.
  Раунды исправлений (красный CI, конфликт, правки владельца) продолжают ту же сессию через `resume`.
- **Проекты**: проект — это один или несколько репозиториев с общим stage. Хранятся в БД.
  `autodev.yaml` только засевает их при первом старте, дальше проекты редактируются в дашборде.
- **GitHub** опрашивается воркером, входящие вебхуки не нужны.

Подробности — в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Статусы задачи

| статус | что происходит |
|---|---|
| `queued` | ждёт свободного слота (или раунда исправлений) |
| `in_progress` | Claude работает |
| `ci` | PR открыт, ждём проверок; после зелёного CI будет авто-merge |
| `deploying` | смержено в stage, ждём, когда stage реально запустит этот коммит |
| `on_stage` | на stage, ждёт релиза |
| `released` | в проде |
| `failed` / `cancelled` | см. `error`; кнопка Retry |

## Локальный запуск

```bash
uv sync --extra dev
export DATABASE_URL=postgresql+asyncpg://autodev:autodev@localhost:5432/autodev
export GITHUB_TOKEN=...            # repo + workflow scopes
export AUTODEV_WORKDIR=/tmp/autodev-work
uv run autodev start               # миграции, API на :8000 и воркер
uv run autodev task add "Добавь поиск по имени" -p alerter
```

Claude Code должен быть залогинен (`claude login` или `CLAUDE_CODE_OAUTH_TOKEN`).

Основные переменные (полный список — `autodev/core/config.py`):

| переменная | по умолчанию | |
|---|---|---|
| `AUTODEV_ROLE` | `all` | `api`, `worker` или `all` |
| `AUTODEV_MODEL` | (дефолт CLI) | модель Claude, например `opus` |
| `AUTODEV_WORKER_SLOTS` | `2` | сколько задач идёт параллельно (плюс `max_parallel` у проекта) |
| `AUTODEV_MAX_FIX_ATTEMPTS` | `3` | раундов исправлений до `failed` |
| `AUTODEV_PUBLIC_URL` | | адрес дашборда для ссылок в уведомлениях |

## Разработка

```bash
git config core.hooksPath .githooks   # pre-push: ruff, pytest, tsc
export TEST_DATABASE_URL=postgresql+asyncpg://autodev:autodev@localhost:5432/autodev_test
uv run pytest
```

Тестам нужен Postgres (модели используют sequence).
