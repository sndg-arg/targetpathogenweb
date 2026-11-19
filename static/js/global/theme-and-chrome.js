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

    // Desktop topbar button plus the mobile menu one (the mobile navbar had no
    // theme control at all, so phones could never switch).
    var BUTTON_IDS = ["tp-theme-toggle", "tp-theme-toggle-mobile"];

    function apply(mode) {
        var dark = getEffective(mode);
        var shown = dark ? "dark" : "light";
        document.documentElement.classList.toggle("tp-dark", dark);
        BUTTON_IDS.forEach(function (id) {
            var btn = document.getElementById(id);
            if (!btn) return;
            var icon = btn.querySelector(".tp-theme-toggle-icon");
            var label = btn.querySelector(".tp-theme-toggle-label");
            if (icon) icon.innerHTML = ICONS[shown];
            if (label) label.textContent = LABELS[shown];
        });
        document.dispatchEvent(new CustomEvent("tp:themechange", {
            detail: {
                mode: mode,
                dark: dark
            }
        }));
    }

    // No stored choice = follow the operating system ("auto"), matching the
    // pre-paint script in masterpage.html. Defaulting to "light" here used to
    // undo that script and flash dark-mode users back to light.
    function current() {
        var stored = null;
        try { stored = localStorage.getItem("tp-theme"); } catch (e) {}
        return MODES.indexOf(stored) !== -1 ? stored : "auto";
    }

    function cycle() {
        var next = getEffective(current()) ? "light" : "dark";
        try { localStorage.setItem("tp-theme", next); } catch (e) {}
        apply(next);
    }

    function init() {
        apply(current());
        BUTTON_IDS.forEach(function (id) {
            var btn = document.getElementById(id);
            if (btn) btn.addEventListener("click", cycle);
        });
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

/* ── Breadcrumb "Back" link ────────────────────── */
/* Uses the browser history when the previous page was on this site, so the
 * page you return to keeps its filters, sort and scroll; otherwise (opened
 * from a bookmark/shared link) falls back to the parent breadcrumb. Shown only
 * when there is a parent crumb to go back to. */
(function () {
    var back = document.querySelector("[data-breadcrumb-back]");
    if (!back) return;
    var crumbLinks = back.parentElement.querySelectorAll(".tp-breadcrumb-link");
    if (crumbLinks.length < 2) return;
    var parentHref = crumbLinks[crumbLinks.length - 1].getAttribute("href");
    back.setAttribute("href", parentHref);
    back.hidden = false;
    var cameFromSite = false;
    try {
        cameFromSite = !!document.referrer && new URL(document.referrer).origin === window.location.origin;
    } catch (error) {
        cameFromSite = false;
    }
    back.addEventListener("click", function (event) {
        if (!cameFromSite || window.history.length < 2) return;
        event.preventDefault();
        window.history.back();
    });
})();

/* In-page section links (quick nav, "See evidence", ...) replace the URL hash
 * instead of adding a history entry, so Back (the button above or the
 * browser's) returns to the previous page, not the previous section. */
(function () {
    document.addEventListener("click", function (event) {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        var link = event.target.closest("a[href^='#']");
        if (!link || link.target || link.matches("[data-toggle], [data-bs-toggle]")) return;
        var id = decodeURIComponent(link.getAttribute("href").slice(1));
        var target = id && document.getElementById(id);
        if (!target) return;
        event.preventDefault();
        if (window.location.hash !== "#" + id) {
            var oldURL = window.location.href;
            window.history.replaceState(window.history.state, "", "#" + id);
            window.dispatchEvent(new HashChangeEvent("hashchange", { oldURL: oldURL, newURL: window.location.href }));
        }
        target.scrollIntoView({ block: "start" });
    });
})();
