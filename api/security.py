"""Аутентификация: пароли (PBKDF2-SHA256), JWT, доступ только к своим компаниям."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Company, User, get_session

_ITER = 200_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), _ITER).hex()
    return f"pbkdf2_sha256${_ITER}${salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        cand = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), int(it)).hex()
        return hmac.compare_digest(cand, h)
    except (ValueError, TypeError):
        return False


def ensure_users(session: Session) -> None:
    """Создать пользователей из API_USERS («логин:пароль,…»), если их ещё нет."""
    for pair in get_settings().users.split(","):
        if ":" not in pair:
            continue
        login, pwd = pair.split(":", 1)
        login = login.strip()
        if login and not session.scalar(select(User).where(User.username == login)):
            session.add(User(username=login, password_hash=hash_password(pwd)))
    session.commit()


def create_token(username: str) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    payload = {"sub": username, "iat": now, "exp": now + dt.timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def authenticate(session: Session, username: str, password: str) -> str | None:
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        # одинаковое время ответа для существующего и несуществующего логина
        verify_password(password, hash_password("x", "0" * 32))
        return None
    return create_token(user.username) if verify_password(password, user.password_hash) else None


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 session: Session = Depends(get_session)) -> str:
    if cred is None or cred.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужно войти в систему",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(cred.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла — войдите заново",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный токен — войдите заново",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    username = str(payload.get("sub") or "")
    if not session.scalar(select(User).where(User.username == username)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден — войдите заново")
    return username


def check_access(company: Company | None, username: str) -> Company:
    """Компании из датасета и синтетики — общие (демо), загруженные — только владельцу."""
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена — загрузите выписку")
    if company.owner is not None and company.owner != username:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к этой компании")
    return company
