/* ── CV Assistant 👁️ — Frontend App ── */

// ── State ──
let ws = null;
let currentView = 'chat';
let specRawMode = false;
let currentSpecRaw = '';
let logWs = null;
let agentWs = null;
let currentAgentId = null;
const _PINNED_KEY = 'cv_pinned_agents';
const _PINNED_SKILLS_KEY = 'cv_pinned_skills';
let _t2dJobId = null;
let _t2dPollTimer = null;
let _t2dReady = false;
let _t2dProviderDefaults = { profiles: {}, vlm_providers: {}, image_providers: {} };
let _t2dVlmChoices = [];
let _skillsById = {};
let _draggedPinnedSkillId = null;

function _localDefaultT2DVlmModel(vlmProvider) {
    if (vlmProvider === 'gemini') return 'gemini-2.0-flash';
    if (vlmProvider === 'openai') return 'gpt-4o';
    if (vlmProvider === 'openrouter') return 'openai/gpt-4o-mini';
    return 'qwen2.5-vl:7b';
}

function _localDefaultT2DImageModel(imageProvider) {
    if (imageProvider === 'mermaid_local') return 'beautiful-mermaid';
    if (imageProvider === 'matplotlib') return 'matplotlib';
    if (imageProvider === 'google_imagen') return 'gemini-3-pro-image-preview';
    if (imageProvider === 'openai_imagen') return 'gpt-image-1';
    if (imageProvider === 'openrouter_imagen') return 'openai/gpt-image-1';
    if (imageProvider === 'stability') return 'stabilityai/stable-diffusion-3.5-large';
    return 'matplotlib';
}

function _localT2DProfileMap(profile) {
    if (profile === 'gemini') return { vlm_provider: 'gemini', image_provider: 'google_imagen' };
    if (profile === 'openai') return { vlm_provider: 'openai', image_provider: 'openai_imagen' };
    if (profile === 'openrouter') return { vlm_provider: 'openrouter', image_provider: 'openrouter_imagen' };
    return { vlm_provider: 'ollama', image_provider: 'mermaid_local' };
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    initNav();
    initChat();
    initAgentChat();
    renderPinnedNavItems();
    renderPinnedSkillNavItems();
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
        datasets: loadDatasets,
        text2diagram: loadTextToDiagramView,
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

// ── Streaming state ──
let _streamingMsg = null;
let _streamingBody = null;
let _streamingContent = '';
let _toolActivity = null;
let _streamTimeout = null;
let _hadToolCalls = false;
let _writingResponse = false;

function _toolStatusText(name) {
    if (/search|arxiv/i.test(name)) return 'Searching…';
    if (/fetch|download|pdf/i.test(name)) return 'Fetching…';
    if (/analyz|vision|image|mlx/i.test(name)) return 'Analyzing…';
    if (/graph|kg|map/i.test(name)) return 'Mapping…';
    if (/draft|blog|write|generat|scaffold/i.test(name)) return 'Drafting…';
    if (/hardware|probe/i.test(name)) return 'Probing hardware…';
    if (/extract|equat/i.test(name)) return 'Extracting…';
    if (/train|cost|scaffold/i.test(name)) return 'Computing…';
    return 'Thinking…';
}

function _resetStreamTimeout() {
    if (_streamTimeout) clearTimeout(_streamTimeout);
    // If no events arrive for 90s, auto-finalize to avoid stuck UI
    _streamTimeout = setTimeout(() => {
        if (_streamingBody) {
            _finalizeStream(_streamingContent, '');
        }
    }, 90000);
}

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'typing') {
            // suppress
        } else if (data.type === 'message') {
            addMessage('assistant', data.content, data.html);
        } else if (data.type === 'stream_start') {
            _startStreamingMessage();
        } else if (data.type === 'stream_token') {
            _resetStreamTimeout();
            if (!_writingResponse) {
                _writingResponse = true;
                document.getElementById('typingText').textContent = 'Writing response…';
            }
            _appendStreamToken(data.content);
        } else if (data.type === 'tool_start') {
            _resetStreamTimeout();
            document.getElementById('typingText').textContent = _toolStatusText(data.name);
            _showToolActivity(data.name, data.input);
        } else if (data.type === 'tool_end') {
            _resetStreamTimeout();
            document.getElementById('typingText').textContent = 'Thinking…';
            _hideToolActivity(data.name, data.output);
        } else if (data.type === 'stream_end') {
            if (_streamTimeout) clearTimeout(_streamTimeout);
            document.getElementById('typingIndicator').hidden = true;
            _finalizeStream(data.content, data.html);
        } else if (data.type === 'error') {
            if (_streamTimeout) clearTimeout(_streamTimeout);
            document.getElementById('typingIndicator').hidden = true;
            _clearStream();
            addMessage('system', `Error: ${data.content}`);
        }
    };
    ws.onclose = () => setTimeout(connectWebSocket, 3000);
    ws.onerror = () => console.error('WebSocket error');
}

function _startStreamingMessage() {
    const container = document.getElementById('chatMessages');
    _streamingContent = '';
    _hadToolCalls = false;
    _writingResponse = false;
    const ind = document.getElementById('typingIndicator');
    document.getElementById('typingText').textContent = 'Thinking…';
    ind.hidden = false;

    _streamingMsg = document.createElement('div');
    _streamingMsg.className = 'message assistant';

    const label = document.createElement('div');
    label.className = 'message-label';
    label.textContent = 'CV Assistant';

    // Tool activity area (hidden until a tool is called)
    _toolActivity = document.createElement('div');
    _toolActivity.className = 'tool-activity';
    _toolActivity.hidden = true;

    _streamingBody = document.createElement('div');
    _streamingBody.className = 'message-content streaming';

    _streamingMsg.appendChild(label);
    _streamingMsg.appendChild(_toolActivity);
    _streamingMsg.appendChild(_streamingBody);
    container.appendChild(_streamingMsg);
    scrollChat();
}

function _appendStreamToken(token) {
    if (!_streamingBody) return;
    _streamingContent += token;
    _streamingBody.textContent = _streamingContent;
    scrollChat();
}

function _showToolActivity(name, input) {
    if (!_toolActivity) return;
    const entry = document.createElement('div');
    entry.className = 'tool-entry running';
    entry.dataset.toolName = name;
    const argSnippet = input ? `(${input.slice(0, 100)})` : '';
    entry.innerHTML = `<span class="tool-dot">⏺</span> <span class="tool-name">${_escHtml(name)}</span>` +
        `<span class="tool-input">${_escHtml(argSnippet)}</span>`;
    _toolActivity.appendChild(entry);
    _toolActivity.hidden = false;
    // Clear streamed content — model will regenerate after tool
    _streamingContent = '';
    _streamingBody.textContent = '';
    scrollChat();
}

function _hideToolActivity(name, output) {
    if (!_toolActivity) return;
    _hadToolCalls = true;
    const entries = _toolActivity.querySelectorAll(`.tool-entry[data-tool-name="${CSS.escape(name)}"].running`);
    const entry = entries[entries.length - 1];
    if (entry) {
        entry.classList.remove('running');
        entry.classList.add('done');
        const check = document.createElement('span');
        check.className = 'tool-check';
        check.textContent = '✓';
        entry.querySelector('.tool-dot')?.replaceWith(check);
        if (output) {
            const preview = document.createElement('span');
            preview.className = 'tool-output';
            preview.textContent = output.slice(0, 150) + (output.length > 150 ? '…' : '');
            entry.appendChild(preview);
        }
    }
    scrollChat();
}

function _finalizeStream(content, html) {
    if (_streamingBody) {
        _streamingBody.classList.remove('streaming');
        const hasContent = Boolean(content && content.trim());
        const hasHtml = Boolean(html && html.trim());

        if (hasHtml) {
            _streamingBody.innerHTML = html;
        } else if (hasContent) {
            _streamingBody.textContent = content;
        } else {
            _streamingBody.textContent = 'Completed tool calls, but no final response text was generated.';
        }
        _streamingBody.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
        renderMathInElement(_streamingBody);
    }
    _clearStream();
    scrollChat();
}

function _clearStream() {
    if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
    _streamingMsg = null;
    _streamingBody = null;
    _streamingContent = '';
    _toolActivity = null;
    _hadToolCalls = false;
    _writingResponse = false;
    document.getElementById('typingIndicator').hidden = true;
}

function _escHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
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

// ── Pin helpers ──
function getPinnedAgents() {
    try { return JSON.parse(localStorage.getItem(_PINNED_KEY) || '[]'); }
    catch { return []; }
}
function setPinnedAgents(agents) {
    localStorage.setItem(_PINNED_KEY, JSON.stringify(agents));
}
function isPinned(id) {
    return getPinnedAgents().some(a => a.id === id);
}
function togglePinAgent(id, name, icon, model) {
    const pinned = getPinnedAgents();
    const idx = pinned.findIndex(a => a.id === id);
    if (idx >= 0) pinned.splice(idx, 1);
    else pinned.push({ id, name, icon, model });
    setPinnedAgents(pinned);
    renderPinnedNavItems();
    loadAgents();
}
function renderPinnedNavItems() {
    const list = document.getElementById('grp-agents');
    if (!list) return;
    list.querySelectorAll('.pinned-agent-item').forEach(el => el.remove());
    let insertAfter = list.querySelector('[data-view="agents"]');
    for (const agent of getPinnedAgents()) {
        const li = document.createElement('li');
        li.className = 'nav-item pinned-agent-item';
        li.id = `pinned-nav-${agent.id}`;
        li.dataset.agentId = agent.id;
        li.innerHTML = `<span class="nav-icon">${agent.icon}</span>${agent.name}`;
        li.addEventListener('click', () => openAgentChat(agent.id, agent.name, agent.icon, agent.model));
        if (insertAfter && insertAfter.nextSibling) list.insertBefore(li, insertAfter.nextSibling);
        else list.appendChild(li);
        insertAfter = li;
    }
}

// ── Pinned skills helpers ──
function getPinnedSkills() {
    try { return JSON.parse(localStorage.getItem(_PINNED_SKILLS_KEY) || '[]'); }
    catch { return []; }
}

function setPinnedSkills(skills) {
    localStorage.setItem(_PINNED_SKILLS_KEY, JSON.stringify(skills));
}

function isSkillPinned(id) {
    return getPinnedSkills().some(s => s.id === id);
}

function openPinnedSkill(skillId) {
    if (skillId === 'text_to_diagram') {
        openTextToDiagramSkill();
    } else {
        switchView('skills');
    }
    document.querySelectorAll('.pinned-skill-item').forEach(el => el.classList.remove('active'));
    const pinnedItem = document.getElementById(`pinned-skill-nav-${skillId}`);
    if (pinnedItem) pinnedItem.classList.add('active');
}

function togglePinSkill(id) {
    const info = _skillsById[id] || {};
    const label = info.label || id;
    const icon = info.icon || '⚡';
    const pinned = getPinnedSkills();
    const idx = pinned.findIndex(s => s.id === id);
    if (idx >= 0) pinned.splice(idx, 1);
    else pinned.push({ id, label, icon });
    setPinnedSkills(pinned);
    renderPinnedSkillNavItems();
    loadSkills();
}

function renderPinnedSkillNavItems() {
    const list = document.getElementById('grp-agent');
    if (!list) return;

    list.querySelectorAll('.pinned-skill-item').forEach(el => el.remove());

    const anchor = list.querySelector('[data-view="skills"]');
    let insertAfter = anchor || null;

    for (const skill of getPinnedSkills()) {
        const li = document.createElement('li');
        li.className = 'nav-item pinned-skill-item';
        li.id = `pinned-skill-nav-${skill.id}`;
        li.dataset.skillId = skill.id;
        li.draggable = true;
        li.innerHTML = `<span class="nav-icon">${skill.icon || '⚡'}</span>${skill.label}<span class="pin-drag">↕</span>`;
        li.addEventListener('click', () => openPinnedSkill(skill.id));
        li.addEventListener('dragstart', (e) => {
            _draggedPinnedSkillId = skill.id;
            li.classList.add('dragging');
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', skill.id);
            }
        });
        li.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (_draggedPinnedSkillId && _draggedPinnedSkillId !== skill.id) {
                li.classList.add('drag-over');
            }
        });
        li.addEventListener('dragleave', () => li.classList.remove('drag-over'));
        li.addEventListener('drop', (e) => {
            e.preventDefault();
            li.classList.remove('drag-over');
            const fromId = _draggedPinnedSkillId || (e.dataTransfer ? e.dataTransfer.getData('text/plain') : '');
            if (!fromId || fromId === skill.id) return;
            reorderPinnedSkills(fromId, skill.id);
        });
        li.addEventListener('dragend', () => {
            _draggedPinnedSkillId = null;
            list.querySelectorAll('.pinned-skill-item').forEach(el => {
                el.classList.remove('drag-over');
                el.classList.remove('dragging');
            });
        });

        if (insertAfter && insertAfter.nextSibling) list.insertBefore(li, insertAfter.nextSibling);
        else list.appendChild(li);
        insertAfter = li;
    }
}

function reorderPinnedSkills(fromId, toId) {
    const pinned = getPinnedSkills();
    const fromIdx = pinned.findIndex(s => s.id === fromId);
    const toIdx = pinned.findIndex(s => s.id === toId);
    if (fromIdx < 0 || toIdx < 0 || fromIdx === toIdx) return;

    const [moved] = pinned.splice(fromIdx, 1);
    const insertAt = fromIdx < toIdx ? toIdx - 1 : toIdx;
    pinned.splice(insertAt, 0, moved);
    setPinnedSkills(pinned);
    renderPinnedSkillNavItems();
}

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
            <button class="pin-btn ${isPinned(agent.id) ? 'pinned' : ''}" onclick="togglePinAgent('${agent.id}', '${agent.name}', '${agent.icon || '🤖'}', '${agent.model}')" title="${isPinned(agent.id) ? 'Unpin from sidebar' : 'Pin to sidebar'}">
                📌 ${isPinned(agent.id) ? 'Pinned' : 'Pin'}
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
    // Show the generic nav item only when agent is not pinned
    const navAgentChat = document.getElementById('nav-agent-chat');
    navAgentChat.style.display = isPinned(id) ? 'none' : '';
    // Update active state on pinned nav items
    document.querySelectorAll('.pinned-agent-item').forEach(el => el.classList.remove('active'));
    const pinnedItem = document.getElementById(`pinned-nav-${id}`);
    if (pinnedItem) pinnedItem.classList.add('active');
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
    agentWs.onclose = () => { };
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
    await Promise.all([
        loadLocalServers(),
        loadModelCatalog(),
        loadHardwareAndRecommended(),
        loadPulledModels(),
    ]);
}

// ── Local Servers ──────────────────────────────────────────────────────────

async function loadLocalServers() {
    try {
        const [servers] = await Promise.all([
            fetch('/api/local-servers').then(r => r.json()),
        ]);
        _renderServerManagement(servers);
        _renderServerStatus(servers);
    } catch (e) {
        document.getElementById('serverManagementList').innerHTML = '<p class="placeholder">Failed to load servers.</p>';
    }
}

function _renderServerManagement(servers) {
    const el = document.getElementById('serverManagementList');
    el.innerHTML = '';
    for (const s of servers) {
        const connected = s.healthy;
        const statusCls = connected ? 'connected' : 'disconnected';
        const statusLabel = connected ? '● Connected' : '○ Disconnected';
        const deviceOpts = ['GPU', 'CPU', 'Auto', 'MPS', 'CUDA'].map(d =>
            `<option value="${d.toLowerCase()}" ${s.device === d.toLowerCase() ? 'selected' : ''}>${d}</option>`
        ).join('');
        const activeLabel = s.healthy ? `Active: ${s.device.toUpperCase()}` : '';
        const activeBadge = s.healthy ? `<span class="accel-badge ${s.device === 'mps' || s.device === 'gpu' ? 'metal' : 'cpu'}">${activeLabel}</span>` : '';
        const ctrlBtns = s.managed
            ? (s.healthy
                ? `<button class="srv-btn srv-restart" onclick="serverAction('${s.id}','restart')">↻ Restart</button>
                   <button class="srv-btn srv-stop"    onclick="serverAction('${s.id}','stop')">■ Stop</button>`
                : `<button class="srv-btn srv-start"   onclick="serverAction('${s.id}','start')">▶ Start</button>`)
            : `<button class="srv-btn srv-restart" onclick="serverAction('${s.id}','restart')" disabled title="Externally managed">↻</button>`;
        const card = document.createElement('div');
        card.className = 'srv-card';
        card.innerHTML = `
            <div class="srv-header">
                <div class="srv-info">
                    <strong>${escapeHtml(s.name)}</strong>
                    <span class="srv-url">${escapeHtml(s.url)}</span>
                </div>
                <span class="srv-status ${statusCls}">${statusLabel}</span>
            </div>
            <div class="srv-controls">
                ${ctrlBtns}
                <span class="srv-device-label">Device:</span>
                <select class="srv-device-select" onchange="setServerDevice('${s.id}', this.value)">${deviceOpts}</select>
                ${activeBadge}
            </div>`;
        el.appendChild(card);
    }
}

function _renderServerStatus(servers) {
    const el = document.getElementById('serverStatusList');
    el.innerHTML = '';
    for (const s of servers) {
        const row = document.createElement('div');
        row.className = 'srv-status-row';
        row.innerHTML = `
            <span class="srv-status-name">${escapeHtml(s.name)}</span>
            <span class="srv-status ${s.healthy ? 'connected' : 'disconnected'}">${s.healthy ? '● Connected' : '○ Disconnected'}</span>`;
        el.appendChild(row);
    }
}

async function serverAction(id, action) {
    try {
        await fetch(`/api/local-servers/${id}/${action}`, { method: 'POST' });
        await loadLocalServers();
    } catch (e) { console.error(e); }
}

async function setServerDevice(id, device) {
    try {
        await fetch(`/api/local-servers/${id}`, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ device }),
        });
        await loadLocalServers();
    } catch (e) { console.error(e); }
}

// ── Local Model Catalog ────────────────────────────────────────────────────

async function loadModelCatalog() {
    try {
        const models = await fetch('/api/local-models/catalog').then(r => r.json());
        _renderModelCatalog(models);
    } catch (e) {
        document.getElementById('localModelCatalog').innerHTML = '<p class="placeholder">Failed to load catalog.</p>';
    }
}

const _CATALOG_CATEGORY_ORDER = ['Image Generation', 'Video Generation', 'Segmentation', 'OCR'];

function _renderModelCatalog(models) {
    const el = document.getElementById('localModelCatalog');
    el.innerHTML = '';
    // Group by category
    const groups = {};
    for (const m of models) (groups[m.category] = groups[m.category] || []).push(m);
    for (const cat of _CATALOG_CATEGORY_ORDER) {
        if (!groups[cat]) continue;
        const section = document.createElement('div');
        section.className = 'mcat-section';
        section.innerHTML = `<div class="mcat-cat-header">${cat}</div>`;
        for (const m of groups[cat]) {
            const sizeLabel = m.downloaded && m.local_size_gb ? `Size: ${m.local_size_gb} GB` : `~${m.size_gb} GB`;
            const statusBadge = m.downloaded ? '<span class="mcat-badge downloaded">Downloaded</span>' : '';
            const pipNote = m.pip_pkg ? `<span class="mcat-pip-note">via pip: ${m.pip_pkg}</span>` : '';
            const rightCol = m.downloaded
                ? `<div class="mcat-actions">
                       <span class="mcat-ready">Ready</span>
                       <button class="btn-mcat-delete" onclick="deleteLocalModel('${m.id}', this)" title="Delete">🗑</button>
                   </div>`
                : m.pip_pkg
                    ? `<div class="mcat-actions"><span class="mcat-pip-install">pip install ${m.pip_pkg}</span></div>`
                    : `<div class="mcat-actions"><button class="btn-mcat-download" onclick="downloadLocalModel('${m.id}', this)">⬇ Download</button></div>`;
            const card = document.createElement('div');
            card.className = 'mcat-card';
            card.dataset.modelId = m.id;
            card.innerHTML = `
                <div class="mcat-info">
                    <div class="mcat-name">${escapeHtml(m.name)} ${statusBadge} ${pipNote}</div>
                    <div class="mcat-desc">${escapeHtml(m.desc)}</div>
                    <div class="mcat-size">${sizeLabel}</div>
                </div>
                ${rightCol}`;
            section.appendChild(card);
        }
        el.appendChild(section);
    }
}

async function downloadLocalModel(modelId, btn) {
    const statusEl = document.getElementById('localModelStatus');
    const progressWrap = document.getElementById('localModelProgressWrap');
    const progressFill = document.getElementById('localModelProgressFill');
    const progressPct  = document.getElementById('localModelProgressPct');

    btn.disabled = true;
    btn.textContent = '⏳';
    statusEl.hidden = false;
    statusEl.className = 'pull-status';
    statusEl.textContent = `Starting download…`;
    progressWrap.hidden = false;
    progressFill.style.width = '0%';
    progressPct.textContent = '0%';

    try {
        const resp = await fetch(`/api/local-models/${modelId}/download`, { method: 'POST' });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        outer: while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                let ev;
                try { ev = JSON.parse(line.slice(6)); } catch { continue; }
                if (ev.error) throw new Error(ev.error);
                if (ev.status === '__done__') break outer;
                if (ev.downloaded_gb !== undefined && ev.total_gb) {
                    const pct = Math.min(100, Math.round(ev.downloaded_gb / ev.total_gb * 100));
                    const dlStr = ev.downloaded_gb.toFixed(2);
                    const totStr = ev.total_gb.toFixed(2);
                    statusEl.textContent = `Downloading… ${dlStr} / ${totStr} GB`;
                    progressFill.style.width = pct + '%';
                    progressPct.textContent = pct + '%';
                } else if (ev.status) {
                    statusEl.textContent = ev.status;
                }
            }
        }
        statusEl.className = 'pull-status success';
        statusEl.textContent = 'Download complete!';
        progressFill.style.width = '100%';
        progressPct.textContent = '100%';
        await loadModelCatalog();
    } catch (e) {
        statusEl.className = 'pull-status error';
        statusEl.textContent = 'Error: ' + e.message;
        progressWrap.hidden = true;
        btn.disabled = false;
        btn.textContent = '⬇ Download';
    }
}

async function deleteLocalModel(modelId, btn) {
    if (!confirm(`Delete local files for this model? This cannot be undone.`)) return;
    btn.disabled = true;
    try {
        await fetch(`/api/local-models/${modelId}`, { method: 'DELETE' });
        await loadModelCatalog();
    } catch (e) {
        alert('Delete failed: ' + e.message);
        btn.disabled = false;
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Datasets
// ═══════════════════════════════════════════════════════════════════════

const _DS_CAT_ORDER = ['Image Classification', 'Object Detection', 'Segmentation', 'Document / OCR'];
const _DS_CAT_ICON  = {
    'Image Classification': '🖼️',
    'Object Detection':     '📦',
    'Segmentation':         '🎨',
    'Document / OCR':       '📄',
};

async function loadDatasets() {
    const el = document.getElementById('datasetCatalog');
    el.innerHTML = '<p class="placeholder">Loading…</p>';
    try {
        const resp = await fetch('/api/datasets');
        const data = await resp.json();
        const datasets = data.datasets || [];
        if (datasets.length === 0) { el.innerHTML = '<p class="placeholder">No datasets in catalog.</p>'; return; }

        const groups = {};
        for (const d of datasets) {
            (groups[d.category] = groups[d.category] || []).push(d);
        }

        el.innerHTML = '';
        for (const cat of _DS_CAT_ORDER) {
            if (!groups[cat]) continue;
            const header = document.createElement('div');
            header.className = 'mcat-group-label';
            header.textContent = `${_DS_CAT_ICON[cat] || ''} ${cat}`;
            el.appendChild(header);

            for (const d of groups[cat]) {
                el.appendChild(buildDatasetCard(d));
            }
        }
    } catch (e) {
        el.innerHTML = `<p class="placeholder">Failed to load datasets: ${e.message}</p>`;
    }
}

function buildDatasetCard(d) {
    const card = document.createElement('div');
    card.className = 'ds-card';
    card.id = `ds-card-${d.id}`;

    const badge = d.downloaded
        ? `<span class="mcat-badge downloaded">Downloaded</span>`
        : '';
    const sizeLabel = d.downloaded && d.local_size_gb
        ? `${d.local_size_gb} GB on disk`
        : `~${d.size_gb} GB`;
    const samplesLabel = d.num_samples ? `${(d.num_samples / 1000).toFixed(0)}K samples` : '';
    const splitsLabel = (d.splits || []).join(' · ');
    const taskBadge = d.task ? `<span class="ds-task-badge">${d.task}</span>` : '';

    const rightCol = d.downloaded
        ? `<div class="ds-actions">
               <span class="ready-label">Ready</span>
               <button class="btn-delete-sm" onclick="deleteDataset('${d.id}', this)" title="Delete">🗑</button>
           </div>`
        : `<button class="btn-dl-ds" id="ds-dl-btn-${d.id}" onclick="downloadDataset('${d.id}', this)">⬇ Download</button>`;

    card.innerHTML = `
        <div class="ds-info">
            <div class="ds-title">${d.name} ${badge}</div>
            ${taskBadge}
            <div class="ds-desc">${d.desc}</div>
            <div class="ds-meta">${sizeLabel}${samplesLabel ? ' · ' + samplesLabel : ''}${splitsLabel ? ' · ' + splitsLabel : ''}</div>
        </div>
        <div class="ds-right">${rightCol}</div>`;
    return card;
}

async function downloadDataset(datasetId, btn) {
    const statusEl = document.getElementById('datasetStatus');
    const progressWrap = document.getElementById('datasetProgressWrap');
    const fill = document.getElementById('datasetProgressFill');
    const pct = document.getElementById('datasetProgressPct');

    btn.disabled = true;
    btn.textContent = '⏳ Starting…';
    statusEl.hidden = false;
    statusEl.className = 'pull-status';
    statusEl.textContent = 'Connecting…';
    progressWrap.hidden = false;
    fill.style.width = '0%';
    pct.textContent = '0%';

    // scroll progress into view
    statusEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    try {
        const resp = await fetch(`/api/datasets/${datasetId}/download`, { method: 'POST' });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '', totalGb = 0;
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const ev = JSON.parse(line.slice(5).trim());
                if (ev.error) {
                    statusEl.className = 'pull-status error';
                    statusEl.textContent = '❌ ' + ev.error;
                    btn.disabled = false;
                    btn.textContent = '⬇ Download';
                    return;
                }
                if (ev.total_gb) totalGb = ev.total_gb;
                if (ev.downloaded_gb !== undefined && totalGb) {
                    const p = Math.min(100, Math.round(ev.downloaded_gb / totalGb * 100));
                    fill.style.width = p + '%';
                    pct.textContent = p + '%';
                    statusEl.textContent = `Downloading… ${ev.downloaded_gb.toFixed(2)} / ${totalGb.toFixed(2)} GB`;
                } else if (ev.status && ev.status !== '__done__') {
                    statusEl.textContent = ev.status;
                }
                if (ev.status === '__done__') {
                    fill.style.width = '100%';
                    pct.textContent = '100%';
                    statusEl.className = 'pull-status success';
                    statusEl.textContent = '✅ Download complete';
                    await loadDatasets();
                    setTimeout(() => { progressWrap.hidden = true; statusEl.hidden = true; }, 3000);
                    return;
                }
            }
        }
    } catch (e) {
        statusEl.className = 'pull-status error';
        statusEl.textContent = '❌ ' + e.message;
        btn.disabled = false;
        btn.textContent = '⬇ Download';
    }
}

async function deleteDataset(datasetId, btn) {
    if (!confirm('Delete this dataset? This cannot be undone.')) return;
    btn.disabled = true;
    try {
        await fetch(`/api/datasets/${datasetId}`, { method: 'DELETE' });
        await loadDatasets();
    } catch (e) {
        alert('Delete failed: ' + e.message);
        btn.disabled = false;
    }
}

async function searchDatasets() {
    const q = document.getElementById('dsSearchInput').value.trim();
    if (!q) return;
    const source = document.getElementById('dsSearchSource').value;
    const resultsEl = document.getElementById('dsSearchResults');
    resultsEl.hidden = false;
    resultsEl.innerHTML = '<p class="placeholder">Searching…</p>';

    try {
        const resp = await fetch(`/api/datasets/search?q=${encodeURIComponent(q)}&source=${source}&limit=12`);
        const data = await resp.json();
        if (data.error) {
            resultsEl.innerHTML = `<p class="placeholder error-text">⚠ ${data.error}</p>`;
            return;
        }
        if (!data.results.length) {
            resultsEl.innerHTML = '<p class="placeholder">No results found.</p>';
            return;
        }
        const sourceIcon = source === 'huggingface' ? '🤗' : '📊';
        resultsEl.innerHTML = `
            <div class="ds-search-header">
                <span>${sourceIcon} ${data.results.length} results for "<strong>${q}</strong>" on ${source === 'huggingface' ? 'HuggingFace' : 'Kaggle'}</span>
                <button class="btn-sm" onclick="document.getElementById('dsSearchResults').hidden=true">✕ Close</button>
            </div>
            <div class="ds-search-grid">${data.results.map(r => buildSearchResultCard(r)).join('')}</div>`;
    } catch (e) {
        resultsEl.innerHTML = `<p class="placeholder error-text">⚠ Search failed: ${e.message}</p>`;
    }
}

function buildSearchResultCard(r) {
    const tags = (r.tags || []).slice(0, 4).map(t => `<span class="ds-tag">${t}</span>`).join('');
    const dlCount = r.downloads > 1000 ? `${(r.downloads/1000).toFixed(0)}k` : (r.downloads || 0);
    const sizeStr = r.size_mb ? ` · ~${(r.size_mb/1024).toFixed(1)} GB` : '';
    const source = r.source;
    return `
        <div class="ds-result-card">
            <div class="ds-result-info">
                <div class="ds-result-title">${r.name} <span class="ds-result-id">${r.full_id}</span></div>
                <div class="ds-result-meta">⬇ ${dlCount}${sizeStr} · ♥ ${r.likes || 0}</div>
                <div class="ds-result-tags">${tags}</div>
            </div>
            <div class="ds-result-actions">
                <a href="${r.url}" target="_blank" class="btn-sm btn-link">↗ View</a>
                ${source === 'huggingface'
                    ? `<button class="btn-primary-sm" onclick="downloadExternalDataset('${r.full_id}', '${r.name.replace(/'/g,"\\'")}', this)">⬇ Download</button>`
                    : `<button class="btn-primary-sm" onclick="openKaggleDownload('${r.full_id}')">⬇ Kaggle</button>`
                }
            </div>
        </div>`;
}

async function downloadExternalDataset(fullId, name, btn) {
    const statusEl = document.getElementById('datasetStatus');
    const progressWrap = document.getElementById('datasetProgressWrap');
    const fill = document.getElementById('datasetProgressFill');
    const pct = document.getElementById('datasetProgressPct');

    btn.disabled = true;
    btn.textContent = '⏳ Starting…';
    statusEl.hidden = false;
    statusEl.className = 'pull-status';
    statusEl.textContent = 'Connecting…';
    progressWrap.hidden = false;
    fill.style.width = '0%';
    pct.textContent = '0%';
    statusEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    try {
        const resp = await fetch('/api/datasets/add-external', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: fullId, full_id: fullId, name, source: 'huggingface' }),
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '', totalGb = 0;
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const ev = JSON.parse(line.slice(5).trim());
                if (ev.error) {
                    statusEl.className = 'pull-status error';
                    statusEl.textContent = '❌ ' + ev.error;
                    btn.disabled = false;
                    btn.textContent = '⬇ Download';
                    return;
                }
                if (ev.total_gb) totalGb = ev.total_gb;
                if (ev.downloaded_gb !== undefined && totalGb) {
                    const p = Math.min(100, Math.round(ev.downloaded_gb / totalGb * 100));
                    fill.style.width = p + '%';
                    pct.textContent = p + '%';
                    statusEl.textContent = `Downloading… ${ev.downloaded_gb.toFixed(2)} / ${totalGb.toFixed(2)} GB`;
                } else if (ev.status && ev.status !== '__done__') {
                    statusEl.textContent = ev.status;
                }
                if (ev.status === '__done__') {
                    fill.style.width = '100%';
                    pct.textContent = '100%';
                    statusEl.className = 'pull-status success';
                    statusEl.textContent = '✅ Download complete';
                    btn.textContent = '✅ Downloaded';
                    await loadDatasets();
                    setTimeout(() => { progressWrap.hidden = true; statusEl.hidden = true; }, 3000);
                    return;
                }
            }
        }
    } catch (e) {
        statusEl.className = 'pull-status error';
        statusEl.textContent = '❌ ' + e.message;
        btn.disabled = false;
        btn.textContent = '⬇ Download';
    }
}

function openKaggleDownload(ref) {
    window.open(`https://www.kaggle.com/datasets/${ref}`, '_blank');
}

async function loadHardwareAndRecommended() {
    try {
        const [resp, pulledResp] = await Promise.all([
            fetch('/api/models/recommended'),
            fetch('/api/models'),
        ]);
        const data = await resp.json();
        const pulledData = await pulledResp.json().catch(() => ({ models: [] }));
        // Normalize pulled model names: strip tag suffix, lowercase
        const pulledSet = new Set(
            (pulledData.models || []).map(n => n.replace(/:latest$/i, '').toLowerCase())
        );
        const hw = data.hardware;
        const hwEl = document.getElementById('hardwareInfo');
        if (hw) {
            const accel = hw.acceleration || 'cpu';
            const accelLabel = { metal: 'Metal', mps: 'MPS', mlx: 'MLX', cuda: 'CUDA', rocm: 'ROCm', cpu: 'CPU' }[accel] || accel.toUpperCase();
            const vramLabel = hw.gpu_vram_gb > 0 ? `${hw.gpu_vram_gb.toFixed(0)} GB` : '—';
            const gpuCoresLabel = hw.gpu_cores > 0 ? hw.gpu_cores : '—';
            const unifiedBadge = hw.unified_memory ? '<span class="hw-badge-unified">Unified</span>' : '';
            const chipName = hw.cpu_name || hw.gpu_name || '';
            hwEl.innerHTML = `
                <div class="hw-grid">
                    <div class="hw-card"><div class="hw-value">${hw.ram_gb.toFixed(0)} GB</div><div class="hw-label">System RAM${hw.unified_memory ? ' / VRAM' : ''}</div></div>
                    <div class="hw-card"><div class="hw-value">${vramLabel}</div><div class="hw-label">GPU VRAM${unifiedBadge}</div></div>
                    <div class="hw-card"><div class="hw-value">${hw.cpu_cores}</div><div class="hw-label">CPU Cores</div></div>
                    <div class="hw-card"><div class="hw-value">${gpuCoresLabel}</div><div class="hw-label">GPU Cores</div></div>
                </div>
                <div class="hw-footer">
                    ${chipName ? `<span class="hw-chip-name">${chipName}</span>` : ''}
                    <span class="accel-badge ${accel}">${accelLabel}</span>
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
            const runtime = (m.runtime || 'ollama').toLowerCase();
            const runtimeLabel = { mlx: 'MLX', llamacpp: 'llama.cpp', ollama: 'Ollama' }[runtime] || runtime.toUpperCase();
            const shortName = m.name.includes('/') ? m.name.split('/').pop() : m.name;
            // For MLX models, prefer the first gguf_source as the pull target (hf.co/<repo>)
            const ggufRepo = (m.gguf_sources || [])[0]?.repo;
            const pullTag = ggufRepo ? `hf.co/${ggufRepo}` : (m.name.includes('/') ? `hf.co/${m.name}` : `${m.name}:${m.quantization}`);
            const displayTag = `${m.name}:${m.quantization}`;
            // Check if already pulled: match on pullTag or displayTag (strip :latest, lowercase)
            const normalizedPull = pullTag.replace(/:latest$/i, '').toLowerCase();
            const normalizedDisplay = displayTag.replace(/:latest$/i, '').toLowerCase();
            const alreadyPulled = pulledSet.has(normalizedPull) || pulledSet.has(normalizedDisplay)
                || [...pulledSet].some(p => p === normalizedPull || p.endsWith('/' + normalizedPull));
            const actionCol = alreadyPulled
                ? `<span class="mcat-badge downloaded" style="font-size:0.72rem">Downloaded</span>`
                : `<button class="btn-pull-sm" onclick="quickPullCmd('${escapeHtml(pullTag)}', this)" title="ollama pull ${escapeHtml(pullTag)}">⬇</button>`;
            row.innerHTML = `
                <span class="fit-badge ${fitCls}">${m.fit}</span>
                <span class="runtime-badge runtime-${runtime}">${runtimeLabel}</span>
                <span class="model-name" title="${displayTag}">${shortName}:${m.quantization}</span>
                <span class="model-meta">${m.vram_gb}GB</span>
                ${actionCol}`;
            recEl.appendChild(row);
        }
    } catch (e) {
        document.getElementById('hardwareInfo').innerHTML = '<p class="placeholder">Failed to load.</p>';
        console.error(e);
    }
}

function _categorizeModel(name) {
    const n = name.toLowerCase();
    if (/llava|glm-ocr|olmocr|moondream|bakllava|vision|vl:|vl-|minicpm-v|qwen.*vl|cogvlm|idefics|ocr/.test(n)) return 'Vision';
    if (/thinking|r1|reasoning|qwq|deepseek-r/.test(n)) return 'Reasoning';
    if (/coder|codellama|code|starcoder|deepseek-coder|magicoder|wizard-coder/.test(n)) return 'Coding';
    if (/embed|minilm|bge-|nomic-embed/.test(n)) return 'Embedding';
    if (/tts|whisper|speech|transcri/.test(n)) return 'Specialized';
    if (/cloud/.test(n)) return 'Cloud';
    return 'General';
}

const _CATEGORY_ORDER = ['Vision', 'Reasoning', 'Coding', 'General', 'Embedding', 'Specialized', 'Cloud'];
const _CATEGORY_ICON = { Vision: '👁', Reasoning: '🧠', Coding: '💻', General: '💬', Embedding: '🔢', Specialized: '🎙', Cloud: '☁' };

async function loadPulledModels() {
    try {
        const resp = await fetch('/api/models');
        const data = await resp.json();
        const container = document.getElementById('pulledModelsList');
        const badge = document.getElementById('pulledCount');
        const models = data.models || [];
        badge.textContent = models.length;
        if (models.length === 0) { container.innerHTML = '<p class="placeholder">No models pulled yet.</p>'; return; }

        // Group by category
        const groups = {};
        for (const name of models.sort()) {
            const cat = _categorizeModel(name);
            (groups[cat] = groups[cat] || []).push(name);
        }

        container.innerHTML = '';
        for (const cat of _CATEGORY_ORDER) {
            if (!groups[cat]) continue;
            const section = document.createElement('div');
            section.className = 'model-category';
            section.innerHTML = `<div class="model-cat-header">${_CATEGORY_ICON[cat] || ''} ${cat} <span class="model-cat-count">${groups[cat].length}</span></div>`;
            for (const name of groups[cat]) {
                const row = document.createElement('div');
                row.className = 'model-row';
                const displayName = name.includes('/') ? name.split('/').pop() : name;
                row.innerHTML = `
                    <span class="model-name" title="${name}">${displayName}</span>
                    <button class="btn-delete" onclick="deleteModel('${name}', this)" title="Delete">✕</button>`;
                section.appendChild(row);
            }
            container.appendChild(section);
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

async function quickPullCmd(modelTag, btn) {
    const status = document.getElementById('pullStatus');
    const progressWrap = document.getElementById('pullProgressWrap');
    const progressFill = document.getElementById('pullProgressFill');
    const progressPct  = document.getElementById('pullProgressPct');

    btn.disabled = true;
    btn.textContent = '⏳';
    status.hidden = false;
    status.className = 'pull-status';
    status.textContent = `Starting: ollama pull ${modelTag} …`;
    progressWrap.hidden = false;
    progressFill.style.width = '0%';
    progressPct.textContent = '0%';

    try {
        const resp = await fetch('/api/models/pull-cmd', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelTag }),
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        outer: while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                let ev;
                try { ev = JSON.parse(line.slice(6)); } catch { continue; }
                if (ev.error) throw new Error(ev.error);
                if (ev.status === '__done__') break outer;

                const st = ev.status || '';
                if (ev.total && ev.completed) {
                    const pct = Math.min(100, Math.round(ev.completed / ev.total * 100));
                    const doneGb = (ev.completed / 1e9).toFixed(2);
                    const totalGb = (ev.total / 1e9).toFixed(2);
                    status.textContent = `${st} — ${doneGb} GB / ${totalGb} GB`;
                    progressFill.style.width = pct + '%';
                    progressPct.textContent = pct + '%';
                } else {
                    status.textContent = st;
                }
            }
        }

        status.className = 'pull-status success';
        status.textContent = `Pulled '${modelTag}' successfully.`;
        progressFill.style.width = '100%';
        progressPct.textContent = '100%';
        await loadPulledModels();
    } catch (e) {
        status.className = 'pull-status error';
        status.textContent = 'Error: ' + e.message;
        progressWrap.hidden = true;
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
            const actionsHtml = j.runnable
                ? `<div class="cron-actions">
                    <button class="btn-run-job" onclick="showFineTuneModal(${JSON.stringify(j).replace(/"/g, '&quot;')})">⚙ Configure &amp; Run</button>
                   </div>`
                : '';
            html += `<div class="cron-card${j.runnable ? ' cron-runnable' : ''}">
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
                ${actionsHtml}
            </div>`;
        }
        html += '</div>';
        el.innerHTML = html;
    } catch {
        el.innerHTML = '<p class="placeholder">Failed to load jobs.</p>';
    }
}

function showFineTuneModal(job) {
    const d = job.defaults || {};
    const existing = document.getElementById('fineTuneModalOverlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'fineTuneModalOverlay';
    overlay.className = 'skill-modal-overlay';
    overlay.innerHTML = `
        <div class="skill-modal ft-modal">
            <div class="sim-header">
                <span class="sim-icon">🎯</span>
                <div>
                    <div class="sim-title">Model Fine-Tuning</div>
                    <div class="sim-subtitle">HuggingFace Trainer — local GPU/MPS/CPU</div>
                </div>
                <button class="sim-close" onclick="document.getElementById('fineTuneModalOverlay').remove()">✕</button>
            </div>
            <div class="ft-form">
                <div class="ft-row">
                    <label>Base Model <span class="ft-hint">(HuggingFace model ID)</span></label>
                    <input id="ft-model-id" type="text" value="${d.model_id || 'google/vit-base-patch16-224'}" placeholder="google/vit-base-patch16-224" />
                </div>
                <div class="ft-row">
                    <label>Dataset <span class="ft-hint">(HuggingFace dataset ID or local path)</span></label>
                    <input id="ft-dataset-id" type="text" value="${d.dataset_id || 'food101'}" placeholder="food101" />
                </div>
                <div class="ft-row-2col">
                    <div class="ft-row">
                        <label>Image column</label>
                        <input id="ft-image-col" type="text" value="${d.image_column || 'image'}" placeholder="image" />
                    </div>
                    <div class="ft-row">
                        <label>Label column</label>
                        <input id="ft-label-col" type="text" value="${d.label_column || 'label'}" placeholder="label" />
                    </div>
                </div>
                <div class="ft-row-3col">
                    <div class="ft-row">
                        <label>Epochs</label>
                        <input id="ft-epochs" type="number" value="${d.epochs || 3}" min="1" max="100" />
                    </div>
                    <div class="ft-row">
                        <label>Learning rate</label>
                        <input id="ft-lr" type="text" value="${d.lr || '5e-5'}" placeholder="5e-5" />
                    </div>
                    <div class="ft-row">
                        <label>Batch size</label>
                        <input id="ft-batch" type="number" value="${d.batch_size || 16}" min="1" max="256" />
                    </div>
                </div>
                <div class="ft-row">
                    <label>Output name <span class="ft-hint">(saved to output/fine-tuned/…)</span></label>
                    <input id="ft-output-name" type="text" value="${d.output_name || 'my-fine-tuned-model'}" placeholder="my-fine-tuned-model" />
                </div>
                <div class="ft-log-wrap" id="ft-log-wrap" hidden>
                    <div class="ft-log" id="ft-log"></div>
                </div>
                <div class="ft-footer">
                    <button class="sim-btn primary" id="ft-run-btn" onclick="runFineTuneJob()">▶ Start Training</button>
                    <span class="ft-status" id="ft-status"></span>
                </div>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

async function runFineTuneJob() {
    const btn = document.getElementById('ft-run-btn');
    const statusEl = document.getElementById('ft-status');
    const logWrap = document.getElementById('ft-log-wrap');
    const log = document.getElementById('ft-log');

    const config = {
        model_id:     document.getElementById('ft-model-id').value.trim(),
        dataset_id:   document.getElementById('ft-dataset-id').value.trim(),
        image_column: document.getElementById('ft-image-col').value.trim(),
        label_column: document.getElementById('ft-label-col').value.trim(),
        epochs:       parseInt(document.getElementById('ft-epochs').value) || 3,
        lr:           parseFloat(document.getElementById('ft-lr').value) || 5e-5,
        batch_size:   parseInt(document.getElementById('ft-batch').value) || 16,
        output_name:  document.getElementById('ft-output-name').value.trim() || 'my-fine-tuned-model',
    };

    btn.disabled = true;
    btn.textContent = '⏳ Training…';
    statusEl.textContent = '';
    logWrap.hidden = false;
    log.innerHTML = '';

    try {
        const resp = await fetch('/api/jobs/fine-tune/run', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const ev = JSON.parse(line.slice(5).trim());
                if (ev.line !== undefined) {
                    const div = document.createElement('div');
                    div.className = 'ft-log-line';
                    div.textContent = ev.line;
                    log.appendChild(div);
                    log.scrollTop = log.scrollHeight;
                } else if (ev.status === '__done__') {
                    if (ev.success) {
                        statusEl.className = 'ft-status ok';
                        statusEl.textContent = `✅ Saved to output/fine-tuned/${config.output_name}`;
                    } else {
                        statusEl.className = 'ft-status error';
                        statusEl.textContent = '❌ Training failed — see log above';
                    }
                    btn.disabled = false;
                    btn.textContent = '▶ Run Again';
                }
            }
        }
    } catch (e) {
        statusEl.className = 'ft-status error';
        statusEl.textContent = '❌ ' + e.message;
        btn.disabled = false;
        btn.textContent = '▶ Start Training';
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
        _skillsById = data || {};
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

function buildSkillCard(id, info) {
    const card = document.createElement('div');
    card.className = `skill-card ${info.status}`;
    const toolsHtml = (info.tools || []).map(t => `<span class="skill-tool-chip">${t}</span>`).join('');
    const missingItems = info.missing || [];
    const missingHtml = missingItems.length
        ? (info.status === 'ready'
            ? `<div class="skill-missing optional">+ Optional: ${missingItems.join(', ')}</div>`
            : `<div class="skill-missing">⚠ Requires: ${missingItems.join(', ')}</div>`)
        : '';
    const modelHtml = info.model_label
        ? `<div class="skill-model-tag">🤖 ${escapeHtml(info.model_label)}</div>` : '';
    const actions = [];
    if (id === 'text_to_diagram') {
        actions.push(`<button class="btn-sm" onclick="openTextToDiagramSkill()">Open</button>`);
    }
    if (info.status !== 'ready') {
        actions.push(`<button class="btn-install-skill" onclick="showSkillInstallModal('${id}')">⚙ Install Skill</button>`);
    }
    actions.push(
        `<button class="pin-btn ${isSkillPinned(id) ? 'pinned' : ''}" ` +
        `onclick="togglePinSkill('${id}')" ` +
        `title="${isSkillPinned(id) ? 'Unpin from sidebar' : 'Pin to sidebar'}">` +
        `📌 ${isSkillPinned(id) ? 'Pinned' : 'Pin'}</button>`
    );
    const actionsHtml = `<div class="skill-actions">${actions.join('')}</div>`;
    card.innerHTML = `
        <div class="skill-head">
            <span class="skill-icon">${info.icon}</span>
            <span class="skill-title">${info.label}</span>
            <span class="status-badge ${info.status}">${info.status.replace(/-/g, ' ')}</span>
        </div>
        <div class="skill-cat">${info.category}</div>
        <div class="skill-desc">${info.description}</div>
        ${modelHtml}
        ${missingHtml}
        ${actionsHtml}
        ${toolsHtml ? `<div class="skill-tools">${toolsHtml}</div>` : ''}`;
    return card;
}

// ── Skill Install Modal ───────────────────────────────────────────────────────

function showSkillInstallModal(skillId) {
    const info = _skillsById[skillId];
    if (!info) return;

    const packages = info.packages || [];
    const models   = info.models   || [];
    const powers   = info.powers   || [];

    const overlay = document.createElement('div');
    overlay.className = 'skill-modal-overlay';
    overlay.id = 'skillInstallOverlay';

    const hasSteps = packages.length || models.length || powers.length;
    const stepsHtml = !hasSteps
        ? `<p class="sim-empty">No automated install steps available. Check the skill requirements manually.</p>`
        : [
            packages.length ? `
            <div class="sim-step" id="sim-step-pkg">
                <div class="sim-step-header">
                    <span class="sim-step-icon">📦</span>
                    <div class="sim-step-info">
                        <strong>Python Packages</strong>
                        <span class="sim-step-detail">${packages.join('  ·  ')}</span>
                    </div>
                    <span class="sim-step-badge pending" id="sim-badge-pkg">Pending</span>
                </div>
                <div class="sim-step-body" id="sim-body-pkg" hidden>
                    <div class="sim-output" id="sim-output-pkg"></div>
                </div>
                <button class="sim-btn" id="sim-btn-pkg" onclick="skillInstallPackages('${skillId}')">
                    Install Packages
                </button>
            </div>` : '',
            models.map((m, i) => `
            <div class="sim-step" id="sim-step-model-${i}">
                <div class="sim-step-header">
                    <span class="sim-step-icon">🤖</span>
                    <div class="sim-step-info">
                        <strong>Download Model</strong>
                        <span class="sim-step-detail">${escapeHtml(m.label)}</span>
                    </div>
                    <span class="sim-step-badge pending" id="sim-badge-model-${i}">Pending</span>
                </div>
                <button class="sim-btn" id="sim-btn-model-${i}" onclick="skillDownloadModel('${m.id}')">
                    Download Model
                </button>
            </div>`).join(''),
            powers.map((p, i) => `
            <div class="sim-step" id="sim-step-power-${i}">
                <div class="sim-step-header">
                    <span class="sim-step-icon">🔌</span>
                    <div class="sim-step-info">
                        <strong>Configure Power</strong>
                        <span class="sim-step-detail">${escapeHtml(p.label)}</span>
                    </div>
                    <span class="sim-step-badge pending" id="sim-badge-power-${i}">Pending</span>
                </div>
                <button class="sim-btn" id="sim-btn-power-${i}" onclick="skillOpenPower()">
                    Open Powers →
                </button>
            </div>`).join(''),
        ].join('');

    overlay.innerHTML = `
        <div class="skill-modal">
            <div class="sim-header">
                <span class="sim-icon">${info.icon}</span>
                <div>
                    <div class="sim-title">Install: ${escapeHtml(info.label)}</div>
                    <div class="sim-subtitle">Complete the steps below to enable this skill</div>
                </div>
                <button class="sim-close" onclick="closeSkillInstallModal()">✕</button>
            </div>
            <div class="sim-steps">${stepsHtml}</div>
        </div>`;

    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) closeSkillInstallModal(); });
}

function closeSkillInstallModal() {
    document.getElementById('skillInstallOverlay')?.remove();
    loadSkills();
}

async function skillInstallPackages(skillId) {
    const info = _skillsById[skillId];
    const packages = info?.packages || [];
    const btn    = document.getElementById('sim-btn-pkg');
    const badge  = document.getElementById('sim-badge-pkg');
    const body   = document.getElementById('sim-body-pkg');
    const output = document.getElementById('sim-output-pkg');
    if (!btn) return;

    btn.disabled = true;
    btn.textContent = 'Installing…';
    badge.className = 'sim-step-badge running';
    badge.textContent = 'Installing';
    body.hidden = false;
    output.textContent = '';

    try {
        const resp = await fetch('/api/skills/install-packages', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ packages }),
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                let ev;
                try { ev = JSON.parse(line.slice(6)); } catch { continue; }
                if (ev.line !== undefined) {
                    output.textContent += ev.line + '\n';
                    output.scrollTop = output.scrollHeight;
                }
                if (ev.status === '__done__') {
                    if (ev.success) {
                        badge.className = 'sim-step-badge done';
                        badge.textContent = '✓ Done';
                        btn.textContent = '✓ Installed';
                    } else {
                        badge.className = 'sim-step-badge error';
                        badge.textContent = '✗ Failed';
                        btn.disabled = false;
                        btn.textContent = 'Retry';
                    }
                }
            }
        }
    } catch (e) {
        badge.className = 'sim-step-badge error';
        badge.textContent = '✗ Error';
        output.textContent += '\nError: ' + e.message;
        btn.disabled = false;
        btn.textContent = 'Retry';
    }
}

function skillDownloadModel(modelId) {
    closeSkillInstallModal();
    switchView('instances');
    // Give the view time to render, then scroll to the model in the catalog
    setTimeout(() => {
        const card = document.querySelector(`.mcat-card[data-model-id="${modelId}"]`);
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.style.outline = '2px solid var(--accent)';
            setTimeout(() => { card.style.outline = ''; }, 3000);
            card.querySelector('.btn-mcat-download')?.click();
        }
    }, 400);
}

function skillOpenPower() {
    closeSkillInstallModal();
    switchView('powers');
}

function openTextToDiagramSkill() {
    switchView('text2diagram');
}

function _getT2DSelections() {
    const provider = document.getElementById('t2dProvider')?.value || 'ollama';
    const vlmProvider = document.getElementById('t2dVlmProvider')?.value || 'ollama';
    const imageProvider = document.getElementById('t2dImageProvider')?.value || 'matplotlib';
    const vlmModel = document.getElementById('t2dVlmModel')?.value?.trim() || '';
    const imageModel = document.getElementById('t2dImageModel')?.value?.trim() || '';
    const outputFormat = document.getElementById('t2dOutputFormat')?.value || 'png';
    return { provider, vlmProvider, imageProvider, vlmModel, imageModel, outputFormat };
}

function _syncT2DProfileFromProviders() {
    const profileSel = document.getElementById('t2dProvider');
    const vlmProvider = document.getElementById('t2dVlmProvider')?.value;
    const imageProvider = document.getElementById('t2dImageProvider')?.value;
    if (!profileSel || !vlmProvider || !imageProvider) return;

    const profiles = _t2dProviderDefaults.profiles || {};
    let matched = null;
    for (const [id, profile] of Object.entries(profiles)) {
        if (profile.vlm_provider === vlmProvider && profile.image_provider === imageProvider) {
            matched = id;
            break;
        }
    }
    if (matched) profileSel.value = matched;
}

function _populateT2DSelectOptions(selectEl, optionsMap, preferredValue) {
    if (!selectEl) return;

    const entries = Object.entries(optionsMap || {});
    if (!entries.length) return;

    const previousValue = selectEl.value;
    selectEl.innerHTML = '';

    for (const [id, meta] of entries) {
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = meta?.label || id;
        selectEl.appendChild(opt);
    }

    const pick = [preferredValue, previousValue, entries[0][0]].find(v =>
        typeof v === 'string' && entries.some(([id]) => id === v)
    );
    selectEl.value = pick || entries[0][0];
}

function _refreshT2DProviderSelectors(preferredProfile, preferredVlmProvider, preferredImageProvider) {
    _populateT2DSelectOptions(
        document.getElementById('t2dProvider'),
        _t2dProviderDefaults.profiles,
        preferredProfile
    );
    _populateT2DSelectOptions(
        document.getElementById('t2dVlmProvider'),
        _t2dProviderDefaults.vlm_providers,
        preferredVlmProvider
    );
    _populateT2DSelectOptions(
        document.getElementById('t2dImageProvider'),
        _t2dProviderDefaults.image_providers,
        preferredImageProvider
    );
}

function _ensureT2DModelSelect(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    if (el.tagName === 'SELECT') return el;

    // Backward compatibility: older UI shipped these as <input> elements.
    const sel = document.createElement('select');
    sel.id = el.id;
    sel.className = el.className;
    sel.style.cssText = el.style.cssText;
    if (el.disabled) sel.disabled = true;
    el.replaceWith(sel);
    return sel;
}

function _populateT2DModelSelectOptions(selectEl, choices, preferredValue) {
    if (!selectEl) return;
    const values = Array.from(new Set((choices || []).filter(v => typeof v === 'string' && v.trim())));
    if (!values.length) return;

    const previousValue = selectEl.value;
    selectEl.innerHTML = '';

    for (const value of values) {
        const opt = document.createElement('option');
        opt.value = value;
        opt.textContent = value;
        selectEl.appendChild(opt);
    }

    const pick = [preferredValue, previousValue, values[0]].find(v => values.includes(v));
    selectEl.value = pick || values[0];
}

function _setT2DModelInputState() {
    const vlmInput = _ensureT2DModelSelect('t2dVlmModel');
    const imageProvider = document.getElementById('t2dImageProvider')?.value || 'matplotlib';
    const imageInput = _ensureT2DModelSelect('t2dImageModel');
    if (!imageInput || !vlmInput) return;

    vlmInput.disabled = false;
    vlmInput.title = '';

    const locked = imageProvider === 'matplotlib' || imageProvider === 'mermaid_local';
    const hasSingleImageChoice = (imageInput.options?.length || 0) <= 1;
    imageInput.disabled = locked || hasSingleImageChoice;
}

function _applyT2DProviderDefaults(vlmProvider, imageProvider, force = false) {
    const vlmDefaults = (_t2dProviderDefaults.vlm_providers || {})[vlmProvider] || {};
    const imageDefaults = (_t2dProviderDefaults.image_providers || {})[imageProvider] || {};
    const vlmInput = _ensureT2DModelSelect('t2dVlmModel');
    const imageInput = _ensureT2DModelSelect('t2dImageModel');
    if (!vlmInput || !imageInput) return;

    const fallbackVlm = _localDefaultT2DVlmModel(vlmProvider);
    const fallbackImage = _localDefaultT2DImageModel(imageProvider);
    const defaultVlm = vlmDefaults.default_vlm_model || fallbackVlm;
    const defaultImage = imageDefaults.default_image_model || fallbackImage;

    const vlmChoices =
        vlmProvider === 'ollama' && _t2dVlmChoices.length
            ? _t2dVlmChoices
            : [defaultVlm];
    const imageChoices = [defaultImage];
    const lockedImageProvider = imageProvider === 'matplotlib' || imageProvider === 'mermaid_local';

    _populateT2DModelSelectOptions(vlmInput, vlmChoices, force ? defaultVlm : vlmInput.value);
    _populateT2DModelSelectOptions(
        imageInput,
        imageChoices,
        force || lockedImageProvider ? defaultImage : imageInput.value
    );

    if (force || !vlmInput.value.trim()) {
        vlmInput.value = vlmChoices.includes(defaultVlm) ? defaultVlm : vlmChoices[0];
    }
    if (force || lockedImageProvider || !imageInput.value.trim()) {
        imageInput.value = imageChoices.includes(defaultImage) ? defaultImage : imageChoices[0];
    }
    _setT2DModelInputState();
}

function onT2DProfileChange() {
    const provider = document.getElementById('t2dProvider')?.value || 'ollama';
    const profile = (_t2dProviderDefaults.profiles || {})[provider] || _localT2DProfileMap(provider);
    const vlmProviderSel = document.getElementById('t2dVlmProvider');
    const imageProviderSel = document.getElementById('t2dImageProvider');
    if (profile && vlmProviderSel && imageProviderSel) {
        vlmProviderSel.value = profile.vlm_provider || 'ollama';
        imageProviderSel.value = profile.image_provider || 'matplotlib';
        _applyT2DProviderDefaults(vlmProviderSel.value, imageProviderSel.value, true);
    }
    loadTextToDiagramView();
}

function onT2DVlmProviderChange() {
    const vlmProvider = document.getElementById('t2dVlmProvider')?.value || 'ollama';
    const imageProvider = document.getElementById('t2dImageProvider')?.value || 'matplotlib';
    _applyT2DProviderDefaults(vlmProvider, imageProvider, true);
    _syncT2DProfileFromProviders();
    loadTextToDiagramView();
}

function onT2DImageProviderChange() {
    const vlmProvider = document.getElementById('t2dVlmProvider')?.value || 'ollama';
    const imageProvider = document.getElementById('t2dImageProvider')?.value || 'matplotlib';
    _applyT2DProviderDefaults(vlmProvider, imageProvider, true);
    _syncT2DProfileFromProviders();
    loadTextToDiagramView();
}

function _t2dDownloadName(url, fallback) {
    try {
        const clean = String(url || '').split('?')[0];
        const name = clean.substring(clean.lastIndexOf('/') + 1);
        return name || fallback;
    } catch {
        return fallback;
    }
}

async function loadTextToDiagramView() {
    const status = document.getElementById('t2dJobStatus');
    const readiness = document.getElementById('t2dReadiness');
    const generateBtn = document.getElementById('t2dGenerateBtn');
    const { provider, vlmProvider, imageProvider, vlmModel, imageModel } = _getT2DSelections();
    _ensureT2DModelSelect('t2dVlmModel');
    _ensureT2DModelSelect('t2dImageModel');
    _applyT2DProviderDefaults(vlmProvider, imageProvider);
    if (status && !_t2dJobId) {
        status.className = 'status-badge inactive';
        status.textContent = 'idle';
    }
    // Resume polling if a job is active but no timer is running
    if (_t2dJobId && !_t2dPollTimer) {
        pollTextToDiagramJob();
        _t2dPollTimer = setInterval(pollTextToDiagramJob, 1200);
    }

    try {
        const params = new URLSearchParams({
            provider,
            vlm_provider: vlmProvider,
            image_provider: imageProvider,
        });
        if (vlmModel) params.set('vlm_model', vlmModel);
        if (imageModel) params.set('image_model', imageModel);
        const resp = await fetch(`/api/text-to-diagram/readiness?${params.toString()}`);
        const data = await resp.json();
        _t2dReady = Boolean(data.ready);
        if (generateBtn) generateBtn.disabled = !_t2dReady;

        // Support both new hybrid details schema and legacy single-provider schema.
        const details = data?.details || {};
        _t2dVlmChoices = Array.isArray(details.pulled_models) ? details.pulled_models : [];
        const legacyProviders = details.providers || {};
        const legacyVlmProviders = {};
        const legacyImageProviders = {};
        for (const [key, meta] of Object.entries(legacyProviders)) {
            const legacyImageProvider = meta.image_provider || _localT2DProfileMap(key).image_provider;
            legacyVlmProviders[key] = {
                label: meta.label || key,
                default_vlm_model: meta.default_vlm_model || _localDefaultT2DVlmModel(key),
            };
            legacyImageProviders[legacyImageProvider] = {
                label: legacyImageProvider,
                effective_provider: legacyImageProvider,
                default_image_model:
                    meta.default_image_model || _localDefaultT2DImageModel(legacyImageProvider),
            };
        }

        _t2dProviderDefaults = {
            profiles: details.profiles || {},
            vlm_providers: details.vlm_providers || legacyVlmProviders,
            image_providers: details.image_providers || legacyImageProviders,
        };

        _refreshT2DProviderSelectors(provider, vlmProvider, imageProvider);
        const currentSelections = _getT2DSelections();

        const resolvedVlmModel = details.selected_vlm_model || '';
        const resolvedImageModel = details.selected_image_model || '';
        const resolvedVlmProvider = details.selected_vlm_provider || '';
        const resolvedImageProvider = details.selected_image_provider || '';
        const resolvedImageProviderEffective = details.selected_image_provider_effective || resolvedImageProvider;
        const vlmInput = _ensureT2DModelSelect('t2dVlmModel');
        const imageInput = _ensureT2DModelSelect('t2dImageModel');
        const effectiveSelectedImageProvider =
            currentSelections.imageProvider === 'stability'
                ? 'openrouter_imagen'
                : currentSelections.imageProvider;

        const canApplyResolvedVlm = resolvedVlmProvider === currentSelections.vlmProvider;
        const canApplyResolvedImage =
            resolvedImageProvider === currentSelections.imageProvider ||
            resolvedImageProviderEffective === effectiveSelectedImageProvider;

        if (
            vlmInput &&
            canApplyResolvedVlm &&
            (!vlmInput.value.trim() ||
                vlmInput.value.trim() === _localDefaultT2DVlmModel(currentSelections.vlmProvider))
        ) {
            vlmInput.value = resolvedVlmModel || vlmInput.value;
        }
        if (
            imageInput &&
            canApplyResolvedImage &&
            (!imageInput.value.trim() ||
                imageInput.value.trim() === _localDefaultT2DImageModel(currentSelections.imageProvider))
        ) {
            imageInput.value = resolvedImageModel || imageInput.value;
        }

        _applyT2DProviderDefaults(currentSelections.vlmProvider, currentSelections.imageProvider);
        _syncT2DProfileFromProviders();

        const activeProfile = document.getElementById('t2dProvider')?.value || provider;
        const activeVlmProvider = document.getElementById('t2dVlmProvider')?.value || vlmProvider;
        const activeImageProvider = document.getElementById('t2dImageProvider')?.value || imageProvider;

        if (_t2dReady) {
            const pickedProfile = escapeHtml(activeProfile);
            const pickedVlm = escapeHtml(activeVlmProvider);
            const pickedImage = escapeHtml(activeImageProvider);
            readiness.innerHTML = `<div class="t2d-ok">Ready: profile <strong>${pickedProfile}</strong> → VLM <strong>${pickedVlm}</strong> + image <strong>${pickedImage}</strong> can generate diagrams.</div>`;
        } else {
            const issues = (data.issues || []).map(i => `<li>${escapeHtml(i)}</li>`).join('');
            const fixes = (data.fixes || []).map(f => `<code class="skill-install">${escapeHtml(f)}</code>`).join('<br/>');
            readiness.innerHTML = `
                <div class="t2d-bad">Not Ready: fix items below before generating.</div>
                <ul class="t2d-list">${issues || '<li>Unknown readiness error</li>'}</ul>
                <div class="t2d-fixes">${fixes || ''}</div>
            `;
        }
    } catch (e) {
        _t2dReady = false;
        if (generateBtn) generateBtn.disabled = true;
        readiness.innerHTML = `<div class="t2d-bad">Readiness check failed: ${escapeHtml(String(e.message || e))}</div>`;
    }
}

async function startTextToDiagramJob() {
    const sourceText = document.getElementById('t2dSourceText').value.trim();
    const caption = document.getElementById('t2dCaption').value.trim();
    const diagramType = document.getElementById('t2dType').value;
    const iterations = Number(document.getElementById('t2dIterations').value || 2);
    const { provider, vlmProvider, imageProvider, vlmModel, imageModel, outputFormat } = _getT2DSelections();
    const status = document.getElementById('t2dJobStatus');

    if (!_t2dReady) {
        status.className = 'status-badge needs-power';
        status.textContent = 'not ready';
        await loadTextToDiagramView();
        return;
    }

    if (!sourceText) {
        status.className = 'status-badge needs-power';
        status.textContent = 'source text required';
        return;
    }
    if (!caption) {
        status.className = 'status-badge needs-power';
        status.textContent = 'caption required';
        return;
    }

    document.getElementById('t2dEvents').innerHTML = '<p class="placeholder">Starting job…</p>';
    document.getElementById('t2dIterationsList').innerHTML = '<p class="placeholder">Waiting for iteration output…</p>';
    document.getElementById('t2dFinal').innerHTML = '<p class="placeholder">Running…</p>';

    try {
        const resp = await fetch('/api/text-to-diagram/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_text: sourceText,
                caption,
                diagram_type: diagramType,
                iterations,
                provider,
                vlm_provider: vlmProvider,
                image_provider: imageProvider,
                vlm_model: vlmModel,
                image_model: imageModel,
                output_format: outputFormat,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to create job');
        _t2dJobId = data.job_id;
        status.className = 'status-badge active';
        status.textContent = 'running';
        if (_t2dPollTimer) clearInterval(_t2dPollTimer);
        await pollTextToDiagramJob();
        _t2dPollTimer = setInterval(pollTextToDiagramJob, 1200);
    } catch (e) {
        status.className = 'status-badge needs-power';
        status.textContent = String(e.message || e);
    }
}

async function pollTextToDiagramJob() {
    if (!_t2dJobId) return;
    const status = document.getElementById('t2dJobStatus');
    try {
        const resp = await fetch(`/api/text-to-diagram/jobs/${_t2dJobId}`);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Job lookup failed');

        status.textContent = data.status;
        status.className = `status-badge ${data.status === 'completed' ? 'ready' : data.status === 'failed' ? 'needs-power' : 'active'}`;

        const eventsEl = document.getElementById('t2dEvents');
        const running = data.status !== 'completed' && data.status !== 'failed';
        const pulse = running ? '<div class="t2d-event-pulse">● running…</div>' : '';
        eventsEl.innerHTML = data.events.length
            ? data.events.map(e => `<div class="t2d-event ${e.kind}"><span>[${escapeHtml(e.time)}]</span> ${escapeHtml(e.message)}</div>`).join('') + pulse
            : (running ? pulse : '<p class="placeholder">No events yet.</p>');
        eventsEl.scrollTop = eventsEl.scrollHeight;

        const itersEl = document.getElementById('t2dIterationsList');
        itersEl.innerHTML = data.iterations.length
            ? data.iterations.map(it => `
                <div class="t2d-iter-card">
                    <div class="t2d-iter-head">Iteration ${it.iteration}</div>
                    <img src="${it.image_url}" alt="Iteration ${it.iteration}" class="t2d-img" />
                    <div style="margin-top:8px;">
                        <a class="btn-sm" href="${it.image_url}" download="${_t2dDownloadName(it.image_url, `diagram_iter_${it.iteration}.png`)}">Download Iteration ${it.iteration}</a>
                    </div>
                    <div class="t2d-iter-note">${escapeHtml(it.critique_summary || 'No critique summary yet.')}</div>
                </div>
            `).join('')
            : '<p class="placeholder">No iterations yet.</p>';

        const finalEl = document.getElementById('t2dFinal');
        if (data.final_mermaid) {
            const mermaidId = `t2d-mermaid-${data.id || _t2dJobId || 'final'}`;
            const mmdDataUrl = `data:text/plain;charset=utf-8,${encodeURIComponent(data.final_mermaid)}`;
            finalEl.innerHTML = `
                <div id="${mermaidId}" class="mermaid">${escapeHtml(data.final_mermaid)}</div>
                <div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap;">
                    <a class="btn-sm" href="${mmdDataUrl}" download="final_output.mmd">Download Mermaid Source</a>
                </div>
                <div class="t2d-iter-note">${escapeHtml(data.result_description || '')}</div>
            `;

            if (window.mermaid && typeof window.mermaid.initialize === 'function') {
                window.mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });
                const node = document.getElementById(mermaidId);
                if (node && typeof window.mermaid.run === 'function') {
                    window.mermaid.run({ nodes: [node] }).catch(() => {});
                }
            }
        } else if (data.final_image_url) {
            finalEl.innerHTML = `
                <img src="${data.final_image_url}" alt="Final output" class="t2d-img" />
                <div style="margin-top:8px;">
                    <a class="btn-sm" href="${data.final_image_url}" download="${_t2dDownloadName(data.final_image_url, 'final_output.png')}">Download Final Output</a>
                </div>
                <div class="t2d-iter-note">${escapeHtml(data.result_description || '')}</div>
            `;
        } else if (data.status === 'failed') {
            finalEl.innerHTML = `<p class="placeholder">Failed: ${escapeHtml(data.error || 'Unknown error')}</p>`;
        }

        if (data.status === 'completed' || data.status === 'failed') {
            if (_t2dPollTimer) {
                clearInterval(_t2dPollTimer);
                _t2dPollTimer = null;
            }
        }
    } catch (e) {
        status.className = 'status-badge needs-power';
        status.textContent = 'polling error';
    }
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
        statusEl.textContent = data.updated.length
            ? `Saved ${data.updated.length} key${data.updated.length !== 1 ? 's' : ''}`
            : 'No changes (token unchanged)';
        await new Promise(r => setTimeout(r, 800));
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
