// Signup: the Institution field only makes sense for someone asking for a
// collaborator role, so it stays hidden until that box is ticked. The form
// validates it server-side under the same condition (tpweb/forms/UserForms.py),
// and a rejected submission comes back with the box still ticked, so the field
// is visible again along with its error.
(function () {
    "use strict";

    var checkbox = document.getElementById("id_wants_collaborator_access");
    var input = document.getElementById("id_collaborator_institution");
    if (!checkbox || !input) {
        return;
    }
    // crispy-forms (bootstrap4) wraps every field in a .form-group; fall back
    // to the input's own parent if that ever changes, so the label and help
    // text never end up visible on their own.
    var group = input.closest(".form-group") || input.parentNode;

    function sync() {
        group.classList.toggle("is-hidden", !checkbox.checked);
        // Required only while it is on screen: the browser refuses to
        // submit a form holding a required field it cannot focus, which is
        // exactly what a hidden one is.
        input.required = checkbox.checked;
    }

    checkbox.addEventListener("change", sync);
    sync();
})();
