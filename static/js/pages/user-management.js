/* /users "Manage users" screen -- the Edit button on each approved,
 * non-superuser row opens a shared modal (one dialog, reused per row) to
 * set that person's role and permissions in-app, instead of sending the
 * owner to Django admin's own user_permissions widget. The trigger carries
 * the user's id/name/current role/currently-granted codenames as data
 * attributes; opening the modal points the form at that user and shows
 * the matching state. The actual save happens server-side on submit (see
 * UserManagementView.post, action=update_permissions), which re-derives a
 * named role's codenames itself rather than trusting the submitted
 * checkboxes -- the disabled state below is a UI nicety, not enforcement.
 *
 * The Role <select> drives the checkboxes: picking a named role fills them
 * to match that role's exact permission set (tpweb.services.
 * user_permissions.PROFILE_PRESETS, embedded below as JSON) and disables
 * them, since the role IS the permission set. Picking Custom unlocks them
 * for hand-picked permissions that don't match any named role.
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
    var CUSTOM_ROLE = "custom";

    var profilePresets = [];
    var presetsEl = document.getElementById("user-mgmt-profile-presets");
    if (presetsEl) {
        try {
            profilePresets = JSON.parse(presetsEl.textContent || "[]");
        } catch (err) {
            profilePresets = [];
        }
    }

    function presetByKey(key) {
        for (var i = 0; i < profilePresets.length; i++) {
            if (profilePresets[i].key === key) return profilePresets[i];
        }
        return null;
    }

    if (modal && panel && form && userIdInput && roleSelect) {
        var checkboxes = Array.prototype.slice.call(
            form.querySelectorAll('input[name="permissions"]')
        );
        var editTriggers = Array.prototype.slice.call(
            document.querySelectorAll(".user-mgmt-edit-trigger")
        );
        var lastTrigger = null;

        function setCheckboxesLocked(locked) {
            checkboxes.forEach(function (checkbox) {
                checkbox.disabled = locked;
                var row = checkbox.closest(".user-mgmt-perm-row");
                if (row) row.classList.toggle("is-locked", locked);
            });
        }

        function applyRole(roleKey) {
            if (roleKey === CUSTOM_ROLE) {
                setCheckboxesLocked(false);
                return;
            }
            var preset = presetByKey(roleKey);
            var presetCodenames = preset ? preset.codenames : [];
            checkboxes.forEach(function (checkbox) {
                checkbox.checked = presetCodenames.indexOf(checkbox.value) !== -1;
            });
            setCheckboxesLocked(true);
        }

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

            var currentRole = trigger.getAttribute("data-role") || "";
            var hasRoleOption = Array.prototype.some.call(roleSelect.options, function (option) {
                return option.value === currentRole;
            });
            roleSelect.value = hasRoleOption ? currentRole : CUSTOM_ROLE;
            applyRole(roleSelect.value);

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

        roleSelect.addEventListener("change", function () {
            applyRole(roleSelect.value);
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
            if (!revokePanel.contains(ev.target)) closeRevokeModal();
        });
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && revokeModal.classList.contains("is-open")) closeRevokeModal();
        });
    }
})();
