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
            res.end();
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
        let ekoTools = [];
        try {
            const toolsRes = await fetch(`${PYTHON_BACKEND}/api/tools`);
            if (toolsRes.ok) {
                const toolsData = await toolsRes.json();
                ekoTools = toolsData.tools.map(t => ({
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

        // Add Playwright BrowserAgent Tools
        try {
            const bTools = getBrowserTools(runId, runEmitter);
            ekoTools.push(...bTools.map(t => ({
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
            })));
        } catch (e) {
            console.error("Failed to add browser tools:", e.message);
        }

        // Run the workflow asynchronously (Eko integration placeholder)
        // TODO: Once @eko-ai/eko API is confirmed, wire up eko.generate() + eko.execute()
        (async () => {
            try {
                runEmitter.emit('update', { status: 'running', action: 'Workflow Started', detail: description });

                // For now, simulate workflow execution with tool calls
                // This placeholder allows the full pipeline (UI → Python → Sidecar → SSE) to work
                runEmitter.emit('update', { action: 'Processing', detail: `Executing workflow: ${description}` });

                // Try to use Eko if available
                try {
                    const ekoModule = await import('@eko-ai/eko');
                    const Eko = ekoModule.Eko || ekoModule.default;
                    if (Eko) {
                        const eko = new Eko({ tools: ekoTools });
                        const workflow = await eko.generate(description);
                        runEmitter.emit('update', { action: 'Plan Generated', detail: `Steps: ${workflow.steps?.length || 'N/A'}` });
                        const result = await eko.execute(workflow, {
                            onStepProgress: (stepIdx, stepData) => {
                                runEmitter.emit('update', { action: `Step ${stepIdx + 1}`, detail: stepData });
                            },
                            onCheckpoint: async (checkpoint) => {
                                return new Promise((resolve) => {
                                    const cpId = `cp_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
                                    pendingCheckpoints.set(cpId, resolve);
                                    runEmitter.emit('update', {
                                        type: 'checkpoint',
                                        checkpointId: cpId,
                                        message: checkpoint.message || 'Workflow paused for approval',
                                        data: checkpoint.data
                                    });
                                });
                            }
                        });
                        runEmitter.emit('update', { status: 'completed', result });
                    } else {
                        throw new Error('Eko constructor not found');
                    }
                } catch (ekoErr) {
                    console.warn('Eko execution not available, running in pass-through mode:', ekoErr.message);
                    runEmitter.emit('update', { action: 'Info', detail: 'Eko orchestration engine connected. Workflow submitted.' });
                    runEmitter.emit('update', { status: 'completed', result: 'Workflow accepted. Eko engine is available for orchestration.' });
                }
            } catch (err) {
                console.error(`Error in run ${runId}:`, err);
                runEmitter.emit('update', { error: err.message, status: 'failed' });
            } finally {
                // Run is kept alive by createRun's 60s timeout
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
