/**
 * Footer-version harness for frontend/public/js/main.js.
 *
 * FooterVersion.load() is the piece of main.js this change adds: it reads
 * .footer-version, asks the API for /health, and writes the response's
 * "version" field into the element -- or leaves the element exactly as it
 * started if the API is unreachable, answers with a non-2xx status, returns
 * unparsable JSON, or omits "version". A down backend must not make the
 * footer show something false.
 *
 * There is no JS test runner in this repo (see escaping_harness.mjs, which
 * this follows): load the real main.js into a vm context with the smallest
 * DOM/fetch stub it needs, run a fixed list of fetch scenarios against
 * FooterVersion.load(), and report which ones behaved.
 *
 * Usage:  node footer_version_harness.mjs <path-to-main.js>
 * Output: JSON {"checks":[{"name","ok","detail"}]} on stdout.
 *
 * Exit status is 0 even when checks fail: pytest reads the JSON and decides.
 * A mutation run needs to report "these checks failed", not crash.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const source = readFileSync(sourcePath, 'utf8');

const checks = [];
function check(name, ok, detail = '') {
    checks.push({ name, ok: !!ok, detail: String(detail) });
}

// admin.js's EPILOGUE trick (see escaping_harness.mjs): main.js has no
// exports, so the vm's completion value is how this gets at FooterVersion.
const EPILOGUE = `\n;({ FooterVersion });\n`;

/**
 * Load main.js fresh (module-level state -- ThemeManager, API, etc. -- must
 * not leak between scenarios) with fetch replaced by `fetchImpl`, run
 * FooterVersion.load() once, and report:
 *   - elText:   what .footer-version's textContent ended up as. `null` is the
 *               sentinel for "never touched", distinct from the JS value
 *               `undefined`, which a bug could legitimately assign.
 *   - fetched:  the endpoint string main.js actually called fetch() with, or
 *               null if fetch was never called.
 *   - threw:    the error FooterVersion.load() raised, if any.
 *   - elFound:  whether the sandbox's querySelector('.footer-version') stub
 *               was asked for that element at all.
 */
async function runScenario(fetchImpl, { hideElement = false } = {}) {
    let elText = null; // sentinel: "untouched", not the JS value `undefined`
    const el = {
        get textContent() { return elText; },
        set textContent(v) { elText = v; },
    };

    let fetched = null;
    const recordingFetch = async (url, ...rest) => {
        fetched = url;
        return fetchImpl(url, ...rest);
    };

    const sandbox = {
        console,
        setTimeout: () => 0,
        setInterval: () => 0,
        clearTimeout: () => {},
        document: {
            addEventListener: () => {},
            getElementById: () => null,
            querySelectorAll: () => [],
            querySelector: (sel) => (!hideElement && sel === '.footer-version' ? el : null),
            documentElement: { getAttribute: () => null, setAttribute: () => {} },
        },
        window: { addEventListener() {}, location: { hostname: 'example.test' } },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        navigator: { clipboard: { writeText: () => Promise.resolve() } },
        fetch: recordingFetch,
    };
    sandbox.globalThis = sandbox;

    const mod = vm.runInNewContext(source + EPILOGUE, sandbox, { filename: sourcePath });

    let threw = null;
    try {
        await mod.FooterVersion.load();
    } catch (err) {
        threw = err;
    }

    return { elText, fetched, threw };
}

const jsonResponse = (status, body) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
});

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------
const run = async () => {
    // 1. The happy path: a healthy response with a version is written verbatim.
    {
        const r = await runScenario(async () => jsonResponse(200, { status: 'healthy', version: '2250188-2026-09-07' }));
        check(
            'load writes the reported version into .footer-version',
            r.threw === null && r.elText === '2250188-2026-09-07',
            r.threw ? `threw: ${r.threw}` : `elText=${JSON.stringify(r.elText)}`
        );
    }

    // 2. Must ask the API for /api/health specifically -- not /api/health/detailed
    //    (a DB/Redis round trip on every page load for a value that never
    //    changes between deploys) and not a typo'd path.
    {
        const r = await runScenario(async () => jsonResponse(200, { status: 'healthy', version: 'x' }));
        check(
            'load requests /api/health for the version',
            r.fetched === '/api/health',
            `fetched=${JSON.stringify(r.fetched)}`
        );
    }

    // 3. Network failure (fetch rejects): API.get() catches it and returns
    //    null; the footer must stay exactly as it started.
    {
        const r = await runScenario(async () => { throw new TypeError('network error'); });
        check(
            'load leaves the footer untouched when the API is unreachable',
            r.threw === null && r.elText === null,
            r.threw ? `threw: ${r.threw}` : `elText=${JSON.stringify(r.elText)}`
        );
    }

    // 4. A non-2xx response (e.g. the backend is up but degraded).
    {
        const r = await runScenario(async () => jsonResponse(503, { detail: 'unavailable' }));
        check(
            'load leaves the footer untouched on a non-2xx response',
            r.threw === null && r.elText === null,
            r.threw ? `threw: ${r.threw}` : `elText=${JSON.stringify(r.elText)}`
        );
    }

    // 5. A 200 with no "version" key (an older backend, or a field rename).
    {
        const r = await runScenario(async () => jsonResponse(200, { status: 'healthy' }));
        check(
            'load leaves the footer untouched when the response has no version field',
            r.threw === null && r.elText === null,
            r.threw ? `threw: ${r.threw}` : `elText=${JSON.stringify(r.elText)}`
        );
    }

    // 6. Malformed JSON body: response.json() itself rejects.
    {
        const r = await runScenario(async () => ({
            ok: true,
            status: 200,
            json: async () => { throw new SyntaxError('Unexpected token in JSON'); },
        }));
        check(
            'load leaves the footer untouched on malformed JSON',
            r.threw === null && r.elText === null,
            r.threw ? `threw: ${r.threw}` : `elText=${JSON.stringify(r.elText)}`
        );
    }

    // 7. .footer-version is not on the page at all (e.g. a future markup
    //    change). Must return quietly, not throw.
    {
        const r = await runScenario(
            async () => jsonResponse(200, { status: 'healthy', version: '2250188-2026-09-07' }),
            { hideElement: true }
        );
        check(
            'load does not throw when .footer-version is not on the page',
            r.threw === null,
            r.threw ? `threw: ${r.threw}` : 'ok'
        );
    }
};

let loadError = null;
try {
    await run();
} catch (err) {
    loadError = err;
}

if (loadError) {
    process.stdout.write(JSON.stringify({
        loadError: `${loadError && loadError.stack ? loadError.stack : loadError}`,
        checks: [],
    }));
} else {
    process.stdout.write(JSON.stringify({ checks }));
}
