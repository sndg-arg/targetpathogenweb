// File picker: wraps every <input type="file" class="tp-file-input"> in a
// "Choose file" button + file name, so the text is the site's (English)
// rather than the browser's own, which comes in the browser's language and
// gets cut off ("Sin …dos"). The input stays in place (hidden, still
// focusable and submitted with its form); without JS it shows natively.
(function () {
    function fileLabel(input) {
        var files = input.files;
        if (!files || !files.length) return "No file chosen";
        if (files.length === 1) return files[0].name;
        return files.length + " files";
    }

    function enhance(input) {
        if (input.closest(".tp-file")) return;
        var wrap = document.createElement("label");
        wrap.className = "tp-file";
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        var button = document.createElement("span");
        button.className = "btn tp-btn tp-btn--sm tp-file-button";
        button.setAttribute("aria-hidden", "true");
        button.textContent = input.multiple ? "Choose files" : "Choose file";
        wrap.appendChild(button);

        var name = document.createElement("span");
        name.className = "tp-file-name";
        wrap.appendChild(name);

        function sync() {
            name.textContent = fileLabel(input);
            name.title = name.textContent;
            wrap.classList.toggle("has-file", !!(input.files && input.files.length));
            wrap.classList.toggle("is-disabled", input.disabled);
        }
        input.addEventListener("change", sync);
        // A form reset clears the input without a change event.
        if (input.form) {
            input.form.addEventListener("reset", function () { setTimeout(sync, 0); });
        }
        sync();
    }

    function init(root) {
        (root || document).querySelectorAll("input[type=file].tp-file-input").forEach(enhance);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { init(); });
    } else {
        init();
    }
    window.tpFilePicker = { init: init };
})();
