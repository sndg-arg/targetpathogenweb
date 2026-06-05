(function () {
    "use strict";

    var residueModalInitialized = false;
    var quickNavInitialized = false;
    var pointerBlurInitialized = false;
    var detailsToggleBound = false;

    function parseScore(value) {
        var parsed = Number.parseFloat(String(value || "").replace(",", "."));
        return Number.isFinite(parsed) ? parsed : Number.NaN;
    }

    function classifyScore(score, scoreType) {
        if (Number.isNaN(score)) return "medium";
        if (scoreType === "p2rank-prob") {
            if (score >= 0.5) return "high";
            if (score >= 0.2) return "medium";
            return "low";
        }
        if (score >= 0.7) return "high";
        if (score >= 0.4) return "medium";
        return "low";
    }

    function parseResidues(rawResidues) {
        return String(rawResidues || "")
            .split(/[\s,;]+/)
            .map(function (token) { return token.trim(); })
            .filter(Boolean);
    }

    function fallbackCopyText(text) {
        return new Promise(function (resolve, reject) {
            var fallback = document.createElement("textarea");
            fallback.value = text;
            fallback.setAttribute("readonly", "readonly");
            fallback.style.position = "fixed";
            fallback.style.left = "-10000px";
            document.body.appendChild(fallback);
            fallback.select();
            try {
                var copied = document.execCommand("copy");
                document.body.removeChild(fallback);
                if (copied) {
                    resolve(true);
                } else {
                    reject(new Error("copy failed"));
                }
            } catch (error) {
                document.body.removeChild(fallback);
                reject(error);
            }
        });
    }

    function copyText(text) {
        if (!text) return Promise.resolve(false);
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            return navigator.clipboard.writeText(text)
                .then(function () { return true; })
                .catch(function () { return fallbackCopyText(text); });
        }
        return fallbackCopyText(text);
    }

    function setTemporaryLabel(button, temporaryLabel, durationMs) {
        if (!button) return;
        var defaultLabel = button.getAttribute("data-default-label") || button.textContent || "";
        button.textContent = temporaryLabel;
        window.setTimeout(function () {
            button.textContent = defaultLabel;
        }, durationMs || 1200);
    }

    function initCopyButton(button, getText) {
        if (!button || typeof getText !== "function") return;
        if (button.getAttribute("data-copy-bound") === "1") return;
        button.setAttribute("data-copy-bound", "1");

        var defaultLabel = button.getAttribute("data-default-label") || button.textContent || "Copy";
        var copiedLabel = button.getAttribute("data-copied-label") || "Copied";
        button.textContent = defaultLabel;

        button.addEventListener("click", function () {
            var text = String(getText() || "").trim();
            if (!text) return;
            copyText(text)
                .then(function (copied) {
                    if (!copied) return;
                    setTemporaryLabel(button, copiedLabel, 1300);
                })
                .catch(function () {
                    // Keep UI stable if copy is blocked by browser policy.
                });
        });
    }

    function initResidueModal() {
        if (residueModalInitialized) return;

        var modal = document.getElementById("residue-modal");
        var panel = modal ? modal.querySelector(".residue-modal-panel") : null;
        var content = document.getElementById("residue-modal-content");
        var closeBtn = document.getElementById("close-residue-modal");
        var copyBtn = document.getElementById("copy-residue-list");
        if (!modal || !panel || !content) return;

        residueModalInitialized = true;
        var lastFocusedTrigger = null;
        var defaultCopyLabel = copyBtn ? (copyBtn.getAttribute("data-default-label") || copyBtn.textContent || "Copy") : "Copy";
        var copiedCopyLabel = copyBtn ? (copyBtn.getAttribute("data-copied-label") || "Copied") : "Copied";

        function openModalFromTrigger(trigger) {
            lastFocusedTrigger = trigger || null;
            var residues = parseResidues(trigger ? trigger.getAttribute("data-residues") : "");
            content.textContent = residues.length ? residues.join(", ") : "-";
            if (copyBtn) copyBtn.textContent = defaultCopyLabel;
            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
            document.body.classList.add("residue-modal-open");
            if (closeBtn) closeBtn.focus();
        }

        function closeModal() {
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("residue-modal-open");
            if (copyBtn) copyBtn.textContent = defaultCopyLabel;
            if (lastFocusedTrigger && typeof lastFocusedTrigger.focus === "function") {
                lastFocusedTrigger.focus();
            }
        }

        document.addEventListener("click", function (event) {
            var trigger = event.target.closest(".js-show-residues");
            if (!trigger) return;
            event.preventDefault();
            openModalFromTrigger(trigger);
        });

        if (closeBtn) {
            closeBtn.addEventListener("click", function () {
                closeModal();
            });
        }

        modal.addEventListener("click", function (event) {
            if (!panel.contains(event.target)) {
                closeModal();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && modal.classList.contains("is-open")) {
                closeModal();
            }
        });

        if (copyBtn) {
            copyBtn.addEventListener("click", function () {
                var text = (content.textContent || "").trim();
                copyText(text).then(function () {
                    copyBtn.textContent = copiedCopyLabel;
                    window.setTimeout(function () {
                        copyBtn.textContent = defaultCopyLabel;
                    }, 1200);
                });
            });
        }
    }

    function decorateScoreTags(selector) {
        var targetSelector = selector || ".js-score-tag";
        document.querySelectorAll(targetSelector).forEach(function (tag) {
            var score = parseScore(tag.getAttribute("data-score") || tag.textContent);
            var scoreType = tag.getAttribute("data-score-type") || "";
            var statusClass = classifyScore(score, scoreType);
            tag.classList.remove("high", "medium", "low");
            tag.classList.add(statusClass);
        });
    }

    function initQuickNav(selector) {
        if (quickNavInitialized) return;
        var nav = document.querySelector(selector || ".quick-nav");
        if (!nav) return;
        quickNavInitialized = true;

        var links = Array.from(nav.querySelectorAll("a[href^='#']"));
        if (!links.length) return;

        var targets = links
            .map(function (link) {
                var id = (link.getAttribute("href") || "").slice(1);
                if (!id) return null;
                var section = document.getElementById(id);
                return section ? { link: link, section: section } : null;
            })
            .filter(Boolean);

        if (!targets.length) return;

        function setActive(sectionId) {
            targets.forEach(function (entry) {
                var isActive = entry.section.id === sectionId;
                entry.link.classList.toggle("is-active", isActive);
                entry.link.setAttribute("aria-current", isActive ? "true" : "false");
            });
        }

        function updateActive() {
            var triggerLine = Math.round(window.innerHeight * 0.32);
            var active = targets[0];
            for (var i = targets.length - 1; i >= 0; i--) {
                if (targets[i].section.getBoundingClientRect().top <= triggerLine) {
                    active = targets[i];
                    break;
                }
            }
            setActive(active.section.id);
        }

        window.addEventListener("scroll", updateActive, { passive: true });
        updateActive();
    }

    function initPointerButtonBlur(scopeSelector) {
        if (pointerBlurInitialized) return;
        var scope = document.querySelector(scopeSelector || "body");
        if (!scope) return;
        pointerBlurInitialized = true;
        scope.addEventListener("pointerup", function (event) {
            var button = event.target.closest("button");
            if (button && typeof button.blur === "function") {
                button.blur();
            }
        });
    }

    function placeFeatureResetButton(featureContainer, resetButton) {
        if (!featureContainer || !resetButton) return;
        resetButton.classList.add("is-inline");

        function findZoomHost() {
            var candidates = Array.from(featureContainer.querySelectorAll("div, p, span, strong"));
            for (var i = 0; i < candidates.length; i += 1) {
                var node = candidates[i];
                var text = (node.textContent || "").replace(/\s+/g, " ").trim();
                if (!/zoom\s*:\s*x/i.test(text)) continue;
                return node.tagName === "STRONG" && node.parentElement ? node.parentElement : node;
            }
            return null;
        }

        function placeNearZoom() {
            var zoomHost = findZoomHost();
            if (!zoomHost) return false;
            var slot = zoomHost.querySelector(".features-zoom-reset-slot");
            if (!slot) {
                slot = document.createElement("span");
                slot.className = "features-zoom-reset-slot";
                zoomHost.appendChild(slot);
            }
            if (resetButton.parentElement !== slot) {
                slot.appendChild(resetButton);
            }
            return true;
        }

        if (!placeNearZoom()) {
            var toolbarHost = document.querySelector(".features-tools-inline");
            if (toolbarHost && resetButton.parentElement !== toolbarHost) {
                toolbarHost.appendChild(resetButton);
            }
        }

        if ("MutationObserver" in window && !featureContainer.__tpFeatureResetObserver) {
            var observer = new MutationObserver(function () {
                placeNearZoom();
            });
            observer.observe(featureContainer, {
                childList: true,
                subtree: true,
                characterData: true
            });
            featureContainer.__tpFeatureResetObserver = observer;
        }
    }

    function adjustDataTablesOnDetailsToggle() {
        if (detailsToggleBound) return;
        detailsToggleBound = true;
        document.querySelectorAll("details").forEach(function (detailsEl) {
            detailsEl.addEventListener("toggle", function () {
                if (!detailsEl.open || !window.jQuery || !$.fn.dataTable) return;
                window.setTimeout(function () {
                    $.fn.dataTable.tables({ visible: true, api: true }).columns.adjust();
                }, 40);
            });
        });
    }

    window.tpProteinDetail = {
        initCopyButton: initCopyButton,
        decorateScoreTags: decorateScoreTags,
        initResidueModal: initResidueModal,
        initQuickNav: initQuickNav,
        initPointerButtonBlur: initPointerButtonBlur,
        placeFeatureResetButton: placeFeatureResetButton,
        adjustDataTablesOnDetailsToggle: adjustDataTablesOnDetailsToggle
    };
})();
