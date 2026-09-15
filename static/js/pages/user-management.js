/* /users "Manage users" screen -- the Edit button on each approved,
 * non-superuser row opens a shared modal (one dialog, reused per row) to
 * toggle that person's individual permissions in-app, instead of sending
 * the owner to Django admin's own user_permissions widget. The trigger
 * carries the user's id/name/currently-granted codenames as data
 * attributes; opening the modal just points the form at that user and
 * checks the right boxes -- the actual grant/revoke happens server-side
 * on submit (see UserManagementView.post, action=update_permissions).
 */
(function () {
    "use strict";

    var modal = document.getElementById("user-permissions-modal");
    var panel = modal ? modal.querySelector(".user-mgmt-edit-panel") : null;
    var closeBtn = document.getElementById("user-permissions-modal-close");
    var cancelBtn = document.getElementById("user-permissions-modal-cancel");
    var nameEl = document.getElementById("user-permissions-modal-name");
    var userIdInput = document.getElementById("user-permissions-modal-user-id");
    var form = document.getElementById("user-permissions-form");
    if (!modal || !panel || !form || !userIdInput) return;

    var checkboxes = Array.prototype.slice.call(form.querySelectorAll('input[name="permissions"]'));
    var editTriggers = Array.prototype.slice.call(document.querySelectorAll(".user-mgmt-edit-trigger"));

    var lastTrigger = null;

    function openModal(trigger) {
        var granted = [];
        try {
            granted = JSON.parse(trigger.getAttribute("data-granted") || "[]");
        } catch (err) {
            granted = [];
        }

        userIdInput.value = trigger.getAttribute("data-user-id") || "";
        if (nameEl) nameEl.textContent = trigger.getAttribute("data-user-name") || "";
        checkboxes.forEach(function (checkbox) {
            checkbox.checked = granted.indexOf(checkbox.value) !== -1;
        });

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("user-mgmt-modal-open");
        lastTrigger = trigger;
    }

    function closeModal() {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("user-mgmt-modal-open");
        if (lastTrigger) lastTrigger.focus();
        lastTrigger = null;
    }

    editTriggers.forEach(function (trigger) {
        trigger.addEventListener("click", function () {
            openModal(trigger);
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
})();
