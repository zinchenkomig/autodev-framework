# AutoDev Architecture

## Task Lifecycle

```
   ┌─────────┐  ┌───────────┐  ┌────────────┐  ┌─────────────────┐  ┌─────────┐  ┌──────────┐
   │ QUEUED  │─→│IN_PROGRESS│─→│ AUTOREVIEW │─→│READY_TO_RELEASE │─→│ STAGING │─→│ RELEASED │
   └─────────┘  └───────────┘  └────────────┘  └─────────────────┘  └─────────┘  └──────────┘
        ↑              │              │                                    │
        │              ▼              ▼                                    │ правки
        │         ┌────────┐                                              ↓
        └─────────│ FAILED │                                    новая задача → QUEUED
                  └────────┘
```

### Статусы

| Статус | Описание | Кто переводит |
|--------|----------|---------------|
| `queued` | Задача в очереди | PM Agent / User |
| `in_progress` | Developer работает | Orchestrator |
| `autoreview` | CI + Critic проверяют (автоматика, не требует человека) | Orchestrator |
| `ready_to_release` | Все проверки пройдены, ждёт пока Release Agent сформирует релиз | CI Webhook |
| `staging` | Задеплоено на staging в составе релиза, ждёт фидбек/approve от User | Release Agent |
| `released` | Approve получен, задеплоено на production | Release Agent |
| `failed` | Ошибка выполнения | Orchestrator |

### Переходы

- **queued → in_progress**: Orchestrator берёт задачу, Developer Agent начинает работу
- **in_progress → autoreview**: Developer Agent завершил (Critic одобрил), PR создан
- **autoreview → ready_to_release**: GitHub CI прошёл успешно (webhook)
- **autoreview → failed**: CI или Critic отклонили
- **ready_to_release → staging**: Release Agent формирует релиз, мержит PR, деплоит на staging
- **staging → released**: User approve → deploy production
- **staging → (новая задача)**: User даёт фидбек → создаётся follow-up задача → queued
- **failed → queued**: Full Restart (удаляет ветку, PR, сбрасывает)

### Релизы

Release Agent формирует релизы из пула `ready_to_release` задач:

1. Берёт N задач в `ready_to_release`
2. Создаёт Release (фиксирует список задач)
3. Мержит их PR в develop
4. Создаёт release branch
5. Деплоит на staging
6. Задачи переходят в `staging`
7. User смотрит staging, даёт фидбек или approve

**Важно:**
- Список задач в релизе фиксируется при создании
- Новые `ready_to_release` задачи НЕ попадают в текущий релиз
- Доработки по фидбеку создаются как новые задачи → проходят полный цикл
- Developer продолжает работать над другими задачами параллельно

## Agent Graph

```
┌─────────────────────────────────────────────────────────────┐
│                        USER (Mikhail)                        │
│   Telegram / Dashboard                                       │
└──────────┬─────────────────────────────────┬─────────────────┘
           │ описание фичи                   │ фидбек/approve
           ▼                                 ▼
┌──────────────────┐              ┌────────────────────┐
│   PM Agent       │              │  Dashboard UI      │
│   (GLM-5 Turbo)  │              │  ready_to_release  │
│   Анализ + план  │              │  → правки/approve  │
│   → task proposals│              └────────┬───────────┘
└────────┬─────────┘                        │
         │ создаёт задачи                   │ follow-up задачи
         │ (с depends_on)                   │
         ▼                                  ▼
┌──────────────────────────────────────────────────────────────┐
│                     TASK QUEUE (PostgreSQL)                   │
│  Задачи с приоритетами и зависимостями                       │
└──────────┬───────────────────────────────────────────────────┘
           │ poll every 30s
           ▼
┌──────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR (systemd)                    │
│  Единственный процесс с Claude Code CLI                     │
│                                                              │
│  Phase 1: 📋 Developer → Plan                               │
│  Phase 2: 🔍 Critic → Plan Review                           │
│  Phase 3: 🛠️ Developer → Implementation                      │
│  Phase 4: 🔍 Critic → Code Review (до 3 итераций)           │
│  Phase 5: 📦 git commit + push + PR                         │
│                                                              │
│  Claude Code: --print --permission-mode bypassPermissions    │
│  Timeout: 30 min                                             │
│  Working dir: /tmp/autodev-{task_id}                         │
└──────────┬───────────────────────────────────────────────────┘
           │ push + PR
           ▼
┌──────────────────────────────────────────────────────────────┐
│                     GITHUB                                    │
│                                                              │
│  Branch: autodev-{task_id}                                   │
│  PR: develop ← autodev-{task_id}                            │
│  CI: GitHub Actions (pytest / npm build)                     │
│  Review: Claude Code Review (workflow)                       │
└──────────┬───────────────────────────────────────────────────┘
           │ check_suite webhook
           ▼
┌──────────────────────────────────────────────────────────────┐
│                     CI WEBHOOK                                │
│  autoreview → ready_to_release (при CI success)              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     RELEASE AGENT (TODO)                      │
│                                                              │
│  1. Собирает задачи в ready_to_release                       │
│  2. Мержит PR в develop                                      │
│  3. Создаёт release branch                                   │
│  4. Деплоит на staging                                       │
│  5. Уведомляет user                                          │
│  6. User approve → deploy production                         │
│  7. Статус → released                                        │
└──────────────────────────────────────────────────────────────┘
```

## Alerting System

```
Triggers:
  ├── Task failed          → high severity
  ├── API 500 error        → high severity (middleware auto)
  ├── Task stuck >1h       → medium severity (TODO: heartbeat)
  └── Agent stuck          → medium severity (TODO: heartbeat)

Pipeline:
  Event → Alert (DB) → Notify OpenClaw (Brian) → Telegram (User)
                     → Dashboard /alerts page
```

## Infrastructure

| Component | Where | Purpose |
|-----------|-------|---------|
| Orchestrator (worker) | systemd on dev server | Runs Claude Code, processes tasks |
| API | k8s pod (autodev-api) | REST API, no worker |
| Dashboard | k8s pod (autodev-dashboard) | Next.js UI |
| PostgreSQL | k8s pod (autodev-postgres) | Data store |
| Claude Code | installed on dev server | AI coding |

**Dev server**: 188.245.45.123  
**Staging/Prod**: 178.104.35.218  
**Dashboard**: https://autodev.zinchenkomig.com  

## Repositories

| Repo | Purpose |
|------|---------|
| `zinchenkomig/autodev-framework` | AutoDev platform itself |
| `zinchenkomig/great_alerter_backend` | Target project: backend |
| `zinchenkomig/great_alerter_frontend` | Target project: frontend |

## Key Design Decisions

1. **Orchestrator on host, not k8s** — Claude Code needs local filesystem
2. **HTTPS clone с токеном** — Docker/k8s не имеет SSH ключей
3. **develop для PR, main для production** — стандартный git flow
4. **PM на GLM-5 Turbo** — оптимизирован для агентов, 200K контекст
5. **Developer-Critic loop** — два независимых "мнения" для качества кода
6. **Sequential tasks** — depends_on для backend → frontend порядка
7. **autoreview ≠ human review** — автоматика не требует действий от user

## Task Types

### Feature (default)
```
queued → in_progress → autoreview → ready_to_release → [ждёт Release Manager] → staging → released
```

### Hotfix (feedback fix)
```
queued → in_progress → autoreview → staging (в текущий релиз, PR мержится сразу)
```

Hotfix создаётся через:
- `/feedback текст` в Telegram
- "Request Changes" на странице релиза в Dashboard
- `POST /api/releases/{id}/feedback`

Hotfix обходит Release Manager и попадает напрямую в текущий staging релиз.
