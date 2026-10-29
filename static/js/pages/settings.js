/* Settings works without full page reloads: section and page links fetch
 * the page and swap the index + panel, the search box filters as you
 * type, and visibility/delete/unrestrict forms post with fetch and answer
 * in place. Any fetch failure falls back to a normal navigation. */
(function () {
    const page = document.querySelector(".settings-page");
    if (!page) return;

    const HEADERS = { "X-Requested-With": "XMLHttpRequest" };
    const SAVED_LABEL = page.dataset.savedLabel || "Saved";
    const ERROR_LABEL = page.dataset.errorLabel || "Something went wrong.";
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let controller = null;
    let searchTimer = null;

    // page-chrome-init.js turns [title] into the site tooltip only at load.
    function adoptTooltips(root) {
        root.querySelectorAll("[title]").forEach(function (el) {
            el.setAttribute("data-tp-native-title", el.getAttribute("title"));
            el.removeAttribute("title");
        });
        document.querySelectorAll(".tp-global-tooltip.is-visible").forEach(function (tip) {
            tip.classList.remove("is-visible");
        });
    }

    function swap(selector, doc) {
        const current = page.querySelector(selector);
        const next = doc.querySelector(selector);
        if (!current || !next) return;
        current.replaceWith(next);
        adoptTooltips(next);
    }

    function load(url, options) {
        options = options || {};
        if (controller) controller.abort();
        controller = new AbortController();
        const results = page.querySelector("[data-settings-results]");
        if (results) results.classList.add("is-loading");
        return fetch(url, { headers: HEADERS, credentials: "same-origin", signal: controller.signal })
            .then(function (response) {
                if (!response.ok) throw new Error("HTTP " + response.status);
                return response.text();
            })
            .then(function (html) {
                const doc = new DOMParser().parseFromString(html, "text/html");
                swap(".settings-nav", doc);
                swap(options.resultsOnly ? "[data-settings-results]" : ".settings-panel", doc);
                if (options.history === "push") window.history.pushState({ settings: true }, "", url);
                if (options.history === "replace") window.history.replaceState({ settings: true }, "", url);
                const panel = page.querySelector(".settings-panel");
                if (options.scroll && panel && panel.getBoundingClientRect().top < 0) {
                    panel.scrollIntoView({ block: "start", behavior: reduceMotion ? "auto" : "smooth" });
                }
            })
            .catch(function (error) {
                if (error.name !== "AbortError") window.location.assign(url);
            });
    }

    function post(form) {
        return fetch(form.action, {
            method: "POST",
            body: new FormData(form),
            headers: HEADERS,
            credentials: "same-origin"
        }).then(function (response) {
            return response.json().catch(function () {
                return { ok: false, message: ERROR_LABEL };
            });
        }, function () {
            return { ok: false, message: ERROR_LABEL };
        });
    }

    function showError(text) {
        let box = document.getElementById("tp-messages");
        if (!box) {
            box = document.createElement("div");
            box.className = "tp-messages";
            box.id = "tp-messages";
            page.parentNode.insertBefore(box, page);
        }
        const message = document.createElement("div");
        message.className = "tp-message tp-message--error";
        message.setAttribute("role", "alert");
        const label = document.createElement("span");
        label.textContent = text || ERROR_LABEL;
        const close = document.createElement("button");
        close.type = "button";
        close.className = "tp-message-close";
        close.setAttribute("aria-label", "Close");
        close.textContent = "×";
        message.append(label, close);
        box.appendChild(message);
        const dismiss = function () {
            message.classList.add("is-hiding");
            window.setTimeout(function () { message.remove(); }, 300);
        };
        close.addEventListener("click", dismiss);
        window.setTimeout(dismiss, 6000);
        box.scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
    }

    function searchUrl(form) {
        const params = new URLSearchParams(new FormData(form));
        if (!params.get("q")) params.delete("q");
        return "?" + params.toString();
    }

    // ── Navigation: index, pages, researcher links, clear search ──
    page.addEventListener("click", function (event) {
        const link = event.target.closest("a[data-settings-link]");
        if (!link || event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        load(link.href, { history: "push", scroll: !!link.closest(".settings-footer") });
    });

    window.addEventListener("popstate", function () {
        load(window.location.href);
    });

    // ── Search as you type ──
    page.addEventListener("input", function (event) {
        const form = event.target.closest(".settings-search");
        if (!form) return;
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(function () {
            load(searchUrl(form), { resultsOnly: true, history: "replace" });
        }, 250);
    });

    page.addEventListener("submit", function (event) {
        const form = event.target;
        if (form.matches(".settings-search")) {
            event.preventDefault();
            window.clearTimeout(searchTimer);
            load(searchUrl(form), { resultsOnly: true, history: "replace" });
            return;
        }
        if ((form.method || "").toLowerCase() !== "post") return;
        event.preventDefault();
        if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) return;
        const button = form.querySelector("button[type='submit']");
        if (button) button.disabled = true;
        post(form).then(function (result) {
            if (!result.ok) {
                if (button) button.disabled = false;
                showError(result.message);
                return;
            }
            const row = form.closest("tr");
            if (row) row.classList.add("is-leaving");
            window.setTimeout(function () {
                load(window.location.href, { resultsOnly: true });
            }, reduceMotion ? 0 : 180);
        });
    });

    // ── Visibility: saved as soon as it changes ──
    page.addEventListener("change", function (event) {
        const select = event.target;
        const form = select.closest(".settings-visibility-form");
        if (!form || select.name !== "visibility") return;
        const state = form.querySelector(".settings-save-state");
        form.classList.remove("is-saved");
        form.classList.add("is-saving");
        post(form).then(function (result) {
            form.classList.remove("is-saving");
            const options = Array.from(select.options);
            if (!result.ok) {
                const saved = options.find(function (option) { return option.defaultSelected; });
                if (saved) select.value = saved.value;
                // "input" redraws the custom dropdown without re-saving.
                select.dispatchEvent(new Event("input"));
                showError(result.message);
                return;
            }
            options.forEach(function (option) { option.defaultSelected = option.value === select.value; });
            if (state) state.textContent = SAVED_LABEL;
            form.classList.add("is-saved");
            window.clearTimeout(form._savedTimer);
            form._savedTimer = window.setTimeout(function () {
                form.classList.remove("is-saved");
                if (state) state.textContent = "";
            }, 1800);
        });
    });
})();
