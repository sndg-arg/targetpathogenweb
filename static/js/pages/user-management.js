/* /users "Manage users" screen -- the Edit button on each approved,
 * non-superuser row opens a shared modal (one dialog, reused per row) to
 * assign that person's role in-app, instead of sending the owner to Django
 * admin's own user_permissions widget. The trigger carries the user's
 * id/name/current role as data attributes; opening the modal points the
 * form at that user and preselects their current role. The actual save
 * happens server-side on submit (see UserManagementView.post,
 * action=update_permissions), which re-derives a named role's codenames
 * itself rather than trusting anything else from the client. A role is the
 * whole permission set -- there's no per-permission hand-picking.
 *
 * Revoke access goes through its own confirm modal instead of a native
 * confirm() -- those are easy to click through by reflex without reading.
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
    var roleSelect = document.getElementById("user-permissions-role-select");

    if (modal && panel && form && userIdInput && roleSelect) {
        var editTriggers = Array.prototype.slice.call(
            document.querySelectorAll(".user-mgmt-edit-trigger")
        );
        var lastTrigger = null;

        function openModal(trigger) {
            userIdInput.value = trigger.getAttribute("data-user-id") || "";
            if (nameEl) nameEl.textContent = trigger.getAttribute("data-user-name") || "";

            var currentRole = trigger.getAttribute("data-role") || "";
            var hasRoleOption = Array.prototype.some.call(roleSelect.options, function (option) {
                return option.value === currentRole;
            });
            if (hasRoleOption) roleSelect.value = currentRole;

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
        // Close only on a click landing exactly on the backdrop -- a native
        // <select> popup (the role dropdown) isn't really part of the page's
        // DOM layout, and picking an option can report a click target that
        // "panel.contains(ev.target)" doesn't recognize as inside the panel
        // in some browsers, closing the modal instead of letting the pick
        // register.
        modal.addEventListener("click", function (ev) {
            if (ev.target === modal) closeModal();
        });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && modal.classList.contains("is-open")) closeModal();
        });
    }

    var revokeModal = document.getElementById("user-revoke-modal");
    var revokePanel = revokeModal ? revokeModal.querySelector(".user-mgmt-edit-panel") : null;
    var revokeCloseBtn = document.getElementById("user-revoke-modal-close");
    var revokeCancelBtn = document.getElementById("user-revoke-modal-cancel");
    var revokeNameEl = document.getElementById("user-revoke-modal-name");
    var revokeUserIdInput = document.getElementById("user-revoke-modal-user-id");
    var revokeTriggers = Array.prototype.slice.call(
        document.querySelectorAll(".user-mgmt-revoke-trigger")
    );

    if (revokeModal && revokePanel && revokeUserIdInput && revokeTriggers.length) {
        var lastRevokeTrigger = null;

        function openRevokeModal(trigger) {
            revokeUserIdInput.value = trigger.getAttribute("data-user-id") || "";
            if (revokeNameEl) revokeNameEl.textContent = trigger.getAttribute("data-user-name") || "";
            revokeModal.classList.add("is-open");
            revokeModal.setAttribute("aria-hidden", "false");
            document.body.classList.add("user-mgmt-modal-open");
            lastRevokeTrigger = trigger;
        }

        function closeRevokeModal() {
            revokeModal.classList.remove("is-open");
            revokeModal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("user-mgmt-modal-open");
            if (lastRevokeTrigger) lastRevokeTrigger.focus();
            lastRevokeTrigger = null;
        }

        revokeTriggers.forEach(function (trigger) {
            trigger.addEventListener("click", function () {
                openRevokeModal(trigger);
            });
        });

        if (revokeCloseBtn) revokeCloseBtn.addEventListener("click", closeRevokeModal);
        if (revokeCancelBtn) revokeCancelBtn.addEventListener("click", closeRevokeModal);
        revokeModal.addEventListener("click", function (ev) {
            if (ev.target === revokeModal) closeRevokeModal();
        });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && revokeModal.classList.contains("is-open")) closeRevokeModal();
        });
    }
})();
