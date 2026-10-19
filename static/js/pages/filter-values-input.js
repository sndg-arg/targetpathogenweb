// Token input for criteria with too many values for chips (e.g. an uploaded
// locus-tag column): type to get suggestions from this genome's values,
// Enter / comma / Tab adds the value as a chip, pasting a list adds them all,
// Backspace on an empty field removes the last chip. On Apply the chips are
// written into the form's own textarea, so proteins-list.js queues the
// filter exactly as before (one add_filter_values change).
(function () {
    "use strict";

    var SPLIT_RE = /[\s,;]+/;
    var DEBOUNCE_MS = 140;

    function enhance(form) {
        var textarea = form.querySelector(".filter-values-input");
        var row = form.querySelector(".filter-values-row");
        var url = form.getAttribute("data-suggest-url");
        var paramId = form.getAttribute("data-param-id");
        if (!textarea || !row || !url || !paramId || form.dataset.tokenInput) return;
        form.dataset.tokenInput = "true";

        var values = [];
        var known = Object.create(null); // value (lowercase) -> true/false once checked
        var suggestions = [];
        var highlighted = -1;
        var timer = null;
        var requestSeq = 0;
        var listId = textarea.id + "-suggestions";

        var field = document.createElement("div");
        field.className = "filter-token-field";

        var chips = document.createElement("ul");
        chips.className = "filter-token-chips";
        chips.setAttribute("aria-label", form.getAttribute("data-param-label") || "");

        var input = document.createElement("input");
        input.type = "text";
        input.className = "filter-token-text";
        input.placeholder = textarea.placeholder;
        input.setAttribute("autocomplete", "off");
        input.setAttribute("spellcheck", "false");
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", listId);
        var label = form.querySelector(".filter-values-label");
        if (label) {
            label.setAttribute("for", textarea.id + "-text");
            input.id = textarea.id + "-text";
        }

        var list = document.createElement("ul");
        list.className = "filter-token-suggestions";
        list.id = listId;
        list.setAttribute("role", "listbox");
        list.hidden = true;

        field.appendChild(chips);
        field.appendChild(input);
        textarea.hidden = true;
        row.insertBefore(field, textarea);
        // In the flow under the field, not floating: the filter drawer's
        // groups clip overflow, which cut a floating list down to one row.
        row.insertAdjacentElement("afterend", list);

        field.addEventListener("click", function (event) {
            if (event.target === field || event.target === chips) input.focus();
        });

        var addButton = form.querySelector("button[type='submit']");

        // "Add" is disabled until there's a chip or something typed.
        function syncButton() {
            if (addButton) addButton.disabled = !values.length && !input.value.trim();
        }

        function syncTextarea() {
            syncButton();
            textarea.value = values.join("\n");
            field.classList.toggle("has-values", values.length > 0);
            input.placeholder = values.length ? "" : textarea.placeholder;
        }

        function renderChips() {
            chips.innerHTML = "";
            values.forEach(function (value, index) {
                var li = document.createElement("li");
                li.className = "tp-chip tp-chip--filter filter-token-chip";
                var text = document.createElement("span");
                text.textContent = value;
                var remove = document.createElement("button");
                remove.type = "button";
                remove.className = "filter-token-remove";
                remove.setAttribute("aria-label", "Remove " + value);
                remove.innerHTML = "&times;";
                remove.addEventListener("click", function () {
                    values.splice(index, 1);
                    renderChips();
                    syncTextarea();
                    input.focus();
                });
                li.appendChild(text);
                li.appendChild(remove);
                chips.appendChild(li);
            });
        }

        var checking = Object.create(null); // value (lowercase) -> pending check

        function checkKnown(value) {
            var key = value.toLowerCase();
            if (key in known) return Promise.resolve(known[key]);
            if (checking[key]) return checking[key];
            checking[key] = fetchValues(value).then(function (found) {
                known[key] = found.some(function (v) { return v.toLowerCase() === key; });
                delete checking[key];
                if (!known[key]) dropUnknown(value);
                return known[key];
            });
            return checking[key];
        }

        // A value no protein has is taken out right away and named in a small
        // bubble on the field, instead of staying as a chip nobody can use.
        var notice = document.createElement("div");
        notice.className = "tp-state-note tp-state-note--warning filter-token-notice";
        notice.setAttribute("role", "status");
        notice.hidden = true;
        row.insertAdjacentElement("afterend", notice); // in flow: the drawer clips overflow
        var noticeValues = [];
        var noticeTimer = null;

        function showNotice(value) {
            if (noticeValues.indexOf(value) === -1) noticeValues.push(value);
            var shown = noticeValues.slice(0, 3).map(function (v) { return "“" + v + "”"; }).join(", ");
            var more = noticeValues.length > 3 ? " +" + (noticeValues.length - 3) : "";
            notice.textContent = shown + more + (noticeValues.length > 1 ? " are not values in this genome, not added." : " is not a value in this genome, not added.");
            notice.hidden = false;
            notice.classList.remove("is-leaving");
            clearTimeout(noticeTimer);
            noticeTimer = setTimeout(function () {
                notice.classList.add("is-leaving");
                noticeTimer = setTimeout(function () {
                    notice.hidden = true;
                    noticeValues = [];
                }, 220);
            }, 4200);
        }

        function dropUnknown(value) {
            var before = values.length;
            values = values.filter(function (v) { return v.toLowerCase() !== value.toLowerCase(); });
            if (values.length !== before) {
                renderChips();
                syncTextarea();
            }
            showNotice(value);
        }

        function addValues(raw) {
            var added = false;
            String(raw || "").split(SPLIT_RE).forEach(function (part) {
                var value = part.trim();
                if (!value) return;
                if (known[value.toLowerCase()] === false) {
                    showNotice(value);
                    return;
                }
                var exists = values.some(function (v) { return v.toLowerCase() === value.toLowerCase(); });
                if (exists) return;
                values.push(value);
                checkKnown(value);
                added = true;
            });
            if (added) {
                renderChips();
                syncTextarea();
            }
            input.value = "";
            closeList();
        }

        function fetchValues(query) {
            var params = new URLSearchParams({ param: paramId, q: query });
            return fetch(url + "?" + params.toString(), { headers: { Accept: "application/json" } })
                .then(function (response) { return response.ok ? response.json() : { values: [] }; })
                .then(function (data) { return Array.isArray(data.values) ? data.values : []; })
                .catch(function () { return []; });
        }

        function closeList() {
            list.hidden = true;
            list.innerHTML = "";
            suggestions = [];
            highlighted = -1;
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
        }

        function setHighlight(index) {
            highlighted = index;
            Array.from(list.children).forEach(function (li, i) {
                var on = i === index;
                li.classList.toggle("is-highlighted", on);
                li.setAttribute("aria-selected", on ? "true" : "false");
                if (on) {
                    input.setAttribute("aria-activedescendant", li.id);
                    li.scrollIntoView({ block: "nearest" });
                }
            });
        }

        function renderList(found, query) {
            var chosen = values.map(function (v) { return v.toLowerCase(); });
            suggestions = found.filter(function (v) { return chosen.indexOf(v.toLowerCase()) === -1; });
            list.innerHTML = "";
            if (!suggestions.length) {
                closeList();
                return;
            }
            var q = query.toLowerCase();
            suggestions.forEach(function (value, i) {
                var li = document.createElement("li");
                li.id = listId + "-" + i;
                li.setAttribute("role", "option");
                var at = value.toLowerCase().indexOf(q);
                if (at >= 0 && q) {
                    li.appendChild(document.createTextNode(value.slice(0, at)));
                    var mark = document.createElement("mark");
                    mark.textContent = value.slice(at, at + q.length);
                    li.appendChild(mark);
                    li.appendChild(document.createTextNode(value.slice(at + q.length)));
                } else {
                    li.textContent = value;
                }
                li.addEventListener("mousedown", function (event) {
                    event.preventDefault(); // keep focus in the input
                    known[value.toLowerCase()] = true;
                    addValues(value);
                    input.focus();
                });
                list.appendChild(li);
            });
            list.hidden = false;
            input.setAttribute("aria-expanded", "true");
            setHighlight(0);
        }

        // Enter before the suggestions arrived: an exact match is added; a
        // partial one ("KPN") opens the suggestions to pick from instead of
        // becoming a value no protein has; only text with no match at all is
        // added as typed (and flagged).
        function commitTyped() {
            var typed = input.value.trim();
            if (!typed) return;
            clearTimeout(timer);
            var seq = ++requestSeq;
            fetchValues(typed).then(function (found) {
                if (seq !== requestSeq || input.value.trim() !== typed) return;
                var exact = found.filter(function (v) { return v.toLowerCase() === typed.toLowerCase(); })[0];
                if (exact) {
                    known[exact.toLowerCase()] = true;
                    addValues(exact);
                } else if (found.length) {
                    renderList(found, typed);
                } else {
                    known[typed.toLowerCase()] = false;
                    addValues(typed);
                }
            });
        }

        input.addEventListener("input", function () {
            syncButton();
            var query = input.value.trim();
            if (SPLIT_RE.test(input.value) && query) {
                // Typed a separator (space, comma): commit what's before it,
                // same rules as Enter.
                var parts = input.value.split(SPLIT_RE).filter(Boolean);
                if (parts.length > 1) {
                    addValues(parts.slice(0, -1).join(" "));
                    input.value = parts[parts.length - 1];
                } else {
                    input.value = parts[0] || "";
                }
                commitTyped();
                return;
            }
            clearTimeout(timer);
            if (!query) {
                closeList();
                return;
            }
            var seq = ++requestSeq;
            timer = setTimeout(function () {
                fetchValues(query).then(function (found) {
                    if (seq === requestSeq && input.value.trim() === query) renderList(found, query);
                });
            }, DEBOUNCE_MS);
        });

        input.addEventListener("paste", function (event) {
            var text = (event.clipboardData || window.clipboardData).getData("text");
            if (text && SPLIT_RE.test(text.trim())) {
                event.preventDefault();
                addValues(text);
            }
        });

        input.addEventListener("keydown", function (event) {
            var listOpen = !list.hidden && suggestions.length;
            if (event.key === "ArrowDown" && listOpen) {
                event.preventDefault();
                setHighlight((highlighted + 1) % suggestions.length);
            } else if (event.key === "ArrowUp" && listOpen) {
                event.preventDefault();
                setHighlight((highlighted - 1 + suggestions.length) % suggestions.length);
            } else if (event.key === "Enter" || (event.key === "Tab" && input.value.trim())) {
                if (!input.value.trim() && event.key === "Enter") {
                    // Empty field + Enter: apply the chips (if any).
                    event.preventDefault();
                    if (values.length) form.requestSubmit ? form.requestSubmit() : form.submit();
                    return;
                }
                event.preventDefault();
                if (listOpen && highlighted >= 0) {
                    var picked = suggestions[highlighted];
                    known[picked.toLowerCase()] = true;
                    addValues(picked);
                } else {
                    commitTyped();
                }
            } else if (event.key === "Escape" && listOpen) {
                event.preventDefault();
                closeList();
            } else if (event.key === "Backspace" && !input.value && values.length) {
                values.pop();
                renderChips();
                syncTextarea();
            }
        });

        input.addEventListener("blur", function () {
            setTimeout(closeList, 120);
        });

        // Only chips are applied (plus text that exactly matches a suggestion):
        // half-typed text left in the field ("kpn") is not a value. Capture phase, so it runs before proteins-list.js
        // reads the form.
        // Only values that exist in this genome are applied (unknown ones are
        // dropped as soon as they're checked). Capture phase on the form, so
        // this runs before proteins-list.js's document-level handler -- and
        // can hold it until a running check finishes.
        form.addEventListener("submit", function (event) {
            var leftover = input.value.trim().toLowerCase();
            var exact = suggestions.filter(function (v) { return v.toLowerCase() === leftover; })[0];
            if (exact) {
                known[leftover] = true;
                addValues(exact);
            }
            input.value = "";
            closeList();

            // A check still running: wait for it, then submit again.
            var pending = values.filter(function (v) { return !(v.toLowerCase() in known); });
            if (pending.length) {
                event.preventDefault();
                event.stopImmediatePropagation();
                Promise.all(pending.map(checkKnown)).then(function () {
                    if (form.requestSubmit) form.requestSubmit();
                });
                return;
            }

            syncTextarea();
        }, true);

        // Queued values stay visible as pending chips under the field until
        // the drawer's "Apply filters" runs (proteins-list.js resets the form
        // right after queueing it, so the field itself is emptied).
        var queuedGroup = document.createElement("div");
        queuedGroup.className = "filter-chip-group filter-token-queued";
        queuedGroup.hidden = true;
        var queuedNote = document.createElement("p");
        queuedNote.className = "filter-token-queued-note";
        queuedNote.hidden = true;
        var message = form.querySelector(".filter-input-message");
        if (message) {
            message.insertAdjacentElement("beforebegin", queuedGroup);
            message.insertAdjacentElement("beforebegin", queuedNote);
        } else {
            form.appendChild(queuedGroup);
            form.appendChild(queuedNote);
        }
        var queuedValues = [];

        function renderQueued() {
            queuedGroup.innerHTML = "";
            queuedValues.forEach(function (value) {
                var chip = document.createElement("span");
                chip.className = "filter-chip filter-chip--active filter-chip--pending";
                chip.textContent = value;
                queuedGroup.appendChild(chip);
            });
            queuedGroup.hidden = !queuedValues.length;
            queuedNote.hidden = !queuedValues.length;
            queuedNote.textContent = queuedValues.length ? "Queued. Press Apply filters to update the results." : "";
        }

        form.addEventListener("reset", function () {
            var sent = values.slice();
            values = [];
            setTimeout(function () {
                if (sent.length) {
                    sent.forEach(function (v) {
                        if (queuedValues.indexOf(v) === -1) queuedValues.push(v);
                    });
                    renderQueued();
                    // The chips say what's queued; drop the long sentence.
                    if (message) message.textContent = "";
                }
                renderChips();
                syncTextarea();
            }, 0);
        });

        syncButton();
    }

    function init() {
        document.querySelectorAll(".filter-values-form[data-suggest-url]").forEach(enhance);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
