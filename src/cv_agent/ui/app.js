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
    if (view === 'vault')   loadVaultTree();
    if (view === 'graph')   loadGraph();
    if (view === 'specs')   loadSpecs();
    if (view === 'digests') loadDigests();
    if (view === 'config')  loadConfig();
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

// ── Config / Model Management ──

async function loadConfig() {
    await Promise.all([loadZeroClawStatus(), loadHardwareAndRecommended(), loadPulledModels(), loadIntegrations()]);
}

async function loadZeroClawStatus() {
    const el = document.getElementById('zeroClawStatus');
    try {
        const resp = await fetch('/api/zeroclaw');
        const d = await resp.json();

        const modeLabel = d.mode === 'shim'
            ? '<span class="zc-value shim">Local Shim</span>'
            : '<span class="zc-value pkg">Real Package</span>';

        let updateHtml = '';
        if (d.update_available) {
            updateHtml = `<div class="zc-update-banner">
                ⬆ Update available: <strong>${d.pypi_version}</strong> (current: ${d.current_version})
                — run <code>pip install -U zeroclaw-tools</code>
            </div>`;
        } else if (!d.package_on_pypi && d.mode === 'shim') {
            updateHtml = `<div class="zc-not-on-pypi">
                zeroclaw-tools not yet on PyPI — using local compatibility shim.
                <div class="zc-install-hint">When published: <code>pip install zeroclaw-tools</code> then delete <code>src/zeroclaw_tools/</code></div>
            </div>`;
        }

        const toolsHtml = (d.builtin_tools || [])
            .map(t => `<span class="zc-tool-chip">${t}</span>`)
            .join('');

        el.innerHTML = `
            ${updateHtml}
            <div class="zc-grid">
                <div class="zc-card highlight">
                    <div class="zc-label">Mode</div>
                    ${modeLabel}
                </div>
                <div class="zc-card">
                    <div class="zc-label">Version</div>
                    <div class="zc-value">${d.current_version}</div>
                </div>
                <div class="zc-card">
                    <div class="zc-label">Agent Framework</div>
                    <div class="zc-value" style="font-size:11px">${d.agent_framework}</div>
                </div>
                <div class="zc-card">
                    <div class="zc-label">Tool Call Mode</div>
                    <div class="zc-value" style="font-size:10px;line-height:1.4">${d.tool_call_mode}</div>
                </div>
            </div>
            <div class="zc-label" style="margin-bottom:6px">Built-in Tools</div>
            <div class="zc-tools">${toolsHtml}</div>
        `;
    } catch (e) {
        el.innerHTML = '<p class="placeholder">Failed to load ZeroClaw status.</p>';
    }
}

async function loadHardwareAndRecommended() {
    try {
        const resp = await fetch('/api/models/recommended');
        const data = await resp.json();

        // Hardware panel
        const hw = data.hardware;
        const hwEl = document.getElementById('hardwareInfo');
        if (hw) {
            hwEl.innerHTML = `
                <div class="hw-grid">
                    <div class="hw-card">
                        <div class="hw-value">${hw.ram_gb.toFixed(0)} GB</div>
                        <div class="hw-label">System RAM</div>
                    </div>
                    <div class="hw-card">
                        <div class="hw-value">${hw.gpu_vram_gb.toFixed(0)} GB</div>
                        <div class="hw-label">GPU VRAM</div>
                    </div>
                    <div class="hw-card">
                        <div class="hw-value">${hw.cpu_cores}</div>
                        <div class="hw-label">CPU Cores</div>
                    </div>
                    <div class="hw-card">
                        <div class="hw-value">${hw.gpu_vram_gb > 0 ? 'GPU' : 'CPU'}</div>
                        <div class="hw-label">Inference Mode</div>
                    </div>
                    <div class="hw-accel">
                        <span>Acceleration</span>
                        <span class="accel-badge">${hw.acceleration.toUpperCase()}</span>
                    </div>
                </div>`;
        } else if (!data.llmfit_available) {
            hwEl.innerHTML = `<div class="llmfit-notice">
                ⚠️ <strong>llmfit not installed</strong> — hardware detection unavailable.<br>
                Install: <code>brew install llmfit</code>
            </div>`;
        } else {
            hwEl.innerHTML = '<p class="placeholder">Hardware info unavailable.</p>';
        }

        // Recommended models panel
        const recEl = document.getElementById('recommendedList');
        const badge = document.getElementById('llmfitBadge');
        if (!data.llmfit_available) {
            recEl.innerHTML = `<div class="llmfit-notice">Install llmfit to get hardware-matched recommendations.</div>`;
            badge.textContent = 'llmfit required';
            return;
        }
        const recs = data.recommended || [];
        badge.textContent = recs.length + ' models';
        if (recs.length === 0) {
            recEl.innerHTML = '<p class="placeholder">No recommendations found.</p>';
            return;
        }
        recEl.innerHTML = '';
        for (const m of recs) {
            const row = document.createElement('div');
            row.className = 'model-row';
            const fitCls = { perfect: 'fit-perfect', good: 'fit-good', marginal: 'fit-marginal' }[m.fit] || 'fit-unknown';
            row.innerHTML = `
                <span class="fit-badge ${fitCls}">${m.fit}</span>
                <span class="model-name" title="${m.name}:${m.quantization}">${m.name}:${m.quantization}</span>
                <span class="model-meta">${m.vram_gb}GB</span>
                <button class="btn-pull-sm" onclick="quickPull('${m.name}:${m.quantization}', this)">⬇</button>`;
            recEl.appendChild(row);
        }
    } catch (e) {
        document.getElementById('hardwareInfo').innerHTML = '<p class="placeholder">Failed to load.</p>';
        console.error(e);
    }
}

async function loadPulledModels() {
    try {
        const resp = await fetch('/api/models');
        const data = await resp.json();
        const container = document.getElementById('pulledModelsList');
        const badge = document.getElementById('pulledCount');
        const models = data.models || [];
        badge.textContent = models.length;

        if (models.length === 0) {
            container.innerHTML = '<p class="placeholder">No models pulled yet.</p>';
            return;
        }
        container.innerHTML = '';
        for (const name of models.sort()) {
            const row = document.createElement('div');
            row.className = 'model-row';
            row.innerHTML = `
                <span class="model-name" title="${name}">${name}</span>
                <button class="btn-delete" onclick="deleteModel('${name}', this)" title="Delete">✕</button>`;
            container.appendChild(row);
        }
    } catch (e) {
        document.getElementById('pulledModelsList').innerHTML = '<p class="placeholder">Failed to load.</p>';
    }
}

async function pullModel() {
    const input = document.getElementById('pullModelInput');
    const btn = document.getElementById('pullModelBtn');
    const status = document.getElementById('pullStatus');
    const model = input.value.trim();

    btn.disabled = true;
    btn.textContent = '⏳ Pulling…';
    status.hidden = false;
    status.className = 'pull-status';
    status.textContent = model ? `Pulling '${model}'…` : 'Auto-selecting and pulling best model…';

    try {
        const resp = await fetch('/api/models/pull', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model }),
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);

        status.className = 'pull-status success';
        status.textContent = data.message;
        input.value = '';
        await loadPulledModels();
    } catch (e) {
        status.className = 'pull-status error';
        status.textContent = 'Error: ' + e.message;
    } finally {
        btn.disabled = false;
        btn.textContent = '⬇ Pull';
    }
}

async function quickPull(modelTag, btn) {
    const status = document.getElementById('pullStatus');
    btn.disabled = true;
    btn.textContent = '⏳';
    status.hidden = false;
    status.className = 'pull-status';
    status.textContent = `Pulling '${modelTag}'…`;

    try {
        const resp = await fetch('/api/models/pull', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelTag }),
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        status.className = 'pull-status success';
        status.textContent = data.message;
        await loadPulledModels();
    } catch (e) {
        status.className = 'pull-status error';
        status.textContent = 'Error: ' + e.message;
    } finally {
        btn.disabled = false;
        btn.textContent = '⬇';
    }
}

async function deleteModel(name, btn) {
    if (!confirm(`Delete model '${name}'? This cannot be undone.`)) return;
    btn.disabled = true;
    try {
        const resp = await fetch(`/api/models/${encodeURIComponent(name)}`, { method: 'DELETE' });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        await loadPulledModels();
    } catch (e) {
        alert('Delete failed: ' + e.message);
        btn.disabled = false;
    }
}

// ── Remote Integrations ──

async function loadIntegrations() {
    const grid = document.getElementById('integrationCards');
    try {
        const resp = await fetch('/api/integrations');
        const data = await resp.json();
        grid.innerHTML = '';
        for (const [id, info] of Object.entries(data)) {
            grid.appendChild(buildIntegrationCard(id, info));
        }
    } catch (e) {
        grid.innerHTML = '<p class="placeholder">Failed to load integrations.</p>';
    }
}

function buildIntegrationCard(id, info) {
    const card = document.createElement('div');
    const statusClass = info.enabled ? 'enabled' : (info.configured ? 'connected' : '');
    card.className = `int-card ${statusClass}`;
    card.id = `int-card-${id}`;

    const dotClass = info.enabled ? 'ok' : (info.configured ? 'warn' : '');
    const statusLabel = info.enabled ? 'Enabled' : (info.configured ? 'Configured' : 'Not configured');

    // Build credential fields HTML
    const fieldsHtml = info.fields.map(f => `
        <div class="int-field">
            <label>${f.label}</label>
            <input type="${f.secret ? 'password' : 'text'}"
                   id="int-${id}-${f.key}"
                   placeholder="${escapeHtml(f.placeholder || '')}"
                   value="${escapeHtml(info.field_values[f.key] || '')}" />
        </div>`).join('');

    card.innerHTML = `
        <div class="int-card-head">
            <span class="int-icon">${info.icon}</span>
            <div class="int-info">
                <div class="int-title">
                    ${info.label}
                    <span class="int-status-dot ${dotClass}" title="${statusLabel}"></span>
                </div>
                <div class="int-desc">${info.description}</div>
            </div>
            <label class="int-toggle" title="${info.enabled ? 'Disable' : 'Enable'}">
                <input type="checkbox" id="int-toggle-${id}" ${info.enabled ? 'checked' : ''}
                       onchange="toggleIntegration('${id}', this.checked)">
                <span class="int-slider"></span>
            </label>
        </div>
        <div class="int-actions">
            <button class="int-btn" onclick="toggleIntegrationForm('${id}')">⚙ Configure</button>
            <button class="int-btn primary" id="int-test-${id}" onclick="testIntegration('${id}')">▷ Test</button>
        </div>
        <div class="int-form" id="int-form-${id}">
            ${fieldsHtml}
            <div class="int-docs">${escapeHtml(info.docs)}</div>
            <div class="int-save-row">
                <button class="int-btn primary" onclick="saveIntegration('${id}')">Save</button>
                <span class="int-save-status" id="int-save-status-${id}"></span>
            </div>
        </div>`;
    return card;
}

function toggleIntegrationForm(id) {
    const form = document.getElementById(`int-form-${id}`);
    form.classList.toggle('open');
}

async function toggleIntegration(id, enabled) {
    try {
        await fetch(`/api/integrations/${id}/configure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
        await loadIntegrations();
    } catch (e) {
        console.error('Toggle failed:', e);
    }
}

async function saveIntegration(id) {
    const statusEl = document.getElementById(`int-save-status-${id}`);
    statusEl.className = 'int-save-status';
    statusEl.textContent = 'Saving…';

    // Collect field values from inputs
    const fields = {};
    document.querySelectorAll(`#int-form-${id} input[id^="int-${id}-"]`).forEach(input => {
        const key = input.id.replace(`int-${id}-`, '');
        // Only send non-masked values (user has typed something real)
        if (input.value && !input.value.match(/^•+/)) {
            fields[key] = input.value;
        }
    });

    try {
        const resp = await fetch(`/api/integrations/${id}/configure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fields }),
        });
        const data = await resp.json();
        if (!data.ok) throw new Error(data.error || 'Unknown error');
        statusEl.className = 'int-save-status ok';
        statusEl.textContent = `Saved (${data.updated.length} key${data.updated.length !== 1 ? 's' : ''})`;
        await loadIntegrations();
    } catch (e) {
        statusEl.className = 'int-save-status error';
        statusEl.textContent = e.message;
    }
}

async function testIntegration(id) {
    const btn = document.getElementById(`int-test-${id}`);
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        const resp = await fetch(`/api/integrations/${id}/test`, { method: 'POST' });
        const data = await resp.json();
        btn.textContent = data.ok ? '✓' : '✗';
        btn.title = data.message;
        // Show result in save-status if form is open, else alert
        const statusEl = document.getElementById(`int-save-status-${id}`);
        if (statusEl) {
            statusEl.className = `int-save-status ${data.ok ? 'ok' : 'error'}`;
            statusEl.textContent = data.message;
            // Open form to show result
            document.getElementById(`int-form-${id}`).classList.add('open');
        }
        setTimeout(() => { btn.textContent = '▷ Test'; btn.title = ''; }, 3000);
    } catch (e) {
        btn.textContent = '✗';
        btn.title = e.message;
        setTimeout(() => { btn.textContent = '▷ Test'; btn.title = ''; }, 3000);
    } finally {
        btn.disabled = false;
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
