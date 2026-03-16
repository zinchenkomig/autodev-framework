# Конфигурация

## autodev.yaml

Полная спецификация конфигурационного файла.

### project

```yaml
project:
  name: "My App"      # Название проекта (обязательно)
```

### repos

Список репозиториев проекта. Может быть один или несколько.

```yaml
repos:
  - name: backend              # Уникальное имя (обязательно)
    url: github.com/user/repo  # GitHub URL (обязательно)
    language: python            # Язык: python, typescript, go, rust, java
    tests: "pytest tests/"     # Команда запуска тестов
    lint: "ruff check ."       # Команда линтера
    context_file: CLAUDE.md    # Файл с инструкциями для LLM (опционально)
```

### environments

Среды деплоя. Минимум одна (staging или production).

```yaml
environments:
  dev:
    url: https://dev.myapp.com
    deploy_command: "./deploy.sh dev"
  staging:
    url: https://staging.myapp.com
    deploy_command: "./deploy.sh staging"
  production:
    url: https://myapp.com
    deploy_command: "./deploy.sh production"
    requires_approval: true     # Требует одобрения человека
```

### agents

Настройка AI-агентов.

```yaml
agents:
  developer:
    runner: claude-code          # claude-code, llm, shell, mock
    model: claude-sonnet-4       # Модель LLM
    max_iterations: 20           # Макс попыток на задачу
    triggers:
      - type: event              # event или schedule
        value: task.assigned     # Имя события
    tools: []                    # Доп. инструменты: playwright, etc.
    instructions: |              # Системный промпт для агента
      Ты разработчик...
```

**Доступные роли:** developer, tester, ba, pm, release_manager

**Runners:**
- `claude-code` — Claude Code CLI (лучший для разработки)
- `llm` — Прямой вызов LLM API
- `shell` — Bash скрипт
- `mock` — Для тестов

**Триггеры:**
- `event: task.assigned` — когда назначена задача
- `event: pr.created` — когда создан PR
- `event: deploy.staging` — когда задеплоили на staging
- `schedule: "0 */2 * * *"` — cron расписание

### release

```yaml
release:
  branch_strategy: gitflow    # gitflow (develop→main) или trunk (только main)
  min_prs: 8                  # Минимум PR-ов для релиза
  auto_deploy_staging: true   # Авто-деплой на staging
  require_human_approval: true # Требовать одобрение для прода
```

### notifications

```yaml
notifications:
  targets:
    - type: telegram
      config:
        bot_token: "${TELEGRAM_BOT_TOKEN}"
        chat_id: "123456789"
    - type: slack
      config:
        webhook_url: "${SLACK_WEBHOOK_URL}"
    - type: webhook
      config:
        url: "https://hooks.example.com/autodev"
        headers:
          Authorization: "Bearer ${WEBHOOK_TOKEN}"
  events:                      # Какие события отправлять
    - release.ready
    - bug.found
    - deploy.production
    - agent.failed
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://autodev:autodev@localhost:5432/autodev` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `GITHUB_TOKEN` | GitHub personal access token | — |
| `GITHUB_WEBHOOK_SECRET` | Secret для верификации webhooks | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OPENAI_API_KEY` | OpenAI API key (если используется) | — |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | — |
| `TELEGRAM_CHAT_ID` | Telegram chat ID для уведомлений | — |

## LLM Провайдеры

Поддерживаемые провайдеры и модели:

| Провайдер | Модели | Переменная |
|---|---|---|
| Anthropic | claude-opus-4, claude-sonnet-4 | `ANTHROPIC_API_KEY` |
| OpenAI | gpt-4o, gpt-4-turbo | `OPENAI_API_KEY` |
| Google | gemini-2.5-pro | `GOOGLE_API_KEY` |
| Ollama | llama3, codestral | — (локальный) |
