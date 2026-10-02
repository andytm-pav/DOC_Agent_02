"""Полный сброс «Документоведа»: база, история чата, векторный индекс,
загруженные файлы, обратная связь (v3.0.0 — запрос пользователя: «возможность
полностью обнулить (рестартнуть) Агента, а так же удалить базу»).

Запускать ПРИ ОСТАНОВЛЕННОМ сервере (uvicorn/app.py не должен держать БД).

Режимы (по умолчанию — ПОЛНЫЙ сброс):
  (без флагов)   БД (файлы, чанки, таблицы, связи, jobs, audit, ОБРАТНАЯ
                 СВЯЗЬ, пути файлов) + история чата и архивы памяти +
                 векторный индекс + загруженные файлы.
                 ВАЖНО: config/users.yaml (пользователи и группы) НЕ трогается
                 — это конфигурация, её бэкапят отдельно.
  --keep-files   полный сброс, НО оставить загруженные оригиналы
                 (data/storage): БД чистится, оригиналы остаются на диске,
                 их можно заново импортировать папкой без повторного
                 копирования из внешнего источника
  --history-only стереть ТОЛЬКО историю чата и архивы памяти
  --vectors-only стереть ТОЛЬКО векторный индекс (после смены backend/
                 чанкинга; переиндексация — кнопка в админ-панели)
  --feedback-only стереть ТОЛЬКО базу обратной связи (проверенные ответы:
                 «дообучение» начнётся с нуля)
  --yes          без интерактивного подтверждения

Пути — из config/config.yaml (app.data_dir и подпапки), ничего не
хардкодится. После сброса схема пересоздаётся, администратор
(app.admin_username/admin_password) создаётся заново.

Примеры (Windows/PyCharm Terminal):
  python scripts/reset_database.py --yes
  python scripts/reset_database.py --yes --keep-files
  python scripts/reset_database.py --history-only --yes
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from doc_agent.config import load_settings  # noqa: E402
from doc_agent.db.migrations import init_db  # noqa: E402
from doc_agent.db.session import db_file  # noqa: E402
from doc_agent.logging import get_logger  # noqa: E402
from doc_agent.vector.chroma_client import reset_vector_store  # noqa: E402

log = get_logger("scripts.reset")


def _rmtree(path: Path, label: str) -> int:
    """Удалить дерево каталогов; вернуть счётчик удалённых путей (1/0)."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        print(f"  удалено: {label}: {path}")
        return 1
    print(f"  отсутствует (пропущено): {label}: {path}")
    return 0


def _unlink(path: Path, label: str) -> int:
    if path.exists():
        path.unlink()
        print(f"  удалено: {label}: {path}")
        return 1
    return 0


def wipe_history() -> None:
    print("[1/1] История чата и архивы памяти")
    init_db()  # гарантирует существование схемы
    from sqlalchemy import delete

    from doc_agent.db.models import ChatMessage, ContextArchive
    from doc_agent.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as db:
        m = db.execute(delete(ChatMessage)).rowcount
        a = db.execute(delete(ContextArchive)).rowcount
        db.commit()
    print(f"  сообщений удалено: {m}, памяток удалено: {a}")


def wipe_feedback() -> None:
    """v3.0.0: очистка базы обратной связи (проверенные ответы)."""
    print("[1/1] Обратная связь (проверенные ответы, feedback_entries)")
    init_db()
    from sqlalchemy import delete

    from doc_agent.db.models import FeedbackEntry
    from doc_agent.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as db:
        n = db.execute(delete(FeedbackEntry)).rowcount
        db.commit()
    print(f"  записей обратной связи удалено: {n}")


def wipe_vectors() -> None:
    print("[1/1] Векторный индекс (Chroma/lite)")
    s = load_settings()
    n = _rmtree(s.app.sub_dir("chroma"), "векторный индекс")
    reset_vector_store()
    if n == 0:
        print("  (индекс и так пуст)")


def wipe_all(keep_files: bool) -> None:
    print("[1/4] База данных (файлы, чанки, таблицы, jobs, audit, фидбэк, пути)")
    s = load_settings()
    dbf = db_file()
    removed = 0
    for suffix in ("", "-wal", "-shm"):
        removed += _unlink(Path(str(dbf) + suffix), "SQLite")
    if removed == 0:
        print("  (БД и так отсутствует)")

    print("[2/4] Векторный индекс")
    wipe_vectors()

    print("[3/4] История чата и архивы памяти")
    # Удаляется вместе с БД (шаг 1) — отдельного прохода не требуется.

    print("[4/4] Загруженные файлы" + (" (сохраняются по --keep-files)" if keep_files else ""))
    if not keep_files:
        _rmtree(s.app.sub_dir(s.app.storage_subdir), "хранилище файлов")
    else:
        print(f"  сохранено: {s.app.sub_dir(s.app.storage_subdir)}")

    # v3.0.0: users.yaml — конфигурация, не данные: намеренно НЕ удаляется.
    try:
        from doc_agent.services import users_store

        print(f"  пользователи и группы сохранены (users.yaml): {users_store.users_file()}")
    except Exception:  # noqa: BLE001
        pass


def recreate() -> None:
    print("\nПересоздание схемы и администратора…")
    init_db()
    s = load_settings()
    print(f"  БД: {db_file()}")
    print(f"  администратор: {s.app.admin_username} (пароль из .env/app.admin_password)")
    try:
        from doc_agent.services import users_store

        if users_store.users_file().exists():
            print(f"  пользователи/группы (users.yaml): {users_store.users_file()}")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Полный сброс «Документоведа» (v3.0.0). Запускать при остановленном сервере.")
    parser.add_argument("--yes", action="store_true", help="без подтверждения")
    parser.add_argument("--keep-files", action="store_true",
                        help="не трогать загруженные файлы (data/storage)")
    parser.add_argument("--history-only", action="store_true",
                        help="стереть только историю чата и архивы памяти")
    parser.add_argument("--vectors-only", action="store_true",
                        help="стереть только векторный индекс")
    parser.add_argument("--feedback-only", action="store_true",
                        help="стереть только базу обратной связи (проверенные ответы)")
    args = parser.parse_args()

    modes = [m for m, on in
             (("history", args.history_only), ("vectors", args.vectors_only),
              ("feedback", args.feedback_only),
              ("full", not (args.history_only or args.vectors_only or args.feedback_only))) if on]
    mode = modes[0]

    print("=" * 62)
    print("Документовед — сброс данных")
    print(f"режим: {mode}"
          + (" (файлы сохраняются)" if mode == "full" and args.keep_files else ""))
    print("=" * 62)

    if not args.yes:
        answer = input("Продолжить? [y/N]: ").strip().lower()
        if answer not in {"y", "yes", "д", "да"}:
            print("Отменено.")
            return 1

    if mode == "history":
        wipe_history()
    elif mode == "vectors":
        wipe_vectors()
    elif mode == "feedback":
        wipe_feedback()
    else:
        wipe_all(keep_files=args.keep_files)
    recreate()

    print("\nГотово. Теперь:")
    print("  1. Запустите сервер (run.bat или uvicorn app:app).")
    print("  2. Загрузите файлы заново (drag&drop или «Импортировать папку»).")
    print("     Все файлы переиндексируются с текущими настройками чанкинга")
    print("     и эмбеддингов — старые чанки и псевдоэмбеддинги не «накладываются».")
    log_audit_safe(mode)
    return 0


def log_audit_safe(mode: str) -> None:
    try:
        from doc_agent.db.migrations import log_audit

        log_audit("scripts", "database_reset", {"mode": mode})
    except Exception as exc:  # noqa: BLE001
        print(f"  (audit не записан: {exc})")


if __name__ == "__main__":
    raise SystemExit(main())
