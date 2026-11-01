"""Projects started from scratch: the deploy contract and the first task.

Repos in the projects organization (``AUTODEV_PROJECTS_ORG``) are deployed by the
cluster with one shared chart (hetzner-gitops: ``charts/project``): a repo with
``deploy/values.yaml`` gets a stage (branch stage) and a prod (branch main), each
running ``ghcr.io/<org>/<repo>:<sha of the branch head>``. This module holds what
a new repo needs to fit that: the image workflow committed at creation and the
scaffold task that tells the agent the rest of the contract.
"""

from __future__ import annotations

import logging

import httpx

from autodev.core.config import Settings
from autodev.integrations.github import GitHubClient

logger = logging.getLogger(__name__)

IMAGE_WORKFLOW_PATH = ".github/workflows/image.yml"

# Committed with the repo: builds the image the cluster deploys. Skips until the
# scaffold task adds a Dockerfile.
IMAGE_WORKFLOW = """\
# Managed by AutoDev: the cluster deploys ghcr.io/<org>/<repo>:<sha> of the stage and
# main heads (stage -> https://<repo>.stage..., main -> https://<repo>.prod...).
name: Image

# AutoDev also starts it by hand (workflow_dispatch) after merging into stage or main:
# push events don't reliably start workflows in the projects organization.
on:
  push:
    branches: [stage, main]
  workflow_dispatch:

# A push run and AutoDev's dispatch for the same commit don't race; the second is a cached rebuild.
concurrency:
  group: image-${{ github.sha }}

permissions:
  contents: read
  packages: write

jobs:
  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: image
        run: |
          if [ -f Dockerfile ]; then
            echo "tag=ghcr.io/${GITHUB_REPOSITORY,,}:${GITHUB_SHA}" >> "$GITHUB_OUTPUT"
          else
            echo "No Dockerfile yet — nothing to build"
          fi
      - if: steps.image.outputs.tag
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - if: steps.image.outputs.tag
        uses: docker/setup-buildx-action@v3
      - if: steps.image.outputs.tag
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ steps.image.outputs.tag }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
"""


IMAGE_WORKFLOW_FILE = IMAGE_WORKFLOW_PATH.rsplit("/", 1)[1]


async def build_image(gh: GitHubClient, repo: str, branch: str, settings: Settings) -> bool:
    """Start the image build for *branch* of a deployed repo. False if not applicable or refused."""
    if not deployed(repo, settings):
        return False
    try:
        await gh.dispatch_workflow(IMAGE_WORKFLOW_FILE, branch, repo)
    except httpx.HTTPStatusError as exc:  # no workflow (yet) or no dispatch trigger in it
        logger.warning("image build for %s@%s refused: %s", repo, branch, exc.response.text[:200])
        return False
    return True


def deployed(repo: str, settings: Settings) -> bool:
    """True if the cluster deploys *repo* (it is in the projects organization)."""
    owner = repo.split("/", 1)[0]
    return bool(settings.projects_org and settings.apps_domain) and owner.lower() == settings.projects_org.lower()


def stage_url(repo: str, settings: Settings) -> str:
    return f"https://{repo.split('/', 1)[1].lower()}.stage.{settings.apps_domain}"


# What every task in a deployed repo should know beyond its CLAUDE.md (repos scaffolded
# before secrets and extraManifests existed don't describe them).
PLATFORM_NOTES = """\
Секреты и доп. сервисы (платформа, hetzner-gitops charts/project):
- Секреты приходят в env. Ключи от владельца (API-ключи и т.п.) он вводит в дашборде AutoDev; их имена —
  в `deploy/secrets.yaml` (значения зашифрованы, файл не редактируй). Нужен ключ, которого там нет, — читай
  его из env, без него приложение не должно падать, и напиши в итоге, какой секрет владельцу добавить.
- Секрет, который можно сгенерировать (ключ подписи сессий и т.п.), добавь сам в `deploy/values-stage.yaml`
  и `deploy/values-prod.yaml`, свой для каждого окружения: `secretEnv: {<env>: {NAME: <шифртекст>}}`,
  шифртекст — `openssl rand -hex 32 | tr -d '\\n' | kubeseal --raw --scope strict --namespace p-<repo>-<env>
  --name app-secrets`. Открытым текстом секреты в репозиторий не клади.
- Нужен ещё сервис (ClickHouse, Redis, фоновый воркер, CronJob) — опиши его манифестами в `extraManifests`
  в `deploy/values.yaml`: StatefulSet/Deployment, Service (ClusterIP), ConfigMap, PVC, CronJob. Ingress
  нельзя: наружу отвечает только приложение. Задавай `resources`; квота namespace маленькая (2 CPU, 2Gi
  на всё) — если не влезает, напиши в итоге, что владельцу нужно поднять квоту.
"""


def task_description(brief: str, with_deploy: bool) -> str:
    lines = [
        brief.strip(),
        "",
        "---",
        "Репозиторий только что создан и пуст. Это первая задача проекта — заложи основу:",
        "- выбери стек (если в описании его нет — простой и распространённый) и сделай рабочую первую версию "
        "описанного;",
        "- README: что это и как запустить локально;",
        "- CLAUDE.md: стек, структура, команды запуска, тестов и линтеров, соглашения — по нему будут работать "
        "следующие задачи;",
        "- тесты и линтер, и чтобы они проходили;",
        "- GitHub Actions workflow, который запускает их на pull_request: CI проверяет каждый PR перед авто-merge;",
        "- .gitignore.",
        "Cookie — только host-only, без атрибута Domain, а сессионные — с префиксом __Host- (Secure, Path=/): "
        "stage и прод живут на соседних поддоменах одного домена. Запиши это правило в CLAUDE.md.",
    ]
    if with_deploy:
        lines += [
            "",
            "Деплой уже настроен платформой — подстройся под её контракт и опиши его в CLAUDE.md:",
            "- один `Dockerfile` в корне собирает всё приложение в один образ (если есть фронт и бэк — бэк "
            "отдаёт собранный фронт); образ собирает уже лежащий в репо `.github/workflows/image.yml`, не меняй его;",
            "- контейнер слушает порт из env `PORT` (8000), `GET /healthz` отвечает 200, `GET /version` отдаёт "
            '`{"sha": "<env GIT_SHA>"}` — по нему проверяется, что коммит доехал до stage;',
            "- в env также приходят `APP_ENV` (stage / prod) и `PUBLIC_URL`; нужна БД — Postgres, адрес в env "
            "`DATABASE_URL`;",
            "- создай `deploy/values.yaml` — с ним проект начинает деплоиться. Возможные ключи: "
            "`port`, `healthPath`, `env` (KEY: value), `migrate.command` (список: команда миграций), "
            "`postgres.enabled` (true, если нужна БД), `resources`. Отличия prod — в `deploy/values-prod.yaml`.",
            "- миграции БД — через `migrate.command`: платформа запускает их отдельным Job один раз на деплой, "
            "после базы и до новой версии приложения; упали — деплой останавливается, работает старая версия. "
            "Миграции делай обратно совместимыми (expand/contract): пока поднимается новая версия, старая ещё "
            "работает с уже мигрированной схемой. Нельзя в одном изменении переименовать или удалить колонку, "
            "которую читает текущий код, — сначала добавь новое и перейди на него, удаляй старое следующим "
            "изменением. Запиши это правило в CLAUDE.md.",
            "Секреты в репозиторий не клади.",
            "",
            PLATFORM_NOTES.rstrip(),
            "Опиши это в CLAUDE.md тоже.",
        ]
    else:
        lines.append("Деплой на stage не настраивай, если об этом не сказано выше.")
    return "\n".join(lines)
