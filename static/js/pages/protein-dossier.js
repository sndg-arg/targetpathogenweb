/*
 * Target dossier behavior shared by the pathogen and human protein pages:
 * plain tab groups and the hero glance count-up.
 */
(function () {
    "use strict";

    // [data-tab] buttons switch the [data-tab-panel] with the same key inside
    // their [data-tab-group].
    function initTabGroups() {
        document.querySelectorAll("[data-tab-group]").forEach(function (group) {
            var tabs = group.querySelectorAll("[data-tab]");
            var panels = group.querySelectorAll("[data-tab-panel]");
            tabs.forEach(function (tab) {
                tab.addEventListener("click", function () {
                    var key = tab.getAttribute("data-tab");
                    tabs.forEach(function (t) {
                        var isActive = t === tab;
                        t.classList.toggle("is-active", isActive);
                        t.setAttribute("aria-selected", isActive ? "true" : "false");
                    });
                    panels.forEach(function (panel) {
                        panel.classList.toggle("is-hidden", panel.getAttribute("data-tab-panel") !== key);
                    });
                });
            });
        });
    }

    // Glance numbers count up once on load (ease-out, ~0.9 s).
    function initGlanceCountUp() {
        var targets = document.querySelectorAll(".protein-glance [data-count]");
        if (!targets.length) return;
        if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        var duration = 900;
        var start = null;
        var items = [];
        Array.prototype.forEach.call(targets, function (el) {
            var raw = (el.getAttribute("data-count") || "").replace(/,/g, "");
            var end = parseFloat(raw);
            if (!/^-?\d+(\.\d+)?$/.test(raw) || !isFinite(end)) return;
            var decimals = raw.indexOf(".") === -1 ? 0 : raw.split(".")[1].length;
            el.textContent = (0).toFixed(decimals);
            items.push({ el: el, end: end, decimals: decimals });
        });
        if (!items.length) return;
        function frame(now) {
            if (start === null) start = now;
            var t = Math.min(1, (now - start) / duration);
            var eased = 1 - Math.pow(1 - t, 3);
            items.forEach(function (item) {
                var value = item.end * eased;
                item.el.textContent = item.decimals
                    ? value.toFixed(item.decimals)
                    : Math.round(value).toLocaleString("en-US");
            });
            if (t < 1) window.requestAnimationFrame(frame);
        }
        window.requestAnimationFrame(frame);
    }

    // A link to a collapsed row (#pe-essentiality, #binding-site-evidence...)
    // opens it, then scrolls to it.
    function openHashTarget() {
        var id = decodeURIComponent((window.location.hash || "").slice(1));
        if (!id) return;
        var target = document.getElementById(id);
        if (!target) return;
        var details = target.tagName === "DETAILS" ? target : target.closest("details");
        if (details && !details.open) {
            details.open = true;
            target.scrollIntoView({ block: "start" });
        }
    }

    // "Show all N" under a collapsed list ([data-expand-target] = list id).
    function initExpandToggles() {
        document.querySelectorAll("[data-expand-target]").forEach(function (button) {
            var list = document.getElementById(button.getAttribute("data-expand-target"));
            if (!list) return;
            button.addEventListener("click", function () {
                var collapsed = list.classList.toggle("is-collapsed");
                button.textContent = collapsed ? button.dataset.labelMore : button.dataset.labelLess;
            });
        });
    }

    function ready(fn) {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
        else fn();
    }

    ready(function () {
        initTabGroups();
        initGlanceCountUp();
        initExpandToggles();
        openHashTarget();
        window.addEventListener("hashchange", openHashTarget);
    });
})();
