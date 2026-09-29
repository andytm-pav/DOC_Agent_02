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
    if (m.recall) bits.push("📦 из архива памяти");
    if (typeof m.grounded === "boolean") bits.push(m.grounded ? "✅ подтверждено файлами" : "⚠️ не подтверждено");
    if (m.confidence != null) bits.push("уверенность: " + m.confidence);
    if (m.partial) bits.push("частичный ответ");
    if (bits.length) html += "<div class='meta'>" + bits.join(" · ") + "</div>";
    return html;
}

function renderMsg(kind, content, meta) {
    if (!chatBox) return null;
    const div = document.createElement("div");
    div.className = "msg " + kind;
    if (kind === "agent") {
        div.innerHTML = escapeHtml(content).replace(/\n/g, "<br>") + metaHtml(meta);
    } else {
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
        (data.items || []).forEach((m) => renderMsg(m.role === "user" ? "user" : "agent", m.content, m.meta));
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
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const input = document.getElementById("chatInput");
        const q = input.value.trim();
        if (!q) return;
        renderMsg("user", q);
        input.value = "";
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

if (document.getElementById("jobsTable")) { loadJobs(); loadMetrics(); loadLogs(); loadDebug(); }
