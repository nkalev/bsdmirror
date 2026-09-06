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
    renderDashboard, renderSyncFailures, renderProtectedPaths, filesDeletedBadge,
    LARGE_DELETION_THRESHOLD, DISK_USAGE_WARNING_PERCENT, Toast, Modal, api, state });
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

    process.stdout.write(JSON.stringify({ checks }, null, 2) + '\n');
}

main();
