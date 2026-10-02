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
 * This harness serves frontend/public over plain HTTP (no CSP, except on the
 * admin fixture pages below -- the public site's CSP is a different test's
 * job), drives real headless Chrome over the DevTools
 * Protocol, and reads `getComputedStyle(...).color` /
 * `...backgroundColor` for the same elements test_contrast.py reasons about
 * statically. Two pages are covered:
 *
 *   - the public site, both themes, toggled with a genuine click on
 *     #themeToggle (not by setting the attribute from here) so the real
 *     ThemeManager code path is exercised;
 *   - a synthetic admin fixture: admin.js's own page-renderer functions
 *     (renderLoginPage, renderLayout, renderUsers, renderMirrors,
 *     renderDashboard), loaded into a vm context exactly the way
 *     tests/js/escaping_harness.mjs does, called for their real HTML output,
 *     and dropped into a page that links the real admin.css/tokens.css/
 *     fonts.css. The admin SPA needs a live backend to reach these views by
 *     clicking through the app; calling the renderers directly gets the real
 *     markup without one, the same trade-off escaping_harness.mjs already
 *     makes. The admin console now follows the same saved light/dark choice
 *     as the public site (spec section 6.2), so this same rendered markup is
 *     served twice, as two separate documents each with its own <html
 *     data-surface="admin"> (light) or <html data-theme="dark"
 *     data-surface="admin"> (dark) -- a real navigation to each, not a class
 *     toggle on one shared page, since data-theme is an attribute of <html>
 *     itself. Both pages are served with the Content-Security-Policy that
 *     nginx/nginx.conf sends (read from that file, not copied), and every
 *     violation Chrome reports while one loads and is measured is collected
 *     and returned in the output's "csp" key. A third page, the light fixture
 *     with one inline style attribute added, is the control: style-src 'self'
 *     must refuse it, or the collector cannot be trusted to notice anything.
 *     The fixture pages hold rendered markup and link the real stylesheets, so
 *     this covers markup, CSS, fonts and mask images; no script runs in them.
 *
 * :hover states (.nav-link:hover, .btn-secondary:hover) are reached with a
 * genuine Input.dispatchMouseEvent mousemove, not a CSS class toggle, so the
 * browser's own hit-testing decides whether the pseudo-class applies.
 *
 * The public site's mirror status is data-state-keyed (main.js writes one
 * attribute per element; nothing here reads a class -- spec section 5.2).
 * The /api/ stub below seeds one mirror of each live state (FreeBSD online,
 * NetBSD syncing, OpenBSD error), which the harness waits for by polling the
 * real, stub-driven attribute values -- proving the real end-to-end paint,
 * not just that some element exists. The neutral pill and three of the four
 * status-dot states are not reachable through any single stub response (the
 * overall card's data-state is one value at a time), so for those the
 * harness sets data-state on the element itself immediately before
 * measuring it, always AFTER that same element's naturally-stubbed
 * measurement has already been taken -- CSS keys purely off the attribute,
 * so this is exactly the cascade test_contrast.py's static half assumes,
 * just reached a different way. Every element visited this way is
 * re-measured fresh in each theme pass (see measurePublicProbes()), so a
 * light-pass override is never still sitting there when the dark pass reads
 * the same element "naturally".
 *
 * Colour/background-color changes on data-state (or class, or :hover) run
 * through a CSS transition (--transition-fast, 150ms) -- a probe taken
 * mid-fade once measured a pill's neutral colours moments after main.js had
 * already set it to "online". Rather than guess a settle delay per probe,
 * launchChrome() emulates `prefers-reduced-motion: reduce` for the whole
 * session: style.css's own reduced-motion block (`transition: none
 * !important` on `*, *::before, *::after`) then makes every one of these
 * changes apply instantly, so getComputedStyle -- which forces a synchronous
 * style recalculation regardless -- always reads the settled value with no
 * wait at all. The 250ms hover settle and 450ms theme-switch wait stay as
 * extra margin for the real event/click plumbing, not because a colour
 * fade needs time to finish any more.
 *
 * Also fails loudly, instead of silently reporting whatever partial
 * measurements it collected, if the public page raises an uncaught JS error
 * or an unhandled promise rejection at any point: a main.js write that
 * throws may break nothing a probe measures, so nothing else here would
 * notice it. Runtime.exceptionThrown reports both categories once
 * Runtime.enable is on; console.error() calls are also treated as failures.
 * waitFor() checks on every poll, and main() once more at the end; see
 * checkForPageErrors().
 *
 * No npm packages: node's built-in http/vm/WebSocket only, and whatever
 * Chrome is already installed. getComputedStyle always resolves to
 * rgb()/rgba() regardless of how the source declared the colour; the
 * WCAG maths (and any alpha compositing) is left to the Python side so there
 * is exactly one implementation of it across both the static and dynamic
 * checks.
 *
 * Usage:  node contrast_harness.mjs <docroot> <admin-js-path> [chrome-binary]
 * Output: JSON {"public": {...}, "admin": {...}, "csp": {...}} on stdout. A CSP
 *         violation is reported there, never a reason to exit non-zero:
 *         tests/test_contrast.py pins the lists, and its negative controls
 *         need them returned.
 */
import { createServer } from 'node:http';
import { readFile, mkdtemp, readFile as rf } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const DOCROOT = path.resolve(process.argv[2]);
const ADMIN_JS_PATH = path.resolve(process.argv[3]);
const CHROME = process.argv[4]
    || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// How long Chrome gets to write DevToolsActivePort. It was a fixed 10 s until a
// cold start on a GitHub-hosted runner outlasted it and failed every
// real-browser test at setup (2026-09-25). CHROME_START_TIMEOUT_MS overrides
// it; tests/test_chrome_harness_start.py uses that to reach the failure fast.
const DEFAULT_CHROME_START_TIMEOUT_MS = 30_000;
const CHROME_START_TIMEOUT_MS = Number(process.env.CHROME_START_TIMEOUT_MS) > 0
    ? Number(process.env.CHROME_START_TIMEOUT_MS)
    : DEFAULT_CHROME_START_TIMEOUT_MS;

// The Chrome this run started, so a run that fails can stop it rather than
// leave it running into whatever runs next.
let chromeProcess = null;

// The policy the admin fixture pages are served under: the single `map $host
// $csp_policy` default in nginx/nginx.conf, read here rather than copied, so
// the pages can never be checked against a policy nobody serves.
// tests/test_contrast.py compares what this reads with its own reading of the
// same file. Found relative to this file, not the working directory, because
// the harness is always run from the repository.
const NGINX_CONF = fileURLToPath(new URL('../../nginx/nginx.conf', import.meta.url));

function productionCsp() {
    const conf = readFileSync(NGINX_CONF, 'utf8');
    const block = conf.match(/map\s+\$host\s+\$csp_policy\s*\{([\s\S]*?)\}/);
    if (!block) throw new Error(`no \`map $host $csp_policy\` block in ${NGINX_CONF}`);
    const value = block[1].match(/default\s+"([^"]+)"/);
    if (!value) throw new Error(`no default value in the $csp_policy map in ${NGINX_CONF}`);
    return value[1];
}

const CSP = productionCsp();

const MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
    '.json': 'application/json'
};

// ---------------------------------------------------------------------------
// admin.js's real page renderers, loaded the way escaping_harness.mjs does.
// Unchanged by the public palette switch.
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
;({ html, renderLoginPage, renderLayout, renderUsers, renderMirrors, renderDashboard, state, api });
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
    // table and dashboard renders are produced by the caller and passed in
    // instead.
    return { login, layout };
}

/** One <html>-level page embedding the same five rendered fragments, for a
 * given theme: data-surface="admin" always; data-theme="light"/"dark" set
 * explicitly, exactly as AdminTheme.apply() does in the real console (spec
 * section 6.2) -- tokens.css has no [data-theme="light"] rule, so this
 * matches the light state whether the attribute is set or left off, and
 * setting it explicitly is what a real page after a real toggle click
 * actually carries. */
function buildAdminFixturePage(theme, fragments) {
    const { login, layout, usersHtml, mirrorsHtml, dashboardHtml } = fragments;
    return `<!DOCTYPE html>
<html data-theme="${theme}" data-surface="admin">
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
<div id="dashboard-fixture">${dashboardHtml}</div>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Static + synthetic-fixture server
// ---------------------------------------------------------------------------
function serve(fixturePages) {
    return new Promise((resolve) => {
        const server = createServer(async (req, res) => {
            const url = req.url.split('?')[0];
            if (Object.prototype.hasOwnProperty.call(fixturePages, url)) {
                // Every fixture page is an admin console page: it gets the
                // header nginx sends. Nothing else this server answers does.
                res.writeHead(200, {
                    'Content-Type': 'text/html; charset=utf-8',
                    'Content-Security-Policy': CSP
                });
                return res.end(fixturePages[url]);
            }
            let rel = decodeURIComponent(url);
            if (rel.endsWith('/')) rel += 'index.html';
            const file = path.join(DOCROOT, path.normalize(rel));
            if (!file.startsWith(DOCROOT) || !existsSync(file)) {
                if (rel.startsWith('/api/')) {
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    // One mirror in each live state -- online, syncing,
                    // error -- so MirrorStatus.load() (main.js) paints every
                    // pill/stream/status-dot variant the /api/ response can
                    // reach on its own; the neutral pill and the other three
                    // status-dot states are reached by the harness setting
                    // data-state directly, see measurePublicProbes(). Any
                    // /api/ path (including /health, for FooterVersion)
                    // gets this same body: it has no "version" field, so
                    // FooterVersion.load() leaves .footer-version empty,
                    // which this harness never asserts text content on.
                    return res.end(JSON.stringify({
                        mirrors: {
                            freebsd: {
                                status: 'active', size: '1.4 TB',
                                last_updated: new Date(Date.now() - 3 * 60_000).toISOString()
                            },
                            netbsd: {
                                status: 'syncing', size: '900 GB',
                                last_updated: new Date(Date.now() - 3 * 60_000).toISOString()
                            },
                            openbsd: { status: 'error' }
                        },
                        totals: { size: '4.2 TB', files: '604,618' }
                    }));
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
// Minimal CDP client (identical shape to csp_click_harness.mjs's), plus a
// standing collector for two kinds of page misbehaviour that no probe
// otherwise notices: an uncaught JS error (or unhandled promise rejection --
// Chrome reports both through the same event once Runtime.enable is on) and
// a console.error() call. Both are queried on every waitFor() poll and once
// more at the end of main(), so a bug anywhere in the run -- not just during
// a specific probe -- is caught.
// ---------------------------------------------------------------------------
class CDP {
    constructor(ws) {
        this.ws = ws;
        this.id = 0;
        this.pending = new Map();
        this.jsErrors = [];
        this.consoleErrors = [];
        this.cspViolations = [];
        ws.addEventListener('message', (ev) => {
            const msg = JSON.parse(ev.data);
            // CSP violations arrive on two DevTools channels, and a violation
            // normally shows up on both: the Log domain's console message, and
            // the Audits domain's structured issue (which names the directive).
            // Either one counts. Both are matched on what they are, not on a
            // page: takeCspViolations() says which page they belong to.
            if (msg.method === 'Log.entryAdded') {
                const entry = msg.params.entry;
                if (/Content Security Policy/i.test(entry.text || '')) {
                    this.cspViolations.push({ via: 'log', text: entry.text, url: entry.url || null });
                }
                return;
            }
            if (msg.method === 'Audits.issueAdded') {
                const issue = msg.params.issue;
                if (issue.code === 'ContentSecurityPolicyIssue') {
                    const d = issue.details.contentSecurityPolicyIssueDetails || {};
                    this.cspViolations.push({
                        via: 'audits',
                        directive: d.violatedDirective || null,
                        type: d.contentSecurityPolicyViolationType || null,
                        blockedUrl: d.blockedURL || null,
                        reportOnly: Boolean(d.isReportOnly),
                        url: d.sourceCodeLocation ? d.sourceCodeLocation.url : null
                    });
                }
                return;
            }
            if (msg.method === 'Runtime.exceptionThrown') {
                const d = msg.params.exceptionDetails;
                const detail = d.exception?.description || d.exception?.value || d.text || JSON.stringify(d);
                this.jsErrors.push(String(detail));
                return;
            }
            if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
                const parts = (msg.params.args || []).map((a) => a.value ?? a.description ?? String(a));
                this.consoleErrors.push(parts.join(' '));
                return;
            }
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

    /** Every CSP violation reported since the last call, and forgets them.
     *  Called before a page's navigation (so an earlier page's never counts
     *  against it) and after its last measurement (so a late one, such as a
     *  font fetched after layout, is still its own). */
    takeCspViolations() {
        const taken = this.cspViolations;
        this.cspViolations = [];
        return taken;
    }
}

/** Throws, naming every collected error, if the public page misbehaved at
 * any point in the run so far. Called on every waitFor() poll, so an error
 * that stops the page from ever reaching the awaited state is reported as
 * itself rather than as a timeout, and once more at the end of main(), for
 * anything raised after the last wait -- a whole-session check, not a
 * per-probe one. "Report it, don't hide it": the message carries the full
 * detail rather than just a count, since this is the only place any of it is
 * ever surfaced. */
function checkForPageErrors(cdp) {
    if (cdp.jsErrors.length === 0 && cdp.consoleErrors.length === 0) return;
    const lines = [
        ...cdp.jsErrors.map((e) => `uncaught JS error/rejection: ${e}`),
        ...cdp.consoleErrors.map((e) => `console.error(): ${e}`)
    ];
    throw new Error(
        `the public page misbehaved during this run (${cdp.jsErrors.length} JS error(s)/` +
        `rejection(s), ${cdp.consoleErrors.length} console.error() call(s)):\n` + lines.join('\n')
    );
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launchChrome() {
    const userDataDir = await mkdtemp(path.join(tmpdir(), 'contrast-chrome-'));
    const chrome = spawn(CHROME, [
        '--headless=new',
        '--remote-debugging-port=0',
        `--user-data-dir=${userDataDir}`,
        '--no-first-run', '--no-default-browser-check',
        '--disable-gpu', '--disable-extensions', '--mute-audio',
        // Nothing but this harness's own 127.0.0.1 server should be contacted:
        // CI runs this on a bare runner, where Chrome would otherwise reach out
        // for variations, safe browsing and component updates as well.
        '--disable-background-networking', '--disable-component-update'
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
    chromeProcess = chrome;

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
    const deadline = Date.now() + CHROME_START_TIMEOUT_MS;
    while (!wsUrl && Date.now() < deadline) {
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
            `Chrome did not expose a DevTools endpoint within ${CHROME_START_TIMEOUT_MS / 1000}s.\n` +
            '--- chrome stderr (tail) ---\n' + (chromeStderr || '(nothing on stderr)')
        );
    }
    const cdp = await CDP.connect(wsUrl);
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: 1400, height: 4200, deviceScaleFactor: 1, mobile: false
    }, sessionId);
    // The public site follows prefers-color-scheme until a visitor picks a
    // theme (js/theme-init.js), so main()'s first pass is only the light theme
    // if this Chrome says light. Pin it rather than inherit the host's default.
    // prefers-reduced-motion: reduce turns every colour/background transition
    // and every @keyframes animation off (style.css's own reduced-motion
    // block) for the rest of the session -- see the module docstring for why
    // that, not a per-probe sleep, is how this harness gets a settled colour
    // after a data-state change.
    await cdp.send('Emulation.setEmulatedMedia', {
        features: [
            { name: 'prefers-color-scheme', value: 'light' },
            { name: 'prefers-reduced-motion', value: 'reduce' }
        ]
    }, sessionId);
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    // Both domains replay what they already hold when enabled, and report new
    // entries as they happen: the CSP collector (see class CDP) needs them on
    // before the first navigation.
    await cdp.send('Log.enable', {}, sessionId);
    await cdp.send('Audits.enable', {}, sessionId);
    return { chrome, cdp, sessionId };
}

/** Polls `expression` in the page until it is truthy. For state a page only
 * reaches after its load event: navigate() waits for load, not for the
 * fetches a DOMContentLoaded handler starts.
 *
 * Checks for a page error on every poll, not just once at the end of
 * main(): a synchronous throw early in main.js's DOMContentLoaded handler
 * stops the rest of that handler from ever running, so MirrorStatus.load()
 * is never called and the condition this function is waiting for is never
 * going to become true no matter how long it waits. Left unchecked here,
 * that surfaces as a generic "timed out" message five seconds later instead
 * of the real cause, which checkForPageErrors() already has on hand. */
async function waitFor(cdp, evaluate, expression, what, timeoutMs = 5000) {
    const deadline = Date.now() + timeoutMs;
    while (!(await evaluate(expression))) {
        checkForPageErrors(cdp);
        if (Date.now() > deadline) throw new Error(`timed out after ${timeoutMs}ms waiting for ${what}`);
        await sleep(50);
    }
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
        // Under prefers-reduced-motion the hover colour/background applies
        // instantly (no transition to settle); this margin is for the real
        // input dispatch and hit-testing to land, not for a fade to finish.
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

/** Like measure(), but for an element whose own identity is a fill colour,
 * not text -- .status-dot has no content, so the pairing that matters is
 * backgroundColor-vs-backgroundColor, not colour-vs-backgroundColor. Reads
 * backgroundColor on both sides and still returns it under the `color` key,
 * so the {color, backgroundColor} shape test_contrast.py's _measured_ratio()
 * already expects needs no change to handle it. No hover: none of these
 * probes are hover states. */
async function measureDot(evaluate, { selector, bgSelector }) {
    return evaluate(`(() => {
        const fg = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!fg || !bg) return { error: 'element(s) not found: ' +
            (!fg ? ${JSON.stringify(selector)} : ${JSON.stringify(bgSelector)}) };
        return {
            color: getComputedStyle(fg).backgroundColor,
            backgroundColor: getComputedStyle(bg).backgroundColor
        };
    })()`);
}

/** For a ::before pseudo-element painted by a background token (the online
 * sync-stream's line) rather than a placeholder's text colour:
 * getComputedStyle(el, pseudo) is the only way to reach a pseudo-element's
 * computed style at all (it has no node querySelector can return). Unlike
 * the admin-only ::placeholder case below, the comparison background here is
 * a separate ancestor (.streams-inner), not the pseudo's own host element
 * (.stream-line itself declares no background), so bgSelector is always
 * required. */
async function measurePseudoBackground(evaluate, selector, pseudo, bgSelector) {
    return evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!el || !bg) return { error: 'element(s) not found: ' +
            (!el ? ${JSON.stringify(selector)} : ${JSON.stringify(bgSelector)}) };
        const style = getComputedStyle(el, ${JSON.stringify(pseudo)});
        const color = style && style.backgroundColor;
        if (!color) return { error: 'getComputedStyle(el, ' + ${JSON.stringify(pseudo)} +
            ') returned no backgroundColor in this Chrome build' };
        return { color, backgroundColor: getComputedStyle(bg).backgroundColor };
    })()`);
}

/** Sets data-state on `selector` directly, because CSS keys every pill,
 * status-dot and stream-line purely off that attribute (spec section 5.2) --
 * a probe does not need main.js to have painted a particular value, only for
 * the value to be there when getComputedStyle reads it. Always applied
 * immediately before the measurement it exists for; see PUBLIC_PROBES'
 * ordering comment for why that order matters. */
async function setDataState(evaluate, selector, value) {
    const ok = await evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false;
        el.setAttribute('data-state', ${JSON.stringify(value)});
        return true;
    })()`);
    if (!ok) throw new Error(`setDataState: no element for ${selector}`);
}

/** Dispatches a PUBLIC_PROBES entry to whichever of measure()/measureDot()/
 * measurePseudoBackground() its shape calls for, applying setState first if
 * the probe has one, so main()'s probe loop can stay a plain `for` over one
 * list. */
async function measureProbe(cdp, sessionId, evaluate, probe) {
    if (probe.setState) await setDataState(evaluate, probe.setState.selector, probe.setState.value);
    if (probe.pseudo) return measurePseudoBackground(evaluate, probe.selector, probe.pseudo, probe.bgSelector);
    if (probe.dot) return measureDot(evaluate, probe);
    return measure(cdp, sessionId, evaluate, probe);
}

// ---------------------------------------------------------------------------
// Probe lists -- mirrors the selectors test_contrast.py reasons about
// statically. Keep the two in step; a mismatch is not caught automatically
// (test_dynamic_probe_list_matches_the_harness only compares the id sets,
// not this ordering comment).
//
// Order matters for four entries: '#freebsd-status' and '#overallStatus'
// are each probed twice, first at whatever /api/ naturally left them (the
// online pill and the error dot, both real end-to-end paints) and then
// again with data-state forced to a value the stub cannot reach on this
// element (the neutral pill, the online/syncing/neutral dot). The forced
// entries are listed after their element's natural one so the natural
// measurement is never accidentally taken from an already-overridden
// element -- see measurePublicProbes() in main(), which reruns this whole
// list once per theme after a fresh natural paint.
// ---------------------------------------------------------------------------
const PUBLIC_PROBES = [
    { id: 'body', selector: 'body', bgSelector: 'body' },
    { id: '.nav-link', selector: '.nav-link', bgSelector: '.header' },
    { id: '.nav-link:hover', selector: '.nav-link', bgSelector: '.nav-link', hover: true },
    { id: '.nav-admin', selector: '.nav-admin', bgSelector: '.header' },
    { id: '.stat-label', selector: '.stat-label', bgSelector: 'body' },
    { id: '.mirror-description', selector: '.mirror-description', bgSelector: '.mirror-card' },
    { id: '.access-label', selector: '.access-label', bgSelector: '.access-row' },
    { id: '.btn-primary', selector: '.mirror-actions .btn-primary', bgSelector: '.mirror-actions .btn-primary' },
    { id: '.btn-secondary:hover', selector: '.mirror-actions .btn-secondary', bgSelector: '.mirror-actions .btn-secondary', hover: true },
    { id: '.footer-content p', selector: '.footer-content p:not(.footer-version)', bgSelector: '.footer' },
    { id: '.footer-content a', selector: '.footer-content p a', bgSelector: '.footer' },
    { id: '.about-text a', selector: '.about-text a', bgSelector: 'body' },
    { id: '.footer-version', selector: '.footer-version', bgSelector: '.footer' },
    { id: '.section-subtitle', selector: '.section-subtitle', bgSelector: 'body' },
    { id: '.toast', selector: '#toast', bgSelector: '#toast' },
    // Pills, natural first (the stub's own online/syncing/error), then the
    // neutral base rule forced onto the same element the online pill just
    // used.
    { id: '.pill[data-state="online"]', selector: '#freebsd-status', bgSelector: '#freebsd-status' },
    { id: '.pill[data-state="syncing"]', selector: '#netbsd-status', bgSelector: '#netbsd-status' },
    { id: '.pill[data-state="error"]', selector: '#openbsd-status', bgSelector: '#openbsd-status' },
    { id: '.pill', selector: '#freebsd-status', bgSelector: '#freebsd-status', setState: { selector: '#freebsd-status', value: 'disabled' } },
    // The one sync-stream state with a bare var() background (see
    // test_contrast.py's PUBLIC_PAIRS comment on the syncing/error lines'
    // gradients); natural, from the same stub entry as the pill above.
    { id: '.stream[data-state="online"] .stream-line::before', selector: '#freebsd-stream .stream-line', pseudo: '::before', bgSelector: '.streams-inner' },
    // The overall card's dot: natural (error, since any mirror erroring
    // wins main.js's priority order), then the other three states forced
    // onto the same element in turn.
    { id: '.status-card[data-state="error"] .status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true },
    { id: '.status-card[data-state="online"] .status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true, setState: { selector: '#overallStatus', value: 'online' } },
    { id: '.status-card[data-state="syncing"] .status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true, setState: { selector: '#overallStatus', value: 'syncing' } },
    { id: '.status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true, setState: { selector: '#overallStatus', value: 'disabled' } }
];

// Measured once per admin theme (see buildAdminFixturePage() and main()): the
// fixture markup itself does not depend on theme, only which stylesheet
// cascade layer <html>'s data-theme selects. The three job-status/meter/
// toggle entries are what the Reflection redesign added to the console (spec
// sections 4.8 and 6.2); the rest predate it.
const ADMIN_PROBES = [
    { id: '.login-subtitle', selector: '#login-fixture .login-subtitle', bgSelector: '#login-fixture .login-card' },
    { id: '.btn-primary', selector: '#login-fixture .btn-primary', bgSelector: '#login-fixture .btn-primary' },
    { id: '.theme-toggle', selector: '#layout-fixture .theme-toggle', bgSelector: '#layout-fixture .theme-toggle' },
    { id: '.nav-item.active', selector: '#layout-fixture .nav-item.active', bgSelector: '#layout-fixture .nav-item.active' },
    { id: '.user-avatar', selector: '#layout-fixture .user-avatar', bgSelector: '#layout-fixture .user-avatar' },
    { id: '.user-role', selector: '#layout-fixture .user-role', bgSelector: '#layout-fixture .user-info' },
    { id: '.nav-section-title', selector: '#layout-fixture .nav-section-title', bgSelector: '#layout-fixture .sidebar' },
    { id: '.status-badge.disabled', selector: '#users-fixture .status-badge.disabled', bgSelector: '#users-fixture .status-badge.disabled' },
    { id: '.status-badge.active', selector: '#users-fixture .status-badge.active', bgSelector: '#users-fixture .status-badge.active' },
    { id: 'th', selector: '#users-fixture th', bgSelector: '#users-fixture th' },
    { id: '.u-text-muted', selector: '#mirrors-fixture .u-text-muted', bgSelector: '#mirrors-fixture .card' },
    { id: '.status-badge.error', selector: '#mirrors-fixture .status-badge.error', bgSelector: '#mirrors-fixture .status-badge.error' },
    { id: '.status-badge.syncing', selector: '#mirrors-fixture .status-badge.syncing', bgSelector: '#mirrors-fixture .status-badge.syncing' },
    // Recent Sync Jobs' job-status pill (dashboard-fixture is seeded with one
    // completed job, spec 4.8's pill mapping) and the disk meter's own fill,
    // seeded at 91% so it renders in its is-warn band (DISK_USAGE_WARNING_
    // PERCENT/_CRITICAL_PERCENT; the .meter-fill on .meter pairing is a UI
    // indicator, 3:1, not text -- see measureDot()'s reasoning; this one still
    // has real text content, so the plain (element, property) measure() shape
    // fits, unlike .status-dot).
    { id: '.status-badge.completed', selector: '#dashboard-fixture .status-badge.completed', bgSelector: '#dashboard-fixture .status-badge.completed' },
    { id: '.meter-fill.is-warn', selector: '#dashboard-fixture .meter-fill.is-warn', bgSelector: '#dashboard-fixture .meter', dot: true }
];

/** ::placeholder is a pseudo-element, not reachable through the plain
 * (element, property) probe shape above. Chrome supports the two-argument
 * form of getComputedStyle for it; measured separately for that reason, with
 * a clearly-labelled error (rather than a silent skip) if a given Chrome
 * build does not support it -- test_contrast.py treats a missing/errored
 * measurement as "not dynamically confirmed" and falls back to its static
 * coverage of the same pairing, but it needs to see why. Unchanged by the
 * public palette switch. */
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

// The condition the /api/ stub's own response satisfies once main.js has
// painted it for real: every element PUBLIC_PROBES measures "naturally"
// (not via setState) at its expected, stub-driven value. Waited for once per
// theme pass, before that pass's probe loop runs -- see measurePublicProbes().
// That includes #freebsd-stream, whose own data-state is what the online
// stream line's ::before keys off: the row's pill is painted separately, so
// a pill reading "online" says nothing about the row.
const NATURAL_STATE_READY = `(
    document.getElementById('freebsd-status')?.getAttribute('data-state') === 'online' &&
    document.getElementById('netbsd-status')?.getAttribute('data-state') === 'syncing' &&
    document.getElementById('openbsd-status')?.getAttribute('data-state') === 'error' &&
    document.getElementById('freebsd-stream')?.getAttribute('data-state') === 'online' &&
    document.getElementById('overallStatus')?.getAttribute('data-state') === 'error'
)`;

/** Waits for a fresh, real, stub-driven paint (proving main.js's own wiring,
 * not just that an element exists), then measures every PUBLIC_PROBES entry
 * in order. Called once per theme; main() ensures each call sees a page
 * that has just (re)run its DOMContentLoaded handler against the stub, so a
 * setState override from a previous call is never still sitting on an
 * element this one reads "naturally". */
async function measurePublicProbes(cdp, sessionId, evaluate) {
    await waitFor(cdp, evaluate, NATURAL_STATE_READY, 'the stubbed mirror statuses to paint');
    const out = {};
    for (const probe of PUBLIC_PROBES) {
        out[probe.id] = await measureProbe(cdp, sessionId, evaluate, probe);
    }
    return out;
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
    // A completed job (the pill probe) and 91% storage (the meter's is-warn
    // band, DISK_USAGE_WARNING_PERCENT/_CRITICAL_PERCENT) in one render.
    const dashboardHtml = await renderWith(mod, mod.renderDashboard, {
        mirrors: { total: 3, active: 2, syncing: 1, error: 0, total_size_bytes: 0 },
        users: { total: 2 },
        storage: { path: '/data/mirrors', total_bytes: 1000, used_bytes: 910, free_bytes: 90, percent_used: 91 },
        recent_syncs: [
            { id: 1, mirror_id: 1, status: 'completed', files_deleted: 0, created_at: new Date().toISOString() }
        ],
        recent_activity: []
    });

    const fragments = { login, layout, usersHtml, mirrorsHtml, dashboardHtml };
    const lightPage = buildAdminFixturePage('light', fragments);
    // The CSP control: the light page with one inline style attribute on
    // <body>. Under style-src 'self' Chrome must refuse it and say so.
    const controlPage = lightPage.replace('<body>', '<body style="color: red">');
    if (controlPage === lightPage) {
        throw new Error('the CSP control page could not be built: the fixture page has no <body>');
    }
    const fixturePages = {
        '/__admin_fixture_light__.html': lightPage,
        '/__admin_fixture_dark__.html': buildAdminFixturePage('dark', fragments),
        '/__admin_fixture_csp_control__.html': controlPage
    };

    const { server, port } = await serve(fixturePages);
    const origin = `http://127.0.0.1:${port}`;
    const { chrome, cdp, sessionId } = await launchChrome();
    const evaluate = makeEvaluate(cdp, sessionId);

    const out = {
        public: { light: {}, dark: {} },
        admin: { light: {}, dark: {} },
        csp: { policy: CSP, admin: { light: [], dark: [] }, controls: { inlineStyleAttribute: [] } }
    };

    await navigate(cdp, sessionId, `${origin}/index.html`);
    const initialTheme = await evaluate('document.documentElement.getAttribute("data-theme")');
    if (initialTheme !== 'light') {
        throw new Error(`index.html did not open in the light theme (got ${initialTheme})`);
    }
    out.public.light = await measurePublicProbes(cdp, sessionId, evaluate);

    // A genuine click on the real toggle button, not setAttribute from here,
    // so ThemeManager's own click handler and its localStorage write are
    // what actually flips the theme.
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
    // Extra margin for the click/attribute plumbing to land; the colour
    // fade itself needs none of this under prefers-reduced-motion (see the
    // module docstring).
    await sleep(450);
    let theme = await evaluate('document.documentElement.getAttribute("data-theme")');
    if (theme !== 'dark') throw new Error(`clicking #themeToggle did not set data-theme=dark (got ${theme})`);

    // Reload so the dynamic probes read a second, fresh, real paint rather
    // than reusing whatever the light pass's setState calls left behind on
    // shared elements (#freebsd-status, #overallStatus). ThemeManager just
    // saved "dark" to localStorage; theme-init.js reads that choice and
    // applies dark before first paint, so this reopens dark without
    // clicking the toggle again -- the click above already proved that path.
    await navigate(cdp, sessionId, `${origin}/index.html`);
    theme = await evaluate('document.documentElement.getAttribute("data-theme")');
    if (theme !== 'dark') {
        throw new Error(`reloading did not keep data-theme=dark (got ${theme}); did the toggle's localStorage write fail?`);
    }
    out.public.dark = await measurePublicProbes(cdp, sessionId, evaluate);

    // The admin console now follows the same saved light/dark choice as the
    // public site (spec section 6.2): each theme's fixture is its own
    // document (data-theme lives on <html>, not on a sub-tree), so every
    // ADMIN_PROBES entry is measured once per real navigation, not once per
    // page. checkForPageErrors() runs once at the end of main(), after both.
    //
    // Each page is served under the production CSP (see serve()), and the
    // violations Chrome reports for it are collected into out.csp: those from
    // before its navigation are dropped, those from after its last measurement
    // are its own, so a font or mask image fetched late still counts.
    for (const theme of ['light', 'dark']) {
        cdp.takeCspViolations();
        await navigate(cdp, sessionId, `${origin}/__admin_fixture_${theme}__.html`);
        const admin_theme = await evaluate('document.documentElement.getAttribute("data-theme")');
        if (admin_theme !== theme) {
            throw new Error(`admin fixture (${theme}) did not carry data-theme=${theme} (got ${admin_theme})`);
        }
        for (const probe of ADMIN_PROBES) {
            out.admin[theme][probe.id] = await measureProbe(cdp, sessionId, evaluate, probe);
        }
        out.admin[theme]['.form-input::placeholder'] = await measurePlaceholder(
            evaluate, '#login-fixture .form-input', '#login-fixture .form-input'
        );
        out.csp.admin[theme] = cdp.takeCspViolations();
    }

    // The control, in the same Chrome session: the collector has to hear about
    // an inline style attribute here, or its silence above means nothing.
    cdp.takeCspViolations();
    await navigate(cdp, sessionId, `${origin}/__admin_fixture_csp_control__.html`);
    await sleep(300);
    out.csp.controls.inlineStyleAttribute = cdp.takeCspViolations();

    checkForPageErrors(cdp);

    process.stdout.write(JSON.stringify(out, null, 2) + '\n');
    chrome.kill();
    server.close();
    process.exit(0);
}

main().catch((err) => {
    process.stderr.write(String(err && err.stack ? err.stack : err) + '\n');
    chromeProcess?.kill();
    process.exit(1);
});
