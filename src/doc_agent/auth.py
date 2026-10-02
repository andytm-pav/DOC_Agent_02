"""Аутентификация: JWT (python-jose) + RBAC + API-ключи для внешних систем.

v3.0.0: пользователи и ГРУППЫ живут в отдельном файле config/users.yaml
(бэкап) — services/users_store.py. Права пользователя = объединение прав
его групп; право "admin" даёт полный доступ (в том числе role=admin для
require_admin). Права разрешаются при КАЖДОМ запросе (правки групп
вступают в силу сразу, без перелогина). Обратная совместимость:
пользователи SQLite переносятся в файл при первом старте/входе; если
в файле пользователя нет — работает старая ролевая модель
(admin | user). API-ключи config auth.api_keys — без изменений.
"""
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
from doc_agent.db.migrations import hash_password, verify_password
from doc_agent.db.models import User
from doc_agent.db.session import get_db
from doc_agent.services import users_store

_bearer = HTTPBearer(auto_error=False)


def create_access_token(username: str, role: str, groups: list[str] | None = None) -> str:
    s = load_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=s.auth.token_expire_minutes)
    payload = {"sub": username, "role": role, "exp": expire}
    if groups:
        payload["groups"] = groups
    return jwt.encode(payload, s.app.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    s = load_settings()
    return jwt.decode(token, s.app.secret_key, algorithms=["HS256"])


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Логин: users.yaml (источник истины, v3.0.0) -> SQLite-фолбэк.

    Успешный вход legacy-пользователя из SQLite прозрачно переносит его в
    users.yaml (ensure_user) — файл постепенно становится полным списком.
    """
    user = users_store.verify_login(username, password)
    if user is not None:
        return user
    db_user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if db_user is None or not verify_password(password, db_user.password_hash):
        return None
    try:
        users_store.ensure_user(db_user.username, db_user.password_hash, db_user.role)
    except Exception:  # noqa: BLE001 — вход не должен ломаться от сбоя файла
        pass
    return db_user


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


def _resolve_user(username: str, token_role: str) -> User:
    """Пользователь JWT с АКТУАЛЬНОЙ ролью: groups в users.yaml важнее
    роли в токене (правки групп вступают в силу без перелогина)."""
    role = users_store.role_for(username, token_role)
    return User(id=0, username=username, password_hash="", role=role)


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
    return _resolve_user(username, role)


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


def require_perm(perm: str):
    """Зависимость FastAPI: конкретное право (v3.0.0).

    Право "admin" включает всё. Права берутся из групп пользователя в
    users.yaml при каждом запросе; для пользователей вне файла — старая
    ролевая модель (admin -> всё, user -> chat/feedback_submit/files_view).
    """

    def _dep(user: User = Depends(get_current_user)) -> User:
        if not users_store.has_permission(user.username, perm, user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Не хватает прав ({perm}) — настройте группы в админ-вкладке «Пользователи»",
            )
        return user

    return _dep


def audit_payload(user: User) -> str:
    return json.dumps({"actor": user.username, "role": user.role}, ensure_ascii=False)


# hash_password реэкспортируется для совместимости импортов (bcrypt-формат
# одинаков для SQLite и users.yaml)
__all__ = ["create_access_token", "decode_token", "authenticate", "match_api_key",
           "get_current_user", "get_current_user_optional", "require_admin",
           "require_perm", "audit_payload", "hash_password"]
