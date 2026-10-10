"""Dashboard smoke test against a running dashboard + API (see README).

    python e2e/smoke.py http://localhost:3100 [screenshot_dir]

Uses an iPhone-sized viewport. Expects projects 'alerter' (2 repos, disabled so no
worker picks tasks up) to exist; creates its own tasks.
"""

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1].rstrip("/")
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
errors: list[str] = []
RUN = str(int(time.time()))[-6:]
TITLE = f"E2E {RUN}: кнопка экспорта в CSV"


def shot(page, name):
    if SHOTS:
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)


with sync_playwright() as p:
    browser = p.chromium.launch()
    for scheme in ("light", "dark"):
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            color_scheme=scheme,
        )
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))

        # Board
        page.goto(BASE + "/")
        expect(page.get_by_role("button", name="Задача")).to_be_visible()
        expect(page.get_by_text("Воркер не на связи").or_(page.get_by_text("Свободен"))).to_be_visible()
        page.get_by_role("button", name=re.compile("^В работе")).click()
        shot(page, f"{scheme}-board")

        if scheme == "light":
            # Create a task from the FAB
            page.get_by_role("button", name="Задача").click()
            dialog = page.get_by_role("dialog", name="Новая задача")
            expect(dialog).to_be_visible()
            dialog.locator("textarea").fill(f"{TITLE}\nНа странице алертов, рядом с фильтрами")
            dialog.locator("select").first.select_option("alerter")
            expect(dialog.get_by_text("Авто — агент решит сам")).to_be_attached()
            shot(page, "light-new-task")
            dialog.get_by_role("button", name="В работу").click()
            expect(dialog).to_be_hidden()
            card = page.get_by_role("link", name=re.compile(re.escape(TITLE)))
            expect(card).to_be_visible()  # board switched to the queue tab

            # Task page: actions
            card.click()
            expect(page.get_by_role("heading", name=TITLE)).to_be_visible()
            expect(page.get_by_text("На странице алертов, рядом с фильтрами")).to_be_visible()
            page.once("dialog", lambda d: d.accept())
            page.get_by_role("button", name="Стоп").click()
            expect(page.get_by_text("Отменена").first).to_be_visible()
            page.get_by_role("button", name="Повторить").click()
            expect(page.get_by_text("В очереди").first).to_be_visible()
            expect(
                page.get_by_text("queued → cancelled").or_(page.get_by_text("cancelled → queued")).first
            ).to_be_visible(timeout=10000)
            shot(page, "light-task-new")

        # Task with a summary (on stage) and one with a live log
        page.goto(BASE + "/")
        page.get_by_role("button", name=re.compile("^На stage")).click()
        page.get_by_role("link", name=re.compile("Добавь поиск по имени")).click()
        expect(page.get_by_text("Что сделал агент")).to_be_visible()
        expect(page.get_by_text("На stage есть проблемы")).to_be_visible()
        expect(page.get_by_role("img", name=re.compile("autodev-sandbox"))).to_be_visible()
        expect(page.get_by_role("button", name="Открыть stage")).to_be_visible()
        shot(page, f"{scheme}-task-stage")

        page.goto(BASE + "/")
        page.get_by_role("button", name=re.compile("^Ошибки")).click()
        page.get_by_role("link", name=re.compile("Тёмная тема")).click()
        expect(page.get_by_text("Что пошло не так")).to_be_visible()
        shot(page, f"{scheme}-task-failed")

        page.goto(BASE + "/")
        page.get_by_role("button", name=re.compile("^В работе")).click()
        page.get_by_role("link", name=re.compile("Починить падение")).click()
        expect(page.get_by_text("Run frontend unit tests")).to_be_visible()
        page.get_by_text("Нашёл причину").click()
        shot(page, f"{scheme}-task-log")

        # Projects
        page.get_by_role("link", name="Проекты").click()
        expect(page.get_by_text("Great Alerter")).to_be_visible()
        shot(page, f"{scheme}-projects")
        page.get_by_text("Great Alerter").click()
        expect(page.get_by_text("Релиз в прод")).to_be_visible()
        expect(page.get_by_text("Попадут в релиз")).to_be_visible()
        shot(page, f"{scheme}-project")
        page.get_by_role("button", name="Настройки проекта").click()
        expect(page.get_by_text("Репозитории")).to_be_visible()

        # Settings
        page.get_by_role("link", name="Настройки").click()
        expect(page.get_by_text("Telegram", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("Приостановить|Возобновить"))).to_be_visible()
        shot(page, f"{scheme}-settings")
        ctx.close()

    # Desktop board
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(BASE + "/")
    expect(page.get_by_role("heading", name="CI и деплой")).to_be_visible()
    shot(page, "desktop-board")
    browser.close()

if errors:
    print("\n".join(errors))
    sys.exit(1)
print("e2e ok")
