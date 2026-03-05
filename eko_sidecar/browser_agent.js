import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let browser = null;
let page = null;

async function ensureBrowser() {
    if (!browser) {
        browser = await chromium.launch({ headless: true });
        const context = await browser.newContext();
        page = await context.newPage();
    }
    return page;
}

export function getBrowserTools(runId, runEmitter) {
    return [
        {
            name: 'browser_navigate',
            description: 'Navigate the browser to a given URL',
            parameters: {
                type: 'object',
                properties: {
                    url: { type: 'string', description: 'The absolute URL to navigate to (e.g., https://arxiv.org)' }
                },
                required: ['url']
            },
            execute: async ({ url }) => {
                const p = await ensureBrowser();
                await p.goto(url, { waitUntil: 'load' });
                return `Successfully navigated to ${url}. Title: ${await p.title()}`;
            }
        },
        {
            name: 'browser_extract_text',
            description: 'Extract visible text from the current browser page. Use this to read the page content.',
            parameters: { type: 'object', properties: {} },
            execute: async () => {
                const p = await ensureBrowser();
                return await p.evaluate(() => document.body.innerText.substring(0, 10000));
            }
        },
        {
            name: 'browser_click',
            description: 'Click an element on the page using a CSS selector',
            parameters: {
                type: 'object',
                properties: {
                    selector: { type: 'string', description: 'CSS selector of the element to click' }
                },
                required: ['selector']
            },
            execute: async ({ selector }) => {
                const p = await ensureBrowser();
                await p.click(selector);
                return `Clicked element matching selector: ${selector}`;
            }
        },
        {
            name: 'browser_screenshot',
            description: 'Take a screenshot of the current page to document visual state',
            parameters: { type: 'object', properties: {} },
            execute: async () => {
                const p = await ensureBrowser();
                const projectRoot = path.resolve(__dirname, '..');
                const outputDir = path.join(projectRoot, 'output', '.workflows', runId, 'screenshots');
                if (!fs.existsSync(outputDir)) {
                    fs.mkdirSync(outputDir, { recursive: true });
                }
                const filename = `shot_${Date.now()}.png`;
                const filepath = path.join(outputDir, filename);
                await p.screenshot({ path: filepath, fullPage: true });

                if (runEmitter) {
                    runEmitter.emit('update', {
                        type: 'screenshot',
                        action: 'Screenshot Taken',
                        url: `/output/.workflows/${runId}/screenshots/${filename}`,
                        detail: `Captured ${filename}`
                    });
                }

                return `Screenshot saved completely.`;
            }
        }
    ];
}

export async function closeBrowser() {
    if (browser) {
        await browser.close();
        browser = null;
        page = null;
    }
}
