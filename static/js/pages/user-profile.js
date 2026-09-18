/* "My profile" page -- each field has its own Edit (pencil) button, all
 * sharing one modal: opening it shows only that field's input (the other
 * two stay in the DOM, hidden, still carrying their current value so the
 * single underlying form submission stays valid). Save stays disabled
 * until the visible field's value actually changed AND passes a minimum
 * client-side check (non-empty name, email-shaped email); the server
 * still re-validates everything (email uniqueness in particular) on
 * submit regardless.
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

    var activeField = null;
    var originalValue = "";
    var lastTrigger = null;

    function groupFor(fieldName) {
        return fieldGroups.filter(function (group) {
            return group.getAttribute("data-field-group") === fieldName;
        })[0] || null;
    }

    function inputFor(fieldName) {
        var group = groupFor(fieldName);
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
        var input = inputFor(activeField);
        if (!input) return;
        var value = input.value.trim();
        var changed = hasServerError || value !== originalValue.trim();
        var valid = isValidValue(activeField, value);
        saveBtn.disabled = !(changed && valid);
    }

    function openFieldModal(fieldName, label, trigger, hadServerError) {
        activeField = fieldName;
        hasServerError = !!hadServerError;
        fieldGroups.forEach(function (group) {
            group.hidden = group.getAttribute("data-field-group") !== fieldName;
        });
        if (titleEl) titleEl.textContent = label || fieldName;

        var input = inputFor(fieldName);
        originalValue = input ? input.value : "";
        updateSaveState();

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("profile-modal-open");
        lastTrigger = trigger || null;
        if (input) input.focus();
    }

    function closeModal() {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("profile-modal-open");
        if (lastTrigger) lastTrigger.focus();
        lastTrigger = null;
        activeField = null;
    }

    editTriggers.forEach(function (trigger) {
        trigger.addEventListener("click", function () {
            openFieldModal(trigger.getAttribute("data-field"), trigger.getAttribute("data-field-label"), trigger);
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
    // already be open, scoped to that field, so the error is actually
    // visible instead of hidden behind the closed modal.
    if (window.TPW_PROFILE_ERROR_FIELD) {
        var errorTrigger = editTriggers.filter(function (trigger) {
            return trigger.getAttribute("data-field") === window.TPW_PROFILE_ERROR_FIELD;
        })[0];
        if (errorTrigger) {
            openFieldModal(
                window.TPW_PROFILE_ERROR_FIELD,
                errorTrigger.getAttribute("data-field-label"),
                errorTrigger,
                true
            );
        }
    }
})();
