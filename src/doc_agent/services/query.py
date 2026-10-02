"""Query-конвейер, v2.6 — LLM-first:

    вопрос (естественный язык)
        -> 1. LLM-планировщик: понимает вопрос (с картотекой и контекстом
           беседы) и выбирает механизм — services/planner.py;
        -> 2. детерминированный механизм по плану: картотека/подсчёт/поиск
           по названиям (services/intents.py), глубокое чтение
           (services/deep_read.py) или поиск по содержимому (RAG);
        -> 3. LLM-синтез: ответ оборачивается в естественный язык
           (reporter.txt / deep_read.txt / synthesis.txt).

Жёстких привязок к фразам нет. Ключевые слова qa.* и явные просьбы
deep_read_cues — только офлайн-fallback (llm.provider: none или сбой
планировщика; planner.fallback_keywords). Без плана автодочтение после
«НЕТ ДАННЫХ» работает как в v2.5.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from doc_agent.config import load_settings
from doc_agent.db.migrations import log_audit
from doc_agent.db.session import get_session_factory
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger
from doc_agent.services.deep_read import try_deep_read
from doc_agent.services.intents import (
    catalog_block,
    count_files_answer,
    find_files_answer,
    help_text,
    intent_result,
    list_files_answer,
    no_data_hint,
    try_service_intent,
)
from doc_agent.services.planner import build_plan
from doc_agent.subagents.classifier_agent import extract_filters_from_query
from doc_agent.subagents.reporter_agent import NO_DATA, ReporterAgent
from doc_agent.subagents.retriever_agent import RetrieverAgent
from doc_agent.subagents.validator_agent import ValidatorAgent

log = get_logger("services.query")

_retriever = RetrieverAgent()
_reporter = ReporterAgent()
_validator = ValidatorAgent()

# v2.8: отказ как полноценная фича (не сбой): детерминированный ответ при
# слабых сигналах ретрива — вместо передачи мусорных фрагментов в LLM
# (именно мусор в промпте давал «повод» галлюцинировать). Текст честный:
# данных нет, отвечать догадками агент не будет.
REFUSAL_TEXT = (
    "НЕТ ДАННЫХ. В загруженных документах информации по вашему запросу не "
    "найдено — отвечать по догадкам не буду. Загрузите подходящие файлы или "
    "переформулируйте запрос."
)


def _weak_retrieval(fragments: list[dict], stats: dict) -> bool:
    """v2.8: сигналы ретрива слишком слабы для ответа (qa.refuse_*).

    Отказ ТОЛЬКО когда ОБА сигнала ниже порогов: сильный хотя бы один
    (семантический косинус или лексическое перекрытие) — отвечаем.
    Если векторный бэкенд недоступен/пуст (best_vector_cosine = 0), гейт
    вырождается в лексический — BM25-совпадения всё равно отвечают."""
    s = load_settings().qa
    if not s.refuse_enabled:
        return False
    best_vec = max(float(stats.get("best_vector_cosine") or 0.0), 0.0)
    best_lex = max(float(stats.get("best_lexical") or 0.0),
                   max((float(f.get("score") or 0.0) for f in fragments), default=0.0))
    return best_vec < s.refuse_vector_below and best_lex < s.refuse_lexical_below


def _refusal(question: str, db: Session, filters: dict) -> dict:
    """Детерминированный отказ + подсказка похожих файлов картотеки."""
    result: dict = {
        "answer": REFUSAL_TEXT, "files": [], "confidence": 0.0,
        "grounded": False, "partial": False, "filters": filters,
        "intent": "refusal",
    }
    hint = no_data_hint(question, db)
    if hint:
        result["answer"] += "\n\n" + hint
    log_audit("query", "query_answered", {
        "q": question[:200], "intent": "refusal", "no_data": True, "files": [],
    })
    return result


def _maybe_synthesize(question: str, res: dict) -> dict:
    """Обернуть детерминированные данные картотеки (список/подсчёт) в
    естественный язык через LLM (planner.synthesize_lists). Числа и
    [file_id:N] копируются из данных без изменений (промпт synthesis.txt);
    сбой LLM -> детерминированный текст как есть."""
    s = load_settings()
    if not s.planner.synthesize_lists or s.llm.provider == "none":
        return res
    try:
        prompt = get_prompt("synthesis", question=question, facts=res["answer"])
        answer = get_llm().chat(prompt, model=s.llm.model_light).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("synthesis_failed", error=str(exc))
        return res
    if not answer:
        return res
    out = dict(res)
    out["answer"] = answer
    return out


def _run_plan(question: str, db: Session, plan: dict[str, Any]) -> dict | None:
    """Исполняет план планировщика детерминированным механизмом.

    None — механизм не смог дать ответ (например, read_file без совпадений):
    вопрос уходит в обычную обработку (fallback-интенты / RAG).
    """
    s = load_settings()
    action = plan.get("action")
    terms = plan.get("terms") or []
    doc_type = plan.get("doc_type")

    if action == "direct":
        reply = (plan.get("reply") or "").strip()
        if reply and s.planner.allow_direct_reply:
            log_audit("query", "query_answered", {
                "q": question[:200], "intent": "direct",
            })
            return {
                "answer": reply, "files": [], "confidence": 1.0,
                "grounded": False, "partial": False, "filters": {},
                "intent": "direct",
            }
        return None
    if action == "help":
        text = help_text()
        if text:
            return intent_result(text, [], "help", question)
        return None
    if action == "list_files":
        return _maybe_synthesize(
            question, list_files_answer(question, db, terms=terms, doc_type=doc_type))
    if action == "count_files":
        return _maybe_synthesize(
            question, count_files_answer(question, db, terms=terms, doc_type=doc_type))
    if action == "find_files":
        found = find_files_answer(question, db, terms=terms, doc_type=doc_type)
        if found is None:
            return None
        return _maybe_synthesize(question, found)
    if action == "read_file":
        return try_deep_read(
            question, db, require_cue=False,
            file_ids=plan.get("file_ids") or None, terms=terms or None)
    # search_content — обычный RAG-путь ниже (с search_query/doc_type плана)
    return None


def run_query(
    question: str, limit: int = 20, db: Session | None = None, context: str | None = None,
) -> dict:
    """context — актуальный контекст беседы (прошлые сообщения); передаётся
    планировщику и репортеру. Заархивированная беседа сюда не попадает
    (services.chat)."""
    settings = load_settings()
    question = (question or "").strip()[: settings.limits.max_query_len]

    own_db = db is None
    if db is None:
        db = get_session_factory()()

    try:
        # 1. LLM-планировщик: понимает вопрос и выбирает механизм.
        #    provider none / сбой -> план нет (детерминированный fallback).
        plan = build_plan(question, db, context)

        # 2. механизм по плану
        if plan is not None:
            routed = _run_plan(question, db, plan)
            if routed is not None:
                return routed
            # механизм не дал ответа (не search_content — тот идёт в RAG)
            # -> детерминированные интенты (отключаются planner.fallback_keywords)
            if plan.get("action") != "search_content" and \
                    load_settings().planner.fallback_keywords:
                service = try_service_intent(question, db)
                if service is not None:
                    return service
        else:
            # 2b. офлайн-fallback (без LLM/планировщика): интенты по
            #     ключевым словам из конфига + явная просьба прочитать файл
            service = try_service_intent(question, db)
            if service is not None:
                return service
            deep = try_deep_read(question, db, require_cue=True)
            if deep is not None:
                return deep

        # 3. RAG: фильтры (с doc_type плана) + переформулированный запрос
        filters = extract_filters_from_query(
            question, prefill={"doc_type": plan.get("doc_type")} if plan else None)
        search_query = (plan or {}).get("search_query") or question
        stats: dict = {}
        fragments, _candidates = _retriever.run(db, search_query, filters, limit=limit,
                                                stats=stats)

        # 3.5 v2.8: ОТКАЗ КАК ФИЧА — ретрив не нашёл ничего осмысленного
        #     (оба сигнала слабы): LLM не вызывается, честный отказ +
        #     подсказка. Автодочтение по плану сохранено (могут найтись
        #     файлы по названиям).
        if _weak_retrieval(fragments, stats):
            if (plan and (plan.get("file_ids") or plan.get("terms"))) or \
                    load_settings().qa.deep_read_on_no_data:
                deep = try_deep_read(
                    question, db, require_cue=False,
                    file_ids=(plan or {}).get("file_ids") or None,
                    terms=(plan or {}).get("terms") or None,
                )
                if deep is not None:
                    return deep
            return _refusal(question, db, filters)

        # 4. reporter (LLM или экстрактивный); картотека — чтобы агент
        #    «знал», какие файлы вообще есть в картотеке
        raw_answer = _reporter.run(
            question, fragments, context=context, catalog=catalog_block(db))

        # 5-6. groundrails + числовая валидация
        validated = _validator.run(raw_answer, fragments)

        files_payload: dict[int, dict] = {}
        for fr in fragments[:5]:
            files_payload.setdefault(fr["file_id"], {
                "file_id": fr["file_id"], "file_name": fr["file_name"], "doc_type": fr["doc_type"],
            })
        no_data = validated["answer"].strip() == NO_DATA

        # 6.5 автодочтение: обычный поиск сказал «НЕТ ДАННЫХ» — если план
        #     указал файлы/термы, читаем их; иначе как в v2.5 (по терсам
        #     вопроса, при deep_read_on_no_data)
        if no_data and (
            (plan and (plan.get("file_ids") or plan.get("terms")))
            or load_settings().qa.deep_read_on_no_data
        ):
            deep = try_deep_read(
                question, db, require_cue=False,
                file_ids=(plan or {}).get("file_ids") or None,
                terms=(plan or {}).get("terms") or None,
            )
            if deep is not None:
                return deep

        result = {
            "answer": validated["answer"],
            "files": list(files_payload.values()),
            # v2.7: калиброванная уверенность — смесь retrieval-score TOP-K
            # и доли утверждений, переживших grounding-валидацию
            "confidence": 0.0 if no_data else _validator.confidence(
                fragments, grounding_ratio=1.0 - validated.get("cut_ratio", 0.0)),
            "grounded": bool(validated["grounded"]) and not no_data,
            "partial": bool(validated.get("partial")),
            "filters": filters,
            "cut_ratio": validated.get("cut_ratio", 0.0),
        }
        # 6.7 вместо голого «НЕТ ДАННЫХ» — подсказка похожих файлов картотеки
        if no_data:
            hint = no_data_hint(question, db)
            if hint:
                result["answer"] = result["answer"] + "\n\n" + hint
        log_audit("query", "query_answered", {
            "q": question[:200],
            "grounded": result["grounded"],
            "partial": result["partial"],
            "no_data": no_data,
            "planned": bool(plan),
            "files": [f["file_id"] for f in result["files"]],
        })
        return result
    finally:
        if own_db:
            db.close()
