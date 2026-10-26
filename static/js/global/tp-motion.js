/*
 * Page motion for pages that opt in with [data-motion] on their root:
 *   - sections rise in as they scroll into view (above-the-fold ones play
 *     right away),
 *   - their numbers count up, their bars grow, grids and lists cascade,
 *   - content injected later (lazy rankings, re-rendered tables) gets the
 *     same entrance.
 * data-motion="calm" (protein page) keeps numbers, bars and small cascades
 * but skips the section fade-in, table-row cascades and the DOM watcher.
 * Classes: .tp-motion-section (+ .tp-reveal while below the fold) gets
 * .is-revealed; CSS lives in ui-system.css ("Motion"). Honors
 * prefers-reduced-motion by doing nothing.
 */
(function () {
    "use strict";

    var SECTION_SELECTOR = "section";
    var NUMBER_SELECTOR = [
        ".metric-value",
        ".evidence-headline",
        ".evidence-bd-value",
        ".targets-score-number",
        "[data-countup]"
    ].join(", ");
    var STAGGER_SELECTOR = [
        ".tp-metrics",
        ".evidence-grid",
        ".targets-list",
        ".tp-table tbody",
        "[data-stagger]"
    ].join(", ");
    var STAGGER_LIMIT = 24;
    var COUNT_DURATION = 1000;

    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // "5,081" / "0.999" / "5080 proteins" / "τ 0.49" / "84%": one standalone
    // number, optional symbol prefix and unit/word suffix. IDs such as
    // "VK055_3586" or "map00790" don't match.
    var NUMBER_RE = /^(\D*?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s*%|\s+\D.*)?$/;

    function firstNumberNode(el) {
        var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
        var node;
        while ((node = walker.nextNode())) {
            if (/\d/.test(node.nodeValue)) return node;
        }
        return null;
    }

    function prepareCount(el) {
        if (el.__tpCount || el.closest("[data-count]") || el.querySelector("[data-count]")) return null;
        var node = firstNumberNode(el);
        if (!node) return null;
        var text = node.nodeValue;
        var lead = text.match(/^\s*/)[0];
        var trail = text.match(/\s*$/)[0];
        var match = text.trim().match(NUMBER_RE);
        if (!match || /[A-Za-z0-9_]$/.test(match[1] || "")) return null;
        var integer = match[2];
        var decimals = match[3] ? match[3].length - 1 : 0;
        var value = parseFloat(integer.replace(/,/g, "") + (match[3] || ""));
        if (!isFinite(value) || value === 0) return null;
        var job = {
            node: node,
            value: value,
            decimals: decimals,
            commas: integer.indexOf(",") !== -1,
            before: lead + (match[1] || ""),
            after: (match[4] || "") + trail,
            original: text
        };
        el.__tpCount = job;
        node.nodeValue = job.before + format(0, job) + job.after;
        return job;
    }

    function format(value, job) {
        var fixed = value.toFixed(job.decimals);
        if (!job.commas) return fixed;
        var parts = fixed.split(".");
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        return parts.join(".");
    }

    function runCount(job) {
        if (!job || job.started) return;
        job.started = true;
        var start = null;
        function frame(now) {
            if (start === null) start = now;
            var t = Math.min(1, (now - start) / COUNT_DURATION);
            var eased = 1 - Math.pow(1 - t, 3);
            if (t < 1) {
                job.node.nodeValue = job.before + format(job.value * eased, job) + job.after;
                window.requestAnimationFrame(frame);
            } else {
                job.node.nodeValue = job.original;
            }
        }
        window.requestAnimationFrame(frame);
    }

    function stagger(scope, skipTables) {
        var containers = [];
        if (scope.matches && scope.matches(STAGGER_SELECTOR)) containers.push(scope);
        scope.querySelectorAll(STAGGER_SELECTOR).forEach(function (c) { containers.push(c); });
        containers.forEach(function (container) {
            if (skipTables && container.matches("tbody")) return;
            Array.prototype.slice.call(container.children, 0, STAGGER_LIMIT).forEach(function (child, i) {
                if (child.classList.contains("tp-stagger-item")) return;
                child.classList.add("tp-stagger-item");
                child.style.setProperty("--tp-i", i);
            });
        });
    }

    function init() {
        var root = document.querySelector("[data-motion]");
        if (!root || reduceMotion || !("IntersectionObserver" in window)) return;
        var calm = root.getAttribute("data-motion") === "calm";

        var numberObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                runCount(entry.target.__tpCount);
                numberObserver.unobserve(entry.target);
            });
        }, { threshold: 0.4 });

        function watchNumbers(scope) {
            scope.querySelectorAll(NUMBER_SELECTOR).forEach(function (el) {
                if (prepareCount(el)) numberObserver.observe(el);
            });
        }

        var sectionObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                entry.target.classList.add("is-revealed");
                sectionObserver.unobserve(entry.target);
            });
        }, { threshold: 0.08, rootMargin: "0px 0px -6% 0px" });

        var sections = Array.prototype.filter.call(root.querySelectorAll(SECTION_SELECTOR), function (section) {
            return !section.parentElement.closest(".tp-motion-section, " + SECTION_SELECTOR);
        });
        sections.forEach(function (section) {
            section.classList.add("tp-motion-section");
            if (!calm && section.getBoundingClientRect().top > window.innerHeight * 0.92) {
                section.classList.add("tp-reveal");
            }
            stagger(section, calm);
            sectionObserver.observe(section);
        });
        watchNumbers(root);

        // Lazily injected content (triage rankings, re-rendered table rows).
        if (!calm && "MutationObserver" in window) {
            new MutationObserver(function (mutations) {
                mutations.forEach(function (mutation) {
                    mutation.addedNodes.forEach(function (node) {
                        if (node.nodeType !== 1 || node.closest(".tp-fresh")) return;
                        if (!node.querySelector(".tp-bar-fill, .targets-score-fill, " + STAGGER_SELECTOR) &&
                            !node.matches(STAGGER_SELECTOR + ", tr")) return;
                        node.classList.add("tp-fresh");
                        if (node.matches("tr") && node.parentElement) {
                            stagger(node.parentElement);
                        } else {
                            stagger(node);
                        }
                        watchNumbers(node);
                    });
                });
            }).observe(root, { childList: true, subtree: true });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
