"""Accesso con password condivisa (per qualche amico). Se APP_PASSWORD è vuota, il sito è aperto."""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

COOKIE_NAME = "psb_session"
MAX_AGE = 60 * 60 * 24 * 30  # 30 giorni
PUBLIC_PATHS = {"/login", "/static/style.css", "/healthz", "/favicon.svg"}

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="psb-login")


def check_password(password: str) -> bool:
    return bool(settings.app_password) and hmac.compare_digest(
        password.encode(), settings.app_password.encode()
    )


def make_token() -> str:
    return _serializer.dumps({"ok": True})


def is_logged_in(request: Request) -> bool:
    if not settings.app_password:
        return True
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


async def auth_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS or is_logged_in(request):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "login richiesto"}, status_code=401)
    return RedirectResponse("/login", status_code=303)
