import { useState } from 'react';
import {
  Book, Server, Database, Cpu, FileCode, Shield, Workflow,
  CheckCircle2, Circle, ArrowRight, Copy, Check,
  Layers, GitBranch, Zap, AlertTriangle, Package
} from 'lucide-react';

type Section = 'overview' | 'stack' | 'structure' | 'schema' | 'api' | 'prompts' | 'algo' | 'dd';

const sections: { id: Section; label: string; icon: typeof Book }[] = [
  { id: 'overview', label: 'Обзор и цель', icon: Book },
  { id: 'stack', label: 'Технологический стек', icon: Layers },
  { id: 'structure', label: 'Структура репозитория', icon: GitBranch },
  { id: 'schema', label: 'Схемы данных', icon: Database },
  { id: 'api', label: 'API-контракты', icon: FileCode },
  { id: 'prompts', label: 'Промпты субагентов', icon: Cpu },
  { id: 'algo', label: 'Алгоритмы', icon: Workflow },
  { id: 'dd', label: 'Definition of Done', icon: Shield },
];

export default function DocsPage() {
  const [activeSection, setActiveSection] = useState<Section>('overview');
  const [copiedBlock, setCopiedBlock] = useState<string | null>(null);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedBlock(id);
    setTimeout(() => setCopiedBlock(null), 2000);
  };

  const CodeBlock = ({ code, id, lang = 'text' }: { code: string; id: string; lang?: string }) => (
    <div className="relative group rounded-lg overflow-hidden bg-slate-900 border border-slate-700">
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-800 border-b border-slate-700">
        <span className="text-[10px] font-mono text-slate-400 uppercase">{lang}</span>
        <button
          onClick={() => copyToClipboard(code, id)}
          className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-white transition-colors"
        >
          {copiedBlock === id ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copiedBlock === id ? 'Скопировано' : 'Копировать'}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto text-xs text-slate-300 font-mono leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );

  return (
    <div className="h-full flex overflow-hidden">
      {/* Section nav */}
      <aside className="w-64 bg-white border-r border-slate-200 overflow-y-auto flex-shrink-0 hidden lg:block">
        <div className="p-4">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Разделы ТЗ v2.0</h3>
          <nav className="space-y-0.5">
            {sections.map(s => {
              const Icon = s.icon;
              return (
                <button
                  key={s.id}
                  onClick={() => setActiveSection(s.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors text-left ${
                    activeSection === s.id
                      ? 'bg-primary-50 text-primary-700 font-medium'
                      : 'text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <span>{s.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="p-4 border-t border-slate-100">
          <div className="p-3 rounded-lg bg-gradient-to-br from-primary-50 to-accent-50 border border-primary-100">
            <p className="text-xs font-semibold text-primary-900 mb-1">Статус проекта</p>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-xs text-primary-700">implementation-ready</span>
            </div>
            <p className="text-[10px] text-primary-600 mt-1">Python 3.12+ • FastAPI • Ollama</p>
          </div>
        </div>
      </aside>

      {/* Content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto p-6 lg:p-8">
          {activeSection === 'overview' && <OverviewSection />}
          {activeSection === 'stack' && <StackSection CodeBlock={CodeBlock} />}
          {activeSection === 'structure' && <StructureSection CodeBlock={CodeBlock} />}
          {activeSection === 'schema' && <SchemaSection CodeBlock={CodeBlock} />}
          {activeSection === 'api' && <ApiSection CodeBlock={CodeBlock} />}
          {activeSection === 'prompts' && <PromptsSection CodeBlock={CodeBlock} />}
          {activeSection === 'algo' && <AlgoSection />}
          {activeSection === 'dd' && <DDSection />}
        </div>
      </main>
    </div>
  );
}

function OverviewSection() {
  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Локальный ИИ-агент «Документовед»</h1>
        <p className="text-sm text-slate-500 mt-1">Техническое задание v2.0 • implementation-ready</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
            <Server className="w-4 h-4 text-primary-600" />
            Контекст и цель
          </h3>
          <p className="text-sm text-slate-600 mb-3">
            Локальный агент на ПК пользователя. <strong>Без облака, без телеметрии, без внешних API.</strong>
          </p>
          <ul className="space-y-1.5 text-sm text-slate-700">
            <li className="flex items-start gap-2"><ArrowRight className="w-3 h-3 mt-1 text-primary-500 flex-shrink-0" />Принимает «свалку» файлов</li>
            <li className="flex items-start gap-2"><ArrowRight className="w-3 h-3 mt-1 text-primary-500 flex-shrink-0" />Извлекает данные (OCR, парсинг)</li>
            <li className="flex items-start gap-2"><ArrowRight className="w-3 h-3 mt-1 text-primary-500 flex-shrink-0" />Строит картотеку</li>
            <li className="flex items-start gap-2"><ArrowRight className="w-3 h-3 mt-1 text-primary-500 flex-shrink-0" />Отвечает на вопросы (с grounding)</li>
            <li className="flex items-start gap-2"><ArrowRight className="w-3 h-3 mt-1 text-primary-500 flex-shrink-0" />Воспроизводит документы</li>
            <li className="flex items-start gap-2"><ArrowRight className="w-3 h-3 mt-1 text-primary-500 flex-shrink-0" />Взаимодействует с другими агентами по A2A</li>
          </ul>
        </div>

        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
            <Shield className="w-4 h-4 text-accent-600" />
            Принципы доверия
          </h3>
          <div className="p-3 rounded-lg bg-red-50 border border-red-100 mb-3">
            <p className="text-sm text-red-800 font-medium">Кому доверять: никому.</p>
            <p className="text-xs text-red-700 mt-1">Всё, что не подтверждено источником, — не выводится.</p>
          </div>
          <ul className="space-y-2 text-sm text-slate-700">
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 mt-0.5 text-green-500 flex-shrink-0" />
              <span>Каждое утверждение помечено ссылкой [file_id:N]</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 mt-0.5 text-green-500 flex-shrink-0" />
              <span>Groundrails проверяет ответ на соответствие источникам</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 mt-0.5 text-green-500 flex-shrink-0" />
              <span>При отсутствии данных — ответ «НЕТ ДАННЫХ»</span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 mt-0.5 text-green-500 flex-shrink-0" />
              <span>Числа копируются точно, без округления</span>
            </li>
          </ul>
        </div>
      </div>

      {/* Architecture diagram */}
      <div className="card p-5">
        <h3 className="text-sm font-semibold text-slate-800 mb-4 flex items-center gap-2">
          <Layers className="w-4 h-4 text-primary-600" />
          Архитектура системы
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="p-3 rounded-lg bg-blue-50 border border-blue-100">
            <p className="text-xs font-bold text-blue-900 mb-2">🌐 ВХОД</p>
            <div className="space-y-1.5 text-xs text-blue-800">
              <p>• UI (HTMX + Jinja2)</p>
              <p>• REST API (FastAPI)</p>
              <p>• A2A (JSON-RPC)</p>
              <p>• Watchdog (папки)</p>
            </div>
          </div>
          <div className="p-3 rounded-lg bg-purple-50 border border-purple-100">
            <p className="text-xs font-bold text-purple-900 mb-2">🧠 ОБРАБОТКА</p>
            <div className="space-y-1.5 text-xs text-purple-800">
              <p>• Оркестратор</p>
              <p>• Субагенты (6 шт.)</p>
              <p>• Ollama (LLM)</p>
              <p>• Экстракторы</p>
            </div>
          </div>
          <div className="p-3 rounded-lg bg-green-50 border border-green-100">
            <p className="text-xs font-bold text-green-900 mb-2">💾 ХРАНЕНИЕ</p>
            <div className="space-y-1.5 text-xs text-green-800">
              <p>• SQLite (метаданные)</p>
              <p>• ChromaDB (векторы)</p>
              <p>• FS (оригиналы)</p>
              <p>• JSON-деревья</p>
            </div>
          </div>
        </div>
      </div>

      <div className="p-4 rounded-lg bg-amber-50 border border-amber-200">
        <div className="flex items-start gap-2">
          <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-900">Ограничения</p>
            <ul className="text-xs text-amber-800 mt-1 space-y-0.5">
              <li>• Язык интерфейса: только русский</li>
              <li>• OCR: только rus + eng</li>
              <li>• До 10 одновременных пользователей</li>
              <li>• Максимум 1 млн файлов (далее — PostgreSQL)</li>
              <li>• Ollama обязательна для LLM-задач</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function StackSection({ CodeBlock }: { CodeBlock: any }) {
  const stack = [
    { layer: 'Web', items: [['fastapi', '0.115.*'], ['uvicorn[standard]', '0.32.*']] },
    { layer: 'UI', items: [['jinja2', '3.1.*'], ['htmx (CDN)', '2.0.*']] },
    { layer: 'Auth', items: [['python-jose[cryptography]', '3.3.*'], ['passlib[bcrypt]', '1.7.*']] },
    { layer: 'ORM/DB', items: [['sqlalchemy', '2.0.*'], ['sqlite', 'встроен']] },
    { layer: 'Vector', items: [['chromadb', '0.5.*'], ['sentence-transformers', '3.2.*']] },
    { layer: 'LLM', items: [['ollama', '0.3.*'], ['qwen2.5:1.5b', 'default'], ['gemma2:2b', 'light']] },
    { layer: 'Extraction', items: [['kreuzberg', '3.*'], ['pytesseract', '0.3.*'], ['paddleocr', '2.8.*']] },
    { layer: 'Docs', items: [['python-docx', '1.1.*'], ['openpyxl', '3.1.*'], ['weasyprint', '62.*']] },
    { layer: 'A2A', items: [['a2a-sdk', '0.2.*'], ['groundrails', '1.*']] },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Технологический стек</h1>
        <p className="text-sm text-slate-500 mt-1">Все версии зафиксированы через == в pyproject.toml</p>
      </div>

      <div className="space-y-3">
        {stack.map(group => (
          <div key={group.layer} className="card p-4">
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">{group.layer}</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {group.items.map(([pkg, ver]) => (
                <div key={pkg} className="flex items-center justify-between px-3 py-1.5 rounded-md bg-slate-50">
                  <span className="text-sm font-mono text-slate-800">{pkg}</span>
                  <span className="text-xs text-slate-500 font-mono">{ver}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="card p-4">
        <h3 className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-2">
          <Package className="w-4 h-4" />
          Модели
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="p-3 rounded-lg bg-blue-50 border border-blue-100">
            <p className="text-xs font-bold text-blue-900">LLM (основная)</p>
            <p className="text-sm font-mono text-blue-800 mt-1">qwen2.5:1.5b-instruct-q4_K_M</p>
          </div>
          <div className="p-3 rounded-lg bg-purple-50 border border-purple-100">
            <p className="text-xs font-bold text-purple-900">LLM (лёгкая)</p>
            <p className="text-sm font-mono text-purple-800 mt-1">gemma2:2b-instruct-q4_K_M</p>
          </div>
          <div className="p-3 rounded-lg bg-green-50 border border-green-100">
            <p className="text-xs font-bold text-green-900">Embeddings</p>
            <p className="text-sm font-mono text-green-800 mt-1">multilingual-e5-small</p>
            <p className="text-xs text-green-700">384 dim • cosine</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StructureSection({ CodeBlock }: { CodeBlock: any }) {
  const tree = `document-agent/
├── pyproject.toml
├── README.md
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── config/
│   ├── config.yaml
│   ├── rules.yaml
│   └── prompts/
│       ├── classifier.txt
│       ├── extractor.txt
│       ├── reporter.txt
│       └── validator.txt
├── data/                     # монтируется как volume
│   ├── storage/              # оригиналы + извлечённые JSON
│   ├── sqlite/app.db
│   └── chroma/
├── src/doc_agent/
│   ├── __init__.py
│   ├── main.py               # FastAPI app + lifespan
│   ├── config.py             # pydantic settings
│   ├── logging.py            # structlog setup
│   ├── auth.py               # JWT, RBAC
│   ├── db/
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── session.py
│   │   └── migrations.py
│   ├── vector/
│   │   ├── chroma_client.py
│   │   └── embedder.py
│   ├── extractors/
│   │   ├── base.py           # Protocol Extractor
│   │   ├── registry.py       # авторегистрация плагинов
│   │   ├── office.py         # pdf/docx/xlsx/pptx/csv
│   │   ├── image.py          # OCR
│   │   ├── email.py          # eml/msg
│   │   ├── gge.py            # сметы XML
│   │   └── archive.py        # zip/rar/7z
│   ├── subagents/
│   │   ├── base.py           # интерфейс Subagent
│   │   ├── orchestrator.py
│   │   ├── extractor_agent.py
│   │   ├── classifier_agent.py
│   │   ├── retriever_agent.py
│   │   ├── reporter_agent.py
│   │   ├── reconstructor_agent.py
│   │   └── validator_agent.py
│   ├── llm/
│   │   ├── ollama_client.py
│   │   └── prompts.py
│   ├── services/
│   │   ├── ingest.py
│   │   ├── card_index.py
│   │   ├── query.py
│   │   ├── reproduce.py
│   │   ├── ocr_fix.py
│   │   ├── watcher.py
│   │   └── a2a_server.py
│   ├── api/
│   │   ├── routes_ui.py
│   │   ├── routes_auth.py
│   │   ├── routes_files.py
│   │   ├── routes_query.py
│   │   ├── routes_admin.py
│   │   └── routes_a2a.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── chat.html
│   │   ├── admin.html
│   │   └── login.html
│   └── static/
│       ├── htmx.min.js
│       ├── app.js
│       └── style.css
├── plugins/                  # пользовательские парсеры
└── tests/
    ├── conftest.py
    ├── test_extract.py
    ├── test_classify.py
    ├── test_card_index.py
    ├── test_query.py
    ├── test_export.py
    ├── test_hallucination.py
    ├── test_ocr_fix.py
    ├── test_reconstruct.py
    ├── test_a2a.py
    ├── test_e2e.py
    └── test_offline.py`;

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Структура репозитория</h1>
        <p className="text-sm text-slate-500 mt-1">Организация файлов и модулей</p>
      </div>
      <CodeBlock code={tree} id="tree" lang="text" />
    </div>
  );
}

function SchemaSection({ CodeBlock }: { CodeBlock: any }) {
  const ddl = `CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256          TEXT UNIQUE NOT NULL,
    original_name   TEXT NOT NULL,
    stored_path     TEXT NOT NULL,
    format          TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    mtime           TEXT NOT NULL,
    city            TEXT,
    customer        TEXT,
    contract_no     TEXT,
    contract_date   TEXT,
    doc_type        TEXT,
    doc_number      TEXT,
    doc_date        TEXT,
    amount          REAL,
    status          TEXT NOT NULL DEFAULT 'pending',
    ocr_confidence  REAL,
    description     TEXT,
    source          TEXT,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    child_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    link_type   TEXT NOT NULL,
    UNIQUE(parent_id, child_id, link_type)
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    page        INTEGER,
    char_start  INTEGER,
    char_end    INTEGER
);

CREATE TABLE IF NOT EXISTS tables_flat (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    table_name  TEXT,
    row_index   INTEGER,
    col_index   INTEGER,
    value       TEXT,
    cell_ref    TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER REFERENCES files(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 5,
    status      TEXT NOT NULL DEFAULT 'queued',
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    payload     TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS ocr_corrections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    original    TEXT NOT NULL,
    corrected   TEXT NOT NULL,
    user        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);`;

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Схемы данных</h1>
        <p className="text-sm text-slate-500 mt-1">SQLite DDL + ChromaDB + JSON-дерево</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { name: 'files', desc: 'Метаданные документов', color: 'blue' },
          { name: 'file_links', desc: 'Связи между файлами', color: 'indigo' },
          { name: 'chunks', desc: 'Текстовые чанки', color: 'purple' },
          { name: 'tables_flat', desc: 'Таблицы (плоские)', color: 'violet' },
          { name: 'jobs', desc: 'Очередь задач', color: 'amber' },
          { name: 'audit_log', desc: 'Журнал действий', color: 'slate' },
          { name: 'users', desc: 'Пользователи', color: 'green' },
          { name: 'ocr_corrections', desc: 'Правки OCR', color: 'red' },
        ].map(t => (
          <div key={t.name} className={`p-3 rounded-lg bg-${t.color}-50 border border-${t.color}-100`}>
            <p className="text-xs font-mono font-bold text-slate-800">{t.name}</p>
            <p className="text-[10px] text-slate-600 mt-0.5">{t.desc}</p>
          </div>
        ))}
      </div>

      <CodeBlock code={ddl} id="ddl" lang="sql" />

      <div className="card p-4">
        <h3 className="text-sm font-semibold text-slate-800 mb-2">Допустимые значения</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <div>
            <p className="font-medium text-slate-700 mb-1">status:</p>
            <div className="flex flex-wrap gap-1">
              {['pending', 'processing', 'done', 'failed', 'description_only'].map(v => (
                <span key={v} className="px-2 py-0.5 rounded bg-slate-100 font-mono text-slate-700">{v}</span>
              ))}
            </div>
          </div>
          <div>
            <p className="font-medium text-slate-700 mb-1">doc_type:</p>
            <div className="flex flex-wrap gap-1">
              {['ks2', 'ks3', 'ks6', 'ttn', 'ds', 'id', 'invoice', 'contract', 'other'].map(v => (
                <span key={v} className="px-2 py-0.5 rounded bg-slate-100 font-mono text-slate-700">{v}</span>
              ))}
            </div>
          </div>
          <div>
            <p className="font-medium text-slate-700 mb-1">link_type:</p>
            <div className="flex flex-wrap gap-1">
              {['ds_to_contract', 'ks_to_contract', 'ttn_to_contract', 'id_to_contract'].map(v => (
                <span key={v} className="px-2 py-0.5 rounded bg-slate-100 font-mono text-slate-700">{v}</span>
              ))}
            </div>
          </div>
          <div>
            <p className="font-medium text-slate-700 mb-1">source:</p>
            <div className="flex flex-wrap gap-1">
              {['user', 'watcher', 'agent:<id>'].map(v => (
                <span key={v} className="px-2 py-0.5 rounded bg-slate-100 font-mono text-slate-700">{v}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ApiSection({ CodeBlock }: { CodeBlock: any }) {
  const [activeEndpoint, setActiveEndpoint] = useState('auth');

  const endpoints = {
    auth: {
      title: 'Аутентификация',
      items: [
        { method: 'POST', path: '/auth/login', body: '{"username": "...", "password": "..."}', response: '{"access_token": "...", "token_type": "bearer", "role": "user|admin"}' },
        { method: 'GET', path: '/auth/me', body: '—', response: '{"username": "...", "role": "..."}' },
      ]
    },
    files: {
      title: 'Файлы',
      items: [
        { method: 'POST', path: '/files/upload', body: 'multipart/form-data', response: '{"file_id": 1, "status": "queued", "message": "Файл принят"}' },
        { method: 'GET', path: '/files/{id}', body: '—', response: '{"file": {...}, "links": [...], "chunks_count": 12}' },
        { method: 'GET', path: '/files/{id}/tree', body: '—', response: 'JSON-дерево документа' },
        { method: 'POST', path: '/files/{id}/reproduce', body: '{"target_format": "docx|xlsx|pdf|html|md"}', response: '{"download_url": "/files/{id}/download/{job_id}"}' },
      ]
    },
    card: {
      title: 'Картотека',
      items: [
        { method: 'GET', path: '/card', body: 'Параметры: city, customer, contract_no, doc_type, date_from, date_to, limit, offset', response: '{"total": N, "items": [...]}' },
        { method: 'GET', path: '/card/export.xlsx', body: 'те же параметры', response: 'XLSX-файл (15 колонок + автофильтр)' },
      ]
    },
    query: {
      title: 'Запросы',
      items: [
        { method: 'POST', path: '/query', body: '{"q": "Покажи все КС2 по договору 123", "limit": 20}', response: '{"answer": "...", "files": [...], "confidence": 0.87, "grounded": true}' },
        { method: 'POST', path: '/query/report', body: '{"q": "...", "format": "xlsx|md|json"}', response: '{"download_url": "..."}' },
      ]
    },
    ocr: {
      title: 'OCR-исправление',
      items: [
        { method: 'GET', path: '/ocr/{file_id}/suspects', body: '—', response: '{"suspects": [{"chunk_id": 5, "text": "...", "confidence": 0.72}]}' },
        { method: 'POST', path: '/ocr/{file_id}/correct', body: '{"chunk_id": 5, "corrected": "123-А"}', response: '{"status": "ok", "reindex_job": 42}' },
      ]
    },
    a2a: {
      title: 'A2A протокол',
      items: [
        { method: 'GET', path: '/.well-known/agent.json', body: '—', response: 'Agent Card' },
        { method: 'POST', path: '/a2a', body: 'JSON-RPC 2.0 (tasks/send)', response: 'JSON-RPC 2.0 result' },
      ]
    },
    admin: {
      title: 'Администрирование',
      items: [
        { method: 'GET', path: '/admin/jobs', body: '—', response: 'Очередь задач' },
        { method: 'POST', path: '/admin/reindex', body: '—', response: 'Полная переиндексация' },
        { method: 'GET', path: '/admin/metrics', body: '—', response: 'precision/recall/галлюцинации' },
        { method: 'GET', path: '/admin/logs', body: '?tail=200', response: 'Последние логи' },
      ]
    },
    health: {
      title: 'Health',
      items: [
        { method: 'GET', path: '/health', body: '—', response: '{"status": "ok", "db": "ok", "chroma": "ok", "ollama": "ok"}' },
      ]
    },
  };

  const methodColors: Record<string, string> = {
    GET: 'bg-green-100 text-green-700',
    POST: 'bg-blue-100 text-blue-700',
    PUT: 'bg-amber-100 text-amber-700',
    DELETE: 'bg-red-100 text-red-700',
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">API-контракты</h1>
        <p className="text-sm text-slate-500 mt-1">Все ответы — JSON. Требуется JWT (кроме /auth/login и /health)</p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {Object.entries(endpoints).map(([key, val]) => (
          <button
            key={key}
            onClick={() => setActiveEndpoint(key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeEndpoint === key
                ? 'bg-primary-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {val.title}
          </button>
        ))}
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-600 w-20">Метод</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-600">Путь</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-600">Тело/Параметры</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-600">Ответ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {endpoints[activeEndpoint as keyof typeof endpoints].items.map((item, i) => (
              <tr key={i} className="hover:bg-slate-50">
                <td className="px-4 py-2.5">
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${methodColors[item.method]}`}>
                    {item.method}
                  </span>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-slate-800">{item.path}</td>
                <td className="px-4 py-2.5 text-xs text-slate-600 font-mono">{item.body}</td>
                <td className="px-4 py-2.5 text-xs text-slate-600 font-mono">{item.response}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PromptsSection({ CodeBlock }: { CodeBlock: any }) {
  const classifier = `Ты классифицируешь документы. Верни СТРОГО JSON без пояснений.

Схема:
{
  "doc_type": "ks2|ks3|ks6|ttn|ds|id|invoice|contract|other",
  "city": "строка или null",
  "customer": "строка или null",
  "contract_no": "строка или null",
  "contract_date": "YYYY-MM-DD или null",
  "doc_number": "строка или null",
  "doc_date": "YYYY-MM-DD или null",
  "amount": число или null,
  "confidence": 0.0..1.0
}

Правила:
- Если поле не найдено в тексте — ставь null. НИКОГДА не выдумывай.
- amount — только итоговая сумма, число без пробелов и валюты.
- confidence — твоя уверенность в целом ответе.

Текст:
---
{text}
---`;

  const extractor = `Ты извлекаешь структуру документа. Верни СТРОГО JSON по схеме (см. документ).
Сохраняй порядок абзацев и таблиц. Ничего не додумывай.
Если элемент нечитаем — пропусти его и увеличь счётчик unreadable.

Схема:
{"children": [{"type": "heading|paragraph|table|image", ...}], "unreadable": 0}

Текст:
---
{text}
---`;

  const reporter = `Ты формируешь ответ на вопрос пользователя. Используй ТОЛЬКО фрагменты ниже.
Каждое утверждение помечай ссылкой [file_id:N].
Если факта нет — напиши ровно: НЕТ ДАННЫХ
Числа копируй точно из источника. Не округляй.

Вопрос: {question}

Фрагменты:
{fragments}`;

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Промпты субагентов</h1>
        <p className="text-sm text-slate-500 mt-1">Все промпты — только из config/prompts/*.txt. Никакой инлайн-генерации.</p>
      </div>

      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-2">
            <span className="w-6 h-6 rounded-md bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold">1</span>
            classifier.txt
          </h3>
          <CodeBlock code={classifier} id="prompt-classifier" lang="text" />
        </div>

        <div>
          <h3 className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-2">
            <span className="w-6 h-6 rounded-md bg-purple-100 text-purple-700 flex items-center justify-center text-xs font-bold">2</span>
            extractor.txt
          </h3>
          <CodeBlock code={extractor} id="prompt-extractor" lang="text" />
        </div>

        <div>
          <h3 className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-2">
            <span className="w-6 h-6 rounded-md bg-green-100 text-green-700 flex items-center justify-center text-xs font-bold">3</span>
            reporter.txt
          </h3>
          <CodeBlock code={reporter} id="prompt-reporter" lang="text" />
        </div>

        <div>
          <h3 className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-2">
            <span className="w-6 h-6 rounded-md bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-bold">4</span>
            validator.txt
          </h3>
          <div className="p-3 rounded-lg bg-amber-50 border border-amber-100">
            <p className="text-sm text-amber-800">Не используется. Валидация выполняется groundrails на CPU без LLM.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function AlgoSection() {
  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Алгоритмы</h1>
        <p className="text-sm text-slate-500 mt-1">Основные процессы системы</p>
      </div>

      <div className="space-y-4">
        {/* Ingest */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary-600" />
            8.1 Ingest (приём файла)
          </h3>
          <div className="space-y-2">
            {[
              'Вычислить sha256. Если есть в files — вернуть существующий id (dedup).',
              'Определить формат через magic bytes (python-magic).',
              'Создать запись в files (status=pending).',
              'Скопировать файл в storage/{sha256}/original.{ext}.',
              'Поставить job(kind=ingest, priority=1) в jobs.',
              'Вернуть file_id и сообщение "Файл принят".',
            ].map((step, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="w-5 h-5 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center text-xs font-bold flex-shrink-0">{i + 1}</span>
                <p className="text-sm text-slate-700">{step}</p>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-slate-100">
            <p className="text-xs font-semibold text-slate-600 mb-2">Фоновый воркер:</p>
            <div className="space-y-1.5">
              {[
                'Взять job. status=processing.',
                'Выбрать экстрактор из registry по формату.',
                'Извлечь: text, tree.json, tables (в tables_flat).',
                'Если format ∈ {image} → confidence = OCR mean. Если < 0.80 → пометить фрагменты.',
                'Вызвать classifier_agent (LLM ≤ 2B) → метаданные.',
                'Разбить текст на чанки (512 токенов, overlap 64).',
                'Создать эмбеддинги → ChromaDB.',
                'Создать связи: если doc_type=ds и contract_no → link(ds, contract, ds_to_contract).',
                'status=done. Уведомить UI.',
              ].map((step, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center text-xs font-bold flex-shrink-0">{i + 7}</span>
                  <p className="text-xs text-slate-700">{step}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Query */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-accent-600" />
            8.2 Query (запрос)
          </h3>
          <div className="space-y-2">
            {[
              'Извлечь фильтры из вопроса (LLM classifier, JSON-схема filters).',
              'Гибридный поиск: SQL-фильтр → BM25 → ChromaDB → объединить (RRF).',
              'Реранкер cross-encoder → top 5.',
              'reporter_agent генерирует ответ по промпту reporter.txt.',
              'validator (groundrails): разбить на утверждения, найти поддержку в top-5, вырезать неподтверждённые.',
              'Числовая валидация: regex по числам; сравнить с источниками; при расхождении — заменить.',
              'Вернуть: answer, files, confidence, grounded.',
            ].map((step, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="w-5 h-5 rounded-full bg-accent-100 text-accent-700 flex items-center justify-center text-xs font-bold flex-shrink-0">{i + 1}</span>
                <p className="text-sm text-slate-700">{step}</p>
              </div>
            ))}
          </div>
        </div>

        {/* OCR fix */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
            <FileCode className="w-4 h-4 text-amber-600" />
            8.3 OCR-исправление
          </h3>
          <div className="space-y-2 text-sm text-slate-700">
            <p>1. При выдаче suspects — показать фрагмент изображения (crop по char_start/char_end).</p>
            <p>2. Пользователь вводит corrected.</p>
            <p>3. Сравнить original и corrected: edit_distance / len(original) &gt; 0.5 → 50%+ ошибок.</p>
            <p>4. Если &gt; 0.5 → ответ: «Загрузите скан ≥300 dpi».</p>
            <p>5. Иначе: записать в ocr_corrections, добавить в user_words.txt, переиндексировать.</p>
            <p>6. Задать 1-2 уточняющих вопроса.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function DDSection() {
  const ddItems = [
    { id: 'DD-1', text: 'Пользователь открывает http://localhost:8000, видит чат и кнопку «Загрузить»', check: 'Ручная проверка', done: true },
    { id: 'DD-2', text: 'Перетаскивание файла в чат → ответ «Файл X добавлен в <папка>, распознан как <тип>» за ≤ 30 с для PDF ≤ 5 МБ', check: 'pytest tests/test_e2e.py::test_drop_file', done: true },
    { id: 'DD-3', text: 'Картотека выгружается в card_index.xlsx с 15 колонками и автофильтром', check: 'pytest tests/test_export.py', done: true },
    { id: 'DD-4', text: 'Запрос «Покажи все КС2 по договору 123» возвращает JSON + файлы', check: 'pytest tests/test_query.py::test_ks2', done: true },
    { id: 'DD-5', text: 'На вопрос, ответа на который нет в файлах, — ответ «НЕТ ДАННЫХ»', check: 'pytest tests/test_hallucination.py', done: true },
    { id: 'DD-6', text: 'OCR-ошибка: агент задаёт уточняющий вопрос вместо догадки', check: 'pytest tests/test_ocr_fix.py', done: true },
    { id: 'DD-7', text: 'DOCX с таблицей → XLSX с сохранённой таблицей', check: 'pytest tests/test_reconstruct.py', done: true },
    { id: 'DD-8', text: 'Внешний A2A-клиент получает ответ по POST /a2a', check: 'pytest tests/test_a2a.py', done: true },
    { id: 'DD-9', text: 'Всё работает без интернета (после docker pull)', check: 'pytest tests/test_offline.py', done: true },
    { id: 'DD-10', text: 'ruff check . && mypy . && pytest проходит без ошибок', check: 'CI', done: true },
  ];

  const checklist = [
    'Все версии в pyproject.toml зафиксированы через ==.',
    'ruff check . && mypy . && pytest — без ошибок.',
    'docker compose up работает на чистой машине.',
    'DD-1..DD-10 из раздела 2 проходят.',
    'Нет ни одной строки, обращающейся в интернет (кроме docker pull).',
    'Промпты лежат в файлах, не в коде.',
    'Все схемы SQL соответствуют DDL из раздела 5.1.',
    'Все API соответствуют контрактам из раздела 6.',
    'README.md содержит инструкцию запуска на 1 страницу.',
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Definition of Done</h1>
        <p className="text-sm text-slate-500 mt-1">Критерии готовности проекта</p>
      </div>

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-800">Прогресс</h3>
          <span className="text-sm font-bold text-green-600">10/10 ✓</span>
        </div>
        <div className="w-full bg-slate-100 rounded-full h-2 mb-4">
          <div className="bg-gradient-to-r from-green-500 to-emerald-500 h-2 rounded-full" style={{ width: '100%' }} />
        </div>

        <div className="space-y-2">
          {ddItems.map(item => (
            <div key={item.id} className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 border border-slate-100">
              <CheckCircle2 className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-slate-500">{item.id}</span>
                </div>
                <p className="text-sm text-slate-800 mt-0.5">{item.text}</p>
                <p className="text-xs text-slate-500 mt-1 font-mono">{item.check}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card p-5">
        <h3 className="text-sm font-semibold text-slate-800 mb-4">Финальный чек-лист</h3>
        <div className="space-y-2">
          {checklist.map((item, i) => (
            <div key={i} className="flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-slate-700">{item}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="p-4 rounded-lg bg-green-50 border border-green-200">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-green-600" />
          <p className="text-sm font-medium text-green-900">Проект готов к развёртыванию</p>
        </div>
        <p className="text-xs text-green-800 mt-1">
          Запуск: <code className="bg-green-100 px-1.5 py-0.5 rounded font-mono">docker compose up</code> или <code className="bg-green-100 px-1.5 py-0.5 rounded font-mono">make run</code>
        </p>
      </div>
    </div>
  );
}
