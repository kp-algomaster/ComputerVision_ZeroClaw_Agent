import express from 'express';
import { createRequire } from 'module';
import { EventEmitter } from 'events';
import { getBrowserTools } from './browser_agent.js';

const require = createRequire(import.meta.url);

const app = express();
const port = 7862;
const PYTHON_BACKEND = 'http://127.0.0.1:8420';

app.use(express.json());

const activeRuns = new Map();       // runId -> { emitter, events[], done }
const pendingCheckpoints = new Map();

function createRun(runId) {
    const run = {
        emitter: new EventEmitter(),
        events: [],
        done: false,
    };
    // Buffer every event
    run.emitter.on('update', (data) => {
        run.events.push(data);
        if (data.status === 'completed' || data.status === 'failed' || data.error) {
            run.done = true;
        }
    });
    activeRuns.set(runId, run);
    // Clean up after 60s
    setTimeout(() => activeRuns.delete(runId), 60000);
    return run;
}

// Basic health check endpoint required by Python cv_agent
app.get('/health', (req, res) => {
    res.status(200).json({ status: 'ok', service: 'eko-sidecar' });
});

app.get('/workflow/:runId/stream', (req, res) => {
    const { runId } = req.params;

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');

    const run = activeRuns.get(runId);
    if (!run) {
        res.write(`data: ${JSON.stringify({ error: 'Run ID not found', status: 'failed' })}\n\n`);
        return res.end();
    }

    // Replay all buffered events first
    for (const evt of run.events) {
        res.write(`data: ${JSON.stringify(evt)}\n\n`);
    }

    // If already done, close immediately
    if (run.done) {
        return res.end();
    }

    // Otherwise, stream new events as they arrive
    const onUpdate = (data) => {
        res.write(`data: ${JSON.stringify(data)}\n\n`);
        if (data.status === 'completed' || data.status === 'failed' || data.error) {
            // Delay close so the browser has time to process the final message
            setTimeout(() => res.end(), 200);
        }
    };

    run.emitter.on('update', onUpdate);

    req.on('close', () => {
        run.emitter.off('update', onUpdate);
    });
});

app.post('/workflow/checkpoint/:cpId', (req, res) => {
    const { cpId } = req.params;
    const { approved, feedback } = req.body;

    if (pendingCheckpoints.has(cpId)) {
        const resolve = pendingCheckpoints.get(cpId);
        resolve({ approved, feedback });
        pendingCheckpoints.delete(cpId);
        res.status(200).json({ status: 'resumed' });
    } else {
        res.status(404).json({ error: 'Checkpoint not found' });
    }
});

app.post('/workflow/run', async (req, res) => {
    try {
        const { description } = req.body;

        if (!description) {
            return res.status(400).json({ error: 'Missing workflow description' });
        }

        const runId = `run_${Date.now()}`;
        const run = createRun(runId);
        const runEmitter = run.emitter;

        res.status(202).json({
            message: 'Workflow accepted',
            runId: runId
        });

        // Fetch tools from Python backend
        let pythonTools = [];
        try {
            const toolsRes = await fetch(`${PYTHON_BACKEND}/api/tools`);
            if (toolsRes.ok) {
                const toolsData = await toolsRes.json();
                pythonTools = toolsData.tools.map(t => ({
                    name: t.name,
                    description: t.description,
                    parameters: t.parameters,
                    execute: async (args) => {
                        runEmitter.emit('update', { type: 'tool_start', action: `Executing ${t.name}`, tool: t.name, tool_input: args });
                        const execRes = await fetch(`${PYTHON_BACKEND}/api/tools/execute`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ name: t.name, arguments: args })
                        });
                        const data = await execRes.json();
                        if (!execRes.ok) throw new Error(data.error || "Tool execution failed");
                        runEmitter.emit('update', { type: 'tool_end', action: `Finished ${t.name}`, detail: "Success" });
                        return JSON.stringify(data.result);
                    }
                }));
            }
        } catch (e) {
            console.error("Failed to fetch python tools:", e.message);
        }

        // Collect Playwright BrowserAgent Tools
        let browserTools = [];
        try {
            const bTools = getBrowserTools(runId, runEmitter);
            browserTools = bTools.map(t => ({
                name: t.name,
                description: t.description,
                parameters: t.parameters,
                execute: async (args) => {
                    runEmitter.emit('update', { type: 'tool_start', action: `Browser: ${t.name}`, tool: t.name, tool_input: args });
                    try {
                        const result = await t.execute(args);
                        runEmitter.emit('update', { type: 'tool_end', action: `Finished ${t.name}`, detail: result.substring(0, 100) });
                        return result;
                    } catch (err) {
                        runEmitter.emit('update', { type: 'tool_end', action: `Failed ${t.name}`, error: err.message });
                        throw err;
                    }
                }
            }));
        } catch (e) {
            console.error("Failed to add browser tools:", e.message);
        }

        // Configure Eko with Ollama (OpenAI-compatible provider)
        const OLLAMA_MODEL = process.env.EKO_MODEL || 'qwen3.5:latest';
        const OLLAMA_BASE = process.env.OLLAMA_BASE_URL || 'http://localhost:11434/v1';

        (async () => {
            // Keepalive ping every 15 s so the Python proxy and browser don't timeout
            // during the silent LLM planning phase
            const keepalive = setInterval(() => {
                if (!run.done) {
                    runEmitter.emit('update', { action: 'Planning', detail: 'Thinking...' });
                }
            }, 15000);

            try {
                runEmitter.emit('update', { status: 'running', action: 'Workflow Started', detail: description });

                const { Eko, Agent } = await import('@eko-ai/eko');

                // Wrap raw tool lists into proper Eko Agent instances
                const ekoAgents = [];
                if (pythonTools.length > 0) {
                    ekoAgents.push(new Agent({
                        name: 'CVResearch',
                        description: 'Computer vision research agent with access to specialized CV analysis, hardware probing, dataset management, and ML model tools.',
                        planDescription: 'CV research agent for analysis, dataset operations, and ML model management tasks.',
                        tools: pythonTools,
                    }));
                }
                if (browserTools.length > 0) {
                    ekoAgents.push(new Agent({
                        name: 'Browser',
                        description: 'Browser automation agent for web research: navigating websites, extracting page content, clicking elements, and taking screenshots.',
                        planDescription: 'Browser automation agent for web research and internet-based information gathering.',
                        tools: browserTools,
                    }));
                }

                const ekoConfig = {
                    llms: {
                        default: {
                            provider: 'openai-compatible',
                            model: OLLAMA_MODEL,
                            apiKey: 'ollama',           // Ollama doesn't need a real key
                            config: {
                                baseURL: OLLAMA_BASE,
                            },
                        },
                    },
                    agents: ekoAgents,
                    callback: {
                        onMessage: async (message) => {
                            if (message.type === 'workflow') {
                                // Only emit the final plan, not every streaming token
                                if (message.streamDone) {
                                    runEmitter.emit('update', {
                                        action: 'Workflow Plan',
                                        detail: 'Planning complete',
                                        workflow: message.workflow,
                                    });
                                }
                            } else if (message.type === 'agent_start') {
                                runEmitter.emit('update', {
                                    action: `Agent: ${message.agentName}`,
                                    detail: `Starting: ${message.agentNode?.task || ''}`,
                                });
                            } else if (message.type === 'agent_result') {
                                runEmitter.emit('update', {
                                    action: `Agent Done: ${message.agentName}`,
                                    detail: message.result ? message.result.substring(0, 200) : 'Completed',
                                });
                            } else if (message.type === 'tool_use') {
                                runEmitter.emit('update', {
                                    type: 'tool_start',
                                    action: `Tool: ${message.toolName}`,
                                    tool: message.toolName,
                                    tool_input: message.params,
                                });
                            } else if (message.type === 'tool_result') {
                                runEmitter.emit('update', {
                                    type: 'tool_end',
                                    action: `Tool Done: ${message.toolName}`,
                                    detail: typeof message.toolResult === 'string'
                                        ? message.toolResult.substring(0, 200)
                                        : JSON.stringify(message.toolResult).substring(0, 200),
                                });
                            } else if (message.type === 'text') {
                                if (message.streamDone && message.text) {
                                    runEmitter.emit('update', {
                                        action: 'LLM Response',
                                        detail: String(message.text).substring(0, 300),
                                    });
                                }
                            } else if (message.type === 'error') {
                                runEmitter.emit('update', {
                                    action: 'Error',
                                    detail: String(message.error),
                                });
                            }
                        },
                    },
                };

                runEmitter.emit('update', { action: 'Initializing', detail: `Using Ollama model: ${OLLAMA_MODEL}` });

                const eko = new Eko(ekoConfig);
                const result = await eko.run(description);

                if (result.success) {
                    runEmitter.emit('update', { status: 'completed', result: result.result });
                } else {
                    runEmitter.emit('update', { error: result.result || result.stopReason, status: 'failed' });
                }

            } catch (err) {
                console.error(`Error in run ${runId}:`, err);
                const errMsg = (err instanceof Error) ? err.message : String(err);
                runEmitter.emit('update', { error: errMsg || 'Unknown error', status: 'failed' });
            } finally {
                clearInterval(keepalive);
            }
        })();

    } catch (error) {
        console.error('Error running workflow:', error);
        res.status(500).json({ error: error.message });
    }
});

const server = app.listen(port, () => {
    console.log(`Eko Sidecar listening on port ${port}`);
});

server.on('error', (err) => {
    console.error('Server error:', err);
    process.exit(1);
});

// Keep the process alive
process.on('SIGINT', () => {
    console.log('Shutting down Eko Sidecar...');
    server.close();
    process.exit(0);
});
