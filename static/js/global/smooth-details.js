/* Smooth open/close for native <details>/<summary> disclosures -- present on
 * every page (loaded directly from masterpage.html, matching the existing
 * plain-script convention used by agent-drawer.js/nav-toggle.js).
 *
 * Opt-in via the .js-smooth-details class rather than wiring every <details>
 * automatically, so this only ever touches disclosures that were actually
 * reviewed for it -- not any future/unreviewed one added elsewhere.
 *
 * Intercepts the <summary> click and animates the <details> element's own
 * height (via the Web Animations API) between its measured collapsed and
 * expanded values, only flipping the real `open` attribute at the right
 * moment: immediately when opening (so content is rendered/measurable),
 * deferred to the animation's end when closing (so content stays visible,
 * clipped only by the shrinking box, instead of vanishing instantly).
 *
 * The chevron rotation most of these disclosures use is keyed off `[open]`
 * in CSS, but `open` deliberately stays true for the whole close animation --
 * left alone, the chevron would stay rotated "open" and snap back only on
 * the last frame. The `is-open-visual` class is toggled in sync with when
 * the *animation* starts instead, and each page's CSS keys the chevron off
 * `[open], .is-open-visual` together, so it rotates in sync with the motion
 * regardless of which one is driving a given toggle (this script's animated
 * clicks, or any pre-existing instant/programmatic `.open = ...` elsewhere).
 */
(function () {
    "use strict";

    var SELECTOR = ".js-smooth-details";
    var DURATION = 200;
    var EASING = "ease-out";
    var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function wireSmoothDetails(details) {
        var summary = details.querySelector(":scope > summary");
        if (!summary) return;
        var animation = null;

        function finish(isOpen) {
            details.open = isOpen;
            details.style.height = "";
            details.style.overflow = "";
            details.classList.toggle("is-open-visual", isOpen);
            animation = null;
        }

        function expand() {
            if (animation) animation.cancel();
            var startHeight = details.offsetHeight + "px";
            details.style.overflow = "hidden";
            details.classList.add("is-open-visual");
            details.open = true;
            var endHeight = details.offsetHeight + "px";
            animation = details.animate(
                { height: [startHeight, endHeight] },
                { duration: DURATION, easing: EASING }
            );
            animation.onfinish = function () { finish(true); };
        }

        function collapse() {
            if (animation) animation.cancel();
            var startHeight = details.offsetHeight + "px";
            details.style.overflow = "hidden";
            details.classList.remove("is-open-visual");
            details.open = false;
            var endHeight = details.offsetHeight + "px";
            details.open = true;
            animation = details.animate(
                { height: [startHeight, endHeight] },
                { duration: DURATION, easing: EASING }
            );
            animation.onfinish = function () { finish(false); };
        }

        summary.addEventListener("click", function (e) {
            e.preventDefault();
            if (details.open) {
                collapse();
            } else {
                expand();
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        if (prefersReducedMotion) return;
        document.querySelectorAll(SELECTOR).forEach(wireSmoothDetails);
    });
}());
