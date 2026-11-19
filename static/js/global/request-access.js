// "Request access" (components/request_access_form.html): the institution
// field only appears once the button is pressed. Open from the start it reads
// as a field someone forgot to finish, next to a button that looks unrelated.
//
// The server renders the field open and required, and this hides it, so a
// browser that never runs the script still shows a form that can be filled in
// and sent.
(function () {
    "use strict";

    function setUp(form) {
        var field = form.querySelector("[data-request-access-field]");
        var input = field ? field.querySelector("input[name='institution']") : null;
        var button = form.querySelector("[data-request-access-submit]");
        if (!field || !input || !button || form.dataset.requestAccessReady) {
            return;
        }
        form.dataset.requestAccessReady = "1";

        function collapse() {
            field.classList.add("is-hidden");
            // A required field the browser cannot focus blocks the whole
            // form, so the requirement comes back with the field.
            input.required = false;
        }

        function reveal() {
            field.classList.remove("is-hidden");
            input.required = true;
            button.textContent = button.getAttribute("data-request-access-submit");
            input.focus();
        }

        collapse();
        button.addEventListener("click", function (event) {
            if (field.classList.contains("is-hidden")) {
                // First press asks the question instead of sending a
                // request with nothing to review.
                event.preventDefault();
                reveal();
            }
        });
    }

    function init() {
        Array.prototype.forEach.call(document.querySelectorAll(".tp-request-access"), setUp);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
