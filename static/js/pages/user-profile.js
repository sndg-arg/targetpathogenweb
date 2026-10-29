/* "My profile" page -- each row has its own Edit button, all sharing one
 * modal: opening it shows only that row's inputs (Name = first + last; the
 * others stay in the DOM, hidden, still carrying their current value so the
 * single underlying form submission stays valid). Save stays disabled
 * until a visible value actually changed AND every visible one passes a
 * minimum client-side check (non-empty name, email-shaped email); the
 * server still re-validates everything (email uniqueness in particular)
 * on submit regardless.
 */
(function () {
    "use strict";

    var modal = document.getElementById("profile-edit-modal");
    var panel = modal ? modal.querySelector(".profile-edit-panel") : null;
    var closeBtn = document.getElementById("profile-edit-close");
    var cancelBtn = document.getElementById("profile-edit-cancel");
    var form = document.getElementById("profile-edit-form");
    var saveBtn = document.getElementById("profile-edit-save");
    var titleEl = document.getElementById("profile-edit-modal-title");
    if (!modal || !panel || !form || !saveBtn) return;

    var fieldGroups = Array.prototype.slice.call(form.querySelectorAll("[data-field-group]"));
    var editTriggers = Array.prototype.slice.call(document.querySelectorAll(".js-profile-edit-field"));

    var activeFields = [];
    var originalValues = {};
    var lastTrigger = null;

    function fieldsOf(trigger) {
        return (trigger.getAttribute("data-field") || "").split(/\s+/).filter(Boolean);
    }

    function inputFor(fieldName) {
        var group = fieldGroups.filter(function (g) {
            return g.getAttribute("data-field-group") === fieldName;
        })[0];
        return group ? group.querySelector("input") : null;
    }

    // Deliberately simple -- just enough to catch an obviously incomplete
    // address before it round-trips to the server, not full RFC validation.
    function looksLikeEmail(value) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
    }

    function isValidValue(fieldName, value) {
        if (fieldName === "email") return looksLikeEmail(value);
        return value.length > 0;
    }

    // Set only for the auto-reopen-after-a-rejected-submit case: the value
    // already showing IS the one the server just rejected, so "unchanged
    // from what's shown" must not be read as "nothing to fix" the way it
    // would for a normal edit.
    var hasServerError = false;

    function updateSaveState() {
        var changed = hasServerError;
        var valid = activeFields.length > 0;
        activeFields.forEach(function (fieldName) {
            var input = inputFor(fieldName);
            var value = input ? input.value.trim() : "";
            if (value !== (originalValues[fieldName] || "").trim()) changed = true;
            if (!isValidValue(fieldName, value)) valid = false;
        });
        saveBtn.disabled = !(changed && valid);
    }

    function openFieldModal(fields, label, trigger, hadServerError) {
        activeFields = fields;
        hasServerError = !!hadServerError;
        fieldGroups.forEach(function (group) {
            group.hidden = fields.indexOf(group.getAttribute("data-field-group")) === -1;
        });
        if (titleEl) titleEl.textContent = label || fields.join(", ");

        originalValues = {};
        fields.forEach(function (fieldName) {
            var input = inputFor(fieldName);
            originalValues[fieldName] = input ? input.value : "";
        });
        updateSaveState();

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("profile-modal-open");
        lastTrigger = trigger || null;
        var first = inputFor(fields[0]);
        if (first) first.focus();
    }

    function closeModal() {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("profile-modal-open");
        if (lastTrigger) lastTrigger.focus();
        lastTrigger = null;
        activeFields = [];
    }

    editTriggers.forEach(function (trigger) {
        trigger.addEventListener("click", function () {
            openFieldModal(fieldsOf(trigger), trigger.getAttribute("data-field-label"), trigger);
        });
    });

    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", function (ev) {
        if (!panel.contains(ev.target)) closeModal();
    });
    document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && modal.classList.contains("is-open")) closeModal();
    });

    fieldGroups.forEach(function (group) {
        var input = group.querySelector("input");
        if (input) input.addEventListener("input", updateSaveState);
    });

    // A failed POST (e.g. "email already in use") re-renders this same
    // page with the erroring field's errors set -- the modal needs to
    // already be open, scoped to that row, so the error is actually
    // visible instead of hidden behind the closed modal.
    if (window.TPW_PROFILE_ERROR_FIELD) {
        var errorTrigger = editTriggers.filter(function (trigger) {
            return fieldsOf(trigger).indexOf(window.TPW_PROFILE_ERROR_FIELD) !== -1;
        })[0];
        if (errorTrigger) {
            openFieldModal(fieldsOf(errorTrigger), errorTrigger.getAttribute("data-field-label"), errorTrigger, true);
        }
    }
})();
