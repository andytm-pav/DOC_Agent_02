"""Конфигурация приложения.

Все настройки — в config/config.yaml + .env. Код не хардкодит значения.
Поддерживается подстановка "${VAR}" из переменных окружения / .env.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Корень репозитория: src/doc_agent/config.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")

_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _interpolate(node: Any) -> Any:
    """Рекурсивно заменяет ${VAR} на значения из окружения."""
    if isinstance(node, str):
        def sub(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), "")
        return _ENV_RE.sub(sub, node)
    if isinstance(node, dict):
        return {k: _interpolate(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_interpolate(v) for v in node]
    return node


class AppSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "dev-secret"
    data_dir: str = "./data"
    admin_username: str = "admin"
    admin_password: str = "admin"
    storage_subdir: str = "storage"

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    def sub_dir(self, name: str) -> Path:
        d = self.data_path / name
        d.mkdir(parents=True, exist_ok=True)
        return d


class StorageSettings(BaseModel):
    local_paths: list[str] = Field(default_factory=lambda: ["./data/storage"])
    network_paths: list[str] = Field(default_factory=list)


class IngestSettings(BaseModel):
    """Импорт свалки файлов из папки (папку указывает пользователь в UI
    или предзадают здесь) + drag&drop по одному файлу как раньше."""

    folder_paths: list[str] = Field(default_factory=list)
    recursive: bool = True
    # Максимум документов за один импорт; 0 = без лимита (v2.5)
    max_files_per_scan: int = 0
    # Глушить UserWarning библиотек-экстракторов (openpyxl: «Print area
    # cannot be set…», «Workbook contains no default style…») — иначе
    # они забивают консоль и логи при импорте больших свалок.
    suppress_extract_warnings: bool = True
    supported_extensions: list[str] = Field(default_factory=lambda: [
        "pdf", "docx", "xlsx", "xlsm", "pptx", "csv", "txt", "log", "md",
        "eml", "msg", "xml", "gge", "amkr", "arps", "zip",
        "png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "7z", "rar",
    ])


class SortingSettings(BaseModel):
    """Разгребание свалки: агент сам создаёт папку и раскладывает файлы
    по тематическим подпапкам — названия придумывает LLM по содержимому.
    Без LLM (provider: none) — детерминированный fallback из конфига.
    Промпт — config/prompts/sorting.txt (инлайн-промпты запрещены)."""

    enabled: bool = True
    default_output_suffix: str = "_разобрано"
    run_dir_prefix: str = "Разобранная свалка"
    run_dir_time_format: str = "%Y-%m-%d_%H-%M-%S"
    recursive: bool = True
    # Максимум файлов за один запуск; 0 = без лимита (v2.5)
    max_files: int = 0
    text_excerpt_chars: int = 1200
    batch_size: int = 20
    batch_max_chars: int = 12000
    max_folders: int = 20
    max_folder_name_len: int = 60
    misc_folder: str = "Прочее"
    fallback: str = "by_extension"  # by_extension | single
    fallback_folder_template: str = "Файлы {ext}"
    move_files: bool = False
    duplicate_name_template: str = "{stem} ({n}){suffix}"
    llm_retries: int = 1
    poll_interval_ms: int = 1000


class ChatSettings(BaseModel):
    """История чата и память (контекст) беседы.

    История сообщений хранится в БД (chat_messages) и переживает обновление
    страницы. «Очистить контекст» сворачивает активные сообщения в сжатую
    памятку (context_archives; LLM-суммаризация, без LLM — выжимка из
    вопросов) и помечает их неактивными: архив НЕ занимает контекстное окно
    актуального контекста и поднимается по запросу вида «вспомни …»
    (recall_keywords). Промпты — config/prompts/context_summary.txt и
    config/prompts/context_recall.txt (инлайн-промпты запрещены).
    """

    history_load_limit: int = 200
    context_max_messages: int = 20
    context_summary_chars: int = 4000
    archive_title_chars: int = 80
    archives_list_limit: int = 50
    recall_max_archives: int = 3
    recall_max_terms: int = 8
    recall_min_word_len: int = 4
    recall_keywords: list[str] = Field(default_factory=lambda: [
        "вспомни", "вспомнить", "напомни", "прошлый раз",
        "что было раньше", "мы загружали", "мы обсуждали", "в прошлый",
    ])
    status_poll_ms: int = 2000
    health_cache_sec: int = 15
    debug_log_tail: int = 30
    debug_audit_tail: int = 20


class QaSettings(BaseModel):
    """Сервисные ответы чата вне поиска по документам (без LLM, без RAG).

    «Показать все файлы» / «какие файлы…» — список загруженных файлов из БД
    (поиск в том числе по словам в названиях файлов). «Что ты можешь?» —
    подсказка о возможностях из config/prompts/help.txt. Ответ детерминирован
    и всегда фактичен (метаданные файлов), поэтому grounded=True.
    Ключевые слова и лимиты — только config.yaml (секция qa).
    """

    list_files_keywords: list[str] = Field(default_factory=lambda: [
        "покажи все файлы", "покажи файлы", "список файлов", "какие файлы",
        "что за файлы", "какие документы", "список документов",
        "что загружено", "все файлы", "все документы",
    ])
    help_keywords: list[str] = Field(default_factory=lambda: [
        "что ты можешь", "что вы можете", "что умеешь", "что вы умеете",
        "какие возможности", "как пользоваться", "помощь", "help",
    ])
    list_limit: int = 30        # максимум файлов в одном ответе
    name_min_word_len: int = 4  # слова короче не ищутся в названиях файлов
    name_max_terms: int = 8     # максимум поисковых слов в названиях файлов
    name_stopwords: list[str] = Field(default_factory=lambda: [
        "файл", "файла", "файлы", "файлов", "документ", "документы", "документов",
        "покажи", "показать", "список", "какие", "какой", "какая",
        "есть", "были", "загружено", "загруженные", "загрузил", "загрузили",
        "все", "всё", "свой", "моя", "мне", "меня", "чтобы", "которые",
        # v2.5: слова вопросов подсчёта/чтения — в названиях файлов не ищутся
        "сколько", "штук", "всего", "обработал", "обработано", "обработать",
        "прочитай", "прочитать", "открой", "найди", "найти", "поищи",
        "подробно", "полностью", "целиком", "содержимое", "скажи", "дай",
    ])
    # --- v2.5: подсчёт файлов («сколько файлов…», «сколько договоров по …») ---
    count_trigger_words: list[str] = Field(default_factory=lambda: ["сколько"])
    # Слова файлового домена: без них «сколько стоит ремонт…» — это вопрос
    # про содержимое, а не про файлы (подсчёт не перехватываем)
    file_domain_words: list[str] = Field(default_factory=lambda: [
        "файл", "файла", "файлы", "файлов", "документ", "документа",
        "документы", "документов", "картотека", "картотеке", "типов",
        "обработано", "обработал", "загружено", "загрузил",
    ])
    # --- v2.5: поиск по названиям/типам («покажи все КС2», «найди договоры…») ---
    find_files_keywords: list[str] = Field(default_factory=lambda: [
        "покажи все", "показать все", "найди", "найти", "поищи",
        "есть ли файлы", "есть ли документы", "открой файл",
    ])
    # Коды doc_type -> русские подписи (для ответов и каталога)
    doc_type_labels: dict[str, str] = Field(default_factory=lambda: {
        "ks2": "КС-2", "ks3": "КС-3", "ks6": "КС-6", "ttn": "ТТН",
        "ds": "ДС", "id": "ИД", "invoice": "счёт", "contract": "договор",
        "other": "прочее",
    })
    # Слова запроса, мапящиеся на коды doc_type при поиске по типу
    # («покажи все КС2» найдёт и файлы с «КС2» в имени, и doc_type=ks2)
    doc_type_aliases: dict[str, list[str]] = Field(default_factory=lambda: {
        "ks2": ["кс2", "кс-2"], "ks3": ["кс3", "кс-3"], "ks6": ["кс6", "кс-6"],
        "ttn": ["ттн", "трн"], "ds": ["дс"],
        "invoice": ["счёт", "счет", "счета", "счетов"],
        "contract": ["договор", "договора", "договоров", "подряд", "подряда"],
    })
    # Токены НЕ длиннее этого (и токены с цифрами) ищутся в названиях
    # только точным вхождением — иначе «кс2» -> «к» матчит всё подряд,
    # а «23» -> «2» матчит «№27-07-2026» (баг v2.4.1).
    name_exact_max_len: int = 4
    # Искать подсчёт по содержимому чанков, если по названиям/типам 0?
    count_content_fallback: bool = True
    count_content_scan_max_chunks: int = 50000
    # --- v2.5: картотека в промпте репортера (агент «знает» файлы) ---
    catalog_max_files: int = 150
    catalog_max_chars: int = 12000
    catalog_brief_chars: int = 140
    # --- v2.5: подсказка вместо голого «НЕТ ДАННЫХ» ---
    no_data_suggest: bool = True
    # --- v2.5: глубокое чтение файла(ов) по запросу ---
    deep_read_cues: list[str] = Field(default_factory=lambda: [
        "прочитай", "прочитать", "открой файл", "что в файле",
        "что в документе", "содержимое файла", "читай файл",
        "полностью", "целиком", "подробно",
    ])
    deep_read_max_files: int = 3
    deep_read_max_chars: int = 60000
    # Сколько термов вопроса должны совпасть с названием/типом файла,
    # чтобы файл взяли для глубокого чтения/подсказки («сколько листов
    # в смете вилоновской?» — «листов» в имени нет, но «смета»+«вилоновская» есть)
    deep_read_min_terms: int = 2
    deep_read_on_no_data: bool = True
    deep_read_confidence: float = 0.9
    # --- v2.8: ОТКАЗ КАК ПОЛНОЦЕННАЯ ФИЧА (анти-галлюцинация) ---
    # Если ретрив вернул только слабые сигналы (лучший векторный косинус
    # НИЖЕ refuse_vector_below И лучшее лексическое перекрытие НИЖЕ
    # refuse_lexical_below) — LLM не вызывается вовсе: детерминированный
    # отказ «в документах информации не найдено» + подсказка похожих
    # файлов. Раньше мусорные фрагменты шли в промпт и давали «повод»
    # выдумывать. Отказ включается, только ОБА сигнала слабы: сильный
    # хотя бы один (семантика или лексика) — отвечаем.
    refuse_enabled: bool = True
    # Косинусная похожесть лучших выживших векторных хитов (0..1).
    # 0.35 — уверенный минимум для осмысленной семантической связи.
    refuse_vector_below: float = 0.35
    # Доля термов запроса, найденных в лучшем фрагменте после реранкера
    # (0..1). 0.12 — хотя бы ~1 терм из 8 должен быть в тексте.
    refuse_lexical_below: float = 0.12


class PlannerSettings(BaseModel):
    """LLM-планировщик чата (v2.6): вопрос пользователя на естественном
    языке понимает LLM (с картотекой и контекстом беседы) и выбирает
    механизм: подсчёт/список/поиск по картотеке, чтение файла, поиск по
    содержимому (RAG), подсказка или прямой ответ. Жёстких привязок к
    фразам нет — ключевые слова qa.* остаются только офлайн-fallback'ом.
    Промпт — config/prompts/planner.txt (инлайн-промпты запрещены).
    """

    enabled: bool = True
    model: str = "light"             # light | main — какая модель планирует
    timeout_sec: float = 30.0
    retries: int = 1                 # повторов при сбое/не-JSON (E003-стиль)
    max_terms: int = 8               # максимум термов поиска от планировщика
    allowed_actions: list[str] = Field(default_factory=lambda: [
        "count_files", "list_files", "find_files", "read_file",
        "search_content", "help", "direct",
    ])
    allow_direct_reply: bool = True  # прямой ответ на приветствия/благодарности
    # Сбой планировщика или «механизм не дал ответа» -> детерминированные
    # интенты по ключевым словам (qa.*), затем обычный RAG
    fallback_keywords: bool = True
    # Оборачивать списки/подсчёты картотеки в естественный язык через LLM
    # (числа и [file_id:N] копируются из данных без изменений)
    synthesize_lists: bool = True
    context_max_chars: int = 1200    # сколько контекста беседы отдать планировщику
    catalog_for_planner: bool = True # отдавать картотеку планировщику (выбор файла)
    catalog_max_chars: int = 4000


class WatchdogSettings(BaseModel):
    enabled: bool = False
    paths: list[str] = Field(default_factory=lambda: ["./data/inbox"])
    interval_sec: int = 30


class LLMSettings(BaseModel):
    provider: str = "ollama"          # openai_compatible | ollama | none
    base_url: str = "http://localhost:11434"
    api_key: str = ""
    api_path: str = "/chat/completions"
    model_main: str = "qwen2.5:1.5b-instruct-q4_K_M"
    model_light: str = "gemma2:2b-instruct-q4_K_M"
    timeout_sec: float = 60.0
    temperature: float = 0.0
    # v2.8: ретраи при rate-limit (429) и 5xx — бесплатный tier glm-4.5-flash
    # малыми RPM: очередь ингеста валит классификатор 429-ми. Ждём
    # Retry-After, если провайдер отдал, иначе backoff_sec * 2^попытка.
    rate_limit_retries: int = 2
    rate_limit_backoff_sec: float = 2.0
    # Доп. поля тела запроса к OpenAI-совместимому API (передаются как есть).
    # Пример для reasoning-моделей Zhipu/Z.ai (glm-4.5*, glm-4.6):
    #   {"thinking": {"type": "disabled"}} — быстрее и без <think> в ответе.
    extra_body: dict[str, Any] = Field(default_factory=dict)


class EmbeddingApiSettings(BaseModel):
    """Настоящие эмбеддинги через OpenAI-совместимый /embeddings (v2.6).

    По умолчанию наследуют base_url и api_key из секции llm — тот же
    провайдер, что и для основной модели (например Z.ai: embedding-3).
    Пустые base_url/api_key = «взять из llm». Переопределять нужно только
    если эмбеддинг-модель живёт у другого провайдера.
    """

    model: str = "embedding-3"
    base_url: str = ""               # пусто = llm.base_url
    api_key: str = ""                # пусто = llm.api_key
    api_path: str = "/embeddings"
    timeout_sec: float = 60.0
    # Кастомная размерность (v2.7.1): Zhipu embedding-3 принимает 256/512/
    # 1024/2048 (дефолт 2048); OpenAI text-embedding-3-small — 512/1536.
    # 0 = параметр НЕ передаётся (дефолт провайдера). Смена значения меняет
    # векторное пространство -> требуется переиндексация (коллекция
    # подбирается автоматически при vector.auto_collection_suffix: true).
    dimensions: int = 0
    # v2.8: ретраи при 429 (rate-limit) от эмбеддинг-API.
    rate_limit_retries: int = 2
    rate_limit_backoff_sec: float = 2.0


class EmbeddingsSettings(BaseModel):
    # v2.7: backend auto — api, если доступен ключ/base_url (llm.* или
    # embeddings.api.*), иначе hashing. Псевдо-эмбеддинги (hashing) — это
    # лексическое совпадение токенов, НЕ семантика: они и были причиной
    # мусорной выдачи на реальных вопросах.
    backend: str = "auto"             # auto | hashing | sentence_transformers | api
    model: str = "intfloat/multilingual-e5-small"
    batch_size: int = 32
    # v2.7: морфология (Snowball ru) для ЛЕКСИЧЕСКИХ механизмов — BM25,
    # реранкер, hashing-эмбеддинги, grounding. Для api/sentence_transformers
    # НЕ применяется (модели сами понимают флексию, обрезка им вредит).
    # После включения/выключения нужна переиндексация (векторный пейсмаж
    # меняется при hashing-бэкенде).
    stem_lexical: bool = True
    # --- v2.9: ЛОКАЛЬНАЯ МОДЕЛЬ (backend: sentence_transformers) ---
    # Поля device/dimensions/query_prefix/passage_prefix применяются
    # ТОЛЬКО к локальному бэкенду (api/hashing их игнорируют).
    # Модель качается с huggingface.co при ПЕРВОМ старте (e5-small ~470 МБ),
    # далее живёт в кэше HF и работает офлайн. Медленная сеть — переменная
    # окружения HF_ENDPOINT=https://hf-mirror.com перед запуском.
    # Устройство вычисления: "" = авто (CUDA, если доступна, иначе CPU);
    # "cpu" — принудительно CPU; "cuda" — при установленном CUDA-torch.
    device: str = ""
    # Переопределение размерности локальной модели: 0 = взять фактическую
    # из модели после загрузки (e5-small = 384, bge-m3 = 1024). Задайте,
    # если хотите видеть dim в диагностике до первого запуска. Смена
    # значения = новое векторное пространство = новая коллекция (авто
    # при vector.auto_collection_suffix: true).
    dimensions: int = 0
    # E5-модели требуют префиксов "query: "/"passage: " — без них качество
    # поиска заметно падает. Другим локальным моделям (BAAI/bge-m3,
    # paraphrase-multilingual-*) префиксы не нужны: поставьте "".
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    # backend: api — настоящий эмбеддинг по API (v2.6), без отдельного ключа:
    # наследует base_url/api_key секции llm, если не переопределено тут.
    api: EmbeddingApiSettings = Field(default_factory=EmbeddingApiSettings)


class VectorSettings(BaseModel):
    backend: str = "chroma"           # chroma | lite
    collection: str = "chunks"
    metric: str = "cosine"
    # v2.7: изоляция векторных пространств — коллекция получает суффикс
    # «-{backend}-{модель}-{hash}». Смена backend/модели больше НЕ смешивает
    # старые и новые векторы в одной коллекции (жалоба «наложились старые
    # псевдоэмбеддинги на новые»): старая коллекция просто перестаёт
    # использоваться, переиндексация пишется в новую.
    auto_collection_suffix: bool = True


class RetrievalSettings(BaseModel):
    """Параметры гибридного ретрива (v2.7, промышленные практики).

    Гибрид BM25+вектор с RRF — стандарт (Elastic/Weaviate/Qdrant docs,
    provod.ai 2026); порог отсева слабых векторных хитов и буст файлов с
    совпадением по имени (contextual signal) — практики production RAG;
    Contextual Retrieval (Anthropic, 2024) — контекст документа в каждом
    чанке (в нашем случае — преамбула имени файла/листа).
    """

    # Верхняя граница чанков, отдаваемых в BM25 (защита от OOM).
    # v2.7: раньше был молчаливый LIMIT 4000 БЕЗ сортировки — чанки
    # поздних файлов вообще не участвовали в поиске.
    max_chunks: int = 200000
    # Доля от лучшего векторного score, ниже которой хиты отсеиваются ДО
    # слияния (0 = без отсева). Убирает «мусор с 0.11 похожести» из промпта.
    vector_relative_cutoff: float = 0.55
    # Мультипликативный буст RRF-score чанков файлов, чьё ИМЯ содержит
    # термы запроса («вилоновская» -> все сметы Вилоновской выше прочих).
    # Общий сигнальный механизм, без привязок к конкретным фразам.
    filename_boost: float = 0.35
    # Вес источников при RRF-слиянии (индивидуальные списки ранжирования).
    bm25_weight: float = 1.0
    vector_weight: float = 1.0
    # Минимальная доля термов запроса в реранкере: фрагменты с нулевым
    # лексическим перекрытием выкидываются, если есть хоть один с перекрытием.
    rerank_drop_zero_overlap: bool = True


class RerankerSettings(BaseModel):
    backend: str = "simple"           # simple | cross_encoder
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 5


class ChunkingSettings(BaseModel):
    size_tokens: int = 512
    overlap_tokens: int = 64
    # v2.6.1: преамбула «[имя_файла] » в тексте каждого чанка — без неё
    # строки смет из xlsx не содержат имени объекта («Вилоновская») и не
    # находятся ни BM25, ни векторным поиском по содержимому.
    filename_prefix: bool = True
    # v2.7: табличные форматы (xlsx/xlsm/csv) чанкуются ПО СТРОКАМ — чанк
    # никогда не режет строку посередине (раньше «Унифлекс ЭПП... рул»
    # обрывался, материал терялся). Листовые заголовки и шапка колонок
    # попадают в преамбулу каждого чанка (contextual retrieval).
    table_aware: bool = True
    # Повторять шапку таблицы в каждом чанке (для KV-строк это уже
    # «Заголовок: значение», флаг добавляет строку шапки первой строкой чанка).
    table_header_in_chunk: bool = True
    # Форматы, обрабатываемые табличным чанкингом (по строкам/листам).
    table_formats: list[str] = Field(default_factory=lambda: ["xlsx", "xlsm", "csv"])
    # --- v2.8: КОНТЕКСТУАЛЬНЫЕ ПРЕАМБУЛЫ (Contextual Retrieval, Anthropic
    # 2024; промышленно даёт +18 п.п. recall@5 на вопросах-синтезах) ---
    # В начало КАЖДОГО чанка перед эмбеддингом и индексацией добавляется
    # контекст: имя документа (+лист), путь заголовков главы, однострочная
    # заметка о том, чему посвящён документ. Смысл внутри чанка важнее
    # арифметики размеров.
    # Однострочная заметка о документе: 1 LLM-вызов на файл (model_light),
    # результат кэшируется в File.description. При llm.provider: none или
    # сбое — детерминированный fallback из метаданных классификатора.
    context_note: bool = True
    # Максимальная длина заметки (символы).
    note_max_chars: int = 160
    # Путь заголовков главы («Смета > Материалы») в преамбуле чанков:
    # строится по дереву документа (extractor) без LLM.
    headings_in_prefix: bool = True


class OcrSettings(BaseModel):
    engine: str = "tesseract"         # tesseract | paddle | none
    tesseract_cmd: str = ""
    tesseract_langs: list[str] = Field(default_factory=lambda: ["rus", "eng"])
    min_confidence: float = 0.80
    reject_threshold: float = 0.50
    process_embedded_images: bool = False


class GroundrailsSettings(BaseModel):
    enabled: bool = True
    cut_ratio: float = 0.30
    # v2.6.1: confidence = среднее TOP-K score фрагментов (раньше — минимум
    # из 5, что давало «уверенность: 0» при одном слабом фрагменте).
    confidence_top_k: int = 3
    # v2.7: калиброванная уверенность = w_retrieval * среднее TOP-K score
    # ретрива + w_grounding * доля переживших grounding-валидацию утверждений.
    # Голый retrieval-score не откалиброван (0.11 у мусора), голый grounding
    # не чувствует полноты выдачи — смесь даёт осмысленную шкалу 0..1.
    confidence_retrieval_weight: float = 0.6
    confidence_grounding_weight: float = 0.4


class A2ASettings(BaseModel):
    enabled: bool = True
    agent_name: str = "document-agent"
    auth_required: bool = False


class LimitsSettings(BaseModel):
    max_file_mb: int = 500
    max_query_len: int = 2000


class ApiKeySettings(BaseModel):
    """Ключ доступа к API агента из внешних систем (без логина).

    Ключ передаётся в заголовке ``X-API-Key`` (или ``Authorization: Bearer``).
    Значение удобно хранить в .env и подставлять как ``${EXTERNAL_API_KEY}``.
    Пустой ``key`` — запись отключена. ``name`` попадает в audit_log
    как имя вызывающей стороны (actor ``api:<name>``).
    """

    key: str = ""
    name: str = "external-system"
    role: str = "user"  # user | admin


class AuthSettings(BaseModel):
    token_expire_minutes: int = 1440
    api_keys: list[ApiKeySettings] = Field(default_factory=list)


class Settings(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    sorting: SortingSettings = Field(default_factory=SortingSettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    qa: QaSettings = Field(default_factory=QaSettings)
    planner: PlannerSettings = Field(default_factory=PlannerSettings)
    watchdog: WatchdogSettings = Field(default_factory=WatchdogSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    vector: VectorSettings = Field(default_factory=VectorSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    reranker: RerankerSettings = Field(default_factory=RerankerSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    groundrails: GroundrailsSettings = Field(default_factory=GroundrailsSettings)
    a2a: A2ASettings = Field(default_factory=A2ASettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    _raw: dict[str, Any] = {}

    @property
    def config_dir(self) -> Path:
        return REPO_ROOT / "config"


def _config_file() -> Path:
    custom = os.environ.get("DOC_AGENT_CONFIG")
    return Path(custom) if custom else REPO_ROOT / "config" / "config.yaml"


def load_settings() -> Settings:
    """Загружает config.yaml (каждый вызов — свежие данные, удобно для тестов)."""
    path = _config_file()
    data: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data = _interpolate(data)
    cfg = Settings(**data)
    cfg._raw = data  # type: ignore[attr-defined]
    return cfg
