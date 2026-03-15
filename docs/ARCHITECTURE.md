# Архитектура AutoDev Framework

## Обзор

AutoDev состоит из 5 основных компонентов:

### 1. Orchestrator (ядро)

Центральный процесс-демон. Управляет всем.

```python
class Orchestrator:
    queue: TaskQueue          # очередь задач
    agents: AgentRegistry     # зарегистрированные агенты
    events: EventBus          # шина событий
    state: StateManager       # состояние системы
    runner: AgentRunner       # запуск LLM-сессий
```

**Жизненный цикл:**
1. Запускается как демон
2. Слушает события (webhooks, таймеры, внутренние)
3. По событию роутит задачу к агенту
4. Спаунит LLM-сессию для агента
5. Собирает результат, обновляет состояние
6. Генерирует новые события → цикл

### 2. Task Queue (очередь задач)

```python
class Task:
    id: str
    title: str
    description: str
    source: TaskSource        # github_issue, agent_created, manual
    priority: Priority        # critical, high, normal, low
    status: TaskStatus        # queued, assigned, in_progress, review, done, failed
    assigned_to: str | None   # agent role
    repo: str                 # target repository
    issue_number: int | None  # GitHub issue
    pr_number: int | None     # created PR
    depends_on: list[str]     # task IDs this depends on
    metadata: dict            # extra context
    created_by: str           # who created
    created_at: datetime
    updated_at: datetime
```

Приоритеты:
- **critical** — баги от тестировщика, блокеры
- **high** — задачи от пользователя
- **normal** — задачи от PM
- **low** — улучшения, рефакторинг

### 3. Event Bus (шина событий)

Events:
```
task.created        → PM создал задачу
task.assigned       → задача назначена агенту
pr.created          → developer создал PR
pr.merged           → PR замержен
pr.ci.passed        → CI прошёл
pr.ci.failed        → CI упал
deploy.staging      → задеплоили на staging
deploy.production   → задеплоили на прод
review.passed       → ревью пройдено
review.failed       → ревью не пройдено
bug.found           → тестировщик нашёл баг
release.ready       → релиз готов к проверке
release.approved    → человек одобрил релиз
agent.idle          → агент освободился
agent.failed        → агент не справился
```

Роутинг:
```yaml
routes:
  task.created:
    - action: assign_to_developer
  pr.created:
    - action: run_ci
    - action: trigger_agent
      agent: tester
  deploy.staging:
    - action: trigger_agent
      agent: tester
    - action: trigger_agent
      agent: ba
  bug.found:
    - action: create_task
      priority: critical
    - action: trigger_agent
      agent: developer
```

### 4. Agent Runner

Запускает LLM-сессии для агентов. Абстрактный — поддерживает разные бэкенды:

```python
class AgentRunner(Protocol):
    async def run(self, agent: AgentConfig, task: Task, context: dict) -> AgentResult:
        """Запустить агента с задачей"""

class ClaudeCodeRunner(AgentRunner):
    """Запуск через Claude Code CLI"""

class OpenClawRunner(AgentRunner):
    """Запуск через OpenClaw cron/sessions"""

class OpenAIRunner(AgentRunner):
    """Запуск через OpenAI API напрямую"""
```

### 5. Project Config

```yaml
project:
  name: "My App"
  repos:
    - name: backend
      url: github.com/user/backend
      language: python
      context_file: CLAUDE.md  # инструкции для LLM
      tests: "pytest tests/"
      lint: "ruff check ."
    - name: frontend
      url: github.com/user/frontend
      language: typescript
      context_file: CLAUDE.md
      tests: "npm run build"
      lint: "npm run lint"

environments:
  staging:
    url: https://staging.app.com
    deploy_command: "./deploy.sh staging"
  production:
    url: https://app.com
    deploy_command: "./deploy.sh production"
    requires_approval: true

agents:
  developer:
    runner: claude-code
    model: claude-sonnet-4
    max_iterations: 20
    triggers:
      - event: task.assigned
    instructions: |
      Ты разработчик. Бери задачу, пиши код, создавай PR.
      
  tester:
    runner: claude-sonnet
    tools: [playwright]
    triggers:
      - event: pr.created
      - event: deploy.staging
    instructions: |
      Ты тестировщик. Тестируй через браузер как пользователь.

release:
  branch_strategy: gitflow  # develop → release → main
  min_prs: 8
  auto_deploy_staging: true
  require_human_approval: true

notifications:
  telegram:
    chat_id: "123456789"
    events: [release.ready, bug.found, deploy.production]
```

## Схема базы данных

```sql
-- Задачи
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    source TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'queued',
    assigned_to TEXT,
    repo TEXT,
    issue_number INT,
    pr_number INT,
    depends_on UUID[],
    metadata JSONB DEFAULT '{}',
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Агенты
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    current_task_id UUID REFERENCES tasks(id),
    last_run_at TIMESTAMPTZ,
    total_runs INT DEFAULT 0,
    total_failures INT DEFAULT 0
);

-- История событий
CREATE TABLE events (
    id UUID PRIMARY KEY,
    type TEXT NOT NULL,
    payload JSONB NOT NULL,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Запуски агентов
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY,
    agent_id TEXT REFERENCES agents(id),
    task_id UUID REFERENCES tasks(id),
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    result JSONB,
    tokens_used INT,
    cost_usd DECIMAL(10,4)
);

-- Релизы
CREATE TABLE releases (
    id UUID PRIMARY KEY,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    tasks UUID[] NOT NULL,
    release_notes TEXT,
    staging_deployed_at TIMESTAMPTZ,
    production_deployed_at TIMESTAMPTZ,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## API

```
GET  /api/tasks                    # список задач
POST /api/tasks                    # создать задачу
GET  /api/tasks/:id                # детали задачи
PATCH /api/tasks/:id               # обновить задачу

GET  /api/agents                   # статусы агентов
POST /api/agents/:id/trigger       # запустить агента

GET  /api/events                   # история событий

GET  /api/releases                 # список релизов
POST /api/releases                 # создать релиз
POST /api/releases/:id/approve     # одобрить релиз
POST /api/releases/:id/deploy      # деплой на прод

POST /api/webhooks/github          # GitHub webhooks

GET  /api/dashboard/stats          # метрики для дашборда

WebSocket /ws/events               # real-time события для UI
```
