// Active-section highlighting for the shared .quick-nav section menu
// (ui-system.css). Pages with their own richer quick-nav script (genome
// overview, protein) don't load this one.
(function () {
    "use strict";

    function init(nav) {
        var targets = Array.from(nav.querySelectorAll('.quick-nav-link[href^="#"]'))
            .map(function (link) {
                var section = document.getElementById(link.getAttribute("href").slice(1));
                return section ? { link: link, section: section } : null;
            })
            .filter(Boolean);
        if (!targets.length) return;

        // A section near the end of the page may never scroll up to the nav;
        // when that's the one the user clicked, keep it highlighted.
        var clicked = null;

        function setActive(active) {
            targets.forEach(function (t) {
                var on = t === active;
                t.link.classList.toggle("is-active", on);
                if (on) t.link.setAttribute("aria-current", "true");
                else t.link.removeAttribute("aria-current");
            });
            if (active && nav.scrollWidth > nav.clientWidth) {
                var l = active.link;
                if (l.offsetLeft < nav.scrollLeft || l.offsetLeft + l.offsetWidth > nav.scrollLeft + nav.clientWidth) {
                    nav.scrollLeft = l.offsetLeft - 18;
                }
            }
        }

        function update() {
            var atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
            if (atBottom && clicked && clicked.section.getBoundingClientRect().top < window.innerHeight) {
                setActive(clicked);
                return;
            }
            if (atBottom) {
                setActive(targets[targets.length - 1]);
                return;
            }
            var line = nav.getBoundingClientRect().bottom + 30;
            var active = targets[0];
            targets.forEach(function (t) {
                if (t.section.getBoundingClientRect().top <= line) active = t;
            });
            setActive(active);
        }

        targets.forEach(function (t) {
            t.link.addEventListener("click", function () {
                clicked = t;
                setTimeout(update, 150);
            });
        });
        window.addEventListener("wheel", function () { clicked = null; }, { passive: true });
        window.addEventListener("touchmove", function () { clicked = null; }, { passive: true });
        window.addEventListener("scroll", update, { passive: true });
        window.addEventListener("resize", update);
        update();
    }

    document.querySelectorAll(".quick-nav[data-quick-nav]").forEach(init);
})();
