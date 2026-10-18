"""Telegram bot: owner notifications plus a tiny task inbox.

- any text message → new task in the current project
- /project [slug] — show or switch the current project
- /tasks — active tasks, /stage — what is on stage, /release — ship to prod
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
CURRENT_PROJECT_KEY = "telegram_current_project"

#: Bot menu, pushed to Telegram on API start so it never drifts from the handlers.
COMMANDS = [
    ("tasks", "Задачи в работе"),
    ("stage", "Что уже на stage"),
    ("project", "Текущий проект / переключить"),
    ("release", "Выкатить stage в прод"),
    ("help", "Как пользоваться"),
]
#: Names from the v1 bot, still accepted so old habits keep working.
ALIASES = {"/status": "/tasks", "/staging": "/stage"}

STATUS_EMOJI = {
    "queued": "⏳",
    "in_progress": "🛠",
    "ci": "🧪",
    "deploying": "🚚",
    "on_stage": "✅",
    "released": "🚀",
    "failed": "❌",
    "cancelled": "⏹",
}


async def get_telegram_settings() -> dict:
    """Get Telegram settings from database."""
    from autodev.api.database import SessionLocal
    from autodev.core.models import Setting

    async with SessionLocal() as session:
        result = await session.execute(select(Setting))
        settings = {s.key: s.value for s in result.scalars().all()}

    return {
        "token": settings.get("telegram_bot_token", ""),
        "chat_id": settings.get("telegram_owner_chat_id", ""),
        "secret": settings.get("telegram_webhook_secret", ""),
        "project": settings.get(CURRENT_PROJECT_KEY, ""),
    }


def _esc(text: str) -> str:
    return html.escape(text or "")


class TelegramPMBot:
    """Telegram bot bound to the owner's chat."""

    def __init__(self, token: str = "", owner_chat_id: str = "", current_project: str = "") -> None:
        self.token = token
        self.owner_chat_id = owner_chat_id
        self.current_project = current_project
        self._client: httpx.AsyncClient | None = None

    @classmethod
    async def from_settings(cls) -> TelegramPMBot:
        settings = await get_telegram_settings()
        return cls(token=settings["token"], owner_chat_id=settings["chat_id"], current_project=settings["project"])

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(base_url=f"{TELEGRAM_API}/bot{self.token}", timeout=30.0)
        return self._client

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            resp = await self.client.post("/sendMessage", data=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Telegram sendMessage failed: %s", e)
            return {}

    async def send_photo(self, chat_id: str, photo: bytes, caption: str) -> dict:
        """Photo with an HTML caption (Telegram caps captions at 1024 chars)."""
        try:
            resp = await self.client.post(
                "/sendPhoto",
                data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
                files={"photo": ("stage.png", photo, "image/png")},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Telegram sendPhoto failed: %s", e)
            return {}

    async def answer_callback_query(self, callback_id: str, text: str = "") -> None:
        try:
            await self.client.post("/answerCallbackQuery", data={"callback_query_id": callback_id, "text": text})
        except Exception as e:
            logger.error("Telegram answerCallbackQuery failed: %s", e)

    async def edit_message_text(self, chat_id: str, message_id: int, text: str) -> None:
        try:
            await self.client.post(
                "/editMessageText",
                data={"chat_id": chat_id, "message_id": message_id, "text": text[:4000], "parse_mode": "HTML"},
            )
        except Exception as e:
            logger.error("Telegram editMessageText failed: %s", e)

    # ------------------------------------------------------------------
    # Incoming updates
    # ------------------------------------------------------------------

    async def handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if chat_id != self.owner_chat_id:
            await self.send_message(chat_id, "⛔ Доступ только для владельца")
            return

        if text.startswith("/"):
            await self._handle_command(chat_id, text)
        else:
            await self._create_task(chat_id, text)

    async def _handle_command(self, chat_id: str, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lower().split("@")[0]
        cmd = ALIASES.get(cmd, cmd)
        arg = arg.strip()
        if cmd in ("/start", "/help"):
            await self.send_message(
                chat_id,
                "👋 <b>AutoDev</b>\n\n"
                "Напиши задачу обычным сообщением — она уйдёт в работу в текущем проекте.\n"
                "Первая строка станет заголовком.\n\n"
                "/project — текущий проект (/project <i>slug</i> — переключить)\n"
                "/tasks — задачи в работе\n"
                "/stage — что уже на stage\n"
                "/release — выкатить stage в прод",
            )
        elif cmd == "/project":
            await self._project(chat_id, arg)
        elif cmd == "/tasks":
            await self._show_tasks(chat_id)
        elif cmd == "/stage":
            await self._show_stage(chat_id)
        elif cmd == "/release":
            await self._ask_release(chat_id)
        else:
            await self.send_message(chat_id, f"❓ Неизвестная команда {_esc(cmd)}. /help")

    async def _resolve_project(self, session):
        from autodev.core.models import Project

        projects = list(
            (await session.execute(select(Project).where(Project.enabled).order_by(Project.name))).scalars()
        )
        current = next((p for p in projects if p.id == self.current_project), None)
        if current is None and len(projects) == 1:
            current = projects[0]
        return current, projects

    async def _project(self, chat_id: str, slug: str) -> None:
        from autodev.api.database import SessionLocal
        from autodev.core.models import Setting

        async with SessionLocal() as session:
            current, projects = await self._resolve_project(session)
            if slug:
                match = next((p for p in projects if p.id == slug), None)
                if match is None:
                    await self.send_message(chat_id, f"Нет проекта <code>{_esc(slug)}</code>")
                    return
                setting = await session.get(Setting, CURRENT_PROJECT_KEY)
                if setting is None:
                    session.add(Setting(key=CURRENT_PROJECT_KEY, value=slug))
                else:
                    setting.value = slug
                await session.commit()
                self.current_project = slug
                current = match
        names = "\n".join(
            f"{'👉' if current and p.id == current.id else '•'} <code>{p.id}</code> {_esc(p.name)}" for p in projects
        )
        await self.send_message(chat_id, f"Проекты:\n{names or '—'}")

    async def _create_task(self, chat_id: str, text: str) -> None:
        from autodev.api.database import SessionLocal
        from autodev.core.models import Task, TaskStatus

        async with SessionLocal() as session:
            project, projects = await self._resolve_project(session)
            if project is None:
                await self.send_message(
                    chat_id, "Сначала выбери проект: " + ", ".join(f"/project {p.id}" for p in projects)
                )
                return
            title, _, rest = text.partition("\n")
            title = title.strip()
            task = Task(
                title=title[:200],
                description=rest.strip() or (title if len(title) > 200 else ""),
                project_id=project.id,
                repo=project.repos[0]["name"],
                created_by="telegram",
                status=TaskStatus.QUEUED,
                metadata_={},
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

        await self.send_message(chat_id, f"⏳ #{task.ticket_number} <b>{_esc(task.title)}</b> → {_esc(project.name)}")

    async def _show_tasks(self, chat_id: str) -> None:
        from autodev.api.database import SessionLocal
        from autodev.core.models import Task, TaskStatus

        active = [TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.CI, TaskStatus.DEPLOYING, TaskStatus.FAILED]
        async with SessionLocal() as session:
            rows = await session.execute(
                select(Task).where(Task.status.in_(active)).order_by(Task.status_changed_at.desc()).limit(20)
            )
            tasks = list(rows.scalars())
        if not tasks:
            await self.send_message(chat_id, "Пусто — всё сделано 🎉")
            return
        lines = [f"{STATUS_EMOJI.get(t.status, '•')} #{t.ticket_number} {_esc(t.title[:60])}" for t in tasks]
        await self.send_message(chat_id, "\n".join(lines))

    async def _show_stage(self, chat_id: str) -> None:
        from autodev.api.database import SessionLocal
        from autodev.core.models import Project, Task, TaskStatus

        async with SessionLocal() as session:
            rows = await session.execute(
                select(Task).where(Task.status == TaskStatus.ON_STAGE).order_by(Task.project_id, Task.ticket_number)
            )
            tasks = list(rows.scalars())
            projects = {p.id: p for p in (await session.execute(select(Project))).scalars()}
        if not tasks:
            await self.send_message(chat_id, "На stage нет невыпущенных задач")
            return
        # Follow-ups are checked with their main task: one line for the main task.
        from autodev import review

        listed = {t.id for t in tasks}
        folded = {t.id for t in tasks if t.parent_id in listed and review.checked_with_main(t)}
        extra: dict = {}
        for t in tasks:
            if t.id in folded:
                extra[t.parent_id] = extra.get(t.parent_id, 0) + 1
        tasks = [t for t in tasks if t.id not in folded]
        text, current = "", None
        for t in tasks:
            if t.project_id != current:
                current = t.project_id
                project = projects.get(current)
                url = f' — <a href="{_esc(project.stage_url)}">stage</a>' if project and project.stage_url else ""
                text += f"\n<b>{_esc(project.name if project else current or '?')}</b>{url}\n"
            mark = "✅" if (t.metadata_ or {}).get("verified_at") else "👀"
            more = f" <i>+{extra[t.id]} доработ.</i>" if t.id in extra else ""
            text += f"{mark} #{t.ticket_number} {_esc(t.title[:60])}{more}\n"
        await self.send_message(chat_id, text.strip() + "\n\n✅ проверено · 👀 ждёт проверки")

    async def _ask_release(self, chat_id: str) -> None:
        from autodev.api.database import SessionLocal

        async with SessionLocal() as session:
            project, _ = await self._resolve_project(session)
        if project is None:
            await self.send_message(chat_id, "Сначала выбери проект: /project <i>slug</i>")
            return
        await self.send_message(
            chat_id,
            f"🚀 Выкатить <b>{_esc(project.name)}</b> ({_esc(project.base_branch)} → {_esc(project.prod_branch)})?",
            reply_markup={"inline_keyboard": [[{"text": "🚀 Да, в прод", "callback_data": f"rel:{project.id}"}]]},
        )

    async def _handle_callback(self, callback: dict) -> None:
        callback_id = callback.get("id", "")
        data = callback.get("data", "")
        message = callback.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        message_id = message.get("message_id", 0)
        if chat_id != self.owner_chat_id:
            await self.answer_callback_query(callback_id, "⛔")
            return

        action, _, arg = data.partition(":")
        if action == "ok":
            await self._verify_from_callback(callback_id, chat_id, message_id, arg)
            return
        if action != "rel":
            await self.answer_callback_query(callback_id)
            return

        from autodev.api.database import SessionLocal
        from autodev.core.config import get_settings
        from autodev.core.models import Project
        from autodev.integrations.github import GitHubClient
        from autodev.release import ReleaseError, start_release

        async with SessionLocal() as session:
            project = await session.get(Project, arg)
            if project is None:
                await self.answer_callback_query(callback_id, "Проект не найден")
                return
            try:
                async with GitHubClient(token=get_settings().github_token) as gh:
                    release = await start_release(session, gh, project, by="telegram")
            except (ReleaseError, httpx.HTTPError) as exc:
                await self.answer_callback_query(callback_id, "Не получилось")
                await self.edit_message_text(chat_id, message_id, f"⚠️ {_esc(str(exc)[:500])}")
                return
        prs = "\n".join(
            f'<a href="{_esc(p["pr_url"])}">{_esc(p["repo"])}#{p["pr_number"]}</a>' for p in release.release_prs or []
        )
        await self.answer_callback_query(callback_id, "Поехали")
        await self.edit_message_text(
            chat_id, message_id, f"🚀 Релиз {_esc(release.version)} запущен — смержу, когда пройдут проверки.\n{prs}"
        )

    async def _verify_from_callback(self, callback_id: str, chat_id: str, message_id: int, task_id: str) -> None:
        import uuid

        from autodev import notify, review
        from autodev.api.database import SessionLocal
        from autodev.core.models import MERGED_STATUSES, Task

        async with SessionLocal() as session:
            try:
                task = await session.get(Task, uuid.UUID(task_id), with_for_update=True)
            except ValueError:
                task = None
            if task is None:
                await self.answer_callback_query(callback_id, "Задача не найдена")
                return
            waiting = (await review.waiting_children(session, {task.id})).get(task.id, [])
            try:
                review.set_verified(task, True, waiting)
            except review.ReviewError as exc:
                text = "Задача уже не на stage" if task.status not in MERGED_STATUSES else str(exc)
                await self.answer_callback_query(callback_id, text[:190])
                return
            await session.commit()
        await self.answer_callback_query(callback_id, "Отмечено")
        await self.edit_message_text(chat_id, message_id, notify.test_plan_text(task) + "\n\n✅ <b>Проверено</b>")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()


async def sync_commands() -> None:
    """Replace the bot's command menu with COMMANDS. Never raises."""
    bot = await get_telegram_bot()
    try:
        if not bot.token:
            return
        resp = await bot.client.post(
            "/setMyCommands",
            json={"commands": [{"command": c, "description": d} for c, d in COMMANDS]},
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error("Telegram setMyCommands failed: %s", e)
    finally:
        await bot.close()


async def get_telegram_bot() -> TelegramPMBot:
    """Get Telegram bot from settings."""
    return await TelegramPMBot.from_settings()


async def notify_owner(text: str, photo: bytes | None = None, reply_markup: dict | None = None) -> bool:
    """Send an HTML message (optionally with a photo) to the owner chat. Returns True if delivered."""
    bot = await get_telegram_bot()
    try:
        if not bot.token or not bot.owner_chat_id:
            return False
        if photo and not reply_markup and len(text) <= 1024 and await bot.send_photo(bot.owner_chat_id, photo, text):
            return True
        return bool(await bot.send_message(bot.owner_chat_id, text, reply_markup=reply_markup))
    finally:
        await bot.close()
