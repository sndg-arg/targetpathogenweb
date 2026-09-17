/* /users "Manage users" screen -- the Edit button on each approved,
 * non-superuser row opens a shared modal (one dialog, reused per row) to
 * toggle that person's individual permissions in-app, instead of sending
 * the owner to Django admin's own user_permissions widget. The trigger
 * carries the user's id/name/currently-granted codenames as data
 * attributes; opening the modal just points the form at that user and
 * checks the right boxes -- the actual grant/revoke happens server-side
 * on submit (see UserManagementView.post, action=update_permissions).
 *
 * The profile <select> is a pure client-side convenience on top of that
 * same checkbox list (tpweb.services.user_permissions.PROFILE_PRESETS,
 * embedded below as JSON) -- picking one just pre-checks/unchecks boxes,
 * it never becomes part of what's actually submitted. "Advanced" mode is
 * just not picking one, or hand-adjusting after.
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
    var profileSelect = document.getElementById("user-permissions-profile-select");
    var roleSelect = document.getElementById("user-permissions-role-select");

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

    function matchingPresetKey(checkedCodenames) {
        var checkedSet = checkedCodenames.slice().sort().join(",");
        for (var i = 0; i < profilePresets.length; i++) {
            var presetSet = profilePresets[i].codenames.slice().sort().join(",");
            if (presetSet === checkedSet) return profilePresets[i].key;
        }
        return "";
    }

    if (modal && panel && form && userIdInput) {
        var checkboxes = Array.prototype.slice.call(
            form.querySelectorAll('input[name="permissions"]')
        );
        var editTriggers = Array.prototype.slice.call(
            document.querySelectorAll(".user-mgmt-edit-trigger")
        );
        var lastTrigger = null;

        function checkedCodenames() {
            return checkboxes.filter(function (cb) {
                return cb.checked;
            }).map(function (cb) {
                return cb.value;
            });
        }

        function syncProfileSelectToCheckboxes() {
            if (!profileSelect) return;
            profileSelect.value = matchingPresetKey(checkedCodenames());
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
            if (roleSelect) roleSelect.value = trigger.getAttribute("data-role") || "";
            checkboxes.forEach(function (checkbox) {
                checkbox.checked = granted.indexOf(checkbox.value) !== -1;
            });
            syncProfileSelectToCheckboxes();

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

        if (profileSelect) {
            profileSelect.addEventListener("change", function () {
                var preset = presetByKey(profileSelect.value);
                var presetCodenames = preset ? preset.codenames : [];
                checkboxes.forEach(function (checkbox) {
                    checkbox.checked = presetCodenames.indexOf(checkbox.value) !== -1;
                });
            });
        }

        checkboxes.forEach(function (checkbox) {
            checkbox.addEventListener("change", syncProfileSelectToCheckboxes);
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
