"""Аутентификация (6.1): POST /auth/login, GET /auth/me.

v3.0.0: в токен добавляются группы; /auth/me возвращает права пользователя
(объединение прав групп users.yaml) — UI может скрывать недоступные панели.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from doc_agent.auth import authenticate, create_access_token, get_current_user
from doc_agent.db.migrations import log_audit
from doc_agent.db.models import User
from doc_agent.db.session import get_db
from doc_agent.services import users_store

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль (E009)")
    groups = users_store.groups_of(user.username)
    token = create_access_token(user.username, user.role, groups)
    log_audit(user.username, "auth_login", {"role": user.role, "groups": groups})
    return {"access_token": token, "token_type": "bearer", "role": user.role,
            "groups": groups}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "username": user.username,
        "role": user.role,
        "groups": users_store.groups_of(user.username),
        "permissions": users_store.permissions_for(user.username, user.role),
    }
