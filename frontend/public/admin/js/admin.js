/**
 * BSD Mirror Admin Panel
 * Single Page Application with vanilla JavaScript
 */

// ===========================================
// Configuration & State
// ===========================================

const config = {
    apiBase: '/api',
    tokenKey: 'bsdmirror_token',
    refreshInterval: 30000
};

const state = {
    user: null,
    token: null,
    currentPage: 'dashboard',
    data: {
        dashboard: null,
        healthChecks: null,
        mirrors: null,
        syncFailures: null,
        protectedPaths: null,
        users: null,
        auditLogs: null,
        settings: null
    }
};

// ===========================================
// Display Thresholds
// ===========================================
//
// Two numbers that only decide when a value gets a stronger visual
// treatment. Neither gates backend behaviour or validation -- both are pure
// UI judgement calls, named and kept together so neither is a magic number
// buried inside a template literal.

// Matches DISK_WARN_PCT's default in scripts/health_check.sh (see README.md's
// Configuration table) rather than picking a second number: that script
// already alerts a channel at 85%/95%, so an operator's mental model of
// "85 means pay attention" already exists. This host has no historical
// growth-rate data (no snapshot table exists), so this stays a fixed cutoff
// and not a projection -- see the storage card in renderDashboard for why no
// ETA is shown.
const DISK_USAGE_WARNING_PERCENT = 85;

// rsync's --delete (always on; see sync/sync_service.py) removes a handful
// of stale files on almost every ordinary sync. A files_deleted count this
// large is well outside that and is the signature of a mass removal -- most
// plausibly an EOL release shared/protected_paths.py's filter did not cover.
const LARGE_DELETION_THRESHOLD = 1000;

// ===========================================
// API Client
// ===========================================

const api = {
    async request(endpoint, options = {}) {
        const url = `${config.apiBase}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        if (state.token) {
            headers['Authorization'] = `Bearer ${state.token}`;
        }

        try {
            const response = await fetch(url, { ...options, headers });

            if (response.status === 401) {
                this.logout();
                return null;
            }

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                let message = `HTTP ${response.status}`;
                if (typeof error.detail === 'string') {
                    message = error.detail;
                } else if (Array.isArray(error.detail) && error.detail.length > 0) {
                    message = error.detail.map(e => e.msg || JSON.stringify(e)).join(', ');
                }
                throw new Error(message);
            }

            return response.status === 204 ? null : await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    get(endpoint) {
        return this.request(endpoint);
    },

    post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },

    patch(endpoint, data) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
    },

    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    },

    async login(username, password) {
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch(`${config.apiBase}/auth/token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData
        });

        if (!response.ok) {
            throw new Error('Invalid credentials');
        }

        return response.json();
    },

    logout() {
        state.token = null;
        state.user = null;
        localStorage.removeItem(config.tokenKey);
        router.navigate('login');
    }
};

// ===========================================
// Router
// ===========================================

const router = {
    routes: {
        login: { title: 'Login', requiresAuth: false, render: renderLoginPage },
        dashboard: { title: 'Dashboard', requiresAuth: true, render: renderDashboard },
        mirrors: { title: 'Mirrors', requiresAuth: true, render: renderMirrors },
        'sync-failures': { title: 'Sync Failures', requiresAuth: true, render: renderSyncFailures },
        'protected-paths': { title: 'Protected Paths', requiresAuth: true, render: renderProtectedPaths },
        users: { title: 'Users', requiresAuth: true, render: renderUsers, requiredRole: 'admin' },
        'audit-logs': { title: 'Audit Logs', requiresAuth: true, render: renderAuditLogs, requiredRole: 'admin' },
        settings: { title: 'Settings', requiresAuth: true, render: renderSettings }
    },

    navigate(page) {
        const route = this.routes[page];
        if (!route) {
            page = 'dashboard';
        }

        if (route?.requiresAuth && !state.token) {
            page = 'login';
        }

        if (route?.requiredRole === 'admin' && state.user?.role !== 'admin') {
            Toast.show('Admin access required', 'error');
            page = 'dashboard';
        }

        state.currentPage = page;
        window.history.pushState({ page }, '', `#${page}`);
        this.render();
    },

    async render() {
        const route = this.routes[state.currentPage];
        const app = document.getElementById('app');

        if (!route) {
            this.navigate('dashboard');
            return;
        }

        if (route.requiresAuth && !state.token) {
            this.navigate('login');
            return;
        }

        if (state.currentPage === 'login') {
            setHtml(app, await route.render());
        } else {
            setHtml(app, renderLayout(await route.render(), route.title));
        }

        attachEventListeners();
    },

    init() {
        window.addEventListener('popstate', (e) => {
            const page = e.state?.page || window.location.hash.slice(1) || 'dashboard';
            this.navigate(page);
        });

        const hash = window.location.hash.slice(1);
        this.navigate(hash || 'dashboard');
    }
};

// ===========================================
// Layout Components
// ===========================================

function renderLayout(content, title) {
    const isAdmin = state.user?.role === 'admin';
    const isOperator = ['admin', 'operator'].includes(state.user?.role);

    return html`
        <div class="app-layout">
            <aside class="sidebar">
                <div class="sidebar-header">
                    <div class="sidebar-logo">
                        <span class="sidebar-logo-icon">🔄</span>
                        <span>BSD Mirror</span>
                    </div>
                </div>
                
                <nav class="sidebar-nav">
                    <div class="nav-section">
                        <div class="nav-section-title">Overview</div>
                        <a class="nav-item ${state.currentPage === 'dashboard' ? 'active' : ''}" data-nav="dashboard">
                            <span class="nav-item-icon">📊</span>
                            <span>Dashboard</span>
                        </a>
                    </div>
                    
                    <div class="nav-section">
                        <div class="nav-section-title">Management</div>
                        <a class="nav-item ${state.currentPage === 'mirrors' ? 'active' : ''}" data-nav="mirrors">
                            <span class="nav-item-icon">💾</span>
                            <span>Mirrors</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'sync-failures' ? 'active' : ''}" data-nav="sync-failures">
                            <span class="nav-item-icon">⚠️</span>
                            <span>Sync Failures</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'protected-paths' ? 'active' : ''}" data-nav="protected-paths">
                            <span class="nav-item-icon">🔒</span>
                            <span>Protected Paths</span>
                        </a>
                        ${isAdmin ? html`
                        <a class="nav-item ${state.currentPage === 'users' ? 'active' : ''}" data-nav="users">
                            <span class="nav-item-icon">👥</span>
                            <span>Users</span>
                        </a>
                        ` : ''}
                    </div>
                    
                    ${isAdmin ? html`
                    <div class="nav-section">
                        <div class="nav-section-title">System</div>
                        <a class="nav-item ${state.currentPage === 'audit-logs' ? 'active' : ''}" data-nav="audit-logs">
                            <span class="nav-item-icon">📋</span>
                            <span>Audit Logs</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'settings' ? 'active' : ''}" data-nav="settings">
                            <span class="nav-item-icon">⚙️</span>
                            <span>Settings</span>
                        </a>
                    </div>
                    ` : ''}
                </nav>
                
                <div class="sidebar-footer">
                    <div class="user-info">
                        <div class="user-avatar">${state.user?.username?.[0]?.toUpperCase() || 'A'}</div>
                        <div class="user-details">
                            <div class="user-name">${state.user?.username || 'Admin'}</div>
                            <div class="user-role">${state.user?.role || 'Unknown'}</div>
                        </div>
                    </div>
                    <button class="btn btn-secondary btn-sm u-full-width u-mt-sm" data-action="logout">
                        Logout
                    </button>
                </div>
            </aside>
            
            <main class="main-content">
                <header class="header">
                    <h1 class="header-title">${title}</h1>
                    <div class="header-actions">
                        <a href="/" class="btn btn-secondary btn-sm" target="_blank">
                            View Public Site
                        </a>
                    </div>
                </header>
                
                <div class="page-content">
                    ${content}
                </div>
            </main>
        </div>
        
        <div class="toast-container" id="toastContainer"></div>
        <div class="modal-overlay" id="modalOverlay">
            <div class="modal" id="modal"></div>
        </div>
    `;
}

// ===========================================
// Toast Notifications
// ===========================================

const Toast = {
    show(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        setHtml(toast, html`
            <span>${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
            <span>${message}</span>
        `);

        container.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }
};

// ===========================================
// Modal
// ===========================================

const Modal = {
    show(title, content, actions = '') {
        const overlay = document.getElementById('modalOverlay');
        const modal = document.getElementById('modal');

        setHtml(modal, html`
            <div class="modal-header">
                <h3 class="modal-title">${title}</h3>
                <button class="modal-close" data-action="closeModal">×</button>
            </div>
            <div class="modal-body">
                ${content}
            </div>
            ${actions ? html`<div class="modal-footer">${actions}</div>` : ''}
        `);

        overlay.classList.add('active');
    },

    close() {
        document.getElementById('modalOverlay')?.classList.remove('active');
    }
};

// ===========================================
// Page Renderers
// ===========================================

function renderLoginPage() {
    return html`
        <div class="login-page">
            <div class="login-card">
                <div class="login-header">
                    <div class="login-logo">🔄</div>
                    <h1 class="login-title">BSD Mirror Admin</h1>
                    <p class="login-subtitle">Sign in to continue</p>
                </div>
                
                <form id="loginForm">
                    <div class="form-group">
                        <label class="form-label" for="username">Username</label>
                        <input type="text" id="username" class="form-input" placeholder="Enter username" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="password">Password</label>
                        <input type="password" id="password" class="form-input" placeholder="Enter password" required>
                    </div>
                    <button type="submit" class="btn btn-primary u-full-width">
                        Sign In
                    </button>
                </form>
            </div>
        </div>
    `;
}

async function renderDashboard() {
    try {
        state.data.dashboard = await api.get('/admin/dashboard');
    } catch (error) {
        return html`<div class="card"><p>Error loading dashboard: ${error.message}</p></div>`;
    }

    const d = state.data.dashboard;

    // A second, independent fetch. GET /api/admin/health-checks always
    // answers 200 on its own (see backend/app/core/health_status.py), but
    // the fetch itself can still fail here -- an expired token mid-load, a
    // network blip -- and that failure must degrade to the "unknown" card
    // below, not take the rest of an otherwise-working dashboard down with
    // it (renderHealthChecksCard treats null the same as a real "unknown").
    let healthChecks = null;
    try {
        healthChecks = await api.get('/admin/health-checks');
    } catch (error) {
        healthChecks = null;
    }
    state.data.healthChecks = healthChecks;

    return html`
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">💾</span>
                </div>
                <div class="stat-card-value">${d.mirrors.total}</div>
                <div class="stat-card-label">Total Mirrors</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">✅</span>
                </div>
                <div class="stat-card-value">${d.mirrors.active}</div>
                <div class="stat-card-label">Active Mirrors</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">🔄</span>
                </div>
                <div class="stat-card-value">${d.mirrors.syncing}</div>
                <div class="stat-card-label">Currently Syncing</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">👥</span>
                </div>
                <div class="stat-card-value">${d.users.total}</div>
                <div class="stat-card-label">Admin Users</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">🗄️</span>
                    ${d.storage.percent_used != null ? html`
                    <span class="stat-card-trend ${d.storage.percent_used >= DISK_USAGE_WARNING_PERCENT ? 'down' : 'up'}">${d.storage.percent_used}% used</span>
                    ` : ''}
                </div>
                <div class="stat-card-value">${d.storage.free_bytes != null ? formatBytes(d.storage.free_bytes) : 'Unknown'}</div>
                <div class="stat-card-label">
                    ${d.storage.total_bytes != null
                        ? html`Disk free of ${formatBytes(d.storage.total_bytes)} (${formatBytes(d.storage.used_bytes)} used)`
                        : 'Disk capacity unavailable'}
                </div>
            </div>
        </div>

        ${renderHealthChecksCard(healthChecks)}

        <div class="u-grid-2">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">Recent Sync Jobs</h3>
                </div>
                <ul class="activity-list">
                    ${d.recent_syncs.length ? d.recent_syncs.map(sync => html`
                        <li class="activity-item">
                            <div class="activity-icon">🔄</div>
                            <div class="activity-content">
                                <div class="activity-text">
                                    Mirror #${sync.mirror_id} -
                                    <span class="status-badge ${sync.status}">${sync.status}</span>
                                    ${sync.files_deleted ? filesDeletedBadge(sync.files_deleted) : ''}
                                </div>
                                <div class="activity-time">${formatDate(sync.created_at)}</div>
                            </div>
                        </li>
                    `) : html`<li class="activity-item"><div class="activity-content">No recent sync jobs</div></li>`}
                </ul>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">Recent Activity</h3>
                </div>
                <ul class="activity-list">
                    ${d.recent_activity.length ? d.recent_activity.map(log => html`
                        <li class="activity-item">
                            <div class="activity-icon">${getActivityIcon(log.action)}</div>
                            <div class="activity-content">
                                <div class="activity-text">${formatAction(log.action)}</div>
                                <div class="activity-time">${formatDate(log.created_at)}</div>
                            </div>
                        </li>
                    `) : html`<li class="activity-item"><div class="activity-content">No recent activity</div></li>`}
                </ul>
            </div>
        </div>
    `;
}

// ===========================================
// Health Checks card (Dashboard)
// ===========================================
//
// GET /api/admin/health-checks (backend/app/core/health_status.py) reports
// on scripts/health_check.sh -- the hourly, systemd-timed script that alerts
// Discord on a transition, not this backend's own liveness check. That
// script's only visible output today is a Discord message, so a quiet
// channel and a dead timer look identical from here; this card is what
// closes that gap on the dashboard itself.
//
// `health` is null both for a real fetch failure (see renderDashboard) and
// for a value the backend itself could not produce (its own "unknown"
// states use null fields the same way) -- UNREACHABLE_HEALTH mirrors that
// exact shape so both paths render through the one function below instead
// of a second, easily-drifting "fetch failed" branch.

const UNREACHABLE_HEALTH = {
    state: 'unknown',
    reason: 'Could not load health-check status.',
    finished_at: null,
    age_seconds: null,
    stale_after_seconds: null,
    counts: null,
    ok: [],
    bad: [],
    skipped: [],
    warnings: [],
    alerting: null,
    state_persisted: null
};

// Reuses three of the four existing `.status-badge` colour variants (see
// admin.css) -- none of the five health states maps onto Mirror.status's set
// exactly. `active` (green) and `error` (red) fit ok and failing; unknown
// gets the muted `disabled` tint, since "no signal at all" is a different
// thing from "a problem was seen". stale and incomplete needed their own
// look rather than sharing `syncing`: a checker that hasn't reported in a
// while (stale) and one that ran but skipped checks or never sent its alert
// (incomplete) are different problems, and this card exists precisely so
// neither is ever mistaken for the others -- least of all for ok. `stale`
// keeps the amber `syncing` tint (still "time-based, not a hard failure");
// `incomplete` gets its own blue `health-incomplete` tint, defined
// alongside the other four in admin.css.
const HEALTH_STATE_BADGE_CLASS = {
    ok: 'active',
    stale: 'syncing',
    incomplete: 'health-incomplete',
    failing: 'error',
    unknown: 'disabled'
};

const HEALTH_STATE_LABEL = {
    ok: 'OK',
    stale: 'Stale',
    incomplete: 'Incomplete',
    failing: 'Failing',
    unknown: 'Unknown'
};

/**
 * One of the four lists on the card: a heading with a count, then either the
 * items (via `renderItem`, which may return a plain string or a nested
 * html`` fragment -- both are escaped the same way by the outer template)
 * or a placeholder `<li>` when there are none, matching the empty-state
 * shape Recent Sync Jobs / Recent Activity above already use.
 */
function healthChecklistSection(title, items, emptyLabel, icon, renderItem) {
    return html`
        <h4 class="card-subtitle">${title} (${items.length})</h4>
        <ul class="health-check-list">
            ${items.length ? items.map(item => html`
                <li class="health-check-row">
                    <div class="health-check-icon">${icon}</div>
                    <div class="health-check-content">
                        <div class="health-check-text">${renderItem(item)}</div>
                    </div>
                </li>
            `) : html`<li class="health-check-row"><div class="health-check-content">${emptyLabel}</div></li>`}
        </ul>
    `;
}

function renderHealthChecksCard(health) {
    const h = health || UNREACHABLE_HEALTH;
    const badgeClass = HEALTH_STATE_BADGE_CLASS[h.state] || 'disabled';
    const label = HEALTH_STATE_LABEL[h.state] || h.state || 'Unknown';
    const age = formatHealthAge(h.age_seconds);

    return html`
        <div class="card u-mt-md">
            <div class="card-header">
                <h3 class="card-title">Health Checks</h3>
            </div>
            <div class="u-row-8">
                <span class="status-badge ${badgeClass}">${label}</span>
                <span>${h.reason || 'No health-check report is available.'}</span>
            </div>
            <p class="u-text-muted u-text-sm u-mt-sm">
                ${h.finished_at
                    ? html`Last ran ${formatDate(h.finished_at)}${age ? html` (${age})` : ''}`
                    : 'Last run: unknown'}
            </p>
            <div class="u-mt-sm">
                ${healthChecklistSection('Bad', h.bad || [], 'No failing checks', '❌',
                    (item) => `${item.label}: ${item.detail}`)}
                ${healthChecklistSection('Skipped', h.skipped || [], 'No skipped checks', '⏭️',
                    (item) => `${item.check}: ${item.reason}`)}
                ${healthChecklistSection('Warnings', h.warnings || [], 'No warnings', '⚠️',
                    (item) => item)}
                ${healthChecklistSection('OK', h.ok || [], 'No checks reported ok', '✅',
                    (item) => item)}
            </div>
        </div>
    `;
}

async function renderMirrors() {
    try {
        state.data.mirrors = await api.get('/mirrors/');
    } catch (error) {
        return html`<div class="card"><p>Error loading mirrors: ${error.message}</p></div>`;
    }

    return html`
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Mirror Status</h3>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Status</th>
                            <th>Size</th>
                            <th>Last Sync</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${state.data.mirrors.map(mirror => html`
                            <tr>
                                <td>
                                    <strong>${mirror.name}</strong>
                                    <br><small class="u-text-muted">${mirror.url_path}</small>
                                </td>
                                <td>
                                    <span class="status-badge ${mirror.status}">
                                        <span class="status-dot"></span>
                                        ${mirror.status}
                                    </span>
                                </td>
                                <td>${mirror.total_size_human || '--'}</td>
                                <td>${mirror.last_sync_completed ? formatDate(mirror.last_sync_completed) : 'Never'}</td>
                                <td>
                                    <button class="btn btn-primary btn-sm" data-action="syncMirror" data-id="${mirror.id}">
                                        Sync Now
                                    </button>
                                    <button class="btn btn-secondary btn-sm" data-action="viewMirror" data-id="${mirror.id}">
                                        Details
                                    </button>
                                </td>
                            </tr>
                        `)}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

/**
 * Recent sync failures across every mirror (GET /api/admin/sync-failures).
 *
 * The backend already collapses repeated identical (mirror, error_message)
 * failures into one incident with an occurrence count -- see
 * app.core.sync_failures -- so this renders that grouping rather than a raw
 * per-job list. error_message is rsync's own stderr: untrusted text from an
 * external process, capable of carrying paths, quotes and newlines, and it
 * goes through the same html`` escaping as everything else in this file.
 */
async function renderSyncFailures() {
    try {
        state.data.syncFailures = await api.get('/admin/sync-failures');
    } catch (error) {
        return html`<div class="card"><p>Error loading sync failures: ${error.message}</p></div>`;
    }

    const d = state.data.syncFailures;

    return html`
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">❌</span>
                </div>
                <div class="stat-card-value">${d.totals.failed}</div>
                <div class="stat-card-label">Failed (last ${d.period_days}d)</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">✅</span>
                </div>
                <div class="stat-card-value">${d.totals.completed}</div>
                <div class="stat-card-label">Completed (last ${d.period_days}d)</div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Failures by Mirror</h3>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Mirror</th>
                            <th>Failed</th>
                            <th>Completed</th>
                            <th>Failure Rate</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${d.by_mirror.map(m => html`
                            <tr>
                                <td><strong>${m.mirror_name}</strong></td>
                                <td class="${m.failed > 0 ? 'u-text-error' : ''}">${m.failed}</td>
                                <td>${m.completed}</td>
                                <td>${m.failure_rate_percent != null ? m.failure_rate_percent + '%' : '--'}</td>
                            </tr>
                        `)}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="card u-mt-md">
            <div class="card-header">
                <h3 class="card-title">Recent Failure Incidents</h3>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Mirror</th>
                            <th>Error</th>
                            <th>Occurrences</th>
                            <th>First Seen</th>
                            <th>Last Seen</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${d.incidents.length ? d.incidents.map(inc => html`
                            <tr>
                                <td><strong>${inc.mirror_name}</strong></td>
                                <td><code class="code-block">${inc.error_message || '(no error message recorded)'}</code></td>
                                <td>${inc.occurrences.toLocaleString()}</td>
                                <td>${formatDate(inc.first_seen)}</td>
                                <td>${formatDate(inc.last_seen)}</td>
                                <td>
                                    <button class="btn btn-secondary btn-sm" data-action="viewSyncLogs" data-id="${inc.latest_job_id}">
                                        View Logs
                                    </button>
                                </td>
                            </tr>
                        `) : html`<tr><td colspan="6">No sync failures in the last ${d.period_days} days</td></tr>`}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

/**
 * Which release trees are frozen against rsync --delete
 * (GET /api/admin/protected-paths), plus what is actually on disk and
 * whether it lines up with that list (GET /api/admin/archive-inventory).
 *
 * The patterns list is read-only by design -- see shared/protected_paths.py
 * and app.core.protected_paths_view. There is no corresponding PATCH/POST
 * action anywhere in this file; do not add one here.
 *
 * Two independent fetches, the same shape renderDashboard already uses for
 * its health-checks card: a failed archive-inventory fetch degrades that
 * section alone to an error card (see renderArchiveInventorySection) and
 * must never take down the pattern list below it, which has its own,
 * separate failure mode (the first try/catch, unchanged from before this
 * inventory existed).
 */
async function renderProtectedPaths() {
    try {
        state.data.protectedPaths = await api.get('/admin/protected-paths');
    } catch (error) {
        return html`<div class="card"><p>Error loading protected paths: ${error.message}</p></div>`;
    }

    const groups = state.data.protectedPaths.groups;

    let inventory = null;
    let inventoryError = null;
    try {
        inventory = await api.get('/admin/archive-inventory');
        state.data.archiveInventory = inventory;
    } catch (error) {
        inventoryError = error.message;
    }

    return html`
        <div class="card">
            <div class="u-pad-body">
                <p class="u-text-muted u-text-sm">
                    These release trees are exempt from rsync's <code>--delete</code> and
                    survive even after upstream stops carrying them. This list is read-only
                    here -- it is configured in <code>shared/protected_paths.py</code> and
                    deployed with the sync service.
                </p>
            </div>
        </div>

        ${renderArchiveInventorySection(inventory, inventoryError)}

        ${groups.map(g => html`
        <div class="card u-mt-md">
            <div class="card-header">
                <h3 class="card-title">${g.mirror_names.length ? g.mirror_names.join(', ') : g.mirror_type}</h3>
                <span class="u-text-muted u-text-sm">${g.patterns.length.toLocaleString()} protected</span>
            </div>
            ${g.patterns.length ? html`
            <ul class="activity-list">
                ${g.patterns.map(pattern => html`
                    <li class="activity-item">
                        <code>${pattern}</code>
                    </li>
                `)}
            </ul>
            ` : html`<p class="u-text-muted u-pad-body">No protected paths configured.</p>`}
        </div>
        `)}
    `;
}

// Reuses the four existing `.status-badge` colour variants (see admin.css)
// the same way renderHealthChecksCard's HEALTH_STATE_BADGE_CLASS does --
// full/partial/none/unknown has no state of its own to draw from. `none` is
// deliberately the muted `disabled` tint, not red: it is the expected,
// correct state for a mirror's actively-served release (see
// shared/protected_paths.py's "WHY THE NEWEST RELEASE ... IS DELIBERATELY
// NOT HERE"), not a problem on its own -- `at_risk` (below) is what actually
// flags a problem.
const PROTECTION_BADGE_CLASS = {
    full: 'active',
    partial: 'syncing',
    none: 'disabled',
    unknown: 'error',
};

const PROTECTION_LABEL = {
    full: 'Protected',
    partial: 'Partial',
    none: 'Unprotected',
    unknown: 'Unknown',
};

function protectionBadge(protection) {
    const cls = PROTECTION_BADGE_CLASS[protection] || 'disabled';
    const label = PROTECTION_LABEL[protection] || protection;
    return html`<span class="status-badge ${cls}">${label}</span>`;
}

/**
 * Newest / latest-in-major / pre-release / at-risk, as a row of small badges
 * -- an array of SafeHtml, not a joined string, so html`` can interpolate it
 * the same way it already does for `groups.map(...)` elsewhere in this file.
 */
function releaseTagBadges(release) {
    const tags = [];
    // .info, not .disabled: .disabled's muted tint means "inactive"
    // everywhere else in this file (nav items, the mirror status badges),
    // and these are purely informational. See .status-badge.info in
    // admin.css.
    //
    // `current` (shared.protected_paths.CURRENT_RELEASES) is the field
    // at_risk actually keys off; newest/latest_in_major below are shown too
    // but are informational only -- see archive_inventory.py's module
    // docstring for why neither is a safe stand-in for "still served".
    if (release.current) {
        tags.push(html`<span class="status-badge info">Current</span>`);
    }
    if (release.kind === 'prerelease') {
        tags.push(html`<span class="status-badge info">Pre-release</span>`);
    }
    if (release.newest) {
        tags.push(html`<span class="status-badge info">Newest</span>`);
    } else if (release.latest_in_major) {
        tags.push(html`<span class="status-badge info">Latest in major</span>`);
    }
    // .status-badge.at-risk, not the old plain .u-text-error text: needs to
    // read as a pill matching its row-mates. See that class in admin.css for
    // why it is the most alarming colour available here, not a softer one.
    if (release.at_risk) {
        tags.push(html`<span class="status-badge at-risk">⚠️ At risk</span>`);
    }
    return tags;
}

/**
 * A comma-separated list of <code> spans -- used for both a release's
 * unprotected_locations and a mirror's protected_not_on_disk. Every item is
 * a directory name upstream controls (an architecture directory is an
 * arbitrary string as far as this file is concerned), so each one goes
 * through html`` like any other untrusted field; there is no shortcut here
 * because "it's just a path".
 */
function joinCodeList(items) {
    return items.map((item, i) => html`${i > 0 ? ', ' : ''}<code>${item}</code>`);
}

function releaseRows(release) {
    const unprotectedRow = release.protection === 'partial' && release.unprotected_locations.length
        ? html`
        <tr>
            <td colspan="5">
                <span class="u-text-muted u-text-sm code-chip-list">Unprotected: ${joinCodeList(release.unprotected_locations)}</span>
            </td>
        </tr>
        ` : '';

    return html`
        <tr>
            <td><strong>${release.version}</strong></td>
            <td>${protectionBadge(release.protection)}</td>
            <td><span class="u-row-8">${releaseTagBadges(release)}</span></td>
            <td>${release.location_count.toLocaleString()}</td>
            <td>${formatDate(release.modified)}</td>
        </tr>
        ${unprotectedRow}
    `;
}

function renderMirrorInventoryTable(mirror) {
    if (!mirror.releases.length) {
        return html`<p class="u-text-muted u-pad-body">No releases found on disk.</p>`;
    }

    return html`
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Version</th>
                        <th>Protection</th>
                        <th>Tags</th>
                        <th>Locations</th>
                        <th>Last Changed</th>
                    </tr>
                </thead>
                <tbody>
                    ${mirror.releases.map(release => releaseRows(release))}
                </tbody>
            </table>
        </div>
    `;
}

function renderMirrorInventoryCard(mirror) {
    const title = mirror.mirror_names.length ? mirror.mirror_names.join(', ') : mirror.mirror_type;

    return html`
    <div class="card u-mt-md">
        <div class="card-header">
            <h3 class="card-title">${title} -- On Disk</h3>
            ${mirror.available ? html`
            <span class="u-text-muted u-text-sm">${mirror.releases.length.toLocaleString()} releases</span>
            ` : ''}
        </div>
        ${mirror.available
            ? renderMirrorInventoryTable(mirror)
            : html`<p class="u-text-error u-pad-body">Unavailable: ${mirror.error}</p>`}
        ${mirror.available && mirror.incomplete ? html`
        <p class="u-text-error u-text-sm u-pad-body">
            This scan is incomplete -- treat the list above as a lower bound, not the full picture.
        </p>
        ` : ''}
        ${mirror.available && mirror.protected_not_on_disk.length ? html`
        <p class="u-text-error u-text-sm u-pad-body code-chip-list">
            Protected but missing from disk: ${joinCodeList(mirror.protected_not_on_disk)}
        </p>
        ` : ''}
        ${mirror.available && mirror.current_not_on_disk && mirror.current_not_on_disk.length ? html`
        <p class="u-text-error u-text-sm u-pad-body code-chip-list">
            Listed as current but missing from disk (CURRENT_RELEASES needs updating):
            ${joinCodeList(mirror.current_not_on_disk)}
        </p>
        ` : ''}
        ${mirror.available && mirror.stale_current && mirror.stale_current.length ? html`
        <p class="u-text-error u-text-sm u-pad-body code-chip-list">
            Listed as current but superseded by a newer current release (CURRENT_RELEASES needs
            updating): ${joinCodeList(mirror.stale_current)}
        </p>
        ` : ''}
        ${mirror.available && mirror.unclassified && mirror.unclassified.length ? html`
        <p class="u-text-error u-text-sm u-pad-body code-chip-list">
            Not recognised as a release: ${joinCodeList(mirror.unclassified)}
        </p>
        ` : ''}
        ${mirror.available && mirror.errors && mirror.errors.length ? html`
        <p class="u-text-error u-text-sm u-pad-body code-chip-list">
            Skipped while scanning: ${joinCodeList(mirror.errors)}
        </p>
        ` : ''}
        ${mirror.available && mirror.truncated ? html`
        <p class="u-text-muted u-text-sm u-pad-body">
            This mirror has more entries than could be scanned; the list above may be incomplete.
        </p>
        ` : ''}
    </div>
    `;
}

/**
 * The "On disk" inventory (GET /api/admin/archive-inventory), rendered above
 * the pattern list in renderProtectedPaths. `error` is the fetch's own
 * failure (network, an expired token) -- distinct from an individual
 * mirror's `available: false`, which is a normal, per-mirror state the
 * backend already reports inside a 200 (see app.core.archive_inventory) and
 * is handled by renderMirrorInventoryCard instead.
 */
function renderArchiveInventorySection(inventory, error) {
    if (error) {
        return html`
        <div class="card u-mt-md">
            <div class="card-header">
                <h3 class="card-title">On Disk</h3>
            </div>
            <p class="u-text-error u-pad-body">Error loading archive inventory: ${error}</p>
        </div>
        `;
    }

    return html`${(inventory?.mirrors || []).map(mirror => renderMirrorInventoryCard(mirror))}`;
}

async function renderUsers() {
    try {
        state.data.users = await api.get('/admin/users');
    } catch (error) {
        return html`<div class="card"><p>Error loading users: ${error.message}</p></div>`;
    }

    return html`
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">User Management</h3>
                <button class="btn btn-primary btn-sm" data-action="showAddUser">
                    + Add User
                </button>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Username</th>
                            <th>Email</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th>Last Login</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${state.data.users.map(user => html`
                            <tr>
                                <td><strong>${user.username}</strong></td>
                                <td>${user.email || '--'}</td>
                                <td>
                                    <span class="status-badge ${user.role === 'admin' ? 'active' : ''}">${user.role}</span>
                                </td>
                                <td>
                                    <span class="status-badge ${user.is_active ? 'active' : 'disabled'}">
                                        ${user.is_active ? 'Active' : 'Disabled'}
                                    </span>
                                </td>
                                <td>${user.last_login ? formatDate(user.last_login) : 'Never'}</td>
                                <td>
                                    <button class="btn btn-secondary btn-sm" data-action="editUser" data-id="${user.id}">
                                        Edit
                                    </button>
                                    ${user.id !== state.user?.id ? html`
                                    <button class="btn btn-danger btn-sm" data-action="deleteUser" data-id="${user.id}">
                                        Delete
                                    </button>
                                    ` : ''}
                                </td>
                            </tr>
                        `)}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

async function renderAuditLogs() {
    try {
        state.data.auditLogs = await api.get('/admin/audit-logs?limit=50');
    } catch (error) {
        return html`<div class="card"><p>Error loading audit logs: ${error.message}</p></div>`;
    }

    return html`
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Audit Logs</h3>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>User</th>
                            <th>Action</th>
                            <th>Resource</th>
                            <th>IP Address</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${state.data.auditLogs.map(log => html`
                            <tr>
                                <td>${formatDate(log.created_at)}</td>
                                <td>${log.username || 'System'}</td>
                                <td>${formatAction(log.action)}</td>
                                <td>${log.resource_type}${log.resource_id ? html` #${log.resource_id}` : ''}</td>
                                <td><code>${log.ip_address || '--'}</code></td>
                            </tr>
                        `)}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

async function renderSettings() {
    try {
        state.data.settings = await api.get('/admin/settings');
    } catch (error) {
        return html`<div class="card"><p>Error loading settings: ${error.message}</p></div>`;
    }

    const settings = {};
    for (const s of state.data.settings) {
        settings[s.key] = s;
    }

    return html`
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Sync Settings</h3>
            </div>
            <form id="settingsForm" class="u-pad-body">
                <div class="form-group">
                    <label class="form-label" for="setting_sync_schedule">Sync Schedule (Cron)</label>
                    <input type="text" id="setting_sync_schedule" class="form-input"
                        value="${settings.sync_schedule?.value || '0 4 * * *'}"
                        placeholder="0 4 * * *">
                    <small class="u-text-muted">${settings.sync_schedule?.description || ''}</small>
                </div>
                <div class="form-group">
                    <label class="form-label" for="setting_sync_bandwidth_limit">Bandwidth Limit (KB/s)</label>
                    <input type="number" id="setting_sync_bandwidth_limit" class="form-input"
                        value="${settings.sync_bandwidth_limit?.value || '0'}"
                        min="0" placeholder="0">
                    <small class="u-text-muted">${settings.sync_bandwidth_limit?.description || ''}</small>
                </div>
                <div class="form-group">
                    <label class="form-label" for="setting_sync_timeout">Sync Timeout (seconds)</label>
                    <input type="number" id="setting_sync_timeout" class="form-input"
                        value="${settings.sync_timeout?.value || '600'}"
                        min="60" placeholder="600">
                    <small class="u-text-muted">${settings.sync_timeout?.description || ''}</small>
                </div>
                <div class="form-group">
                    <label class="form-label" for="setting_sync_on_startup">Sync on Startup</label>
                    <select id="setting_sync_on_startup" class="form-input">
                        <option value="false" ${(settings.sync_on_startup?.value || 'false') === 'false' ? 'selected' : ''}>Disabled</option>
                        <option value="true" ${settings.sync_on_startup?.value === 'true' ? 'selected' : ''}>Enabled</option>
                    </select>
                    <small class="u-text-muted">${settings.sync_on_startup?.description || ''}</small>
                </div>
                <div class="u-row-12 u-mt-md">
                    <button type="button" class="btn btn-primary" data-action="saveSettings">Save Settings</button>
                </div>
            </form>
        </div>

        <div class="card u-mt-md">
            <div class="card-header">
                <h3 class="card-title">Settings Info</h3>
            </div>
            <div class="u-pad-body">
                <p class="u-text-muted u-text-sm">
                    Settings are stored in the database and applied by the sync service.
                    Changes to the sync schedule will take effect at the next scheduler iteration (within ~10 seconds).
                    Some settings may require a service restart to fully apply.
                </p>
                ${state.data.settings.length ? html`
                <table class="u-mt-sm u-full-width">
                    <thead>
                        <tr>
                            <th>Key</th>
                            <th>Last Updated</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${state.data.settings.map(s => html`
                            <tr>
                                <td><code>${s.key}</code></td>
                                <td>${formatDate(s.updated_at)}</td>
                            </tr>
                        `)}
                    </tbody>
                </table>
                ` : ''}
            </div>
        </div>
    `;
}

// ===========================================
// Action Handlers
// ===========================================

const actions = {
    async login(e) {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;

        try {
            const data = await api.login(username, password);
            state.token = data.access_token;
            localStorage.setItem(config.tokenKey, data.access_token);

            // Get user info
            state.user = await api.get('/auth/me');

            Toast.show('Login successful', 'success');
            router.navigate('dashboard');
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    logout() {
        api.logout();
        Toast.show('Logged out', 'success');
    },

    async syncMirror(mirrorId) {
        try {
            await api.post(`/admin/mirrors/${mirrorId}/sync`);
            Toast.show('Sync job started', 'success');
            router.render();
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    async viewMirror(mirrorId) {
        try {
            const mirror = await api.get(`/mirrors/${mirrorId}`);
            const history = await api.get(`/mirrors/${mirrorId}/sync-history`);
            const isOperator = ['admin', 'operator'].includes(state.user?.role);

            Modal.show(`Mirror: ${mirror.name}`, html`
                <div class="form-group">
                    <label class="form-label">Upstream URL</label>
                    ${isOperator ? html`
                    <div class="u-row-8">
                        <input type="text" id="mirrorUpstreamUrl" class="form-input u-flex-1" value="${mirror.upstream_url}">
                        <button class="btn btn-primary btn-sm" data-action="saveMirrorUpstream" data-id="${mirror.id}">Save</button>
                    </div>
                    <small class="u-text-muted">Change the rsync upstream URL (e.g. rsync://mirror.example.com/FreeBSD/)</small>
                    ` : html`
                    <code class="code-block">
                        ${mirror.upstream_url}
                    </code>
                    `}
                </div>
                <div class="form-group">
                    <label class="form-label">Local Path</label>
                    <code class="code-block">
                        ${mirror.local_path}
                    </code>
                </div>
                <div class="form-group">
                    <label class="form-label">Total Size</label>
                    <p>${mirror.total_size_human || 'Unknown'}</p>
                </div>
                <div class="form-group">
                    <label class="form-label">Recent Sync History</label>
                    <ul class="activity-list">
                        ${history.length ? history.map(h => html`
                            <li class="activity-item">
                                <div class="activity-icon">${h.status === 'completed' ? '✅' : h.status === 'failed' ? '❌' : h.status === 'running' ? '🔄' : '⏳'}</div>
                                <div class="activity-content">
                                    <div class="activity-text">
                                        ${h.status}${h.bytes_transferred ? ' - ' + formatBytes(h.bytes_transferred) : ''}
                                        ${h.files_deleted ? html` ${filesDeletedBadge(h.files_deleted)}` : ''}
                                        ${h.triggered_by ? html` <small>(by ${h.triggered_by})</small>` : ''}
                                    </div>
                                    <div class="activity-time">${formatDate(h.completed_at || h.started_at || h.created_at)}</div>
                                </div>
                                <div class="u-push-right">
                                    <button class="btn btn-secondary btn-sm" data-action="viewSyncLogs" data-id="${h.id}">
                                        View Logs
                                    </button>
                                </div>
                            </li>
                        `) : html`<li>No history</li>`}
                    </ul>
                </div>
            `, html`<button class="btn btn-secondary" data-action="closeModal">Close</button>`);
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    async saveMirrorUpstream(mirrorId) {
        const urlInput = document.getElementById('mirrorUpstreamUrl');
        if (!urlInput) return;

        const newUrl = urlInput.value.trim();
        if (!newUrl) {
            Toast.show('Upstream URL cannot be empty', 'error');
            return;
        }

        if (!newUrl.match(/^(rsync|https?):\/\//)) {
            Toast.show('URL must start with rsync://, http://, or https://', 'error');
            return;
        }

        try {
            await api.patch(`/admin/mirrors/${mirrorId}`, { upstream_url: newUrl });
            Toast.show('Upstream URL updated', 'success');
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    async viewSyncLogs(jobId) {
        try {
            const job = await api.get(`/admin/sync-jobs/${jobId}/logs`);
            const statusIcon = job.status === 'completed' ? '✅' : job.status === 'failed' ? '❌' : job.status === 'running' ? '🔄' : '⏳';
            const isRunning = job.status === 'running' || job.status === 'pending';

            Modal.show(`${statusIcon} Sync Job #${job.id}`, html`
                <div class="u-grid-2-tight">
                    <div>
                        <label class="form-label">Status</label>
                        <span class="status-badge ${job.status}">${job.status}</span>
                    </div>
                    <div>
                        <label class="form-label">Triggered By</label>
                        <p>${job.triggered_by || 'unknown'}</p>
                    </div>
                    <div>
                        <label class="form-label">Started</label>
                        <p>${job.started_at ? formatDate(job.started_at) : 'Not started'}</p>
                    </div>
                    <div>
                        <label class="form-label">Completed</label>
                        <p>${job.completed_at ? formatDate(job.completed_at) : '--'}</p>
                    </div>
                    ${job.files_transferred != null ? html`
                    <div>
                        <label class="form-label">Files Transferred</label>
                        <p>${job.files_transferred.toLocaleString()}</p>
                    </div>` : ''}
                    ${job.bytes_transferred != null ? html`
                    <div>
                        <label class="form-label">Bytes Transferred</label>
                        <p>${formatBytes(job.bytes_transferred)}</p>
                    </div>` : ''}
                    ${job.files_deleted != null ? html`
                    <div>
                        <label class="form-label">Files Deleted</label>
                        <p>${filesDeletedBadge(job.files_deleted)}</p>
                    </div>` : ''}
                </div>
                ${job.error_message ? html`
                <div class="form-group">
                    <label class="form-label u-text-error">Error</label>
                    <pre class="log-pre log-pre-error">${job.error_message}</pre>
                </div>` : ''}
                <div class="form-group">
                    <label class="form-label">Rsync Output</label>
                    <pre class="log-pre log-pre-output">${job.rsync_output || (isRunning ? 'Sync is in progress... click Refresh to update.' : 'No output available.')}</pre>
                </div>
            `, html`
                ${isRunning ? html`<button class="btn btn-primary btn-sm" data-action="viewSyncLogs" data-id="${job.id}">Refresh</button>` : ''}
                <button class="btn btn-secondary" data-action="closeModal">Close</button>
            `);
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    showAddUser() {
        Modal.show('Add User', html`
            <form id="addUserForm">
                <div class="form-group">
                    <label class="form-label">Username</label>
                    <input type="text" class="form-input" name="username" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Email (optional)</label>
                    <input type="email" class="form-input" name="email">
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input type="password" class="form-input" name="password" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Role</label>
                    <select class="form-input" name="role">
                        <option value="readonly">Read Only</option>
                        <option value="operator">Operator</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
            </form>
        `, html`
            <button class="btn btn-secondary" data-action="closeModal">Cancel</button>
            <button class="btn btn-primary" data-action="submitAddUser">Add User</button>
        `);
    },

    async submitAddUser() {
        const form = document.getElementById('addUserForm');
        const formData = new FormData(form);

        try {
            await api.post('/admin/users', {
                username: formData.get('username'),
                email: formData.get('email') || null,
                password: formData.get('password'),
                role: formData.get('role')
            });

            Modal.close();
            Toast.show('User created', 'success');
            router.render();
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    async deleteUser(userId) {
        if (!confirm('Are you sure you want to delete this user?')) return;

        try {
            await api.delete(`/admin/users/${userId}`);
            Toast.show('User deleted', 'success');
            router.render();
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    async saveSettings() {
        const settingsPayload = {};
        const keys = ['sync_schedule', 'sync_bandwidth_limit', 'sync_timeout', 'sync_on_startup'];

        for (const key of keys) {
            const el = document.getElementById(`setting_${key}`);
            if (el) {
                settingsPayload[key] = el.value;
            }
        }

        try {
            await api.patch('/admin/settings', { settings: settingsPayload });
            Toast.show('Settings saved', 'success');
            router.render();
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    async editUser(userId) {
        const user = state.data.users?.find(u => u.id === parseInt(userId));
        if (!user) {
            Toast.show('User not found', 'error');
            return;
        }

        Modal.show('Edit User', html`
            <form id="editUserForm">
                <div class="form-group">
                    <label class="form-label">Username</label>
                    <input type="text" class="form-input" value="${user.username}" disabled>
                </div>
                <div class="form-group">
                    <label class="form-label">Email</label>
                    <input type="email" class="form-input" name="email" value="${user.email || ''}">
                </div>
                <div class="form-group">
                    <label class="form-label">Role</label>
                    <select class="form-input" name="role">
                        <option value="readonly" ${user.role === 'readonly' ? 'selected' : ''}>Read Only</option>
                        <option value="operator" ${user.role === 'operator' ? 'selected' : ''}>Operator</option>
                        <option value="admin" ${user.role === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Status</label>
                    <select class="form-input" name="is_active">
                        <option value="true" ${user.is_active ? 'selected' : ''}>Active</option>
                        <option value="false" ${!user.is_active ? 'selected' : ''}>Disabled</option>
                    </select>
                </div>
                <input type="hidden" name="user_id" value="${user.id}">
            </form>
        `, html`
            <button class="btn btn-secondary" data-action="closeModal">Cancel</button>
            <button class="btn btn-primary" data-action="submitEditUser" data-id="${user.id}">Save Changes</button>
        `);
    },

    async submitEditUser(userId) {
        const form = document.getElementById('editUserForm');
        const formData = new FormData(form);

        try {
            await api.patch(`/admin/users/${userId}`, {
                email: formData.get('email') || null,
                role: formData.get('role'),
                is_active: formData.get('is_active') === 'true'
            });

            Modal.close();
            Toast.show('User updated', 'success');
            router.render();
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    closeModal() {
        Modal.close();
    }
};

// ===========================================
// Event Listeners
// ===========================================

function attachEventListeners() {
    // Login form — must be re-bound after each render since form is re-created
    document.getElementById('loginForm')?.addEventListener('submit', actions.login);
}

/**
 * Set up document-level event delegation for all [data-action] and [data-nav] clicks.
 * This runs once in init() and catches clicks on dynamically injected elements (modals, etc.).
 */
function setupGlobalEventDelegation() {
    // Close modal on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            Modal.close();
        }
    });

    document.addEventListener('click', (e) => {
        // Handle navigation links
        const navEl = e.target.closest('[data-nav]');
        if (navEl) {
            e.preventDefault();
            router.navigate(navEl.dataset.nav);
            return;
        }

        // Handle action buttons
        const actionEl = e.target.closest('[data-action]');
        if (actionEl) {
            const action = actionEl.dataset.action;
            const id = actionEl.dataset.id;
            if (actions[action]) {
                actions[action](id);
            }
            return;
        }

        // Click on modal overlay background closes modal
        if (e.target.id === 'modalOverlay') {
            Modal.close();
        }
    });
}

// ===========================================
// Utilities
// ===========================================

/**
 * A string that is already escaped and may be injected as HTML.
 *
 * The only ways to obtain one are html`...` and trustedHtml(). setHtml()
 * accepts nothing else, so "forgot to escape" is a TypeError at the sink
 * rather than an injection.
 */
class SafeHtml {
    constructor(value) {
        this.value = value;
    }

    toString() {
        return this.value;
    }
}

const HTML_ESCAPES = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
    '`': '&#96;'
};

/**
 * Escape for element text AND for quoted attribute values.
 *
 * Quotes are escaped, not just angle brackets: this file interpolates into
 * value="..." and class="..." in a dozen places, and a text-only escaper
 * leaves `" onfocus=alert(1) autofocus x="` intact in those.
 *
 * Not sufficient for: unquoted attribute values, href/src (javascript: URLs
 * survive HTML escaping), on* handlers, or <script>/<style> bodies. None of
 * those interpolate here, and tests/test_admin_js_escaping.py fails the build
 * if one appears.
 *
 * null and undefined render as ''. 0 and false render as "0" and "false" --
 * do not reintroduce a falsy check here.
 */
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>"'`]/g, (ch) => HTML_ESCAPES[ch]);
}

/**
 * Tagged template literal for building HTML. Every ${...} is escaped unless it
 * is already a SafeHtml, which makes escaping the default rather than a call
 * the next person has to remember.
 *
 *   html`<td>${user.username}</td>`   escaped
 *   html`<tr>${rows}</tr>`            SafeHtml / arrays of SafeHtml pass through
 */
function html(strings, ...values) {
    let out = strings[0];
    for (let i = 0; i < values.length; i++) {
        out += interpolateHtml(values[i]) + strings[i + 1];
    }
    return new SafeHtml(out);
}

function interpolateHtml(value) {
    if (value instanceof SafeHtml) return value.value;
    if (Array.isArray(value)) return value.map(interpolateHtml).join('');
    return escapeHtml(value);
}

/**
 * Escape hatch: assert that a string is already safe HTML. Deliberately ugly
 * and greppable. There are currently zero uses; adding one is a review point.
 */
function trustedHtml(value) {
    return new SafeHtml(String(value));
}

/**
 * The only writer to innerHTML in this file. Rejects plain strings so an
 * untagged template literal fails loudly instead of injecting.
 */
function setHtml(el, content) {
    if (!(content instanceof SafeHtml)) {
        throw new TypeError('setHtml() requires html`...`, got ' + typeof content);
    }
    el.innerHTML = content.value;
}

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

/**
 * A sync job's deleted-file count, marked distinctly once it crosses
 * LARGE_DELETION_THRESHOLD (see Display Thresholds near the top of this file).
 *
 * SyncJob.files_deleted has been populated on every job since sync_service.py
 * started parsing "Number of deleted files:", and until now nothing in this
 * UI rendered it anywhere: a sync that quietly removed an entire EOL release
 * looked identical, in this panel, to one that deleted nothing. A count that
 * still has to be looked for is not much better than no count at all, so a
 * large one gets the same error styling a failed sync gets, not just a
 * plain number next to the small ones.
 */
function filesDeletedBadge(count) {
    const large = count >= LARGE_DELETION_THRESHOLD;
    return html`<span class="${large ? 'u-text-error' : 'u-text-muted'}">${large ? '⚠️ ' : ''}${count.toLocaleString()} deleted</span>`;
}

function formatDate(dateStr) {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;

    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * `age_seconds` on the health-checks card: the backend's own computation
 * (server clock vs the report's finished_epoch), shown alongside
 * formatDate()'s client-computed "ago" so a card about clock-based staleness
 * is not itself silently trusting the viewer's browser clock for the number
 * that actually drove the stale/failing/incomplete decision.
 */
function formatHealthAge(seconds) {
    if (seconds == null) return null;
    const total = Math.max(0, Math.floor(seconds));
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h ago`;
    if (hours > 0) return `${hours}h ${minutes}m ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return `${total}s ago`;
}

function formatAction(action) {
    const actions = {
        'login_success': 'Logged in',
        'login_failed': 'Failed login attempt',
        'logout': 'Logged out',
        'user_created': 'Created user',
        'user_updated': 'Updated user',
        'user_deleted': 'Deleted user',
        'mirror_updated': 'Updated mirror',
        'sync_triggered': 'Triggered sync',
        'settings_updated': 'Updated settings'
    };
    return actions[action] || action.replace(/_/g, ' ');
}

function getActivityIcon(action) {
    const icons = {
        'login_success': '🔓',
        'login_failed': '🔒',
        'logout': '👋',
        'user_created': '👤',
        'user_updated': '✏️',
        'user_deleted': '🗑️',
        'mirror_updated': '💾',
        'sync_triggered': '🔄',
        'settings_updated': '⚙️'
    };
    return icons[action] || '📋';
}

// ===========================================
// Initialization
// ===========================================

async function init() {
    // Set up global event delegation once — catches all future clicks on
    // [data-action] and [data-nav] elements, including those inside modals
    setupGlobalEventDelegation();

    // Check for stored token
    const storedToken = localStorage.getItem(config.tokenKey);

    if (storedToken) {
        state.token = storedToken;

        try {
            state.user = await api.get('/auth/me');
        } catch (error) {
            // Token invalid, clear it
            localStorage.removeItem(config.tokenKey);
            state.token = null;
        }
    }

    router.init();

    // Refresh data periodically
    setInterval(() => {
        if (state.token && state.currentPage === 'dashboard') {
            router.render();
        }
    }, config.refreshInterval);
}

// Start the app
document.addEventListener('DOMContentLoaded', init);
