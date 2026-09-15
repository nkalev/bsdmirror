/**
 * Theme harness for frontend/public/js/theme-init.js and the ThemeManager in
 * frontend/public/js/main.js.
 *
 * Runs the real scripts in a Node vm context with only the browser APIs they
 * touch stubbed -- localStorage, matchMedia, <html>'s attributes, the toggle
 * button and its icon -- the same way footer_version_harness.mjs loads
 * main.js. Prints one JSON object, {checkName: [ok, detail]}, for
 * tests/test_theme.py to assert on.
 *
 * Usage:  node theme_harness.mjs <path-to-theme-init.js> <path-to-main.js>
 */
import fs from 'node:fs';
import vm from 'node:vm';

const [initPath, mainPath] = process.argv.slice(2);
const INIT_SOURCE = fs.readFileSync(initPath, 'utf8');
const MAIN_SOURCE = fs.readFileSync(mainPath, 'utf8');
const MOON = '☾';
const SUN = '☀';

/** A fresh, browser-shaped global for one page view. */
function makePage({ saved = null, storageThrows = false, writeThrows = false, prefersDark = false, matchMedia = true } = {}) {
    const store = new Map(saved === null ? [] : [['theme', saved]]);
    const writes = [];
    const storage = {
        getItem: (key) => (store.has(key) ? store.get(key) : null),
        setItem: (key, value) => {
            if (writeThrows) throw new Error('QuotaExceededError');
            store.set(key, String(value));
            writes.push([key, String(value)]);
        },
        removeItem: (key) => store.delete(key),
    };

    const htmlAttrs = new Map();
    const toggleAttrs = new Map([['aria-label', 'Toggle theme']]);
    const clickListeners = [];
    const icon = { textContent: MOON };
    const toggle = {
        setAttribute: (name, value) => toggleAttrs.set(name, String(value)),
        getAttribute: (name) => (toggleAttrs.has(name) ? toggleAttrs.get(name) : null),
        addEventListener: (type, fn) => { if (type === 'click') clickListeners.push(fn); },
    };
    const document = {
        documentElement: {
            setAttribute: (name, value) => htmlAttrs.set(name, String(value)),
            getAttribute: (name) => (htmlAttrs.has(name) ? htmlAttrs.get(name) : null),
        },
        getElementById: (id) => (id === 'themeToggle' ? toggle : null),
        querySelector: (selector) => (selector === '.theme-icon' ? icon : null),
        querySelectorAll: () => [],
        // main.js registers its DOMContentLoaded hook here; the checks call
        // ThemeManager.init() by hand instead.
        addEventListener: () => {},
    };

    const mediaListeners = [];
    const media = {
        matches: prefersDark,
        addEventListener: (type, fn) => { if (type === 'change') mediaListeners.push(fn); },
    };

    const sandbox = {
        document,
        console,
        fetch: async () => ({ ok: false, status: 503, json: async () => ({}) }),
        setInterval: () => 0,
        setTimeout: () => 0,
        clearInterval: () => {},
        navigator: {},
        location: { hostname: 'mirror.test' },
    };
    Object.defineProperty(sandbox, 'localStorage', {
        get() {
            if (storageThrows) throw new Error('SecurityError: site data is blocked');
            return storage;
        },
    });
    if (matchMedia) {
        sandbox.matchMedia = (query) =>
            query === '(prefers-color-scheme: dark)' ? media : { matches: false, addEventListener: () => {} };
    }
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);

    return {
        writes,
        theme: () => (htmlAttrs.has('data-theme') ? htmlAttrs.get('data-theme') : null),
        icon: () => icon.textContent,
        label: () => toggleAttrs.get('aria-label'),
        click: () => clickListeners.forEach((fn) => fn()),
        systemChanges: (dark) => {
            media.matches = dark;
            mediaListeners.forEach((fn) => fn({ matches: dark }));
        },
        runThemeInit: () => vm.runInContext(INIT_SOURCE, sandbox, { filename: initPath }),
        loadThemeManager: () => vm.runInContext(`${MAIN_SOURCE}\n;ThemeManager`, sandbox, { filename: mainPath }),
    };
}

const results = {};

function check(name, fn) {
    try {
        const outcome = fn();
        results[name] = outcome === true ? [true, ''] : [false, String(outcome)];
    } catch (err) {
        results[name] = [false, `threw: ${(err && err.stack) || err}`];
    }
}

const expect = (actual, expected, what) =>
    actual === expected ? true : `${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;

const all = (...outcomes) => outcomes.find((outcome) => outcome !== true) ?? true;

check('no saved choice and a light system preference gives light', () => {
    const page = makePage({ prefersDark: false });
    page.runThemeInit();
    return expect(page.theme(), 'light', 'data-theme');
});

check('no saved choice and a dark system preference gives dark', () => {
    const page = makePage({ prefersDark: true });
    page.runThemeInit();
    return expect(page.theme(), 'dark', 'data-theme');
});

check('a saved dark choice wins over a light system preference', () => {
    const page = makePage({ saved: 'dark', prefersDark: false });
    page.runThemeInit();
    return expect(page.theme(), 'dark', 'data-theme');
});

check('a saved light choice wins over a dark system preference', () => {
    const page = makePage({ saved: 'light', prefersDark: true });
    page.runThemeInit();
    return expect(page.theme(), 'light', 'data-theme');
});

check('an unrecognised saved value falls back to the system preference', () => {
    const page = makePage({ saved: 'purple', prefersDark: true });
    page.runThemeInit();
    return expect(page.theme(), 'dark', 'data-theme');
});

check('storage that throws still applies the system preference', () => {
    const page = makePage({ storageThrows: true, prefersDark: true });
    page.runThemeInit();
    return expect(page.theme(), 'dark', 'data-theme');
});

check('without matchMedia and with nothing saved the theme is light', () => {
    const page = makePage({ matchMedia: false });
    page.runThemeInit();
    return expect(page.theme(), 'light', 'data-theme');
});

check('theme-init writes nothing to storage', () => {
    const page = makePage({ prefersDark: true });
    page.runThemeInit();
    return expect(page.writes.length, 0, 'storage writes');
});

check('ThemeManager.init adopts the theme theme-init applied and syncs the toggle', () => {
    const page = makePage({ prefersDark: true });
    page.runThemeInit();
    page.loadThemeManager().init();
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(page.icon(), SUN, 'icon'),
        expect(page.label(), 'Switch to light theme', 'aria-label'),
        expect(page.writes.length, 0, 'storage writes'),
    );
});

check('ThemeManager.init alone falls back to the saved or system theme', () => {
    const page = makePage({ saved: 'dark' });
    page.loadThemeManager().init();
    return all(expect(page.theme(), 'dark', 'data-theme'), expect(page.icon(), SUN, 'icon'));
});

check('clicking the toggle flips the theme and saves the choice', () => {
    const page = makePage({ prefersDark: true });
    page.runThemeInit();
    page.loadThemeManager().init();
    page.click();
    return all(
        expect(page.theme(), 'light', 'data-theme'),
        expect(page.icon(), MOON, 'icon'),
        expect(page.label(), 'Switch to dark theme', 'aria-label'),
        expect(JSON.stringify(page.writes), JSON.stringify([['theme', 'light']]), 'storage writes'),
    );
});

check('a failing storage write still flips the theme', () => {
    const page = makePage({ writeThrows: true });
    page.runThemeInit();
    page.loadThemeManager().init();
    page.click();
    return expect(page.theme(), 'dark', 'data-theme');
});

check('a system change is followed until the visitor chooses', () => {
    const page = makePage({ prefersDark: false });
    page.runThemeInit();
    page.loadThemeManager().init();
    page.systemChanges(true);
    return all(expect(page.theme(), 'dark', 'data-theme'), expect(page.icon(), SUN, 'icon'));
});

check('a system change is ignored once a choice is saved', () => {
    const page = makePage({ prefersDark: false });
    page.runThemeInit();
    page.loadThemeManager().init();
    page.click();
    page.systemChanges(false);
    return expect(page.theme(), 'dark', 'data-theme');
});

process.stdout.write(JSON.stringify(results));
