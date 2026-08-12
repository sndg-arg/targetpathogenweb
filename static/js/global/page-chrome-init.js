/* Table-export/scroll-hint init trigger, auto-dismiss flash messages, and the
 * global custom-tooltip system that replaces native [title] tooltips --
 * present on every page (loaded directly from masterpage.html, matching the
 * existing plain-script convention used by agent-drawer.js/nav-toggle.js).
 */
(function () {
    function initExports() {
        if (window.tpInitTableExports) {
            window.tpInitTableExports(document);
        }
        if (window.tpRefreshTableScrollHints) {
            window.tpRefreshTableScrollHints(document);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initExports, { once: true });
    } else {
        initExports();
    }

    window.addEventListener("resize", function () {
        if (window.tpRefreshTableScrollHints) {
            window.tpRefreshTableScrollHints(document);
        }
    });
})();

/* ── Auto-dismiss messages ── */
(function () {
    function dismissMsg(el) {
        el.classList.add("is-hiding");
        setTimeout(function () { el.remove(); }, 300);
    }
    document.querySelectorAll(".tp-message-close").forEach(function (btn) {
        btn.addEventListener("click", function () { dismissMsg(btn.closest(".tp-message")); });
    });
    document.querySelectorAll(".tp-message").forEach(function (msg) {
        setTimeout(function () { dismissMsg(msg); }, 5000);
    });
})();

/* ── Replace native title tooltips with the Target Pathogen tooltip ── */
(function () {
    const tooltip = document.createElement("div");
    tooltip.className = "tp-global-tooltip";
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);

    let activeEl = null;

    document.querySelectorAll("[title]").forEach(function (el) {
        const title = el.getAttribute("title");
        if (title && !el.getAttribute("data-tp-native-title")) {
            el.setAttribute("data-tp-native-title", title);
            el.removeAttribute("title");
        }
    });

    function getTitle(el) {
        return el.getAttribute("data-tp-native-title") || "";
    }

    function positionTooltip(el) {
        const text = getTitle(el).trim();
        if (!text) return;

        tooltip.textContent = text;
        tooltip.classList.remove("is-below", "is-visible");
        tooltip.style.width = "";
        tooltip.style.left = "0px";
        tooltip.style.top = "0px";

        const pad = 12;
        const gap = 8;
        const anchor = el.getBoundingClientRect();
        const size = tooltip.getBoundingClientRect();
        const width = Math.min(size.width || 260, window.innerWidth - (pad * 2));

        let left = anchor.left + (anchor.width / 2) - (width / 2);
        left = Math.max(pad, Math.min(left, window.innerWidth - pad - width));

        let top = anchor.top - size.height - gap;
        let below = false;
        if (top < pad) {
            top = anchor.bottom + gap;
            below = true;
            tooltip.classList.add("is-below");
        }

        const arrowLeft = anchor.left + (anchor.width / 2) - left;
        tooltip.style.left = left + "px";
        tooltip.style.top = top + "px";
        tooltip.style.setProperty("--tp-tooltip-arrow-left", Math.max(12, Math.min(width - 12, arrowLeft)) + "px");
        tooltip.classList.add("is-visible");
    }

    function showTooltip(el) {
        if (!getTitle(el).trim()) return;
        activeEl = el;
        positionTooltip(el);
    }

    function hideTooltip(el) {
        if (activeEl === el) {
            activeEl = null;
            tooltip.classList.remove("is-visible");
        }
    }

    document.addEventListener("pointerover", function (event) {
        if (!(event.target instanceof Element)) return;
        const el = event.target.closest("[data-tp-native-title]");
        if (el && event.relatedTarget instanceof Node && el.contains(event.relatedTarget)) return;
        if (el) showTooltip(el);
    });

    document.addEventListener("pointerout", function (event) {
        if (!(event.target instanceof Element)) return;
        const el = event.target.closest("[data-tp-native-title]");
        if (el && event.relatedTarget instanceof Node && el.contains(event.relatedTarget)) return;
        if (el) hideTooltip(el);
    });

    document.addEventListener("focusin", function (event) {
        if (!(event.target instanceof Element)) return;
        const el = event.target.closest("[data-tp-native-title]");
        if (el) showTooltip(el);
    });

    document.addEventListener("focusout", function (event) {
        if (!(event.target instanceof Element)) return;
        const el = event.target.closest("[data-tp-native-title]");
        if (el) hideTooltip(el);
    });

    window.addEventListener("resize", function () {
        if (activeEl) positionTooltip(activeEl);
    });

    document.addEventListener("scroll", function () {
        if (activeEl) positionTooltip(activeEl);
    }, true);
})();
