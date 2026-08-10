/* Mobile topbar nav -- present on every page (loaded directly from masterpage.html,
 * matching the existing plain-script convention used by agent-drawer.js/protein-detail.js).
 *
 * The topbar's hamburger + user dropdown use Bootstrap 4's data-toggle="collapse"/"dropdown"
 * markup, but only Bootstrap's CSS is loaded (no bundle JS, no Popper, no jQuery anywhere in
 * this codebase) -- so those buttons need their own minimal toggle. Bootstrap's CSS already
 * defines `.collapse.show { display: block }` / `.dropdown-menu.show { display: block }`; this
 * script only has to flip that class, not reimplement Bootstrap's JS behavior.
 */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var toggler = document.querySelector(".navbar-toggler[data-target='#navbarCollapse']");
        var collapse = document.getElementById("navbarCollapse");

        if (toggler && collapse) {
            toggler.addEventListener("click", function () {
                var isOpen = collapse.classList.toggle("show");
                toggler.setAttribute("aria-expanded", isOpen ? "true" : "false");
            });

            collapse.querySelectorAll(".nav-link").forEach(function (link) {
                link.addEventListener("click", function () {
                    collapse.classList.remove("show");
                    toggler.setAttribute("aria-expanded", "false");
                });
            });

            document.addEventListener("click", function (event) {
                if (!collapse.classList.contains("show")) return;
                if (collapse.contains(event.target) || toggler.contains(event.target)) return;
                collapse.classList.remove("show");
                toggler.setAttribute("aria-expanded", "false");
            });
        }

        var dropdownToggle = document.querySelector("#user_dropdown > .dropdown-toggle");
        var dropdownMenu = document.getElementById("user_dropdown_menu");

        if (dropdownToggle && dropdownMenu) {
            dropdownToggle.addEventListener("click", function (event) {
                event.preventDefault();
                var isOpen = dropdownMenu.classList.toggle("show");
                dropdownToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
            });

            document.addEventListener("click", function (event) {
                if (!dropdownMenu.classList.contains("show")) return;
                if (dropdownMenu.contains(event.target) || dropdownToggle.contains(event.target)) return;
                dropdownMenu.classList.remove("show");
                dropdownToggle.setAttribute("aria-expanded", "false");
            });

            document.addEventListener("keydown", function (event) {
                if (event.key === "Escape" && dropdownMenu.classList.contains("show")) {
                    dropdownMenu.classList.remove("show");
                    dropdownToggle.setAttribute("aria-expanded", "false");
                }
            });
        }
    });
}());
