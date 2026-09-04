/* "My profile" page -- read-only card with an Edit button that opens a
 * modal. Save stays disabled until something actually changed AND the
 * minimum client-side checks pass (non-empty names, email-shaped email);
 * the server still re-validates everything (email uniqueness in
 * particular) on submit regardless.
 */
(function () {
    "use strict";

    var trigger = document.getElementById("profile-edit-trigger");
    var modal = document.getElementById("profile-edit-modal");
    var panel = modal ? modal.querySelector(".profile-edit-panel") : null;
    var closeBtn = document.getElementById("profile-edit-close");
    var cancelBtn = document.getElementById("profile-edit-cancel");
    var form = document.getElementById("profile-edit-form");
    var saveBtn = document.getElementById("profile-edit-save");
    if (!trigger || !modal || !panel || !form || !saveBtn) return;

    var firstNameInput = form.querySelector("[name='first_name']");
    var lastNameInput = form.querySelector("[name='last_name']");
    var emailInput = form.querySelector("[name='email']");

    var original = { first_name: "", last_name: "", email: "" };
    var lastTrigger = null;

    function snapshotOriginal() {
        original = {
            first_name: firstNameInput.value.trim(),
            last_name: lastNameInput.value.trim(),
            email: emailInput.value.trim()
        };
    }

    // Deliberately simple -- just enough to catch an obviously incomplete
    // address before it round-trips to the server, not full RFC validation.
    function looksLikeEmail(value) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
    }

    function updateSaveState() {
        var firstName = firstNameInput.value.trim();
        var lastName = lastNameInput.value.trim();
        var email = emailInput.value.trim();

        var valid = firstName.length > 0 && lastName.length > 0 && looksLikeEmail(email);
        var changed = firstName !== original.first_name
            || lastName !== original.last_name
            || email !== original.email;

        saveBtn.disabled = !(valid && changed);
    }

    function openModal(trigger_) {
        snapshotOriginal();
        updateSaveState();
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("profile-modal-open");
        lastTrigger = trigger_ || trigger;
        firstNameInput.focus();
    }

    function closeModal() {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("profile-modal-open");
        if (lastTrigger) lastTrigger.focus();
        lastTrigger = null;
    }

    trigger.addEventListener("click", function () { openModal(trigger); });
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", function (ev) {
        if (!panel.contains(ev.target)) closeModal();
    });
    document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && modal.classList.contains("is-open")) closeModal();
    });

    [firstNameInput, lastNameInput, emailInput].forEach(function (input) {
        input.addEventListener("input", updateSaveState);
    });

    // A failed POST (e.g. "email already in use") re-renders this same
    // page with form.errors set -- the modal needs to already be open so
    // the error is actually visible, not hidden behind the closed modal.
    if (window.TPW_PROFILE_HAS_ERRORS) {
        openModal(trigger);
        updateSaveState();
    }
})();
