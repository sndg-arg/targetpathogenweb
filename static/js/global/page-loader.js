/* Page-transition loading overlay + shared DataTables defaults -- present on
 * every page (loaded directly from masterpage.html, matching the existing
 * plain-script convention used by agent-drawer.js/nav-toggle.js).
 *
 * Reads translated copy from window.TPW_I18N (set by a small inline <script>
 * in masterpage.html, right before this file loads) instead of embedding
 * {% trans %} calls directly -- this file is a plain static asset, not a
 * Django template.
 */
(function () {
    const LOADING_CLASS = "tp-page-is-loading";
    const NAVIGATING_CLASS = "tp-page-is-navigating";
    const ACTION_LOADING_CLASS = "tp-page-action-loading";
    const EXCLUDED_LINK_SELECTOR = [
        "[data-tp-loader='off']",
        "[data-no-page-loader]",
        "[download]",
        "[target='_blank']",
        "[data-toggle]",
        "[data-bs-toggle]",
        ".dropdown-toggle",
        ".tp-agent-drawer-suggestion"
    ].join(",");
    const EXCLUDED_FORM_SELECTOR = [
        "[data-tp-loader='off']",
        "[data-no-page-loader]",
        "#tp-agent-drawer-form"
    ].join(",");
    let showTimer = null;
    let activeAction = null;
    const LOADER_DEFAULT_COPY = window.TPW_I18N.pageLoader.defaultCopy;
    const LOADER_OPENING_PREFIX = window.TPW_I18N.pageLoader.openingPrefix;
    const LOADER_LABEL_MAX_LENGTH = 42;

    // Genome overview and protein detail are the two heaviest pages to
    // render (see the assembly_workspace/pdb_structure query cost) --
    // a single static "Opening X…" label sits there doing nothing for a
    // couple seconds. This doesn't measure real progress, it's a staged
    // sequence of plausible-sounding steps that just keeps advancing on a
    // timer, purely to make the wait read as "something is happening"
    // instead of a frozen label. Matches exactly `/genome/<slug>` and
    // `/protein/<id>` -- NOT their sub-pages (proteins list, metabolism,
    // structure viewer, etc.), which already get the normal per-link label.
    const GENOME_OVERVIEW_PATH_RE = /^\/genome\/[^/]+\/?$/;
    const PROTEIN_DETAIL_PATH_RE = /^\/protein\/\d+\/?$/;
    const GENOME_OVERVIEW_SEQUENCE = window.TPW_I18N.pageLoader.genomeOverviewSequence;
    const PROTEIN_DETAIL_SEQUENCE = window.TPW_I18N.pageLoader.proteinDetailSequence;
    const LOADER_SEQUENCE_STEP_MS = 550;
    let sequenceTimer = null;

    function loaderSequenceForUrl(url) {
        let pathname = null;
        try {
            pathname = (typeof url === "string" ? new URL(url, window.location.href) : url).pathname;
        } catch (error) {
            return null;
        }
        if (!pathname) return null;
        if (GENOME_OVERVIEW_PATH_RE.test(pathname)) return GENOME_OVERVIEW_SEQUENCE;
        if (PROTEIN_DETAIL_PATH_RE.test(pathname)) return PROTEIN_DETAIL_SEQUENCE;
        return null;
    }

    function loaderEl() {
        return document.getElementById("tp-page-loader");
    }

    function loaderCopyEl() {
        return document.getElementById("tp-page-loader-copy");
    }

    function setLoaderCopy(label) {
        const copyEl = loaderCopyEl();
        if (!copyEl) return;
        if (!label) {
            copyEl.textContent = LOADER_DEFAULT_COPY;
            return;
        }
        const trimmed = label.length > LOADER_LABEL_MAX_LENGTH
            ? label.slice(0, LOADER_LABEL_MAX_LENGTH - 1).trimEnd() + "…"
            : label;
        copyEl.textContent = LOADER_OPENING_PREFIX + " " + trimmed + "…";
    }

    function stopLoaderSequence() {
        window.clearInterval(sequenceTimer);
        sequenceTimer = null;
    }

    function startLoaderSequence(messages) {
        stopLoaderSequence();
        const copyEl = loaderCopyEl();
        if (!copyEl || !messages || !messages.length) return;
        let index = 0;
        copyEl.textContent = messages[0];
        sequenceTimer = window.setInterval(function () {
            index += 1;
            if (index >= messages.length) {
                // Stay on the last ("Opening…") message instead of
                // looping -- if the real navigation is still pending past
                // the full sequence, restarting from "Resolving…" would
                // read as if it had gone backwards/gotten stuck.
                stopLoaderSequence();
                return;
            }
            copyEl.textContent = messages[index];
        }, LOADER_SEQUENCE_STEP_MS);
    }

    function deriveLoaderLabel(el) {
        if (!el) return null;
        const raw = (el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent || "")
            .replace(/\s+/g, " ")
            .trim();
        if (!raw) return null;
        // A bare textContent fallback on a link/button with several
        // nested elements (a data row, a card) reads as several labels
        // jammed together with no separators -- past a plausible
        // single-control label length, prefer the generic default copy
        // over a garbled truncation.
        if (raw.length > 90) return null;
        return raw;
    }

    function setLoaderVisible(visible) {
        const loader = loaderEl();
        if (loader) {
            loader.setAttribute("aria-hidden", visible ? "false" : "true");
        }
        if (document.body) {
            if (visible) {
                document.body.setAttribute("aria-busy", "true");
            } else {
                document.body.removeAttribute("aria-busy");
            }
        }
    }

    function clearAction() {
        if (!activeAction) return;
        activeAction.classList.remove(ACTION_LOADING_CLASS);
        activeAction.removeAttribute("aria-busy");
        activeAction = null;
    }

    function show(options) {
        const opts = options || {};
        if (opts.sequence) {
            startLoaderSequence(opts.sequence);
        } else {
            stopLoaderSequence();
            setLoaderCopy(opts.label || null);
        }
        window.clearTimeout(showTimer);
        showTimer = window.setTimeout(function () {
            document.documentElement.classList.add(NAVIGATING_CLASS);
            setLoaderVisible(true);
        }, Number.isFinite(opts.delay) ? opts.delay : 90);
    }

    function hide() {
        window.clearTimeout(showTimer);
        stopLoaderSequence();
        document.documentElement.classList.remove(LOADING_CLASS, NAVIGATING_CLASS);
        setLoaderVisible(false);
        clearAction();
        setLoaderCopy(null);
    }

    function markAction(el) {
        clearAction();
        if (!el || !el.classList) return;
        activeAction = el;
        activeAction.classList.add(ACTION_LOADING_CLASS);
        activeAction.setAttribute("aria-busy", "true");
    }

    function isModifiedClick(event) {
        return event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
    }

    function shouldSkipUrl(url) {
        if (!url) return true;
        if (url.protocol && !["http:", "https:"].includes(url.protocol)) return true;
        if (url.origin !== window.location.origin) return true;
        if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return true;
        if (url.pathname === window.location.pathname && url.search === window.location.search && !url.hash) return true;
        return /\/download\/?|\/export\/?|csv|xlsx|fasta|\.fna|\.faa|\.gbk?|\.zip|\.pdb$/i.test(url.pathname);
    }

    function shouldSkipFormUrl(url) {
        if (!url) return true;
        if (url.protocol && !["http:", "https:"].includes(url.protocol)) return true;
        if (url.origin !== window.location.origin) return true;
        return /\/download\/?|\/export\/?|csv|xlsx|fasta|\.fna|\.faa|\.gbk?|\.zip|\.pdb$/i.test(url.pathname);
    }

    function linkUrl(link) {
        try {
            return new URL(link.getAttribute("href"), window.location.href);
        } catch (error) {
            return null;
        }
    }

    function formUrl(form) {
        try {
            return new URL(form.getAttribute("action") || window.location.href, window.location.href);
        } catch (error) {
            return null;
        }
    }

    function initNavigationLoading() {
        window.setTimeout(hide, 180);

        document.addEventListener("click", function (event) {
            if (isModifiedClick(event)) return;
            const link = event.target.closest ? event.target.closest("a[href]") : null;
            if (!link || link.matches(EXCLUDED_LINK_SELECTOR)) return;
            const url = linkUrl(link);
            if (shouldSkipUrl(url)) return;
            markAction(link);
            const sequence = loaderSequenceForUrl(url);
            show(sequence ? { sequence: sequence } : { label: deriveLoaderLabel(link) });
        });

        document.addEventListener("submit", function (event) {
            window.setTimeout(function () {
                if (event.defaultPrevented) return;
                const form = event.target;
                if (!form || !form.matches || form.matches(EXCLUDED_FORM_SELECTOR)) return;
                const target = (form.getAttribute("target") || "").toLowerCase();
                if (target && target !== "_self") return;
                if (shouldSkipFormUrl(formUrl(form))) return;
                const submitter = event.submitter || form.querySelector("button[type='submit'], input[type='submit'], .tp-btn");
                markAction(submitter);
                show({ label: deriveLoaderLabel(submitter) });
            }, 0);
        });

        window.addEventListener("pageshow", hide);
        window.addEventListener("load", hide);
        window.addEventListener("pagehide", function () {
            setLoaderVisible(true);
        });
    }

    window.TPPageLoader = {
        show: show,
        hide: hide,
        markAction: markAction,
        // For programmatic navigations (e.g. the protein search
        // autocomplete's window.location.assign) that don't go through
        // the click handler above and so never get the automatic
        // sequence detection -- pass the destination URL and get the
        // same staged messages a normal link click to that page would.
        showForUrl: function (url, fallbackOptions) {
            const sequence = loaderSequenceForUrl(url);
            show(sequence ? { sequence: sequence } : (fallbackOptions || {}));
        },
        withLoading: function (promiseOrFactory, options) {
            show(options);
            let result;
            try {
                result = typeof promiseOrFactory === "function" ? promiseOrFactory() : promiseOrFactory;
            } catch (error) {
                hide();
                throw error;
            }
            return Promise.resolve(result).finally(hide);
        }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initNavigationLoading, { once: true });
    } else {
        initNavigationLoading();
    }
})();

if (window.jQuery && $.fn && $.fn.dataTable) {
    const TP_DT_VARIANTS = Object.freeze({
        full: Object.freeze({
            pagingType: "full_numbers",
            dom: "<'tp-dt-toolbar'<'tp-dt-length'l><'tp-dt-search'f>>rt<'tp-dt-footer'<'tp-dt-info'i><'tp-dt-pager'p>>"
        }),
        compact: Object.freeze({
            pagingType: "simple_numbers",
            dom: "<'tp-dt-toolbar'<'tp-dt-search'f>>rt<'tp-dt-footer'<'tp-dt-info'i><'tp-dt-pager'p>>"
        })
    });

    const TP_DT_LANGUAGE = Object.assign({}, window.TPW_I18N.dataTable, {
        paginate: {
            first: "«",
            last: "»",
            next: "›",
            previous: "‹"
        }
    });

    $.extend(true, $.fn.dataTable.defaults, {
        pagingType: TP_DT_VARIANTS.full.pagingType,
        dom: TP_DT_VARIANTS.full.dom,
        language: TP_DT_LANGUAGE
    });

    window.tpInitDataTable = function (selector, options) {
        if (!selector || !document.querySelector(selector)) return null;
        if (!window.jQuery || !$.fn || !$.fn.dataTable) return null;

        const config = $.extend(true, {}, options || {});
        const variantName = config.tpVariant === "compact" ? "compact" : "full";
        delete config.tpVariant;

        function applyWrapperClasses(tableApi) {
            const wrapper = $(tableApi.table().container());
            wrapper.addClass("tp-dt-wrapper");
            wrapper.addClass("tp-dt-variant-" + variantName);
            if (config.searching === false) wrapper.addClass("tp-dt-no-search");
            if (config.lengthChange === false) wrapper.addClass("tp-dt-no-length");
            if (config.paging === false) wrapper.addClass("tp-dt-no-paging");
        }

        if (!Object.prototype.hasOwnProperty.call(config, "pagingType")) {
            config.pagingType = TP_DT_VARIANTS[variantName].pagingType;
        }
        if (!Object.prototype.hasOwnProperty.call(config, "dom")) {
            config.dom = TP_DT_VARIANTS[variantName].dom;
        }
        if (!Object.prototype.hasOwnProperty.call(config, "language")) {
            config.language = {};
        }
        config.language = $.extend(true, {}, TP_DT_LANGUAGE, config.language);

        if ($.fn.dataTable.isDataTable(selector)) {
            const existingTable = $(selector).DataTable();
            applyWrapperClasses(existingTable);
            return existingTable;
        }

        const table = $(selector).DataTable(config);
        applyWrapperClasses(table);

        const wrapper = $(table.table().container());
        wrapper.find(".dataTables_filter label").each(function () {
            const $label = $(this);
            const $input = $label.find("input[type=search]");
            if ($input.length && !$label.find(".tp-dt-search-icon").length) {
                $input.wrap('<span class="tp-dt-search-wrap"></span>');
                $label.find(".tp-dt-search-wrap").prepend(
                    '<svg class="tp-dt-search-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">' +
                    '<circle cx="6" cy="6" r="4" stroke="currentColor" stroke-width="1.4"/>' +
                    '<path d="M9.5 9.5l2.5 2.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>' +
                    '</svg>'
                );
            }
        });

        return table;
    };
}
