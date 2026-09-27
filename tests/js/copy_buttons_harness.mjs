/**
 * Copy-button harness for the page-wide [data-copy] buttons in
 * frontend/public/js/main.js.
 *
 * docs/design/2026-09-25-reflection-redesign.md, section 5.1. Binds the real
 * bindDataCopyButtons() against a fake [data-copy] button, fires a genuine
 * click through the same addEventListener path the page uses, and reports
 * what the toast said.
 *
 * tests/js/csp_click_harness.mjs already proves, in a real browser under the
 * production CSP, that these buttons copy the right URL -- but a real
 * browser always has navigator.clipboard, so it cannot exercise the guard
 * copyUrl() adds: outside a secure context, and in older browsers,
 * navigator.clipboard is undefined, not a promise that rejects. Missing that
 * check turns a click into a thrown TypeError instead of the "Failed to copy
 * URL" toast a rejected write gets. (The per-mirror copyRsync has no such
 * guard: spec section 5.2 keeps those buttons unchanged.) Deleting
 * navigator.clipboard from an already-started Chrome to test that would be a
 * browser quirk in its own right; a Node vm with no clipboard property at
 * all asks the question directly.
 *
 * There is no JS test runner in this repo (see escaping_harness.mjs, which
 * this follows): load the real main.js into a vm context with the smallest
 * DOM/navigator stub it needs, run a fixed list of scenarios, and report
 * which ones behaved.
 *
 * Usage:  node copy_buttons_harness.mjs <path-to-main.js>
 * Output: JSON {"checks":[{"name","ok","detail"}]} on stdout.
 *
 * Exit status is 0 even when checks fail: pytest reads the JSON and decides.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const source = readFileSync(sourcePath, 'utf8');

const checks = [];
function check(name, ok, detail = '') {
    checks.push({ name, ok: !!ok, detail: String(detail) });
}

// main.js has no exports; the vm's completion value is how this gets at the
// binder (escaping_harness.mjs's EPILOGUE trick, also used by
// footer_version_harness.mjs and states_harness.mjs).
const EPILOGUE = `\n;({ bindDataCopyButtons });\n`;

/** One fake [data-copy] button: dataset.copy plus an addEventListener that
 * remembers its click handler for the harness to fire directly, since this
 * vm's DOM has no real event dispatch. */
function makeButton(dataCopy) {
    let onClick = null;
    return {
        dataset: { copy: dataCopy },
        addEventListener(type, handler) {
            if (type === 'click') onClick = handler;
        },
        click() {
            onClick?.();
        }
    };
}

/**
 * Bind main.js's real [data-copy] buttons against one fake button carrying
 * `dataCopy`, click it, and report what happened:
 *   - clipboardCalledWith: the URL passed to navigator.clipboard.writeText,
 *     or null if it was never called -- the no-clipboard guard path, or an
 *     unrecognised data-copy value that was never bound at all.
 *   - toastText/toastShown: #toast's state once the click's microtasks have
 *     settled. toastText is null if its setter was never touched.
 *   - threw: the error the click raised synchronously, if any -- the guard
 *     this harness exists to check is precisely what keeps this null.
 */
async function runScenario({ dataCopy, hasClipboard, hostname = 'mirror.test' }) {
    const button = makeButton(dataCopy);

    let toastText = null;
    let toastShown = false;
    const toast = {
        get textContent() { return toastText; },
        set textContent(v) { toastText = v; },
        classList: {
            add: (name) => { if (name === 'show') toastShown = true; },
            remove: (name) => { if (name === 'show') toastShown = false; }
        }
    };

    let clipboardCalledWith = null;
    const navigator = hasClipboard
        ? { clipboard: { writeText: (url) => { clipboardCalledWith = url; return Promise.resolve(); } } }
        : {};

    const sandbox = {
        console,
        setTimeout: () => 0,
        clearTimeout: () => {},
        document: {
            addEventListener: () => {},
            getElementById: (id) => (id === 'toast' ? toast : null),
            querySelectorAll: (sel) => (sel === '[data-copy]' ? [button] : [])
        },
        window: { location: { hostname } },
        navigator
    };
    sandbox.globalThis = sandbox;

    const mod = vm.runInNewContext(source + EPILOGUE, sandbox, { filename: sourcePath });
    mod.bindDataCopyButtons();

    let threw = null;
    try {
        button.click();
        // copyUrl's toast comes out of a Promise .then()/.catch(), which
        // settles on a microtask -- after click() returns, not during it.
        // This await runs on the harness's own, non-sandboxed event loop, so
        // one real macrotask trip is enough to let every microtask ahead of
        // it drain first.
        await new Promise((resolve) => setTimeout(resolve, 0));
    } catch (err) {
        threw = err;
    }

    return { toastText, toastShown, clipboardCalledWith, threw };
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------
const run = async () => {
    // Positive control: with the Clipboard API present, a bound button
    // copies its builder's URL and shows the toast. Without this passing
    // first, the guard check below would prove nothing -- it would also pass
    // for a harness that never actually clicked anything.
    {
        const r = await runScenario({ dataCopy: 'rsync-root', hasClipboard: true, hostname: 'mirror.test' });
        check(
            'a bound data-copy button copies its built URL and shows the toast',
            r.threw === null && r.clipboardCalledWith === 'rsync://mirror.test/'
                && r.toastShown && r.toastText === 'Copied: rsync://mirror.test/',
            r.threw
                ? `threw: ${r.threw}`
                : `clipboardCalledWith=${JSON.stringify(r.clipboardCalledWith)} `
                    + `toastShown=${r.toastShown} toastText=${JSON.stringify(r.toastText)}`
        );
    }

    // The guard this harness exists to check.
    {
        const r = await runScenario({ dataCopy: 'https-root', hasClipboard: false, hostname: 'mirror.test' });
        check(
            'a data-copy click with no navigator.clipboard toasts Failed to copy URL instead of throwing',
            r.threw === null && r.clipboardCalledWith === null
                && r.toastShown && r.toastText === 'Failed to copy URL',
            r.threw
                ? `threw: ${r.threw}`
                : `clipboardCalledWith=${JSON.stringify(r.clipboardCalledWith)} `
                    + `toastShown=${r.toastShown} toastText=${JSON.stringify(r.toastText)}`
        );
    }

    // An unrecognised data-copy value (e.g. a future markup typo) is left
    // unbound, not wired to a builder that would throw on `undefined`.
    {
        const r = await runScenario({ dataCopy: 'bogus', hasClipboard: true, hostname: 'mirror.test' });
        check(
            'an unrecognised data-copy value is left unbound rather than throwing',
            r.threw === null && r.clipboardCalledWith === null && !r.toastShown,
            r.threw
                ? `threw: ${r.threw}`
                : `clipboardCalledWith=${JSON.stringify(r.clipboardCalledWith)} toastShown=${r.toastShown}`
        );
    }
    {
        // An inherited Object.prototype name is not one of the builders:
        // looked up naively, 'constructor' would copy a bare hostname and
        // 'valueOf' would throw on the click.
        const bad = [];
        for (const dataCopy of ['constructor', 'toString', 'valueOf', 'hasOwnProperty']) {
            const r = await runScenario({ dataCopy, hasClipboard: true, hostname: 'mirror.test' });
            if (r.threw !== null || r.clipboardCalledWith !== null || r.toastShown) {
                bad.push(`${dataCopy}: threw=${r.threw} clipboardCalledWith=${JSON.stringify(r.clipboardCalledWith)} toastShown=${r.toastShown}`);
            }
        }
        check('an inherited object key as the data-copy value is left unbound', bad.length === 0, bad.join('; '));
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
        checks: []
    }));
} else {
    process.stdout.write(JSON.stringify({ checks }));
}
