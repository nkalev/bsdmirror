/**
 * Applies the visitor's theme before the first paint.
 *
 * Loaded synchronously from <head>, ahead of the stylesheets, so a dark-mode
 * visitor is never painted in the light theme and then faded to dark by the
 * body's colour transition -- which is what happened while main.js set the
 * theme only on DOMContentLoaded. main.js's ThemeManager adopts what this sets
 * and owns the toggle.
 *
 * Order: an explicit choice saved by the toggle, else the operating system's
 * preference, else light. Storage can be unavailable (a private window, blocked
 * site data), and even reading it can throw; that must never cost the theme.
 */
(function () {
    var theme = null;
    try {
        var saved = window.localStorage.getItem('theme');
        if (saved === 'light' || saved === 'dark') {
            theme = saved;
        }
    } catch (e) {
        // No readable storage: fall through to the system preference.
    }
    if (theme === null) {
        var prefersDark = typeof window.matchMedia === 'function' &&
            window.matchMedia('(prefers-color-scheme: dark)').matches;
        theme = prefersDark ? 'dark' : 'light';
    }
    document.documentElement.setAttribute('data-theme', theme);
})();
