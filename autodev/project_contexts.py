"""Project contexts for PM agent."""

PROJECTS = {
    "zinchenkomig/great_alerter_backend": {
        "name": "Great Alerter Backend",
        "description": "FastAPI backend для системы мониторинга и алертов",
        "stack": "Python, FastAPI, SQLAlchemy, PostgreSQL, Celery",
        "features": """
- Мониторинг цен криптовалют (Binance API)
- Настраиваемые алерты (price above/below, % change)
- Telegram уведомления
- REST API для управления алертами
- Аутентификация через JWT
- Celery для фоновых задач (проверка цен)
""",
        "current_focus": "Стабилизация, добавление новых источников данных",
    },
    
    "zinchenkomig/great_alerter_frontend": {
        "name": "Great Alerter Frontend", 
        "description": "Next.js dashboard для управления алертами",
        "stack": "TypeScript, Next.js 15, Tailwind CSS, shadcn/ui",
        "features": """
- Dashboard с текущими ценами
- Создание/редактирование алертов
- История срабатываний
- Графики цен (TradingView widget)
- Responsive дизайн
- Dark/Light theme
""",
        "current_focus": "UX улучшения, мобильная версия",
    },
    
    "zinchenkomig/autodev-framework": {
        "name": "AutoDev Framework",
        "description": "Платформа для автоматизации разработки с AI агентами",
        "stack": "Python, FastAPI, Next.js, PostgreSQL, k3s",
        "features": """
- Developer Agent (Claude Code) — автоматическое написание кода
- PM Agent — создание задач через чат
- Release Manager — деплой на staging/production
- Kanban доска для задач
- GitHub интеграция (PR, branches)
- Метрики и логи агентов
""",
        "current_focus": "Улучшение PM агента, автономность",
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

**Текущие фичи:**
{project['features']}

**Фокус:** {project['current_focus']}
"""

def get_all_projects_context() -> str:
    """Get context for all projects."""
    contexts = []
    for repo, project in PROJECTS.items():
        contexts.append(f"""
### {project['name']} ({repo})
{project['description']}
Стек: {project['stack']}
Фичи: {project['features'].strip()}
""")
    return "\n".join(contexts)
