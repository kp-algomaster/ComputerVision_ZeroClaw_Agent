/* ── CV Assistant 👁️ — Frontend App ── */

// ── State ──
let ws = null;
let currentView = 'chat';
let specRawMode = false;
let currentSpecRaw = '';
let logWs = null;
let agentWs = null;
let currentAgentId = null;

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    initNav();
    initChat();
    initAgentChat();
    checkStatus();
});

// ═══════════════════════════════════════════════════════════════════════
// Navigation
// ═══════════════════════════════════════════════════════════════════════

function initNav() {
    // View switching
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => switchView(item.dataset.view));
    });
    // Section collapse toggles
    document.querySelectorAll('.nav-group-title').forEach(title => {
        title.addEventListener('click', () => {
            const targetId = title.dataset.toggle;
            const list = document.getElementById(targetId);
            const icon = title.querySelector('.toggle-icon');
            if (list) {
                list.classList.toggle('collapsed');
                icon.textContent = list.classList.contains('collapsed') ? '+' : '−';
            }
        });
    });
}

function switchView(view) {
    currentView = view;
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const activeItem = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (activeItem) activeItem.classList.add('active');

    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    const viewEl = document.getElementById(`view-${view}`);
    if (viewEl) viewEl.classList.add('active');

    // Load data per view
    const loaders = {
        overview: loadOverview,
        channels: loadChannels,
        instances: loadInstances,
        sessions: loadSessions,
        cron: loadCron,
        skills: loadSkills,
        powers: loadPowers,
        vault: loadVaultTree,
        graph: loadGraph,
        specs: loadSpecs,
        digests: loadDigests,
        config: loadConfig,
        cache: loadCacheStats,
        debug: loadDebug,
        logs: loadLogs,
        agents: loadAgents,
    };
    if (loaders[view]) loaders[view]();
}

// ═══════════════════════════════════════════════════════════════════════
// Status
// ═══════════════════════════════════════════════════════════════════════

async function checkStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        document.getElementById('statusDot').classList.add('online');
        document.getElementById('agentInfo').innerHTML =
            `<div>${data.agent}</div>` +
            `<div style="margin-top:2px">LLM: ${data.llm_model}</div>` +
            `<div>Vision: ${data.vision_model}</div>`;
    } catch {
        document.getElementById('agentInfo').textContent = 'Offline';
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Chat
// ═══════════════════════════════════════════════════════════════════════

function initChat() {
    const form = document.getElementById('chatForm');
    const input = document.getElementById('chatInput');

    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
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
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);
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
    ws.onclose = () => setTimeout(connectWebSocket, 3000);
    ws.onerror = () => console.error('WebSocket error');
}

function sendMessage(text) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ message: text }));
        document.getElementById('sendBtn').disabled = true;
        setTimeout(() => { document.getElementById('sendBtn').disabled = false; }, 1000);
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
    label.textContent = role === 'user' ? 'You' : role === 'assistant' ? 'CV Assistant' : '';

    const body = document.createElement('div');
    body.className = 'message-content';
    if (html) { body.innerHTML = html; } else { body.textContent = content; }

    if (label.textContent) msg.appendChild(label);
    msg.appendChild(body);
    container.appendChild(msg);

    msg.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
    renderMathInElement(msg);
    scrollChat();
}

function scrollChat() {
    const c = document.getElementById('chatMessages');
    c.scrollTop = c.scrollHeight;
}

function renderMathInElement(el) {
    el.innerHTML = el.innerHTML.replace(/\$\$([\s\S]*?)\$\$/g, (m, tex) => {
        try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }); } catch { return m; }
    });
    el.innerHTML = el.innerHTML.replace(/\$([^\$\n]+?)\$/g, (m, tex) => {
        try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }); } catch { return m; }
    });
}

// ═══════════════════════════════════════════════════════════════════════
// Overview
// ═══════════════════════════════════════════════════════════════════════

async function loadOverview() {
    const el = document.getElementById('overviewContent');
    try {
        const [ovResp, agentsResp, cacheResp] = await Promise.all([
            fetch('/api/overview'),
            fetch('/api/agents'),
            fetch('/api/cache/stats'),
        ]);
        const d = await ovResp.json();
        const agentsData = await agentsResp.json().catch(() => ({ agents: [] }));
        const cacheData = await cacheResp.json().catch(() => ({}));
        const agentsEnabled = (agentsData.agents || []).filter(a => a.enabled).length;
        const agentsTotal = (agentsData.agents || []).length;
        const hitPct = cacheData.hit_rate !== undefined ? (cacheData.hit_rate * 100).toFixed(0) + '%' : '—';
        el.innerHTML = `
            <div class="overview-grid">
                <div class="ov-card accent">
                    <div class="ov-icon">👁️</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.agent_name}</div>
                        <div class="ov-label">CV Assistant</div>
                    </div>
                    <span class="status-dot-lg ${d.status === 'ok' ? 'online' : ''}"></span>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">🤖</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.models_pulled}</div>
                        <div class="ov-label">Models Pulled</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">⚡</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.skills_ready} / ${d.skills_total}</div>
                        <div class="ov-label">Skills Ready</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">🔌</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.powers_active} / ${d.powers_total}</div>
                        <div class="ov-label">Nodes Active</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">🔗</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.channels_enabled} / ${d.channels_total}</div>
                        <div class="ov-label">Channels Enabled</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">📚</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.vault_notes}</div>
                        <div class="ov-label">Vault Notes</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">📋</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.specs_count}</div>
                        <div class="ov-label">Specs Generated</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">📰</div>
                    <div class="ov-info">
                        <div class="ov-value">${d.digests_count}</div>
                        <div class="ov-label">Weekly Digests</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">🤖</div>
                    <div class="ov-info">
                        <div class="ov-value">${agentsEnabled} / ${agentsTotal}</div>
                        <div class="ov-label">Agents Active</div>
                    </div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">💾</div>
                    <div class="ov-info">
                        <div class="ov-value">${hitPct}</div>
                        <div class="ov-label">Cache Hit Rate</div>
                    </div>
                </div>
            </div>
            <div class="ov-section">
                <h3>System</h3>
                <div class="ov-system-grid">
                    <div class="ov-sys-item"><span class="ov-sys-label">LLM Model</span><span class="ov-sys-val">${d.llm_model}</span></div>
                    <div class="ov-sys-item"><span class="ov-sys-label">Vision Model</span><span class="ov-sys-val">${d.vision_model}</span></div>
                    <div class="ov-sys-item"><span class="ov-sys-label">ZeroClaw</span><span class="ov-sys-val">${d.zeroclaw_mode}</span></div>
                    <div class="ov-sys-item"><span class="ov-sys-label">Vault Path</span><span class="ov-sys-val mono">${d.vault_path}</span></div>
                </div>
            </div>`;
    } catch (e) {
        el.innerHTML = '<p class="placeholder">Failed to load overview.</p>';
        console.error(e);
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Agents
// ═══════════════════════════════════════════════════════════════════════

async function loadAgents() {
    const grid = document.getElementById('agentsGrid');
    try {
        const resp = await fetch('/api/agents');
        const data = await resp.json();
        const agents = data.agents || [];
        if (agents.length === 0) {
            grid.innerHTML = '<p class="placeholder">No sub-agents configured.</p>';
            return;
        }
        grid.innerHTML = '';
        for (const agent of agents) {
            grid.appendChild(buildAgentCard(agent));
        }
    } catch {
        grid.innerHTML = '<p class="placeholder">Failed to load agents.</p>';
    }
}

function buildAgentCard(agent) {
    const card = document.createElement('div');
    card.className = `agent-card ${agent.enabled ? 'enabled' : 'disabled'}`;
    const statusLabel = agent.enabled ? 'enabled' : 'disabled';
    card.innerHTML = `
        <div class="agent-card-head">
            <span class="agent-icon">${agent.icon || '🤖'}</span>
            <div class="agent-info">
                <div class="agent-name">${agent.name}
                    <span class="status-badge ${agent.enabled ? 'active' : 'inactive'}">${statusLabel}</span>
                </div>
                <div class="agent-desc">${agent.description}</div>
            </div>
        </div>
        <div class="agent-model"><span class="config-key">Model:</span> <code>${agent.model}</code></div>
        <div class="agent-actions">
            <button class="int-btn primary" ${!agent.enabled ? 'disabled' : ''} onclick="openAgentChat('${agent.id}', '${agent.name}', '${agent.icon || '🤖'}', '${agent.model}')">
                💬 Chat
            </button>
        </div>`;
    return card;
}

function openAgentChat(id, name, icon, model) {
    currentAgentId = id;
    document.getElementById('agentChatIcon').textContent = icon;
    document.getElementById('agentChatName').textContent = name;
    document.getElementById('agentChatModel').textContent = model;
    document.getElementById('agentChatLabel').textContent = name;
    document.getElementById('nav-agent-chat').style.display = '';
    // Clear previous messages
    const msgs = document.getElementById('agentChatMessages');
    msgs.innerHTML = `<div class="message system"><div class="message-content">
        <p><strong>${icon} ${name}</strong> — ready.</p>
        <p>Ask this agent a task directly.</p>
    </div></div>`;
    // Connect WebSocket
    if (agentWs) { agentWs.close(); agentWs = null; }
    connectAgentWebSocket(id);
    switchView('agent-chat');
}

function connectAgentWebSocket(agentId) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    agentWs = new WebSocket(`${protocol}//${location.host}/ws/agent/${agentId}`);
    agentWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'typing') {
            document.getElementById('agentTypingIndicator').hidden = !data.status;
            scrollAgentChat();
        } else if (data.type === 'message') {
            addAgentMessage('assistant', data.content, data.html);
        } else if (data.type === 'error') {
            addAgentMessage('system', `Error: ${data.content}`);
        }
    };
    agentWs.onclose = () => {};
    agentWs.onerror = () => addAgentMessage('system', 'WebSocket error.');
}

function initAgentChat() {
    const form = document.getElementById('agentChatForm');
    const input = document.getElementById('agentChatInput');
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.dispatchEvent(new Event('submit')); }
    });
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text || !agentWs || agentWs.readyState !== WebSocket.OPEN) return;
        addAgentMessage('user', text);
        agentWs.send(JSON.stringify({ message: text }));
        document.getElementById('agentSendBtn').disabled = true;
        setTimeout(() => { document.getElementById('agentSendBtn').disabled = false; }, 1000);
        input.value = '';
        input.style.height = 'auto';
    });
}

function addAgentMessage(role, content, html) {
    const container = document.getElementById('agentChatMessages');
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    const label = document.createElement('div');
    label.className = 'message-label';
    const agentIcon = document.getElementById('agentChatIcon').textContent;
    const agentName = document.getElementById('agentChatName').textContent;
    label.textContent = role === 'user' ? 'You' : role === 'assistant' ? `${agentIcon} ${agentName}` : '';
    const body = document.createElement('div');
    body.className = 'message-content';
    if (html) { body.innerHTML = html; } else { body.textContent = content; }
    if (label.textContent) msg.appendChild(label);
    msg.appendChild(body);
    container.appendChild(msg);
    msg.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
    renderMathInElement(msg);
    scrollAgentChat();
}

function scrollAgentChat() {
    const c = document.getElementById('agentChatMessages');
    c.scrollTop = c.scrollHeight;
}

// ═══════════════════════════════════════════════════════════════════════
// Cache
// ═══════════════════════════════════════════════════════════════════════

async function loadCacheStats() {
    const el = document.getElementById('cacheContent');
    try {
        const resp = await fetch('/api/cache/stats');
        const d = await resp.json();
        if (d.enabled === false) {
            el.innerHTML = '<p class="placeholder">Cache is disabled (CACHE_ENABLED=false).</p>';
            return;
        }
        const hitPct = d.hit_rate !== undefined ? (d.hit_rate * 100).toFixed(1) : '0.0';
        el.innerHTML = `
            <div class="overview-grid">
                <div class="ov-card">
                    <div class="ov-icon">✅</div>
                    <div class="ov-info"><div class="ov-value">${d.hits}</div><div class="ov-label">Cache Hits</div></div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">❌</div>
                    <div class="ov-info"><div class="ov-value">${d.misses}</div><div class="ov-label">Cache Misses</div></div>
                </div>
                <div class="ov-card accent">
                    <div class="ov-icon">📈</div>
                    <div class="ov-info"><div class="ov-value">${hitPct}%</div><div class="ov-label">Hit Rate</div></div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">📄</div>
                    <div class="ov-info"><div class="ov-value">${d.total_entries}</div><div class="ov-label">Total Entries</div></div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">⏳</div>
                    <div class="ov-info"><div class="ov-value">${d.expired_entries}</div><div class="ov-label">Expired</div></div>
                </div>
                <div class="ov-card">
                    <div class="ov-icon">💽</div>
                    <div class="ov-info"><div class="ov-value">${d.size_mb} MB</div><div class="ov-label">Disk Usage</div></div>
                </div>
            </div>
            <div class="ov-section">
                <h3>Details</h3>
                <div class="ov-system-grid">
                    <div class="ov-sys-item"><span class="ov-sys-label">Cache Directory</span><span class="ov-sys-val mono">${d.cache_dir}</span></div>
                    <div class="ov-sys-item"><span class="ov-sys-label">LLM TTL</span><span class="ov-sys-val">24h</span></div>
                    <div class="ov-sys-item"><span class="ov-sys-label">Tool TTL</span><span class="ov-sys-val">7 days</span></div>
                    <div class="ov-sys-item"><span class="ov-sys-label">Search TTL</span><span class="ov-sys-val">1h</span></div>
                </div>
            </div>`;
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to load cache stats.</p>';
    }
}

async function clearCache() {
    const el = document.getElementById('cacheContent');
    try {
        const resp = await fetch('/api/cache/clear', { method: 'POST' });
        const d = await resp.json();
        const banner = document.createElement('div');
        banner.className = 'zc-update-banner';
        banner.style.marginBottom = '12px';
        banner.textContent = `Cleared ${d.deleted} expired cache entries.`;
        el.prepend(banner);
        setTimeout(() => banner.remove(), 4000);
        await loadCacheStats();
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to clear cache.</p>';
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Channels (Remote Integrations)
// ═══════════════════════════════════════════════════════════════════════

async function loadChannels() {
    const grid = document.getElementById('channelsGrid');
    try {
        const resp = await fetch('/api/integrations');
        const data = await resp.json();
        grid.innerHTML = '';
        for (const [id, info] of Object.entries(data)) {
            grid.appendChild(buildIntegrationCard(id, info));
        }
    } catch {
        grid.innerHTML = '<p class="placeholder">Failed to load channels.</p>';
    }
}

function buildIntegrationCard(id, info) {
    const card = document.createElement('div');
    const statusClass = info.enabled ? 'enabled' : (info.configured ? 'connected' : '');
    card.className = `int-card ${statusClass}`;
    card.id = `int-card-${id}`;

    const dotClass = info.enabled ? 'ok' : (info.configured ? 'warn' : '');
    const statusLabel = info.enabled ? 'Enabled' : (info.configured ? 'Configured' : 'Not configured');

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
    document.getElementById(`int-form-${id}`).classList.toggle('open');
}

async function toggleIntegration(id, enabled) {
    try {
        await fetch(`/api/integrations/${id}/configure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
        await loadChannels();
    } catch (e) { console.error('Toggle failed:', e); }
}

async function saveIntegration(id) {
    const statusEl = document.getElementById(`int-save-status-${id}`);
    statusEl.className = 'int-save-status';
    statusEl.textContent = 'Saving…';
    const fields = {};
    document.querySelectorAll(`#int-form-${id} input[id^="int-${id}-"]`).forEach(input => {
        const key = input.id.replace(`int-${id}-`, '');
        if (input.value && !input.value.match(/^•+/)) fields[key] = input.value;
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
        await loadChannels();
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
        const statusEl = document.getElementById(`int-save-status-${id}`);
        if (statusEl) {
            statusEl.className = `int-save-status ${data.ok ? 'ok' : 'error'}`;
            statusEl.textContent = data.message;
            document.getElementById(`int-form-${id}`).classList.add('open');
        }
        setTimeout(() => { btn.textContent = '▷ Test'; btn.title = ''; }, 3000);
    } catch (e) {
        btn.textContent = '✗';
        setTimeout(() => { btn.textContent = '▷ Test'; }, 3000);
    } finally { btn.disabled = false; }
}

// ═══════════════════════════════════════════════════════════════════════
// Models
// ═══════════════════════════════════════════════════════════════════════

async function loadInstances() {
    await Promise.all([loadHardwareAndRecommended(), loadPulledModels()]);
}

async function loadHardwareAndRecommended() {
    try {
        const resp = await fetch('/api/models/recommended');
        const data = await resp.json();
        const hw = data.hardware;
        const hwEl = document.getElementById('hardwareInfo');
        if (hw) {
            const accel = hw.acceleration || 'cpu';
            const accelLabel = { metal: 'Metal', mps: 'MPS', mlx: 'MLX', cuda: 'CUDA', rocm: 'ROCm', cpu: 'CPU' }[accel] || accel.toUpperCase();
            const inferLabel = accel === 'cpu' ? 'CPU' : accelLabel;
            const vramLabel = hw.gpu_vram_gb > 0 ? `${hw.gpu_vram_gb.toFixed(0)} GB` : '—';
            hwEl.innerHTML = `
                <div class="hw-grid">
                    <div class="hw-card"><div class="hw-value">${hw.ram_gb.toFixed(0)} GB</div><div class="hw-label">System RAM</div></div>
                    <div class="hw-card"><div class="hw-value">${vramLabel}</div><div class="hw-label">GPU VRAM</div></div>
                    <div class="hw-card"><div class="hw-value">${hw.cpu_cores}</div><div class="hw-label">CPU Cores</div></div>
                    <div class="hw-card"><div class="hw-value">${inferLabel}</div><div class="hw-label">Inference</div></div>
                    <div class="hw-accel"><span>Acceleration</span><span class="accel-badge ${accel}">${accelLabel}</span></div>
                </div>`;
        } else if (!data.llmfit_available) {
            hwEl.innerHTML = `<div class="llmfit-notice">⚠️ <strong>llmfit not installed</strong> — hardware detection unavailable.<br>Install: <code>brew install llmfit</code></div>`;
        } else {
            hwEl.innerHTML = '<p class="placeholder">Hardware info unavailable.</p>';
        }

        const recEl = document.getElementById('recommendedList');
        const badge = document.getElementById('llmfitBadge');
        if (!data.llmfit_available) {
            recEl.innerHTML = '<div class="llmfit-notice">Install llmfit to get hardware-matched recommendations.</div>';
            badge.textContent = 'llmfit required';
            return;
        }
        const recs = data.recommended || [];
        badge.textContent = recs.length + ' models';
        if (recs.length === 0) { recEl.innerHTML = '<p class="placeholder">No recommendations found.</p>'; return; }
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
        if (models.length === 0) { container.innerHTML = '<p class="placeholder">No models pulled yet.</p>'; return; }
        container.innerHTML = '';
        for (const name of models.sort()) {
            const row = document.createElement('div');
            row.className = 'model-row';
            row.innerHTML = `
                <span class="model-name" title="${name}">${name}</span>
                <button class="btn-delete" onclick="deleteModel('${name}', this)" title="Delete">✕</button>`;
            container.appendChild(row);
        }
    } catch {
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
            method: 'POST', headers: { 'Content-Type': 'application/json' },
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
            method: 'POST', headers: { 'Content-Type': 'application/json' },
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

// ═══════════════════════════════════════════════════════════════════════
// Sessions
// ═══════════════════════════════════════════════════════════════════════

async function loadSessions() {
    const el = document.getElementById('sessionsContent');
    try {
        const resp = await fetch('/api/sessions');
        const data = await resp.json();
        const sessions = data.sessions || [];
        if (sessions.length === 0) {
            el.innerHTML = '<p class="placeholder">No chat sessions recorded yet. Start a conversation in the Chat view.</p>';
            return;
        }
        let html = '<div class="sessions-list">';
        for (const s of sessions) {
            html += `<div class="session-row">
                <div class="session-info">
                    <div class="session-id">${escapeHtml(s.id)}</div>
                    <div class="session-meta">${s.messages} messages · Started ${formatDate(s.started)}</div>
                </div>
                <span class="status-badge ${s.active ? 'active' : 'inactive'}">${s.active ? 'active' : 'ended'}</span>
            </div>`;
        }
        html += '</div>';
        el.innerHTML = html;
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to load sessions.</p>';
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Cron Jobs
// ═══════════════════════════════════════════════════════════════════════

async function loadCron() {
    const el = document.getElementById('cronContent');
    try {
        const resp = await fetch('/api/cron');
        const data = await resp.json();
        const jobs = data.jobs || [];
        if (jobs.length === 0) {
            el.innerHTML = '<p class="placeholder">No jobs configured.</p>';
            return;
        }
        let html = '<div class="cron-list">';
        for (const j of jobs) {
            const statusCls = j.enabled ? 'active' : 'inactive';
            html += `<div class="cron-card">
                <div class="cron-head">
                    <span class="cron-icon">${j.icon || '⏰'}</span>
                    <div class="cron-info">
                        <div class="cron-title">${escapeHtml(j.name)}</div>
                        <div class="cron-desc">${escapeHtml(j.description)}</div>
                    </div>
                    <span class="status-badge ${statusCls}">${j.enabled ? 'enabled' : 'disabled'}</span>
                </div>
                <div class="cron-detail">
                    <span class="cron-schedule">Schedule: <code>${escapeHtml(j.schedule)}</code></span>
                    <span class="cron-next">Next run: <strong>${j.next_run || 'N/A'}</strong></span>
                    <span class="cron-last">Last run: ${j.last_run || 'Never'}</span>
                </div>
            </div>`;
        }
        html += '</div>';
        el.innerHTML = html;
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to load jobs.</p>';
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Skills
// ═══════════════════════════════════════════════════════════════════════

const _CAT_ORDER_SKILLS = ['vision', 'research', 'content', 'ml'];
const _CAT_LABELS_SKILLS = { vision: '👁️ Vision', research: '🔬 Research', content: '✍️ Content', ml: '⚙️ ML / Training' };

async function loadSkills() {
    const grid = document.getElementById('skillsGrid');
    try {
        const resp = await fetch('/api/skills');
        const data = await resp.json();
        grid.innerHTML = '';
        const groups = {};
        for (const [id, info] of Object.entries(data)) {
            const cat = info.category || 'research';
            (groups[cat] = groups[cat] || []).push([id, info]);
        }
        for (const cat of _CAT_ORDER_SKILLS) {
            if (!groups[cat]) continue;
            const label = document.createElement('div');
            label.className = 'cap-group-label';
            label.textContent = _CAT_LABELS_SKILLS[cat] || cat;
            grid.appendChild(label);
            for (const [id, info] of groups[cat]) {
                grid.appendChild(buildSkillCard(id, info));
            }
        }
    } catch {
        grid.innerHTML = '<p class="placeholder">Failed to load skills.</p>';
    }
}

function buildSkillCard(_id, info) {
    const card = document.createElement('div');
    card.className = `skill-card ${info.status}`;
    const toolsHtml = (info.tools || []).map(t => `<span class="skill-tool-chip">${t}</span>`).join('');
    const missingHtml = (info.missing || []).length
        ? `<div class="skill-missing">⚠ Requires: ${info.missing.join(', ')}</div>` : '';
    const installHtml = info.install
        ? `<code class="skill-install" title="Click to copy">${escapeHtml(info.install)}</code>` : '';
    card.innerHTML = `
        <div class="skill-head">
            <span class="skill-icon">${info.icon}</span>
            <span class="skill-title">${info.label}</span>
            <span class="status-badge ${info.status}">${info.status.replace('-', ' ')}</span>
        </div>
        <div class="skill-cat">${info.category}</div>
        <div class="skill-desc">${info.description}</div>
        ${missingHtml}
        ${installHtml}
        ${toolsHtml ? `<div class="skill-tools">${toolsHtml}</div>` : ''}`;
    if (info.install) {
        card.querySelector('.skill-install')?.addEventListener('click', () => {
            navigator.clipboard?.writeText(info.install);
        });
    }
    return card;
}

// ═══════════════════════════════════════════════════════════════════════
// Nodes (Powers)
// ═══════════════════════════════════════════════════════════════════════

const _CAT_ORDER_POWERS = ['built-in', 'integration', 'cloud'];
const _CAT_LABELS_POWERS = { 'built-in': '🔌 Built-in', integration: '🔗 Integrations', cloud: '☁️ Cloud Compute' };

async function loadPowers() {
    const grid = document.getElementById('powersGrid');
    try {
        const resp = await fetch('/api/powers');
        const data = await resp.json();
        grid.innerHTML = '';
        const groups = {};
        for (const [id, info] of Object.entries(data)) {
            const cat = info.category || 'integration';
            (groups[cat] = groups[cat] || []).push([id, info]);
        }
        for (const cat of _CAT_ORDER_POWERS) {
            if (!groups[cat]) continue;
            const label = document.createElement('div');
            label.className = 'cap-group-label';
            label.textContent = _CAT_LABELS_POWERS[cat] || cat;
            grid.appendChild(label);
            for (const [id, info] of groups[cat]) {
                grid.appendChild(buildPowerCard(id, info));
            }
        }
    } catch {
        grid.innerHTML = '<p class="placeholder">Failed to load powers.</p>';
    }
}

function buildPowerCard(id, info) {
    const card = document.createElement('div');
    card.className = `pwr-card ${info.status}`;
    card.id = `pwr-card-${id}`;

    const fieldsHtml = info.configurable && info.fields ? info.fields.map(f => `
        <div class="pwr-field">
            <label>${f.label}</label>
            <input type="${f.secret ? 'password' : 'text'}"
                   id="pwr-${id}-${f.key}"
                   placeholder="${escapeHtml(f.placeholder || '')}"
                   value="${escapeHtml((info.field_values || {})[f.key] || '')}" />
        </div>`).join('') : '';

    const cfgBtn = info.configurable
        ? `<button class="int-btn" onclick="togglePowerForm('${id}')">⚙ Configure</button>` : '';

    card.innerHTML = `
        <div class="pwr-head">
            <span class="pwr-icon">${info.icon}</span>
            <div class="pwr-info">
                <div class="pwr-title">
                    ${info.label}
                    <span class="status-badge ${info.status}">${info.status.replace('-', ' ')}</span>
                </div>
                <div class="pwr-desc">${info.description}</div>
            </div>
        </div>
        <div class="pwr-detail">${info.detail || ''}</div>
        ${cfgBtn ? `<div class="pwr-actions">${cfgBtn}</div>` : ''}
        <div class="pwr-form" id="pwr-form-${id}">
            ${fieldsHtml}
            <div class="pwr-save-row">
                <button class="int-btn primary" onclick="savePower('${id}')">Save</button>
                <span class="pwr-save-status" id="pwr-save-status-${id}"></span>
            </div>
        </div>`;
    return card;
}

function togglePowerForm(id) {
    document.getElementById(`pwr-form-${id}`).classList.toggle('open');
}

async function savePower(id) {
    const statusEl = document.getElementById(`pwr-save-status-${id}`);
    statusEl.className = 'pwr-save-status';
    statusEl.textContent = 'Saving…';
    const fields = {};
    document.querySelectorAll(`#pwr-form-${id} input[id^="pwr-${id}-"]`).forEach(input => {
        const key = input.id.replace(`pwr-${id}-`, '');
        if (input.value && !input.value.match(/^•+/)) fields[key] = input.value;
    });
    try {
        const resp = await fetch(`/api/powers/${id}/configure`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fields }),
        });
        const data = await resp.json();
        if (!data.ok) throw new Error(data.error || 'Unknown error');
        statusEl.className = 'pwr-save-status ok';
        statusEl.textContent = `Saved ${data.updated.length} key${data.updated.length !== 1 ? 's' : ''}`;
        await Promise.all([loadPowers(), loadSkills()]);
    } catch (e) {
        statusEl.className = 'pwr-save-status error';
        statusEl.textContent = e.message;
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Vault Tree
// ═══════════════════════════════════════════════════════════════════════

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
    } catch (e) { console.error('Failed to load vault tree:', e); }
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
    } catch (e) { console.error('Failed to load note:', e); }
}

// ═══════════════════════════════════════════════════════════════════════
// Knowledge Graph
// ═══════════════════════════════════════════════════════════════════════

async function loadGraph() {
    try {
        const resp = await fetch('/api/graph');
        const data = await resp.json();
        const stats = data.stats;
        document.getElementById('graphStats').textContent = `${stats.nodes} nodes · ${stats.edges} edges`;
        drawGraph(data.graph);
    } catch (e) { console.error('Failed to load graph:', e); }
}

function drawGraph(graphData) {
    const canvas = document.getElementById('graphCanvas');
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    ctx.scale(devicePixelRatio, devicePixelRatio);

    const W = rect.width, H = rect.height;
    const nodes = graphData.nodes || [], edges = graphData.edges || [];

    if (nodes.length === 0) {
        ctx.fillStyle = '#8b949e';
        ctx.font = '14px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No nodes yet. Process papers to build the graph.', W / 2, H / 2);
        return;
    }

    const typeColors = { paper: '#58a6ff', method: '#f0883e', dataset: '#3fb950', task: '#f85149', author: '#d2a8ff', unknown: '#8b949e' };
    const positions = {};
    nodes.forEach((node, i) => {
        const angle = (2 * Math.PI * i) / nodes.length;
        const r = Math.min(W, H) * 0.35;
        positions[node.id] = {
            x: W / 2 + r * Math.cos(angle) + (Math.random() - 0.5) * 40,
            y: H / 2 + r * Math.sin(angle) + (Math.random() - 0.5) * 40,
        };
    });

    ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1;
    for (const edge of edges) {
        const from = positions[edge.source], to = positions[edge.target];
        if (from && to) {
            ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke();
            const dx = to.x - from.x, dy = to.y - from.y, len = Math.sqrt(dx * dx + dy * dy);
            if (len > 0) {
                const nx = dx / len, ny = dy / len, ax = to.x - nx * 14, ay = to.y - ny * 14;
                ctx.beginPath();
                ctx.moveTo(to.x - nx * 8, to.y - ny * 8);
                ctx.lineTo(ax - ny * 4, ay + nx * 4);
                ctx.lineTo(ax + ny * 4, ay - nx * 4);
                ctx.fillStyle = '#30363d'; ctx.fill();
            }
        }
    }

    for (const node of nodes) {
        const pos = positions[node.id];
        if (!pos) continue;
        const color = typeColors[node.type] || typeColors.unknown;
        const radius = node.type === 'paper' ? 8 : 6;
        ctx.beginPath(); ctx.arc(pos.x, pos.y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = color; ctx.fill();
        ctx.strokeStyle = '#0d1117'; ctx.lineWidth = 2; ctx.stroke();
        const label = (node.title || node.id || '').substring(0, 30);
        ctx.fillStyle = '#e6edf3'; ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'center'; ctx.fillText(label, pos.x, pos.y + radius + 14);
    }

    let ly = 20; ctx.textAlign = 'left';
    for (const [type, color] of Object.entries(typeColors)) {
        ctx.beginPath(); ctx.arc(20, ly, 5, 0, 2 * Math.PI);
        ctx.fillStyle = color; ctx.fill();
        ctx.fillStyle = '#8b949e'; ctx.font = '11px -apple-system, sans-serif';
        ctx.fillText(type, 32, ly + 4);
        ly += 18;
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Specs
// ═══════════════════════════════════════════════════════════════════════

async function loadSpecs() {
    try {
        const resp = await fetch('/api/specs');
        const data = await resp.json();
        const container = document.getElementById('specsList');
        container.innerHTML = '';
        if (data.specs.length === 0) { container.innerHTML = '<p class="placeholder">No specs generated yet.</p>'; return; }
        for (const spec of data.specs) {
            const item = document.createElement('div');
            item.className = 'file-list-item';
            item.innerHTML = `<div class="name">${spec.name}</div><div class="meta">${formatBytes(spec.size)} · ${formatDate(spec.modified)}</div>`;
            item.addEventListener('click', () => {
                document.querySelectorAll('#specsList .file-list-item').forEach(el => el.classList.remove('active'));
                item.classList.add('active');
                loadSpec(spec.name);
            });
            container.appendChild(item);
        }
    } catch (e) { console.error('Failed to load specs:', e); }
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
    } catch (e) { console.error('Failed to load spec:', e); }
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

// ═══════════════════════════════════════════════════════════════════════
// Digests
// ═══════════════════════════════════════════════════════════════════════

async function loadDigests() {
    try {
        const resp = await fetch('/api/digests');
        const data = await resp.json();
        const container = document.getElementById('digestsList');
        container.innerHTML = '';
        if (data.digests.length === 0) { container.innerHTML = '<p class="placeholder">No digests yet. Run: cv-agent digest</p>'; return; }
        for (const digest of data.digests) {
            const item = document.createElement('div');
            item.className = 'file-list-item';
            item.innerHTML = `<div class="name">${digest.name}</div><div class="meta">${formatBytes(digest.size)} · ${formatDate(digest.modified)}</div>`;
            item.addEventListener('click', () => {
                document.querySelectorAll('#digestsList .file-list-item').forEach(el => el.classList.remove('active'));
                item.classList.add('active');
                loadDigest(digest.name);
            });
            container.appendChild(item);
        }
    } catch (e) { console.error('Failed to load digests:', e); }
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
    } catch (e) { console.error('Failed to load digest:', e); }
}

// ═══════════════════════════════════════════════════════════════════════
// Config
// ═══════════════════════════════════════════════════════════════════════

async function loadConfig() {
    await Promise.all([loadZeroClawStatus(), loadAgentConfig()]);
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
            updateHtml = `<div class="zc-update-banner">⬆ Update available: <strong>${d.pypi_version}</strong> (current: ${d.current_version}) — run <code>pip install -U zeroclaw-tools</code></div>`;
        } else if (!d.package_on_pypi && d.mode === 'shim') {
            updateHtml = `<div class="zc-not-on-pypi">zeroclaw-tools not yet on PyPI — using local compatibility shim.<div class="zc-install-hint">When published: <code>pip install zeroclaw-tools</code> then delete <code>src/zeroclaw_tools/</code></div></div>`;
        }
        const toolsHtml = (d.builtin_tools || []).map(t => `<span class="zc-tool-chip">${t}</span>`).join('');
        el.innerHTML = `
            ${updateHtml}
            <div class="zc-grid">
                <div class="zc-card highlight"><div class="zc-label">Mode</div>${modeLabel}</div>
                <div class="zc-card"><div class="zc-label">Version</div><div class="zc-value">${d.current_version}</div></div>
                <div class="zc-card"><div class="zc-label">Agent Framework</div><div class="zc-value" style="font-size:11px">${d.agent_framework}</div></div>
                <div class="zc-card"><div class="zc-label">Tool Call Mode</div><div class="zc-value" style="font-size:10px;line-height:1.4">${d.tool_call_mode}</div></div>
            </div>
            <div class="zc-label" style="margin-bottom:6px">Built-in Tools</div>
            <div class="zc-tools">${toolsHtml}</div>`;
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to load ZeroClaw status.</p>';
    }
}

async function loadAgentConfig() {
    const el = document.getElementById('agentConfigView');
    try {
        const resp = await fetch('/api/status');
        const d = await resp.json();
        el.innerHTML = `
            <div class="config-kv">
                <div class="config-row"><span class="config-key">Agent Name</span><span class="config-val">${d.agent}</span></div>
                <div class="config-row"><span class="config-key">LLM Model</span><span class="config-val mono">${d.llm_model}</span></div>
                <div class="config-row"><span class="config-key">Vision Model</span><span class="config-val mono">${d.vision_model}</span></div>
                <div class="config-row"><span class="config-key">Vault Path</span><span class="config-val mono">${d.vault_path}</span></div>
                <div class="config-row"><span class="config-key">Status</span><span class="config-val"><span class="status-badge active">${d.status}</span></span></div>
            </div>`;
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to load agent config.</p>';
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Debug
// ═══════════════════════════════════════════════════════════════════════

async function loadDebug() {
    const el = document.getElementById('debugContent');
    try {
        const resp = await fetch('/api/debug');
        const d = await resp.json();
        let html = '<div class="debug-panels">';

        // Dependencies
        html += '<div class="inst-card"><div class="inst-card-header"><h3>Dependencies</h3></div><div class="inst-card-body">';
        for (const dep of d.dependencies) {
            const cls = dep.installed ? 'active' : 'inactive';
            html += `<div class="debug-dep-row">
                <span class="status-badge ${cls}">${dep.installed ? 'installed' : 'missing'}</span>
                <span class="debug-dep-name">${dep.name}</span>
                <span class="debug-dep-ver">${dep.version || ''}</span>
            </div>`;
        }
        html += '</div></div>';

        // Environment
        html += '<div class="inst-card"><div class="inst-card-header"><h3>Environment</h3></div><div class="inst-card-body"><div class="config-kv">';
        for (const [k, v] of Object.entries(d.environment)) {
            html += `<div class="config-row"><span class="config-key">${k}</span><span class="config-val mono">${escapeHtml(String(v))}</span></div>`;
        }
        html += '</div></div></div>';

        // Tool registry
        html += '<div class="inst-card"><div class="inst-card-header"><h3>Registered Tools</h3></div><div class="inst-card-body"><div class="zc-tools">';
        for (const t of d.tools) {
            html += `<span class="zc-tool-chip">${t}</span>`;
        }
        html += '</div></div></div>';

        html += '</div>';
        el.innerHTML = html;
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to load debug info.</p>';
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Logs
// ═══════════════════════════════════════════════════════════════════════

function loadLogs() {
    const output = document.getElementById('logOutput');
    output.textContent = 'Connecting to log stream…\n';
    if (logWs) { logWs.close(); logWs = null; }
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    logWs = new WebSocket(`${protocol}//${location.host}/ws/logs`);
    logWs.onopen = () => { output.textContent += '[connected]\n'; };
    logWs.onmessage = (event) => {
        output.textContent += event.data + '\n';
        if (document.getElementById('logAutoScroll').checked) {
            const container = document.getElementById('logContainer');
            container.scrollTop = container.scrollHeight;
        }
    };
    logWs.onclose = () => { output.textContent += '[disconnected]\n'; };
    logWs.onerror = () => { output.textContent += '[error]\n'; };
}

function clearLogs() {
    document.getElementById('logOutput').textContent = '';
}

// ═══════════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════════

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatDate(isoStr) {
    try {
        return new Date(isoStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch { return isoStr; }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
