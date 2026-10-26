/*
 * Target dossier behavior shared by the pathogen and human protein pages:
 * plain tab groups and the hero glance count-up.
 */
(function () {
    "use strict";

    // Scroll el into view inside its own scrolling panel only. scrollIntoView
    // also scrolls the page, which on the full viewer (a fixed-height layout)
    // pushed the whole viewer up and left a blank band below it.
    function scrollWithinPanel(el, block) {
        var panel = el.parentElement;
        while (panel && panel !== document.body) {
            var overflowY = getComputedStyle(panel).overflowY;
            if ((overflowY === "auto" || overflowY === "scroll") && panel.scrollHeight > panel.clientHeight) break;
            panel = panel.parentElement;
        }
        if (!panel || panel === document.body) {
            el.scrollIntoView({ behavior: "smooth", block: block });
            return;
        }
        var offset = el.getBoundingClientRect().top - panel.getBoundingClientRect().top;
        if (block === "center") offset -= (panel.clientHeight - el.offsetHeight) / 2;
        panel.scrollBy({ top: offset - 8, behavior: "smooth" });
    }

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

    // ?pocket=p2rank:3 / fpocket:12 (links from the protein page): select that
    // pocket once the viewer has drawn its layers, as if it had been clicked.
    function openLinkedPocket() {
        var raw = new URLSearchParams(window.location.search).get("pocket") || "";
        var match = raw.match(/^(p2rank|fpocket):(.+)$/i);
        if (!match) return;
        var id = (match[1].toLowerCase() === "p2rank" ? "P2Rank #" : "FPocket #") + match[2];
        var card = Array.prototype.find.call(document.querySelectorAll(".pocket-card"), function (el) {
            return el.getAttribute("data-pocket-id") === id;
        });
        var head = card && card.querySelector(".js-inspect-pocket");
        if (!head) return;
        var core = card.getAttribute("data-pocket-core-repr") || "";
        var tries = 0;
        (function waitForViewer() {
            var reps = window.representations || {};
            if ((core && reps[core]) || tries > 60) {
                head.click();
                scrollWithinPanel(card, "center");
                return;
            }
            tries += 1;
            window.setTimeout(waitForViewer, 250);
        })();
    }

    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Pages that opt in with [data-motion]: sections below the fold rise in
    // as they scroll into view (their bars grow, the cell diagram lights up,
    // the topology chain draws itself).
    function initSectionReveal() {
        var root = document.querySelector("[data-motion]");
        if (!root || reduceMotion || !("IntersectionObserver" in window)) return;
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                entry.target.classList.add("is-revealed");
                observer.unobserve(entry.target);
            });
        }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
        root.querySelectorAll(".protein-card").forEach(function (section) {
            if (section.getBoundingClientRect().top < window.innerHeight * 0.92) return;
            section.classList.add("tp-reveal");
            observer.observe(section);
        });
    }

    // Structure viewers: once the camera is framed, start a little farther
    // and turned, then glide in while the canvas fades up.
    window.tpStructureReveal = function (stage, viewportEl, delay) {
        if (reduceMotion || !stage || !stage.viewer || !stage.animationControls) return;
        if (viewportEl) {
            viewportEl.classList.add("tp-structure-motion", "tp-structure-entering");
        }
        // Below the fold, wait until its section has scrolled in.
        var pending = viewportEl && viewportEl.closest(".tp-reveal:not(.is-revealed)");
        if (pending && "MutationObserver" in window) {
            var watcher = new MutationObserver(function () {
                if (!pending.classList.contains("is-revealed")) return;
                watcher.disconnect();
                window.tpStructureReveal(stage, viewportEl, 300);
            });
            watcher.observe(pending, { attributes: true, attributeFilter: ["class"] });
            return;
        }
        window.setTimeout(function () {
            var viewer = stage.viewer;
            var z = viewer.camera.position.z;
            var orientation = viewer.rotationGroup.quaternion.clone();
            stage.viewerControls.distance(z * 1.6);
            stage.viewerControls.spin([0, 1, 0], -0.5);
            if (viewportEl) viewportEl.classList.remove("tp-structure-entering");
            stage.animationControls.zoom(z, 1200);
            stage.animationControls.rotate(orientation, 1200);
        }, delay || 650);
    };

    function ready(fn) {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
        else fn();
    }

    ready(function () {
        initTabGroups();
        initGlanceCountUp();
        initExpandToggles();
        initSectionReveal();
        openLinkedPocket();
        openHashTarget();
        window.addEventListener("hashchange", openHashTarget);
    });
})();
