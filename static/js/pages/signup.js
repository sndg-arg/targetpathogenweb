// Signup form: the password rules checked here instead of only on the server.
//
// Django validates every one of these again (that is what actually guards the
// account); this exists so the three usual mistakes -- too short, entirely
// numeric, an obvious password -- are answered in place instead of after a
// round trip that throws away everything already typed. Any rule this file
// cannot reproduce faithfully (the full 20k common-password list) stays with
// the server, which is why nothing here is treated as approval.
(function () {
    "use strict";

    var form = document.getElementById("signup_form");
    if (!form) {
        return;
    }

    var password = document.getElementById("id_password1");
    var confirmation = document.getElementById("id_password2");
    var email = document.getElementById("id_email");
    var firstName = document.getElementById("id_first_name");
    var lastName = document.getElementById("id_last_name");

    var MIN_LENGTH = 8;
    // Django's own wording, handed over by signup.html so the message a
    // person reads here is the one the server would have sent back.
    var COPY = window.TPW_SIGNUP_I18N || {};
    // The head of Django's common-password list. The server holds all 20k;
    // these are the ones someone actually types, so catching them here is
    // what spares the round trip.
    var COMMON_PASSWORDS = [
        "123456", "123456789", "12345678", "1234567890", "password", "password1",
        "password123", "qwerty", "qwerty123", "qwertyuiop", "111111", "123123",
        "abc123", "1234567", "iloveyou", "000000", "123321", "666666", "654321",
        "admin", "admin123", "welcome", "welcome1", "monkey", "dragon", "sunshine",
        "princess", "football", "baseball", "letmein", "login", "master", "shadow",
        "superman", "michael", "jordan", "harley", "ranger", "trustno1", "freedom",
        "whatever", "starwars", "computer", "internet", "samsung", "google",
        "zaq12wsx", "asdfghjkl", "1q2w3e4r", "1qaz2wsx", "passw0rd", "p@ssword",
        "secret", "test123", "changeme", "charlie", "donald", "hello123"
    ];

    function clearErrors() {
        Array.prototype.forEach.call(
            form.querySelectorAll(".tp-client-error"),
            function (node) {
                node.parentNode.removeChild(node);
            }
        );
        Array.prototype.forEach.call(
            form.querySelectorAll(".tp-client-invalid"),
            function (node) {
                node.classList.remove("is-invalid", "tp-client-invalid");
            }
        );
    }

    // Same markup Django's own errors come back in, so a message raised here
    // and one raised by the server look identical.
    function showErrors(field, messages) {
        field.classList.add("is-invalid", "tp-client-invalid");
        messages.forEach(function (message) {
            var paragraph = document.createElement("p");
            paragraph.className = "invalid-feedback tp-client-error";
            var strong = document.createElement("strong");
            strong.textContent = message;
            paragraph.appendChild(strong);
            field.parentNode.insertBefore(paragraph, field.nextSibling);
        });
    }

    function personalStrings() {
        // What UserAttributeSimilarityValidator compares against on the
        // server: the email (whole and local part) and the name parts.
        return [
            email ? email.value : "",
            email && email.value.indexOf("@") > -1 ? email.value.split("@")[0] : "",
            firstName ? firstName.value : "",
            lastName ? lastName.value : ""
        ].filter(function (value) {
            // Short fragments ("ana") turn up inside perfectly good
            // passwords; the server compares with a similarity ratio, and
            // guessing low here would block a password Django accepts.
            return value && value.length >= 5;
        });
    }

    function passwordProblems(value) {
        var problems = [];
        if (value.length < MIN_LENGTH) {
            problems.push(COPY.tooShort ||
                "This password is too short. It must contain at least 8 characters.");
        }
        if (COMMON_PASSWORDS.indexOf(value.toLowerCase()) > -1) {
            problems.push(COPY.tooCommon || "This password is too common.");
        }
        if (/^\d+$/.test(value)) {
            problems.push(COPY.numeric || "This password is entirely numeric.");
        }
        var lowered = value.toLowerCase();
        var tooPersonal = personalStrings().some(function (personal) {
            var other = personal.toLowerCase();
            return lowered === other || lowered.indexOf(other) > -1;
        });
        if (tooPersonal) {
            problems.push(COPY.tooSimilar ||
                "The password is too similar to the other information you entered.");
        }
        return problems;
    }

    function validate(moveFocus) {
        clearErrors();
        var firstBad = null;
        if (password && password.value) {
            var problems = passwordProblems(password.value);
            if (problems.length) {
                showErrors(password, problems);
                firstBad = password;
            }
        }
        if (confirmation && confirmation.value && password && confirmation.value !== password.value) {
            showErrors(confirmation, [
                COPY.mismatch || "You must type the same password each time."
            ]);
            firstBad = firstBad || confirmation;
        }
        if (firstBad) {
            // Only when the person tried to submit -- re-checking as they
            // type must not yank the cursor out of the field they are in.
            if (moveFocus) {
                firstBad.focus();
            }
            return false;
        }
        return true;
    }

    form.addEventListener("submit", function (event) {
        if (!validate(true)) {
            // Before the page loader's own submit handler runs: it checks
            // defaultPrevented before showing the overlay.
            event.preventDefault();
        }
    });

    // Once a message is on screen, keep it honest while the field is edited
    // rather than leaving a stale complaint under a password already fixed.
    [password, confirmation].forEach(function (field) {
        if (!field) {
            return;
        }
        field.addEventListener("input", function () {
            if (form.querySelector(".tp-client-error")) {
                validate(false);
            }
        });
    });
})();
