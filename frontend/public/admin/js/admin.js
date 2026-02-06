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
        mirrors: null,
        users: null,
        auditLogs: null
    }
};

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
                throw new Error(error.detail || `HTTP ${response.status}`);
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
            app.innerHTML = await route.render();
        } else {
            app.innerHTML = renderLayout(await route.render(), route.title);
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

    return `
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
                        ${isAdmin ? `
                        <a class="nav-item ${state.currentPage === 'users' ? 'active' : ''}" data-nav="users">
                            <span class="nav-item-icon">👥</span>
                            <span>Users</span>
                        </a>
                        ` : ''}
                    </div>
                    
                    ${isAdmin ? `
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
                    <button class="btn btn-secondary btn-sm" style="width: 100%; margin-top: 12px;" data-action="logout">
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
        toast.innerHTML = `
            <span>${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
            <span>${message}</span>
        `;

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

        modal.innerHTML = `
            <div class="modal-header">
                <h3 class="modal-title">${title}</h3>
                <button class="modal-close" data-action="closeModal">×</button>
            </div>
            <div class="modal-body">
                ${content}
            </div>
            ${actions ? `<div class="modal-footer">${actions}</div>` : ''}
        `;

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
    return `
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
                    <button type="submit" class="btn btn-primary" style="width: 100%;">
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
        return `<div class="card"><p>Error loading dashboard: ${error.message}</p></div>`;
    }

    const d = state.data.dashboard;

    return `
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
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">Recent Sync Jobs</h3>
                </div>
                <ul class="activity-list">
                    ${d.recent_syncs.length ? d.recent_syncs.map(sync => `
                        <li class="activity-item">
                            <div class="activity-icon">🔄</div>
                            <div class="activity-content">
                                <div class="activity-text">
                                    Mirror #${sync.mirror_id} - 
                                    <span class="status-badge ${sync.status}">${sync.status}</span>
                                </div>
                                <div class="activity-time">${formatDate(sync.created_at)}</div>
                            </div>
                        </li>
                    `).join('') : '<li class="activity-item"><div class="activity-content">No recent sync jobs</div></li>'}
                </ul>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title">Recent Activity</h3>
                </div>
                <ul class="activity-list">
                    ${d.recent_activity.length ? d.recent_activity.map(log => `
                        <li class="activity-item">
                            <div class="activity-icon">${getActivityIcon(log.action)}</div>
                            <div class="activity-content">
                                <div class="activity-text">${formatAction(log.action)}</div>
                                <div class="activity-time">${formatDate(log.created_at)}</div>
                            </div>
                        </li>
                    `).join('') : '<li class="activity-item"><div class="activity-content">No recent activity</div></li>'}
                </ul>
            </div>
        </div>
    `;
}

async function renderMirrors() {
    try {
        state.data.mirrors = await api.get('/mirrors/');
    } catch (error) {
        return `<div class="card"><p>Error loading mirrors: ${error.message}</p></div>`;
    }

    return `
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
                        ${state.data.mirrors.map(mirror => `
                            <tr>
                                <td>
                                    <strong>${mirror.name}</strong>
                                    <br><small style="color: var(--text-muted)">${mirror.url_path}</small>
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
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

async function renderUsers() {
    try {
        state.data.users = await api.get('/admin/users');
    } catch (error) {
        return `<div class="card"><p>Error loading users: ${error.message}</p></div>`;
    }

    return `
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
                        ${state.data.users.map(user => `
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
                                    ${user.id !== state.user?.id ? `
                                    <button class="btn btn-danger btn-sm" data-action="deleteUser" data-id="${user.id}">
                                        Delete
                                    </button>
                                    ` : ''}
                                </td>
                            </tr>
                        `).join('')}
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
        return `<div class="card"><p>Error loading audit logs: ${error.message}</p></div>`;
    }

    return `
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
                        ${state.data.auditLogs.map(log => `
                            <tr>
                                <td>${formatDate(log.created_at)}</td>
                                <td>${log.username || 'System'}</td>
                                <td>${formatAction(log.action)}</td>
                                <td>${log.resource_type}${log.resource_id ? ` #${log.resource_id}` : ''}</td>
                                <td><code>${log.ip_address || '--'}</code></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderSettings() {
    return `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Settings</h3>
            </div>
            <p>Settings configuration coming soon.</p>
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

            Modal.show(`Mirror: ${mirror.name}`, `
                <div class="form-group">
                    <label class="form-label">Upstream URL</label>
                    <code style="display: block; padding: 8px; background: var(--bg-tertiary); border-radius: 6px;">
                        ${mirror.upstream_url}
                    </code>
                </div>
                <div class="form-group">
                    <label class="form-label">Local Path</label>
                    <code style="display: block; padding: 8px; background: var(--bg-tertiary); border-radius: 6px;">
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
                        ${history.map(h => `
                            <li class="activity-item">
                                <div class="activity-icon">${h.status === 'completed' ? '✅' : h.status === 'failed' ? '❌' : '🔄'}</div>
                                <div class="activity-content">
                                    <div class="activity-text">${h.status} - ${h.bytes_transferred_human || '--'}</div>
                                    <div class="activity-time">${formatDate(h.completed_at || h.started_at)}</div>
                                </div>
                            </li>
                        `).join('') || '<li>No history</li>'}
                    </ul>
                </div>
            `, `<button class="btn btn-secondary" data-action="closeModal">Close</button>`);
        } catch (error) {
            Toast.show(error.message, 'error');
        }
    },

    showAddUser() {
        Modal.show('Add User', `
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
        `, `
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

    closeModal() {
        Modal.close();
    }
};

// ===========================================
// Event Listeners
// ===========================================

function attachEventListeners() {
    // Login form
    document.getElementById('loginForm')?.addEventListener('submit', actions.login);

    // Navigation
    document.querySelectorAll('[data-nav]').forEach(el => {
        el.addEventListener('click', (e) => {
            e.preventDefault();
            router.navigate(el.dataset.nav);
        });
    });

    // Action buttons
    document.querySelectorAll('[data-action]').forEach(el => {
        el.addEventListener('click', (e) => {
            const action = el.dataset.action;
            const id = el.dataset.id;

            if (actions[action]) {
                actions[action](id);
            }
        });
    });
}

// ===========================================
// Utilities
// ===========================================

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

function formatAction(action) {
    const actions = {
        'login_success': 'Logged in',
        'login_failed': 'Failed login attempt',
        'logout': 'Logged out',
        'user_created': 'Created user',
        'user_updated': 'Updated user',
        'user_deleted': 'Deleted user',
        'mirror_updated': 'Updated mirror',
        'sync_triggered': 'Triggered sync'
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
        'sync_triggered': '🔄'
    };
    return icons[action] || '📋';
}

// ===========================================
// Initialization
// ===========================================

async function init() {
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
