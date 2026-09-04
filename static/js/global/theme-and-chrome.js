/* Topbar scroll shadow, assistant-FAB first-visit peek, and light/dark theme
 * toggle -- present on every page (loaded directly from masterpage.html,
 * matching the existing plain-script convention used by agent-drawer.js/
 * nav-toggle.js). Three small, independent page-chrome behaviors that were
 * already grouped together in masterpage.html's inline script.
 */
/* ── Topbar scroll shadow ─────────────────────────── */
(function () {
    function update() {
        document.body.classList.toggle("tp-scrolled", window.scrollY > 2);
    }
    update();
    window.addEventListener("scroll", update, { passive: true });
})();

/* ── Assistant FAB first-visit peek ───────────────── */
(function () {
    var STORAGE_KEY = "tp.agentFabPeeked";
    var fab = document.getElementById("tp-agent-drawer-toggle");
    if (!fab || localStorage.getItem(STORAGE_KEY)) return;

    localStorage.setItem(STORAGE_KEY, "1");
    window.setTimeout(function () {
        if (fab.getAttribute("aria-expanded") === "true") return;
        fab.classList.add("is-peeking");
        window.setTimeout(function () {
            fab.classList.remove("is-peeking");
        }, 2600);
    }, 1200);
})();

/* ── Sticky sub-nav offset (topbar + breadcrumb bar height) ─────────
 * A page-level sticky element that should dock right below the
 * breadcrumb bar (.quick-nav, .ds-quick-nav) needs the combined height
 * of the fixed topbar AND the sticky breadcrumb bar under it -- using
 * just the topbar's own height left it sticking at nearly the same
 * position as the breadcrumb bar, which then rendered on top of it
 * (breadcrumb bar's z-index is far higher), hiding it almost entirely.
 * Measuring both here, once, avoids every page re-guessing pixel
 * offsets for chrome it doesn't own. */
(function () {
    function measure() {
        var desktopNav = document.querySelector(".tp-topbar-desktop");
        var mobileNav = document.querySelector("#main_header");
        var nav = (desktopNav && desktopNav.offsetHeight > 0) ? desktopNav
            : (mobileNav && mobileNav.offsetHeight > 0) ? mobileNav
            : null;
        var breadcrumb = document.querySelector(".tp-breadcrumb-bar");
        var height = (nav ? nav.offsetHeight : 0) + (breadcrumb ? breadcrumb.offsetHeight : 0);
        document.documentElement.style.setProperty("--tp-sticky-chrome-h", height + "px");
    }
    measure();
    window.addEventListener("resize", measure);
})();

/* ── Theme toggle ──────────────────────────────── */
(function () {
    var MODES = ["light", "dark"];
    var ICONS = {
        light: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="2.75"/><path d="M8 1.5V3M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1.06 1.06M11.54 11.54l1.06 1.06M12.6 3.4l-1.06 1.06M4.46 11.54l-1.06 1.06"/></svg>',
        dark:  '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M13.5 10.5A6.5 6.5 0 0 1 5.5 2.5a6.5 6.5 0 1 0 8 8z"/></svg>'
    };
    var LABELS = { light: "Light", dark: "Dark" };

    function getEffective(mode) {
        if (mode === "dark") return true;
        if (mode === "light") return false;
        return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }

    function apply(mode) {
        var dark = getEffective(mode);
        document.documentElement.classList.toggle("tp-dark", dark);
        var btn = document.getElementById("tp-theme-toggle");
        if (btn) {
            btn.querySelector(".tp-theme-toggle-icon").innerHTML = ICONS[mode];
            btn.querySelector(".tp-theme-toggle-label").textContent = LABELS[mode];
        }
        document.dispatchEvent(new CustomEvent("tp:themechange", {
            detail: {
                mode: mode,
                dark: dark
            }
        }));
    }

    function current() {
        var stored = localStorage.getItem("tp-theme");
        return MODES.indexOf(stored) !== -1 ? stored : "light";
    }

    function cycle() {
        var idx = (MODES.indexOf(current()) + 1) % MODES.length;
        var next = MODES[idx];
        if (next === "auto") {
            localStorage.removeItem("tp-theme");
        } else {
            localStorage.setItem("tp-theme", next);
        }
        apply(next);
    }

    function init() {
        apply(current());
        var btn = document.getElementById("tp-theme-toggle");
        if (btn) btn.addEventListener("click", cycle);
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
            if (current() === "auto") apply("auto");
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
