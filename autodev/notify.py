"""Owner notifications (Telegram). Never raise: a failed notification must not break the pipeline."""

from __future__ import annotations

import html
import logging

from autodev.core.config import get_settings
from autodev.core.models import Project, Release, Task

logger = logging.getLogger(__name__)


def _task_link(task: Task) -> str:
    title = html.escape(f"#{task.ticket_number} {task.title}")
    base = get_settings().public_url.rstrip("/")
    return f'<a href="{base}/tasks/{task.id}">{title}</a>' if base else f"<b>{title}</b>"


async def _send(text: str, photo: bytes | None = None, reply_markup: dict | None = None) -> None:
    try:
        from autodev.integrations.telegram_pm import notify_owner

        await notify_owner(text, photo=photo, reply_markup=reply_markup)
    except Exception:
        logger.exception("notification failed")


def test_plan_text(task: Task) -> str:
    plan = (task.metadata_ or {}).get("test_plan") or []
    steps = "\n".join(f"{i}. {html.escape(step[:400])}" for i, step in enumerate(plan, 1))
    return f"🧪 <b>Как проверить #{task.ticket_number}</b>\n\n{steps}"[:3900]


async def on_stage(task: Task, project: Project | None, qa=None, screenshot: bytes | None = None) -> None:
    broken = qa is not None and not qa.ok
    text = f"{'⚠️' if broken else '✅'} {_task_link(task)} на stage"
    if project and project.stage_url:
        text += f'\n🌐 <a href="{html.escape(project.stage_url)}">{html.escape(project.stage_url)}</a>'
    if broken:
        problems = "\n".join(f"• {html.escape(p[:200])}" for p in qa.problems[:5])
        text += f"\n\n<b>QA нашёл проблемы</b> — поставил задачу на исправление:\n{problems}"
    elif task.summary:
        text += f"\n\n{html.escape(task.summary[:600])}"
    if task.pr_url:
        text += f'\n\n<a href="{html.escape(task.pr_url)}">PR</a>'
    await _send(text, photo=screenshot)
    if (task.metadata_ or {}).get("test_plan") and not broken:
        button = {"text": "✅ Проверено", "callback_data": f"ok:{task.id}"}
        await _send(test_plan_text(task), reply_markup={"inline_keyboard": [[button]]})


async def failed(task: Task, reason: str) -> None:
    text = f"❌ {_task_link(task)}\n\n<pre>{html.escape(reason[:800])}</pre>"
    if task.pr_url:
        text += f'\n<a href="{html.escape(task.pr_url)}">PR</a>'
    await _send(text)


async def blocked(task: Task, reason: str) -> None:
    await _send(f"🤔 {_task_link(task)} — агенту нужна помощь\n\n{html.escape(reason[:1000])}")


async def released(release: Release, project: Project, tasks: list[Task]) -> None:
    lines = "\n".join(f"• {html.escape(f'#{t.ticket_number} {t.title}')}" for t in tasks[:30])
    await _send(f"🚀 <b>{html.escape(project.name)}</b> {html.escape(release.version)} в проде\n\n{lines}")


async def release_failed(release: Release, project: Project, reason: str) -> None:
    await _send(
        f"⚠️ Релиз <b>{html.escape(project.name)}</b> {html.escape(release.version)} застрял\n\n"
        f"<pre>{html.escape(reason[:800])}</pre>"
    )
