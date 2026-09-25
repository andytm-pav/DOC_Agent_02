# Документовед v2.0

Локальный ИИ-агент для работы с документами. Без облака, без телеметрии, без внешних API.

## Возможности

- 📥 Приём «свалки» файлов (PDF, DOCX, XLSX, JPG, EML, ZIP)
- 🔍 Извлечение данных (OCR, парсинг таблиц)
- 📇 Построение картотеки с 15 колонками
- 💬 Ответы на вопросы с grounding (защита от галлюцинаций)
- 🔄 Воспроизведение документов (DOCX, XLSX, PDF, HTML, MD)
- 🤝 Взаимодействие с другими агентами по A2A

## Быстрый старт

```bash
# Клонировать репозиторий
git clone <repo-url>
cd document-agent

# Запустить одной командой
make run

# Открыть в браузере
open http://localhost:8000
```

## Требования

- Docker 24+ и docker-compose v2
- 8 ГБ RAM (для моделей LLM)
- 10 ГБ свободного места

## Структура

```
├── config/          — конфигурация и промпты
├── src/doc_agent/   — исходный код
│   ├── api/         — FastAPI роуты
│   ├── db/          — SQLAlchemy модели
│   ├── extractors/  — парсеры документов
│   ├── llm/         — Ollama клиент
│   ├── services/    — бизнес-логика
│   ├── subagents/   — субагенты
│   └── vector/      — ChromaDB + эмбеддинги
├── tests/           — pytest тесты
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## API

| Метод | Путь | Описание |
|-------|------|----------|
| POST | /auth/login | Аутентификация |
| POST | /files/upload | Загрузка файла |
| POST | /query | Запрос к документам |
| GET | /query/card | Картотека |
| GET | /query/card/export.xlsx | Экспорт XLSX |
| POST | /a2a | A2A протокол |
| GET | /health | Проверка состояния |

## Тестирование

```bash
make test
# или
ruff check . && mypy . && pytest -x
```

## Конфигурация

Основные настройки в `config/config.yaml`:
- Модели LLM: `qwen2.5:1.5b-instruct-q4_K_M` (основная), `gemma2:2b-instruct-q4_K_M` (лёгкая)
- Эмбеддинги: `intfloat/multilingual-e5-small` (384 dim)
- OCR: Tesseract (rus + eng)

## Лицензия

MIT
