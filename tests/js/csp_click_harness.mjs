/**
 * Does clicking "Copy rsync URL" do anything, under the production CSP?
 *
 * Static inspection is what missed this bug in the first place -- an
 * onclick="..." attribute looks like working code -- so this harness does not
 * inspect. It serves frontend/public over HTTP with the exact
 * Content-Security-Policy from nginx/nginx.conf, drives real headless Chrome
 * over the DevTools Protocol, dispatches a genuine trusted mouse click on each
 * button, and reports what the page did.
 *
 * No npm packages: node's built-in http and WebSocket only, and whatever
 * Chrome is already installed.
 *
 * Usage:  node csp_click_harness.mjs <docroot> [chrome-binary]
 * Output: JSON {"buttons":[...], "cspViolations":[...]} on stdout.
 */
import { createServer } from 'node:http';
import { readFile, mkdtemp, readFile as rf } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';

const DOCROOT = path.resolve(process.argv[2]);
const CHROME = process.argv[3]
    || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// Copied verbatim from the `map $host $csp_policy` block in nginx/nginx.conf.
// If that string changes, this test is testing the wrong policy.
const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; "
    + "img-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; "
    + "frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'";

const MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
    '.json': 'application/json'
};

// ---------------------------------------------------------------------------
// Static server, CSP on every response, exactly as nginx sends it.
// ---------------------------------------------------------------------------
function serve() {
    return new Promise((resolve) => {
        const server = createServer(async (req, res) => {
            let rel = decodeURIComponent(req.url.split('?')[0]);
            if (rel.endsWith('/')) rel += 'index.html';
            const file = path.join(DOCROOT, path.normalize(rel));
            res.setHeader('Content-Security-Policy', CSP);
            if (!file.startsWith(DOCROOT) || !existsSync(file)) {
                // The status API is not under test; return an empty payload so
                // MirrorStatus.load() fails quietly instead of throwing.
                if (rel.startsWith('/api/')) {
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    return res.end('{"mirrors":{},"totals":{}}');
                }
                res.writeHead(404);
                return res.end('not found');
            }
            res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
            res.end(await readFile(file));
        });
        server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
    });
}

// ---------------------------------------------------------------------------
// Minimal CDP client
// ---------------------------------------------------------------------------
class CDP {
    constructor(ws) {
        this.ws = ws;
        this.id = 0;
        this.pending = new Map();
        this.handlers = [];
        ws.addEventListener('message', (ev) => {
            const msg = JSON.parse(ev.data);
            if (msg.id && this.pending.has(msg.id)) {
                const { resolve, reject } = this.pending.get(msg.id);
                this.pending.delete(msg.id);
                msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
            } else if (msg.method) {
                for (const h of this.handlers) h(msg);
            }
        });
    }

    static connect(url) {
        return new Promise((resolve, reject) => {
            const ws = new WebSocket(url);
            ws.addEventListener('open', () => resolve(new CDP(ws)));
            ws.addEventListener('error', reject);
        });
    }

    send(method, params = {}, sessionId) {
        const id = ++this.id;
        this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
        return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    }

    on(fn) { this.handlers.push(fn); }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
    const { server, port } = await serve();
    const origin = `http://127.0.0.1:${port}`;
    const userDataDir = await mkdtemp(path.join(tmpdir(), 'csp-chrome-'));

    const chrome = spawn(CHROME, [
        '--headless=new',
        '--remote-debugging-port=0',
        `--user-data-dir=${userDataDir}`,
        '--no-first-run', '--no-default-browser-check',
        '--disable-gpu', '--disable-extensions', '--mute-audio'
    ], { stdio: ['ignore', 'ignore', 'pipe'] });

    // Chrome writes the port it actually chose here.
    let wsUrl = null;
    for (let i = 0; i < 100 && !wsUrl; i++) {
        await sleep(100);
        try {
            const portFile = path.join(userDataDir, 'DevToolsActivePort');
            const [p] = (await rf(portFile, 'utf8')).split('\n');
            const version = await (await fetch(`http://127.0.0.1:${p}/json/version`)).json();
            wsUrl = version.webSocketDebuggerUrl;
        } catch { /* not up yet */ }
    }
    if (!wsUrl) throw new Error('Chrome did not expose a DevTools endpoint');

    const cdp = await CDP.connect(wsUrl);
    await cdp.send('Browser.grantPermissions', {
        origin, permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite']
    });

    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });

    const cspViolations = [];
    const consoleErrors = [];
    cdp.on((msg) => {
        if (msg.method === 'Log.entryAdded') {
            const e = msg.params.entry;
            const text = e.text || '';
            if (/Content Security Policy/i.test(text)) cspViolations.push(text);
            else if (e.level === 'error') consoleErrors.push(text);
        }
    });

    // A viewport tall enough to hold the whole page. style.css sets
    // `scroll-behavior: smooth`, so scrollIntoView() animates and any rect read
    // straight after it is stale -- which lands the click on empty space.
    // Not scrolling at all sidesteps that entirely.
    await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: 1400, height: 4200, deviceScaleFactor: 1, mobile: false
    }, sessionId);

    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    await cdp.send('Log.enable', {}, sessionId);

    const loaded = new Promise((resolve) => {
        cdp.on((m) => { if (m.method === 'Page.loadEventFired') resolve(); });
    });
    await cdp.send('Page.navigate', { url: `${origin}/index.html` }, sessionId);
    await loaded;
    await sleep(400);

    const evaluate = async (expression) => {
        const r = await cdp.send('Runtime.evaluate', {
            expression, returnByValue: true, awaitPromise: true
        }, sessionId);
        if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
        return r.result.value;
    };

    // How is each button wired, as the page actually sees it?
    const wiring = await evaluate(`
        Array.from(document.querySelectorAll('.mirror-actions button')).map(b => ({
            label: b.textContent.trim(),
            onclickAttr: b.getAttribute('onclick'),
            onclickCompiled: typeof b.onclick,
            dataAttr: b.dataset.copyRsync ?? null
        }))
    `);

    const buttons = [];
    for (let i = 0; i < wiring.length; i++) {
        // Clear the toast so each click is measured independently.
        await evaluate(`(() => { const t = document.getElementById('toast');
                                 if (t) { t.textContent = ''; t.classList.remove('show'); } })()`);

        const box = await evaluate(`(() => {
            const b = document.querySelectorAll('.mirror-actions button')[${i}];
            b.scrollIntoView({ block: 'center', behavior: 'instant' });
            const r = b.getBoundingClientRect();
            const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return {
                x: r.x + r.width / 2, y: r.y + r.height / 2,
                // If the click point is not on the button, the click proves
                // nothing -- surface that rather than reporting "no toast".
                hits: Boolean(el) && Boolean(el.closest('[data-copy-rsync], button'))
            };
        })()`);
        if (!box.hits) throw new Error(`button ${i} is not under its own click point (${box.x}, ${box.y})`);

        // A real trusted click, not element.click(): inline handlers and
        // addEventListener listeners are both reached this way, and the
        // clipboard API needs the user activation it grants.
        for (const type of ['mousePressed', 'mouseReleased']) {
            await cdp.send('Input.dispatchMouseEvent', {
                type, x: box.x, y: box.y, button: 'left', clickCount: 1
            }, sessionId);
        }
        await sleep(350);

        const toast = await evaluate(`(() => { const t = document.getElementById('toast');
            return t ? { text: t.textContent, shown: t.classList.contains('show') } : null; })()`);

        buttons.push({ ...wiring[i], toast });
    }

    process.stdout.write(JSON.stringify({
        docroot: DOCROOT, csp: CSP, buttons, cspViolations, consoleErrors
    }, null, 2) + '\n');

    chrome.kill();
    server.close();
    process.exit(0);
}

main().catch((err) => {
    process.stderr.write(String(err && err.stack ? err.stack : err) + '\n');
    process.exit(1);
});
