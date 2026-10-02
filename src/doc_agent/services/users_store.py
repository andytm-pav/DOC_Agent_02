"""Пользователи и группы — ОТДЕЛЬНЫЙ файл (v3.0.0, запрос: «должно храниться
в отдельном файле для возможности бэкапа этого файла»).

Источник истины — config/users.yaml (путь настраивается, users.file в
config.yaml). Файл создаётся автоматически при первом старте
(ensure_users_file): переносятся ВСЕ пользователи SQLite (bcrypt-хэши
совместимы), группы по ролям: role=admin -> [admins], role=user -> [users].
При входе пользователь, найденный в SQLite, но отсутствующий в файле,
прозрачно переносится туда же (обратная совместимость).

Формат файла:
    users:
      - username: admin
        password_hash: "$2b$12$..."   # bcrypt, тот же формат, что в БД
        display_name: "Администратор"
        groups: [admins]
        is_active: true
    groups:
      admins:
        permissions: [admin]          # admin = все права
      users:
        permissions: [chat, feedback_submit, files_view]
        allowed_roots: []             # песочница файловых операций

Права (permissions): admin, chat, feedback_submit, feedback_manage,
documents_manage, files_view, files_manage, users_manage.
Отсутствие права в группах пользователя = запрет (fail-closed).
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

from doc_agent.config import REPO_ROOT, load_settings
from doc_agent.db.migrations import hash_password, log_audit, verify_password
from doc_agent.db.models import User
from doc_agent.logging import get_logger

log = get_logger("services.users")

# Словарь прав (единый для UI и сервера; UI рисует чекбоксы по нему)
KNOWN_PERMISSIONS: list[str] = [
    "admin",              # полный доступ (включает всё ниже)
    "chat",               # пользоваться чатом
    "feedback_submit",    # ставить 👍/👎 и отправлять исправления
    "feedback_manage",    # администрировать базу обратной связи
    "documents_manage",   # удалять/реиндексировать/править документы и чанки
    "files_view",         # видеть пути файлов на диске
    "files_manage",       # перемещать/копировать файлы, создавать папки
    "users_manage",       # управлять пользователями и группами
]

DEFAULT_GROUPS: dict[str, dict] = {
    "admins": {"permissions": ["admin"], "allowed_roots": []},
    "users": {"permissions": ["chat", "feedback_submit", "files_view"],
              "allowed_roots": []},
}

_USER_RE = re.compile(r"^[a-zA-Z0-9_.\-\u0400-\u04FF]{2,64}$")
_GROUP_RE = re.compile(r"^[a-zA-Z0-9_\-]{2,64}$")


class UsersError(ValueError):
    """Ошибка валидации данных пользователей (текст — для HTTP 400/422)."""


def users_file() -> Path:
    """Путь файла пользователей из конфига (относительный — от корня)."""
    raw = Path(load_settings().users.file)
    return raw if raw.is_absolute() else (REPO_ROOT / raw)


def load() -> dict:
    """Читает users.yaml; отсутствующий файл = пустое хранилище."""
    path = users_file()
    if not path.exists():
        return {"users": [], "groups": dict(DEFAULT_GROUPS)}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        log.error("users_file_corrupt", error=str(exc))
        raise UsersError(f"Файл пользователей повреждён ({path}): {exc}") from exc
    data.setdefault("users", [])
    data.setdefault("groups", {})
    return data


def save(data: dict, actor: str = "system") -> None:
    """Атомарная запись users.yaml (+ копия .bak предыдущей версии)."""
    path = users_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    log_audit(actor, "users_file_saved", {
        "users": len(data.get("users", [])),
        "groups": len(data.get("groups", {})),
    })
    log.info("users_file_saved", path=str(path), actor=actor)


def _entry_to_user(entry: dict) -> User:
    role = "admin" if "admin" in permissions_of(entry) else "user"
    return User(id=0, username=str(entry.get("username", "")),
                password_hash=str(entry.get("password_hash", "")), role=role)


# ---------- поиск / права ----------

def get_entry(username: str, data: dict | None = None) -> dict | None:
    data = data or load()
    for u in data.get("users", []):
        if str(u.get("username", "")) == username:
            return u
    return None


def permissions_of(entry: dict) -> list[str]:
    """Права пользователя = объединение прав его групп."""
    groups = load().get("groups", {})
    out: list[str] = []
    for g in entry.get("groups", []) or []:
        for p in (groups.get(g) or {}).get("permissions", []) or []:
            if p not in out:
                out.append(p)
    return out


def permissions_for(username: str, fallback_role: str = "user") -> list[str]:
    """Права по имени: users.yaml -> роли-фолбэк (api-ключи, a2a, legacy)."""
    entry = get_entry(username)
    if entry is not None:
        if entry.get("is_active", True) is False:
            return []
        return permissions_of(entry)
    if fallback_role == "admin":
        return ["admin"]
    return ["chat", "feedback_submit", "files_view"]


def has_permission(username: str, perm: str, fallback_role: str = "user") -> bool:
    perms = permissions_for(username, fallback_role)
    return "admin" in perms or perm in perms


def role_for(username: str, fallback_role: str = "user") -> str:
    entry = get_entry(username)
    if entry is not None:
        return "admin" if "admin" in permissions_of(entry) else "user"
    return fallback_role


def groups_of(username: str) -> list[str]:
    entry = get_entry(username)
    return list((entry or {}).get("groups", []) or [])


def allowed_roots_for(username: str) -> list[Path]:
    """Песочница файловых операций: files.allowed_roots + корни групп."""
    from doc_agent.config import load_settings as _ls

    roots: list[str] = list(_ls().files.allowed_roots)
    data = load()
    for g in groups_of(username):
        roots += [str(r) for r in (data.get("groups", {}).get(g) or {}).get("allowed_roots", []) or []]
    out: list[Path] = []
    for r in roots:
        p = Path(r).expanduser()
        if p not in out:
            out.append(p)
    return out


# ---------- аутентификация ----------

def verify_login(username: str, password: str) -> User | None:
    entry = get_entry(username)
    if entry is None or entry.get("is_active", True) is False:
        return None
    if not verify_password(password, str(entry.get("password_hash", ""))):
        return None
    return _entry_to_user(entry)


def import_sqlite_users(actor: str = "system") -> int:
    """Переносит пользователей из SQLite в users.yaml (идемпотентно)."""
    from sqlalchemy import select

    from doc_agent.db.models import User as UserModel
    from doc_agent.db.session import get_session_factory

    try:
        factory = get_session_factory()
        with factory() as db:
            rows = db.execute(select(UserModel)).scalars().all()
    except Exception as exc:  # noqa: BLE001 — БД может отсутствовать на этапе тестов
        log.warning("users_import_db_unavailable", error=str(exc))
        return 0
    data = load()
    known = {str(u.get("username", "")) for u in data.get("users", [])}
    imported = 0
    for row in rows:
        if row.username in known:
            continue
        data["users"].append({
            "username": row.username,
            "password_hash": row.password_hash,
            "display_name": "",
            "groups": ["admins"] if row.role == "admin" else ["users"],
            "is_active": True,
        })
        imported += 1
    if imported:
        save(data, actor)
    return imported


def ensure_users_file() -> Path:
    """Создаёт users.yaml при первом старте; возвращает путь.

    Идемпотентно: существующий файл не перезаписывается. Дефолтные группы
    (admins/users) добавляются, только если в файле нет ни одной группы.
    Если пользователей нет вовсе — создаётся админ из app.admin_*.
    """
    path = users_file()
    if path.exists():
        return path
    data = load()
    if not data["groups"]:
        data["groups"] = dict(DEFAULT_GROUPS)
    imported = import_sqlite_users("system")
    if not data["users"]:
        s = load_settings()
        admin_name = s.app.admin_username or "admin"
        data["users"].append({
            "username": admin_name,
            "password_hash": hash_password(s.app.admin_password or "admin"),
            "display_name": "Администратор",
            "groups": ["admins"],
            "is_active": True,
        })
        save(data, "system")
        log.info("users_file_created", path=str(path), admin=admin_name,
                 imported_from_sqlite=imported)
        log_audit("system", "users_file_created", {"path": str(path), "imported": imported})
    elif imported:
        log.info("users_imported_from_sqlite", count=imported)
    return path


# ---------- CRUD пользователей (админ-вкладка + прозрачный перенос) ----------

def _validate_groups(data: dict, groups: list[str]) -> None:
    known = data.get("groups", {})
    for g in groups:
        if g not in known:
            raise UsersError(f"Неизвестная группа: {g}")


def _find_user_row(data: dict, username: str) -> dict:
    for u in data.get("users", []):
        if str(u.get("username", "")) == username:
            return u
    raise UsersError(f"Пользователь не найден: {username}")


def create_user(username: str, password: str, groups: list[str],
                display_name: str = "", actor: str = "system") -> dict:
    username = (username or "").strip()
    if not _USER_RE.match(username):
        raise UsersError("Логин: 2-64 символа, буквы/цифры/._- (кириллица допустима)")
    if len(password or "") < 4:
        raise UsersError("Пароль минимум 4 символа")
    data = load()
    if get_entry(username, data) is not None:
        raise UsersError(f"Пользователь уже существует: {username}")
    groups = groups or ["users"]
    _validate_groups(data, groups)
    entry = {
        "username": username,
        "password_hash": hash_password(password),
        "display_name": (display_name or "").strip()[:120],
        "groups": groups,
        "is_active": True,
    }
    data["users"].append(entry)
    save(data, actor)
    log_audit(actor, "user_created", {"username": username, "groups": groups})
    return {k: v for k, v in entry.items() if k != "password_hash"}


def update_user(username: str, password: str | None = None,
                groups: list[str] | None = None, display_name: str | None = None,
                is_active: bool | None = None, actor: str = "system") -> dict:
    data = load()
    entry = _find_user_row(data, username)
    if groups is not None:
        _validate_groups(data, groups)
        # защита от блокировки: нельзя снять последнего администратора
        if "admins" not in groups and _is_last_admin(data, username):
            raise UsersError("Нельзя убрать группу admins у последнего администратора")
        entry["groups"] = groups
    if password:
        if len(password) < 4:
            raise UsersError("Пароль минимум 4 символа")
        entry["password_hash"] = hash_password(password)
    if display_name is not None:
        entry["display_name"] = display_name.strip()[:120]
    if is_active is not None:
        if is_active is False and _is_last_admin(data, username):
            raise UsersError("Нельзя отключить последнего администратора")
        entry["is_active"] = bool(is_active)
    save(data, actor)
    log_audit(actor, "user_updated", {"username": username})
    return {k: v for k, v in entry.items() if k != "password_hash"}


def delete_user(username: str, actor: str = "system") -> None:
    data = load()
    _find_user_row(data, username)
    if username == actor:
        raise UsersError("Нельзя удалить собственную учётную запись")
    if _is_last_admin(data, username):
        raise UsersError("Нельзя удалить последнего администратора")
    data["users"] = [u for u in data["users"]
                     if str(u.get("username", "")) != username]
    save(data, actor)
    log_audit(actor, "user_deleted", {"username": username})


def _is_last_admin(data: dict, username: str) -> bool:
    entry = get_entry(username, data)
    if entry is None or "admins" not in (entry.get("groups") or []):
        return False
    active_admins = [
        u for u in data.get("users", [])
        if "admins" in (u.get("groups") or []) and u.get("is_active", True)
    ]
    return len(active_admins) <= 1


def ensure_user(username: str, password_hash: str, role: str = "user") -> None:
    """Прозрачный перенос пользователя из SQLite при первом входе."""
    data = load()
    if get_entry(username, data) is not None:
        return
    if not data.get("groups"):
        data["groups"] = dict(DEFAULT_GROUPS)
    data["users"].append({
        "username": username,
        "password_hash": password_hash,
        "display_name": "",
        "groups": ["admins"] if role == "admin" else ["users"],
        "is_active": True,
    })
    save(data, "system")
    log.info("user_imported_on_login", username=username, role=role)


# ---------- CRUD групп ----------

def upsert_group(name: str, permissions: list[str],
                 allowed_roots: list[str] | None = None, actor: str = "system") -> dict:
    name = (name or "").strip()
    if not _GROUP_RE.match(name):
        raise UsersError("Имя группы: 2-64 символа, латиница/цифры/_-")
    unknown = [p for p in permissions if p not in KNOWN_PERMISSIONS]
    if unknown:
        raise UsersError(f"Неизвестные права: {', '.join(unknown)}")
    data = load()
    existed = name in data.get("groups", {})
    if existed and "admin" in (data["groups"][name].get("permissions") or []) \
            and "admin" not in permissions:
        raise UsersError("Нельзя убрать право admin у группы admins (заблокируете админку)")
    data.setdefault("groups", {})[name] = {
        "permissions": permissions,
        "allowed_roots": [str(r).strip() for r in (allowed_roots or []) if str(r).strip()],
    }
    save(data, actor)
    log_audit(actor, "group_saved", {"group": name, "permissions": permissions})
    return data["groups"][name]


def delete_group(name: str, actor: str = "system") -> None:
    data = load()
    if name not in data.get("groups", {}):
        raise UsersError(f"Группа не найдена: {name}")
    if name == "admins":
        raise UsersError("Системную группу admins удалить нельзя")
    in_use = [str(u.get("username", "")) for u in data.get("users", [])
              if name in (u.get("groups") or [])]
    if in_use:
        raise UsersError("Группа используется пользователями: " + ", ".join(in_use[:5]))
    del data["groups"][name]
    save(data, actor)
    log_audit(actor, "group_deleted", {"group": name})


def snapshot_for_admin() -> dict:
    """Данные для админ-вкладки (без хэшей паролей)."""
    data = load()
    return {
        "file": str(users_file()),
        "backup_file": str(users_file()) + ".bak",
        "known_permissions": KNOWN_PERMISSIONS,
        "users": [
            {
                "username": u.get("username", ""),
                "display_name": u.get("display_name", ""),
                "groups": u.get("groups", []),
                "is_active": bool(u.get("is_active", True)),
                "permissions": permissions_of(u),
            }
            for u in data.get("users", [])
        ],
        "groups": data.get("groups", {}),
    }


def to_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)
