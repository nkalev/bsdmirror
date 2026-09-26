/**
 * Does favicon.svg's dark-theme rule survive the production CSP header?
 *
 * favicon.svg keeps its light colours in presentation attributes and switches
 * to its dark tile with one `@media (prefers-color-scheme: dark)` rule in a
 * <style> element. nginx serves every file with `style-src 'self'`, which
 * blocks an inline <style> in a document. Whether Chromium applies an image's
 * own CSP header to the SVG it draws as that image is browser behaviour, so
 * this asks Chromium instead of reading a spec.
 *
 * It draws three copies as 64px <img>s on a mid-grey page whose colour scheme
 * is dark, with prefers-color-scheme emulated as dark, and reads back one
 * pixel of each tile:
 *   withCsp       the file, served with the production CSP header
 *   withoutCsp    the file, served without it: must read dark
 *   withoutStyle  the file without its <style>: must read light
 * The last two are the controls. Together they show that the sampled pixel is
 * on the tile and that a dark reading comes from the <style> rule. If either
 * control fails, the withCsp reading means nothing. A copy that did not draw
 * reads the grey page, which is neither tile. Before reading any pixel, the
 * harness checks that each copy arrived with the CSP header it stands for.
 *
 * No npm packages: node's built-in http, zlib and WebSocket only.
 *
 * Usage:  node favicon_harness.mjs <favicon.svg> <csp> [chrome-binary]
 * Output: JSON {"withCsp": [r, g, b, a], "withoutCsp": [...], "withoutStyle": [...]}
 */
import { createServer } from 'node:http';
import { readFile, mkdtemp } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { inflateSync } from 'node:zlib';
import path from 'node:path';

const SVG_PATH = path.resolve(process.argv[2]);
const CSP = process.argv[3];
const CHROME = process.argv[4]
    || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// How long Chrome gets to write DevToolsActivePort: the same limit and the
// same override as the other harnesses (tests/test_chrome_harness_start.py).
const DEFAULT_CHROME_START_TIMEOUT_MS = 30_000;
const CHROME_START_TIMEOUT_MS = Number(process.env.CHROME_START_TIMEOUT_MS) > 0
    ? Number(process.env.CHROME_START_TIMEOUT_MS)
    : DEFAULT_CHROME_START_TIMEOUT_MS;

// The Chrome this run started, so a failed run can stop it.
let chromeProcess = null;

// Each copy is drawn 64px square, so one CSS pixel is one unit of the
// favicon's 64-unit grid. (32, 6) is inside the tile, above the axis and clear
// of the edge and the glyph (design sections 4.5 and 4.6).
const SIZE = 64;
const SAMPLE = { x: 32, y: 6 };
const COPIES = ['withCsp', 'withoutCsp', 'withoutStyle'];

const PAGE = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="color-scheme" content="dark">
<style>
html, body { margin: 0; background: #808080; }
img { display: block; width: ${SIZE}px; height: ${SIZE}px; }
</style></head>
<body>${COPIES.map((copy) => `<img src="/${copy}/favicon.svg" alt="">`).join('')}</body></html>`;

function serve(svg) {
    const unstyled = Buffer.from(svg.toString('utf8').replace(/<style\b[^>]*>[\s\S]*?<\/style>/, ''));
    return new Promise((resolve) => {
        const server = createServer((req, res) => {
            const url = req.url.split('?')[0];
            if (url === '/page.html') {
                res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
                return res.end(PAGE);
            }
            const copy = COPIES.find((c) => url === `/${c}/favicon.svg`);
            if (copy) {
                const headers = { 'Content-Type': 'image/svg+xml' };
                if (copy === 'withCsp') headers['Content-Security-Policy'] = CSP;
                res.writeHead(200, headers);
                return res.end(copy === 'withoutStyle' ? unstyled : svg);
            }
            res.writeHead(404);
            return res.end();
        });
        server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
    });
}

// ---------------------------------------------------------------------------
// Minimal CDP client: csp_click_harness.mjs's, without its event handlers
// ---------------------------------------------------------------------------
class CDP {
    constructor(ws) {
        this.ws = ws;
        this.id = 0;
        this.pending = new Map();
        ws.addEventListener('message', (ev) => {
            const msg = JSON.parse(ev.data);
            if (msg.id && this.pending.has(msg.id)) {
                const { resolve, reject } = this.pending.get(msg.id);
                this.pending.delete(msg.id);
                msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
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
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(check, what, timeoutMs = 10_000) {
    const deadline = Date.now() + timeoutMs;
    while (!(await check())) {
        if (Date.now() > deadline) throw new Error(`timed out after ${timeoutMs}ms waiting for ${what}`);
        await sleep(50);
    }
}

/** [r, g, b, a] of a 1x1 PNG, as Page.captureScreenshot returns it. With no
 * pixel to the left or above, every PNG row filter leaves the bytes as they
 * are, so no unfiltering is needed. */
function onePixel(base64) {
    const png = Buffer.from(base64, 'base64');
    const idat = [];
    let channels = 0;
    for (let pos = 8; pos < png.length;) {
        const length = png.readUInt32BE(pos);
        const type = png.toString('latin1', pos + 4, pos + 8);
        const data = png.subarray(pos + 8, pos + 8 + length);
        if (type === 'IHDR') {
            if (data.readUInt32BE(0) !== 1 || data.readUInt32BE(4) !== 1 || data[8] !== 8) {
                throw new Error('expected a 1x1, 8-bit screenshot');
            }
            channels = { 2: 3, 6: 4 }[data[9]] ?? 0;
            if (!channels) throw new Error(`unexpected PNG colour type ${data[9]}`);
        } else if (type === 'IDAT') {
            idat.push(data);
        }
        pos += 12 + length;
    }
    const pixel = [...inflateSync(Buffer.concat(idat)).subarray(1, 1 + channels)];
    return channels === 3 ? [...pixel, 255] : pixel;
}

async function main() {
    const svg = await readFile(SVG_PATH);
    const { server, port } = await serve(svg);
    const userDataDir = await mkdtemp(path.join(tmpdir(), 'favicon-chrome-'));

    const chrome = spawn(CHROME, [
        '--headless=new',
        '--remote-debugging-port=0',
        `--user-data-dir=${userDataDir}`,
        '--no-first-run', '--no-default-browser-check',
        '--disable-gpu', '--disable-extensions', '--mute-audio', '--hide-scrollbars'
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
    chromeProcess = chrome;

    // Drain Chrome's stderr, keeping the tail for the error below. An unread
    // pipe can block Chrome before it ever writes DevToolsActivePort (see
    // csp_click_harness.mjs).
    let chromeStderr = '';
    chrome.stderr.setEncoding('utf8');
    chrome.stderr.on('data', (chunk) => {
        chromeStderr = (chromeStderr + chunk).slice(-8192);
    });

    let wsUrl = null;
    const deadline = Date.now() + CHROME_START_TIMEOUT_MS;
    while (!wsUrl && Date.now() < deadline) {
        await sleep(100);
        try {
            const portFile = path.join(userDataDir, 'DevToolsActivePort');
            const [p] = (await readFile(portFile, 'utf8')).split('\n');
            const version = await (await fetch(`http://127.0.0.1:${p}/json/version`)).json();
            wsUrl = version.webSocketDebuggerUrl;
        } catch { /* not up yet */ }
    }
    if (!wsUrl) {
        throw new Error(
            `Chrome did not expose a DevTools endpoint within ${CHROME_START_TIMEOUT_MS / 1000}s.\n` +
            '--- chrome stderr (tail) ---\n' + (chromeStderr || '(nothing on stderr)')
        );
    }

    const cdp = await CDP.connect(wsUrl);
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    const evaluate = async (expression) => {
        const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
            expression, awaitPromise: true, returnByValue: true
        }, sessionId);
        if (exceptionDetails) {
            throw new Error(`${expression}: ${exceptionDetails.exception?.description ?? exceptionDetails.text}`);
        }
        return result.value;
    };

    await cdp.send('Emulation.setEmulatedMedia', {
        features: [{ name: 'prefers-color-scheme', value: 'dark' }]
    }, sessionId);
    await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: 320, height: 240, deviceScaleFactor: 1, mobile: false
    }, sessionId);
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${port}/page.html` }, sessionId);
    await waitFor(
        () => evaluate(`document.readyState === 'complete' && document.images.length === ${COPIES.length}`),
        'the page to load'
    );
    // decode() rejects for an image that failed to load, so a broken file
    // fails here instead of being read as the page behind it.
    await evaluate('Promise.all([...document.images].map((img) => img.decode())).then(() => true)');

    // The copies differ only in what the server sends, so check that first: a
    // withCsp copy that arrived without its header would pass for nothing.
    const served = await evaluate(`Promise.all(${JSON.stringify(COPIES)}.map((copy) =>
        fetch('/' + copy + '/favicon.svg').then((r) => r.headers.get('content-security-policy'))))`);
    const expected = COPIES.map((copy) => (copy === 'withCsp' ? CSP : null));
    if (JSON.stringify(served) !== JSON.stringify(expected)) {
        throw new Error(`the copies arrived with the wrong CSP headers: ${JSON.stringify(served)}`);
    }

    const pixels = {};
    for (const [index, copy] of COPIES.entries()) {
        const { data } = await cdp.send('Page.captureScreenshot', {
            format: 'png',
            clip: { x: SAMPLE.x, y: index * SIZE + SAMPLE.y, width: 1, height: 1, scale: 1 }
        }, sessionId);
        pixels[copy] = onePixel(data);
    }
    process.stdout.write(JSON.stringify(pixels) + '\n');

    chrome.kill();
    server.close();
    process.exit(0);
}

main().catch((err) => {
    process.stderr.write(String(err && err.stack ? err.stack : err) + '\n');
    chromeProcess?.kill();
    process.exit(1);
});
