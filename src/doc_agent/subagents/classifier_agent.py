"""ClassifierAgent: LLM-классификация (строгий JSON) с регламентом E003/E004
и офлайн-fallback по правилам config/rules.yaml."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import yaml

from doc_agent.config import REPO_ROOT, load_settings
from doc_agent.llm.ollama_client import get_llm
from doc_agent.llm.prompts import get_prompt
from doc_agent.logging import get_logger
from doc_agent.utils.json_extract import extract_json

log = get_logger("subagent.classifier")


def _load_yaml(name: str) -> dict:
    path = REPO_ROOT / "config" / name
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _parse_amount(raw: str) -> float | None:
    cleaned = re.sub(r"[^\d,.]", "", raw).replace(" ", "").replace(",", ".")
    if not cleaned or not any(ch.isdigit() for ch in cleaned):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_iso(d: str) -> str | None:
    m = re.match(r"(\d{2})[.](\d{2})[.](\d{4})", d.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    try:
        return datetime.strptime(d.strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


class RulesEngine:
    """Офлайн-классификация по rules.yaml — тоже fallback E003/E004."""

    def __init__(self) -> None:
        rules = _load_yaml("rules.yaml")
        self.doc_patterns: dict[str, list[str]] = rules.get("doc_type_patterns", {})
        self.contract_patterns: list[str] = rules.get("contract_patterns", [])
        self.doc_number_patterns: list[str] = rules.get("doc_number_patterns", [])
        self.amount_patterns: list[str] = rules.get("amount_patterns", [])
        self.date_patterns: list[str] = rules.get("date_patterns", [])
        cities_file = REPO_ROOT / "config" / "cities.txt"
        self.cities: list[str] = (
            cities_file.read_text(encoding="utf-8").splitlines() if cities_file.exists() else []
        )
        self.cities = [c.strip() for c in self.cities if c.strip()]

    def classify(self, text: str) -> dict:
        head = text[:4000]
        low = head.lower()
        out: dict[str, Any] = {
            "doc_type": "other",
            "city": None,
            "customer": None,
            "contract_no": None,
            "contract_date": None,
            "doc_number": None,
            "doc_date": None,
            "amount": None,
            "confidence": 0.55,
        }
        for doc_type, patterns in self.doc_patterns.items():
            for pat in patterns:
                if re.search(pat, head, re.IGNORECASE):
                    out["doc_type"] = doc_type
                    out["confidence"] = 0.75
                    break
            if out["doc_type"] != "other":
                break
        # Улучшенный паттерн: формы «договору/договора/договором» + номер
        m = re.search(
            r"(?:по\s+)?(?:договор|контракт)(?:у|а|е|ом)?\s*(?:№\s*)?(\d[\w\-/]*)",
            head,
            re.IGNORECASE,
        )
        if m:
            out["contract_no"] = m.group(1).strip(". ")
        else:
            for pat in self.contract_patterns:
                m = re.search(pat, head, re.IGNORECASE)
                if m:
                    out["contract_no"] = m.group(1).strip(". ")
                    break
        for pat in self.doc_number_patterns:
            m = re.search(pat, head)
            if m:
                out["doc_number"] = m.group(1).strip(". ")
                break
        for pat in self.amount_patterns:
            m = re.search(pat, head, re.IGNORECASE)
            if m:
                val = _parse_amount(m.group(1))
                if val:
                    out["amount"] = val
                    break
        dates = []
        for pat in self.date_patterns:
            for m in re.finditer(pat, head):
                iso = _to_iso(m.group(0))
                if iso:
                    dates.append(iso)
        if dates:
            out["doc_date"] = dates[0]
        for city in self.cities:
            if city.lower() in low:
                out["city"] = city
                break
        # Заказчик: "Заказчик: <name>" / "Заказчик <name>"
        m = re.search(r"(?:Заказчик|Заказчик:)\s*[:：]?\s*([А-ЯЁA-Z][^\n,;]{2,80})", head)
        if m:
            out["customer"] = m.group(1).strip()
        return out


class ClassifierAgent:
    name = "classifier"

    def __init__(self) -> None:
        self.rules = RulesEngine()

    def run(self, text: str) -> dict:
        """LLM → валидный JSON; E003: retry 1 раз; E004/E003-fail → rules.yaml."""
        settings = load_settings()
        base = self.rules.classify(text)
        if settings.llm.provider == "none":
            return base
        prompt = get_prompt("classifier", text=text[:6000])
        llm = get_llm()
        for attempt in (1, 2):  # E003: retry 1 раз
            try:
                raw = llm.chat(prompt, model=settings.llm.model_main)
                data = self._extract_json(raw)
                return self._merge(base, data)
            except Exception as exc:  # noqa: BLE001
                log.warning("classify_attempt_failed", attempt=attempt, error=str(exc))
        # E003 исчерпан → офлайн-правила (документированная деградация ТЗ п.15)
        log.info("classify_fallback_rules")
        return base

    def _extract_json(self, raw: str) -> dict:
        # extract_json переживает <think>, ограждения ```json и текст вокруг JSON
        data = extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError("LLM вернул не-JSON объект (E003)")
        return data

    def _merge(self, base: dict, llm: dict) -> dict:
        """LLM-поля доверенные, если не null и валидны; правила — fallback."""
        merged = dict(base)
        valid_types = {"ks2", "ks3", "ks6", "ttn", "ds", "id", "invoice", "contract", "other"}
        if llm.get("doc_type") in valid_types:
            merged["doc_type"] = llm["doc_type"]
        for key in ("city", "customer", "contract_no", "doc_number"):
            val = llm.get(key)
            if isinstance(val, str) and val.strip() and val.strip().lower() != "null":
                merged[key] = val.strip()
        for key in ("contract_date", "doc_date"):
            val = llm.get(key)
            if isinstance(val, str):
                iso = _to_iso(val)
                if iso:
                    merged[key] = iso
        amount = llm.get("amount")
        if isinstance(amount, (int, float)) and amount >= 0:
            merged["amount"] = float(amount)
        try:
            merged["confidence"] = max(0.0, min(1.0, float(llm.get("confidence", base["confidence"]))))
        except (TypeError, ValueError):
            pass
        return merged


def extract_filters_from_query(query: str, prefill: dict | None = None) -> dict:
    """Извлечение фильтров из вопроса (8.2 шаг 1): правила + LLM при доступности.

    prefill (v2.6) — фильтры уже распознанные LLM-планировщиком (doc_type и
    т.п.); они приоритетнее правил, а LLM-уточнение не запускается — экономия
    одного запроса к API на каждый вопрос.
    """
    rules = RulesEngine()
    filters: dict[str, Any] = {}
    low = query.lower()
    # doc_type: обратные паттерны (кс2 -> ks2)
    alias = {"кс2": "ks2", "кс-2": "ks2", "кс3": "ks3", "кс-3": "ks3", "кс6": "ks6", "кс-6": "ks6",
             "ттн": "ttn", "дс": "ds", "ид": "id", "упд": "invoice", "счёт-фактура": "invoice",
             "счет-фактура": "invoice", "договор": "contract", "контракт": "contract"}
    for token, doc_type in alias.items():
        if re.search(rf"\b{re.escape(token)}\b", low):
            filters["doc_type"] = doc_type
            break
    pre = prefill or {}
    if pre.get("doc_type"):
        filters["doc_type"] = pre["doc_type"]
    m = re.search(
        r"(?:по\s+)?(?:договор|контракт)(?:у|а|е|ом)?\s*(?:№\s*)?(\d[\w\-/]*)",
        query,
        re.IGNORECASE,
    )
    if m and m.group(1):
        filters["contract_no"] = m.group(1).strip(". ")
    else:
        for pat in rules.contract_patterns:
            m = re.search(pat, query, re.IGNORECASE)
            if m and m.group(1):
                filters["contract_no"] = m.group(1).strip(". ")
                break
    for city in rules.cities:
        if city.lower() in low:
            filters["city"] = city
            break
    m = re.search(r"(\d{2})[.](\d{2})[.](\d{4})", query)
    if m:
        filters["date_from"] = _to_iso(m.group(0))
        filters["date_to"] = filters["date_from"]
    # LLM-уточнение фильтров (не критично при недоступности); с prefill
    # от планировщика не нужно — он уже понял вопрос
    settings = load_settings()
    if settings.llm.provider != "none" and len(filters) < 2 and not pre:
        try:
            llm = get_llm()
            prompt = (
                "Извлеки фильтры из вопроса. Верни СТРОГО JSON: "
                '{"doc_type": "ks2|ks3|ks6|ttn|ds|id|invoice|contract|other|null", '
                '"contract_no": "строка|null", "city": "строка|null", "date_from": "YYYY-MM-DD|null", '
                '"date_to": "YYYY-MM-DD|null"}\nВопрос: ' + query
            )
            raw = llm.chat(prompt, model=settings.llm.model_light, timeout=20)
            data = extract_json(raw)
            for k in ("doc_type", "contract_no", "city", "date_from", "date_to"):
                v = data.get(k)
                if isinstance(v, str) and v.strip().lower() not in ("", "null", "none"):
                    filters.setdefault(k, v.strip())
        except Exception as exc:  # noqa: BLE001
            log.debug("filter_llm_skipped", error=str(exc))
    return filters
