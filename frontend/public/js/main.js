/**
 * BSD Mirror - Main JavaScript
 */

// Theme management
const ThemeManager = {
    init() {
        const savedTheme = localStorage.getItem('theme') || 'light';
        this.setTheme(savedTheme);

        document.getElementById('themeToggle')?.addEventListener('click', () => {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            this.setTheme(newTheme);
        });
    },

    setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);

        const icon = document.querySelector('.theme-icon');
        if (icon) {
            icon.textContent = theme === 'dark' ? '☀️' : '🌙';
        }
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
const MirrorStatus = {
    async load() {
        const data = await API.get('/stats/overview');
        if (!data) return;

        // Update hero stats
        this.updateHeroStats(data);

        // Update mirror cards
        this.updateMirrorCards(data.mirrors);

        // Update overall status
        this.updateOverallStatus(data.mirrors);
    },

    updateOverallStatus(mirrors) {
        if (!mirrors) return;

        const statusCard = document.getElementById('overallStatus');
        if (!statusCard) return;

        const statuses = Object.values(mirrors).map(m => m.status);
        const anyError = statuses.includes('error');
        const anySyncing = statuses.includes('syncing');
        const allActive = statuses.every(s => s === 'active');

        const indicator = statusCard.querySelector('.status-indicator');
        const title = statusCard.querySelector('h3');
        const desc = statusCard.querySelector('p');
        const pulse = statusCard.querySelector('.pulse');

        if (anyError) {
            indicator.className = 'status-indicator degraded';
            if (pulse) pulse.style.background = 'var(--status-error, #ef4444)';
            title.textContent = 'Degraded Service';
            const errorMirrors = Object.entries(mirrors)
                .filter(([, m]) => m.status === 'error')
                .map(([name]) => name);
            desc.textContent = `${errorMirrors.join(', ')} ${errorMirrors.length === 1 ? 'is' : 'are'} experiencing issues.`;
        } else if (anySyncing) {
            indicator.className = 'status-indicator syncing';
            if (pulse) pulse.style.background = 'var(--primary, #e85d04)';
            title.textContent = 'Sync In Progress';
            const syncingMirrors = Object.entries(mirrors)
                .filter(([, m]) => m.status === 'syncing')
                .map(([name]) => name);
            desc.textContent = `${syncingMirrors.join(', ')} ${syncingMirrors.length === 1 ? 'is' : 'are'} currently syncing.`;
        } else if (allActive) {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
            title.textContent = 'All Systems Operational';
            desc.textContent = 'All mirrors are synchronized and available.';
        } else {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
            title.textContent = 'Systems Operational';
            desc.textContent = 'Mirrors are available.';
        }
    },

    updateHeroStats(data) {
        const statSize = document.getElementById('statSize');
        const statLastSync = document.getElementById('statLastSync');

        if (statSize && data.totals) {
            statSize.textContent = data.totals.size;
            statSize.closest('.stat-card')?.classList.remove('loading');
        }

        // Find most recent sync
        if (data.mirrors) {
            const syncs = Object.values(data.mirrors)
                .map(m => m.last_updated)
                .filter(Boolean)
                .sort()
                .reverse();

            if (syncs.length > 0 && statLastSync) {
                const lastSync = new Date(syncs[0]);
                statLastSync.textContent = this.formatRelativeTime(lastSync);
                statLastSync.closest('.stat-card')?.classList.remove('loading');
            }
        }
    },

    updateMirrorCards(mirrors) {
        if (!mirrors) return;

        for (const [name, mirror] of Object.entries(mirrors)) {
            const lowerName = name.toLowerCase();

            // Update status
            const statusEl = document.getElementById(`${lowerName}-status`);
            if (statusEl) {
                const dot = statusEl.querySelector('.status-dot');
                const text = statusEl.querySelector('.status-text');

                if (dot) {
                    dot.className = 'status-dot ' + mirror.status;
                }
                if (text) {
                    text.textContent = this.formatStatus(mirror.status);
                }
            }

            // Update size
            const sizeEl = document.getElementById(`${lowerName}-size`);
            if (sizeEl && mirror.size) {
                sizeEl.textContent = mirror.size;
            }

            // Update last sync
            const syncEl = document.getElementById(`${lowerName}-sync`);
            if (syncEl && mirror.last_updated) {
                const date = new Date(mirror.last_updated);
                syncEl.textContent = this.formatRelativeTime(date);
            }
        }
    },

    formatStatus(status) {
        const statusMap = {
            'active': 'Online',
            'syncing': 'Syncing...',
            'error': 'Error',
            'disabled': 'Offline'
        };
        return statusMap[status] || status;
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

// Set hostname in UI
function setHostname() {
    const hostname = window.location.hostname;
    document.querySelectorAll('#hostname, #rsynchost').forEach(el => {
        el.textContent = hostname;
    });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    ThemeManager.init();
    setHostname();
    MirrorStatus.load();

    // Refresh status every 60 seconds
    setInterval(() => MirrorStatus.load(), 60000);
});
