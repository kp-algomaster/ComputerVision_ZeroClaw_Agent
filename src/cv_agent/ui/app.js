/* ── CV Zero Claw Agent — Frontend App ── */

// ── State ──
let ws = null;
let currentView = 'chat';
let specRawMode = false;
let currentSpecRaw = '';

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    initNav();
    initChat();
    checkStatus();
});

// ── Navigation ──
function initNav() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const view = item.dataset.view;
            switchView(view);
        });
    });
}

function switchView(view) {
    currentView = view;

    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelector(`.nav-item[data-view="${view}"]`).classList.add('active');

    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.getElementById(`view-${view}`).classList.add('active');

    // Load data for the view
    if (view === 'vault') loadVaultTree();
    if (view === 'graph') loadGraph();
    if (view === 'specs') loadSpecs();
    if (view === 'digests') loadDigests();
}

// ── Status Check ──
async function checkStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        document.getElementById('statusDot').classList.add('online');
        document.getElementById('agentInfo').innerHTML =
            `<div>${data.agent}</div>` +
            `<div style="margin-top:2px">LLM: ${data.llm_model}</div>` +
            `<div>Vision: ${data.vision_model}</div>`;
    } catch (e) {
        document.getElementById('agentInfo').textContent = 'Offline';
    }
}

// ── Chat ──
function initChat() {
    const form = document.getElementById('chatForm');
    const input = document.getElementById('chatInput');

    // Auto-resize textarea
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Send on Enter (Shift+Enter for newline)
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.dispatchEvent(new Event('submit'));
        }
    });

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;

        addMessage('user', text);
        sendMessage(text);
        input.value = '';
        input.style.height = 'auto';
    });

    connectWebSocket();
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'typing') {
            document.getElementById('typingIndicator').hidden = !data.status;
            scrollChat();
        } else if (data.type === 'message') {
            addMessage('assistant', data.content, data.html);
        } else if (data.type === 'error') {
            addMessage('system', `Error: ${data.content}`);
        }
    };

    ws.onclose = () => {
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
        console.error('WebSocket error');
    };
}

function sendMessage(text) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ message: text }));
        document.getElementById('sendBtn').disabled = true;
        setTimeout(() => {
            document.getElementById('sendBtn').disabled = false;
        }, 1000);
    } else {
        addMessage('system', 'Connection lost. Reconnecting...');
        connectWebSocket();
    }
}

function addMessage(role, content, html) {
    const container = document.getElementById('chatMessages');
    const msg = document.createElement('div');
    msg.className = `message ${role}`;

    const label = document.createElement('div');
    label.className = 'message-label';
    label.textContent = role === 'user' ? 'You' : role === 'assistant' ? 'CV Agent' : '';

    const body = document.createElement('div');
    body.className = 'message-content';

    if (html) {
        body.innerHTML = html;
    } else {
        body.textContent = content;
    }

    if (label.textContent) msg.appendChild(label);
    msg.appendChild(body);
    container.appendChild(msg);

    // Highlight code blocks
    msg.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });

    // Render KaTeX
    renderMathInElement(msg);

    scrollChat();
}

function scrollChat() {
    const container = document.getElementById('chatMessages');
    container.scrollTop = container.scrollHeight;
}

function renderMathInElement(el) {
    // Render $$...$$ blocks
    el.innerHTML = el.innerHTML.replace(/\$\$([\s\S]*?)\$\$/g, (match, tex) => {
        try {
            return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false });
        } catch (e) {
            return match;
        }
    });
    // Render $...$ inline
    el.innerHTML = el.innerHTML.replace(/\$([^\$\n]+?)\$/g, (match, tex) => {
        try {
            return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false });
        } catch (e) {
            return match;
        }
    });
}

// ── Vault Tree ──
async function loadVaultTree() {
    try {
        const resp = await fetch('/api/vault/tree');
        const data = await resp.json();
        const container = document.getElementById('vaultTree');
        container.innerHTML = '';
        if (data.tree.length === 0) {
            container.innerHTML = '<p class="placeholder">Vault is empty. Process some papers to populate it.</p>';
            return;
        }
        container.appendChild(buildTree(data.tree));
    } catch (e) {
        console.error('Failed to load vault tree:', e);
    }
}

function buildTree(items) {
    const frag = document.createDocumentFragment();
    for (const item of items) {
        if (item.type === 'folder') {
            const folder = document.createElement('div');
            folder.className = 'tree-folder';
            folder.textContent = item.name;
            folder.addEventListener('click', () => {
                const children = folder.nextElementSibling;
                if (children) children.hidden = !children.hidden;
            });
            frag.appendChild(folder);

            if (item.children && item.children.length > 0) {
                const children = document.createElement('div');
                children.className = 'tree-children';
                children.appendChild(buildTree(item.children));
                frag.appendChild(children);
            }
        } else {
            const file = document.createElement('div');
            file.className = 'tree-file';
            file.textContent = item.name;
            file.addEventListener('click', () => {
                document.querySelectorAll('.tree-file').forEach(f => f.classList.remove('active'));
                file.classList.add('active');
                loadVaultNote(item.path);
            });
            frag.appendChild(file);
        }
    }
    return frag;
}

async function loadVaultNote(path) {
    try {
        const resp = await fetch(`/api/vault/note/${encodeURIComponent(path)}`);
        const data = await resp.json();
        document.getElementById('noteTitle').textContent = path;
        const container = document.getElementById('noteContent');
        container.innerHTML = data.html;
        container.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
        renderMathInElement(container);
    } catch (e) {
        console.error('Failed to load note:', e);
    }
}

// ── Knowledge Graph ──
async function loadGraph() {
    try {
        const resp = await fetch('/api/graph');
        const data = await resp.json();
        const stats = data.stats;
        document.getElementById('graphStats').textContent =
            `${stats.nodes} nodes · ${stats.edges} edges`;
        drawGraph(data.graph);
    } catch (e) {
        console.error('Failed to load graph:', e);
    }
}

function drawGraph(graphData) {
    const canvas = document.getElementById('graphCanvas');
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * window.devicePixelRatio;
    canvas.height = rect.height * window.devicePixelRatio;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    const W = rect.width;
    const H = rect.height;
    const nodes = graphData.nodes || [];
    const edges = graphData.edges || [];

    if (nodes.length === 0) {
        ctx.fillStyle = '#8b949e';
        ctx.font = '14px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No nodes yet. Process papers to build the graph.', W / 2, H / 2);
        return;
    }

    // Layout: simple force-directed (single pass for static render)
    const typeColors = {
        paper: '#58a6ff',
        method: '#f0883e',
        dataset: '#3fb950',
        task: '#f85149',
        author: '#d2a8ff',
        unknown: '#8b949e',
    };

    // Assign positions in a circle with some noise
    const positions = {};
    nodes.forEach((node, i) => {
        const angle = (2 * Math.PI * i) / nodes.length;
        const r = Math.min(W, H) * 0.35;
        positions[node.id] = {
            x: W / 2 + r * Math.cos(angle) + (Math.random() - 0.5) * 40,
            y: H / 2 + r * Math.sin(angle) + (Math.random() - 0.5) * 40,
        };
    });

    // Draw edges
    ctx.strokeStyle = '#30363d';
    ctx.lineWidth = 1;
    for (const edge of edges) {
        const from = positions[edge.source];
        const to = positions[edge.target];
        if (from && to) {
            ctx.beginPath();
            ctx.moveTo(from.x, from.y);
            ctx.lineTo(to.x, to.y);
            ctx.stroke();

            // Arrow
            const dx = to.x - from.x;
            const dy = to.y - from.y;
            const len = Math.sqrt(dx * dx + dy * dy);
            if (len > 0) {
                const nx = dx / len;
                const ny = dy / len;
                const ax = to.x - nx * 14;
                const ay = to.y - ny * 14;
                ctx.beginPath();
                ctx.moveTo(to.x - nx * 8, to.y - ny * 8);
                ctx.lineTo(ax - ny * 4, ay + nx * 4);
                ctx.lineTo(ax + ny * 4, ay - nx * 4);
                ctx.fillStyle = '#30363d';
                ctx.fill();
            }
        }
    }

    // Draw nodes
    for (const node of nodes) {
        const pos = positions[node.id];
        if (!pos) continue;
        const color = typeColors[node.type] || typeColors.unknown;
        const radius = node.type === 'paper' ? 8 : 6;

        ctx.beginPath();
        ctx.arc(pos.x, pos.y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = '#0d1117';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Label
        const label = (node.title || node.id || '').substring(0, 30);
        ctx.fillStyle = '#e6edf3';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(label, pos.x, pos.y + radius + 14);
    }

    // Legend
    let ly = 20;
    ctx.textAlign = 'left';
    for (const [type, color] of Object.entries(typeColors)) {
        ctx.beginPath();
        ctx.arc(20, ly, 5, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.fillStyle = '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.fillText(type, 32, ly + 4);
        ly += 18;
    }
}

// ── Specs ──
async function loadSpecs() {
    try {
        const resp = await fetch('/api/specs');
        const data = await resp.json();
        const container = document.getElementById('specsList');
        container.innerHTML = '';

        if (data.specs.length === 0) {
            container.innerHTML = '<p class="placeholder">No specs generated yet.</p>';
            return;
        }

        for (const spec of data.specs) {
            const item = document.createElement('div');
            item.className = 'file-list-item';
            item.innerHTML = `
                <div class="name">${spec.name}</div>
                <div class="meta">${formatBytes(spec.size)} · ${formatDate(spec.modified)}</div>
            `;
            item.addEventListener('click', () => {
                document.querySelectorAll('#specsList .file-list-item').forEach(el => el.classList.remove('active'));
                item.classList.add('active');
                loadSpec(spec.name);
            });
            container.appendChild(item);
        }
    } catch (e) {
        console.error('Failed to load specs:', e);
    }
}

async function loadSpec(filename) {
    try {
        const resp = await fetch(`/api/specs/${encodeURIComponent(filename)}`);
        const data = await resp.json();
        document.getElementById('specTitle').textContent = filename;
        document.getElementById('specRawToggle').hidden = false;
        currentSpecRaw = data.raw;
        specRawMode = false;

        const container = document.getElementById('specContent');
        container.innerHTML = data.html;
        container.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
        renderMathInElement(container);
    } catch (e) {
        console.error('Failed to load spec:', e);
    }
}

function toggleSpecRaw() {
    specRawMode = !specRawMode;
    const container = document.getElementById('specContent');
    const btn = document.getElementById('specRawToggle');

    if (specRawMode) {
        container.innerHTML = `<pre style="white-space:pre-wrap;word-break:break-word">${escapeHtml(currentSpecRaw)}</pre>`;
        btn.textContent = 'Rendered';
    } else {
        loadSpec(document.getElementById('specTitle').textContent);
        btn.textContent = 'Raw';
    }
}

// ── Digests ──
async function loadDigests() {
    try {
        const resp = await fetch('/api/digests');
        const data = await resp.json();
        const container = document.getElementById('digestsList');
        container.innerHTML = '';

        if (data.digests.length === 0) {
            container.innerHTML = '<p class="placeholder">No digests yet. Run: cv-agent digest</p>';
            return;
        }

        for (const digest of data.digests) {
            const item = document.createElement('div');
            item.className = 'file-list-item';
            item.innerHTML = `
                <div class="name">${digest.name}</div>
                <div class="meta">${formatBytes(digest.size)} · ${formatDate(digest.modified)}</div>
            `;
            item.addEventListener('click', () => {
                document.querySelectorAll('#digestsList .file-list-item').forEach(el => el.classList.remove('active'));
                item.classList.add('active');
                loadDigest(digest.name);
            });
            container.appendChild(item);
        }
    } catch (e) {
        console.error('Failed to load digests:', e);
    }
}

async function loadDigest(filename) {
    try {
        const resp = await fetch(`/api/digests/${encodeURIComponent(filename)}`);
        const data = await resp.json();
        document.getElementById('digestTitle').textContent = filename;

        const container = document.getElementById('digestContent');
        container.innerHTML = data.html;
        container.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
        renderMathInElement(container);
    } catch (e) {
        console.error('Failed to load digest:', e);
    }
}

// ── Helpers ──
function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatDate(isoStr) {
    try {
        return new Date(isoStr).toLocaleDateString(undefined, {
            month: 'short', day: 'numeric', year: 'numeric',
        });
    } catch {
        return isoStr;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
