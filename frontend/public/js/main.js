/**
 * BSD Mirror - Main JavaScript
 */

// Theme management.
//
// js/theme-init.js runs from <head> and has already applied the saved or
// system theme before the first paint; ThemeManager adopts it, keeps the
// toggle's icon and label in step, and saves explicit choices. Until the
// visitor makes one, the site keeps following the operating system's
// preference, including a change made while the page is open. Storage can be
// unavailable or throw; a theme change must never depend on it.
const ThemeManager = {
    STORAGE_KEY: 'theme',
    SYSTEM_DARK: '(prefers-color-scheme: dark)',

    init() {
        const current = document.documentElement.getAttribute('data-theme');
        this.apply(current === 'light' || current === 'dark' ? current : this.preferred());

        document.getElementById('themeToggle')?.addEventListener('click', () => {
            const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            this.apply(next);
            this.save(next);
        });

        const media = typeof window.matchMedia === 'function' ? window.matchMedia(this.SYSTEM_DARK) : null;
        media?.addEventListener?.('change', (event) => {
            if (this.saved() === null) {
                this.apply(event.matches ? 'dark' : 'light');
            }
        });
    },

    saved() {
        try {
            const value = window.localStorage.getItem(this.STORAGE_KEY);
            return value === 'light' || value === 'dark' ? value : null;
        } catch {
            return null;
        }
    },

    preferred() {
        const saved = this.saved();
        if (saved) {
            return saved;
        }
        const prefersDark = typeof window.matchMedia === 'function' && window.matchMedia(this.SYSTEM_DARK).matches;
        return prefersDark ? 'dark' : 'light';
    },

    save(theme) {
        try {
            window.localStorage.setItem(this.STORAGE_KEY, theme);
        } catch {
            // Storage unavailable: the choice lasts for this page view only.
        }
    },

    apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        document.getElementById('themeToggle')?.setAttribute(
            'aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
        );
        document.querySelector('.theme-icon')?.setAttribute('data-icon', theme === 'dark' ? 'sun' : 'moon');
    }
};

// API client
const API = {
    baseUrl: '/api',

    async get(endpoint) {
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error(`API Error: ${endpoint}`, error);
            return null;
        }
    }
};

// Mirror status manager
//
// docs/design/2026-09-25-reflection-redesign.md, section 5.2. Each mirror's
// card pill (#<id>-status), its stream row (#<id>-stream) and the row's own
// .pill child all carry a data-state the stylesheet keys off, plus a worded
// .status-text. The overall card gets the same treatment, with its own
// data-state and a title/sentence chosen from every mirror's state at once --
// including the "API failed" and "no mirror online" cases the old
// className-only version could not represent (every() over an empty mirror
// list used to read as "all active").
//
// MIRRORS fixes the three cards the page ships. The API's own keys
// (Mirror.name, e.g. "FreeBSD") are matched to them case-insensitively: the
// real API sends that casing, the contrast harness's stub sends lower-case,
// and both must resolve to the same element ids.
const MIRRORS = ['freebsd', 'netbsd', 'openbsd'];

// API status -> this page's data-state and the word shown next to it.
// "disabled" covers both an explicit disabled status and a mirror missing
// entirely from a successful response: the backend omits disabled mirrors
// outright, so "absent" and "disabled" are the same fact here.
const STATE_TEXT = {
    online: 'Online',
    syncing: 'Syncing',
    error: 'Error',
    disabled: 'Offline',
    unknown: 'Unknown'
};

function mirrorState(apiStatus) {
    if (apiStatus === 'active') return 'online';
    if (apiStatus === 'syncing') return 'syncing';
    if (apiStatus === 'error') return 'error';
    if (apiStatus === 'disabled' || apiStatus === undefined) return 'disabled';
    return 'unknown';
}

// "A", "A and B", "A, B and C" -- for the overall card's sentence, in the
// API's own key casing and in MIRRORS order (not response order).
function joinNames(names) {
    if (names.length < 2) return names[0] || '';
    if (names.length === 2) return `${names[0]} and ${names[1]}`;
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

const isAre = (count) => (count === 1 ? 'is' : 'are');

// Writes data-state and, where the element has one, its .status-text. Used
// for a mirror's card pill, its stream row, and the row's own .pill child
// alike. Any of them may be missing (null or undefined), and is skipped: a
// page without stream rows still gets its card pills painted.
function paintState(el, state, text) {
    if (!el) return;
    el.setAttribute('data-state', state);
    const label = el.querySelector('.status-text');
    if (label) label.textContent = text;
}

const MirrorStatus = {
    async load() {
        const data = await API.get('/stats/overview');
        if (!data || !data.mirrors) {
            this.showUnavailable();
            return;
        }

        this.updateMirrorStates(data.mirrors);
        this.updateStats(data);
    },

    // The data-state model, section 5.2's first table.
    updateMirrorStates(mirrors) {
        const byLowerKey = {};
        for (const [key, mirror] of Object.entries(mirrors)) {
            byLowerKey[key.toLowerCase()] = { key, mirror };
        }

        const named = { online: [], syncing: [], error: [] };

        for (const id of MIRRORS) {
            const found = byLowerKey[id];
            const mirror = found?.mirror;
            const state = mirrorState(mirror?.status);
            const text = STATE_TEXT[state];

            paintState(document.getElementById(`${id}-status`), state, text);
            const row = document.getElementById(`${id}-stream`);
            paintState(row, state, text);
            paintState(row?.querySelector('.pill'), state, text);

            if (found && state in named) {
                named[state].push(found.key);
            }

            const sizeEl = document.getElementById(`${id}-size`);
            if (sizeEl && mirror?.size) {
                sizeEl.textContent = mirror.size;
            }

            const syncEl = document.getElementById(`${id}-sync`);
            if (syncEl && mirror?.last_updated) {
                syncEl.textContent = this.formatRelativeTime(new Date(mirror.last_updated));
            }
        }

        this.updateOverallState(named);
    },

    // The overall card, after a successful load (section 5.2's second table).
    updateOverallState(named) {
        const card = document.getElementById('overallStatus');
        if (!card) return;

        const title = card.querySelector('h3');
        const desc = card.querySelector('p');
        const onlineCount = named.online.length;

        let state;
        let titleText;
        let sentence;
        if (named.error.length > 0) {
            state = 'error';
            titleText = 'Degraded service';
            sentence = `${joinNames(named.error)} ${isAre(named.error.length)} experiencing issues.`;
        } else if (named.syncing.length > 0) {
            state = 'syncing';
            titleText = 'Sync in progress';
            sentence = `${joinNames(named.syncing)} ${isAre(named.syncing.length)} syncing now.`;
        } else if (onlineCount === MIRRORS.length) {
            state = 'online';
            titleText = 'All systems operational';
            sentence = 'All mirrors are synchronized and available.';
        } else if (onlineCount > 0) {
            state = 'online';
            titleText = 'Systems operational';
            sentence = 'Some mirrors are offline; the rest are available.';
        } else {
            state = 'disabled';
            titleText = 'No mirrors online';
            sentence = 'No mirror is reporting as online right now.';
        }

        card.setAttribute('data-state', state);
        if (title) title.textContent = titleText;
        if (desc) desc.textContent = sentence;
    },

    // The API request itself failed, or answered without a mirrors object:
    // the overall card says so; every mirror pill is left exactly as it was.
    showUnavailable() {
        const card = document.getElementById('overallStatus');
        if (!card) return;
        card.setAttribute('data-state', 'unknown');
        const title = card.querySelector('h3');
        const desc = card.querySelector('p');
        if (title) title.textContent = 'Status unavailable';
        if (desc) {
            desc.textContent =
                "The status service didn't answer. The mirrors themselves may still be reachable.";
        }
    },

    updateStats(data) {
        const statSize = document.getElementById('statSize');
        if (statSize && data.totals?.size) {
            statSize.textContent = data.totals.size;
        }

        const statFiles = document.getElementById('statFiles');
        if (statFiles && data.totals?.files) {
            statFiles.textContent = data.totals.files;
        }

        const statLastSync = document.getElementById('statLastSync');
        if (statLastSync && data.mirrors) {
            const syncs = Object.values(data.mirrors)
                .map(m => m.last_updated)
                .filter(Boolean)
                .sort()
                .reverse();
            if (syncs.length > 0) {
                statLastSync.textContent = this.formatRelativeTime(new Date(syncs[0]));
            }
        }
    },

    formatRelativeTime(date) {
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;

        return date.toLocaleDateString();
    }
};

// Footer build/version display
//
// index.html no longer hardcodes a version string in .footer-version -- that
// string (v1.0.1) and backend/app/core/config.py's old VERSION (1.0.0) had
// already drifted from each other and from whatever was actually deployed.
// The footer now asks the API, which reports GIT_SHA-BUILD_DATE baked into
// the backend image at build time (see backend/Dockerfile), so there is
// exactly one place either half of that string can come from.
//
// /api/health, not /api/health/detailed: the latter pings Postgres and Redis
// on every call, and this runs on every page load to display a build stamp
// that never changes between deploys. It should not cost a database round
// trip, and a database blip should not blank out or misrepresent a value that
// has nothing to do with the database.
const FooterVersion = {
    async load() {
        const el = document.querySelector('.footer-version');
        if (!el) return;

        const data = await API.get('/health');

        // API unreachable, or answered without a version: leave the element
        // exactly as it started (empty). A blank line is honest; guessing, or
        // repeating whatever was there before, is not.
        if (!data || !data.version) return;

        el.textContent = data.version;
    }
};

// Toast notifications
const Toast = {
    show(message, duration = 3000) {
        const toast = document.getElementById('toast');
        if (!toast) return;

        toast.textContent = message;
        toast.classList.add('show');

        setTimeout(() => {
            toast.classList.remove('show');
        }, duration);
    }
};

// Copy rsync URL helper
function copyRsync(mirrorName) {
    const hostname = window.location.hostname;
    const url = `rsync://${hostname}/${mirrorName}/`;

    navigator.clipboard.writeText(url).then(() => {
        Toast.show(`Copied: ${url}`);
    }).catch(() => {
        Toast.show('Failed to copy URL');
    });
}

// Wire up the "Copy rsync URL" buttons.
//
// These were inline onclick="copyRsync('FreeBSD')" attributes. The production
// CSP has always carried script-src 'self', which blocks inline event handlers,
// so all three buttons were dead for every visitor:
//
//   Executing inline event handler violates the following Content Security
//   Policy directive: "script-src 'self'"
//
// The mirror name travels in data-copy-rsync instead. Bound per element rather
// than by delegation to match how ThemeManager binds #themeToggle; these
// buttons are static markup and are never re-rendered.
function bindCopyRsyncButtons() {
    document.querySelectorAll('[data-copy-rsync]').forEach(btn => {
        btn.addEventListener('click', () => copyRsync(btn.dataset.copyRsync));
    });
}

// Copy helper shared by the page-wide [data-copy] buttons: the hero's "Copy
// rsync URL" button and the two access-row icon buttons
// (docs/design/2026-09-25-reflection-redesign.md, section 5.1). Each maps to
// a URL builder keyed by its data-copy value.
const COPY_URL_BUILDERS = {
    'rsync-root': hostname => `rsync://${hostname}/`,
    'https-root': hostname => `https://${hostname}/`
};

// Same toasts as copyRsync above, plus a guard for a missing Clipboard API:
// outside a secure context and in older browsers, navigator.clipboard itself
// is undefined rather than a rejected promise. Without this check that reads
// as a thrown error, not one the .catch() below ever sees. copyRsync has the
// same gap, left alone because spec section 5.2 keeps the per-mirror buttons
// unchanged.
function copyUrl(url) {
    if (!navigator.clipboard) {
        Toast.show('Failed to copy URL');
        return;
    }
    navigator.clipboard.writeText(url).then(() => {
        Toast.show(`Copied: ${url}`);
    }).catch(() => {
        Toast.show('Failed to copy URL');
    });
}

// Wire up the page-wide copy buttons, the same way bindCopyRsyncButtons()
// above wires the per-mirror ones. An unrecognised data-copy value is left
// unbound rather than wired to a builder that does not exist.
function bindDataCopyButtons() {
    document.querySelectorAll('[data-copy]').forEach(btn => {
        const build = COPY_URL_BUILDERS[btn.dataset.copy];
        if (!build) return;
        btn.addEventListener('click', () => copyUrl(build(window.location.hostname)));
    });
}

// Set hostname in UI
function setHostname() {
    const hostname = window.location.hostname;
    document.querySelectorAll('#hostname, #rsynchost, [data-hostname]').forEach(el => {
        el.textContent = hostname;
    });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    ThemeManager.init();
    setHostname();
    bindCopyRsyncButtons();
    bindDataCopyButtons();
    MirrorStatus.load();
    FooterVersion.load();

    // Refresh status every 60 seconds
    setInterval(() => MirrorStatus.load(), 60000);
});
