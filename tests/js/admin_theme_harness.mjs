/**
 * Theme harness for the AdminTheme object in frontend/public/admin/js/admin.js
 * and the toggle button renderLayout/renderLoginPage render around it.
 *
 * Loads the real admin.js in a Node vm context, the same way
 * escaping_harness.mjs does, with only the DOM surface AdminTheme and the
 * toggle touch stubbed. Two shapes matter
 * (docs/design/2026-09-25-reflection-redesign.md, section 6.2): one with
 * document.documentElement and window.matchMedia, and one with neither -- the
 * shape tests/js/escaping_harness.mjs and tests/js/contrast_harness.mjs
 * already load this file in, so every top-level theme access must be
 * guarded. Prints one JSON object, {checkName: [ok, detail]}, for
 * tests/test_admin_theme.py to assert on.
 *
 * Usage:  node admin_theme_harness.mjs <path-to-admin.js>
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const [adminPath] = process.argv.slice(2);
const SOURCE = readFileSync(adminPath, 'utf8');

// admin.js has no exports; its top-level bindings are `const`/`function`. The
// trailing expression is the script's completion value, the same trick
// escaping_harness.mjs uses to get at them.
const EPILOGUE = `
;({ AdminTheme, renderThemeToggle, renderLayout, renderLoginPage, actions, state, html });
`;

/** One fake <button class="theme-toggle"> with a nested <span class="icon">. */
function makeToggle() {
    const attrs = new Map([['aria-label', 'Toggle theme']]);
    const icon = { className: 'icon icon-moon' };
    return {
        setAttribute: (name, value) => attrs.set(name, String(value)),
        getAttribute: (name) => (attrs.has(name) ? attrs.get(name) : null),
        querySelector: (selector) => (selector === '.icon' ? icon : null),
        label: () => attrs.get('aria-label'),
        iconClass: () => icon.className,
    };
}

/**
 * A fresh admin.js load. `documentElement: false` and `matchMedia: false`
 * reproduce the sandboxes escaping_harness.mjs and contrast_harness.mjs load
 * this file into, which have neither.
 */
function load({
    documentElement = true,
    matchMedia = true,
    initialTheme = null,
    saved = null,
    getThrows = false,
    setThrows = false,
    toggles = [],
} = {}) {
    const store = new Map(saved === null ? [] : [['theme', saved]]);
    const storage = {
        getItem: (key) => {
            if (getThrows) throw new Error('SecurityError: site data is blocked');
            return store.has(key) ? store.get(key) : null;
        },
        setItem: (key, value) => {
            if (setThrows) throw new Error('QuotaExceededError');
            store.set(key, String(value));
        },
        removeItem: (key) => store.delete(key),
    };

    const htmlAttrs = new Map(initialTheme === null ? [] : [['data-theme', initialTheme]]);
    const doc = {
        addEventListener: () => {},
        getElementById: () => null,
        createElement: () => ({ style: {}, remove() {} }),
        querySelectorAll: (selector) => (selector === '.theme-toggle' ? toggles : []),
    };
    if (documentElement) {
        doc.documentElement = {
            getAttribute: (name) => (htmlAttrs.has(name) ? htmlAttrs.get(name) : null),
            setAttribute: (name, value) => htmlAttrs.set(name, String(value)),
        };
    }

    const mediaListeners = [];
    const media = {
        matches: false,
        addEventListener: (type, fn) => { if (type === 'change') mediaListeners.push(fn); },
    };
    const win = { addEventListener() {}, history: { pushState() {} }, location: { hash: '' } };
    if (matchMedia) {
        win.matchMedia = (query) =>
            (query === '(prefers-color-scheme: dark)' ? media : { matches: false, addEventListener: () => {} });
    }

    const sandbox = {
        console,
        setTimeout: () => 0,
        setInterval: () => 0,
        clearTimeout: () => {},
        document: doc,
        window: win,
        localStorage: storage,
        fetch: async () => { throw new Error('network disabled in harness'); },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    const mod = vm.runInContext(SOURCE + EPILOGUE, sandbox, { filename: adminPath });

    return {
        mod,
        theme: () => (htmlAttrs.has('data-theme') ? htmlAttrs.get('data-theme') : null),
        stored: () => (store.has('theme') ? store.get('theme') : null),
        fireSystemChange: (dark) => {
            media.matches = dark;
            mediaListeners.forEach((fn) => fn({ matches: dark }));
        },
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

check('a fresh load adopts html[data-theme]', () => {
    const page = load({ initialTheme: 'dark' });
    return expect(page.mod.AdminTheme.current(), 'dark', 'AdminTheme.current()');
});

check('current falls back to light when no attribute is set', () => {
    const page = load({ initialTheme: null });
    return expect(page.mod.AdminTheme.current(), 'light', 'AdminTheme.current()');
});

check('current falls back to light with no documentElement', () => {
    const page = load({ documentElement: false });
    return expect(page.mod.AdminTheme.current(), 'light', 'AdminTheme.current()');
});

check('renderThemeToggle returns the markup for the current theme', () => {
    const page = load({ initialTheme: 'dark' });
    const out = String(page.mod.renderThemeToggle());
    return all(
        expect(out.includes('data-action="toggleTheme"'), true, 'data-action'),
        expect(out.includes('type="button"'), true, 'type=button'),
        expect(out.includes('class="theme-toggle"'), true, 'toggle class'),
        expect(out.includes('aria-label="Switch to light theme"'), true, 'aria-label'),
        expect(out.includes('icon icon-sun'), true, 'icon class'),
    );
});

check('toggleTheme flips the attribute, saves the choice, and updates every toggle in place', () => {
    const toggles = [makeToggle(), makeToggle()];
    const page = load({ initialTheme: 'light', toggles });
    page.mod.actions.toggleTheme();
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(page.stored(), 'dark', 'stored theme'),
        ...toggles.flatMap((toggle, i) => [
            expect(toggle.label(), 'Switch to light theme', `toggle ${i} aria-label`),
            expect(toggle.iconClass(), 'icon icon-sun', `toggle ${i} icon class`),
        ]),
    );
});

check('a failing storage write still flips the theme and updates the toggle', () => {
    const toggles = [makeToggle()];
    const page = load({ initialTheme: 'light', setThrows: true, toggles });
    page.mod.actions.toggleTheme();
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(toggles[0].iconClass(), 'icon icon-sun', 'toggle icon class'),
    );
});

check('a failing storage read is treated as nothing saved', () => {
    const page = load({ initialTheme: 'light', getThrows: true });
    page.mod.AdminTheme.init();
    page.fireSystemChange(true);
    return expect(page.theme(), 'dark', 'data-theme');
});

check('the system listener applies the OS theme while nothing is saved', () => {
    const toggles = [makeToggle()];
    const page = load({ initialTheme: 'light', saved: null, toggles });
    page.mod.AdminTheme.init();
    page.fireSystemChange(true);
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(toggles[0].iconClass(), 'icon icon-sun', 'toggle icon class'),
    );
});

check('the system listener is ignored once a choice is saved', () => {
    const page = load({ initialTheme: 'light', saved: 'light' });
    page.mod.AdminTheme.init();
    page.fireSystemChange(true);
    return expect(page.theme(), 'light', 'data-theme');
});

check('a sandbox with no documentElement and no matchMedia still loads and renders the layout', () => {
    const page = load({ documentElement: false, matchMedia: false });
    // init() and toggleTheme() are the two paths render alone never reaches:
    // init() is the only caller of window.matchMedia, and toggleTheme() is
    // the only caller of apply() outside a render. If either guard were
    // missing, this call -- not the render below -- is what would throw.
    page.mod.AdminTheme.init();
    page.mod.actions.toggleTheme();
    const layout = String(page.mod.renderLayout(page.mod.html`<p>x</p>`, 'Dashboard'));
    const login = String(page.mod.renderLoginPage());
    return all(
        expect((layout.match(/data-action="toggleTheme"/g) || []).length, 1, 'layout toggle count'),
        expect((login.match(/data-action="toggleTheme"/g) || []).length, 1, 'login toggle count'),
        expect(layout.includes('icon icon-moon'), true, 'layout falls back to the light icon'),
    );
});

check('renderLayout renders exactly one theme toggle whose icon matches the attribute', () => {
    const page = load({ initialTheme: 'dark' });
    const out = String(page.mod.renderLayout(page.mod.html`<p>x</p>`, 'Dashboard'));
    return all(
        expect((out.match(/data-action="toggleTheme"/g) || []).length, 1, 'toggle count'),
        expect(out.includes('icon icon-sun'), true, 'dark theme should render the sun icon'),
        expect(out.includes('icon icon-moon'), false, 'dark theme should not render the moon icon'),
    );
});

check('renderLoginPage renders exactly one theme toggle whose icon matches the attribute', () => {
    const page = load({ initialTheme: 'light' });
    const out = String(page.mod.renderLoginPage());
    return all(
        expect((out.match(/data-action="toggleTheme"/g) || []).length, 1, 'toggle count'),
        expect(out.includes('icon icon-moon'), true, 'light theme should render the moon icon'),
        expect(out.includes('icon icon-sun'), false, 'light theme should not render the sun icon'),
    );
});

process.stdout.write(JSON.stringify(results));
