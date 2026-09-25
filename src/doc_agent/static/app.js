/* Документовед — клиентский JavaScript */

let token = localStorage.getItem('token') || '';

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;

    addMessage('user', text);
    input.value = '';

    try {
        const resp = await fetch('/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ q: text, limit: 20 }),
        });

        if (resp.status === 401) {
            window.location.href = '/login';
            return;
        }

        const data = await resp.json();
        addMessage('agent', data.answer || 'НЕТ ДАННЫХ');
    } catch (err) {
        addMessage('system', 'Ошибка соединения с сервером');
    }
}

function addMessage(role, text) {
    const messages = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

async function uploadFiles(files) {
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);

        addMessage('system', `Загрузка: ${file.name}...`);

        try {
            const resp = await fetch('/files/upload', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData,
            });
            const data = await resp.json();
            addMessage('system', data.message || 'Файл принят');
        } catch (err) {
            addMessage('system', `Ошибка загрузки: ${file.name}`);
        }
    }
}

// Enter to send
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('chat-input');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
});
