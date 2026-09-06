/**
 * Dynamic half of the WCAG contrast guard (tests/test_contrast.py).
 *
 * test_contrast.py's parametrized checks read style.css/admin.css/tokens.css
 * as text and do the WCAG relative-luminance arithmetic themselves. That
 * proves the declared values are compliant; it does not prove a real engine's
 * cascade resolves each element to the colour the text-only parser assumed --
 * the same gap test_public_page_csp.py's harness exists to close for the CSP
 * (reading finds an onclick attribute that looks like working code; it took a
 * real browser to show the policy killed it).
 *
 * This harness serves frontend/public over plain HTTP (no CSP -- that is a
 * different test's job), drives real headless Chrome over the DevTools
 * Protocol, and reads `getComputedStyle(...).color` /
 * `...backgroundColor` for the same elements test_contrast.py reasons about
 * statically. Two pages are covered:
 *
 *   - the public site, both themes, toggled with a genuine click on
 *     #themeToggle (not by setting the attribute from here) so the real
 *     ThemeManager code path is exercised;
 *   - a synthetic admin fixture: admin.js's own page-renderer functions
 *     (renderLoginPage, renderLayout, renderUsers, renderMirrors), loaded
 *     into a vm context exactly the way tests/js/escaping_harness.mjs does,
 *     called for their real HTML output, and dropped into a page that links
 *     the real admin.css/tokens.css/fonts.css. The admin SPA needs a live
 *     backend to reach these views by clicking through the app; calling the
 *     renderers directly gets the real markup without one, the same
 *     trade-off escaping_harness.mjs already makes.
 *
 * :hover states (.nav-link:hover, .btn-secondary:hover) are reached with a
 * genuine Input.dispatchMouseEvent mousemove, not a CSS class toggle, so the
 * browser's own hit-testing decides whether the pseudo-class applies.
 *
 * No npm packages: node's built-in http/vm/WebSocket only, and whatever
 * Chrome is already installed. getComputedStyle always resolves to
 * rgb()/rgba() regardless of how the source declared the colour; the
 * WCAG maths (and any alpha compositing) is left to the Python side so there
 * is exactly one implementation of it across both the static and dynamic
 * checks.
 *
 * Usage:  node contrast_harness.mjs <docroot> <admin-js-path> [chrome-binary]
 * Output: JSON {"public": {...}, "admin": {...}} on stdout.
 */
import { createServer } from 'node:http';
import { readFile, mkdtemp, readFile as rf } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import vm from 'node:vm';

const DOCROOT = path.resolve(process.argv[2]);
const ADMIN_JS_PATH = path.resolve(process.argv[3]);
const CHROME = process.argv[4]
    || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
    '.json': 'application/json'
};

// ---------------------------------------------------------------------------
// admin.js's real page renderers, loaded the way escaping_harness.mjs does
// ---------------------------------------------------------------------------
function loadAdminRenderers(sourcePath) {
    const source = readFileSync(sourcePath, 'utf8');
    const sandbox = {
        console,
        setTimeout: () => 0,
        setInterval: () => 0,
        clearTimeout: () => {},
        document: {
            addEventListener: () => {},
            getElementById: () => null,
            createElement: () => ({ style: {}, remove() {} })
        },
        window: { addEventListener() {}, history: { pushState() {} }, location: { hash: '' } },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        fetch: async () => { throw new Error('network disabled in harness'); }
    };
    sandbox.globalThis = sandbox;
    const epilogue = `
;({ html, renderLoginPage, renderLayout, renderUsers, renderMirrors, state, api });
`;
    return vm.runInNewContext(source + epilogue, sandbox, { filename: sourcePath });
}

/** Mocks api.get for the duration of one async renderer call, as
 * escaping_harness.mjs's renderWith does, then returns the rendered string. */
async function renderWith(mod, fn, payload) {
    mod.api.get = async () => payload;
    return String(await fn());
}

function buildAdminFixtureHtml(mod) {
    const login = String(mod.renderLoginPage());

    mod.state.user = { id: 1, username: 'alice-admin', role: 'admin' };
    mod.state.currentPage = 'dashboard';
    const layout = String(mod.renderLayout(mod.html`<p>fixture</p>`, 'Dashboard'));

    // Deferred: renderWith is async and buildAdminFixtureHtml is not, so the
    // two table renders are produced by the caller and passed in instead.
    return { login, layout };
}

// ---------------------------------------------------------------------------
// Static + synthetic-fixture server
// ---------------------------------------------------------------------------
function serve(fixtureHtml) {
    return new Promise((resolve) => {
        const server = createServer(async (req, res) => {
            const url = req.url.split('?')[0];
            if (url === '/__admin_fixture__.html') {
                res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
                return res.end(fixtureHtml);
            }
            let rel = decodeURIComponent(url);
            if (rel.endsWith('/')) rel += 'index.html';
            const file = path.join(DOCROOT, path.normalize(rel));
            if (!file.startsWith(DOCROOT) || !existsSync(file)) {
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
// Minimal CDP client (identical shape to csp_click_harness.mjs's)
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

async function launchChrome() {
    const userDataDir = await mkdtemp(path.join(tmpdir(), 'contrast-chrome-'));
    const chrome = spawn(CHROME, [
        '--headless=new',
        '--remote-debugging-port=0',
        `--user-data-dir=${userDataDir}`,
        '--no-first-run', '--no-default-browser-check',
        '--disable-gpu', '--disable-extensions', '--mute-audio'
    ], { stdio: ['ignore', 'ignore', 'pipe'] });

// Chrome's stderr is piped, so SOMETHING has to read it.
//
// An unread pipe fills at roughly 64KB on Linux, and a process that fills it
// blocks on write() until someone drains it. A chatty headless Chrome -- which
// is what a loaded CI runner produces, between GPU, sandbox and font warnings
// -- can therefore block BEFORE it writes DevToolsActivePort, and the loop
// below then times out with "Chrome did not expose a DevTools endpoint" while
// Chrome sits alive and stuck. That is not a flake; it is this function
// holding the pipe shut.
//
// Draining also gives the failure something to say. The old error threw away
// everything Chrome had written, so a real crash and a slow start were
// indistinguishable in CI logs. Both harnesses had this; this one was simply
// the first to lose the race.
    let chromeStderr = '';
    chrome.stderr.setEncoding('utf8');
    chrome.stderr.on('data', (chunk) => {
        // Bounded: keep the tail. An unbounded buffer would just move the
        // memory problem here from the kernel's pipe.
        chromeStderr = (chromeStderr + chunk).slice(-8192);
    });

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
    if (!wsUrl) {
        throw new Error(
            'Chrome did not expose a DevTools endpoint within 10s.\n' +
            '--- chrome stderr (tail) ---\n' + (chromeStderr || '(nothing on stderr)')
        );
    }
    const cdp = await CDP.connect(wsUrl);
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: 1400, height: 4200, deviceScaleFactor: 1, mobile: false
    }, sessionId);
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    return { chrome, cdp, sessionId };
}

async function navigate(cdp, sessionId, url) {
    const loaded = new Promise((resolve) => {
        const handler = (raw) => {
            const msg = JSON.parse(raw.data ?? '{}');
            if (msg.method === 'Page.loadEventFired') resolve();
        };
        cdp.ws.addEventListener('message', handler, { once: false });
    });
    await cdp.send('Page.navigate', { url }, sessionId);
    // Page.navigate resolves on commit, not load; a short poll is simpler and
    // more robust here than wiring up a one-shot event listener per call.
    for (let i = 0; i < 50; i++) {
        const { result } = await cdp.send('Runtime.evaluate', {
            expression: 'document.readyState', returnByValue: true
        }, sessionId);
        if (result.value === 'complete') break;
        await sleep(50);
    }
    await sleep(150);
}

function makeEvaluate(cdp, sessionId) {
    return async (expression) => {
        const r = await cdp.send('Runtime.evaluate', {
            expression, returnByValue: true, awaitPromise: true
        }, sessionId);
        if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
        return r.result.value;
    };
}

/** getComputedStyle(color) for `selector`, and (backgroundColor) for
 * `bgSelector` (a different element when the probed element's own background
 * is transparent and the ambient colour comes from an ancestor). If `hover`,
 * a real mouse is moved onto `selector` first. */
async function measure(cdp, sessionId, evaluate, { selector, bgSelector, hover }) {
    // Park the pointer off-page first so no previous probe's hover lingers.
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 0, y: 0 }, sessionId);

    if (hover) {
        const box = await evaluate(`(() => {
            const el = document.querySelector(${JSON.stringify(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        })()`);
        if (!box) return { error: `no element for ${selector}` };
        await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y }, sessionId);
        // Hover-triggered colour/background changes run through `transition:
        // all var(--transition-fast)` (150ms). Sampling mid-transition once
        // measured a background partway between rest and hover state, which
        // is a real value no user ever reads a colour off -- settle first.
        await sleep(250);
    }

    return evaluate(`(() => {
        const fg = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!fg || !bg) return { error: 'element(s) not found: ' +
            (!fg ? ${JSON.stringify(selector)} : ${JSON.stringify(bgSelector)}) };
        return {
            color: getComputedStyle(fg).color,
            backgroundColor: getComputedStyle(bg).backgroundColor
        };
    })()`);
}

// ---------------------------------------------------------------------------
// Probe lists -- mirrors the selectors test_contrast.py reasons about
// statically. Keep the two in step; a mismatch is not caught automatically.
// ---------------------------------------------------------------------------
const PUBLIC_PROBES = [
    { id: 'body', selector: 'body', bgSelector: 'body' },
    { id: '.nav-link', selector: '.nav-link:not(.nav-admin)', bgSelector: '.header' },
    { id: '.nav-link:hover', selector: '.nav-link:not(.nav-admin)', bgSelector: '.nav-link:not(.nav-admin)', hover: true },
    { id: '.nav-admin', selector: '.nav-admin', bgSelector: '.header' },
    { id: '.stat-label', selector: '.stat-label', bgSelector: '.stat-card' },
    { id: '.mirror-status', selector: '.mirror-status', bgSelector: '.mirror-card' },
    { id: '.detail-label', selector: '.detail-label', bgSelector: '.mirror-details' },
    { id: '.btn-primary', selector: '.mirror-actions .btn-primary', bgSelector: '.mirror-actions .btn-primary' },
    { id: '.btn-secondary:hover', selector: '.mirror-actions .btn-secondary', bgSelector: '.mirror-actions .btn-secondary', hover: true },
    { id: '.footer-content p', selector: '.footer-content p:not(.footer-version)', bgSelector: '.footer' },
    { id: '.footer-version', selector: '.footer-version', bgSelector: '.footer' },
    { id: '.method-card p', selector: '.method-card p', bgSelector: '.method-card' }
];

const ADMIN_PROBES = [
    { id: '.login-subtitle', selector: '#login-fixture .login-subtitle', bgSelector: '#login-fixture .login-card' },
    { id: '.btn-primary', selector: '#login-fixture .btn-primary', bgSelector: '#login-fixture .btn-primary' },
    { id: '.nav-item.active', selector: '#layout-fixture .nav-item.active', bgSelector: '#layout-fixture .nav-item.active' },
    { id: '.user-avatar', selector: '#layout-fixture .user-avatar', bgSelector: '#layout-fixture .user-avatar' },
    { id: '.user-role', selector: '#layout-fixture .user-role', bgSelector: '#layout-fixture .user-info' },
    { id: '.nav-section-title', selector: '#layout-fixture .nav-section-title', bgSelector: '#layout-fixture .sidebar' },
    { id: '.status-badge.disabled', selector: '#users-fixture .status-badge.disabled', bgSelector: '#users-fixture .status-badge.disabled' },
    { id: '.status-badge.active', selector: '#users-fixture .status-badge.active', bgSelector: '#users-fixture .status-badge.active' },
    { id: 'th', selector: '#users-fixture th', bgSelector: '#users-fixture th' },
    { id: '.u-text-muted', selector: '#mirrors-fixture .u-text-muted', bgSelector: '#mirrors-fixture .card' },
    { id: '.status-badge.error', selector: '#mirrors-fixture .status-badge.error', bgSelector: '#mirrors-fixture .status-badge.error' },
    { id: '.status-badge.syncing', selector: '#mirrors-fixture .status-badge.syncing', bgSelector: '#mirrors-fixture .status-badge.syncing' }
];

/** ::placeholder is a pseudo-element, not reachable through the plain
 * (element, property) probe shape above. Chrome supports the two-argument
 * form of getComputedStyle for it; measured separately for that reason, with
 * a clearly-labelled error (rather than a silent skip) if a given Chrome
 * build does not support it -- test_contrast.py treats a missing/errored
 * measurement as "not dynamically confirmed" and falls back to its static
 * coverage of the same pairing, but it needs to see why. */
async function measurePlaceholder(evaluate, selector, bgSelector) {
    return evaluate(`(() => {
        const input = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!input || !bg) return { error: 'element(s) not found' };
        const style = getComputedStyle(input, '::placeholder');
        const color = style && style.color;
        if (!color) return { error: 'getComputedStyle(el, "::placeholder") returned no colour in this Chrome build' };
        return { color, backgroundColor: getComputedStyle(bg).backgroundColor };
    })()`);
}

async function main() {
    const mod = loadAdminRenderers(ADMIN_JS_PATH);
    const { login, layout } = buildAdminFixtureHtml(mod);
    const usersHtml = await renderWith(mod, mod.renderUsers, [
        { id: 1, username: 'rita', email: 'rita@example.test', role: 'readonly', is_active: false, last_login: null },
        { id: 2, username: 'alice', email: 'alice@example.test', role: 'admin', is_active: true, last_login: null }
    ]);
    const mirrorsHtml = await renderWith(mod, mod.renderMirrors, [
        {
            id: 1, name: 'OpenBSD', url_path: '/OpenBSD/', status: 'error',
            total_size_human: '1 GB', last_sync_completed: null
        },
        {
            id: 2, name: 'NetBSD', url_path: '/NetBSD/', status: 'syncing',
            total_size_human: '2 GB', last_sync_completed: null
        }
    ]);

    const fixtureHtml = `<!DOCTYPE html>
<html data-theme="dark" data-surface="admin">
<head>
<meta charset="UTF-8">
<link rel="stylesheet" href="/css/fonts.css">
<link rel="stylesheet" href="/css/tokens.css">
<link rel="stylesheet" href="/admin/css/admin.css">
</head>
<body>
<div id="login-fixture">${login}</div>
<div id="layout-fixture">${layout}</div>
<div id="users-fixture">${usersHtml}</div>
<div id="mirrors-fixture">${mirrorsHtml}</div>
</body>
</html>`;

    const { server, port } = await serve(fixtureHtml);
    const origin = `http://127.0.0.1:${port}`;
    const { chrome, cdp, sessionId } = await launchChrome();
    const evaluate = makeEvaluate(cdp, sessionId);

    const out = { public: { light: {}, dark: {} }, admin: {} };

    await navigate(cdp, sessionId, `${origin}/index.html`);
    for (const probe of PUBLIC_PROBES) {
        out.public.light[probe.id] = await measure(cdp, sessionId, evaluate, probe);
    }

    // A genuine click on the real toggle button, not setAttribute from here.
    const toggleBox = await evaluate(`(() => {
        const b = document.getElementById('themeToggle');
        const r = b.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    })()`);
    for (const type of ['mousePressed', 'mouseReleased']) {
        await cdp.send('Input.dispatchMouseEvent', {
            type, x: toggleBox.x, y: toggleBox.y, button: 'left', clickCount: 1
        }, sessionId);
    }
    // body's colour/background-color transition runs through
    // --transition-base (300ms); 150ms here once sampled a colour partway
    // through the fade (a real computed value, but not the settled one this
    // harness means to check) -- settle well past it before reading anything.
    await sleep(450);
    const theme = await evaluate('document.documentElement.getAttribute("data-theme")');
    if (theme !== 'dark') throw new Error(`clicking #themeToggle did not set data-theme=dark (got ${theme})`);

    for (const probe of PUBLIC_PROBES) {
        out.public.dark[probe.id] = await measure(cdp, sessionId, evaluate, probe);
    }

    await navigate(cdp, sessionId, `${origin}/__admin_fixture__.html`);
    for (const probe of ADMIN_PROBES) {
        out.admin[probe.id] = await measure(cdp, sessionId, evaluate, probe);
    }
    out.admin['.form-input::placeholder'] = await measurePlaceholder(
        evaluate, '#login-fixture .form-input', '#login-fixture .form-input'
    );

    process.stdout.write(JSON.stringify(out, null, 2) + '\n');
    chrome.kill();
    server.close();
    process.exit(0);
}

main().catch((err) => {
    process.stderr.write(String(err && err.stack ? err.stack : err) + '\n');
    process.exit(1);
});
