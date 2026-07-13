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
        var chatUrl = form.getAttribute("data-chat-url");

        var history = [];
        var pending = false;

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
            bubble.className = "tp-agent-drawer-msg tp-agent-drawer-msg--" + role;
            bubble.textContent = text;
            messagesEl.appendChild(bubble);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            return bubble;
        }

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            if (pending || !inputEl) {
                return;
            }
            var message = inputEl.value.trim();
            if (!message) {
                return;
            }

            appendMessage("user", message);
            inputEl.value = "";
            pending = true;
            inputEl.disabled = true;
            var pendingBubble = appendMessage("pending", "…");

            fetch(chatUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify({
                    page_path: window.location.pathname,
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
                        appendMessage("error", result.data.error || "The assistant is unavailable right now.");
                        return;
                    }
                    history = result.data.history || history;
                    appendMessage("assistant", result.data.reply || "");
                })
                .catch(function () {
                    if (pendingBubble) {
                        pendingBubble.remove();
                    }
                    appendMessage("error", "Could not reach the assistant. Check your connection and try again.");
                })
                .finally(function () {
                    pending = false;
                    inputEl.disabled = false;
                    inputEl.focus();
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
