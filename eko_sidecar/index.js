const express = require('express');
const { Eko } = require('@fellouai/eko');
const { getBrowserTools } = require('./browser_agent');

const app = express();
const port = 7862;

app.use(express.json());

const Emitter = require('events');
const activeRuns = new Map();
const pendingCheckpoints = new Map();

// Basic health check endpoint required by Python cv_agent
app.get('/health', (req, res) => {
    res.status(200).json({ status: 'ok', service: 'eko-sidecar' });
});

app.get('/workflow/:runId/stream', (req, res) => {
    const { runId } = req.params;

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');

    // Send initial connection heartbeat
    res.write(`data: ${JSON.stringify({ status: 'connected', runId })}\n\n`);

    const runEmitter = activeRuns.get(runId);
    if (!runEmitter) {
        res.write(`data: ${JSON.stringify({ error: 'Run ID not found or already completed', status: 'failed' })}\n\n`);
        return res.end();
    }

    const onUpdate = (data) => {
        res.write(`data: ${JSON.stringify(data)}\n\n`);
        if (data.status === 'completed' || data.error) {
            res.end();
        }
    };

    runEmitter.on('update', onUpdate);

    req.on('close', () => {
        if (runEmitter) {
            runEmitter.off('update', onUpdate);
        }
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
        const runEmitter = new Emitter();
        activeRuns.set(runId, runEmitter);

        res.status(202).json({
            message: 'Workflow accepted',
            runId: runId
        });

        // Fetch tools from Python backend bridging
        let ekoTools = [];
        try {
            const toolsRes = await fetch("http://127.0.0.1:8000/api/tools");
            if (toolsRes.ok) {
                const toolsData = await toolsRes.json();
                ekoTools = toolsData.tools.map(t => ({
                    name: t.name,
                    description: t.description,
                    parameters: t.parameters,
                    execute: async (args) => {
                        runEmitter.emit('update', { type: 'tool_start', action: `Executing ${t.name}`, tool: t.name, tool_input: args });
                        const res = await fetch("http://127.0.0.1:8000/api/tools/execute", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ name: t.name, arguments: args })
                        });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.error || "Tool execution failed");
                        runEmitter.emit('update', { type: 'tool_end', action: `Finished ${t.name}`, detail: "Success" });
                        return JSON.stringify(data.result);
                    }
                }));
            }
        } catch (e) {
            console.error("Failed to fetch python tools:", e);
        }

        // Add Playwright BrowserAgent Tools
        try {
            const bTools = getBrowserTools(runId, runEmitter);
            // Format for eko
            ekoTools.push(...bTools.map(t => ({
                name: t.name,
                description: t.description,
                parameters: t.parameters,
                execute: async (args) => {
                    runEmitter.emit('update', { type: 'tool_start', action: `Browser: ${t.name}`, tool: t.name, tool_input: args });
                    try {
                        const res = await t.execute(args);
                        runEmitter.emit('update', { type: 'tool_end', action: `Finished ${t.name}`, detail: res.substring(0, 100) });
                        return res;
                    } catch (err) {
                        runEmitter.emit('update', { type: 'tool_end', action: `Failed ${t.name}`, error: err.message });
                        throw err;
                    }
                }
            })));
        } catch (e) {
            console.error("Failed to add browser tools:", e);
        }

        // Initialize Eko Instance
        const eko = new Eko({
            tools: ekoTools
        });

        // Run Eko asynchronously 
        (async () => {
            try {
                runEmitter.emit('update', { status: 'running', action: 'Workflow Started', detail: description });

                // Call Eko to generate the workflow
                const workflow = await eko.generate(description);
                runEmitter.emit('update', { action: 'Plan Generated', detail: `Steps: ${workflow.steps.length}` });

                // Execute the workflow
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
            } catch (err) {
                console.error(`Error in run ${runId}:`, err);
                runEmitter.emit('update', { error: err.message, status: 'failed' });
            } finally {
                // Keep runEmitter briefly to ensure clients receive the final message
                setTimeout(() => {
                    activeRuns.delete(runId);
                }, 5000);
            }
        })();

    } catch (error) {
        console.error('Error running workflow:', error);
        res.status(500).json({ error: error.message });
    }
});

app.listen(port, () => {
    console.log(`Eko Sidecar listening on port ${port}`);
});
