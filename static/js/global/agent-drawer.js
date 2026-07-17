/* Global assistant drawer -- present on every page (loaded directly from
 * masterpage.html, not part of the webpack bundle, matching the existing
 * plain-script convention used by protein-detail.js/metabolic-network.js).
 *
 * Conversation history is kept in memory only (a plain JS array) and
 * round-tripped to the server on every message -- it is intentionally not
 * persisted across page reloads (see AgentChatView.py's module docstring).
 */
(function () {
    "use strict";

    function getCookie(name) {
        var cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            var cookies = document.cookie.split(";");
            for (var i = 0; i < cookies.length; i++) {
                var cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === name + "=") {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function escapeHtml(text) {
        return String(text || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function inlineMarkdown(text) {
        return escapeHtml(text)
            .replace(/\\_/g, "_")
            .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
            .replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    }

    function splitTableRow(line) {
        var trimmed = line.trim();
        if (trimmed.charAt(0) === "|") trimmed = trimmed.slice(1);
        if (trimmed.charAt(trimmed.length - 1) === "|") trimmed = trimmed.slice(0, -1);
        return trimmed.split("|").map(function (cell) { return cell.trim(); });
    }

    function isTableSeparatorRow(line) {
        var cells = splitTableRow(line);
        return cells.length > 0 && cells.every(function (cell) { return /^:?-+:?$/.test(cell); });
    }

    // Line-index loop (not forEach) because fenced code blocks and tables both need to
    // look ahead/consume several lines at once -- the tool layer (e.g. compare_targets in
    // target_evidence.py) emits real pipe-table markdown, which used to render as raw
    // "Accession | Score | ..." text with no table structure at all.
    function renderMarkdown(text) {
        var lines = String(text || "").split(/\r?\n/);
        var html = [];
        var listTag = null;
        var i = 0;

        function closeList() {
            if (listTag) {
                html.push("</" + listTag + ">");
                listTag = null;
            }
        }

        function openList(tag) {
            if (listTag === tag) {
                return;
            }
            closeList();
            html.push("<" + tag + ">");
            listTag = tag;
        }

        while (i < lines.length) {
            var line = lines[i];
            var trimmed = line.trim();

            if (!trimmed) {
                closeList();
                i++;
                continue;
            }

            if (trimmed.slice(0, 3) === "```") {
                closeList();
                var codeLines = [];
                i++;
                while (i < lines.length && lines[i].trim().slice(0, 3) !== "```") {
                    codeLines.push(lines[i]);
                    i++;
                }
                i++;
                html.push("<pre><code>" + escapeHtml(codeLines.join("\n")) + "</code></pre>");
                continue;
            }

            if (trimmed.indexOf("|") !== -1 && i + 1 < lines.length && isTableSeparatorRow(lines[i + 1])) {
                closeList();
                var headerCells = splitTableRow(line);
                i += 2;
                var bodyRows = [];
                while (i < lines.length && lines[i].trim() && lines[i].trim().indexOf("|") !== -1) {
                    bodyRows.push(splitTableRow(lines[i]));
                    i++;
                }
                var tableHtml = ["<table><thead><tr>"];
                headerCells.forEach(function (cell) {
                    tableHtml.push("<th>" + inlineMarkdown(cell) + "</th>");
                });
                tableHtml.push("</tr></thead><tbody>");
                bodyRows.forEach(function (row) {
                    tableHtml.push("<tr>");
                    row.forEach(function (cell) {
                        tableHtml.push("<td>" + inlineMarkdown(cell) + "</td>");
                    });
                    tableHtml.push("</tr>");
                });
                tableHtml.push("</tbody></table>");
                html.push('<div class="tp-agent-drawer-table-wrap">' + tableHtml.join("") + "</div>");
                continue;
            }

            var heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
            if (heading) {
                closeList();
                var level = Math.min(heading[1].length + 2, 5);
                html.push("<h" + level + ">" + inlineMarkdown(heading[2]) + "</h" + level + ">");
                i++;
                continue;
            }

            var bullet = trimmed.match(/^[-*]\s+(.+)$/);
            var numbered = trimmed.match(/^\d+[.)]\s+(.+)$/);
            if (bullet || numbered) {
                openList(numbered ? "ol" : "ul");
                html.push("<li>" + inlineMarkdown((bullet || numbered)[1]) + "</li>");
                i++;
                continue;
            }

            closeList();
            html.push("<p>" + inlineMarkdown(trimmed) + "</p>");
            i++;
        }
        closeList();
        return html.join("");
    }

    function compactText(value, limit) {
        var text = String(value || "").replace(/\s+/g, " ").trim();
        var max = limit || 160;
        if (text.length <= max) {
            return text;
        }
        return text.slice(0, max - 1).trim() + "…";
    }

    function textFrom(selector, limit) {
        var el = document.querySelector(selector);
        return el ? compactText(el.textContent, limit) : "";
    }

    function textsFrom(selector, limit, itemLimit) {
        return Array.prototype.slice.call(document.querySelectorAll(selector), 0, itemLimit || 8)
            .map(function (el) { return compactText(el.textContent, limit || 120); })
            .filter(Boolean);
    }

    function textsFromRoot(root, selector, limit, itemLimit) {
        if (!root) {
            return [];
        }
        return Array.prototype.slice.call(root.querySelectorAll(selector), 0, itemLimit || 8)
            .map(function (el) { return compactText(el.textContent, limit || 120); })
            .filter(Boolean);
    }

    function activeTextFrom(selector, limit, itemLimit) {
        return Array.prototype.slice.call(document.querySelectorAll(selector), 0, itemLimit || 8)
            .filter(function (el) {
                return el.offsetParent !== null && (
                    el.classList.contains("active") ||
                    el.classList.contains("is-active") ||
                    el.classList.contains("is-selected-pocket") ||
                    el.getAttribute("aria-pressed") === "true" ||
                    el.getAttribute("aria-selected") === "true"
                );
            })
            .map(function (el) { return compactText(el.textContent || el.getAttribute("title") || "", limit || 120); })
            .filter(Boolean);
    }

    function getSelectedPocketState() {
        var card = document.querySelector(".pocket-card.is-selected-pocket");
        if (!card) {
            return null;
        }
        return {
            title: compactText(card.getAttribute("data-pocket-title") || (card.querySelector(".pocket-card-name") || {}).textContent, 80),
            method: compactText(card.getAttribute("data-pocket-method"), 40),
            id: compactText(card.getAttribute("data-pocket-id"), 80),
            score: compactText(card.getAttribute("data-pocket-score"), 40),
            active_layers: activeTextFrom(".pocket-card.is-selected-pocket .js-repr-toggle", 80, 6),
        };
    }

    function getStructureViewerState() {
        // Two viewer instances, two id/class schemes: structure.html (fullscreen, sv-*
        // prefix) and protein.html (embedded, structure-* prefix). Neither is present on
        // pages without a viewer, so the combined selectors below just find nothing there.
        var spinBtn = document.querySelector("#sv-spin-btn, #structure-spin-btn");
        var activeModeBtn = document.querySelector(
            '.js-structure-mode.is-active, .js-structure-mode[aria-pressed="true"]'
        );
        if (!spinBtn && !activeModeBtn) {
            return null;
        }
        return {
            spin: !!(spinBtn && spinBtn.getAttribute("aria-pressed") === "true"),
            view_mode: activeModeBtn
                ? compactText(activeModeBtn.getAttribute("data-mode") || activeModeBtn.textContent, 30)
                : "",
        };
    }

    function getVisibleProteinRows() {
        return Array.prototype.slice.call(document.querySelectorAll(".protein-row"), 0, 5)
            .map(function (row) {
                var accession = compactText((row.querySelector(".acc-col a") || {}).textContent, 40);
                var description = compactText((row.querySelector('[data-col="description"], .desc-col') || {}).textContent, 120);
                var scoreCells = textsFromRoot(row, "td[data-col]", 80, 4);
                return accession ? {
                    accession: accession,
                    description: description,
                    visible_values: scoreCells,
                } : null;
            })
            .filter(Boolean);
    }

    function getPageState() {
        var selectedPocket = getSelectedPocketState();
        var state = {
            title: compactText(document.title, 120),
            heading: textFrom("main h1, h1", 120),
            subheading: textFrom(".section-subtitle, .hero-context-note, main h1 + p", 180),
            path: window.location.pathname,
            query: window.location.search ? compactText(window.location.search, 240) : "",
            active_filters: textsFrom(".active-filters .filter-pill, .filter-pill, .hero-analysis-criterion", 140, 10),
            sort: textFrom(".hero-analysis-value", 80),
            active_tabs: activeTextFrom(".tp-tab, .nav-link, .btn, .toolbar-action-btn", 90, 8),
            selected_pocket: selectedPocket,
            selected_structure: textFrom(".experimental-row--viewer-active, .structure-source-chip, .structure-toolbar", 160),
            structure_viewer: getStructureViewerState(),
            visible_proteins: getVisibleProteinRows(),
        };
        Object.keys(state).forEach(function (key) {
            if (
                state[key] === "" ||
                state[key] === null ||
                (Array.isArray(state[key]) && state[key].length === 0)
            ) {
                delete state[key];
            }
        });
        return state;
    }

    document.addEventListener("DOMContentLoaded", function () {
        var drawer = document.getElementById("tp-agent-drawer");
        var backdrop = document.getElementById("tp-agent-drawer-backdrop");
        var form = document.getElementById("tp-agent-drawer-form");
        if (!drawer || !form) {
            return;
        }

        var messagesEl = document.getElementById("tp-agent-drawer-messages");
        var inputEl = document.getElementById("tp-agent-drawer-input");
        var closeBtn = document.getElementById("tp-agent-drawer-close");
        var toggleBtn = document.getElementById("tp-agent-drawer-toggle");
        var toggleBtnMobile = document.getElementById("tp-agent-drawer-toggle-mobile");
        var suggestionButtons = Array.prototype.slice.call(document.querySelectorAll(".tp-agent-drawer-suggestion"));
        var biologistToggle = document.getElementById("tp-agent-drawer-biologist-toggle");
        var chatUrl = form.getAttribute("data-chat-url");

        var history = [];
        var pending = false;

        var BIOLOGIST_MODE_KEY = "tpAgentBiologistMode";
        var biologistMode = false;
        try {
            biologistMode = window.localStorage.getItem(BIOLOGIST_MODE_KEY) === "1";
        } catch (e) {
            /* localStorage unavailable (private mode, disabled storage) -- default off */
        }
        if (biologistToggle) {
            biologistToggle.setAttribute("aria-pressed", biologistMode ? "true" : "false");
            biologistToggle.addEventListener("click", function () {
                biologistMode = !biologistMode;
                biologistToggle.setAttribute("aria-pressed", biologistMode ? "true" : "false");
                try {
                    window.localStorage.setItem(BIOLOGIST_MODE_KEY, biologistMode ? "1" : "0");
                } catch (e) {
                    /* best effort */
                }
            });
        }

        function setOpen(open) {
            drawer.classList.toggle("is-open", open);
            drawer.setAttribute("aria-hidden", open ? "false" : "true");
            if (backdrop) {
                backdrop.classList.toggle("is-visible", open);
                backdrop.hidden = !open;
            }
            [toggleBtn, toggleBtnMobile].forEach(function (btn) {
                if (btn) {
                    btn.setAttribute("aria-expanded", open ? "true" : "false");
                }
            });
            if (open && inputEl) {
                inputEl.focus();
            }
        }

        [toggleBtn, toggleBtnMobile].forEach(function (btn) {
            if (btn) {
                btn.addEventListener("click", function () {
                    setOpen(!drawer.classList.contains("is-open"));
                });
            }
        });
        if (closeBtn) {
            closeBtn.addEventListener("click", function () {
                setOpen(false);
            });
        }
        if (backdrop) {
            backdrop.addEventListener("click", function () {
                setOpen(false);
            });
        }
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && drawer.classList.contains("is-open")) {
                setOpen(false);
            }
        });

        function appendMessage(role, text) {
            if (!messagesEl) {
                return;
            }
            var empty = messagesEl.querySelector(".tp-agent-drawer-empty");
            if (empty) {
                empty.remove();
            }
            var bubble = document.createElement("div");
            bubble.className = "tp-agent-drawer-msg tp-agent-drawer-msg--" + role + " tp-ui-enter";
            if (role === "pending") {
                bubble.innerHTML = '<span class="tp-agent-drawer-typing"><span></span><span></span><span></span></span>';
            } else if (role === "assistant") {
                bubble.innerHTML = renderMarkdown(text);
            } else {
                bubble.textContent = text;
            }
            messagesEl.appendChild(bubble);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            return bubble;
        }

        function appendErrorMessage(text, retryMessage) {
            var bubble = appendMessage("error", text);
            if (bubble && retryMessage) {
                var retryBtn = document.createElement("button");
                retryBtn.type = "button";
                retryBtn.className = "tp-agent-drawer-retry";
                retryBtn.textContent = "Retry";
                retryBtn.addEventListener("click", function () {
                    bubble.remove();
                    performRequest(retryMessage);
                });
                bubble.appendChild(retryBtn);
            }
            return bubble;
        }

        function performRequest(message) {
            pending = true;
            inputEl.disabled = true;
            var pendingBubble = appendMessage("pending");

            fetch(chatUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify({
                    page_path: window.location.pathname,
                    page_url: window.location.pathname + window.location.search,
                    page_state: getPageState(),
                    biologist_mode: biologistMode,
                    history: history,
                    message: message,
                }),
            })
                .then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                })
                .then(function (result) {
                    if (pendingBubble) {
                        pendingBubble.remove();
                    }
                    if (!result.ok || result.data.error) {
                        appendErrorMessage(
                            result.data.error || "The assistant is unavailable right now.",
                            result.data.retryable ? message : null
                        );
                        return;
                    }
                    history = result.data.history || history;
                    appendMessage("assistant", result.data.reply || "");
                    if (result.data.reload) {
                        window.setTimeout(function () {
                            if (result.data.redirect_url) {
                                window.location.href = result.data.redirect_url;
                            } else {
                                window.location.reload();
                            }
                        }, 650);
                    }
                })
                .catch(function () {
                    if (pendingBubble) {
                        pendingBubble.remove();
                    }
                    appendErrorMessage("Could not reach the assistant. Check your connection and try again.", message);
                })
                .finally(function () {
                    pending = false;
                    inputEl.disabled = false;
                    inputEl.focus();
                });
        }

        function sendMessage(rawMessage) {
            if (pending || !inputEl) {
                return;
            }
            var message = String(rawMessage || "").trim();
            if (!message) {
                return;
            }

            appendMessage("user", message);
            inputEl.value = "";
            performRequest(message);
        }

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            sendMessage(inputEl.value);
        });

        suggestionButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                var prompt = button.getAttribute("data-agent-prompt") || button.textContent || "";
                sendMessage(prompt);
            });
        });

        inputEl.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                form.requestSubmit();
            }
        });
    });
})();
