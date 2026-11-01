"""Owner's secrets for deployed projects: sealing and the deploy/secrets.yaml commits."""

from __future__ import annotations

import base64
import datetime
import struct

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

from autodev import secrets
from autodev.core.config import get_settings
from autodev.core.models import Project

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _cert() -> bytes:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sealed-secret")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(KEY.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(KEY, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


CERT = _cert()


def _unseal(ciphertext: str, label: str) -> str:
    """The controller's side of ``kubeseal --scope strict`` (sealed-secrets crypto.HybridDecrypt)."""
    raw = base64.b64decode(ciphertext)
    (n,) = struct.unpack(">H", raw[:2])
    session = KEY.decrypt(
        raw[2 : 2 + n],
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=label.encode()),
    )
    return AESGCM(session).decrypt(b"\0" * 12, raw[2 + n :], None).decode()


def test_seal_is_bound_to_namespace_and_name() -> None:
    sealed = secrets.seal("sk_live_1", CERT, "p-notes-stage")
    assert _unseal(sealed, "p-notes-stage/app-secrets") == "sk_live_1"
    with pytest.raises(ValueError):
        _unseal(sealed, "p-other-stage/app-secrets")


def test_render_parse_roundtrip() -> None:
    data = {"stage": {"B": "y", "A": "x"}, "prod": {}}
    text = secrets.render(data)
    assert text.startswith("# Managed by AutoDev")
    assert secrets.parse(text) == data
    assert secrets.parse("") == {"stage": {}, "prod": {}}


class FakeFilesGitHub:
    """GitHub contents API over an in-memory {(branch, path): content}."""

    def __init__(self, files: dict[tuple[str, str], str] | None = None) -> None:
        self.files = dict(files or {})
        self.commits: list[tuple[str, str]] = []
        self.dispatched: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get_file(self, path, ref, repo=None):
        content = self.files.get((ref, path))
        return None if content is None else (content, f"sha-{ref}")

    async def put_file(self, path, content, message, branch, repo=None, sha=None):
        assert sha == (f"sha-{branch}" if (branch, path) in self.files else None)
        self.files[(branch, path)] = content
        self.commits.append((branch, message))
        return "c1"

    async def dispatch_workflow(self, workflow, ref, repo=None):
        self.dispatched.append(ref)


@pytest.fixture
def deployed(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "projects_org", "Apps-Org")
    monkeypatch.setattr(settings, "apps_domain", "example.com")

    class Response:
        content = CERT

        def raise_for_status(self):
            return None

    class Http:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            assert url == settings.sealed_secrets_cert_url
            return Response()

    monkeypatch.setattr(secrets.httpx, "AsyncClient", Http)
    return settings


def _project() -> Project:
    return Project(
        id="notes", name="Notes", repos=[{"name": "Apps-Org/Notes"}], base_branch="stage", prod_branch="main"
    )


async def test_update_commits_the_same_file_to_both_branches(deployed) -> None:
    gh = FakeFilesGitHub()
    names = await secrets.update(gh, _project(), "prod", "STRIPE_KEY", "sk_live_1", deployed)
    assert names == {"stage": [], "prod": ["STRIPE_KEY"]}
    assert gh.files[("stage", secrets.PATH)] == gh.files[("main", secrets.PATH)]
    sealed = secrets.parse(gh.files[("main", secrets.PATH)])["prod"]["STRIPE_KEY"]
    assert _unseal(sealed, "p-notes-prod/app-secrets") == "sk_live_1"
    assert [b for b, _ in gh.commits] == ["stage", "main"]
    assert gh.dispatched == ["stage", "main"]  # the image rebuild rolls the secret out

    # A branch that already has this content is not committed to again.
    gh.files[("main", secrets.PATH)] = secrets.render({"stage": {"X": "1"}, "prod": {}})
    gh.files[("stage", secrets.PATH)] = gh.files[("main", secrets.PATH)]
    gh.commits.clear()
    await secrets.update(gh, _project(), "stage", "X", None, deployed)
    assert secrets.parse(gh.files[("main", secrets.PATH)]) == {"stage": {}, "prod": {}}
    assert len(gh.commits) == 2

    with pytest.raises(LookupError):
        await secrets.update(gh, _project(), "stage", "X", None, deployed)


@pytest.mark.parametrize(
    ("env", "name"), [("dev", "A"), ("stage", "lower"), ("stage", "DATABASE_URL"), ("stage", "1A")]
)
async def test_update_rejects_bad_names(deployed, env, name) -> None:
    with pytest.raises(secrets.SecretError):
        await secrets.update(FakeFilesGitHub(), _project(), env, name, "v", deployed)


async def test_secrets_endpoints(client, deployed, monkeypatch) -> None:
    import autodev.api.routes.projects as projects_mod

    gh = FakeFilesGitHub()
    monkeypatch.setattr(projects_mod, "GitHubClient", lambda token: gh)

    plain = {"id": "blog", "name": "Blog", "repos": [{"name": "someone/blog"}]}
    assert (await client.post("/api/projects/", json=plain)).status_code == 201
    assert (await client.get("/api/projects/blog/secrets")).json() == {"deployed": False, "stage": [], "prod": []}
    r = await client.put("/api/projects/blog/secrets/stage/A", json={"value": "1"})
    assert r.status_code == 409

    body = {"id": "notes", "name": "Notes", "repos": [{"name": "Apps-Org/notes"}]}
    assert (await client.post("/api/projects/", json=body)).status_code == 201
    r = await client.put("/api/projects/notes/secrets/stage/OPENAI_KEY", json={"value": "sk-1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"deployed": True, "stage": ["OPENAI_KEY"], "prod": []}
    assert (await client.get("/api/projects/notes/secrets")).json()["stage"] == ["OPENAI_KEY"]
    assert "sk-1" not in gh.files[("stage", secrets.PATH)]

    assert (await client.put("/api/projects/notes/secrets/stage/bad", json={"value": "1"})).status_code == 422
    assert (await client.delete("/api/projects/notes/secrets/prod/OPENAI_KEY")).status_code == 404
    r = await client.delete("/api/projects/notes/secrets/stage/OPENAI_KEY")
    assert r.json() == {"deployed": True, "stage": [], "prod": []}
