"""Login for the dashboard: a year-long session cookie instead of basic auth.

Basic auth isn't remembered by an iPhone home-screen app, so the owner had to type
the password on every launch. Traefik now asks ``/api/auth/check`` (forwardAuth)
about every request; it lets through a valid session cookie or basic-auth header
(curl, scripts) and sends a browser without one to the login form.

Credentials are the same htpasswd file the basic-auth middleware used
(``AUTODEV_HTPASSWD``). The cookie is signed with a key derived from that file,
so changing a password signs everyone out.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import time
from pathlib import Path
from urllib.parse import parse_qs, quote

import bcrypt
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from autodev.core.config import get_settings

router = APIRouter()

COOKIE = "autodev_session"
MAX_AGE = 365 * 24 * 3600
LOGIN_PATH = "/api/auth/login"


# ---------------------------------------------------------------------------
# htpasswd
# ---------------------------------------------------------------------------


def _htpasswd() -> bytes:
    path = get_settings().htpasswd
    try:
        return Path(path).read_bytes() if path else b""
    except OSError:
        return b""


def _users(data: bytes) -> dict[str, str]:
    users = {}
    for line in data.decode(errors="replace").splitlines():
        name, sep, hashed = line.strip().partition(":")
        if sep and name and not name.startswith("#"):
            users[name] = hashed
    return users


_ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def apr1(password: str, salt: str) -> str:
    """Apache's MD5 crypt (``htpasswd -m``, the default of ``htpasswd``)."""
    pw, s, magic = password.encode(), salt.encode()[:8], b"$apr1$"
    alt = hashlib.md5(pw + s + pw).digest()
    ctx = hashlib.md5(pw + magic + s)
    for i in range(len(pw), 0, -16):
        ctx.update(alt[: min(16, i)])
    i = len(pw)
    while i:
        ctx.update(b"\0" if i & 1 else pw[:1])
        i >>= 1
    final = ctx.digest()
    for i in range(1000):
        c = hashlib.md5(pw if i & 1 else final)
        if i % 3:
            c.update(s)
        if i % 7:
            c.update(pw)
        c.update(final if i & 1 else pw)
        final = c.digest()

    def to64(v: int, n: int) -> str:
        out = ""
        for _ in range(n):
            out += _ITOA64[v & 0x3F]
            v >>= 6
        return out

    encoded = "".join(
        to64((final[a] << 16) | (final[b] << 8) | final[c], 4)
        for a, b, c in ((0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5))
    )
    encoded += to64(final[11], 2)
    return f"$apr1${s.decode()}${encoded}"


def check_password(hashed: str, password: str) -> bool:
    if hashed.startswith("$apr1$"):
        salt = hashed.split("$")[2]
        return hmac.compare_digest(apr1(password, salt), hashed)
    if hashed.startswith(("$2y$", "$2b$", "$2a$")):
        try:
            return bcrypt.checkpw(password.encode()[:72], ("$2b$" + hashed[4:]).encode())
        except ValueError:
            return False
    if hashed.startswith("{SHA}"):
        digest = base64.b64encode(hashlib.sha1(password.encode()).digest()).decode()
        return hmac.compare_digest("{SHA}" + digest, hashed)
    return False


def verify(user: str, password: str, data: bytes | None = None) -> bool:
    hashed = _users(_htpasswd() if data is None else data).get(user)
    return hashed is not None and check_password(hashed, password)


# ---------------------------------------------------------------------------
# Session cookie: "<user>.<expires>.<signature>"
# ---------------------------------------------------------------------------


def _key(data: bytes) -> bytes:
    return hashlib.sha256(b"autodev-session\0" + data).digest()


def _sign(data: bytes, payload: str) -> str:
    return hmac.new(_key(data), payload.encode(), hashlib.sha256).hexdigest()


def make_session(user: str, data: bytes, now: float | None = None) -> str:
    user_b64 = base64.urlsafe_b64encode(user.encode()).decode().rstrip("=")  # no "=": the cookie stays unquoted
    payload = f"{user_b64}.{int((now or time.time()) + MAX_AGE)}"
    return f"{payload}.{_sign(data, payload)}"


def session_user(value: str, data: bytes, now: float | None = None) -> str | None:
    """The user of a valid, unexpired session that still exists in the htpasswd file."""
    try:
        user_b64, expires, signature = value.split(".")
        user = base64.urlsafe_b64decode(user_b64 + "=" * (-len(user_b64) % 4)).decode()
        if int(expires) < (now or time.time()):
            return None
    except ValueError:
        return None
    if not data or not hmac.compare_digest(_sign(data, f"{user_b64}.{expires}"), signature):
        return None
    return user if user in _users(data) else None


def _basic_ok(header: str | None, data: bytes) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:]).decode().partition(":")
    except ValueError:
        return False
    return verify(user, password, data)


def _safe_next(target: str | None) -> str:
    """Only a path on this site — never another host."""
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")) or target.startswith(LOGIN_PATH):
        return "/"
    return target


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/check", summary="Traefik forwardAuth", include_in_schema=False)
async def check(request: Request) -> Response:
    data = _htpasswd()
    cookie = request.cookies.get(COOKIE)
    if (cookie and session_user(cookie, data)) or _basic_ok(request.headers.get("authorization"), data):
        return Response(status_code=204)
    uri = request.headers.get("x-forwarded-uri", "/")
    if uri.startswith("/api/"):
        return Response(status_code=401, content='{"detail":"Not signed in"}', media_type="application/json")
    return RedirectResponse(f"{LOGIN_PATH}?next={quote(_safe_next(uri), safe='')}", status_code=302)


@router.get("/login", summary="Login form", include_in_schema=False)
async def login_form(next: str = "/") -> HTMLResponse:
    return HTMLResponse(_page(_safe_next(next)))


@router.post("/login", summary="Sign in", include_in_schema=False)
async def login(request: Request) -> Response:
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode(errors="replace")).items()}
    user, target = form.get("username", "").strip(), _safe_next(form.get("next"))
    data = _htpasswd()
    if not verify(user, form.get("password", ""), data):
        await asyncio.sleep(1)  # slow down guessing
        return HTMLResponse(_page(target, user, "Неверный логин или пароль"), status_code=401)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        COOKIE, make_session(user, data), max_age=MAX_AGE, httponly=True, secure=True, samesite="lax", path="/"
    )
    return response


@router.post("/logout", summary="Sign out", include_in_schema=False)
async def logout() -> Response:
    response = RedirectResponse(LOGIN_PATH, status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response


def _page(target: str, user: str = "", error: str = "") -> str:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark"><title>AutoDev — вход</title>
<style>
:root{{--bg:#f6f7f9;--fg:#0f172a;--muted:#64748b;--line:#e2e8f0;--surface:#fff;--accent:#4f46e5;--bad:#dc2626}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1020;--fg:#e2e8f0;--muted:#94a3b8;--line:#1e293b;--surface:#111827;--accent:#818cf8;--bad:#f87171}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100dvh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:16px/1.4 system-ui,-apple-system,sans-serif;padding:16px}}
form{{width:100%;max-width:340px;background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:24px;display:grid;gap:12px}}
h1{{margin:0 0 4px;font-size:20px}}label{{display:grid;gap:6px;font-size:14px;font-weight:500}}
input{{font:inherit;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}}
button{{font:inherit;font-weight:600;padding:12px;border:0;border-radius:12px;background:var(--accent);color:#fff;margin-top:4px}}
.err{{margin:0;color:var(--bad);font-size:14px}}
</style></head><body>
<form method="post" action="{LOGIN_PATH}">
<h1>AutoDev</h1>{err}
<input type="hidden" name="next" value="{html.escape(target)}">
<label>Логин<input id="username" name="username" type="text" autocomplete="username" spellcheck="false" autocapitalize="none" required value="{html.escape(user)}"></label>
<label>Пароль<input id="password" name="password" type="password" autocomplete="current-password" required></label>
<button type="submit">Войти</button>
</form></body></html>"""
