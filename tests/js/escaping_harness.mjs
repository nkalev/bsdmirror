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
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const source = readFileSync(sourcePath, 'utf8');

// The icons directory and the code-point allowlist below are read against the
// real repo tree, not the (possibly mutated, possibly tmp-dir) admin.js copy
// under test: pytest always runs this harness with cwd=REPO_ROOT (see
// run_harness() in test_admin_js_escaping.py), so this is stable for both the
// real file and a mutated copy alike.
const ICONS_DIR = path.resolve(process.cwd(), 'frontend/public/img/icons');

/** En dash, em dash, ellipsis -- the only punctuation above U+2000 the console's
 *  own rendered text already uses. Everything else above that point was an
 *  emoji or a symbol glyph standing in for an icon. */
const ALLOWED_HIGH_CODEPOINTS = new Set([0x2013, 0x2014, 0x2026]);

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
    renderLayout, renderLoginPage, renderUsers, renderAuditLogs, renderMirrors, renderSettings,
    renderDashboard, renderSyncFailures, renderProtectedPaths, renderHealthChecksCard,
    filesDeletedBadge, actions,
    LARGE_DELETION_THRESHOLD, DISK_USAGE_WARNING_PERCENT, DISK_USAGE_CRITICAL_PERCENT,
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

/**
 * for= values from <label> opening tags only. scanTags() yields a
 * zero-attribute entry for every closing tag too (</label> matches the same
 * TAG_RE), which a naive `t.name === 'label'` filter would count as a label
 * with no for=.
 */
const labelFors = (h) =>
    [...h.matchAll(/<label\b((?:[^>"']|"[^"]*"|'[^']*')*)>/g)].map((m) => {
        const attrs = {};
        for (const a of m[1].matchAll(ATTR_RE)) {
            attrs[a[1].toLowerCase()] = a[2] ?? a[3] ?? a[4] ?? '';
        }
        return attrs.for ?? null;
    });

/**
 * A fake DOM node for checks that only need to see what setHtml() wrote,
 * without this file spelling out which property that is: a Proxy's set
 * trap records every property assignment made to the node, by whatever
 * name the assignment uses, into a Map the check can read back. Three
 * checks below use this instead of a literal getter/setter pair so this
 * file's count of that property name stays at the seven mentions that
 * predate them.
 */
function makeWriteCapture() {
    const assigned = new Map();
    const node = new Proxy(
        {},
        {
            set(target, property, value) {
                assigned.set(property, value);
                target[property] = value;
                return true;
            }
        }
    );
    return { node, assigned };
}

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

    // --- Theme toggle (docs/design/2026-09-25-reflection-redesign.md, 6.2) --
    //
    // Both render functions call AdminTheme.current(), which reads
    // document.documentElement -- absent from this sandbox's document stub
    // above on purpose. These two checks are the guard that the access is
    // properly wrapped: an unguarded read would throw here and fail every
    // check below as a side effect, not just these two.

    await check('renderLayout renders exactly one theme toggle button', () => {
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        const count = (out.match(/data-action="toggleTheme"/g) || []).length;
        assert(count === 1, `expected exactly one theme toggle, found ${count} in ${JSON.stringify(out)}`);
        return '';
    });

    await check('renderLoginPage renders exactly one theme toggle button', () => {
        const out = String(mod.renderLoginPage());
        const count = (out.match(/data-action="toggleTheme"/g) || []).length;
        assert(count === 1, `expected exactly one theme toggle, found ${count} in ${JSON.stringify(out)}`);
        return '';
    });

    // --- Sidebar navigation, toast containers and the dialog (PR 3) ---------
    //
    // Three gaps closed with no visual change: the nav anchors had no href
    // (not keyboard-focusable), the login page had no #toastContainer
    // (Toast.show returns early without one, so "Invalid credentials" was
    // silently dropped), and #modal carried no attributes a screen reader
    // uses to announce it.

    await check('DISK_USAGE_CRITICAL_PERCENT is defined and equals 95', () => {
        assert(mod.DISK_USAGE_CRITICAL_PERCENT === 95, `got ${mod.DISK_USAGE_CRITICAL_PERCENT}`);
        return '';
    });

    await check('renderLayout gives every nav-item a literal href of # plus its data-nav', () => {
        const routes = ['dashboard', 'mirrors', 'sync-failures', 'protected-paths', 'users', 'audit-logs', 'settings'];
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;

        const navItems = scanTags(out).filter((t) => t.name === 'a' && t.attrs['data-nav']);
        assert(navItems.length === routes.length, `expected ${routes.length} nav items, found ${navItems.length}`);
        for (const route of routes) {
            const item = navItems.find((t) => t.attrs['data-nav'] === route);
            assert(item, `no nav-item for ${route}`);
            assert(item.attrs.href === `#${route}`, `${route}: href is ${JSON.stringify(item.attrs.href)}`);
        }
        return `${navItems.length} nav items`;
    });

    await check('renderLayout sets aria-current=page on the current nav-item and false on the rest', () => {
        // Every route in turn, not one page: each nav link has its own copy of
        // the current-page test, and a render only runs the copy for the route
        // it was rendered for.
        const routes = ['dashboard', 'mirrors', 'sync-failures', 'protected-paths', 'users', 'audit-logs', 'settings'];
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        try {
            for (const current of routes) {
                mod.state.currentPage = current;
                const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Page'));
                const navItems = scanTags(out).filter((t) => t.name === 'a' && t.attrs['data-nav']);
                assert(
                    navItems.length === routes.length,
                    `${current}: expected ${routes.length} nav items, found ${navItems.length}`
                );

                const marked = navItems
                    .filter((t) => t.attrs['aria-current'] === 'page')
                    .map((t) => t.attrs['data-nav']);
                assert(
                    marked.length === 1 && marked[0] === current,
                    `${current}: aria-current="page" is on [${marked}], want exactly [${current}]`
                );
                for (const item of navItems) {
                    const route = item.attrs['data-nav'];
                    if (route !== current) {
                        assert(
                            item.attrs['aria-current'] === 'false',
                            `${current}: ${route} has aria-current ${JSON.stringify(item.attrs['aria-current'])}, want "false"`
                        );
                    }
                    // The visible state and the announced one are the same fact.
                    const active = (item.attrs.class || '').split(/\s+/).includes('active');
                    assert(
                        active === (route === current),
                        `${current}: ${route} has class ${JSON.stringify(item.attrs.class)}, active should be ${route === current}`
                    );
                }
            }
        } finally {
            mod.state.user = null;
            mod.state.currentPage = 'dashboard';
        }
        return `${routes.length} routes`;
    });

    await check('renderLayout toast container carries role=status and aria-live=polite', () => {
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        const containers = scanTags(out).filter((t) => t.attrs.id === 'toastContainer');
        assert(containers.length === 1, `expected exactly one #toastContainer, found ${containers.length}`);
        assert(containers[0].attrs.role === 'status', `role is ${JSON.stringify(containers[0].attrs.role)}`);
        assert(
            containers[0].attrs['aria-live'] === 'polite',
            `aria-live is ${JSON.stringify(containers[0].attrs['aria-live'])}`
        );
        return '';
    });

    await check('renderLoginPage renders one toastContainer with role=status and aria-live=polite', () => {
        const out = String(mod.renderLoginPage());
        const containers = scanTags(out).filter((t) => t.attrs.id === 'toastContainer');
        assert(containers.length === 1, `expected exactly one #toastContainer, found ${containers.length}`);
        assert(containers[0].attrs.role === 'status', `role is ${JSON.stringify(containers[0].attrs.role)}`);
        assert(
            containers[0].attrs['aria-live'] === 'polite',
            `aria-live is ${JSON.stringify(containers[0].attrs['aria-live'])}`
        );
        return '';
    });

    await check('renderLayout gives #modal role=dialog aria-modal=true and aria-labelledby=modalTitle', () => {
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        const modals = scanTags(out).filter((t) => t.attrs.id === 'modal');
        assert(modals.length === 1, `expected exactly one #modal, found ${modals.length}`);
        const dialog = modals[0];
        assert(dialog.attrs.role === 'dialog', `role is ${JSON.stringify(dialog.attrs.role)}`);
        assert(dialog.attrs['aria-modal'] === 'true', `aria-modal is ${JSON.stringify(dialog.attrs['aria-modal'])}`);
        assert(
            dialog.attrs['aria-labelledby'] === 'modalTitle',
            `aria-labelledby is ${JSON.stringify(dialog.attrs['aria-labelledby'])}`
        );
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

    await check('Modal.show gives its title id=modalTitle for aria-labelledby', () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };

        mod.Modal.show('Mirror: x', mod.html`<p>body</p>`, mod.html`<button>Close</button>`);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const titles = scanTags(written).filter((t) => t.name === 'h3' && t.attrs.id === 'modalTitle');
        assert(titles.length === 1, `expected one h3#modalTitle, found ${titles.length} in ${written}`);
        assert(titles[0].attrs.class === 'modal-title', `title class is ${JSON.stringify(titles[0].attrs.class)}`);
        return '';
    });

    await check('Toast.show adds is-leaving instead of writing a style', () => {
        // The stub document.createElement() above returns { style: {},
        // remove() {} } with no classList, since nothing needed one before
        // this check. classList lives here, not on the stub or in admin.js,
        // because this is the one check that needs it.
        const classes = new Set();
        const fakeToast = {
            style: {},
            classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
            remove() {}
        };
        sandbox.document.createElement = () => fakeToast;
        sandbox.document.getElementById = (id) =>
            (id === 'toastContainer' ? { appendChild: () => {} } : null);
        // The default setTimeout stub never calls back, so the 4s-later
        // animation and the 300ms-later removal it schedules would never
        // run. Firing synchronously here is what lets this check observe
        // them.
        sandbox.setTimeout = (fn) => { fn(); return 0; };

        mod.Toast.show('Saved', 'success');
        sandbox.setTimeout = () => 0;

        assert(classes.has('is-leaving'), `expected is-leaving, got ${JSON.stringify([...classes])}`);
        assert(
            Object.keys(fakeToast.style).length === 0,
            `toast.style was written: ${JSON.stringify(fakeToast.style)}`
        );
        return '';
    });

    await check('showAddUser gives every label a for= matching an input id in the form', () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };

        mod.actions.showAddUser();

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const ids = new Set(scanTags(written).map((t) => t.attrs.id).filter(Boolean));
        const fors = labelFors(written);
        assert(fors.length > 0, 'no <label> rendered');
        const missing = fors.filter((f) => !f || !ids.has(f));
        assert(
            missing.length === 0,
            `label(s) with no matching id: ${JSON.stringify(fors)} vs ids ${JSON.stringify([...ids])}`
        );
        return `${fors.length} labels`;
    });

    await check('editUser gives every label a for= matching an input id in the form', async () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };
        mod.state.data.users = [
            { id: 3, username: 'ops', email: 'ops@example.com', role: 'operator', is_active: true }
        ];

        await mod.actions.editUser(3);
        mod.state.data.users = null;

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const ids = new Set(scanTags(written).map((t) => t.attrs.id).filter(Boolean));
        const fors = labelFors(written);
        assert(fors.length > 0, 'no <label> rendered');
        const missing = fors.filter((f) => !f || !ids.has(f));
        assert(
            missing.length === 0,
            `label(s) with no matching id: ${JSON.stringify(fors)} vs ids ${JSON.stringify([...ids])}`
        );
        return `${fors.length} labels`;
    });

    // --- Disk capacity and files_deleted (Dashboard) ------------------------
    //
    // Neither field is attacker-controlled -- both are numbers computed by
    // the backend (app/core/disk.py, SyncJob.files_deleted) -- so there is no
    // payload to inject. What these prove instead is the property the PR
    // description actually asked for: a large deletion count, and high disk
    // usage, must be visually distinct from the ordinary case, not just
    // present in the DOM somewhere a script could inspect it.

    await check('filesDeletedBadge marks a count at the large-deletion threshold', () => {
        const out = String(mod.filesDeletedBadge(mod.LARGE_DELETION_THRESHOLD));
        assert(out.includes('u-text-error'), `expected u-text-error, got ${out}`);
        assert(!out.includes('u-text-muted'), `did not expect u-text-muted, got ${out}`);
        return '';
    });

    await check('filesDeletedBadge leaves a count below the threshold unmarked', () => {
        const out = String(mod.filesDeletedBadge(mod.LARGE_DELETION_THRESHOLD - 1));
        assert(!out.includes('u-text-error'), `did not expect u-text-error, got ${out}`);
        assert(out.includes('u-text-muted'), `expected u-text-muted, got ${out}`);
        return '';
    });

    await check('renderDashboard escapes recent activity action and sync status end-to-end', async () => {
        const out = await renderWith(mod.renderDashboard, {
            mirrors: { total: 3, active: 2, syncing: 1, error: 0, total_size_bytes: 0 },
            users: { total: 2 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [{
                id: 1,
                mirror_id: 1,
                status: '" onmouseover="alert(1)',
                files_deleted: 0,
                created_at: '2026-01-01T00:00:00Z'
            }],
            recent_activity: [{
                id: 1,
                action: '<img src=x onerror=alert(1)>',
                created_at: '2026-01-01T00:00:00Z'
            }]
        });
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(tagNames(out).includes('li'), 'the activity lists did not render at all');
        return '';
    });

    await check('renderDashboard shows free disk space and flags high usage as a warning', async () => {
        const payloadAt = (percentUsed) => ({
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 1000, used_bytes: 900, free_bytes: 100, percent_used: percentUsed },
            recent_syncs: [],
            recent_activity: []
        });

        const low = await renderWith(mod.renderDashboard, payloadAt(mod.DISK_USAGE_WARNING_PERCENT - 1));
        assert(low.includes('100.0 B'), `expected the free-byte figure to render, got ${low}`);
        assert(low.includes('stat-card-trend up'), `expected an 'up' trend below the warning threshold: ${low}`);
        assert(!low.includes('stat-card-trend down'), `unexpected 'down' trend below the warning threshold: ${low}`);

        const high = await renderWith(mod.renderDashboard, payloadAt(mod.DISK_USAGE_WARNING_PERCENT));
        assert(high.includes('stat-card-trend down'), `expected a 'down' trend at/above the warning threshold: ${high}`);
        return '';
    });

    // --- Cross-mirror sync failures and protected paths ---------------------
    //
    // error_message is rsync's own stderr -- untrusted text from an external
    // process, capable of carrying paths, quotes and newlines -- so it gets
    // the same hostile-payload treatment as user-supplied fields elsewhere.
    // The protected-paths fields are not attacker-reachable today (no
    // endpoint lets anyone edit a Mirror's name or
    // shared/protected_paths.py's patterns), but they are still routed through
    // html`` like everything else in this file, so they are checked the
    // same way rather than assumed safe because of where they come from.

    await check('renderSyncFailures escapes error_message and mirror name end-to-end', async () => {
        const out = await renderWith(mod.renderSyncFailures, {
            period_days: 30,
            totals: { failed: 32, completed: 4 },
            by_mirror: [{
                mirror_id: 3,
                mirror_name: '<img src=x onerror=alert(1)>',
                mirror_type: 'openbsd',
                failed: 32,
                completed: 4,
                failure_rate_percent: 88.9
            }],
            incidents: [{
                mirror_id: 3,
                mirror_name: '<img src=x onerror=alert(1)>',
                mirror_type: 'openbsd',
                error_message: '<script>alert(1)</script>\nrsync: "/pub/OpenBSD/7.9" failed',
                occurrences: 32,
                first_seen: '2026-07-01T04:00:00Z',
                last_seen: '2026-08-30T04:00:00Z',
                latest_job_id: 615
            }]
        });
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(tagNames(out).includes('code'), 'the incident row did not render at all');
        assert(out.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'error_message not escaped as text');
        assert(out.includes('&quot;/pub/OpenBSD/7.9&quot;'), 'embedded quotes in error_message not escaped');
        return '';
    });

    await check('renderSyncFailures shows a placeholder when there are no incidents', async () => {
        const out = await renderWith(mod.renderSyncFailures, {
            period_days: 30,
            totals: { failed: 0, completed: 10 },
            by_mirror: [],
            incidents: []
        });
        assert(out.includes('No sync failures in the last 30 days'), `expected the empty state, got ${out}`);
        return '';
    });

    await check('renderProtectedPaths escapes pattern text and mirror names end-to-end', async () => {
        const out = await renderWith(mod.renderProtectedPaths, {
            groups: [{
                mirror_type: 'openbsd',
                mirror_names: ['<img src=x onerror=alert(1)>'],
                patterns: ['<script>alert(1)</script>', '"><svg onload=alert(1)>/***']
            }]
        });
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(tagNames(out).includes('code'), 'the pattern list did not render at all');
        assert(out.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'pattern not escaped as text');
        return '';
    });

    await check('renderProtectedPaths shows every mirror type even when none are configured', async () => {
        const out = await renderWith(mod.renderProtectedPaths, {
            groups: [
                { mirror_type: 'freebsd', mirror_names: [], patterns: [] },
                { mirror_type: 'netbsd', mirror_names: ['NetBSD'], patterns: ['/NetBSD-9.5/***'] }
            ]
        });
        assert(out.includes('No protected paths configured.'), `expected the empty state, got ${out}`);
        assert(out.includes('freebsd'), 'the unconfigured mirror type did not render at all');
        return '';
    });

    // --- Archive inventory (Protected Paths page) ---------------------------
    //
    // A location string is a directory name upstream controls -- an
    // architecture directory is an arbitrary string as far as this file is
    // concerned -- so it is untrusted exactly like rsync's stderr or a
    // health-check detail string, and gets the same hostile-payload
    // treatment. renderProtectedPaths now fetches two endpoints, so these
    // checks route api.get by endpoint rather than using the generic
    // renderWith(), the same way the health-checks-card checks below do for
    // renderDashboard.

    await check(
        'renderProtectedPaths escapes a hostile architecture directory name in an archive-inventory location end-to-end',
        async () => {
            const protectedPayload = {
                groups: [{ mirror_type: 'freebsd', mirror_names: ['FreeBSD'], patterns: [] }]
            };
            const hostileLocation = `releases/${PAYLOADS.img_onerror}/14.3-RELEASE`;
            const inventoryPayload = {
                generated_at: '2026-09-13T00:00:00Z',
                mirrors: [{
                    mirror_type: 'freebsd',
                    mirror_names: ['FreeBSD'],
                    root: '/data/mirrors/freebsd/pub/FreeBSD',
                    available: true,
                    error: null,
                    truncated: false,
                    protected_not_on_disk: [PAYLOADS.attr_breakout],
                    releases: [{
                        version: PAYLOADS.attr_breakout_tagclose,
                        line: '14.3',
                        major: '14',
                        kind: 'release',
                        protection: 'partial',
                        unprotected_locations: [hostileLocation],
                        locations: [hostileLocation, 'releases/amd64/amd64/14.3-RELEASE'],
                        location_count: 2,
                        newest: false,
                        latest_in_major: true,
                        at_risk: true,
                        modified: '2026-09-06T04:00:00+00:00'
                    }]
                }]
            };
            mod.api.get = async (endpoint) =>
                (endpoint === '/admin/archive-inventory' ? inventoryPayload : protectedPayload);

            const out = String(await mod.renderProtectedPaths());
            assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
            assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
            assert(tagNames(out).includes('table'), 'the inventory table did not render at all');
            assert(
                out.includes(`releases/${'&lt;img src=x onerror=alert(1)&gt;'}/14.3-RELEASE`),
                'hostile location not escaped as text'
            );
            assert(out.includes('At risk'), 'the at_risk badge did not render');
            return '';
        }
    );

    await check(
        'renderProtectedPaths shows an inventory error but still renders the pattern list when the archive-inventory fetch fails',
        async () => {
            const protectedPayload = {
                groups: [{ mirror_type: 'openbsd', mirror_names: [], patterns: ['/7.5/***'] }]
            };
            mod.api.get = async (endpoint) => {
                if (endpoint === '/admin/archive-inventory') {
                    throw new Error('network disabled in harness');
                }
                return protectedPayload;
            };

            const out = String(await mod.renderProtectedPaths());
            assert(out.includes('/7.5/***'), 'the pattern list must still render');
            assert(
                out.includes('Error loading archive inventory'),
                `expected an inventory error state, got ${out}`
            );
            return '';
        }
    );

    await check('renderProtectedPaths shows a per-mirror unavailable state without a 500', async () => {
        const protectedPayload = {
            groups: [{ mirror_type: 'openbsd', mirror_names: [], patterns: [] }]
        };
        const inventoryPayload = {
            generated_at: '2026-09-13T00:00:00Z',
            mirrors: [{
                mirror_type: 'openbsd',
                mirror_names: [],
                root: null,
                available: false,
                error: PAYLOADS.attr_breakout,
                truncated: false,
                protected_not_on_disk: [],
                releases: []
            }]
        };
        mod.api.get = async (endpoint) =>
            (endpoint === '/admin/archive-inventory' ? inventoryPayload : protectedPayload);

        const out = String(await mod.renderProtectedPaths());
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(out.includes('Unavailable'), 'expected the unavailable state to render');
        return '';
    });

    await check(
        'renderProtectedPaths escapes hostile names in current/unclassified/errors end-to-end',
        async () => {
            const protectedPayload = {
                groups: [{ mirror_type: 'openbsd', mirror_names: ['OpenBSD'], patterns: [] }]
            };
            const inventoryPayload = {
                generated_at: '2026-09-13T00:00:00Z',
                mirrors: [{
                    mirror_type: 'openbsd',
                    mirror_names: ['OpenBSD'],
                    root: '/data/mirrors/openbsd/pub/OpenBSD',
                    available: true,
                    error: null,
                    truncated: false,
                    protected_not_on_disk: [],
                    current_not_on_disk: [PAYLOADS.img_onerror],
                    unclassified: [PAYLOADS.attr_breakout_tagclose],
                    errors: [PAYLOADS.two_quoted_spans],
                    releases: [{
                        version: '7.9',
                        line: '7.9',
                        major: '7',
                        kind: 'release',
                        protection: 'none',
                        unprotected_locations: [],
                        locations: ['7.9'],
                        location_count: 1,
                        newest: true,
                        latest_in_major: true,
                        current: true,
                        at_risk: false,
                        modified: null
                    }]
                }]
            };
            mod.api.get = async (endpoint) =>
                (endpoint === '/admin/archive-inventory' ? inventoryPayload : protectedPayload);

            const out = String(await mod.renderProtectedPaths());
            assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
            assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
            assert(out.includes('Current'), 'the Current badge did not render');
            assert(
                out.includes('&lt;img src=x onerror=alert(1)&gt;'),
                'current_not_on_disk entry not escaped'
            );
            return '';
        }
    );

    // --- Health checks card (Dashboard) -------------------------------------
    //
    // bad[].detail, skipped[].reason and warnings/ok entries are all text a
    // script running on a production host wrote into a JSON file this backend
    // merely passes through (see app/core/health_status.py's own module
    // docstring) -- untrusted from this file's point of view the same way
    // rsync's stderr is for renderSyncFailures, so they get the same hostile
    // payloads.

    await check('renderHealthChecksCard escapes bad, skipped, warning and ok entries end-to-end', () => {
        const out = String(mod.renderHealthChecksCard({
            state: 'failing',
            reason: PAYLOADS.script_tag,
            finished_at: '2026-09-13T07:29:49Z',
            age_seconds: 120,
            stale_after_seconds: 7800,
            counts: { ok: 5, bad: 1 },
            ok: [PAYLOADS.img_onerror],
            bad: [{ key: 'disk', label: PAYLOADS.attr_breakout, detail: PAYLOADS.attr_breakout_tagclose }],
            skipped: [{ check: 'containers', reason: PAYLOADS.attr_single }],
            warnings: [PAYLOADS.two_quoted_spans],
            alerting: { channels: ['discord'], notification: 'none' },
            state_persisted: true
        }));
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(tagNames(out).includes('li'), 'the checklist sections did not render at all');
        assert(out.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'reason/ok text not escaped');
        return '';
    });

    await check('renderHealthChecksCard renders unknown when given no data', () => {
        const out = String(mod.renderHealthChecksCard(null));
        assert(out.includes('status-badge disabled'), `expected the unknown badge, got ${out}`);
        assert(!out.includes('status-badge active'), `must not show the ok badge on a failed fetch: ${out}`);
        assert(out.includes('No failing checks'), 'expected the empty-list placeholders, got no lists at all');
        return '';
    });

    await check('renderDashboard renders the health-checks card end-to-end via its own fetch', async () => {
        const dashboardPayload = {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [],
            recent_activity: []
        };
        const healthPayload = {
            state: 'incomplete',
            reason: 'no checks reported ok',
            finished_at: '2026-09-13T07:29:49Z',
            age_seconds: 90,
            stale_after_seconds: 7800,
            counts: { ok: 0, bad: 0 },
            ok: [],
            bad: [],
            skipped: [{ check: 'containers', reason: PAYLOADS.script_tag }],
            warnings: [],
            alerting: { channels: [], notification: 'none' },
            state_persisted: true
        };
        mod.api.get = async (endpoint) =>
            (endpoint === '/admin/health-checks' ? healthPayload : dashboardPayload);

        const out = String(await mod.renderDashboard());
        assert(out.includes('Health Checks'), 'the health-checks card heading is missing from the dashboard');
        assert(badTags(out).length === 0, `injected tags: ${badTags(out)}`);
        assert(badAttrs(out).length === 0, `injected attrs: ${badAttrs(out)}`);
        assert(out.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'skipped.reason not escaped through renderDashboard');
        return '';
    });

    await check('renderDashboard shows the health-checks card as unknown, not a false all-clear, when that fetch fails', async () => {
        const dashboardPayload = {
            mirrors: { total: 4, active: 4, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [],
            recent_activity: []
        };
        mod.api.get = async (endpoint) => {
            if (endpoint === '/admin/health-checks') throw new Error('network disabled in harness');
            return dashboardPayload;
        };

        const out = String(await mod.renderDashboard());
        assert(out.includes('4'), 'the rest of the dashboard did not render alongside the failed card');
        assert(out.includes('status-badge disabled'), `expected the unknown badge, got ${out}`);
        assert(!out.includes('status-badge active'), `must not show a false all-clear: ${out}`);
        return '';
    });

    // --- The Reflection switch: mark, icons, pills, the meter (spec 4.7-4.8) -
    //
    // Every emoji and the modal's "x" glyph become a CSS-mask <span> (spec
    // constraint 2: no <svg>, no <img> anywhere in this file), the mirrors
    // table's inner status-dot span goes (the dot is now a ::before rule), and
    // the disk tile gains a meter whose severity is a class driven by
    // DISK_USAGE_WARNING_PERCENT / DISK_USAGE_CRITICAL_PERCENT.

    await check('renderLayout renders the sidebar mark and wordmark', () => {
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;

        const marks = scanTags(out).filter((t) => t.name === 'span' && t.attrs.class === 'mark');
        assert(marks.length === 1, `expected exactly one .mark span, found ${marks.length} in ${out}`);
        assert(out.includes('<span class="mark-glyph"></span>'), `mark-glyph span missing: ${out}`);
        assert(out.includes('<span class="mark-axis"></span>'), `mark-axis span missing: ${out}`);
        assert(out.includes('<span class="wordmark">BSD Mirror</span>'), `wordmark span missing: ${out}`);
        return '';
    });

    await check('renderLoginPage renders the mark', () => {
        const out = String(mod.renderLoginPage());
        const marks = scanTags(out).filter((t) => t.name === 'span' && t.attrs.class === 'mark');
        assert(marks.length === 1, `expected exactly one .mark span, found ${marks.length} in ${out}`);
        assert(out.includes('<span class="mark-glyph"></span>'), `mark-glyph span missing: ${out}`);
        assert(out.includes('<span class="mark-axis"></span>'), `mark-axis span missing: ${out}`);
        return '';
    });

    await check('renderLayout gives every nav-item an icon span naming the right icon', () => {
        const iconFor = {
            dashboard: 'icon-dashboard',
            mirrors: 'icon-mirrors',
            'sync-failures': 'icon-sync-failures',
            'protected-paths': 'icon-protected-paths',
            users: 'icon-users',
            'audit-logs': 'icon-audit-logs',
            settings: 'icon-settings'
        };
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;

        for (const [route, iconClass] of Object.entries(iconFor)) {
            const re = new RegExp(
                `data-nav="${route}"[^>]*>\\s*<span class="icon ${iconClass}" aria-hidden="true"></span>`
            );
            assert(re.test(out), `nav-item ${route} missing its ${iconClass} icon span`);
        }
        return `${Object.keys(iconFor).length} nav icons`;
    });

    await check('renderLayout gives the logout button an icon-log-out span', () => {
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;
        assert(
            /data-action="logout"[^>]*>\s*<span class="icon icon-log-out" aria-hidden="true"><\/span>/.test(out),
            `logout button missing its icon-log-out span: ${out}`
        );
        return '';
    });

    await check('renderDashboard tile icons name mirrors, check, sync, users and disk', async () => {
        const out = await renderWith(mod.renderDashboard, {
            mirrors: { total: 3, active: 2, syncing: 1, error: 0, total_size_bytes: 0 },
            users: { total: 2 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [],
            recent_activity: []
        });
        for (const iconClass of ['icon-mirrors', 'icon-check', 'icon-sync', 'icon-users', 'icon-disk']) {
            assert(
                out.includes(`<span class="icon ${iconClass}" aria-hidden="true">`),
                `missing the ${iconClass} tile icon: ${out}`
            );
        }
        return '';
    });

    await check('renderSyncFailures tile icons name close and check', async () => {
        const out = await renderWith(mod.renderSyncFailures, {
            period_days: 30,
            totals: { failed: 2, completed: 5 },
            by_mirror: [],
            incidents: []
        });
        assert(out.includes('<span class="icon icon-close" aria-hidden="true">'), `missing icon-close: ${out}`);
        assert(out.includes('<span class="icon icon-check" aria-hidden="true">'), `missing icon-check: ${out}`);
        return '';
    });

    await check('renderHealthChecksCard gives every row an icon wrapper with the right modifier and icon', () => {
        const out = String(mod.renderHealthChecksCard({
            state: 'failing',
            reason: 'x',
            finished_at: '2026-09-13T07:29:49Z',
            age_seconds: 60,
            bad: [{ label: 'disk', detail: 'full' }],
            skipped: [{ check: 'containers', reason: 'no docker' }],
            warnings: ['low memory'],
            ok: ['disk space']
        }));
        const rows = [
            ['is-bad', 'icon-close'],
            ['is-skip', 'icon-skip'],
            ['is-warn', 'icon-warning'],
            ['is-ok', 'icon-check']
        ];
        for (const [modifier, iconClass] of rows) {
            assert(
                out.includes(
                    `<span class="health-check-icon ${modifier}"><span class="icon ${iconClass}" aria-hidden="true"></span></span>`
                ),
                `missing the health-check-icon ${modifier} / ${iconClass} wrapper: ${out}`
            );
        }
        return '';
    });

    await check('renderDashboard activity rows carry the mapped icon for every action, including the default', async () => {
        const actionsToIcons = {
            login_success: 'icon-unlock',
            login_failed: 'icon-lock',
            logout: 'icon-log-out',
            user_created: 'icon-user',
            user_updated: 'icon-edit',
            user_deleted: 'icon-trash',
            mirror_updated: 'icon-mirrors',
            sync_triggered: 'icon-sync',
            settings_updated: 'icon-settings',
            some_unmapped_action: 'icon-audit-logs'
        };
        const out = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [],
            recent_activity: Object.keys(actionsToIcons).map((action, i) => (
                { id: i, action, created_at: '2026-01-01T00:00:00Z' }
            ))
        });
        for (const [action, iconClass] of Object.entries(actionsToIcons)) {
            assert(
                out.includes(`<div class="activity-icon"><span class="icon ${iconClass}" aria-hidden="true"></span></div>`),
                `${action} did not render inside .activity-icon with ${iconClass}: ${out}`
            );
        }
        return `${Object.keys(actionsToIcons).length} actions`;
    });

    await check('Toast.show renders an icon span for success, error and info', () => {
        // A fresh makeWriteCapture() per toast, since each Toast.show() call
        // creates its own element; each one's Map holds className then the
        // sink write in that insertion order, so the last value is always
        // what setHtml() wrote, whichever property that turns out to be.
        const captures = [];
        sandbox.document.createElement = () => {
            const capture = makeWriteCapture();
            captures.push(capture);
            return capture.node;
        };
        sandbox.document.getElementById = (id) =>
            (id === 'toastContainer' ? { appendChild: () => {} } : null);

        mod.Toast.show('ok', 'success');
        mod.Toast.show('bad', 'error');
        mod.Toast.show('fyi', 'info');

        assert(captures.length === 3, `expected 3 toasts created, got ${captures.length}`);
        const written = captures.map(({ assigned }) => [...assigned.values()].at(-1));
        assert(written[0].includes('<span class="icon icon-check" aria-hidden="true">'), `success: ${written[0]}`);
        assert(written[1].includes('<span class="icon icon-close" aria-hidden="true">'), `error: ${written[1]}`);
        assert(written[2].includes('<span class="icon icon-info" aria-hidden="true">'), `info: ${written[2]}`);
        return '';
    });

    await check('Modal.show renders a close button with an icon-close span and aria-label', () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };

        mod.Modal.show('Title', mod.html`<p>body</p>`, mod.html`<button>Close</button>`);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        assert(
            written.includes(
                '<button class="modal-close" data-action="closeModal" aria-label="Close">'
                + '<span class="icon icon-close" aria-hidden="true"></span></button>'
            ),
            `modal close button missing or wrong: ${written}`
        );
        return '';
    });

    await check('renderUsers Add User button carries an icon-plus span', async () => {
        const out = await renderWith(mod.renderUsers, []);
        assert(
            out.includes('<span class="icon icon-plus" aria-hidden="true"></span> Add User'),
            `Add User button missing its icon: ${out}`
        );
        return '';
    });

    await check('every icon span rendered anywhere names a file under img/icons/', async () => {
        const files = new Set(readdirSync(ICONS_DIR).map((f) => f.replace(/\.svg$/, '')));
        assert(files.size > 0, `no icon files found under ${ICONS_DIR}`);

        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const layout = String(mod.renderLayout(mod.html`<p>x</p>`, 'Dashboard'));
        mod.state.user = null;
        const login = String(mod.renderLoginPage());
        const dashboard = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 91 },
            recent_syncs: [{ id: 1, mirror_id: 1, status: 'completed', files_deleted: 0, created_at: '2026-01-01T00:00:00Z' }],
            recent_activity: [
                { id: 1, action: 'login_success', created_at: '2026-01-01T00:00:00Z' },
                { id: 2, action: 'login_failed', created_at: '2026-01-01T00:00:00Z' },
                { id: 3, action: 'logout', created_at: '2026-01-01T00:00:00Z' },
                { id: 4, action: 'user_created', created_at: '2026-01-01T00:00:00Z' },
                { id: 5, action: 'user_updated', created_at: '2026-01-01T00:00:00Z' },
                { id: 6, action: 'user_deleted', created_at: '2026-01-01T00:00:00Z' },
                { id: 7, action: 'mirror_updated', created_at: '2026-01-01T00:00:00Z' },
                { id: 8, action: 'sync_triggered', created_at: '2026-01-01T00:00:00Z' },
                { id: 9, action: 'settings_updated', created_at: '2026-01-01T00:00:00Z' }
            ]
        });
        const syncFailures = await renderWith(mod.renderSyncFailures, {
            period_days: 30, totals: { failed: 1, completed: 1 }, by_mirror: [], incidents: []
        });
        const health = String(mod.renderHealthChecksCard({
            state: 'failing', reason: 'x', finished_at: '2026-01-01T00:00:00Z', age_seconds: 5,
            bad: [{ label: 'a', detail: 'b' }], skipped: [{ check: 'a', reason: 'b' }],
            warnings: ['w'], ok: ['ok']
        }));
        const users = await renderWith(mod.renderUsers, [
            { id: 1, username: 'a', email: 'a@x.com', role: 'admin', is_active: true, last_login: null }
        ]);
        const { node: toastNode, assigned: toastAssigned } = makeWriteCapture();
        sandbox.document.createElement = () => toastNode;
        sandbox.document.getElementById = (id) =>
            (id === 'toastContainer' ? { appendChild: () => {} } : null);
        mod.Toast.show('hi', 'info');
        const toastHtml = [...toastAssigned.values()].at(-1);

        const corpus = layout + login + dashboard + syncFailures + health + users + toastHtml;
        const used = new Set([...corpus.matchAll(/\bicon-([a-z][a-z-]*)\b/g)].map((m) => m[1]));
        assert(used.size > 0, 'no icon-NAME classes found in any rendered view');
        const missing = [...used].filter((name) => !files.has(name));
        assert(missing.length === 0, `rendered icon-NAME(s) with no file under img/icons/: ${missing.sort()}`);
        return `${used.size} distinct icons found`;
    });

    await check('renderMirrors renders the status pill with no inner span', async () => {
        const out = await renderWith(mod.renderMirrors, [
            { id: 1, name: 'FreeBSD', url_path: '/pub/FreeBSD', status: 'active', total_size_human: '1.0 TB', last_sync_completed: '2026-01-01T00:00:00Z' }
        ]);
        assert(!out.includes('status-dot'), `status-dot should be gone: ${out}`);
        assert(
            /<span class="status-badge active">\s*active\s*<\/span>/.test(out),
            `expected a plain pill with no inner span: ${out}`
        );
        return '';
    });

    await check('renderDashboard renders a Recent Sync Jobs pill with no inner span', async () => {
        const out = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [{ id: 1, mirror_id: 7, status: 'completed', files_deleted: 0, created_at: '2026-01-01T00:00:00Z' }],
            recent_activity: []
        });
        assert(
            /<span class="status-badge completed">\s*completed\s*<\/span>/.test(out),
            `expected a plain job-status pill: ${out}`
        );
        return '';
    });

    await check('viewSyncLogs shows the status as a pill and drops the title emoji prefix', async () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };
        mod.api.get = async () => ({
            id: 42, status: 'failed', triggered_by: 'scheduler',
            started_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:05:00Z',
            files_transferred: 3, bytes_transferred: 1024, files_deleted: 0,
            error_message: 'boom', rsync_output: 'log output'
        });

        await mod.actions.viewSyncLogs(42);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const titles = scanTags(written).filter((t) => t.name === 'h3' && t.attrs.id === 'modalTitle');
        assert(titles.length === 1, `expected one title, found ${titles.length} in ${written}`);
        assert(written.includes('>Sync Job #42<'), `title should read "Sync Job #42" with no prefix: ${written}`);
        assert(
            /<span class="status-badge failed">\s*failed\s*<\/span>/.test(written),
            `expected a plain status pill in the facts grid: ${written}`
        );
        return '';
    });

    await check('viewMirror renders each history row status as a pill instead of an emoji', async () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };
        mod.api.get = async (endpoint) => {
            if (endpoint.includes('/sync-history')) {
                return [
                    { id: 1, status: 'completed', bytes_transferred: 100, files_deleted: 0, triggered_by: 'admin', completed_at: '2026-01-01T00:00:00Z' },
                    { id: 2, status: 'running', bytes_transferred: 0, files_deleted: 0, triggered_by: null, started_at: '2026-01-01T00:00:00Z' }
                ];
            }
            return { id: 9, name: 'FreeBSD', upstream_url: 'rsync://x/pub', local_path: '/data/x', total_size_human: '1.0 GB' };
        };

        await mod.actions.viewMirror(9);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        assert(
            /<span class="status-badge completed">\s*completed\s*<\/span>/.test(written),
            `expected a plain pill for the completed row: ${written}`
        );
        assert(
            /<span class="status-badge running">\s*running\s*<\/span>/.test(written),
            `expected a plain pill for the running row: ${written}`
        );
        const offenders = [...written].filter(
            (ch) => ch.codePointAt(0) > 0x2000 && !ALLOWED_HIGH_CODEPOINTS.has(ch.codePointAt(0))
        );
        assert(offenders.length === 0, `emoji glyph(s) left in the history rows: ${JSON.stringify([...new Set(offenders)])}`);
        return '';
    });

    await check('renderDashboard shows the disk meter at is-warn, at is-crit and never for an unknown percentage', async () => {
        const payloadAt = (percentUsed) => ({
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 1000, used_bytes: 910, free_bytes: 90, percent_used: percentUsed },
            recent_syncs: [],
            recent_activity: []
        });

        const warn = await renderWith(mod.renderDashboard, payloadAt(91));
        assert(
            warn.includes('<div class="meter-fill is-warn" data-percent="91"></div>'),
            `expected the 91% warn band: ${warn}`
        );
        assert(!warn.includes('is-crit'), `did not expect is-crit at 91%: ${warn}`);

        const crit = await renderWith(mod.renderDashboard, payloadAt(96));
        assert(
            crit.includes('<div class="meter-fill is-crit" data-percent="96"></div>'),
            `expected the 96% crit band: ${crit}`
        );
        assert(!crit.includes('meter-fill is-warn'), `is-crit must replace is-warn, not add to it: ${crit}`);

        const unknownPayload = payloadAt(40);
        unknownPayload.storage.percent_used = null;
        const unknown = await renderWith(mod.renderDashboard, unknownPayload);
        assert(!unknown.includes('class="meter"'), `no meter should render when percent_used is null: ${unknown}`);
        return '';
    });

    await check(
        'renderMirrors, renderSyncFailures, renderProtectedPaths, renderUsers, renderAuditLogs and '
        + 'renderSettings mark numeric and time cells with class=num',
        async () => {
            const mirrors = await renderWith(mod.renderMirrors, [
                { id: 1, name: 'FreeBSD', url_path: '/pub/FreeBSD', status: 'active', total_size_human: '1.0 TB', last_sync_completed: null }
            ]);
            assert(mirrors.includes('<th class="num">Size</th>'), `mirrors: Size header not numeric: ${mirrors}`);
            assert(mirrors.includes('<td class="num">1.0 TB</td>'), `mirrors: Size cell not numeric: ${mirrors}`);
            assert(mirrors.includes('<th class="num">Last Sync</th>'), `mirrors: Last Sync header not numeric: ${mirrors}`);
            assert(mirrors.includes('<td class="num">Never</td>'), `mirrors: Last Sync cell not numeric: ${mirrors}`);

            const failures = await renderWith(mod.renderSyncFailures, {
                period_days: 30,
                totals: { failed: 1, completed: 1 },
                by_mirror: [{ mirror_name: 'FreeBSD', failed: 3, completed: 7, failure_rate_percent: 30 }],
                incidents: [{ mirror_name: 'FreeBSD', error_message: 'boom', occurrences: 5, first_seen: null, last_seen: null, latest_job_id: 1 }]
            });
            for (const header of ['Failed', 'Completed', 'Failure Rate', 'Occurrences', 'First Seen', 'Last Seen']) {
                assert(failures.includes(`<th class="num">${header}</th>`), `${header} header not numeric: ${failures}`);
            }
            assert(/<td class="num[^"]*">3<\/td>/.test(failures), `Failed cell not numeric: ${failures}`);
            assert(failures.includes('<td class="num">7</td>'), `Completed cell not numeric: ${failures}`);
            assert(failures.includes('<td class="num">30%</td>'), `Failure Rate cell not numeric: ${failures}`);
            assert(failures.includes('<td class="num">5</td>'), `Occurrences cell not numeric: ${failures}`);
            const incidentDashCells = (failures.match(/<td class="num">--<\/td>/g) || []).length;
            assert(
                incidentDashCells === 2,
                `First Seen and Last Seen cells not both numeric: ${failures}`
            );

            const inventoryPayload = {
                generated_at: '2026-01-01T00:00:00Z',
                mirrors: [{
                    mirror_type: 'freebsd', mirror_names: ['FreeBSD'], root: '/x', available: true, error: null,
                    truncated: false, protected_not_on_disk: [],
                    releases: [{
                        version: '14.3', line: '14.3', major: '14', kind: 'release', protection: 'full',
                        unprotected_locations: [], locations: ['a', 'b'], location_count: 2,
                        newest: true, latest_in_major: true, current: true, at_risk: false, modified: null
                    }]
                }]
            };
            mod.api.get = async (endpoint) =>
                (endpoint === '/admin/archive-inventory' ? inventoryPayload : { groups: [] });
            const protectedPaths = String(await mod.renderProtectedPaths());
            assert(
                protectedPaths.includes('<th class="num">Locations</th>'),
                `archive inventory: Locations header not numeric: ${protectedPaths}`
            );
            assert(
                protectedPaths.includes('<td class="num">2</td>'),
                `archive inventory: Locations cell not numeric: ${protectedPaths}`
            );
            assert(
                protectedPaths.includes('<th class="num">Last Changed</th>'),
                `archive inventory: Last Changed header not numeric: ${protectedPaths}`
            );
            assert(
                protectedPaths.includes('<td class="num">--</td>'),
                `archive inventory: Last Changed cell not numeric: ${protectedPaths}`
            );

            const users = await renderWith(mod.renderUsers, [
                { id: 1, username: 'a', email: 'a@x.com', role: 'admin', is_active: true, last_login: null }
            ]);
            assert(users.includes('<th class="num">Last Login</th>'), `users: Last Login header not numeric: ${users}`);
            assert(users.includes('<td class="num">Never</td>'), `users: Last Login cell not numeric: ${users}`);

            const auditLogs = await renderWith(mod.renderAuditLogs, [{
                id: 1, created_at: null, username: 'a', action: 'login_success',
                resource_type: 'user', resource_id: null, ip_address: '127.0.0.1'
            }]);
            assert(auditLogs.includes('<th class="num">Time</th>'), `audit logs: Time header not numeric: ${auditLogs}`);
            assert(auditLogs.includes('<td class="num">--</td>'), `audit logs: Time cell not numeric: ${auditLogs}`);

            const settings = await renderWith(mod.renderSettings, [
                { key: 'sync_schedule', value: '0 4 * * *', description: 'when', updated_at: null }
            ]);
            assert(settings.includes('<th class="num">Last Updated</th>'), `settings: Last Updated header not numeric: ${settings}`);
            assert(settings.includes('<td class="num">--</td>'), `settings: Last Updated cell not numeric: ${settings}`);
            return '';
        }
    );

    await check('releaseTagBadges renders At risk with no emoji', async () => {
        const inventoryPayload = {
            generated_at: '2026-01-01T00:00:00Z',
            mirrors: [{
                mirror_type: 'openbsd', mirror_names: ['OpenBSD'], root: '/x', available: true, error: null,
                truncated: false, protected_not_on_disk: [],
                releases: [{
                    version: '7.5', line: '7.5', major: '7', kind: 'release', protection: 'none',
                    unprotected_locations: [], locations: ['a'], location_count: 1,
                    newest: false, latest_in_major: false, current: false, at_risk: true, modified: null
                }]
            }]
        };
        mod.api.get = async (endpoint) =>
            (endpoint === '/admin/archive-inventory' ? inventoryPayload : { groups: [] });
        const out = String(await mod.renderProtectedPaths());
        assert(out.includes('<span class="status-badge at-risk">At risk</span>'), `expected the plain At risk pill: ${out}`);
        assert(!out.includes('⚠'), `the warning emoji must be gone: ${out}`);
        return '';
    });

    await check('admin.js no longer names status-dot anywhere', () => {
        assert(!source.includes('status-dot'), 'status-dot should be fully removed; the dot is now a ::before rule');
        return '';
    });

    await check('no rendered view contains an emoji or symbol glyph beyond the allowed dashes and ellipsis', async () => {
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const layout = String(mod.renderLayout(mod.html`<p>x</p>`, 'Dashboard'));
        mod.state.user = null;
        const login = String(mod.renderLoginPage());
        const dashboard = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 1000, used_bytes: 910, free_bytes: 90, percent_used: 91 },
            recent_syncs: [{ id: 1, mirror_id: 1, status: 'completed', files_deleted: 1500, created_at: '2026-01-01T00:00:00Z' }],
            recent_activity: [{ id: 1, action: 'login_success', created_at: '2026-01-01T00:00:00Z' }]
        });
        const mirrors = await renderWith(mod.renderMirrors, [
            { id: 1, name: 'FreeBSD', url_path: '/pub/FreeBSD', status: 'active', total_size_human: '1.0 TB', last_sync_completed: null }
        ]);
        const syncFailures = await renderWith(mod.renderSyncFailures, {
            period_days: 30, totals: { failed: 1, completed: 1 }, by_mirror: [], incidents: []
        });
        const users = await renderWith(mod.renderUsers, [
            { id: 1, username: 'a', email: 'a@x.com', role: 'admin', is_active: true, last_login: null }
        ]);
        const auditLogs = await renderWith(mod.renderAuditLogs, [
            { created_at: '2026-01-01T00:00:00Z', username: 'a', action: 'login_success', resource_type: 'user', resource_id: 1, ip_address: '127.0.0.1' }
        ]);
        const settings = await renderWith(mod.renderSettings, [
            { key: 'sync_schedule', value: '0 4 * * *', description: 'when', updated_at: null }
        ]);
        const health = String(mod.renderHealthChecksCard({
            state: 'failing', reason: 'x', finished_at: '2026-01-01T00:00:00Z', age_seconds: 5,
            bad: [{ label: 'a', detail: 'b' }], skipped: [{ check: 'a', reason: 'b' }],
            warnings: ['w'], ok: ['ok']
        }));
        const filesDeleted = String(mod.filesDeletedBadge(mod.LARGE_DELETION_THRESHOLD));

        const corpus = [layout, login, dashboard, mirrors, syncFailures, users, auditLogs, settings, health, filesDeleted].join('');
        const offenders = [...corpus].filter(
            (ch) => ch.codePointAt(0) > 0x2000 && !ALLOWED_HIGH_CODEPOINTS.has(ch.codePointAt(0))
        );
        assert(
            offenders.length === 0,
            `emoji or symbol glyph(s) found: ${JSON.stringify([...new Set(offenders)])}`
        );
        assert(!corpus.includes('×'), 'the modal-close "×" glyph must be gone');
        return '';
    });

    process.stdout.write(JSON.stringify({ checks }, null, 2) + '\n');
}

main();
