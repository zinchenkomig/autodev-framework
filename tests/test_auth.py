"""Dashboard login: htpasswd hashes, the session cookie and Traefik's forwardAuth check."""

from __future__ import annotations

import base64
import subprocess

import pytest

from autodev.api.routes import auth
from autodev.core.config import get_settings

HTPASSWD = (
    "owner:$apr1$Xy12AbCd$pGW088dW4e/.JHfhD3JgY1\n"  # openssl passwd -apr1 -salt Xy12AbCd 'пароль 123'
    "bot:$2y$05$HzpGY.kP09PGv/go9dIR6.ZGOtVE4fCNACXaIpEjd73Xi/DpeyxeK\n"  # htpasswd -nbB bot secret
    "old:{SHA}5en6G6MezRroT3XKqkdPOmY/BfQ=\n"  # htpasswd -nbs old secret
)


@pytest.fixture
def htpasswd(tmp_path, monkeypatch):
    path = tmp_path / "htpasswd"
    path.write_text(HTPASSWD)
    monkeypatch.setattr(get_settings(), "htpasswd", str(path))
    return path


@pytest.mark.parametrize(
    "user,password,ok",
    [
        ("owner", "пароль 123", True),
        ("owner", "пароль", False),
        ("bot", "secret", True),
        ("bot", "Secret", False),
        ("old", "secret", True),
        ("nobody", "secret", False),
    ],
)
def test_verify(user, password, ok) -> None:
    assert auth.verify(user, password, HTPASSWD.encode()) is ok


def test_session_cookie() -> None:
    data = HTPASSWD.encode()
    cookie = auth.make_session("owner", data, now=1000)
    assert auth.session_user(cookie, data, now=2000) == "owner"
    assert auth.session_user(cookie, data, now=1000 + auth.MAX_AGE + 1) is None  # expired
    assert auth.session_user(cookie, data + b"x:{SHA}x\n", now=2000) is None  # password file changed
    forged = base64.urlsafe_b64encode(b"bot").decode().rstrip("=") + cookie[cookie.index(".") :]
    assert auth.session_user(forged, data, now=2000) is None
    assert auth.session_user("garbage", data) is None
    assert auth.session_user(cookie, b"", now=2000) is None  # no htpasswd → nobody


@pytest.mark.parametrize(
    "target,expected",
    [
        ("/inbox", "/inbox"),
        ("/tasks/1?x=1", "/tasks/1?x=1"),
        ("//evil.com", "/"),
        ("https://evil.com", "/"),
        ("/\\evil.com", "/"),
        (None, "/"),
        ("/api/auth/login", "/"),
    ],
)
def test_safe_next(target, expected) -> None:
    assert auth._safe_next(target) == expected


async def test_check_and_login(client, htpasswd) -> None:
    # No session: a page goes to the login form, the API answers 401.
    r = await client.get("/api/auth/check", headers={"X-Forwarded-Uri": "/inbox"})
    assert r.status_code == 302 and r.headers["location"] == "/api/auth/login?next=%2Finbox"
    headers = {"X-Forwarded-Uri": "/inbox", "X-Forwarded-Host": "autodev.example", "X-Forwarded-Proto": "https"}
    r = await client.get("/api/auth/check", headers=headers)
    assert r.headers["location"] == "https://autodev.example/api/auth/login?next=%2Finbox"
    r = await client.get("/api/auth/check", headers={"X-Forwarded-Uri": "/api/tasks/"})
    assert r.status_code == 401 and "www-authenticate" not in r.headers

    # Basic auth still works for scripts.
    basic = "Basic " + base64.b64encode(b"bot:secret").decode()
    assert (await client.get("/api/auth/check", headers={"Authorization": basic})).status_code == 204

    assert "Войти" in (await client.get("/api/auth/login?next=/inbox")).text

    r = await client.post("/api/auth/login", data={"username": "owner", "password": "nope", "next": "/inbox"})
    assert r.status_code == 401 and "Неверный" in r.text and auth.COOKIE not in r.cookies

    r = await client.post("/api/auth/login", data={"username": "owner", "password": "пароль 123", "next": "/inbox"})
    assert r.status_code == 303 and r.headers["location"] == "/inbox"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and f"Max-Age={auth.MAX_AGE}" in cookie

    session = r.cookies[auth.COOKIE]
    r = await client.get("/api/auth/check", headers={"Cookie": f"{auth.COOKIE}={session}"})
    assert r.status_code == 204


def test_hashes_from_htpasswd_tool(tmp_path) -> None:
    """Whatever `htpasswd` writes by default (-m), with -B and with -s."""
    try:
        lines = [
            subprocess.run(["htpasswd", "-nb", flag, "u", "p w"], capture_output=True, text=True, check=True).stdout
            for flag in ("-m", "-B", "-s")
        ]
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("htpasswd not installed")
    for line in lines:
        assert auth.verify("u", "p w", line.encode())
        assert not auth.verify("u", "p", line.encode())
