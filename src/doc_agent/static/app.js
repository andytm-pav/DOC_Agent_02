/* Документовед — клиентский JS: auth, чат, загрузка файлов, админ. */
const API = "";

function token() { return localStorage.getItem("da_token") || ""; }
function role() { return localStorage.getItem("da_role") || ""; }

function authHeaders(extra) {
    const h = extra || {};
    if (token()) h["Authorization"] = "Bearer " + token();
    return h;
}

async function apiFetch(url, options) {
    const opts = options || {};
    opts.headers = authHeaders(opts.headers || {});
    const resp = await fetch(API + url, opts);
    if (resp.status === 401) { localStorage.removeItem("da_token"); goToLogin(); throw new Error("Не авторизован"); }
    return resp;
}

function goToLogin() {
    if (!location.pathname.startsWith("/login")) location.href = "/login";
}

function logout() {
    localStorage.removeItem("da_token");
    localStorage.removeItem("da_role");
    location.href = "/login";
}

/* ---------- Вход ---------- */
const loginForm = document.getElementById("loginForm");
if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const r = await fetch(API + "/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username: document.getElementById("loginUser").value,
                password: document.getElementById("loginPass").value,
            }),
        });
        if (r.ok) {
            const data = await r.json();
            localStorage.setItem("da_token", data.access_token);
            localStorage.setItem("da_role", data.role);
            location.href = "/";
        } else {
            document.getElementById("loginError").hidden = false;
        }
    });
}

const whoami = document.getElementById("whoami");
if (whoami && token()) {
    fetch(API + "/auth/me", { headers: authHeaders() })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (d) whoami.textContent = d.username + " (" + d.role + ")"; })
        .catch(() => {});
}

/* ---------- Чат ---------- */
const chatForm = document.getElementById("chatForm");
const chatBox = document.getElementById("chatBox");
// фазы разгребания свалки — показываются и в pollSort, и в строке статуса
const PHASES = {
    scan: "Сканирую папку",
    read: "Читаю документы",
    name: "Придумываю названия папок",
    copy: "Раскладываю файлы",
};

function addSystem(text) {
    if (!chatBox) return;
    const div = document.createElement("div");
    div.className = "msg system";
    div.textContent = text;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function metaHtml(meta) {
    const m = meta || {};
    let html = "";
    if (m.files && m.files.length) {
        html += "<div class='files'>" + m.files.map((f) =>
            "<span class='filechip'>📄 " + escapeHtml(f.file_name) + " [file_id:" + f.file_id + "]</span>"
        ).join(" ") + "</div>";
    }
    const bits = [];
    if (m.intent === "list_files") bits.push("📋 список файлов из картотеки");
    if (m.intent === "find_files") bits.push("🔍 поиск по названиям и типам");
    if (m.intent === "count_files") bits.push("🧮 подсчёт по картотеке");
    if (m.intent === "deep_read") bits.push("📖 файл прочитан целиком");
    if (m.intent === "help") bits.push("💡 подсказка");
    if (m.intent === "direct") bits.push("💬 ответ агента");
    // v3.0.0: файловые операции + проверенные ответы (обратная связь)
    if (m.intent === "file_link") bits.push("🔗 пути файлов на диске");
    if (m.intent === "file_move") bits.push("📦 файлы перемещены");
    if (m.intent === "file_copy") bits.push("📑 файлы скопированы");
    if (m.intent === "file_mkdir") bits.push("📁 папка создана");
    if (m.known_answer_used) bits.push("🧠 применён проверенный ответ");
    if (m.recall) bits.push("📦 из архива памяти");
    if (typeof m.grounded === "boolean") bits.push(m.grounded ? "✅ подтверждено файлами" : "⚠️ не подтверждено");
    if (m.confidence != null) bits.push("уверенность: " + m.confidence);
    if (m.partial) bits.push("частичный ответ");
    if (bits.length) html += "<div class='meta'>" + bits.join(" · ") + "</div>";
    return html;
}

/* v2.9.1: рендер Markdown в ответах агента — GFM-таблицы, списки, код.
   Ответ ВСЕГДА прогоняется через DOMPurify (XSS-защита: в ответ попадают
   цитаты из файлов, файл может содержать HTML/скрипты). Если вендоренные
   библиотеки не загрузились — прежний путь: escapeHtml + <br>. */
function renderMarkdown(text) {
    const raw = String(text ?? "");
    if (window.marked && window.DOMPurify) {
        marked.setOptions({ gfm: true, breaks: true, headerIds: false, mangle: false });
        return DOMPurify.sanitize(marked.parse(raw));
    }
    return escapeHtml(raw).replace(/\n/g, "<br>");
}

/* v3.0.0: обратная связь в чате — 👍/👎 + исправленный ответ под каждым
   ответом агента. Отправка — POST /feedback (право feedback_submit).
   Запись попадает в базу проверенных ответов: агент подставит её на
   похожем вопросе и поднимет отмеченные файлы в поиске. */
let lastQuestion = "";

function feedbackStrip() {
    return "<div class='fb-strip'><button class='btn btn-ghost fb-btn' data-rating='up' title='Полезный ответ'>👍</button>"
        + "<button class='btn btn-ghost fb-btn' data-rating='down' title='Неправильный ответ — можно исправить'>👎</button>"
        + "<span class='fb-form' hidden><textarea class='fb-textarea' rows='2' placeholder='Какой ответ правильный? (необязательно — агент запомнит и будет отвечать так же)'></textarea>"
        + "<button class='btn btn-primary fb-send'>Отправить отзыв</button></span>"
        + "<span class='fb-thanks muted' hidden>Отзыв сохранён — спасибо! Агент учтёт его на похожих вопросах.</span></div>";
}

/* v3.0.1: визуальная отметка выбранной оценки — кнопка подсвечивается
   сразу при клике (класс .fb-active), иначе непонятно, что выбрал
   пользователь. Переключение между 👍/👎 снимает прежнюю отметку. */
function markFeedbackChoice(strip, rating) {
    strip.querySelectorAll(".fb-btn").forEach((b) => {
        b.classList.toggle("fb-active", b.dataset.rating === rating);
    });
}

function wireFeedback(div) {
    const strip = div.querySelector(".fb-strip");
    if (!strip) return;
    strip.querySelector(".fb-btn[data-rating='up']").addEventListener("click", () => {
        markFeedbackChoice(strip, "up");
        sendFeedback(div, "up");
    });
    strip.querySelector(".fb-btn[data-rating='down']").addEventListener("click", () => {
        markFeedbackChoice(strip, "down");
        const form = strip.querySelector(".fb-form");
        form.hidden = false;
        form.querySelector(".fb-textarea").focus();
    });
    strip.querySelector(".fb-send").addEventListener("click", () => sendFeedback(div, "down"));
}

async function sendFeedback(div, rating) {
    const strip = div.querySelector(".fb-strip");
    const question = (div.dataset.question || "").trim();
    const answer = (div.dataset.answer || div.textContent || "").trim();
    if (!question || !answer || answer === "Думаю…") return;
    const form = strip.querySelector(".fb-form");
    const corrected = form ? form.querySelector(".fb-textarea").value.trim() : "";
    const fileIds = (div.dataset.fileIds || "").split(",").map((x) => parseInt(x, 10)).filter((x) => !isNaN(x));
    try {
        const r = await apiFetch("/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: question, answer: answer, rating: rating,
                                   corrected_answer: corrected || null, file_ids: fileIds }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка отправки");
        if (form) form.hidden = true;
        strip.querySelector(".fb-thanks").hidden = false;
        // v3.0.1: отметка остаётся видимой и после отправки (кнопки гаснут,
        // но выбранная остаётся подсвеченной — видно, что отправлено)
        strip.querySelectorAll(".fb-btn").forEach((b) => (b.disabled = true));
    } catch (err) {
        strip.querySelector(".fb-thanks").hidden = false;
        strip.querySelector(".fb-thanks").textContent = "❌ " + err.message;
        strip.querySelector(".fb-thanks").classList.remove("muted");
    }
}

function renderMsg(kind, content, meta) {
    if (!chatBox) return null;
    const div = document.createElement("div");
    div.className = "msg " + kind;
    if (kind === "agent") {
        // v2.9.1: Markdown (таблицы/списки/код) вместо плоского текста
        div.innerHTML = renderMarkdown(content) + metaHtml(meta) + feedbackStrip();
        // v3.0.0: исходные текст вопроса/ответа — для POST /feedback
        div.dataset.answer = String(content ?? "");
        div.dataset.question = lastQuestion;
        div.dataset.fileIds = ((meta && meta.files) || []).map((f) => f.file_id).join(",");
        wireFeedback(div);
    } else {
        // Сообщения пользователя — как введено: переносы/табуляции сохраняются
        // (white-space: pre-wrap в CSS), экранирование через textContent.
        div.textContent = content;
    }
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
    return div;
}

async function loadHistory() {
    if (!chatBox) return;
    try {
        const r = await apiFetch("/chat/history");
        if (!r.ok) return;
        const data = await r.json();
        (data.items || []).forEach((m) => {
            if (m.role === "user") {
                lastQuestion = m.content;   // v3.0.0: вопрос для отзывов
                renderMsg("user", m.content, m.meta);
            } else {
                renderMsg("agent", m.content, m.meta);
            }
        });
        if ((data.items || []).length) {
            addSystem("— Загружена история: " + data.items.length + " сообщ. (всего " + data.total + ") —");
        }
        if (data.active > 0) {
            addSystem("В актуальном контексте " + data.active + " сообщ. Кнопка «📦 Очистить контекст» свернёт его в сжатую памятку (архив памяти), а кнопка «🧹 Очистить историю» уберёт переписку с экрана.");
        }
    } catch (err) { /* история не критична для работы чата */ }
}
loadHistory();

if (chatForm) {
    const input = document.getElementById("chatInput");
    // v2.9.1: авто-рост textarea по мере набора (до max-height в CSS),
    // Enter — отправка, Shift+Enter — перенос строки (как в промышленных
    // чатах). Во время композиции IME Enter не перехватываем.
    function autoGrow() {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 180) + "px";
    }
    if (input) {
        input.addEventListener("input", autoGrow);
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                chatForm.requestSubmit();
            }
        });
    }
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const q = input.value.trim();
        if (!q) return;
        renderMsg("user", q);          // textContent + pre-wrap: табуляции и
                                        // переносы сохраняются на канве
        lastQuestion = q;               // v3.0.0: вопрос для отзывов 👍/👎
        input.value = "";
        autoGrow();                     // вернуть однострочную высоту
        const box = renderMsg("agent", "Думаю…");
        const started = Date.now();
        const timer = setInterval(() => {
            if (box) box.textContent = "Думаю… (" + Math.round((Date.now() - started) / 1000) + " с)";
        }, 500);
        try {
            const r = await apiFetch("/query", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ q: q, limit: 20 }),
            });
            const data = await r.json();
            clearInterval(timer);
            if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка запроса");
            if (box) box.remove();
            renderMsg("agent", data.answer, data);
        } catch (err) {
            clearInterval(timer);
            if (box) box.textContent = "Ошибка запроса: " + err.message;
        }
    });
}

/* ---------- Очистка истории / контекста, архив памяти ---------- */
const clearHistoryBtn = document.getElementById("clearHistoryBtn");
if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", async () => {
        if (!confirm("Удалить всю историю чата с экрана? Архив памяти (сжатые контексты) останется.")) return;
        try {
            const r = await apiFetch("/chat/clear-history", { method: "POST" });
            const data = await r.json();
            if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка очистки");
            chatBox.innerHTML = "";
            addSystem("История чата очищена (" + data.deleted + " сообщ.). Архив памяти не тронут.");
        } catch (err) { addSystem("❌ " + err.message); }
    });
}

const clearContextBtn = document.getElementById("clearContextBtn");
if (clearContextBtn) {
    clearContextBtn.addEventListener("click", async () => {
        if (!confirm("Свернуть актуальный контекст в сжатую памятку? Агент «забудет» недавний разговор, но памятка сохранится в архиве памяти — её можно поднять запросом «вспомни …». История на экране останется.")) return;
        try {
            const r = await apiFetch("/chat/clear-context", { method: "POST" });
            const data = await r.json();
            if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка архивации");
            if (data.archived) {
                addSystem("📦 Контекст свёрнут в памятку «" + data.title + "» (" + data.messages + " сообщ." + (data.llm ? ", LLM-сжатие" : "") + "). Спросите «вспомни …» — подниму из архива.");
                const panel = document.getElementById("archivePanel");
                if (panel && !panel.hidden) loadArchives();
            } else {
                addSystem(data.message || "Контекст пуст.");
            }
        } catch (err) { addSystem("❌ " + err.message); }
    });
}

const archiveToggleBtn = document.getElementById("archiveToggleBtn");
if (archiveToggleBtn) {
    archiveToggleBtn.addEventListener("click", () => {
        const panel = document.getElementById("archivePanel");
        panel.hidden = !panel.hidden;
        if (!panel.hidden) loadArchives();
    });
}

async function loadArchives() {
    const list = document.getElementById("archiveList");
    if (!list) return;
    try {
        const r = await apiFetch("/chat/archives");
        const data = await r.json();
        list.innerHTML = (data.items || []).map((a) =>
            "<div class='archive-item'><b>" + escapeHtml(a.title) + "</b>" +
            "<span class='muted'> · " + escapeHtml(String(a.created_at).replace("T", " ")) +
            " · сообщ.: " + a.message_count + "</span>" +
            "<div class='muted'>" + escapeHtml(a.summary) + "</div></div>"
        ).join("") || "<span class='muted'>Архив пуст — сверните контекст кнопкой «📦 Очистить контекст».</span>";
    } catch (err) {
        list.innerHTML = "<span class='muted'>Не удалось загрузить архив: " + escapeHtml(err.message) + "</span>";
    }
}

/* ---------- Строка статуса агента (всегда видно, что он делает) ---------- */
const agentStatus = document.getElementById("agentStatus");
if (agentStatus) {
    const STATUS_MS = parseInt(agentStatus.dataset.statusMs, 10) || 2000;

    function renderStatus(d) {
        const dot = (v) => (v === "ok" ? "🟢" : "🔴");
        const parts = ["v" + d.version,
            dot(d.health.db) + " БД", dot(d.health.chroma) + " Вектор",
            dot(d.health.llm) + " Модель: " + d.llm.provider + " · " + d.llm.model_main +
            (d.llm.api_key_set ? "" : " (нет ключа)")];
        const q = d.activity.queue || {};
        if (q.queued || q.processing) parts.push("⏳ очередь: " + (q.queued || 0) + " ждёт / " + (q.processing || 0) + " в работе");
        if (d.activity.files_processing) parts.push("📄 обрабатываю файлы: " + d.activity.files_processing);
        (d.activity.sort_jobs || []).forEach((j) => {
            if (j.state === "running") {
                parts.push("🗂 разбор свалки: " + (PHASES[j.phase] || j.phase) +
                    " (" + (j.progress ? j.progress.processed : 0) + "/" + (j.progress ? j.progress.total : 0) + ")");
            }
        });
        if (d.llm.provider === "openai_compatible" && !d.llm.api_key_set) parts.push("⚠️ задайте LLM_API_KEY в .env");
        agentStatus.innerHTML = parts.map(escapeHtml).join(" <span class='muted'>·</span> ");
    }

    async function pollStatus() {
        try {
            const r = await apiFetch("/status");
            if (r.ok) renderStatus(await r.json());
        } catch (err) { /* страница закрывается / сеть */ }
        setTimeout(pollStatus, STATUS_MS);
    }
    pollStatus();
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- Загрузка ---------- */
const fileInput = document.getElementById("fileInput");
const dropzone = document.getElementById("dropzone");
if (fileInput) {
    fileInput.addEventListener("change", () => {
        for (const f of fileInput.files) uploadFile(f);
        fileInput.value = "";
    });
}
if (dropzone) {
    ["dragover", "dragenter"].forEach((ev) =>
        dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) =>
        dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("over"); }));
    dropzone.addEventListener("drop", (e) => {
        for (const f of e.dataTransfer.files) uploadFile(f);
    });
}

async function uploadFile(file) {
    const status = document.getElementById("uploadStatus");
    const item = document.createElement("div");
    item.className = "upload-item";
    item.textContent = "⏳ " + file.name + " — отправка…";
    status.prepend(item);
    const fd = new FormData();
    fd.append("file", file);
    try {
        const r = await apiFetch("/files/upload", { method: "POST", body: fd });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || "Ошибка загрузки");
        item.textContent = "📨 " + file.name + " — " + data.message + " (id " + data.file_id + ")";
        pollFile(data.file_id, item);
    } catch (err) {
        item.textContent = "❌ " + file.name + " — " + err.message;
    }
}

async function pollFile(fileId, item, tries) {
    const maxTries = tries || 100;
    try {
        const r = await apiFetch("/files/" + fileId);
        const data = await r.json();
        const st = data.file.status;
        if (st === "done") {
            item.textContent = "✅ " + data.file.original_name + " — " + (data.message || "обработан");
            return;
        }
        if (st === "failed" || st === "description_only") {
            item.textContent = (st === "failed" ? "❌ " : "ℹ️ ") + data.file.original_name +
                " — " + (data.file.description || st);
            return;
        }
        if (maxTries <= 0) { item.textContent += " (ещё обрабатывается)"; return; }
        setTimeout(() => pollFile(fileId, item, maxTries - 1), 500);
    } catch (err) {
        item.textContent = "❌ " + err.message;
    }
}

/* ---------- Импорт свалки из папки ---------- */
const scanFolderBtn = document.getElementById("scanFolderBtn");
if (scanFolderBtn) {
    scanFolderBtn.addEventListener("click", async () => {
        const pathInput = document.getElementById("folderPath");
        const status = document.getElementById("folderStatus");
        const path = (pathInput.value || "").trim();
        if (!path) { status.textContent = "Укажите путь к папке со свалкой файлов."; return; }
        scanFolderBtn.disabled = true;
        status.textContent = "Сканирую папку…";
        try {
            const r = await apiFetch("/files/scan-folder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    path: path,
                    recursive: document.getElementById("folderRecursive").checked,
                }),
            });
            const data = await r.json();
            if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка импорта");
            const parts = [
                "принято: " + data.queued,
                "дубликаты: " + data.duplicates,
                "не поддерживаются: " + data.unsupported,
                "ошибки: " + (data.failed + (data.errors || []).length),
            ];
            if (data.too_large) parts.push("слишком большие: " + data.too_large);
            if (data.skipped) parts.push("служебных пропущено: " + data.skipped);
            if (data.truncated) parts.push("⚠️ достигнут лимит скана, импортирована часть");
            status.textContent = "Готово: " + parts.join(" · ");
            const uploadStatus = document.getElementById("uploadStatus");
            (data.file_ids || []).slice(0, 30).forEach((fid) => {
                const item = document.createElement("div");
                item.className = "upload-item";
                item.textContent = "⏳ файл id " + fid + " — обработка…";
                uploadStatus.prepend(item);
                pollFile(fid, item);
            });
        } catch (err) {
            status.textContent = "❌ " + err.message;
        } finally {
            scanFolderBtn.disabled = false;
        }
    });
}

/* ---------- Разгребание свалки по тематическим папкам ---------- */
const sortFolderBtn = document.getElementById("sortFolderBtn");
if (sortFolderBtn) {
    const sortStatus = document.getElementById("sortStatus");
    // интервал опроса приходит из config.yaml (sorting.poll_interval_ms); || 1000 — страховка
    const SORT_POLL_MS = parseInt(sortFolderBtn.closest(".folder-panel").dataset.pollMs, 10) || 1000;

    sortFolderBtn.addEventListener("click", async () => {
        const dump = (document.getElementById("sortDumpPath").value || "").trim();
        const out = (document.getElementById("sortOutputPath").value || "").trim();
        if (!dump) { sortStatus.textContent = "Укажите папку со свалкой."; return; }
        sortFolderBtn.disabled = true;
        sortStatus.textContent = "Запускаю разбор…";
        try {
            const body = { path: dump, recursive: document.getElementById("sortRecursive").checked };
            if (out) body.output_path = out;
            const r = await apiFetch("/files/sort-folder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await r.json();
            if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось запустить разбор");
            pollSort(data.job_id);
        } catch (err) {
            sortStatus.textContent = "❌ " + err.message;
            sortFolderBtn.disabled = false;
        }
    });

    async function pollSort(jobId) {
        try {
            const r = await apiFetch("/files/sort-folder/" + jobId);
            const data = await r.json();
            if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка статуса разбора");
            if (data.state === "running") {
                const phase = PHASES[data.phase] || "Работаю";
                sortStatus.textContent = "⏳ " + phase + "… (" + data.progress.processed + "/" + data.progress.total + ")";
                setTimeout(() => pollSort(jobId), SORT_POLL_MS);
                return;
            }
            if (data.state === "error") {
                sortStatus.textContent = "❌ " + (data.error || "Ошибка разбора");
                sortFolderBtn.disabled = false;
                return;
            }
            const res = data.result;
            const lines = [
                "✅ Готово: " + escapeHtml(res.run_dir) +
                " — " + (res.mode === "move" ? "перемещено" : "скопировано") +
                " файлов: " + (res.copied + res.moved),
            ];
            (res.folders || []).forEach((f) => {
                lines.push("📁 " + escapeHtml(f.folder) + " — " + f.count);
            });
            if (res.fallback_used) lines.push("⚠️ без LLM-названий: " + res.fallback_used);
            if ((res.errors || []).length) lines.push("❌ ошибок: " + res.errors.length);
            sortStatus.innerHTML = lines.join("<br>");
            sortFolderBtn.disabled = false;
        } catch (err) {
            sortStatus.textContent = "❌ " + err.message;
            sortFolderBtn.disabled = false;
        }
    }
}

/* ---------- Админ ---------- */
async function loadJobs() {
    const r = await apiFetch("/admin/jobs?limit=100");
    const data = await r.json();
    const tb = document.querySelector("#jobsTable tbody");
    tb.innerHTML = "";
    for (const j of data.jobs) {
        const tr = document.createElement("tr");
        tr.innerHTML = "<td>" + j.id + "</td><td>" + escapeHtml(j.kind) + "</td><td>" +
            (j.file_id || "-") + "</td><td>" + escapeHtml(j.status) + "</td><td>" + j.attempts +
            "</td><td>" + escapeHtml((j.last_error || "").slice(0, 120)) + "</td>";
        tb.appendChild(tr);
    }
}

async function reindexAll() {
    const r = await apiFetch("/admin/reindex", { method: "POST" });
    if (r.ok) { alert("Переиндексация поставлена в очередь"); loadJobs(); }
}

async function loadMetrics() {
    const r = await apiFetch("/admin/metrics");
    const data = await r.json();
    document.getElementById("metricsBox").textContent = JSON.stringify(data, null, 2);
}

/* ---------- v2.9.1: Прогресс эмбеддингинга (автообновление) ---------- */
const progressPanel = document.getElementById("progressPanel");
if (progressPanel) {
    const PROGRESS_MS = parseInt(progressPanel.dataset.statusMs, 10) || 2000;
    let progressTimer = null;

    function fmtSize(bytes) {
        if (!bytes && bytes !== 0) return "-";
        if (bytes < 1024) return bytes + " Б";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " КБ";
        return (bytes / 1024 / 1024).toFixed(1) + " МБ";
    }

    function counterChip(label, value, cls) {
        return "<div class='pcounter " + (cls || "") + "'><div class='pcounter-num'>"
            + value + "</div><div class='pcounter-label'>" + label + "</div></div>";
    }

    async function loadProgress() {
        try {
            const r = await apiFetch("/admin/ingest/progress");
            if (!r.ok) return;
            const d = await r.json();
            // счётчики очереди
            const q = d.queue || {};
            const emb = d.embedding || {};
            document.getElementById("progressCounters").innerHTML =
                counterChip("в очереди", q.queued || 0, q.queued ? "warn" : "")
                + counterChip("в работе", q.processing || 0, q.processing ? "run" : "")
                + counterChip("готово", q.done || 0, "ok")
                + counterChip("сбои", q.failed || 0, q.failed ? "err" : "")
                + counterChip("за час", (d.throughput || {}).done_last_hour || 0, "")
                + counterChip("сек/файл", (d.throughput || {}).avg_sec_per_file ?? "-", "");
            // что прямо сейчас делает воркер + на чём эмбеддинг
            const cur = (d.current || [])[0];
            let curLine = "Воркер: " + (d.worker_alive ? "работает" : "остановлен");
            curLine += " · эмбеддинг: " + escapeHtml(String(emb.resolved_backend || "?"))
                + " (" + escapeHtml(String(emb.model || emb.api_model || "?")) + ")"
                + " · dim " + (emb.dim ?? "?")
                + " · векторных точек: " + (emb.count ?? "?");
            if (cur) {
                curLine = "📄 <b>" + escapeHtml(cur.file_name) + "</b> (" + escapeHtml(cur.kind) +
                    ", попытка " + cur.attempts + (cur.elapsed_sec != null ? ", " + cur.elapsed_sec + " с" : "") +
                    ") — " + curLine;
            }
            document.getElementById("progressCurrent").innerHTML = curLine;
            // таблица последних файлов
            const tb = document.querySelector("#progressTable tbody");
            tb.innerHTML = (d.recent_files || []).map((f) =>
                "<tr><td>" + f.id + "</td><td>" + escapeHtml(f.name) + "</td><td>"
                + escapeHtml(f.doc_type) + "</td><td>" + escapeHtml(f.status) + "</td><td>"
                + f.chunks + "</td><td class='muted'>" + escapeHtml(String(f.updated_at || "").replace("T", " ")) + "</td></tr>"
            ).join("");
            // недавние сбои
            const fails = d.failed_recent || [];
            document.getElementById("progressFailed").innerHTML = fails.length
                ? "<b class='error'>Недавние сбои:</b> " + fails.map((f) =>
                    escapeHtml(f.file_name) + " — " + escapeHtml((f.last_error || "").slice(0, 140))
                ).join(" · ")
                : "";
            progressTimer = setTimeout(loadProgress, PROGRESS_MS);
        } catch (err) { /* сеть/выход — тихо ждём следующего тика */ }
    }
    loadProgress();
}

/* ---------- v2.9.1: Модели агента ---------- */
async function loadModels() {
    const r = await apiFetch("/admin/models");
    const data = await r.json();
    const box = document.getElementById("modelsBox");
    if (!box) return;
    const row = (role, model, provider, note) =>
        "<tr><td>" + escapeHtml(role) + "</td><td><b>" + escapeHtml(model || "-") + "</b></td><td>"
        + escapeHtml(provider || "-") + "</td><td class='muted'>" + escapeHtml(note || "") + "</td></tr>";
    const llm = data.llm || {}, emb = data.embeddings || {}, vec = data.vector || {};
    const rer = data.reranker || {}, ocr = data.ocr || {};
    box.innerHTML =
        "<table class='table'><thead><tr><th>Роль</th><th>Модель</th><th>Провайдер / URL</th><th>Примечание</th></tr></thead><tbody>"
        + row("LLM основная (ответы, глубокое чтение)", llm.model_main, llm.provider + " · " + llm.base_url,
              "ключ: " + (llm.api_key_set ? "задан" : "НЕТ") + ", t=" + llm.temperature + ", timeout " + llm.timeout_sec + " с")
        + row("LLM лёгкая (классификация, заметки)", llm.model_light, llm.provider + " · " + llm.base_url,
              "ретраи при 429: " + llm.rate_limit_retries)
        + row("LLM планировщик", llm.planner_model, llm.provider,
              "планировщик: " + (llm.planner_enabled ? "вкл" : "выкл") + " (config: " + llm.planner_config + ")")
        + row("Эмбеддинги (фактический backend)", emb.model, emb.resolved_backend,
              "backend в конфиге: " + emb.backend + " · устройство: " + emb.device + " · dim: " + emb.dimensions
              + " · префиксы: '" + emb.query_prefix + "'/'" + emb.passage_prefix + "'")
        + row("Эмбеддинги API (запасной конфиг)", emb.api_model, emb.api_base_url,
              "dimensions: " + emb.api_dimensions + " · batch " + emb.batch_size)
        + row("Векторное хранилище", vec.collection || "-", vec.backend,
              "dim " + (vec.dim ?? "?") + " · метрика " + vec.metric + " · точек: " + (vec.count ?? "?")
              + (vec.auto_collection_suffix ? " · суффикс-авто" : ""))
        + row("Реранкер", rer.model, rer.backend, "top_k " + rer.top_k)
        + row("OCR", "-", ocr.engine, "языки: " + (ocr.langs || []).join(",") + " · min conf " + ocr.min_confidence)
        + "</tbody></table>";
    document.getElementById("packagesBox").textContent =
        "Версии пакетов:\n" + Object.entries(data.packages || {})
            .map(([k, v]) => k + " == " + v).join("\n");
}

/* ---------- v2.9.1: Документы и чанки; v3.0.0: CRUD ---------- */
async function loadDocuments() {
    const r = await apiFetch("/admin/documents?limit=200");
    const data = await r.json();
    const tb = document.querySelector("#documentsTable tbody");
    if (!tb) return;
    tb.innerHTML = (data.files || []).map((f) =>
        "<tr><td>" + f.id + "</td><td>" + escapeHtml(f.name) + "</td><td>" + escapeHtml(f.doc_type)
        + "</td><td>" + fmtSize(f.size_bytes) + "</td><td>" + escapeHtml(f.status)
        + "</td><td>" + f.chunks + "</td><td><button class='btn' onclick='loadChunks(" + f.id
        + ")'>Чанки</button> <button class='btn' onclick='reprocessDoc(" + f.id
        + ")' title='Полная переобработка из оригинала'>Заново</button> <button class='btn btn-ghost' onclick='deleteDoc(" + f.id
        + ")'>🗑</button></td></tr>"
    ).join("");
}

async function reprocessDoc(fileId) {
    if (!confirm("Полностью переобработать файл " + fileId + " из оригинала (извлечение, чанки, эмбеддинги)?")) return;
    const r = await apiFetch("/admin/documents/" + fileId + "/reprocess", { method: "POST" });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    alert(data.message || "Поставлено в очередь");
    loadJobs();
}

async function deleteDoc(fileId) {
    if (!confirm("Удалить документ " + fileId + " вместе с чанками и векторами? Действие необратимо.")) return;
    if (!confirm("Точно удалить? Восстановить можно только повторной загрузкой файла.")) return;
    const r = await apiFetch("/admin/documents/" + fileId, { method: "DELETE" });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка удаления"); return; }
    loadDocuments();
}

async function loadChunks(fileId) {
    const box = document.getElementById("chunksBox");
    const list = document.getElementById("chunksList");
    const title = document.getElementById("chunksTitle");
    try {
        const r = await apiFetch("/admin/documents/" + fileId + "/chunks");
        const data = await r.json();
        if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ошибка");
        title.textContent = "Чанки: " + data.file.name + " (id " + data.file.id + ", "
            + data.file.status + ") — всего " + data.chunks_total;
        list.innerHTML = (data.chunks || []).map((c) =>
            "<details class='chunk-item' data-chunk-id='" + c.id + "'><summary>#" + c.chunk_index
            + (c.page != null ? " · стр. " + c.page : "")
            + " · " + c.chars + " симв. "
            + "<button class='btn btn-ghost' onclick='event.preventDefault();editChunk(" + c.id + ")'>Изм.</button> "
            + "<button class='btn btn-ghost' onclick='event.preventDefault();delChunk(" + c.id + ")'>×</button></summary>"
            + "<pre class='chunk-text'>" + escapeHtml(c.text)
            + (c.truncated ? "\n… (обрезано, полных " + c.chars + " симв.)" : "") + "</pre>"
            + "<div class='chunk-editor' hidden><textarea class='folder-input' rows='6'></textarea>"
            + "<button class='btn btn-primary' onclick='saveChunk(" + c.id + ")'>Сохранить</button></div></details>"
        ).join("") || "<span class='muted'>У файла нет чанков (не обработан или пуст).</span>";
        box.hidden = false;
        box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
        box.hidden = false;
        list.innerHTML = "<span class='error'>Не удалось загрузить чанки: " + escapeHtml(err.message) + "</span>";
    }
}

function editChunk(chunkId) {
    const item = document.querySelector("details.chunk-item[data-chunk-id='" + chunkId + "']");
    if (!item) return;
    item.open = true;
    const editor = item.querySelector(".chunk-editor");
    const ta = editor.querySelector("textarea");
    if (!ta.value) ta.value = item.querySelector(".chunk-text").textContent.replace("\n… (обрезано, полных" + " " + "симв.)", "").trim();
    editor.hidden = false;
    ta.focus();
}

async function saveChunk(chunkId) {
    const item = document.querySelector("details.chunk-item[data-chunk-id='" + chunkId + "']");
    const text = item.querySelector(".chunk-editor textarea").value;
    const r = await apiFetch("/admin/chunks/" + chunkId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка сохранения"); return; }
    alert(data.message || "Сохранено");
}

async function delChunk(chunkId) {
    if (!confirm("Удалить чанк " + chunkId + " из БД и векторной базы?")) return;
    const r = await apiFetch("/admin/chunks/" + chunkId, { method: "DELETE" });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка удаления"); return; }
    document.querySelector("details.chunk-item[data-chunk-id='" + chunkId + "']")?.remove();
}

async function loadLogs() {
    const r = await apiFetch("/admin/logs?tail=200");
    const data = await r.json();
    document.getElementById("logsBox").textContent = data.lines.join("\n");
}

async function loadDebug() {
    const r = await apiFetch("/admin/debug");
    const data = await r.json();
    document.getElementById("debugBox").textContent = JSON.stringify(data, null, 2);
}

async function copyDebug() {
    const box = document.getElementById("debugBox");
    if (!box.textContent) await loadDebug();
    if (!box.textContent) { alert("Диагностика пуста"); return; }
    try {
        await navigator.clipboard.writeText(box.textContent);
        alert("Диагностика скопирована — вставьте её в чат с разработчиком");
    } catch (e) {
        // clipboard API может быть недоступен (http) — резервный способ
        const ta = document.createElement("textarea");
        ta.value = box.textContent;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        alert("Диагностика скопирована — вставьте её в чат с разработчиком");
    }
}

/* ---------- v3.0.0: Обратная связь (проверенные ответы) ---------- */
let feedbackCache = [];

async function loadFeedback() {
    const r = await apiFetch("/feedback/admin/list?limit=300");
    const data = await r.json();
    feedbackCache = data.items || [];
    const st = data.stats || {};
    const statsEl = document.getElementById("feedbackStats");
    if (statsEl) statsEl.textContent = "всего: " + (st.total || 0) + " · активных: " + (st.active || 0)
        + " · 👍: " + (st.up || 0) + " · 👎: " + (st.down || 0)
        + " · с исправлениями: " + (st.with_correction || 0)
        + " · применений: " + (st.uses || 0);
    const tb = document.querySelector("#feedbackTable tbody");
    if (!tb) return;
    tb.innerHTML = feedbackCache.map((f) =>
        "<tr><td>" + f.id + "</td><td class='fb-qcell'>" + escapeHtml(f.question.slice(0, 80))
        + ((f.question.length > 80) ? "…" : "") + "</td><td>" + (f.rating === "up" ? "👍" : "👎")
        + "</td><td>" + escapeHtml(f.status) + "</td><td>" + (f.corrected_answer ? "✅" : "—")
        + "</td><td>" + f.weight + "</td><td>" + f.uses_count + "</td><td>"
        + escapeHtml((f.file_ids || []).join(",")) + "</td>"
        + "<td><button class='btn' onclick='editFeedback(" + f.id + ")'>Изм.</button> "
        + "<button class='btn' onclick='toggleFeedback(" + f.id + ")'>" + (f.status === "active" ? "Выкл" : "Вкл")
        + "</button> <button class='btn btn-ghost' onclick='delFeedback(" + f.id + ")'>🗑</button></td></tr>"
    ).join("") || "<tr><td colspan='9' class='muted'>Пока пусто — поставьте 👍/👎 под ответом в чате.</td></tr>";
}

function editFeedback(id) {
    const f = feedbackCache.find((x) => x.id === id);
    if (!f) return;
    document.getElementById("feedbackEditor").hidden = false;
    document.getElementById("fbEditId").textContent = "№ " + id;
    document.getElementById("fbQuestion").value = f.question;
    document.getElementById("fbCorrected").value = f.corrected_answer || "";
    document.getElementById("fbRating").value = f.rating;
    document.getElementById("fbStatus").value = f.status;
    document.getElementById("fbWeight").value = f.weight;
    document.getElementById("fbFileIds").value = (f.file_ids || []).join(",");
}

async function saveFeedback() {
    const id = parseInt((document.getElementById("fbEditId").textContent || "").replace(/\D/g, ""), 10);
    if (!id) return;
    const body = {
        question: document.getElementById("fbQuestion").value,
        corrected_answer: document.getElementById("fbCorrected").value,
        rating: document.getElementById("fbRating").value,
        status: document.getElementById("fbStatus").value,
        weight: parseFloat(document.getElementById("fbWeight").value) || 1.0,
        file_ids: document.getElementById("fbFileIds").value.split(",")
            .map((x) => parseInt(x.trim(), 10)).filter((x) => !isNaN(x)),
    };
    const r = await apiFetch("/feedback/admin/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка сохранения"); return; }
    document.getElementById("feedbackEditor").hidden = true;
    loadFeedback();
}

async function toggleFeedback(id) {
    const f = feedbackCache.find((x) => x.id === id);
    if (!f) return;
    const r = await apiFetch("/feedback/admin/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: f.status === "active" ? "disabled" : "active" }),
    });
    if (r.ok) loadFeedback();
}

async function delFeedback(id) {
    if (!confirm("Удалить запись обратной связи " + id + "?")) return;
    const r = await apiFetch("/feedback/admin/" + id, { method: "DELETE" });
    if (r.ok) loadFeedback();
}

async function reembedFeedback() {
    if (!confirm("Пересобрать векторы вопросов текущей моделью эмбеддингов? (нужно после смены модели)")) return;
    const r = await apiFetch("/feedback/admin/reembed", { method: "POST" });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    alert(data.message || "Готово");
}

/* ---------- v3.0.0: Пользователи и группы (users.yaml) ---------- */
let usersSnapshot = null;

async function loadUsersPanel() {
    const r = await apiFetch("/admin/users");
    const data = await r.json();
    usersSnapshot = data;
    const info = document.getElementById("usersFileInfo");
    if (info) info.textContent = "файл: " + data.file + " (бэкап: .bak) — скопируйте его, чтобы сохранить пользователей";
    const tb = document.querySelector("#usersTable tbody");
    if (!tb) return;
    tb.innerHTML = (data.users || []).map((u) =>
        "<tr><td><b>" + escapeHtml(u.username) + "</b></td><td>" + escapeHtml(u.display_name || "")
        + "</td><td>" + escapeHtml((u.groups || []).join(", ")) + "</td><td class='muted'>"
        + escapeHtml((u.permissions || []).join(", ")) + "</td><td>"
        + (u.is_active ? "✅" : "⛔") + "</td><td>"
        + "<button class='btn' onclick=\"setPassword('" + escapeHtml(u.username) + "')\">Пароль</button> "
        + "<button class='btn' onclick=\"toggleUser('" + escapeHtml(u.username) + "', " + (!u.is_active) + "\")\">"
        + (u.is_active ? "Откл." : "Вкл.") + "</button> "
        + "<button class='btn btn-ghost' onclick=\"deleteUser('" + escapeHtml(u.username) + "')\">🗑</button></td></tr>"
    ).join("");
    const gb = document.getElementById("groupsBox");
    const perms = data.known_permissions || [];
    gb.innerHTML = Object.entries(data.groups || {}).map(([name, g]) =>
        "<div class='group-editor' data-group='" + escapeHtml(name) + "'>"
        + "<b>" + escapeHtml(name) + "</b> "
        + (name !== "admins" ? "<button class='btn btn-ghost' onclick='deleteGroup(\"" + escapeHtml(name) + "\")'>удалить</button>" : "<span class='muted'>системная</span>")
        + "<div class='perm-checks'>" + perms.map((p) =>
            "<label class='checkline'><input type='checkbox' data-perm='" + p + "'"
            + ((g.permissions || []).includes(p) ? " checked" : "") + "> " + p + "</label>").join("")
        + "</div>"
        + "<textarea class='folder-input' rows='2' data-roots placeholder='Разрешённые корни файловых операций, по одному на строку (D:/Документы)'>"
        + escapeHtml((g.allowed_roots || []).join("\n")) + "</textarea>"
        + "<button class='btn btn-primary' onclick='saveGroup(\"" + escapeHtml(name) + "\")'>Сохранить группу</button>"
        + "</div>"
    ).join("");
}

async function createUser() {
    const username = document.getElementById("newUserName").value.trim();
    const password = document.getElementById("newUserPass").value;
    const groups = document.getElementById("newUserGroups").value.split(",")
        .map((x) => x.trim()).filter(Boolean);
    const r = await apiFetch("/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username, password: password, groups: groups }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка создания"); return; }
    document.getElementById("newUserName").value = "";
    document.getElementById("newUserPass").value = "";
    loadUsersPanel();
}

async function setPassword(username) {
    const p = prompt("Новый пароль для " + username + " (мин. 4 символа):");
    if (!p) return;
    const r = await apiFetch("/admin/users/" + encodeURIComponent(username), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: p }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    alert("Пароль обновлён и сохранён в users.yaml");
}

async function toggleUser(username, newState) {
    const r = await apiFetch("/admin/users/" + encodeURIComponent(username), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: newState }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    loadUsersPanel();
}

async function deleteUser(username) {
    if (!confirm("Удалить пользователя " + username + " из users.yaml?")) return;
    const r = await apiFetch("/admin/users/" + encodeURIComponent(username), { method: "DELETE" });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    loadUsersPanel();
}

async function createGroup() {
    const name = document.getElementById("newGroupName").value.trim();
    if (!name) return;
    const r = await apiFetch("/admin/groups/" + encodeURIComponent(name), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permissions: ["chat", "feedback_submit", "files_view"], allowed_roots: [] }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    document.getElementById("newGroupName").value = "";
    loadUsersPanel();
}

async function saveGroup(name) {
    const el = document.querySelector(".group-editor[data-group='" + name + "']");
    const permissions = [...el.querySelectorAll("input[data-perm]:checked")].map((x) => x.dataset.perm);
    const allowed_roots = el.querySelector("textarea[data-roots]").value.split("\n")
        .map((x) => x.trim()).filter(Boolean);
    const r = await apiFetch("/admin/groups/" + encodeURIComponent(name), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permissions: permissions, allowed_roots: allowed_roots }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    loadUsersPanel();
}

async function deleteGroup(name) {
    if (!confirm("Удалить группу " + name + "?")) return;
    const r = await apiFetch("/admin/groups/" + encodeURIComponent(name), { method: "DELETE" });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    loadUsersPanel();
}

/* ---------- v3.0.0: Файлы на диске ---------- */
async function loadLocations() {
    const r = await apiFetch("/admin/file-locations?limit=500");
    const data = await r.json();
    document.getElementById("allowedRoots").textContent =
        (data.allowed_roots_config || []).join("; ") || "не заданы (см. files.allowed_roots и allowed_roots групп)";
    const tb = document.querySelector("#locationsTable tbody");
    if (!tb) return;
    tb.innerHTML = (data.items || []).map((l) =>
        "<tr><td>" + l.file_id + "</td><td>" + escapeHtml(l.file_name) + "</td><td class='loc-path'>"
        + escapeHtml(l.path) + (l.exists ? "" : " <span class='error'>(нет на диске)</span>")
        + "</td><td>" + escapeHtml(l.kind) + "</td><td>" + (l.is_current ? "✅" : "—") + "</td><td>"
        + "<button class='btn' onclick='copyPath(" + l.id + ")'>Копировать</button> "
        + "<button class='btn' onclick='moveCopyFile(" + l.file_id + ", \"move\")'>Переместить</button> "
        + "<button class='btn' onclick='moveCopyFile(" + l.file_id + ", \"copy\")'>Копировать файл</button> "
        + "<button class='btn btn-ghost' onclick='forgetLocation(" + l.id + ")'>Забыть</button></td></tr>"
    ).join("") || "<tr><td colspan='6' class='muted'>Путей нет — импортируйте папку или запомните путь вручную.</td></tr>";
}

async function addLocation() {
    const fileId = parseInt(document.getElementById("locFileId").value, 10);
    const path = document.getElementById("locPath").value.trim();
    if (!fileId || !path) { alert("Укажите file_id и путь"); return; }
    const r = await apiFetch("/admin/file-locations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: fileId, path: path }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка"); return; }
    loadLocations();
}

async function forgetLocation(id) {
    if (!confirm("Забыть этот путь?")) return;
    const r = await apiFetch("/admin/file-locations/" + id, { method: "DELETE" });
    if (r.ok) loadLocations();
}

async function moveCopyFile(fileId, op) {
    const dest = prompt("Папка назначения (абсолютный путь, например D:/Отчёты):");
    if (!dest) return;
    const r = await apiFetch("/admin/files/" + fileId + "/" + op, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dest: dest, create_dest: true }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка операции"); return; }
    alert((op === "move" ? "Перемещено: " : "Скопировано: ") + data.from + " -> " + data.to);
    loadLocations();
}

async function mkdirHere() {
    const path = document.getElementById("mkdirPath").value.trim();
    if (!path) { alert("Укажите абсолютный путь"); return; }
    const r = await apiFetch("/admin/files/mkdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
    });
    const data = await r.json();
    if (!r.ok) { alert(typeof data.detail === "string" ? data.detail : "Ошибка создания"); return; }
    alert("Папка создана: " + data.path);
}

function copyPath(locId) {
    const row = [...document.querySelectorAll("#locationsTable tbody tr")].find((tr) =>
        tr.innerHTML.includes("copyPath(" + locId + ")"));
    if (!row) return;
    const text = row.querySelector(".loc-path").textContent.trim();
    navigator.clipboard?.writeText(text).catch(() => {});
}

if (document.getElementById("jobsTable")) {
    // v2.9.1: + модели, документы; v3.0.0: + фидбэк, пользователи, файлы
    loadJobs(); loadMetrics(); loadModels(); loadDocuments(); loadLogs(); loadDebug();
    loadFeedback(); loadUsersPanel(); loadLocations();
}
