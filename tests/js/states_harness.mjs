/**
 * Mirror status harness for the MirrorStatus in frontend/public/js/main.js.
 *
 * docs/design/2026-09-25-reflection-redesign.md, section 5.2. Runs the real
 * main.js in a Node vm context with a small fake DOM -- in theme_harness.mjs's
 * style -- and a stubbed fetch, then drives MirrorStatus.load() through every
 * row of section 5.2's two tables (the per-mirror state model, and the
 * overall card computed from it), plus these edge cases: an absent mirror, an
 * empty mirrors object, a first-load API failure, a failure after a success,
 * and sentences naming two or three mirrors. Prints one JSON object,
 * {checkName: [ok, detail]}, for tests/test_public_states.py to assert on --
 * the same shape theme_harness.mjs uses. Unlike that harness,
 * MirrorStatus.load() is async (it awaits API.get()), so check() here awaits
 * its scenario before recording the result, the way footer_version_harness.mjs
 * awaits FooterVersion.load().
 *
 * setHostname() is a one-time page setup with nothing to do with the status
 * poll -- it is called once from DOMContentLoaded, not from load() -- so the
 * epilogue exposes it alongside MirrorStatus and the hostname check below
 * calls it directly on its own fake page, rather than going through load().
 *
 * The fake DOM matches the markup section 5.1 describes and index.html ships
 * (a stream row and pill per mirror, #statFiles, [data-hostname] elements).
 * One check (see "does not throw against markup with no stream rows" below)
 * instead builds a sparser page without them, to prove every lookup is
 * null-safe against it.
 *
 * Usage:  node states_harness.mjs <path-to-main.js>
 */
import fs from 'node:fs';
import vm from 'node:vm';

const [mainPath] = process.argv.slice(2);
const MAIN_SOURCE = fs.readFileSync(mainPath, 'utf8');

/** One fake element: setAttribute/getAttribute (data-state), textContent,
 * className, classList and style (all write-tracking, see `writes` below),
 * plus a flat, non-recursive querySelector into a caller-supplied child map
 * -- the same trade-off theme_harness.mjs's icon/toggle stubs make. `state`,
 * given, seeds data-state the way the shipped HTML does (section 5.2: "As
 * shipped in the HTML, before any data" is data-state="unknown").
 *
 * `writes`, when given, is one array shared by every element `makePage`
 * builds for a page. The className setter, classList.remove (the element's
 * own, and the one on the ancestor closest() finds) and a Proxy around style
 * each push a description onto it, so a check can assert that a whole
 * page's worth of elements were never written to -- not just that the final
 * value still looks untouched, which a write of the same value would hide. */
function makeEl({ text = '', state = null, children = {}, writes = null } = {}) {
    const attrs = new Map();
    if (state !== null) attrs.set('data-state', state);
    let textContent = text;
    let className = '';
    const style = new Proxy({}, {
        set(target, prop, value) {
            writes?.push(`style.${String(prop)} = ${JSON.stringify(value)}`);
            target[prop] = value;
            return true;
        }
    });
    // Records each call instead of tracking classes: no check reads a class
    // back, they only need to know whether one was ever touched.
    const recordingClassList = (owner) => ({
        remove: (name) => { writes?.push(`${owner}classList.remove(${JSON.stringify(name)})`); }
    });
    return {
        get textContent() { return textContent; },
        set textContent(v) { textContent = v; },
        get className() { return className; },
        set className(v) {
            writes?.push(`className = ${JSON.stringify(v)}`);
            className = v;
        },
        style,
        classList: recordingClassList(''),
        // The ancestor a closest() lookup lands on, such as the .stat-card
        // whose "loading" class main.js used to remove: a stand-in with a
        // recording classList of its own.
        closest: (sel) => ({ classList: recordingClassList(`closest(${JSON.stringify(sel)}).`) }),
        setAttribute: (name, value) => attrs.set(name, String(value)),
        getAttribute: (name) => (attrs.has(name) ? attrs.get(name) : null),
        querySelector: (sel) => children[sel] ?? null
    };
}

/** A fresh page. `minimal` builds a sparser page -- no stream rows, no
 * [data-hostname], no #statFiles, as index.html was before section 5.1's
 * redesign -- everything else builds the markup section 5.1 describes, which
 * is what most checks below drive. */
function makePage({ minimal = false, hostname = 'mirror.test' } = {}) {
    // Shared by every element this page builds, so one check can assert that
    // no className, classList or style write happened anywhere on the page.
    const writes = [];
    const mirrors = {};
    for (const id of ['freebsd', 'netbsd', 'openbsd']) {
        const statusText = makeEl({ text: 'Checking…', writes });
        const dot = makeEl({ writes });
        const statusEl = makeEl({
            state: 'unknown', writes,
            children: { '.status-dot': dot, '.status-text': statusText }
        });

        const pillStatusText = makeEl({ text: 'Checking…', writes });
        const pill = makeEl({ state: 'unknown', writes, children: { '.status-text': pillStatusText } });
        const stream = makeEl({ state: 'unknown', writes, children: { '.pill': pill } });

        mirrors[id] = {
            statusEl, dot, statusText, stream, pill, pillStatusText,
            size: makeEl({ text: '--', writes }),
            sync: makeEl({ text: '--', writes }),
            dataHostname: makeEl({ text: '', writes })
        };
    }

    const overallTitle = makeEl({ text: 'Checking mirror status…', writes });
    const overallDesc = makeEl({ text: '', writes });
    const indicator = makeEl({ writes });
    const pulse = makeEl({ writes });
    const overall = makeEl({
        state: 'unknown', writes,
        children: { h3: overallTitle, p: overallDesc, '.status-indicator': indicator, '.pulse': pulse }
    });
    overall.h3 = overallTitle;
    overall.p = overallDesc;
    overall.indicator = indicator;
    overall.pulse = pulse;

    const statSize = makeEl({ text: '—', writes });
    const statFiles = makeEl({ text: '—', writes });
    const statLastSync = makeEl({ text: '—', writes });
    const hostnameEl = makeEl({ text: '', writes });
    const rsynchostEl = makeEl({ text: '', writes });

    const byId = { overallStatus: overall, statSize, statLastSync, hostname: hostnameEl, rsynchost: rsynchostEl };
    if (!minimal) byId.statFiles = statFiles;
    for (const [id, els] of Object.entries(mirrors)) {
        byId[`${id}-status`] = els.statusEl;
        byId[`${id}-size`] = els.size;
        byId[`${id}-sync`] = els.sync;
        if (!minimal) byId[`${id}-stream`] = els.stream;
    }

    const dataHostnameEls = minimal ? [] : Object.values(mirrors).map((m) => m.dataHostname);

    let fetchImpl = async () => { throw new Error('no fetch stubbed for this scenario'); };

    const sandbox = {
        console,
        document: {
            addEventListener: () => {},
            getElementById: (id) => (Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null),
            querySelector: () => null,
            // Only the one compound selector setHostname() actually uses,
            // split generically so word order or spacing there cannot make
            // this pass by accident.
            querySelectorAll: (sel) => {
                const found = [];
                for (const part of sel.split(',').map((s) => s.trim())) {
                    if (part === '[data-hostname]') found.push(...dataHostnameEls);
                    else if (part.startsWith('#') && byId[part.slice(1)]) found.push(byId[part.slice(1)]);
                }
                return found;
            },
            documentElement: { getAttribute: () => null, setAttribute: () => {} }
        },
        navigator: {},
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        setTimeout: () => 0,
        setInterval: () => 0,
        clearTimeout: () => {},
        clearInterval: () => {},
        fetch: (...args) => fetchImpl(...args),
        location: { hostname }
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);

    // Run once per page: MirrorStatus itself holds no state between calls,
    // everything "remembered" across load()s lives in the DOM stubs above.
    // setHostname is exposed alongside it because it is not part of load()'s
    // call graph at all -- see the file header.
    const { MirrorStatus, setHostname } = vm.runInContext(
        `${MAIN_SOURCE}\n;({ MirrorStatus, setHostname })`,
        sandbox,
        { filename: mainPath }
    );

    return {
        load: () => MirrorStatus.load(),
        setHostname: () => setHostname(),
        setFetch: (impl) => { fetchImpl = impl; },
        mirrors,
        overall,
        statSize,
        statFiles,
        statLastSync,
        hostnameEl,
        rsynchostEl,
        dataHostnameEls,
        writes
    };
}

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const networkFailure = async () => { throw new Error('network disabled in harness'); };

const results = {};

async function check(name, fn) {
    try {
        const outcome = await fn();
        results[name] = outcome === true ? [true, ''] : [false, String(outcome)];
    } catch (err) {
        results[name] = [false, `threw: ${(err && err.stack) || err}`];
    }
}

const expect = (actual, expected, what) =>
    actual === expected ? true : `${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;

const all = (...outcomes) => outcomes.find((outcome) => outcome !== true) ?? true;

// ---------------------------------------------------------------------------
// Section 5.2, table 1: API status -> data-state and text, on the card pill,
// the stream row and the row's own .pill child.
// ---------------------------------------------------------------------------
await check(
    'an active mirror maps to online/Online on its card pill, stream row and row pill, and writes size and sync',
    async () => {
        const page = makePage();
        const now = new Date().toISOString();
        page.setFetch(async () => ok({
            mirrors: {
                FreeBSD: { status: 'active', size: '799.9 GB', last_updated: now },
                NetBSD: { status: 'active' },
                OpenBSD: { status: 'active' }
            },
            totals: {}
        }));
        await page.load();
        const m = page.mirrors.freebsd;
        return all(
            expect(m.statusEl.getAttribute('data-state'), 'online', 'card pill data-state'),
            expect(m.statusText.textContent, 'Online', 'card pill text'),
            expect(m.stream.getAttribute('data-state'), 'online', 'stream row data-state'),
            expect(m.pill.getAttribute('data-state'), 'online', 'row pill data-state'),
            expect(m.pillStatusText.textContent, 'Online', 'row pill text'),
            expect(m.size.textContent, '799.9 GB', 'size'),
            expect(m.sync.textContent, 'Just now', 'sync')
        );
    }
);

await check('a syncing mirror maps to syncing/Syncing on its card pill, stream row and row pill', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.netbsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'syncing', 'card pill data-state'),
        expect(m.statusText.textContent, 'Syncing', 'card pill text'),
        expect(m.stream.getAttribute('data-state'), 'syncing', 'stream row data-state'),
        expect(m.pill.getAttribute('data-state'), 'syncing', 'row pill data-state'),
        expect(m.pillStatusText.textContent, 'Syncing', 'row pill text')
    );
});

await check('an error mirror maps to error/Error on its card pill, stream row and row pill', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'error' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.openbsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'error', 'card pill data-state'),
        expect(m.statusText.textContent, 'Error', 'card pill text'),
        expect(m.stream.getAttribute('data-state'), 'error', 'stream row data-state'),
        expect(m.pill.getAttribute('data-state'), 'error', 'row pill data-state'),
        expect(m.pillStatusText.textContent, 'Error', 'row pill text')
    );
});

await check('an explicitly disabled mirror maps to disabled/Offline', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'disabled' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.freebsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'disabled', 'data-state'),
        expect(m.statusText.textContent, 'Offline', 'text')
    );
});

await check('a mirror absent from a successful response maps to disabled/Offline', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' } }, // OpenBSD omitted entirely
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.openbsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'disabled', 'data-state'),
        expect(m.statusText.textContent, 'Offline', 'text')
    );
});

await check('an unrecognised API status maps to unknown/Unknown', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'bogus' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.freebsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'unknown', 'data-state'),
        expect(m.statusText.textContent, 'Unknown', 'text')
    );
});

await check("a lower-cased API key still resolves to its mirror's elements", async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { freebsd: { status: 'active' }, netbsd: { status: 'syncing' }, openbsd: { status: 'error' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.mirrors.freebsd.statusEl.getAttribute('data-state'), 'online', 'freebsd'),
        expect(page.mirrors.netbsd.statusEl.getAttribute('data-state'), 'syncing', 'netbsd'),
        expect(page.mirrors.openbsd.statusEl.getAttribute('data-state'), 'error', 'openbsd')
    );
});

// ---------------------------------------------------------------------------
// Section 5.2's last table-1 row: the API request itself fails.
// ---------------------------------------------------------------------------
await check(
    'a first-load API failure leaves the shipped pills unchanged and marks the overall card unavailable',
    async () => {
        const page = makePage();
        page.setFetch(networkFailure);
        await page.load();
        const m = page.mirrors.freebsd;
        return all(
            expect(m.statusEl.getAttribute('data-state'), 'unknown', 'card pill data-state'),
            expect(m.statusText.textContent, 'Checking…', 'card pill text'),
            expect(page.overall.getAttribute('data-state'), 'unknown', 'overall data-state'),
            expect(page.overall.h3.textContent, 'Status unavailable', 'overall title'),
            expect(
                page.overall.p.textContent,
                "The status service didn't answer. The mirrors themselves may still be reachable.",
                'overall sentence'
            )
        );
    }
);

await check(
    "an API failure after a success keeps each pill's last state and marks the overall card unavailable",
    async () => {
        const page = makePage();
        page.setFetch(async () => ok({
            mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
            totals: {}
        }));
        await page.load();
        page.setFetch(networkFailure);
        await page.load();
        const m = page.mirrors.freebsd;
        return all(
            expect(m.statusEl.getAttribute('data-state'), 'online', 'card pill data-state kept'),
            expect(m.statusText.textContent, 'Online', 'card pill text kept'),
            expect(page.overall.getAttribute('data-state'), 'unknown', 'overall data-state'),
            expect(page.overall.h3.textContent, 'Status unavailable', 'overall title')
        );
    }
);

// ---------------------------------------------------------------------------
// Section 5.2, table 2: the overall card after a successful load.
// ---------------------------------------------------------------------------
await check('all three mirrors online gives All systems operational', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'online', 'data-state'),
        expect(page.overall.h3.textContent, 'All systems operational', 'title'),
        expect(page.overall.p.textContent, 'All mirrors are synchronized and available.', 'sentence')
    );
});

await check('at least one but not all mirrors online gives Systems operational', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'disabled' } }, // OpenBSD absent
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'online', 'data-state'),
        expect(page.overall.h3.textContent, 'Systems operational', 'title'),
        expect(page.overall.p.textContent, 'Some mirrors are offline; the rest are available.', 'sentence')
    );
});

await check('no mirrors online gives No mirrors online', async () => {
    const page = makePage();
    page.setFetch(async () => ok({ mirrors: {}, totals: {} }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'disabled', 'data-state'),
        expect(page.overall.h3.textContent, 'No mirrors online', 'title'),
        expect(page.overall.p.textContent, 'No mirror is reporting as online right now.', 'sentence')
    );
});

await check('a single syncing mirror gives Sync in progress', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'syncing', 'data-state'),
        expect(page.overall.h3.textContent, 'Sync in progress', 'title'),
        expect(page.overall.p.textContent, 'NetBSD is syncing now.', 'sentence')
    );
});

await check('a single error mirror gives Degraded service', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'error' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'error', 'data-state'),
        expect(page.overall.h3.textContent, 'Degraded service', 'title'),
        expect(page.overall.p.textContent, 'OpenBSD is experiencing issues.', 'sentence')
    );
});

await check('an error mirror overrides a syncing one for the overall state', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'error' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'error', 'data-state'),
        expect(page.overall.h3.textContent, 'Degraded service', 'title'),
        expect(page.overall.p.textContent, 'FreeBSD is experiencing issues.', 'sentence')
    );
});

await check('two mirrors in error are joined as A and B in the sentence', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { NetBSD: { status: 'error' }, FreeBSD: { status: 'error' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return expect(page.overall.p.textContent, 'FreeBSD and NetBSD are experiencing issues.', 'sentence');
});

await check('three mirrors syncing are joined as A, B and C in the sentence', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { OpenBSD: { status: 'syncing' }, FreeBSD: { status: 'syncing' }, NetBSD: { status: 'syncing' } },
        totals: {}
    }));
    await page.load();
    return expect(page.overall.p.textContent, 'FreeBSD, NetBSD and OpenBSD are syncing now.', 'sentence');
});

// ---------------------------------------------------------------------------
// Stats and hostname fill.
// ---------------------------------------------------------------------------
await check('statSize and statFiles are written from totals when present', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: { size: '2.1 TB', files: '604,618' }
    }));
    await page.load();
    return all(
        expect(page.statSize.textContent, '2.1 TB', 'statSize'),
        expect(page.statFiles.textContent, '604,618', 'statFiles')
    );
});

await check('statSize and statFiles are left untouched when totals is empty', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.statSize.textContent, '—', 'statSize'),
        expect(page.statFiles.textContent, '—', 'statFiles')
    );
});

await check('statLastSync reflects the most recently updated mirror', async () => {
    const page = makePage();
    const now = new Date().toISOString();
    const earlier = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    page.setFetch(async () => ok({
        mirrors: {
            FreeBSD: { status: 'active', last_updated: earlier },
            NetBSD: { status: 'active', last_updated: now },
            OpenBSD: { status: 'active' }
        },
        totals: {}
    }));
    await page.load();
    return expect(page.statLastSync.textContent, 'Just now', 'statLastSync');
});

await check("hostname fill sets #hostname, #rsynchost and every stream row's data-hostname element", async () => {
    // setHostname() is page setup, not part of the status poll: called
    // directly here, never through load() (see the file header).
    const page = makePage({ hostname: 'mirror.test' });
    page.setHostname();
    return all(
        expect(page.hostnameEl.textContent, 'mirror.test', '#hostname'),
        expect(page.rsynchostEl.textContent, 'mirror.test', '#rsynchost'),
        expect(page.dataHostnameEls.length, 3, 'number of [data-hostname] elements'),
        expect(page.dataHostnameEls.every((el) => el.textContent === 'mirror.test'), true, 'every [data-hostname] text')
    );
});

// ---------------------------------------------------------------------------
// Null-safety against sparser markup, and the retired legacy writes.
// ---------------------------------------------------------------------------
await check('load does not throw against markup with no stream rows', async () => {
    // setHostname() is not part of load()'s call graph (see the file
    // header), so this is purely about load() itself against sparse markup.
    const page = makePage({ minimal: true });
    const now = new Date().toISOString();
    page.setFetch(async () => ok({
        mirrors: {
            FreeBSD: { status: 'active', size: '1.0 TB', last_updated: now },
            NetBSD: { status: 'active' },
            OpenBSD: { status: 'active' }
        },
        totals: { size: '3.0 TB' }
    }));
    await page.load();
    const m = page.mirrors.freebsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'online', 'card pill data-state'),
        expect(page.statSize.textContent, '3.0 TB', 'statSize')
    );
});

await check(
    'the legacy status-dot, status-indicator, pulse and stat-card elements are present but never written',
    async () => {
        // One response that would reach every retired path: an active, a
        // syncing and an error mirror for the dot, indicator and pulse
        // writes, and totals.size plus a last_updated for the two .stat-card
        // "loading" removals.
        const page = makePage();
        const now = new Date().toISOString();
        page.setFetch(async () => ok({
            mirrors: {
                FreeBSD: { status: 'active', last_updated: now },
                NetBSD: { status: 'syncing' },
                OpenBSD: { status: 'error' }
            },
            totals: { size: '2.1 TB', files: '604,618' }
        }));
        await page.load();
        return page.writes.length === 0
            ? true
            : `unexpected className, classList or style writes: ${page.writes.join(', ')}`;
    }
);

process.stdout.write(JSON.stringify(results));
