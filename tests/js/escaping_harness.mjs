/**
 * Escaping harness for frontend/public/admin/js/admin.js.
 *
 * There is no JS test runner in this repo, so this is a plain node script that
 * pytest shells out to (tests/test_admin_js_escaping.py). It loads the REAL
 * admin.js -- or a mutated copy, for the mutation tests -- into a vm context
 * with the smallest DOM stub that file needs, pulls the escaping helpers and
 * page renderers out of it, and runs assertions against them.
 *
 * Usage:  node escaping_harness.mjs <path-to-admin.js>
 * Output: JSON {"checks":[{"name","ok","detail"}]} on stdout.
 *
 * Exit status is 0 even when checks fail: pytest reads the JSON and decides.
 * A mutation run needs to report "these checks failed", not crash.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const source = readFileSync(sourcePath, 'utf8');

// ---------------------------------------------------------------------------
// Load admin.js into a vm context
// ---------------------------------------------------------------------------

/** The smallest DOM admin.js touches at load time, plus hooks the tests move. */
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

// admin.js has no exports; its top-level bindings are `const`/`class`/
// `function`. The trailing expression is the script's completion value, which
// is how we get at them.
const EPILOGUE = `
;({ html, escapeHtml, interpolateHtml, trustedHtml, setHtml, SafeHtml,
    renderLayout, renderUsers, renderAuditLogs, renderMirrors, renderSettings,
    Toast, Modal, api, state });
`;

let mod = null;
let loadError = null;
try {
    mod = vm.runInNewContext(source + EPILOGUE, sandbox, { filename: sourcePath });
} catch (err) {
    loadError = err;
}

// ---------------------------------------------------------------------------
// A small HTML tag scanner.
//
// The question these tests must answer is not "does the output look escaped"
// but "did attacker data create an element or an attribute". Substring
// matching cannot answer that; this can. The alternation lets a quoted
// attribute value contain '>' without ending the tag -- the case a naive
// /<[^>]*>/ gets wrong, and the same class of "stops in the wrong place" bug
// these tests exist to catch.
// ---------------------------------------------------------------------------
const TAG_RE = /<\/?([a-zA-Z][a-zA-Z0-9-]*)((?:[^>"']|"[^"]*"|'[^']*')*)\/?>/g;
const ATTR_RE = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;

function scanTags(htmlStr) {
    const out = [];
    for (const m of htmlStr.matchAll(TAG_RE)) {
        const attrs = {};
        for (const a of (m[2] || '').matchAll(ATTR_RE)) {
            attrs[a[1].toLowerCase()] = a[2] ?? a[3] ?? a[4] ?? '';
        }
        out.push({ name: m[1].toLowerCase(), attrs });
    }
    return out;
}

const tagNames = (h) => scanTags(h).map((t) => t.name);
const attrNames = (h) => scanTags(h).flatMap((t) => Object.keys(t.attrs));

/** Handler attributes: none appear in any static template in admin.js. */
const badAttrs = (h) => attrNames(h).filter((n) => n.startsWith('on'));
/** Elements that appear in no static template in admin.js. */
const INJECTABLE = new Set(['script', 'img', 'iframe', 'svg', 'object', 'embed', 'style', 'base', 'link']);
const badTags = (h) => tagNames(h).filter((n) => INJECTABLE.has(n));

// ---------------------------------------------------------------------------
// Attack strings, each chosen for a specific context.
// ---------------------------------------------------------------------------
const PAYLOADS = {
    script_tag: '<script>alert(1)</script>',
    img_onerror: '<img src=x onerror=alert(1)>',
    // Quoted-attribute breakouts. These need only a quote, not an angle
    // bracket, which is why an escaper that handles < > & is not enough.
    attr_breakout: '" onfocus="alert(1)" autofocus x="',
    attr_breakout_tagclose: '"><script>alert(1)</script><input value="',
    attr_single: "' onfocus='alert(1)' autofocus x='",
    // Already-encoded input: a missing '&' rule would decode this back.
    double_encoded: '&lt;script&gt;alert(1)&lt;/script&gt;',
    backtick: '`${alert(1)}`',
    // Payload split so any escaper that stops at the first match leaves the
    // second half live.
    two_quoted_spans: '"a" onfocus="alert(1)" x="'
};

// ---------------------------------------------------------------------------
// Check runner
// ---------------------------------------------------------------------------
const checks = [];

async function check(name, fn) {
    if (loadError) {
        checks.push({ name, ok: false, detail: `admin.js failed to load: ${loadError.message}` });
        return;
    }
    try {
        const detail = await fn();
        checks.push({ name, ok: true, detail: detail ?? '' });
    } catch (err) {
        checks.push({ name, ok: false, detail: String(err && err.message ? err.message : err) });
    }
}

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

async function main() {
    // --- escapeHtml, the primitive -----------------------------------------

    await check('escapeHtml escapes all six metacharacters', () => {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };
        for (const [raw, enc] of Object.entries(map)) {
            const got = mod.escapeHtml(raw);
            assert(got === enc, `escapeHtml(${JSON.stringify(raw)}) === ${JSON.stringify(got)}, want ${enc}`);
        }
        return '& < > " \' `';
    });

    await check('escapeHtml escapes every occurrence, not just the first', () => {
        const got = mod.escapeHtml('<<<');
        assert(got === '&lt;&lt;&lt;', `escapeHtml('<<<') === ${JSON.stringify(got)}`);
        const mixed = mod.escapeHtml('a"b"c"d');
        assert(!mixed.includes('"'), `left a bare quote: ${JSON.stringify(mixed)}`);
        return '';
    });

    await check('escapeHtml renders 0 and false, blanks only null/undefined', () => {
        assert(mod.escapeHtml(0) === '0', `escapeHtml(0) === ${JSON.stringify(mod.escapeHtml(0))}`);
        assert(mod.escapeHtml(false) === 'false', `escapeHtml(false) === ${JSON.stringify(mod.escapeHtml(false))}`);
        assert(mod.escapeHtml(null) === '', 'escapeHtml(null) should be ""');
        assert(mod.escapeHtml(undefined) === '', 'escapeHtml(undefined) should be ""');
        return '';
    });

    // --- html`` in element-text context -------------------------------------

    await check('html`` escapes payloads in element-text context', () => {
        for (const [name, payload] of Object.entries(PAYLOADS)) {
            const out = String(mod.html`<td>${payload}</td>`);
            assert(badTags(out).length === 0, `${name}: injected tag(s) ${badTags(out)} in ${JSON.stringify(out)}`);
            assert(badAttrs(out).length === 0, `${name}: injected attr(s) ${badAttrs(out)} in ${JSON.stringify(out)}`);
            assert(tagNames(out).join(',') === 'td,td', `${name}: tag structure changed -> ${tagNames(out)}`);
        }
        return `${Object.keys(PAYLOADS).length} payloads`;
    });

    // --- html`` in attribute context ----------------------------------------

    await check('html`` escapes payloads in double-quoted attribute context', () => {
        for (const [name, payload] of Object.entries(PAYLOADS)) {
            const out = String(mod.html`<input value="${payload}" disabled>`);
            const tags = scanTags(out);
            assert(tags.length === 1, `${name}: expected 1 tag, got ${tags.length} -> ${JSON.stringify(out)}`);
            const keys = Object.keys(tags[0].attrs).sort().join(',');
            assert(keys === 'disabled,value', `${name}: attribute set became [${keys}] -> ${JSON.stringify(out)}`);
        }
        return `${Object.keys(PAYLOADS).length} payloads`;
    });

    await check('html`` escapes payloads in single-quoted attribute context', () => {
        for (const [name, payload] of Object.entries(PAYLOADS)) {
            const out = String(mod.html`<input value='${payload}' disabled>`);
            const tags = scanTags(out);
            assert(tags.length === 1, `${name}: expected 1 tag, got ${tags.length} -> ${JSON.stringify(out)}`);
            const keys = Object.keys(tags[0].attrs).sort().join(',');
            assert(keys === 'disabled,value', `${name}: attribute set became [${keys}] -> ${JSON.stringify(out)}`);
        }
        return `${Object.keys(PAYLOADS).length} payloads`;
    });

    await check('html`` escapes payloads in class= alongside a static prefix', () => {
        // Mirrors `class="status-badge ${status}"`, the shape that made status
        // fields look harmless.
        for (const [name, payload] of Object.entries(PAYLOADS)) {
            const out = String(mod.html`<span class="status-badge ${payload}">x</span>`);
            const tags = scanTags(out);
            assert(tags.length === 2, `${name}: expected 2 tags, got ${tags.length} -> ${JSON.stringify(out)}`);
            const keys = Object.keys(tags[0].attrs).sort().join(',');
            assert(keys === 'class', `${name}: attribute set became [${keys}] -> ${JSON.stringify(out)}`);
        }
        return `${Object.keys(PAYLOADS).length} payloads`;
    });

    await check('html`` escapes a payload in the final interpolation slot', () => {
        // Guards an off-by-one in the tag's loop: a helper that stops one value
        // early looks correct on every literal whose last ${} is trusted.
        const out = String(mod.html`<td>${'ok'}</td><td>${PAYLOADS.script_tag}</td>`);
        assert(badTags(out).length === 0, `injected tag in ${JSON.stringify(out)}`);
        assert(out.includes('&lt;script&gt;'), `final value dropped or left raw: ${JSON.stringify(out)}`);
        return '';
    });

    await check('html`` escapes a payload in the first interpolation slot', () => {
        const out = String(mod.html`<td>${PAYLOADS.script_tag}</td><td>${'ok'}</td>`);
        assert(badTags(out).length === 0, `injected tag in ${JSON.stringify(out)}`);
        assert(out.includes('&lt;script&gt;'), `first value dropped or left raw: ${JSON.stringify(out)}`);
        return '';
    });

    await check('html`` preserves the static markup around interpolations', () => {
        const out = String(mod.html`<a class="x">${'v'}</a>`);
        assert(out === '<a class="x">v</a>', `got ${JSON.stringify(out)}`);
        return '';
    });

    // --- composition --------------------------------------------------------

    await check('html`` composes without double-escaping nested SafeHtml', () => {
        const inner = mod.html`<b>${'a&b'}</b>`;
        const out = String(mod.html`<div>${inner}</div>`);
        assert(out === '<div><b>a&amp;b</b></div>', `got ${JSON.stringify(out)}`);
        return '';
    });

    await check('html`` interpolates arrays of SafeHtml', () => {
        const rows = ['a', '<b>'].map((v) => mod.html`<li>${v}</li>`);
        const out = String(mod.html`<ul>${rows}</ul>`);
        assert(out === '<ul><li>a</li><li>&lt;b&gt;</li></ul>', `got ${JSON.stringify(out)}`);
        return '';
    });

    await check('html`` renders an empty array as nothing', () => {
        assert(String(mod.html`<ul>${[]}</ul>`) === '<ul></ul>', 'empty array should vanish');
        return '';
    });

    await check('html`` escapes a plain string that contains markup', () => {
        // The failure mode being designed out: a helper returns a raw HTML
        // string. It must be escaped -- visible breakage -- never injected.
        const out = String(mod.html`<div>${'<li>raw</li>'}</div>`);
        assert(tagNames(out).join(',') === 'div,div', `raw string was trusted: ${JSON.stringify(out)}`);
        return '';
    });

    // --- the sink -----------------------------------------------------------

    await check('setHtml rejects a plain string', () => {
        const el = {};
        let threw = false;
        try {
            mod.setHtml(el, '<img src=x onerror=alert(1)>');
        } catch (err) {
            // Not `instanceof TypeError`: the error is constructed inside the
            // vm context, so it fails instanceof against the host realm's
            // TypeError even though it is one.
            threw = Boolean(err) && err.name === 'TypeError';
        }
        assert(threw, 'setHtml accepted a plain string');
        assert(el.innerHTML === undefined, 'setHtml wrote to innerHTML anyway');
        return '';
    });

    await check('setHtml accepts SafeHtml and writes the escaped value', () => {
        const el = {};
        mod.setHtml(el, mod.html`<p>${'<x>'}</p>`);
        assert(el.innerHTML === '<p>&lt;x&gt;</p>', `got ${JSON.stringify(el.innerHTML)}`);
        return '';
    });

    await check('trustedHtml is the only bypass and returns SafeHtml', () => {
        const t = mod.trustedHtml('<b>x</b>');
        assert(t instanceof mod.SafeHtml, 'trustedHtml should return SafeHtml');
        const el = {};
        mod.setHtml(el, t);
        assert(el.innerHTML === '<b>x</b>', `got ${JSON.stringify(el.innerHTML)}`);
        return '';
    });

    // --- end to end through the real renderers ------------------------------

    const renderWith = async (fn, payload) => {
        mod.api.get = async () => payload;
        return String(await fn());
    };

    await check('renderUsers escapes username and email end-to-end', async () => {
        const out = await renderWith(mod.renderUsers, [{
            id: 7,
            username: '<img src=x onerror=alert(1)>',
            email: '" onfocus="alert(1)" autofocus x="',
            role: 'readonly',
            is_active: true,
            last_login: null
        }]);
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(tagNames(out).includes('tr'), 'the row did not render at all');
        assert(out.includes('&lt;img src=x onerror=alert(1)&gt;'), 'username not escaped as text');
        return '';
    });

    await check('renderAuditLogs escapes username, resource and ip end-to-end', async () => {
        const out = await renderWith(mod.renderAuditLogs, [{
            id: 1,
            created_at: '2026-01-01T00:00:00Z',
            username: '<script>alert(1)</script>',
            action: 'login_success',
            resource_type: '<iframe src=javascript:alert(1)>',
            resource_id: '"><script>alert(1)</script>',
            ip_address: '<svg onload=alert(1)>'
        }]);
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(tagNames(out).includes('code'), 'the row did not render at all');
        return '';
    });

    await check('renderAuditLogs escapes an unmapped action string', async () => {
        // formatAction() falls through to action.replace() for unknown actions,
        // so the raw server value reaches the DOM.
        const out = await renderWith(mod.renderAuditLogs, [{
            id: 1, created_at: null, username: 'x',
            action: '<img src=x onerror=alert(1)>',
            resource_type: 'user', resource_id: null, ip_address: '127.0.0.1'
        }]);
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        return '';
    });

    await check('renderMirrors escapes name, url_path and status end-to-end', async () => {
        const out = await renderWith(mod.renderMirrors, [{
            id: 1,
            name: '<script>alert(1)</script>',
            url_path: '"><img src=x onerror=alert(1)>',
            status: '" onmouseover="alert(1)',   // lands in class="status-badge ${...}"
            total_size_human: '<b>1 GB</b>',
            last_sync_completed: null
        }]);
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(tagNames(out).includes('tr'), 'the row did not render at all');
        return '';
    });

    await check('renderSettings escapes setting values in attribute context', async () => {
        const out = await renderWith(mod.renderSettings, [{
            key: 'sync_schedule',
            value: '" onfocus="alert(1)" autofocus x="',
            description: '<script>alert(1)</script>',
            updated_at: null
        }]);
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        const input = scanTags(out).find((t) => t.attrs.id === 'setting_sync_schedule');
        assert(input, 'the schedule input did not render');
        const keys = Object.keys(input.attrs).sort().join(',');
        assert(keys === 'class,id,placeholder,type,value', `attribute set became [${keys}]`);
        return '';
    });

    await check('renderLayout escapes the logged-in username in the sidebar', () => {
        mod.state.user = {
            id: 1,
            username: '<img src=x onerror=alert(1)>',
            role: '"><script>alert(1)</script>'
        };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(out.includes('<p>body</p>'), 'SafeHtml body was escaped instead of passed through');
        return '';
    });

    await check('Toast.show escapes a hostile server error string', () => {
        let written = null;
        const fakeToast = {
            className: '', style: {}, remove() {},
            set innerHTML(v) { written = v; },
            get innerHTML() { return written; }
        };
        sandbox.document.createElement = () => fakeToast;
        sandbox.document.getElementById = (id) =>
            (id === 'toastContainer' ? { appendChild: () => {} } : null);

        mod.Toast.show('<img src=x onerror=alert(1)>', 'error');

        assert(written !== null, 'Toast.show did not write');
        assert(badTags(written).length === 0, `injected tag: ${written}`);
        assert(badAttrs(written).length === 0, `injected attr: ${written}`);
        assert(written.includes('&lt;img src=x onerror=alert(1)&gt;'), `not escaped: ${written}`);
        return '';
    });

    await check('Modal.show escapes a hostile title and trusts SafeHtml body', () => {
        let written = null;
        const fakeModal = {
            set innerHTML(v) { written = v; },
            get innerHTML() { return written; }
        };
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };

        // viewMirror calls Modal.show(`Mirror: ${mirror.name}`, ...) with an
        // untagged literal -- a plain string, so the tag must escape it.
        mod.Modal.show('Mirror: <script>alert(1)</script>',
                       mod.html`<p>${'<b>'}</p>`,
                       mod.html`<button>Close</button>`);

        assert(written !== null, 'Modal.show did not write');
        assert(badTags(written).length === 0, `injected tag: ${written}`);
        assert(written.includes('&lt;script&gt;'), `title not escaped: ${written}`);
        assert(written.includes('<p>&lt;b&gt;</p>'), `body not passed through: ${written}`);
        assert(written.includes('<button>Close</button>'), `actions not passed through: ${written}`);
        return '';
    });

    process.stdout.write(JSON.stringify({ checks }, null, 2) + '\n');
}

main();
