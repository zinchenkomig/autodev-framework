"""Project contexts for PM agent."""

PROJECTS = {
    "zinchenkomig/great_alerter_backend": {
        "name": "Great Alerter Backend",
        "description": "Backend alerting system с тремя сервисами",
        "stack": "Python, FastAPI, SQLAlchemy 2.0 async, asyncpg, PostgreSQL, Alembic",
        "features": """
## Сервисы:
- **Backend API** (FastAPI) — REST API для управления alert configurations, rules, checks
- **Scheduler** — генерирует scheduled alert runs по конфигурациям
- **Alerter Engine** — выполняет alert checks, вычисляет агрегации, создаёт alerts

## Архитектура:
- src/backend/ — FastAPI REST API (main.py, config.py, database.py, dto.py, repo.py)
- src/scheduler/ — polls DB, creates AlertRun records
- src/alerter_engine/ — processes runs, executes checks
- src/data_loader/ — PostgresLoader, MDLogDataLoader
- src/shared/ — models.py (ORM), enums.py, config.py

## Ключевые модели:
DbQuery, AlertConfig, AlertRule, Check, CheckResult, AlertRun, Alert

## Инфраструктура:
- Helm charts в charts/backend/
- Tilt для локальной k8s разработки
- Prometheus metrics, Jaeger tracing
""",
        "current_focus": "Стабилизация алертинга, новые источники данных",
    },
    
    "zinchenkomig/great_alerter_frontend": {
        "name": "Great Alerter Frontend", 
        "description": "Next.js dashboard для управления алертами",
        "stack": "TypeScript, Next.js 16, React 19, Chakra UI, Tailwind CSS, TanStack React Query, Orval",
        "features": """
## Страницы:
- /runs — timeline alert runs (главная)
- /configs — alert configurations CRUD
- /queries — database queries CRUD
- /rules — alert rules CRUD

## API Layer:
- ВСЕ API хуки генерируются через Orval из OpenAPI spec
- src/api/generated.ts — автогенерированные React Query hooks
- Workflow: npm run pregen:api && npm run gen:api

## Архитектура:
- App Router (src/app/)
- src/components/Layout.tsx — dashboard shell
- src/components/AlertRuleForm.tsx — сложная форма для alert rules
- src/types.ts — domain types

## Стилизация:
- Chakra UI для компонентов
- Tailwind CSS для кастомных стилей
- Light mode only
""",
        "current_focus": "UX улучшения, новые визуализации",
    },
    
    "zinchenkomig/autodev-framework": {
        "name": "AutoDev Framework",
        "description": "Платформа для автоматизации разработки с AI агентами",
        "stack": "Python, FastAPI, Next.js 16, PostgreSQL, k3s, Claude Code",
        "features": """
## Агенты:
- **Developer** (Claude Code) — автоматическое написание кода, создание PR
- **PM** (этот чат) — создание задач через диалог
- **Release Manager** — деплой на staging/production

## Dashboard (Next.js):
- Kanban доска для задач
- Мониторинг агентов
- Управление релизами
- PM Chat

## Backend (FastAPI):
- autodev/api/ — REST API
- autodev/orchestrator.py — основной цикл обработки задач
- autodev/core/models.py — Task, Agent, Release, etc.

## Инфраструктура:
- k3s кластер
- GitHub интеграция (PR, webhooks)
- Staging/Production environments
""",
        "current_focus": "Улучшение PM агента, автономность системы",
    },
}

def get_project_context(repo: str) -> str:
    """Get context string for a project."""
    project = PROJECTS.get(repo)
    if not project:
        return f"Проект: {repo} (контекст не настроен)"
    
    return f"""
## {project['name']}
{project['description']}

**Стек:** {project['stack']}

**Детали:**
{project['features']}

**Текущий фокус:** {project['current_focus']}
"""

def get_all_projects_context() -> str:
    """Get context for all projects."""
    contexts = []
    for repo, project in PROJECTS.items():
        contexts.append(f"""
### {project['name']} (`{repo}`)
{project['description']}

**Стек:** {project['stack']}
{project['features']}
**Фокус:** {project['current_focus']}
""")
    return "\n---\n".join(contexts)
