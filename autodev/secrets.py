"""Secrets of deployed projects: the owner types them in the dashboard, the cluster gets them sealed.

Repos the cluster deploys (:func:`autodev.scaffold.deployed`) carry ``deploy/secrets.yaml``:
``secretEnv.<stage|prod>.<NAME>`` = the value sealed for the namespace ``p-<repo>-<env>`` and the
Secret ``app-secrets`` (hetzner-gitops: charts/project). The chart turns it into a SealedSecret
that reaches the app as env. Only the controller's private key opens it, so the file is plain
repo content: the same on the stage and prod branches, and the agent may read it (names only).
"""

from __future__ import annotations

import base64
import os
import re
import struct

import httpx
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from autodev import scaffold
from autodev.core.config import Settings
from autodev.core.models import Project
from autodev.integrations.github import GitHubClient

PATH = "deploy/secrets.yaml"
SECRET_NAME = "app-secrets"
ENVS = ("stage", "prod")
NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
# Set by the platform; a secret of the same name would be silently shadowed by them.
RESERVED = {"PORT", "GIT_SHA", "APP_ENV", "PUBLIC_URL", "DATABASE_URL"}

HEADER = """\
# Managed by AutoDev (dashboard: project → Secrets). Don't edit by hand.
# secretEnv.<env>.<NAME>: sealed for namespace p-<repo>-<env>, Secret app-secrets;
# the app gets each one as env NAME.
"""


class SecretError(Exception):
    pass


def namespace(repo: str, env: str) -> str:
    return f"p-{repo.split('/', 1)[1].lower()}-{env}"


def seal(value: str, cert_pem: bytes, namespace: str, name: str = SECRET_NAME) -> str:
    """Encrypt *value* the way ``kubeseal --raw --scope strict`` does.

    A random AES-256-GCM session key (zero nonce: it is used once) encrypts the value; the
    session key goes RSA-OAEP(SHA-256) under the controller's key with ``namespace/name`` as
    the label, which binds the ciphertext to that Secret.
    """
    key = x509.load_pem_x509_certificate(cert_pem).public_key()
    if not isinstance(key, RSAPublicKey):
        raise SecretError("sealed-secrets certificate is not RSA")
    session = os.urandom(32)
    label = f"{namespace}/{name}".encode()
    wrapped = key.encrypt(
        session, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=label)
    )
    body = AESGCM(session).encrypt(b"\0" * 12, value.encode(), None)
    return base64.b64encode(struct.pack(">H", len(wrapped)) + wrapped + body).decode()


def parse(text: str) -> dict[str, dict[str, str]]:
    data = (yaml.safe_load(text) or {}).get("secretEnv") or {}
    return {env: dict(data.get(env) or {}) for env in ENVS}


def render(secrets: dict[str, dict[str, str]]) -> str:
    data = {"secretEnv": {env: dict(sorted(secrets[env].items())) for env in ENVS}}
    return HEADER + yaml.safe_dump(data, sort_keys=False, width=1_000_000)


async def names(gh: GitHubClient, project: Project) -> dict[str, list[str]]:
    current = await gh.get_file(PATH, project.base_branch, project.repo()["name"])
    secrets = parse(current[0] if current else "")
    return {env: sorted(secrets[env]) for env in ENVS}


async def update(
    gh: GitHubClient, project: Project, env: str, name: str, value: str | None, settings: Settings
) -> dict[str, list[str]]:
    """Set (or, with *value* None, remove) *name* in *env*; commit to the stage and prod branches.

    Both branches get the same file, so the stage→prod release merge never conflicts on it.
    The commits start the image build: the new revision rolls out with the secret in place.
    """
    if env not in ENVS:
        raise SecretError(f"env must be one of {', '.join(ENVS)}")
    if not NAME.match(name) or name in RESERVED:
        raise SecretError(f"{name}: a name like STRIPE_KEY (A-Z, 0-9, _), not {', '.join(sorted(RESERVED))}")
    repo = project.repo()["name"]
    current = await gh.get_file(PATH, project.base_branch, repo)
    secrets = parse(current[0] if current else "")
    if value is None:
        if secrets[env].pop(name, None) is None:
            raise LookupError(name)
        message = f"chore(secrets): remove {name} ({env})"
    else:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get(settings.sealed_secrets_cert_url)
            response.raise_for_status()
        secrets[env][name] = seal(value, response.content, namespace(repo, env))
        message = f"chore(secrets): set {name} ({env})"

    content = render(secrets)
    for branch in dict.fromkeys((project.base_branch, project.prod_branch)):
        existing = current if branch == project.base_branch else await gh.get_file(PATH, branch, repo)
        if existing and existing[0] == content:
            continue
        await gh.put_file(PATH, content, message, branch, repo, sha=existing[1] if existing else None)
        await scaffold.build_image(gh, repo, branch, settings)
    return {env: sorted(secrets[env]) for env in ENVS}
