"""Аутентификация: JWT (python-jose) + RBAC (admin | user) + API-ключи
для доступа из внешних систем (config: auth.api_keys, заголовок X-API-Key)."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.migrations import verify_password
from doc_agent.db.models import User
from doc_agent.db.session import get_db

_bearer = HTTPBearer(auto_error=False)


def create_access_token(username: str, role: str) -> str:
    s = load_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=s.auth.token_expire_minutes)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, s.app.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    s = load_settings()
    return jwt.decode(token, s.app.secret_key, algorithms=["HS256"])


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def _credentials_error(detail: str = "Не авторизован") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def match_api_key(provided: str) -> User | None:
    """Проверка API-ключа внешней системы против config auth.api_keys.

    Сравнение timing-safe (secrets.compare_digest). При совпадении
    возвращается синтетический пользователь ``api:<name>`` с ролью из
    конфига — он проходит все зависимости и попадает в audit_log.
    """
    provided = (provided or "").strip()
    if not provided:
        return None
    s = load_settings()
    for entry in s.auth.api_keys:
        if entry.key and secrets.compare_digest(provided, entry.key.strip()):
            return User(id=0, username=f"api:{entry.name}", password_hash="", role=entry.role)
    return None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """JWT Bearer ИЛИ API-ключ внешней системы (E009/E010).

    Приоритет: 1) заголовок X-API-Key: <ключ>; 2) JWT Bearer;
    3) Bearer, содержащий API-ключ (удобно для curl/n8n/скриптов).
    """
    api_key_header = request.headers.get("x-api-key", "")
    if api_key_header.strip():
        user = match_api_key(api_key_header)
        if user is None:
            raise _credentials_error("Недействительный API-ключ")
        return user
    if credentials is None:
        raise _credentials_error()
    try:
        payload = decode_token(credentials.credentials)
        username = str(payload.get("sub"))
        role = str(payload.get("role", "user"))
    except JWTError:
        # Bearer может нести API-ключ внешней системы, а не JWT
        user = match_api_key(credentials.credentials)
        if user is not None:
            return user
        raise _credentials_error("Недействительный токен")
    user = User(id=0, username=username, password_hash="", role=role)
    return user


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),  # noqa: ARG001
) -> User:
    """Для A2A: токен не обязателен, если a2a.auth_required=false (E009/E010).

    X-API-Key принимается и здесь: внешний A2A-клиент идентифицируется
    как ``api:<name>``. Неверный ключ — 401 (fail-closed).
    """
    api_key_header = request.headers.get("x-api-key", "")
    if api_key_header.strip():
        user = match_api_key(api_key_header)
        if user is None:
            raise _credentials_error("Недействительный API-ключ")
        return user
    if credentials is None:
        return User(id=0, username="a2a-client", password_hash="", role="user")
    try:
        payload = decode_token(credentials.credentials)
        return User(id=0, username=str(payload.get("sub")), password_hash="", role=str(payload.get("role", "user")))
    except JWTError:
        user = match_api_key(credentials.credentials)
        if user is not None:
            return user
        return User(id=0, username="a2a-client", password_hash="", role="user")


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Не хватает прав (E010)")
    return user


def audit_payload(user: User) -> str:
    return json.dumps({"actor": user.username, "role": user.role}, ensure_ascii=False)
