# Быстрый старт

Настройте автономную AI-разработку для вашего проекта за 5 минут.

## Требования

- Python 3.12+
- Docker & Docker Compose
- GitHub аккаунт с токеном (`repo` + `write:packages` scopes)
- API ключ LLM провайдера (Anthropic Claude рекомендуется)

## Установка

```bash
# Клонировать
git clone https://github.com/zinchenkomig/autodev-framework.git
cd autodev-framework

# Установить зависимости
pip install uv
uv sync --all-extras

# Поднять PostgreSQL и Redis
docker compose up -d
```

## Инициализация проекта

```bash
# Создать конфигурацию
autodev init
```

Это создаст файл `autodev.yaml` — отредактируйте его под ваш проект:

```yaml
project:
  name: "My App"

repos:
  - name: backend
    url: github.com/user/my-backend
    language: python
    tests: "pytest tests/"
    context_file: CLAUDE.md

  - name: frontend
    url: github.com/user/my-frontend
    language: typescript
    tests: "npm run build"

environments:
  staging:
    url: https://staging.myapp.com
    deploy_command: "./deploy.sh staging"
  production:
    url: https://myapp.com
    deploy_command: "./deploy.sh production"
    requires_approval: true

agents:
  developer:
    runner: claude-code
    model: claude-sonnet-4
    max_iterations: 20
    triggers:
      - type: event
        value: task.assigned
    instructions: |
      Ты разработчик. Бери задачу, пиши код, создавай PR.

  tester:
    runner: claude-sonnet
    tools: [playwright]
    triggers:
      - type: event
        value: deploy.staging
    instructions: |
      Ты тестировщик. Тестируй через браузер.

  pm:
    runner: claude-sonnet
    triggers:
      - type: schedule
        value: "0 */6 * * *"
    instructions: |
      Ты PM. Анализируй проект, создавай задачи.

release:
  branch_strategy: gitflow
  min_prs: 8
  auto_deploy_staging: true
  require_human_approval: true

notifications:
  targets:
    - type: telegram
      config:
        bot_token: "${TELEGRAM_BOT_TOKEN}"
        chat_id: "${TELEGRAM_CHAT_ID}"
  events:
    - release.ready
    - bug.found
    - deploy.production
```

## Настройка переменных окружения

```bash
# Создать .env файл
cat > .env << EOF
DATABASE_URL=postgresql+asyncpg://autodev:autodev@localhost:5432/autodev
GITHUB_TOKEN=ghp_your_token
GITHUB_WEBHOOK_SECRET=your_webhook_secret
ANTHROPIC_API_KEY=sk-ant-your_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
EOF
```

## Запуск

```bash
# Запустить сервер
autodev start

# Или через Docker
docker compose --profile full up -d
```

Дашборд будет доступен на http://localhost:3000
API — на http://localhost:8000

## Настройка GitHub Webhook

1. Зайдите в Settings → Webhooks в вашем репозитории
2. Payload URL: `https://your-server.com/api/webhooks/github`
3. Content type: `application/json`
4. Secret: значение из `GITHUB_WEBHOOK_SECRET`
5. Events: Push, Pull requests, Issues, Check suites

## Основные команды

```bash
# Статус системы
autodev status

# Добавить задачу вручную
autodev task add "Добавить авторизацию" --repo backend --priority high

# Список задач
autodev task list

# Запустить агента вручную
autodev agent trigger developer

# Создать релиз
autodev release create

# Одобрить релиз для деплоя на прод
autodev release approve v2024-01-15-1
```

## Как это работает

```
GitHub Issues → PM анализирует → Task Queue
                                      ↓
                              Developer берёт задачу
                                      ↓
                              Пишет код → PR
                                      ↓
                              CI проверяет → ✅
                                      ↓
                         Release Manager собирает релиз
                                      ↓
                           Deploy на staging
                                      ↓
                    Tester + BA проверяют через браузер
                                      ↓
                    Вам приходит отчёт → вы одобряете
                                      ↓
                           Deploy на production
```

## Дашборд

- **📊 Overview** — статистика: задачи, агенты, PR-ы
- **📋 Tasks** — Kanban board с drag & drop
- **🤖 Agents** — мониторинг агентов в реальном времени
- **📦 Releases** — управление релизами
- **📜 Events** — лента событий
- **📈 Metrics** — стоимость, скорость, качество

## Архитектура

```
autodev/
├── core/           # Ядро: очередь, события, стейт-машина
├── agents/         # Агенты: developer, tester, BA, PM, release
├── api/            # FastAPI: REST API + webhooks
├── integrations/   # GitHub, Telegram, Slack, Browser
└── cli/            # CLI команды

dashboard/          # Next.js дашборд
```

Подробнее: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
