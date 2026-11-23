/* Bottom sheet -- present on every page (loaded directly from masterpage.html,
 * before the scripts that use it). On phones (<= 720px) every floating panel
 * becomes a sheet that slides up from the bottom; above that this file does
 * nothing and every rule in bottom-sheet.css is inside the same media query,
 * so desktop is untouched.
 *
 * Two kinds of panel:
 *  - In place ("dialog", "full"): an overlay its page already opens and
 *    closes by class (.tp-modal, .filters-drawer, the assistant). The page's
 *    JS stays as it is; this adds the sheet look, the handle, swipe-down,
 *    focus trap, Escape, scroll lock and focus return while it is open.
 *  - Menu ("menu"): a dropdown list. While open on a phone its node moves
 *    into a sheet built here (title + close + body) and goes back on close.
 *
 * Standard components register themselves (.tp-modal, .filters-drawer).
 * Anything else opts in with markup:
 *   data-tp-sheet="dialog|full|menu"
 *   data-tp-sheet-open="is-open" | "[hidden]" | "[open]"   how "open" is shown
 *                                     (default: menus [hidden], <details> [open],
 *                                      otherwise the is-open class)
 *   data-tp-sheet-panel="selector"   the panel inside the element (default: itself)
 *   data-tp-sheet-close="selector"   clicked to close (default: the trigger, or
 *                                     just flipping the open state back)
 *   data-tp-sheet-trigger="selector" the button that opens it (focus returns there)
 *   data-tp-sheet-title="Text"       menu sheet title
 *   data-tp-sheet-scrim              in-place panel without its own backdrop
 * or from script: TPSheet.register(element, { kind, panel, open, close,
 * trigger, title, scrim }).
 */
(function () {
    "use strict";

    var MQ = window.matchMedia("(max-width: 720px)");
    var REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");
    var FOCUSABLE = "a[href], area[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), "
        + "select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex='-1']), [contenteditable='true']";
    var DRAG_ZONE = 56;      // px from the sheet's top where a drag always works
    var DISMISS_RATIO = 0.25;
    var DISMISS_VELOCITY = 0.5; // px per ms

    var stack = [];
    var entries = [];
    var lastPointerTarget = null;

    function isMobile() {
        return MQ.matches;
    }

    function resolve(value, root) {
        if (!value) return null;
        if (typeof value !== "string") return value;
        return (root && root.querySelector(value)) || document.querySelector(value);
    }

    // ── Scroll lock: overflow hidden on the page (bottom-sheet.css) keeps the
    // scroll position, so nothing jumps and no scroll event fires (pages close
    // their menus on scroll). Touches outside the open sheet can't drag the
    // page either, for browsers that ignore overflow on touch. ──
    function lockScroll() {
        document.documentElement.classList.add("tp-sheet-locked");
    }

    function unlockScroll() {
        document.documentElement.classList.remove("tp-sheet-locked");
    }

    document.addEventListener("touchmove", function (event) {
        var top = stack[stack.length - 1];
        if (top && event.cancelable && !top.panel.contains(event.target)) event.preventDefault();
    }, { passive: false });

    // ── Virtual keyboard: sheets sit on top of it, not behind it. ──
    function syncViewport() {
        var vv = window.visualViewport;
        if (!vv) return;
        var keyboard = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
        var rootStyle = document.documentElement.style;
        rootStyle.setProperty("--tp-sheet-keyboard", Math.round(keyboard) + "px");
        rootStyle.setProperty("--tp-sheet-viewport", Math.round(vv.height) + "px");
    }

    if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", syncViewport);
        window.visualViewport.addEventListener("scroll", syncViewport);
        syncViewport();
    }

    function visibleFocusables(panel) {
        return Array.from(panel.querySelectorAll(FOCUSABLE)).filter(function (el) {
            return el.getClientRects().length > 0 && !el.closest("[hidden], [inert]");
        });
    }

    // ── Swipe down to close. Only from the top strip, or when the content
    // under the finger is already scrolled to its top, so it never fights
    // with scrolling the sheet's own content. ──
    function scrollableAncestor(node, panel) {
        while (node && node !== panel.parentNode) {
            if (node.nodeType === 1 && node.scrollHeight > node.clientHeight + 1) {
                var overflow = window.getComputedStyle(node).overflowY;
                if (overflow === "auto" || overflow === "scroll") return node;
            }
            if (node === panel) break;
            node = node.parentNode;
        }
        return null;
    }

    function bindDrag(session) {
        var panel = session.panel;
        var track = false;
        var decided = false;
        var dragging = false;
        var startX = 0;
        var startY = 0;
        var startTime = 0;
        var offset = 0;

        function onStart(event) {
            track = false;
            if (event.touches.length !== 1) return;
            var target = event.target;
            if (target.closest && target.closest("[data-tp-sheet-nodrag], canvas, input[type='range']")) return;
            var touch = event.touches[0];
            var inTopStrip = touch.clientY - panel.getBoundingClientRect().top < DRAG_ZONE;
            var scroller = scrollableAncestor(target, panel);
            if (!inTopStrip && scroller && scroller.scrollTop > 0) return;
            track = true;
            decided = false;
            dragging = false;
            startX = touch.clientX;
            startY = touch.clientY;
            startTime = Date.now();
            offset = 0;
        }

        function onMove(event) {
            if (!track) return;
            var touch = event.touches[0];
            var dx = touch.clientX - startX;
            var dy = touch.clientY - startY;
            if (!decided) {
                if (Math.abs(dx) < 6 && Math.abs(dy) < 6) {
                    // Keep the browser from starting its own overscroll first.
                    if (dy > 0 && Math.abs(dy) >= Math.abs(dx) && event.cancelable) event.preventDefault();
                    return;
                }
                decided = true;
                if (dy <= 0 || Math.abs(dx) > Math.abs(dy)) {
                    track = false;
                    return;
                }
                dragging = true;
                panel.classList.add("is-sheet-dragging");
            }
            if (!dragging) return;
            if (event.cancelable) event.preventDefault();
            offset = Math.max(0, dy);
            panel.style.transform = "translateY(" + offset + "px)";
        }

        function onEnd() {
            if (!dragging) {
                track = false;
                return;
            }
            dragging = false;
            track = false;
            panel.classList.remove("is-sheet-dragging");
            var velocity = offset / Math.max(1, Date.now() - startTime);
            if (offset > panel.offsetHeight * DISMISS_RATIO || (velocity > DISMISS_VELOCITY && offset > 40)) {
                slideOutThenClose(session);
            } else {
                panel.style.transform = "";
            }
        }

        panel.addEventListener("touchstart", onStart, { passive: true });
        panel.addEventListener("touchmove", onMove, { passive: false });
        panel.addEventListener("touchend", onEnd);
        panel.addEventListener("touchcancel", onEnd);
        return function unbind() {
            panel.removeEventListener("touchstart", onStart);
            panel.removeEventListener("touchmove", onMove);
            panel.removeEventListener("touchend", onEnd);
            panel.removeEventListener("touchcancel", onEnd);
            panel.classList.remove("is-sheet-dragging");
            panel.style.transform = "";
        };
    }

    function slideOutThenClose(session) {
        var panel = session.panel;
        if (REDUCED.matches) {
            panel.style.transform = "";
            session.requestClose();
            return;
        }
        panel.classList.add("is-sheet-leaving");
        panel.style.transform = "translateY(100%)";
        var done = false;
        function finish() {
            if (done) return;
            done = true;
            panel.classList.remove("is-sheet-leaving");
            session.requestClose();
            panel.style.transform = "";
        }
        panel.addEventListener("transitionend", finish, { once: true });
        window.setTimeout(finish, 260);
    }

    // ── Sessions: one per open sheet, stacked (a select sheet can open
    // over a filters sheet). ──
    function activate(panel, options) {
        var active = document.activeElement;
        var returnTo = options.returnFocus
            || (active && active !== document.body && !panel.contains(active) ? active : null)
            || (lastPointerTarget && !panel.contains(lastPointerTarget) ? lastPointerTarget : null);
        if (!stack.length) lockScroll();
        var session = {
            panel: panel,
            requestClose: options.requestClose,
            returnTo: returnTo,
            hadRole: panel.hasAttribute("role"),
            hadModal: panel.getAttribute("aria-modal"),
            hadTabindex: panel.getAttribute("tabindex")
        };
        stack.push(session);
        if (!session.hadRole) panel.setAttribute("role", "dialog");
        panel.setAttribute("aria-modal", "true");
        if (session.hadTabindex === null) panel.setAttribute("tabindex", "-1");
        panel.classList.add("is-sheet-entering");
        panel.addEventListener("animationend", function clear() {
            panel.classList.remove("is-sheet-entering");
        }, { once: true });
        session.unbindDrag = bindDrag(session);
        // The page may already have focused something inside (the
        // assistant's input). Otherwise focus the sheet itself, never a field:
        // that would pop the keyboard up on its own.
        if (!panel.contains(document.activeElement)) panel.focus({ preventScroll: true });
        return session;
    }

    function deactivate(session) {
        var index = stack.indexOf(session);
        if (index === -1) return;
        stack.splice(index, 1);
        var panel = session.panel;
        session.unbindDrag();
        panel.classList.remove("is-sheet-entering", "is-sheet-leaving");
        if (!session.hadRole) panel.removeAttribute("role");
        if (session.hadModal === null) panel.removeAttribute("aria-modal");
        else panel.setAttribute("aria-modal", session.hadModal);
        if (session.hadTabindex === null) panel.removeAttribute("tabindex");
        if (!stack.length) unlockScroll();
        var target = session.returnTo;
        var focusLeftBehind = !document.activeElement || document.activeElement === document.body || panel.contains(document.activeElement);
        if (target && target.isConnected && focusLeftBehind && target.getClientRects().length) {
            target.focus({ preventScroll: true });
        }
    }

    document.addEventListener("pointerdown", function (event) {
        var el = event.target && event.target.closest ? event.target.closest("button, a, summary, [role='button'], [tabindex]") : null;
        if (el) lastPointerTarget = el;
    }, true);

    document.addEventListener("keydown", function (event) {
        var top = stack[stack.length - 1];
        if (!top || !isMobile()) return;
        if (event.key === "Escape") {
            if (event.defaultPrevented) return;
            event.preventDefault();
            top.requestClose();
            return;
        }
        if (event.key !== "Tab") return;
        var items = visibleFocusables(top.panel);
        if (!items.length) {
            event.preventDefault();
            top.panel.focus({ preventScroll: true });
            return;
        }
        var first = items[0];
        var last = items[items.length - 1];
        var current = document.activeElement;
        if (!top.panel.contains(current)) {
            event.preventDefault();
            first.focus();
        } else if (event.shiftKey && (current === first || current === top.panel)) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && current === last) {
            event.preventDefault();
            first.focus();
        }
    });

    // ── Menu sheets: built from the <template> in masterpage.html (title,
    // close button with the site's x icon, translated label). ──
    function buildMenuSheet(title, label) {
        var template = document.getElementById("tp-sheet-template");
        var root = template ? template.content.firstElementChild.cloneNode(true) : null;
        if (!root) return null;
        var titleEl = root.querySelector(".tp-sheet-title");
        var panel = root.querySelector(".tp-sheet");
        if (title) {
            titleEl.textContent = title;
            panel.setAttribute("aria-label", title);
        } else {
            titleEl.hidden = true;
            if (label) panel.setAttribute("aria-label", label);
        }
        document.body.appendChild(root);
        return root;
    }

    // ── Registry ──
    function readOpenMode(root, kind, value) {
        if (value) return value;
        if (root.tagName === "DETAILS") return "[open]";
        return kind === "menu" ? "[hidden]" : "is-open";
    }

    function isOpen(entry) {
        var root = entry.root;
        if (entry.openMode === "[hidden]") return !root.hidden;
        if (entry.openMode === "[open]") return root.hasAttribute("open");
        return root.classList.contains(entry.openMode);
    }

    function requestClose(entry) {
        if (!isOpen(entry)) return;
        var close = entry.close;
        if (typeof close === "function") {
            close();
        } else if (close) {
            var closeEl = resolve(close, entry.root);
            if (closeEl) closeEl.click();
        } else if (entry.trigger && entry.openMode !== "[open]") {
            entry.trigger.click();
        } else if (entry.openMode === "[hidden]") {
            entry.root.hidden = true;
        } else if (entry.openMode === "[open]") {
            entry.root.removeAttribute("open");
        } else {
            entry.root.classList.remove(entry.openMode);
        }
    }

    function openSheet(entry) {
        var close = function () { requestClose(entry); };
        if (entry.kind === "menu") {
            var label = entry.trigger ? (entry.trigger.getAttribute("aria-label") || entry.trigger.textContent || "").trim() : "";
            var sheetRoot = buildMenuSheet(entry.title, label);
            if (!sheetRoot) return;
            var body = sheetRoot.querySelector(".tp-sheet-body");
            entry.placeholder = document.createComment("tp-sheet");
            entry.panel.parentNode.insertBefore(entry.placeholder, entry.panel);
            body.appendChild(entry.panel);
            entry.panel.classList.add("tp-sheet-content");
            entry.sheetRoot = sheetRoot;
            sheetRoot.querySelector(".tp-sheet-backdrop").addEventListener("click", close);
            sheetRoot.querySelector(".tp-sheet-close").addEventListener("click", close);
            entry.session = activate(sheetRoot.querySelector(".tp-sheet"), {
                requestClose: close,
                returnFocus: entry.trigger
            });
            return;
        }
        if (entry.scrim) {
            entry.scrimEl = document.createElement("div");
            entry.scrimEl.className = "tp-sheet-backdrop";
            entry.scrimEl.addEventListener("click", close);
            entry.panel.parentNode.insertBefore(entry.scrimEl, entry.panel);
        }
        entry.panel.classList.add("is-sheet-open");
        entry.session = activate(entry.panel, { requestClose: close, returnFocus: entry.trigger });
    }

    function closeSheet(entry) {
        var session = entry.session;
        entry.session = null;
        if (entry.kind === "menu") {
            if (entry.placeholder && entry.placeholder.parentNode) {
                entry.placeholder.parentNode.insertBefore(entry.panel, entry.placeholder);
                entry.placeholder.remove();
            }
            entry.panel.classList.remove("tp-sheet-content");
            if (session) deactivate(session);
            if (entry.sheetRoot) entry.sheetRoot.remove();
            entry.sheetRoot = null;
            return;
        }
        entry.panel.classList.remove("is-sheet-open");
        if (entry.scrimEl) {
            entry.scrimEl.remove();
            entry.scrimEl = null;
        }
        if (session) deactivate(session);
    }

    function sync(entry) {
        var shouldBeOpen = isMobile() && isOpen(entry);
        if (shouldBeOpen && !entry.session) openSheet(entry);
        else if (!shouldBeOpen && entry.session) closeSheet(entry);
    }

    function register(root, options) {
        if (!root || root.__tpSheet) return root && root.__tpSheet;
        options = options || {};
        var kind = options.kind || "dialog";
        var panel = resolve(options.panel, root) || root;
        if (options.panel && !root.contains(panel)) panel = root;
        var entry = {
            root: root,
            kind: kind,
            panel: panel,
            openMode: readOpenMode(root, kind, options.open),
            close: options.close || null,
            trigger: resolve(options.trigger, null) || (root.tagName === "DETAILS" ? root.querySelector("summary") : null),
            title: options.title || "",
            scrim: Boolean(options.scrim),
            session: null
        };
        root.__tpSheet = entry;
        if (kind !== "menu") {
            panel.classList.add("tp-sheet");
            if (kind === "full") panel.classList.add("tp-sheet--full");
        }
        new MutationObserver(function () { sync(entry); }).observe(root, {
            attributes: true,
            attributeFilter: ["class", "hidden", "open"]
        });
        entries.push(entry);
        sync(entry);
        return entry;
    }

    function registerFromMarkup(el) {
        register(el, {
            kind: el.getAttribute("data-tp-sheet") || "dialog",
            open: el.getAttribute("data-tp-sheet-open"),
            panel: el.getAttribute("data-tp-sheet-panel"),
            close: el.getAttribute("data-tp-sheet-close"),
            trigger: el.getAttribute("data-tp-sheet-trigger"),
            title: el.getAttribute("data-tp-sheet-title"),
            scrim: el.hasAttribute("data-tp-sheet-scrim")
        });
    }

    function scan(scope) {
        scope = scope || document;
        scope.querySelectorAll(".tp-modal").forEach(function (modal) {
            register(modal, { kind: "dialog", panel: ".tp-modal-panel", open: "is-open", close: ".tp-modal-close" });
        });
        scope.querySelectorAll(".filters-drawer").forEach(function (drawer) {
            register(drawer, { kind: "full", open: "open", close: ".drawer-close-btn" });
        });
        scope.querySelectorAll("[data-tp-sheet]").forEach(registerFromMarkup);
    }

    MQ.addEventListener("change", function () {
        entries.forEach(sync);
    });

    window.TPSheet = {
        isMobile: isMobile,
        register: register,
        scan: scan
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { scan(document); });
    } else {
        scan(document);
    }
}());
