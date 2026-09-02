/* Mobile topbar nav -- present on every page (loaded directly from masterpage.html,
 * matching the existing plain-script convention used by agent-drawer.js/protein-detail.js).
 *
 * bundle.js still `import 'bootstrap'`s the real jQuery Collapse/Dropdown plugins (other
 * pages use jQuery for DataTables etc.), which auto-bind to any data-toggle="collapse"/
 * "dropdown" element on the page. This hamburger button and the mobile user-dropdown
 * deliberately omit that attribute in masterpage.html so this script is the ONLY thing
 * wired to them -- leaving it in let Bootstrap's real plugin also react to the same click
 * and immediately reverse whatever this script had just done ("menu opens then instantly
 * closes"). Only matched via data-target/the #user_dropdown id here, not data-toggle.
 * Bootstrap's CSS already defines `.collapse.show { display: block }` /
 * `.dropdown-menu.show { display: block }`; this script only has to flip that class, not
 * reimplement Bootstrap's JS behavior.
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
