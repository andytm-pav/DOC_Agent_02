"""Смоук v2.7: промышленный ретрив + скрипт сброса на живом uvicorn.

Мок OpenAI-совместимого API имитирует glm-4.5-flash. Сценарий — из реального
диалога пользователя (жалоба «агент не видит и галлюцинирует»):
  - библиотека: 3 сметы Вилоновской + ШУМ (Конкурсная документация, Аэр.xlsx);
  - «что в сметах по вилоновской?» -> чтение смет целиком (не RAG-каша);
  - «нужны материалы по отмостке вилоновской» -> целевой файл;
  - RAG-путь: фрагменты только из смет Вилоновской (шум отсечён),
    уверенность > 0.3 (раньше 0.11 у мусора);
  - скрипт reset_database.py: сервер останавливается, сброс выполняется,
    картотека после него пуста, администратор пересоздан.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PORT = 8131
MOCK_PORT = 8132
BASE = f"http://127.0.0.1:{PORT}"

results: list[tuple[bool, str]] = []
mock_state = {"chat_calls": 0, "embed_calls": 0, "deep_prompts": 0}


def _catalog_map(prompt: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in re.finditer(r"• (.+?) \[file_id:(\d+)\]", prompt):
        out[m.group(1).strip()] = int(m.group(2))
    return out


def _plan_for(q: str, prompt: str) -> dict:
    low = q.lower()
    catalog = _catalog_map(prompt)
    vilon_ids = [fid for name, fid in catalog.items()
                 if "смет" in name.lower() and "вилоновская" in name.lower()]
    if "что в сметах" in low:
        return {"action": "read_file", "doc_type": None, "terms": ["вилоновская", "смета"],
                "file_ids": vilon_ids, "search_query": "", "reply": ""}
    # «отмостк» — по усечённому корню: вопрос может склонять слово
    # («по отмостке»); живой LLM это понимает сам, мок — простая строка
    if "отмостк" in low:
        ids = [fid for name, fid in catalog.items() if "отмостк" in name.lower()]
        return {"action": "read_file", "doc_type": None, "terms": ["вилоновская", "отмостка"],
                "file_ids": ids, "search_query": "", "reply": ""}
    # остальные «материалы/вилоновская» — принудительно RAG (проверка ретрива);
    # search_query с исправленной опечаткой (как требует обновлённый planner.txt)
    return {"action": "search_content", "doc_type": None, "terms": ["вилоновская"],
            "file_ids": [], "search_query": "материалы вилоновская", "reply": ""}


def _wrap(text: str) -> dict:
    return {"choices": [{"message": {"content": text, "reasoning_content": ""}}]}


def _fake_question(prompt: str) -> str:
    m = re.search(r"Вопрос пользователя: (.+)", prompt)
    return m.group(1).strip() if m else ""


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:  # noqa: ANN002
        pass

    def _send(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/embeddings"):
            mock_state["embed_calls"] += 1
            inputs = payload.get("input") or []
            data = [{"index": i, "embedding": [float(len(str(t)) % 5 + 1), 0.5]}
                    for i, t in enumerate(inputs)]
            self._send({"data": data})
            return
        mock_state["chat_calls"] += 1
        prompt = (payload.get("messages") or [{}])[0].get("content", "")
        low = prompt.lower()
        if "планировщик" in low:
            plan = _plan_for(_fake_question(prompt), prompt)
            self._send(_wrap(json.dumps(plan, ensure_ascii=False)))
        elif "полный текст" in low:
            mock_state["deep_prompts"] += 1
            self._send(_wrap(
                "Материалы по смете Вилоновская: Унифлекс ЭПП, грунтовка "
                "акрилатная, смесь гипсовая, бетон B15. Итого по материалам 98880."))
        elif "ты формируешь ответ" in low:
            self._send(_wrap("Материалы по Вилоновской: Унифлекс ЭПП [file_id:1]"))
        else:
            self._send(_wrap("неизвестный промпт"))


def start_mock() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def api(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def check(name: str, cond: bool, extra: str = "") -> None:
    results.append((bool(cond), name))
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra and not cond else ""))


def wait_file(token: str, fid: int, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = api("GET", f"/files/{fid}", token)
        if data["file"]["status"] in {"done", "failed", "description_only"}:
            return data
        time.sleep(0.3)
    raise TimeoutError(f"file {fid} not processed")


def start_server(cfg_path: Path, log_path: Path | None = None):
    env = dict(os.environ, DOC_AGENT_CONFIG=str(cfg_path))
    out = open(log_path, "wb") if log_path else subprocess.DEVNULL
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "doc_agent.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(REPO), env=env,
        stdout=out, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            api("GET", "/health")
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("uvicorn не поднялся")


def _rows_estimate() -> list[list[object]]:
    return [
        ["№", "Вид работ", "Объём", "Ед."],
        [1, "Устройство отмостки бетонной", 120, "м2"],
        [2, "Разборка отмостки", 120, "м2"],
        [3, "Материалы", ""],
        [4, "Бетон класса B15", 24, "м3"],
        [5, "Щебень фракции 20-40", 18, "м3"],
    ]


def _rows_krovlya() -> list[list[object]]:
    return [
        ["№", "Наименование", "Кол-во", "Ед."],
        [1, "Унифлекс ЭПП 3.0 рул", 48, "рул"],
        [2, "Праймер битумный", 200, "кг"],
        [3, "Итого по работе", 672103.3],
    ]


def _rows_svod() -> list[list[object]]:
    return [
        ["№", "Раздел", "Сумма"],
        [1, "Работы", 672103.3],
        [2, "Материалы", 98880],
        [3, "Итого по смете", 770983.3],
    ]


def _rows_aer() -> list[list[object]]:
    return [
        ["№", "Наименование", "Кол-во", "Ед."],
        [21, "Регулятор оборотов вентилятора", 2, "шт"],
        [25, "Кабель силовой ВВГнг(A)-LS 3x1,5", 153, "м"],
    ]


NOISE_TXT = ("Документация по отбору в электронной форме. «более 5» — необходимо "
             "указать единственное числовое значение строго выше указанного, крайнее "
             "числовое значение не входит в диапазон.")


def main() -> int:
    from openpyxl import Workbook

    tmp = Path(tempfile.mkdtemp(prefix="smoke_v27_"))
    (tmp / "data").mkdir()
    for sub in ("storage", "sqlite", "chroma", "logs", "inbox"):
        (tmp / "data" / sub).mkdir()
    dump = tmp / "dump"
    dump.mkdir()

    for name, rows in (
        ("Смета по стена и отмостка Вилоновская 23 (2).xlsx", _rows_estimate()),
        ("Смета по кровле Вилоновская 23.xlsx", _rows_krovlya()),
        ("Сводная смета Вилоновская 23.xlsx", _rows_svod()),
        ("Аэр.xlsx", _rows_aer()),
    ):
        wb = Workbook()
        ws = wb.active
        ws.title = "Смета"
        for row in rows:
            ws.append(row)
        wb.save(dump / name)
    (dump / "Конкурсная документация ЗК в ЭФ об. 700 пл.16.txt").write_text(
        NOISE_TXT, encoding="utf-8")

    cfg = {
        "app": {"host": "127.0.0.1", "port": PORT, "secret_key": "s", "data_dir": str(tmp / "data"),
                "admin_username": "admin", "admin_password": "admin"},
        "storage": {"local_paths": [str(tmp / "data" / "storage")], "network_paths": []},
        "watchdog": {"enabled": False, "paths": [], "interval_sec": 30},
        "llm": {"provider": "openai_compatible", "base_url": f"http://127.0.0.1:{MOCK_PORT}",
                "api_key": "test-key", "model_main": "glm-4.5-flash",
                "model_light": "glm-4.5-flash", "timeout_sec": 20, "temperature": 0.0,
                "extra_body": {"thinking": {"type": "disabled"}}},
        # embeddings backend auto: ключ есть, но мок /embeddings отдаёт 2-мерные
        # векторы — это валидно (dim любой, главное согласованность)
        "embeddings": {"backend": "hashing", "model": "unused", "batch_size": 8},
        "vector": {"backend": "chroma", "collection": "chunks", "metric": "cosine",
                   "auto_collection_suffix": True},
        "reranker": {"backend": "simple", "model": "x", "top_k": 5},
        "chunking": {"size_tokens": 128, "overlap_tokens": 16},
        "ocr": {"engine": "none", "tesseract_cmd": "", "tesseract_langs": ["rus"],
                "min_confidence": 0.8, "reject_threshold": 0.5,
                "process_embedded_images": False},
        "groundrails": {"enabled": True, "cut_ratio": 0.30, "confidence_top_k": 3},
        "a2a": {"enabled": True, "agent_name": "document-agent", "auth_required": False},
        "limits": {"max_file_mb": 100, "max_query_len": 2000},
        "auth": {"token_expire_minutes": 60, "api_keys": []},
    }
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    mock = start_mock()
    proc = start_server(cfg_path, log_path=tmp / "uvi.log")
    try:
        tok = api("POST", "/auth/login", body={"username": "admin", "password": "admin"})["access_token"]
        scan = api("POST", "/files/scan-folder", tok, {"path": str(dump)})
        for fid in scan["file_ids"]:
            wait_file(tok, fid)
        check("библиотека обработана (5 файлов, включая шум)", len(scan["file_ids"]) == 5,
              str(scan.get("file_ids")))

        # --- кейс 1: «что в сметах по вилоновской?» ---
        res = api("POST", "/query", tok, {"q": "что в сметах по вилоновской?"})
        check("группа смет -> чтение файлов целиком",
              res.get("intent") == "deep_read" and len(res.get("files") or []) >= 3,
              str(res)[:200])
        check("материалы в ответе", "Унифлекс" in res["answer"], res["answer"][:150])

        # --- кейс 2: «нужны материалы по отмостке вилоновской» ---
        res = api("POST", "/query", tok, {"q": "нужны материалы по отмостке вилоновской"})
        check("целевой файл (отмостка) прочитан",
              res.get("intent") == "deep_read" and len(res.get("files") or []) == 1
              and "отмостка" in res["files"][0]["file_name"].lower(),
              str(res)[:200])

        # --- кейс 3: RAG-путь — шум отсечён ---
        res = api("POST", "/query", tok, {"q": "какие материалы по вилоновской?"})
        files = res.get("files") or []
        check("RAG ответил с цитатой", "[file_id:" in res["answer"], res["answer"][:150])
        check("уверенность RAG > 0.3 (раньше 0.11 у мусора)",
              float(res.get("confidence") or 0) > 0.3, str(res.get("confidence")))
        check("в файлах ответа нет шума (Конкурсная/Аэр)",
              bool(files) and all("аэр" not in f["file_name"].lower()
                                  and "конкурсная" not in f["file_name"].lower() for f in files),
              str(files))

        status = api("GET", "/status", tok)
        check("/status версия 2.7.0", status.get("version") == "2.7.0",
              str(status.get("version")))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    # --- кейс 4: скрипт сброса при остановленном сервере ---
    env = dict(os.environ, DOC_AGENT_CONFIG=str(cfg_path))
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "reset_database.py"), "--yes"],
                       capture_output=True, text=True, env=env, cwd=str(REPO), timeout=120)
    check("reset_database.py выполнен", r.returncode == 0,
          (r.stdout + r.stderr)[-300:])

    proc = start_server(cfg_path)
    try:
        tok = api("POST", "/auth/login", body={"username": "admin", "password": "admin"})["access_token"]
        card = api("GET", "/card?limit=100", tok)
        card_rows = card.get("items") if isinstance(card, dict) else card
        check("после сброса картотека пуста", not card_rows, str(card_rows)[:120])
        res = api("POST", "/query", tok, {"q": "что в сметах по вилоновской?"})
        check("после сброса «НЕТ ДАННЫХ» вместо галлюцинаций",
              "НЕТ ДАННЫХ" in res.get("answer", ""), str(res)[:150])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock.shutdown()
        if not os.environ.get("SMOKE_KEEP"):  # SMOKE_KEEP=1 — не чистить tmp (отладка)
            shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for s, _ in results if s)
    print(f"\nИтог: {ok}/{len(results)}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
